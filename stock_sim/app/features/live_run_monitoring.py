"""Live Run Monitoring Adapter over existing runtime Implementations."""

from __future__ import annotations

from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import RLock, Timer, current_thread
from typing import Any, Callable, TypeVar

from app.event_bridge import (
    EventBridge,
    EventBridgeBatch,
    EventBridgeConnectionPhase,
    EventBridgeConnectionState,
    EventBridgeTerminalPhase,
)
from app.runtime_gateway import RuntimeGateway

from .run_monitoring import (
    AlertSeverity,
    CancelDiagnosticTask,
    Completeness,
    DiagnosticCommandRejectionReason,
    DiagnosticTaskCapabilities,
    DiagnosticTaskCommandResult,
    DiagnosticTaskId,
    ExecutionAssumption,
    Freshness,
    MarketScenarioId,
    PauseDiagnosticTask,
    ReadOnlyDiagnosticContext,
    ReproductionManifestId,
    ResumeDiagnosticTask,
    RunAlert,
    RunLifecyclePhase,
    RunMonitoringContext,
    RunMonitoringData,
    RunMonitoringObserver,
    RunMonitoringPresentationState,
    RunMonitoringSource,
    RunMonitoringViewState,
    RunProgress,
    ScenarioSetId,
    SimulationTime,
    SourceGenerationId,
    SourceKind,
    StrategyUnderTestId,
    StructuredFeatureError,
    Subscription,
    TaskHandle,
    TaskHandleId,
    TaskPhase,
    TerminalOutcome,
    ViewPhase,
    WallTime,
    _RevisionGuardedSubscription,
    _diagnostic_task_transition,
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


class LiveRunMonitoringAdapter:
    """Typed, batched live seam for an already-existing Strategy Run."""

    _TERMINAL_CONFIRMATION_INTERVAL_SECONDS = 0.02

    def __init__(
        self,
        *,
        runtime_gateway: RuntimeGateway,
        event_bridge: EventBridge,
        diagnostic_tasks: Any | None = None,
        clock: Callable[[], datetime] | None = None,
        freshness_threshold: timedelta = timedelta(seconds=5),
        executor: Executor | None = None,
    ) -> None:
        self._runtime_gateway = runtime_gateway
        self._event_bridge = event_bridge
        self._diagnostic_tasks = diagnostic_tasks
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._freshness_threshold = freshness_threshold
        self._owns_executor = executor is None
        self._executor_thread_prefix = (
            f"run-monitoring-{id(self):x}"
            if self._owns_executor
            else None
        )
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=(
                self._executor_thread_prefix
                or "run-monitoring-external"
            ),
        )
        self._states: dict[RunMonitoringContext, RunMonitoringViewState] = {}
        self._subscriptions: dict[
            int,
            tuple[
                RunMonitoringContext,
                RunMonitoringObserver,
                _RevisionGuardedSubscription,
            ],
        ] = {}
        self._task_handles: dict[DiagnosticTaskId, TaskHandle] = {}
        self._next_subscription_id = 1
        self._next_task_id = 1
        connection = event_bridge.connection_state
        self._connection_generation = SourceGenerationId(
            connection.generation.value
        )
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
        self._dispose_connection_subscription = (
            event_bridge.subscribe_connection_state(
                self._on_connection_state,
                replay_current=True,
            )
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
        initial = self._read_state(context, revision=1)
        with self._lock:
            self._ensure_open()
            existing = self._states.get(context)
            if existing is not None:
                return existing
            if (
                self._connection_phase
                is not EventBridgeConnectionPhase.CONNECTED
                or self._connection_generation != connection_generation
            ):
                initial = self._connection_view_state(
                    initial,
                    self._connection_phase,
                    revision=1,
                )
            self._states[context] = initial
            return initial

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
            subscriptions = tuple(
                item[2] for item in self._subscriptions.values()
            )
            self._subscriptions.clear()
            dispose_batch = self._dispose_batch_subscription
            self._dispose_batch_subscription = lambda: None
            dispose_connection = self._dispose_connection_subscription
            self._dispose_connection_subscription = lambda: None
            self._pending_refreshes.clear()
            self._scheduled_refreshes.clear()
            timers = tuple(
                timer
                for _, timer
                in self._terminal_confirmation_timers.values()
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
                and current_thread().name.startswith(
                    self._executor_thread_prefix
                )
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
                or self._connection_phase
                is not EventBridgeConnectionPhase.CONNECTED
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
                                if existing is not None
                                and existing[0] == generation
                                else None
                            ),
                        )
            elif result is _RefreshResult.COMMITTED_TERMINAL:
                self._cancel_terminal_confirmation(context)
            elif (
                terminal_phase is not None
                and result
                is _RefreshResult.COMMITTED_NON_TERMINAL
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
                timer
                for _, timer
                in self._terminal_confirmation_timers.values()
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
            if (
                phase is EventBridgeConnectionPhase.CONNECTED
                and (
                    selection is None
                    or selection.run_id is None
                )
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
            freshness=(
                Freshness.DISCONNECTED if disconnected else Freshness.STALE
            ),
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
                previous.completeness
                if data is not None
                else Completeness.UNKNOWN
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
                or self._connection_phase
                is not EventBridgeConnectionPhase.CONNECTED
            ):
                return _RefreshResult.ABORTED
            previous = self._states.get(context)
        if previous is None:
            return _RefreshResult.ABORTED
        state = self._read_state(context, revision=previous.revision + 1)
        if state.last_reliable_data is None and previous.last_reliable_data is not None:
            age = max(
                state.observed_at
                - previous.last_reliable_data.wall_time.observed_at,
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
        with self._lock:
            if (
                self._closed
                or target_generation != self._connection_generation
                or target_connection_sequence != self._connection_sequence
                or self._connection_phase
                is not EventBridgeConnectionPhase.CONNECTED
            ):
                return _RefreshResult.ABORTED
        stored = self._store_and_notify(
            context,
            state,
            expected_revision=previous.revision,
            expected_connection_sequence=target_connection_sequence,
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
                or self._connection_phase
                is not EventBridgeConnectionPhase.CONNECTED
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
                or self._connection_phase
                is not EventBridgeConnectionPhase.CONNECTED
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
            if (
                current is None
                or current[0] != generation
                or current[1] is not timer
            ):
                return
            self._terminal_confirmation_timers.pop(context, None)
            if (
                self._closed
                or generation != self._connection_generation
                or self._connection_phase
                is not EventBridgeConnectionPhase.CONNECTED
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
    ) -> RunMonitoringViewState:
        observed_at = _aware(self._clock())
        if (
            context.selection is None
            or context.selection.run_id is None
        ):
            return self._empty_state(
                context,
                revision=revision,
                observed_at=observed_at,
            )
        try:
            record = self._runtime_gateway.get_run_monitoring_snapshot(
                context.selection.run_id.value
            )
        except Exception as error:
            return self._failed_state(
                context,
                revision=revision,
                observed_at=observed_at,
                error=error,
            )
        if record is None:
            return self._empty_state(
                context,
                revision=revision,
                observed_at=observed_at,
            )
        try:
            data = self._map_record(
                context,
                record,
                observed_at=observed_at,
            )
        except Exception as error:
            return self._failed_state(
                context,
                revision=revision,
                observed_at=observed_at,
                error=error,
            )
        terminal = data.terminal_outcome is not None
        failed = data.lifecycle is RunLifecyclePhase.FAILED
        age = max(
            observed_at - data.wall_time.observed_at,
            timedelta(0),
        )
        stale = age > self._freshness_threshold
        if stale:
            data = replace(
                data,
                capabilities=DiagnosticTaskCapabilities(
                    False,
                    False,
                    False,
                ),
            )
        completeness = _data_completeness(data)
        return RunMonitoringViewState(
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
                if stale
                else ViewPhase.READY
            ),
            presentation=(
                RunMonitoringPresentationState.TERMINAL
                if terminal
                else RunMonitoringPresentationState.ACTIVE
            ),
            last_reliable_data=data,
            error=(
                StructuredFeatureError(
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
                    code="run_monitoring_source_stale",
                    message=(
                        "Run Monitoring data is older than its "
                        "freshness threshold."
                    ),
                    retryable=True,
                )
                if stale
                else None
            ),
            completeness=completeness,
        )

    def _map_record(
        self,
        context: RunMonitoringContext,
        record: dict[str, Any],
        *,
        observed_at: datetime,
    ) -> RunMonitoringData:
        selection = context.selection
        assert selection is not None
        assert selection.run_id is not None
        task_value = _optional_text(record.get("task_id"))
        task_id = (
            DiagnosticTaskId(task_value)
            if task_value is not None
            else None
        )
        runtime_lifecycle = _lifecycle(record.get("status"))
        controller_status = (
            self._diagnostic_task_status(task_id)
            if task_id is not None
            else None
        )
        lifecycle = (
            _lifecycle(controller_status)
            if controller_status is not None
            and runtime_lifecycle
            not in {
                RunLifecyclePhase.COMPLETED,
                RunLifecyclePhase.FAILED,
                RunLifecyclePhase.CANCELED,
            }
            else runtime_lifecycle
        )
        started_at = _optional_aware(record.get("started_at"))
        wall_observed_at = _optional_aware(record.get("updated_at")) or observed_at
        elapsed = (
            max(wall_observed_at - started_at, timedelta(0))
            if started_at is not None
            else timedelta(0)
        )
        simulation_instant = (
            _optional_aware(record.get("last_sim_dt"))
            or datetime(1, 1, 1, tzinfo=timezone.utc)
        )
        requested = _string_mapping(record.get("requested_execution"))
        effective = _string_mapping(record.get("effective_execution"))
        overrides = _string_mapping(record.get("execution_override_reasons"))
        assumption_names = tuple(sorted(set(requested) | set(effective)))
        assumptions = tuple(
            ExecutionAssumption(
                name=name,
                requested_value=requested.get(
                    name,
                    effective.get(name, "unavailable"),
                ),
                effective_value=effective.get(
                    name,
                    requested.get(name, "unavailable"),
                ),
                override_reason=overrides.get(name),
            )
            for name in assumption_names
        )
        alerts = tuple(
            RunAlert(
                code=_nonempty(item.get("code"), "runtime_alert"),
                severity=_alert_severity(item.get("severity")),
                message=_nonempty(
                    item.get("message"),
                    "Runtime alert details are unavailable.",
                ),
            )
            for item in _mapping_sequence(record.get("alerts"))
        )
        completed = max(int(record.get("completed_nodes") or 0), 0)
        total = max(int(record.get("total_nodes") or 1), 1)
        completed = min(completed, total)
        active_task = (
            self._task_handles.get(task_id)
            if task_id is not None
            else None
        )
        capabilities = (
            self._capabilities(task_id, lifecycle)
            if task_id is not None
            else DiagnosticTaskCapabilities(False, False, False)
        )
        if (
            active_task is not None
            and active_task.phase in {TaskPhase.QUEUED, TaskPhase.RUNNING}
        ):
            capabilities = DiagnosticTaskCapabilities(False, False, False)
        return RunMonitoringData(
            selection=selection,
            strategy_id=_optional_identity(
                record.get("strategy_id"),
                StrategyUnderTestId,
            ),
            market_scenario_id=_optional_identity(
                record.get("scenario_name"),
                MarketScenarioId,
            ),
            scenario_set_id=_optional_identity(
                record.get("scenario_set_id"),
                ScenarioSetId,
            ),
            reproduction_manifest_id=_optional_identity(
                record.get("reproduction_manifest_id"),
                ReproductionManifestId,
            ),
            task_id=task_id,
            lifecycle=lifecycle,
            terminal_outcome=_terminal_outcome(lifecycle),
            progress=RunProgress(
                current_node_id=_nonempty(
                    record.get("current_node_id"),
                    f"RUN-{lifecycle.value.upper()}",
                ),
                current_node_label=_nonempty(
                    record.get("current_node_label"),
                    lifecycle.value.replace("_", " ").title(),
                ),
                completed=completed,
                total=total,
            ),
            simulation_time=SimulationTime(
                sim_day=max(int(record.get("last_sim_day") or 0), 0),
                instant=simulation_instant,
            ),
            wall_time=WallTime(
                started_at=started_at,
                observed_at=wall_observed_at,
                elapsed=elapsed,
            ),
            execution_assumptions=assumptions,
            alerts=alerts,
            context=ReadOnlyDiagnosticContext(
                market=_string_tuple(record.get("market_context")),
                account=_string_tuple(record.get("account_context")),
                positions=_string_tuple(record.get("position_context")),
                orders=_string_tuple(record.get("order_context")),
                fills=_string_tuple(record.get("fill_context")),
            ),
            capabilities=capabilities,
            active_task=active_task,
        )

    def _apply_command(
        self,
        *,
        action: str,
        target_id: DiagnosticTaskId,
        expected_revision: int,
    ) -> DiagnosticTaskCommandResult:
        with self._lock:
            self._ensure_open()
            match = next(
                (
                    (context, state)
                    for context, state in self._states.items()
                    if state.last_reliable_data is not None
                    and state.last_reliable_data.task_id == target_id
                ),
                None,
            )
            if match is None:
                return _rejected(
                    DiagnosticCommandRejectionReason.UNAVAILABLE_CAPABILITY,
                    "The diagnostic task is unavailable.",
                )
            context, state = match
            aged_state = self._age_state(state)
            if aged_state is not state:
                self._states[context] = aged_state
                state = aged_state
            data = state.last_reliable_data
            assert data is not None
            if state.revision != expected_revision:
                return _rejected(
                    DiagnosticCommandRejectionReason.STALE_EXPECTED_REVISION,
                    "The diagnostic task changed; refresh and try again.",
                )
            if state.freshness in {
                Freshness.DISCONNECTED,
                Freshness.STALE,
            } or (
                self._connection_phase
                is not EventBridgeConnectionPhase.CONNECTED
            ):
                return _rejected(
                    DiagnosticCommandRejectionReason.DISCONNECTED_SOURCE,
                    "The diagnostic source is disconnected.",
                )
            if (
                data.active_task is not None
                and data.active_task.phase
                in {TaskPhase.QUEUED, TaskPhase.RUNNING}
            ):
                return _rejected(
                    DiagnosticCommandRejectionReason.UNAVAILABLE_CAPABILITY,
                    "A diagnostic task operation is already in progress.",
                )
            transition = _diagnostic_task_transition(action)
            if not transition.is_allowed(data.capabilities):
                return _rejected(
                    transition.rejection_reason,
                    f"The diagnostic task cannot {action} in its current phase.",
                )
            task = TaskHandle(
                identity=TaskHandleId(
                    f"LIVE-TASK-{self._next_task_id:04d}"
                ),
                target_id=target_id,
                phase=TaskPhase.QUEUED,
                progress=0.0,
                result=None,
                error=None,
                cancelable=False,
            )
            self._next_task_id += 1
            self._task_handles[target_id] = task
            queued_state = replace(
                state,
                revision=state.revision + 1,
                observed_at=_aware(self._clock()),
                last_reliable_data=replace(
                    data,
                    capabilities=DiagnosticTaskCapabilities(
                        False,
                        False,
                        False,
                    ),
                    active_task=task,
                ),
            )
            self._states[context] = queued_state
            deliveries = self._deliveries_for(context)
        for observer, subscription in deliveries:
            subscription.deliver(observer, queued_state)

        future = self._executor.submit(
            self._invoke_diagnostic_task,
            action,
            target_id,
        )
        def _complete(completed: Future[Any]) -> None:
            self._complete_command(
                context=context,
                action=action,
                target_id=target_id,
                task=task,
                future=completed,
            )

        future.add_done_callback(_complete)
        return DiagnosticTaskCommandResult(
            accepted=True,
            message=f"Diagnostic task {action} accepted.",
            rejection_reason=None,
            task=task,
        )

    def _invoke_diagnostic_task(
        self,
        action: str,
        target_id: DiagnosticTaskId,
    ) -> Any:
        controller = self._diagnostic_tasks
        if controller is None:
            raise RuntimeError("Diagnostic task capability is unavailable")
        transition = _diagnostic_task_transition(action)
        method = getattr(controller, transition.controller_method, None)
        if not callable(method):
            raise RuntimeError("Diagnostic task capability is unavailable")
        return method(target_id.value)

    def _complete_command(
        self,
        *,
        context: RunMonitoringContext,
        action: str,
        target_id: DiagnosticTaskId,
        task: TaskHandle,
        future: Future[Any],
    ) -> None:
        try:
            future.result()
        except Exception:
            task = replace(
                task,
                phase=TaskPhase.FAILED,
                progress=1.0,
                error=StructuredFeatureError(
                    code=f"diagnostic_task_{action}_failed",
                    message="The diagnostic task action failed.",
                    retryable=False,
                ),
            )
            lifecycle = None
        else:
            transition = _diagnostic_task_transition(action)
            task = replace(
                task,
                phase=TaskPhase.COMPLETED,
                progress=1.0,
                result=transition.result,
            )
            lifecycle = transition.lifecycle
        with self._lock:
            if self._closed:
                return
            state = self._states.get(context)
            if state is None or state.last_reliable_data is None:
                return
            tracked = self._task_handles.get(target_id)
            if tracked is None or tracked.identity != task.identity:
                return
            self._task_handles[target_id] = task
            data = state.last_reliable_data
            updated_data = replace(
                data,
                lifecycle=lifecycle or data.lifecycle,
                terminal_outcome=(
                    _terminal_outcome(lifecycle)
                    if lifecycle is not None
                    else data.terminal_outcome
                ),
                capabilities=self._capabilities(
                    target_id,
                    lifecycle or data.lifecycle,
                ),
                active_task=task,
            )
            updated_state = replace(
                state,
                revision=state.revision + 1,
                observed_at=_aware(self._clock()),
                phase=(
                    ViewPhase.DEGRADED
                    if task.phase is TaskPhase.FAILED
                    else ViewPhase.READY
                ),
                presentation=(
                    RunMonitoringPresentationState.TERMINAL
                    if updated_data.terminal_outcome is not None
                    else RunMonitoringPresentationState.ACTIVE
                ),
                last_reliable_data=updated_data,
                error=task.error,
            )
            self._states[context] = updated_state
            deliveries = self._deliveries_for(context)
        for observer, subscription in deliveries:
            subscription.deliver(observer, updated_state)

    def _diagnostic_task_status(
        self,
        task_id: DiagnosticTaskId,
    ) -> str | None:
        controller = self._diagnostic_tasks
        reader = getattr(controller, "get_arena", None)
        if not callable(reader):
            return None
        try:
            state = reader(task_id.value)
        except Exception:
            return None
        if not isinstance(state, dict):
            return None
        value = str(state.get("status") or "").strip()
        return value or None

    def _capabilities(
        self,
        task_id: DiagnosticTaskId,
        lifecycle: RunLifecyclePhase,
    ) -> DiagnosticTaskCapabilities:
        status = self._diagnostic_task_status(task_id)
        if status is None:
            return DiagnosticTaskCapabilities(False, False, False)
        return DiagnosticTaskCapabilities(
            can_pause=lifecycle is RunLifecyclePhase.RUNNING,
            can_resume=lifecycle is RunLifecyclePhase.PAUSED,
            can_cancel=lifecycle
            in {
                RunLifecyclePhase.QUEUED,
                RunLifecyclePhase.RUNNING,
                RunLifecyclePhase.PAUSED,
            },
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

    def _failed_state(
        self,
        context: RunMonitoringContext,
        *,
        revision: int,
        observed_at: datetime,
        error: Exception,
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
            error=StructuredFeatureError(
                code="run_monitoring_query_failed",
                message=(
                    "Run Monitoring data is temporarily unavailable."
                ),
                retryable=True,
            ),
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
                        "Run Monitoring data is older than its "
                        "freshness threshold."
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
    ) -> RunMonitoringViewState:
        with self._lock:
            if self._closed:
                return self._states.get(context, state)
            previous = self._states.get(context)
            if (
                expected_connection_sequence is not None
                and expected_connection_sequence
                != self._connection_sequence
            ):
                return previous or state
            if expected_revision is not None and (
                previous is None
                or previous.revision != expected_revision
            ):
                return previous or state
            if state.source.generation != self._connection_generation:
                return previous or state
            if (
                state.freshness is Freshness.FRESH
                and self._connection_phase
                is not EventBridgeConnectionPhase.CONNECTED
            ):
                return previous or state
            if previous is not None and state.revision <= previous.revision:
                return previous
            self._states[context] = state
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
            for subscribed_context, observer, subscription
            in self._subscriptions.values()
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
            identity="frontend-v2-live-runtime",
            generation=self._connection_generation,
        )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _optional_aware(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _aware(value)
    if isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return _aware(parsed)
    return None


def _nonempty(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


IdentityT = TypeVar("IdentityT")


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_identity(
    value: Any,
    factory: Callable[[str], IdentityT],
) -> IdentityT | None:
    text = _optional_text(value)
    return factory(text) if text is not None else None


def _data_completeness(data: RunMonitoringData) -> Completeness:
    required_identities = (
        data.strategy_id,
        data.market_scenario_id,
        data.scenario_set_id,
        data.reproduction_manifest_id,
        data.task_id,
    )
    return (
        Completeness.COMPLETE
        if all(identity is not None for identity in required_identities)
        else Completeness.PARTIAL
    )


def _string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if str(key).strip() and str(item).strip()
    }


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        return ()
    return tuple(
        text
        for item in value
        if (text := str(item or "").strip())
    )


def _mapping_sequence(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (tuple, list)):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, dict))


def _lifecycle(value: Any) -> RunLifecyclePhase:
    normalized = str(value or "").strip().lower()
    aliases = {
        "created": RunLifecyclePhase.QUEUED,
        "ready": RunLifecyclePhase.QUEUED,
        "starting": RunLifecyclePhase.QUEUED,
        "recovered": RunLifecyclePhase.RUNNING,
        "running": RunLifecyclePhase.RUNNING,
        "paused": RunLifecyclePhase.PAUSED,
        "completed": RunLifecyclePhase.COMPLETED,
        "stopped": RunLifecyclePhase.COMPLETED,
        "failed": RunLifecyclePhase.FAILED,
        "canceled": RunLifecyclePhase.CANCELED,
        "cancelled": RunLifecyclePhase.CANCELED,
    }
    return aliases.get(normalized, RunLifecyclePhase.QUEUED)


def _terminal_outcome(
    lifecycle: RunLifecyclePhase | None,
) -> TerminalOutcome | None:
    if lifecycle is None:
        return None
    return {
        RunLifecyclePhase.COMPLETED: TerminalOutcome.COMPLETED,
        RunLifecyclePhase.FAILED: TerminalOutcome.FAILED,
        RunLifecyclePhase.CANCELED: TerminalOutcome.CANCELED,
    }.get(lifecycle)


def _alert_severity(value: Any) -> AlertSeverity:
    try:
        return AlertSeverity(str(value or "").strip().lower())
    except ValueError:
        return AlertSeverity.INFO


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
