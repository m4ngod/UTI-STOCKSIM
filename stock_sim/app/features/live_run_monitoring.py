"""Live Run Monitoring Adapter over the typed V1 application read model."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import RLock, Timer, current_thread

from app.event_bridge import (
    EventBridge,
    EventBridgeBatch,
    EventBridgeConnectionPhase,
    EventBridgeConnectionState,
    EventBridgeTerminalPhase,
)

from .run_monitoring import (
    AlertSeverity,
    CancelDiagnosticTask,
    Completeness,
    DiagnosticCommandRejectionReason,
    DiagnosticTaskCapabilities,
    DiagnosticTaskCommandResult,
    DiagnosticTaskId,
    Freshness,
    PauseDiagnosticTask,
    ResumeDiagnosticTask,
    RunLifecyclePhase,
    RunMonitoringContext,
    RunMonitoringData,
    RunMonitoringObserver,
    RunMonitoringPresentationState,
    RunMonitoringSource,
    RunMonitoringViewState,
    SourceGenerationId,
    SourceKind,
    StructuredFeatureError,
    Subscription,
    ViewPhase,
    _RevisionGuardedSubscription,
)
from .strategy_diagnostics_v1_read_model import (
    APPLICATION_READ_MODEL_INTERFACE_VERSION,
    ApplicationReadAvailability,
    ApplicationReadError,
    SourceRevisionToken,
    StrategyDiagnosticsV1ApplicationReadModel,
    V1JourneySelector,
)
from .versioning import (
    RUN_MONITORING_INTERFACE_VERSION,
    FeatureInterfaceVersion,
)


class _RefreshResult(str, Enum):
    ABORTED = "aborted"
    COMMITTED_NON_TERMINAL = "committed_non_terminal"
    COMMITTED_TERMINAL = "committed_terminal"
    RETRY_CAS = "retry_cas"


@dataclass(frozen=True, slots=True)
class _AuthoritativeRunRead:
    state: RunMonitoringViewState
    source_token: SourceRevisionToken | None


class LiveRunMonitoringAdapter:
    """Typed, batched live seam for an already-existing Strategy Run."""

    _TERMINAL_CONFIRMATION_INTERVAL_SECONDS = 0.02

    def __init__(
        self,
        *,
        application_read_model: StrategyDiagnosticsV1ApplicationReadModel,
        event_bridge: EventBridge,
        journey_selector: V1JourneySelector | None = None,
        clock: Callable[[], datetime] | None = None,
        freshness_threshold: timedelta = timedelta(seconds=5),
        executor: Executor | None = None,
    ) -> None:
        self._application_read_model = application_read_model
        self._event_bridge = event_bridge
        self._journey_selector = journey_selector
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._freshness_threshold = freshness_threshold
        self._owns_executor = executor is None
        self._executor_thread_prefix = (
            f"run-monitoring-{id(self):x}" if self._owns_executor else None
        )
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=(
                self._executor_thread_prefix or "run-monitoring-external"
            ),
        )
        self._states: dict[RunMonitoringContext, RunMonitoringViewState] = {}
        self._source_tokens: dict[
            RunMonitoringContext,
            SourceRevisionToken,
        ] = {}
        self._subscriptions: dict[
            int,
            tuple[
                RunMonitoringContext,
                RunMonitoringObserver,
                _RevisionGuardedSubscription,
            ],
        ] = {}
        self._next_subscription_id = 1
        connection = event_bridge.connection_state
        self._connection_generation = SourceGenerationId(connection.generation.value)
        self._connection_sequence = connection.sequence.value
        self._connection_phase = connection.phase
        self._pending_refreshes: dict[
            RunMonitoringContext,
            tuple[
                SourceGenerationId,
                EventBridgeTerminalPhase | None,
            ],
        ] = {}
        self._scheduled_refreshes: set[RunMonitoringContext] = set()
        self._terminal_confirmation_timers: dict[
            RunMonitoringContext,
            tuple[SourceGenerationId, Timer],
        ] = {}
        self._closed = False
        self._lock = RLock()
        self._dispose_connection_subscription = event_bridge.subscribe_connection_state(
            self._on_connection_state,
            replay_current=True,
        )
        self._dispose_batch_subscription = event_bridge.subscribe_batches(
            self._on_snapshot_batch
        )

    @property
    def interface_version(self) -> FeatureInterfaceVersion:
        return RUN_MONITORING_INTERFACE_VERSION

    def snapshot(
        self,
        context: RunMonitoringContext,
    ) -> RunMonitoringViewState:
        with self._lock:
            self._ensure_open()
            current = self._states.get(context)
            connection_phase = self._connection_phase
            connection_generation = self._connection_generation
        if current is not None:
            aged = self._age_state(current)
            if aged is not current:
                return self._store_and_notify(context, aged)
            return current
        if connection_phase is EventBridgeConnectionPhase.DISCONNECTED:
            observed_at = _aware(self._clock())
            with self._lock:
                self._ensure_open()
                existing = self._states.get(context)
                if existing is not None:
                    return existing
                unavailable = self._connection_view_state(
                    self._empty_state(
                        context,
                        revision=1,
                        observed_at=observed_at,
                    ),
                    connection_phase,
                    revision=1,
                    observed_at=observed_at,
                )
                self._states[context] = unavailable
                return unavailable
        if self._owns_executor:
            return self._start_initial_read(
                context,
                generation=connection_generation,
            )
        authoritative = self._read_state(context, revision=1)
        initial = authoritative.state
        with self._lock:
            self._ensure_open()
            existing = self._states.get(context)
            if existing is not None:
                return existing
            if (
                self._connection_phase is not EventBridgeConnectionPhase.CONNECTED
                or self._connection_generation != connection_generation
            ):
                initial = self._connection_view_state(
                    initial,
                    self._connection_phase,
                    revision=1,
                )
            self._states[context] = initial
            if authoritative.source_token is not None:
                self._source_tokens[context] = authoritative.source_token
            return initial

    def _start_initial_read(
        self,
        context: RunMonitoringContext,
        *,
        generation: SourceGenerationId,
    ) -> RunMonitoringViewState:
        observed_at = _aware(self._clock())
        should_schedule = False
        with self._lock:
            self._ensure_open()
            existing = self._states.get(context)
            if existing is not None:
                return existing
            if (
                self._connection_phase is not EventBridgeConnectionPhase.CONNECTED
                or generation != self._connection_generation
            ):
                unavailable = self._connection_view_state(
                    self._empty_state(
                        context,
                        revision=1,
                        observed_at=observed_at,
                    ),
                    self._connection_phase,
                    revision=1,
                    observed_at=observed_at,
                )
                self._states[context] = unavailable
                return unavailable
            loading = self._loading_state(
                context,
                revision=1,
                observed_at=observed_at,
            )
            self._states[context] = loading
            self._pending_refreshes[context] = (generation, None)
            if context not in self._scheduled_refreshes:
                self._scheduled_refreshes.add(context)
                should_schedule = True
        if should_schedule:
            try:
                self._executor.submit(self._drain_refreshes, context)
            except RuntimeError:
                with self._lock:
                    if not self._closed:
                        self._scheduled_refreshes.discard(context)
                        self._pending_refreshes.pop(context, None)
                        raise
        return loading

    def subscribe(
        self,
        context: RunMonitoringContext,
        observer: RunMonitoringObserver,
    ) -> Subscription:
        state = self.snapshot(context)
        with self._lock:
            self._ensure_open()
            subscription_id = self._next_subscription_id
            self._next_subscription_id += 1
            subscription = _RevisionGuardedSubscription(
                lambda: self._remove_subscription(subscription_id)
            )
            self._subscriptions[subscription_id] = (
                context,
                observer,
                subscription,
            )
            state = self._states.get(context, state)
        subscription.deliver(observer, state)
        return subscription

    def pause_diagnostic_task(
        self,
        command: PauseDiagnosticTask,
    ) -> DiagnosticTaskCommandResult:
        return self._apply_command(
            action="pause",
            target_id=command.target_id,
            expected_revision=command.expected_revision,
        )

    def resume_diagnostic_task(
        self,
        command: ResumeDiagnosticTask,
    ) -> DiagnosticTaskCommandResult:
        return self._apply_command(
            action="resume",
            target_id=command.target_id,
            expected_revision=command.expected_revision,
        )

    def cancel_diagnostic_task(
        self,
        command: CancelDiagnosticTask,
    ) -> DiagnosticTaskCommandResult:
        return self._apply_command(
            action="cancel",
            target_id=command.target_id,
            expected_revision=command.expected_revision,
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            subscriptions = tuple(item[2] for item in self._subscriptions.values())
            self._subscriptions.clear()
            dispose_batch = self._dispose_batch_subscription
            self._dispose_batch_subscription = lambda: None
            dispose_connection = self._dispose_connection_subscription
            self._dispose_connection_subscription = lambda: None
            self._pending_refreshes.clear()
            self._scheduled_refreshes.clear()
            timers = tuple(
                timer for _, timer in self._terminal_confirmation_timers.values()
            )
            self._terminal_confirmation_timers.clear()
        dispose_batch()
        dispose_connection()
        for timer in timers:
            timer.cancel()
        for subscription in subscriptions:
            subscription.mark_disposed()
        if self._owns_executor:
            called_from_owned_worker = bool(
                self._executor_thread_prefix
                and current_thread().name.startswith(self._executor_thread_prefix)
            )
            self._executor.shutdown(
                wait=not called_from_owned_worker,
                cancel_futures=True,
            )

    def _on_snapshot_batch(
        self,
        batch: EventBridgeBatch,
    ) -> None:
        generation = SourceGenerationId(batch.generation.value)
        batch_run_ids = {
            str(item.get("run_id") or "").strip()
            for item in batch.snapshots
            if str(item.get("run_id") or "").strip()
        }
        with self._lock:
            if (
                self._closed
                or generation != self._connection_generation
                or self._connection_phase is not EventBridgeConnectionPhase.CONNECTED
            ):
                return
            contexts = tuple(self._states)
            to_schedule = []
            for context in contexts:
                selection = context.selection
                if (
                    selection is not None
                    and selection.run_id is not None
                    and batch_run_ids
                    and selection.run_id.value not in batch_run_ids
                ):
                    continue
                if selection is None or selection.run_id is None:
                    continue
                run_id = selection.run_id.value
                previous_pending = self._pending_refreshes.get(context)
                terminal_phase = batch.terminal_phase_for(run_id) or (
                    previous_pending[1]
                    if previous_pending is not None
                    and previous_pending[0] == generation
                    else None
                )
                self._pending_refreshes[context] = (
                    generation,
                    terminal_phase,
                )
                if context not in self._scheduled_refreshes:
                    self._scheduled_refreshes.add(context)
                    to_schedule.append(context)
        for context in to_schedule:
            self._executor.submit(self._drain_refreshes, context)

    def _drain_refreshes(self, context: RunMonitoringContext) -> None:
        while True:
            with self._lock:
                if self._closed:
                    self._scheduled_refreshes.discard(context)
                    self._pending_refreshes.pop(context, None)
                    return
                pending = self._pending_refreshes.pop(context, None)
                if pending is None:
                    self._scheduled_refreshes.discard(context)
                    return
            generation, terminal_phase = pending
            result = self._refresh_context(
                context,
                generation=generation,
            )
            if result is _RefreshResult.RETRY_CAS:
                with self._lock:
                    if (
                        not self._closed
                        and generation == self._connection_generation
                        and self._connection_phase
                        is EventBridgeConnectionPhase.CONNECTED
                    ):
                        existing = self._pending_refreshes.get(context)
                        self._pending_refreshes[context] = (
                            generation,
                            terminal_phase
                            or (
                                existing[1]
                                if existing is not None and existing[0] == generation
                                else None
                            ),
                        )
            elif result is _RefreshResult.COMMITTED_TERMINAL:
                self._cancel_terminal_confirmation(context)
            elif (
                terminal_phase is not None
                and result is _RefreshResult.COMMITTED_NON_TERMINAL
            ):
                self._schedule_terminal_confirmation(
                    context,
                    generation,
                )
            with self._lock:
                if context not in self._pending_refreshes:
                    self._scheduled_refreshes.discard(context)
                    return

    def _on_connection_state(
        self,
        connection: EventBridgeConnectionState,
    ) -> None:
        generation = SourceGenerationId(connection.generation.value)
        with self._lock:
            if self._closed:
                return
            if connection.sequence.value <= self._connection_sequence:
                return
            self._connection_sequence = connection.sequence.value
            self._connection_generation = generation
            self._connection_phase = connection.phase
            contexts = tuple(self._states)
            timers = tuple(
                timer for _, timer in self._terminal_confirmation_timers.values()
            )
            self._terminal_confirmation_timers.clear()
        for timer in timers:
            timer.cancel()
        for context in contexts:
            self._publish_connection_state(
                context,
                connection.phase,
                generation,
                connection.sequence.value,
            )

    def _publish_connection_state(
        self,
        context: RunMonitoringContext,
        phase: EventBridgeConnectionPhase,
        generation: SourceGenerationId,
        connection_sequence: int,
    ) -> None:
        with self._lock:
            if (
                self._closed
                or generation != self._connection_generation
                or phase is not self._connection_phase
                or connection_sequence != self._connection_sequence
            ):
                return
            previous = self._states.get(context)
            if previous is None:
                return
            selection = context.selection
            if phase is EventBridgeConnectionPhase.CONNECTED and (
                selection is None or selection.run_id is None
            ):
                state = self._empty_state(
                    context,
                    revision=previous.revision + 1,
                    observed_at=_aware(self._clock()),
                )
            else:
                state = self._connection_view_state(previous, phase)
            self._states[context] = state
            deliveries = self._deliveries_for(context)
        for observer, subscription in deliveries:
            subscription.deliver(observer, state)

    def _connection_view_state(
        self,
        previous: RunMonitoringViewState,
        phase: EventBridgeConnectionPhase,
        *,
        revision: int | None = None,
        observed_at: datetime | None = None,
    ) -> RunMonitoringViewState:
        current_time = observed_at or _aware(self._clock())
        data = previous.last_reliable_data
        disconnected = phase is EventBridgeConnectionPhase.DISCONNECTED
        return replace(
            previous,
            revision=revision or previous.revision + 1,
            observed_at=current_time,
            freshness=(Freshness.DISCONNECTED if disconnected else Freshness.STALE),
            age=(
                max(
                    current_time - data.wall_time.observed_at,
                    timedelta(0),
                )
                if data is not None
                else timedelta(0)
            ),
            source=self._source(),
            phase=ViewPhase.DEGRADED if data is not None else ViewPhase.FAILED,
            presentation=(
                previous.presentation
                if data is not None
                else RunMonitoringPresentationState.DISCONNECTED
            ),
            error=StructuredFeatureError(
                code=(
                    "run_monitoring_source_disconnected"
                    if disconnected
                    else "run_monitoring_source_reconnecting"
                ),
                message=(
                    "Run Monitoring data is disconnected; showing the "
                    "last reliable state."
                    if disconnected
                    else "Run Monitoring reconnected and is awaiting "
                    "a current revision."
                ),
                retryable=True,
            ),
            completeness=(
                previous.completeness if data is not None else Completeness.UNKNOWN
            ),
        )

    def _refresh_context(
        self,
        context: RunMonitoringContext,
        *,
        generation: SourceGenerationId | None = None,
    ) -> _RefreshResult:
        with self._lock:
            target_generation = generation or self._connection_generation
            target_connection_sequence = self._connection_sequence
            if (
                self._closed
                or target_generation != self._connection_generation
                or self._connection_phase is not EventBridgeConnectionPhase.CONNECTED
            ):
                return _RefreshResult.ABORTED
            previous = self._states.get(context)
            previous_token = self._source_tokens.get(context)
        if previous is None:
            return _RefreshResult.ABORTED
        authoritative = self._read_state(
            context,
            revision=previous.revision + 1,
        )
        state = authoritative.state
        source_token_to_store = authoritative.source_token
        terminal_conflict = _terminal_conflict(
            previous,
            state,
            previous_token,
            authoritative.source_token,
        )
        if terminal_conflict is not None:
            state = terminal_conflict
            source_token_to_store = previous_token
        elif (
            authoritative.source_token is not None
            and authoritative.source_token == previous_token
            and _same_authoritative_presentation(previous, state)
        ):
            data = previous.last_reliable_data
            if data is not None and data.terminal_outcome is not None:
                return _RefreshResult.COMMITTED_TERMINAL
            return _RefreshResult.COMMITTED_NON_TERMINAL
        if (
            state.last_reliable_data is None
            and previous.last_reliable_data is not None
            and (state.error is None or state.error.retryable)
        ):
            age = max(
                state.observed_at - previous.last_reliable_data.wall_time.observed_at,
                timedelta(0),
            )
            state = replace(
                state,
                freshness=Freshness.STALE,
                age=age,
                phase=ViewPhase.DEGRADED,
                presentation=previous.presentation,
                last_reliable_data=previous.last_reliable_data,
                error=state.error
                or StructuredFeatureError(
                    code="run_monitoring_source_unavailable",
                    message=(
                        "The selected run is temporarily unavailable; "
                        "showing the last reliable state."
                    ),
                    retryable=True,
                ),
                completeness=previous.completeness,
            )
            source_token_to_store = previous_token
        with self._lock:
            if (
                self._closed
                or target_generation != self._connection_generation
                or target_connection_sequence != self._connection_sequence
                or self._connection_phase is not EventBridgeConnectionPhase.CONNECTED
            ):
                return _RefreshResult.ABORTED
        stored = self._store_and_notify(
            context,
            state,
            expected_revision=previous.revision,
            expected_connection_sequence=target_connection_sequence,
            source_token=source_token_to_store,
        )
        data = stored.last_reliable_data
        if data is not None and data.terminal_outcome is not None:
            return _RefreshResult.COMMITTED_TERMINAL
        if stored is state:
            return _RefreshResult.COMMITTED_NON_TERMINAL
        with self._lock:
            if (
                self._closed
                or target_generation != self._connection_generation
                or target_connection_sequence != self._connection_sequence
                or self._connection_phase is not EventBridgeConnectionPhase.CONNECTED
            ):
                return _RefreshResult.ABORTED
        return _RefreshResult.RETRY_CAS

    def _schedule_terminal_confirmation(
        self,
        context: RunMonitoringContext,
        generation: SourceGenerationId,
    ) -> None:
        with self._lock:
            if (
                self._closed
                or generation != self._connection_generation
                or self._connection_phase is not EventBridgeConnectionPhase.CONNECTED
                or context in self._terminal_confirmation_timers
            ):
                return
            timer: Timer

            def _fire() -> None:
                self._submit_terminal_confirmation(
                    context,
                    generation,
                    timer,
                )

            timer = Timer(
                self._TERMINAL_CONFIRMATION_INTERVAL_SECONDS,
                _fire,
            )
            timer.daemon = True
            self._terminal_confirmation_timers[context] = (
                generation,
                timer,
            )
        timer.start()

    def _submit_terminal_confirmation(
        self,
        context: RunMonitoringContext,
        generation: SourceGenerationId,
        timer: Timer,
    ) -> None:
        with self._lock:
            current = self._terminal_confirmation_timers.get(context)
            if current is None or current[0] != generation or current[1] is not timer:
                return
            self._terminal_confirmation_timers.pop(context, None)
            if (
                self._closed
                or generation != self._connection_generation
                or self._connection_phase is not EventBridgeConnectionPhase.CONNECTED
            ):
                return
            try:
                self._executor.submit(
                    self._terminal_confirmation_attempt,
                    context,
                    generation,
                )
            except RuntimeError:
                if not self._closed:
                    raise

    def _terminal_confirmation_attempt(
        self,
        context: RunMonitoringContext,
        generation: SourceGenerationId,
    ) -> None:
        result = self._refresh_context(
            context,
            generation=generation,
        )
        if result is _RefreshResult.COMMITTED_TERMINAL:
            self._cancel_terminal_confirmation(context)
            return
        if result in {
            _RefreshResult.COMMITTED_NON_TERMINAL,
            _RefreshResult.RETRY_CAS,
        }:
            self._schedule_terminal_confirmation(context, generation)

    def _cancel_terminal_confirmation(
        self,
        context: RunMonitoringContext,
    ) -> None:
        with self._lock:
            current = self._terminal_confirmation_timers.pop(
                context,
                None,
            )
        if current is not None:
            current[1].cancel()

    def _read_state(
        self,
        context: RunMonitoringContext,
        *,
        revision: int,
    ) -> _AuthoritativeRunRead:
        observed_at = _aware(self._clock())
        if context.selection is None or context.selection.run_id is None:
            return _AuthoritativeRunRead(
                state=self._empty_state(
                    context,
                    revision=revision,
                    observed_at=observed_at,
                ),
                source_token=None,
            )
        if not APPLICATION_READ_MODEL_INTERFACE_VERSION.accepts(
            self._application_read_model.interface_version
        ):
            return _AuthoritativeRunRead(
                state=self._failed_state(
                    context,
                    revision=revision,
                    observed_at=observed_at,
                    error=StructuredFeatureError(
                        code="strategy_diagnostics_contract_incompatible",
                        message=(
                            "The Strategy Diagnostics read-model version is "
                            "incompatible."
                        ),
                        retryable=False,
                    ),
                ),
                source_token=None,
            )
        selection = context.selection
        configured_selector = self._journey_selector
        selector = (
            configured_selector
            if configured_selector is not None
            and configured_selector.campaign_id == selection.campaign_id
            and configured_selector.run_id == selection.run_id
            else V1JourneySelector(
                campaign_id=selection.campaign_id,
                run_id=selection.run_id,
            )
        )
        try:
            journey_result = self._application_read_model.resolve_journey(selector)
            if journey_result.value is None:
                return _AuthoritativeRunRead(
                    state=self._failed_state(
                        context,
                        revision=revision,
                        observed_at=observed_at,
                        error=_structured_application_error(journey_result.error),
                    ),
                    source_token=journey_result.source_token,
                )
            if journey_result.value.run_context.selection != selection:
                return _AuthoritativeRunRead(
                    state=self._failed_state(
                        context,
                        revision=revision,
                        observed_at=observed_at,
                        error=StructuredFeatureError(
                            code="strategy_diagnostics_identity_mismatch",
                            message=(
                                "The resolved Strategy Run identity does not "
                                "match the selected Journey."
                            ),
                            retryable=False,
                        ),
                    ),
                    source_token=journey_result.source_token,
                )
            run_result = self._application_read_model.read_run(journey_result.value)
        except Exception:  # noqa: BLE001 - adapters must fail closed at the seam
            return _AuthoritativeRunRead(
                state=self._failed_state(
                    context,
                    revision=revision,
                    observed_at=observed_at,
                    error=StructuredFeatureError(
                        code="strategy_diagnostics_read_failed",
                        message=("Run Monitoring data is temporarily unavailable."),
                        retryable=True,
                    ),
                ),
                source_token=None,
            )
        if run_result.value is None:
            return _AuthoritativeRunRead(
                state=self._failed_state(
                    context,
                    revision=revision,
                    observed_at=observed_at,
                    error=_structured_application_error(run_result.error),
                ),
                source_token=run_result.source_token,
            )
        data = run_result.value
        if data.selection != selection:
            return _AuthoritativeRunRead(
                state=self._failed_state(
                    context,
                    revision=revision,
                    observed_at=observed_at,
                    error=StructuredFeatureError(
                        code="strategy_diagnostics_identity_mismatch",
                        message=(
                            "The authoritative Strategy Run projection does "
                            "not match the selected Journey."
                        ),
                        retryable=False,
                    ),
                ),
                source_token=run_result.source_token,
            )
        data = replace(
            data,
            task_id=None,
            capabilities=DiagnosticTaskCapabilities(False, False, False),
            active_task=None,
        )
        source_observed_at = run_result.source_observed_at or data.wall_time.observed_at
        age = max(
            observed_at - source_observed_at,
            timedelta(0),
        )
        stale = age > self._freshness_threshold
        terminal = data.terminal_outcome is not None
        failed = data.lifecycle is RunLifecyclePhase.FAILED
        partial = run_result.availability in {
            ApplicationReadAvailability.PENDING,
            ApplicationReadAvailability.PARTIAL,
        }
        error = (
            _structured_application_error(run_result.error)
            if run_result.error is not None
            else StructuredFeatureError(
                code="diagnostic_run_failed",
                message=next(
                    (
                        alert.message
                        for alert in data.alerts
                        if alert.severity is AlertSeverity.ERROR
                    ),
                    "The diagnostic run failed.",
                ),
                retryable=False,
            )
            if failed
            else StructuredFeatureError(
                code="strategy_diagnostics_source_stale",
                message=("Run Monitoring data is older than its freshness threshold."),
                retryable=True,
            )
            if stale
            else None
        )
        state = RunMonitoringViewState(
            interface_version=self.interface_version,
            revision=revision,
            observed_at=observed_at,
            freshness=Freshness.STALE if stale else Freshness.FRESH,
            age=age,
            freshness_threshold=self._freshness_threshold,
            source=self._source(),
            context=context,
            phase=(
                ViewPhase.FAILED
                if failed
                else ViewPhase.DEGRADED
                if stale or partial
                else ViewPhase.READY
            ),
            presentation=(
                RunMonitoringPresentationState.TERMINAL
                if terminal
                else RunMonitoringPresentationState.ACTIVE
            ),
            last_reliable_data=data,
            error=error,
            completeness=(
                Completeness.PARTIAL if partial else _data_completeness(data)
            ),
        )
        return _AuthoritativeRunRead(
            state=state,
            source_token=run_result.source_token,
        )

    def _apply_command(
        self,
        *,
        action: str,
        target_id: DiagnosticTaskId,
        expected_revision: int,
    ) -> DiagnosticTaskCommandResult:
        del action, target_id, expected_revision
        with self._lock:
            self._ensure_open()
        return _rejected(
            DiagnosticCommandRejectionReason.UNAVAILABLE_CAPABILITY,
            "V1 Diagnostic Task controls are unavailable in this read-only slice.",
        )

    def _empty_state(
        self,
        context: RunMonitoringContext,
        *,
        revision: int,
        observed_at: datetime,
    ) -> RunMonitoringViewState:
        return RunMonitoringViewState(
            interface_version=self.interface_version,
            revision=revision,
            observed_at=observed_at,
            freshness=Freshness.FRESH,
            age=timedelta(0),
            freshness_threshold=self._freshness_threshold,
            source=self._source(),
            context=context,
            phase=ViewPhase.READY,
            presentation=RunMonitoringPresentationState.EMPTY,
            last_reliable_data=None,
            error=None,
            completeness=Completeness.EMPTY,
        )

    def _loading_state(
        self,
        context: RunMonitoringContext,
        *,
        revision: int,
        observed_at: datetime,
    ) -> RunMonitoringViewState:
        return RunMonitoringViewState(
            interface_version=self.interface_version,
            revision=revision,
            observed_at=observed_at,
            freshness=Freshness.AWAITING_FIRST_STATE,
            age=timedelta(0),
            freshness_threshold=self._freshness_threshold,
            source=self._source(),
            context=context,
            phase=ViewPhase.LOADING,
            presentation=RunMonitoringPresentationState.LOADING,
            last_reliable_data=None,
            error=None,
            completeness=Completeness.UNKNOWN,
        )

    def _failed_state(
        self,
        context: RunMonitoringContext,
        *,
        revision: int,
        observed_at: datetime,
        error: StructuredFeatureError,
    ) -> RunMonitoringViewState:
        return RunMonitoringViewState(
            interface_version=self.interface_version,
            revision=revision,
            observed_at=observed_at,
            freshness=Freshness.DISCONNECTED,
            age=timedelta(0),
            freshness_threshold=self._freshness_threshold,
            source=self._source(),
            context=context,
            phase=ViewPhase.FAILED,
            presentation=RunMonitoringPresentationState.DISCONNECTED,
            last_reliable_data=None,
            error=error,
            completeness=Completeness.UNKNOWN,
        )

    def _age_state(
        self,
        state: RunMonitoringViewState,
    ) -> RunMonitoringViewState:
        data = state.last_reliable_data
        if (
            data is None
            or data.terminal_outcome is not None
            or state.freshness is Freshness.DISCONNECTED
        ):
            return state
        observed_at = _aware(self._clock())
        age = max(
            observed_at - data.wall_time.observed_at,
            timedelta(0),
        )
        source_failed = (
            state.freshness is Freshness.STALE
            and state.error is not None
            and state.error.code != "run_monitoring_source_stale"
        )
        if source_failed:
            if observed_at == state.observed_at and age == state.age:
                return state
            return replace(
                state,
                revision=state.revision + 1,
                observed_at=observed_at,
                age=age,
            )
        stale = age > self._freshness_threshold
        freshness = Freshness.STALE if stale else Freshness.FRESH
        if (
            observed_at == state.observed_at
            and age == state.age
            and freshness is state.freshness
        ):
            return state
        return replace(
            state,
            revision=state.revision + 1,
            observed_at=observed_at,
            freshness=freshness,
            age=age,
            phase=ViewPhase.DEGRADED if stale else ViewPhase.READY,
            last_reliable_data=data,
            error=(
                StructuredFeatureError(
                    code="run_monitoring_source_stale",
                    message=(
                        "Run Monitoring data is older than its freshness threshold."
                    ),
                    retryable=True,
                )
                if stale
                else None
            ),
        )

    def _store_and_notify(
        self,
        context: RunMonitoringContext,
        state: RunMonitoringViewState,
        *,
        expected_revision: int | None = None,
        expected_connection_sequence: int | None = None,
        source_token: SourceRevisionToken | None = None,
    ) -> RunMonitoringViewState:
        with self._lock:
            if self._closed:
                return self._states.get(context, state)
            previous = self._states.get(context)
            if (
                expected_connection_sequence is not None
                and expected_connection_sequence != self._connection_sequence
            ):
                return previous or state
            if expected_revision is not None and (
                previous is None or previous.revision != expected_revision
            ):
                return previous or state
            if state.source.generation != self._connection_generation:
                return previous or state
            if (
                state.freshness is Freshness.FRESH
                and self._connection_phase is not EventBridgeConnectionPhase.CONNECTED
            ):
                return previous or state
            if previous is not None and state.revision <= previous.revision:
                return previous
            self._states[context] = state
            if source_token is not None:
                self._source_tokens[context] = source_token
            deliveries = self._deliveries_for(context)
        for observer, subscription in deliveries:
            subscription.deliver(observer, state)
        return state

    def _deliveries_for(
        self,
        context: RunMonitoringContext,
    ) -> tuple[
        tuple[RunMonitoringObserver, _RevisionGuardedSubscription],
        ...,
    ]:
        return tuple(
            (observer, subscription)
            for subscribed_context, observer, subscription in self._subscriptions.values()
            if subscribed_context == context
        )

    def _remove_subscription(self, subscription_id: int) -> None:
        with self._lock:
            self._subscriptions.pop(subscription_id, None)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Run Monitoring Adapter is closed")

    def _source(self) -> RunMonitoringSource:
        return RunMonitoringSource(
            kind=SourceKind.LIVE_RUNTIME,
            identity="strategy-diagnostics-v1-application",
            generation=self._connection_generation,
        )


def _structured_application_error(
    error: ApplicationReadError | None,
) -> StructuredFeatureError:
    if error is None:
        return StructuredFeatureError(
            code="strategy_diagnostics_read_failed",
            message="Run Monitoring data is temporarily unavailable.",
            retryable=True,
        )
    return StructuredFeatureError(
        code=error.code.value,
        message=error.message,
        retryable=error.retryable,
        correlation_id=error.correlation_id,
    )


def _same_authoritative_presentation(
    previous: RunMonitoringViewState,
    candidate: RunMonitoringViewState,
) -> bool:
    return (
        previous.freshness is candidate.freshness
        and previous.phase is candidate.phase
        and previous.presentation is candidate.presentation
        and previous.completeness is candidate.completeness
        and previous.error == candidate.error
    )


def _terminal_conflict(
    previous: RunMonitoringViewState,
    candidate: RunMonitoringViewState,
    previous_token: SourceRevisionToken | None,
    candidate_token: SourceRevisionToken | None,
) -> RunMonitoringViewState | None:
    previous_data = previous.last_reliable_data
    candidate_data = candidate.last_reliable_data
    if previous_data is None or previous_data.terminal_outcome is None:
        return None
    if candidate_data is None:
        return None
    conflict = (
        candidate_data.terminal_outcome is None
        or candidate_data.terminal_outcome != previous_data.terminal_outcome
        or (
            previous_token is not None
            and candidate_token is not None
            and candidate_token != previous_token
        )
        or (
            (previous_token is None or candidate_token is None)
            and candidate_data != previous_data
        )
    )
    if not conflict:
        return None
    return replace(
        candidate,
        phase=ViewPhase.FAILED,
        presentation=RunMonitoringPresentationState.TERMINAL,
        last_reliable_data=previous_data,
        error=StructuredFeatureError(
            code="strategy_diagnostics_integrity_failed",
            message=(
                "The terminal Strategy Run conflicts with its last verified artifact."
            ),
            retryable=False,
        ),
        completeness=previous.completeness,
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _data_completeness(data: RunMonitoringData) -> Completeness:
    required_identities = (
        data.strategy_id,
        data.market_scenario_id,
        data.reproduction_manifest_id,
    )
    return (
        Completeness.COMPLETE
        if all(identity is not None for identity in required_identities)
        else Completeness.PARTIAL
    )


def _rejected(
    reason: DiagnosticCommandRejectionReason,
    message: str,
) -> DiagnosticTaskCommandResult:
    return DiagnosticTaskCommandResult(
        accepted=False,
        message=message,
        rejection_reason=reason,
        task=None,
    )


__all__ = ["LiveRunMonitoringAdapter"]
