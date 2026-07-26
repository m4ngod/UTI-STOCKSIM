"""Live Evidence & Findings Adapter over runtime and persisted evidence data."""

from __future__ import annotations

from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from math import isfinite
from threading import RLock, current_thread
from typing import Any, Callable, Protocol

from app.event_bridge import (
    EventBridge,
    EventBridgeBatch,
    EventBridgeConnectionPhase,
    EventBridgeConnectionState,
)
from .evidence_and_findings import (
    CandidateEvidence,
    DependencyProvenance,
    DiagnosticEvidenceChart,
    DiagnosticCandidateId,
    EvidenceChartOverlay,
    EvidenceChartOverlayAxis,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsData,
    EvidenceAndFindingsObserver,
    EvidenceAndFindingsPresentationState,
    EvidenceAndFindingsSource,
    EvidenceAndFindingsSubscription,
    EvidenceAndFindingsViewState,
    EvidenceAvailability,
    EvidenceComparison,
    EvidenceComparisonId,
    EvidenceCoverage,
    EvidenceDimension,
    EvidenceProvenance,
    EvidenceRecord,
    EvidenceRecordId,
    FillEvidenceTrace,
    Finding,
    FindingDisposition,
    FindingId,
    OrderEvidenceTrace,
    ReadOnlyEvidenceContext,
    SensitivityBreakpoint,
    SensitivityBreakpointId,
)
from .run_monitoring import (
    Completeness,
    ExecutionAssumption,
    Freshness,
    SourceGenerationId,
    SourceKind,
    StrategyRunId,
    StructuredFeatureError,
    ViewPhase,
)
from .versioning import (
    EVIDENCE_AND_FINDINGS_INTERFACE_VERSION,
    FeatureInterfaceVersion,
)


class _EvidenceAndFindingsRuntimeQueries(Protocol):
    def get_evidence_and_findings_snapshot(
        self,
        run_id: str,
    ) -> dict[str, Any] | None: ...


class _LiveEvidenceSubscription:
    def __init__(self, dispose: Callable[[], None]) -> None:
        self._dispose = dispose
        self._disposed = False
        self._last_revision = 0
        self._lock = RLock()

    @property
    def disposed(self) -> bool:
        with self._lock:
            return self._disposed

    def dispose(self) -> None:
        with self._lock:
            if self._disposed:
                return
            self._disposed = True
        self._dispose()

    def mark_disposed(self) -> None:
        with self._lock:
            self._disposed = True

    def deliver(
        self,
        observer: EvidenceAndFindingsObserver,
        state: EvidenceAndFindingsViewState,
    ) -> None:
        with self._lock:
            if self._disposed or state.revision <= self._last_revision:
                return
            self._last_revision = state.revision
            try:
                observer(state)
            except Exception:
                return


@dataclass(frozen=True, slots=True)
class _SourceVersion:
    """Comparable source identity for numeric and artifact-backed records."""

    revision: int | None
    identity: str | None
    order: int | None
    created_at: datetime | None


class LiveEvidenceAndFindingsAdapter:
    """Typed, read-only live seam for persisted diagnostic evidence."""

    def __init__(
        self,
        *,
        runtime_gateway: _EvidenceAndFindingsRuntimeQueries,
        event_bridge: EventBridge,
        clock: Callable[[], datetime] | None = None,
        freshness_threshold: timedelta = timedelta(seconds=5),
        executor: Executor | None = None,
    ) -> None:
        self._runtime_gateway = runtime_gateway
        self._event_bridge = event_bridge
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._freshness_threshold = freshness_threshold
        self._owns_executor = executor is None
        self._executor_thread_prefix = (
            f"evidence-findings-{id(self):x}"
            if self._owns_executor
            else None
        )
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=(
                self._executor_thread_prefix
                or "evidence-findings-external"
            ),
        )
        self._states: dict[
            EvidenceAndFindingsContext,
            EvidenceAndFindingsViewState,
        ] = {}
        self._accepted_source_revisions: dict[
            EvidenceAndFindingsContext,
            tuple[SourceGenerationId, _SourceVersion],
        ] = {}
        self._subscriptions: dict[
            int,
            tuple[
                EvidenceAndFindingsContext,
                EvidenceAndFindingsObserver,
                _LiveEvidenceSubscription,
            ],
        ] = {}
        self._pending_refreshes: dict[
            EvidenceAndFindingsContext,
            SourceGenerationId,
        ] = {}
        self._scheduled_refreshes: set[EvidenceAndFindingsContext] = set()
        self._next_subscription_id = 1
        connection = event_bridge.connection_state
        self._connection_generation = SourceGenerationId(
            connection.generation.value
        )
        self._connection_sequence = connection.sequence.value
        self._connection_phase = connection.phase
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
        return EVIDENCE_AND_FINDINGS_INTERFACE_VERSION

    def snapshot(
        self,
        context: EvidenceAndFindingsContext,
    ) -> EvidenceAndFindingsViewState:
        while True:
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
            initial, source_revision = self._read_state(
                context,
                revision=1,
            )
            with self._lock:
                self._ensure_open()
                existing = self._states.get(context)
                if existing is not None:
                    return existing
                connection_changed = (
                    self._connection_phase
                    is not EventBridgeConnectionPhase.CONNECTED
                    or self._connection_generation != connection_generation
                )
                if (
                    connection_changed
                    and self._connection_phase
                    is EventBridgeConnectionPhase.CONNECTED
                ):
                    continue
                if connection_changed:
                    initial = self._connection_view_state(
                        initial,
                        self._connection_phase,
                        revision=1,
                    )
                    source_revision = None
                self._states[context] = initial
                if source_revision is not None:
                    self._accepted_source_revisions[context] = (
                        initial.source.generation,
                        source_revision,
                    )
                return initial

    def subscribe(
        self,
        context: EvidenceAndFindingsContext,
        observer: EvidenceAndFindingsObserver,
    ) -> EvidenceAndFindingsSubscription:
        state = self.snapshot(context)
        with self._lock:
            self._ensure_open()
            subscription_id = self._next_subscription_id
            self._next_subscription_id += 1
            subscription = _LiveEvidenceSubscription(
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
        dispose_batch()
        dispose_connection()
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

    def _on_snapshot_batch(self, batch: EventBridgeBatch) -> None:
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
            to_schedule = []
            for context in tuple(self._states):
                selection = context.selection
                if selection is None:
                    continue
                if (
                    batch_run_ids
                    and selection.run_id.value not in batch_run_ids
                ):
                    continue
                self._pending_refreshes[context] = generation
                if context not in self._scheduled_refreshes:
                    self._scheduled_refreshes.add(context)
                    to_schedule.append(context)
        for context in to_schedule:
            self._executor.submit(self._drain_refreshes, context)

    def _drain_refreshes(
        self,
        context: EvidenceAndFindingsContext,
    ) -> None:
        while True:
            with self._lock:
                if self._closed:
                    self._scheduled_refreshes.discard(context)
                    self._pending_refreshes.pop(context, None)
                    return
                generation = self._pending_refreshes.pop(context, None)
                if generation is None:
                    self._scheduled_refreshes.discard(context)
                    return
            retry = self._refresh_context(context, generation=generation)
            with self._lock:
                if (
                    retry
                    and not self._closed
                    and generation == self._connection_generation
                    and self._connection_phase
                    is EventBridgeConnectionPhase.CONNECTED
                ):
                    self._pending_refreshes.setdefault(context, generation)
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
        for context in contexts:
            self._publish_connection_state(
                context,
                connection.phase,
                generation,
                connection.sequence.value,
            )

    def _publish_connection_state(
        self,
        context: EvidenceAndFindingsContext,
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
            state = self._connection_view_state(previous, phase)
            self._states[context] = state
            deliveries = self._deliveries_for(context)
        for observer, subscription in deliveries:
            subscription.deliver(observer, state)

    def _connection_view_state(
        self,
        previous: EvidenceAndFindingsViewState,
        phase: EventBridgeConnectionPhase,
        *,
        revision: int | None = None,
        observed_at: datetime | None = None,
    ) -> EvidenceAndFindingsViewState:
        current_time = observed_at or _aware(self._clock())
        data = previous.last_reliable_data
        disconnected = phase is EventBridgeConnectionPhase.DISCONNECTED
        elapsed = max(current_time - previous.observed_at, timedelta(0))
        return replace(
            previous,
            revision=revision or previous.revision + 1,
            observed_at=current_time,
            freshness=(
                Freshness.DISCONNECTED if disconnected else Freshness.STALE
            ),
            age=previous.age + elapsed if data is not None else timedelta(0),
            source=self._source(),
            phase=ViewPhase.DEGRADED if data is not None else ViewPhase.FAILED,
            presentation=(
                previous.presentation
                if data is not None
                else EvidenceAndFindingsPresentationState.DISCONNECTED
            ),
            error=StructuredFeatureError(
                code=(
                    "evidence_and_findings_source_disconnected"
                    if disconnected
                    else "evidence_and_findings_source_reconnecting"
                ),
                message=(
                    "Evidence is disconnected; showing the last reliable "
                    "research state."
                    if disconnected
                    else "Evidence reconnected and is awaiting a current "
                    "revision."
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
        context: EvidenceAndFindingsContext,
        *,
        generation: SourceGenerationId,
    ) -> bool:
        with self._lock:
            target_sequence = self._connection_sequence
            if (
                self._closed
                or generation != self._connection_generation
                or self._connection_phase
                is not EventBridgeConnectionPhase.CONNECTED
            ):
                return False
            previous = self._states.get(context)
        if previous is None:
            return False
        state, source_revision = self._read_state(
            context,
            revision=previous.revision + 1,
        )
        if (
            state.last_reliable_data is None
            and previous.last_reliable_data is not None
        ):
            elapsed = max(
                state.observed_at - previous.observed_at,
                timedelta(0),
            )
            state = replace(
                previous,
                revision=state.revision,
                observed_at=state.observed_at,
                freshness=Freshness.STALE,
                age=previous.age + elapsed,
                source=self._source(),
                phase=ViewPhase.DEGRADED,
                error=state.error
                or StructuredFeatureError(
                    code="evidence_and_findings_source_unavailable",
                    message=(
                        "The selected evidence is temporarily unavailable; "
                        "showing the last reliable research state."
                    ),
                    retryable=True,
                ),
            )
        stored = self._store_and_notify(
            context,
            state,
            expected_revision=previous.revision,
            expected_connection_sequence=target_sequence,
            source_revision=source_revision,
        )
        if stored is state:
            return False
        with self._lock:
            current = self._states.get(context)
            return bool(
                not self._closed
                and generation == self._connection_generation
                and self._connection_phase
                is EventBridgeConnectionPhase.CONNECTED
                and target_sequence == self._connection_sequence
                and current is stored
                and current is not None
                and current.revision != previous.revision
                and self._source_revision_is_new_locked(
                    context,
                    generation,
                    source_revision,
                    state,
                )
            )

    def _read_state(
        self,
        context: EvidenceAndFindingsContext,
        *,
        revision: int,
    ) -> tuple[
        EvidenceAndFindingsViewState,
        _SourceVersion | None,
    ]:
        observed_at = _aware(self._clock())
        selection = context.selection
        if selection is None:
            return (
                self._empty_state(
                    context,
                    revision=revision,
                    observed_at=observed_at,
                ),
                None,
            )
        try:
            record = (
                self._runtime_gateway
                .get_evidence_and_findings_snapshot(
                    selection.run_id.value
                )
            )
        except Exception:
            return (
                self._failed_state(
                    context,
                    revision=revision,
                    observed_at=observed_at,
                    code="evidence_and_findings_query_failed",
                    message=(
                        "Evidence & Findings data is temporarily unavailable."
                    ),
                    retryable=True,
                    disconnected=True,
                ),
                None,
            )
        if record is None:
            return (
                self._empty_state(
                    context,
                    revision=revision,
                    observed_at=observed_at,
                ),
                None,
            )
        source_revision = _source_version(record, record)
        try:
            _validate_record_selection(context, record)
            payload = _evidence_payload(record)
            _validate_record_selection(context, payload)
            source_revision = _source_version(record, payload)
            status = _status_token(
                payload.get("status")
                or record.get("status")
            )
            candidate_rows = _candidate_rows(payload)
            if not candidate_rows:
                if status in {"loading", "running", "pending"}:
                    return (
                        self._loading_state(
                            context,
                            revision=revision,
                            observed_at=observed_at,
                        ),
                        source_revision,
                    )
                if status in {"failed", "error"}:
                    return (
                        self._failed_state(
                            context,
                            revision=revision,
                            observed_at=observed_at,
                            code="evidence_and_findings_source_failed",
                            message=(
                                "The diagnostic evidence source reported "
                                "a failed result."
                            ),
                            retryable=False,
                            disconnected=False,
                        ),
                        source_revision,
                    )
                return (
                    self._empty_state(
                        context,
                        revision=revision,
                        observed_at=observed_at,
                    ),
                    source_revision,
                )
            data = _map_record(context, record, payload, candidate_rows)
        except Exception:
            return (
                self._failed_state(
                    context,
                    revision=revision,
                    observed_at=observed_at,
                    code="evidence_and_findings_mapping_failed",
                    message=(
                        "Evidence & Findings data failed integrity validation."
                    ),
                    retryable=False,
                    disconnected=False,
                ),
                source_revision,
            )
        source_updated_at = (
            _optional_aware(payload.get("updated_at"))
            or _optional_aware(payload.get("created_at"))
            or _optional_aware(record.get("updated_at"))
            or observed_at
        )
        age = max(observed_at - source_updated_at, timedelta(0))
        stale = age > self._freshness_threshold
        completeness = _data_completeness(data)
        failed = status in {"failed", "error"}
        if status in {"partial", "running", "pending"} or failed:
            completeness = Completeness.PARTIAL
        partial = completeness is Completeness.PARTIAL
        error = (
            StructuredFeatureError(
                code="evidence_and_findings_source_failed",
                message="The diagnostic evidence result is failed.",
                retryable=False,
            )
            if failed
            else StructuredFeatureError(
                code="evidence_and_findings_source_stale",
                message=(
                    "Evidence is older than its freshness threshold."
                ),
                retryable=True,
            )
            if stale
            else StructuredFeatureError(
                code="evidence_and_findings_partial",
                message=(
                    "Some diagnostic evidence is incomplete or unavailable."
                ),
                retryable=True,
            )
            if partial
            else None
        )
        return (
            EvidenceAndFindingsViewState(
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
                    EvidenceAndFindingsPresentationState.FAILED
                    if failed
                    else EvidenceAndFindingsPresentationState.READY
                ),
                last_reliable_data=data,
                error=error,
                completeness=completeness,
            ),
            source_revision,
        )

    def _loading_state(
        self,
        context: EvidenceAndFindingsContext,
        *,
        revision: int,
        observed_at: datetime,
    ) -> EvidenceAndFindingsViewState:
        return EvidenceAndFindingsViewState(
            interface_version=self.interface_version,
            revision=revision,
            observed_at=observed_at,
            freshness=Freshness.AWAITING_FIRST_STATE,
            age=timedelta(0),
            freshness_threshold=self._freshness_threshold,
            source=self._source(),
            context=context,
            phase=ViewPhase.LOADING,
            presentation=EvidenceAndFindingsPresentationState.LOADING,
            last_reliable_data=None,
            error=None,
            completeness=Completeness.UNKNOWN,
        )

    def _empty_state(
        self,
        context: EvidenceAndFindingsContext,
        *,
        revision: int,
        observed_at: datetime,
    ) -> EvidenceAndFindingsViewState:
        return EvidenceAndFindingsViewState(
            interface_version=self.interface_version,
            revision=revision,
            observed_at=observed_at,
            freshness=Freshness.FRESH,
            age=timedelta(0),
            freshness_threshold=self._freshness_threshold,
            source=self._source(),
            context=context,
            phase=ViewPhase.READY,
            presentation=EvidenceAndFindingsPresentationState.EMPTY,
            last_reliable_data=None,
            error=None,
            completeness=Completeness.EMPTY,
        )

    def _failed_state(
        self,
        context: EvidenceAndFindingsContext,
        *,
        revision: int,
        observed_at: datetime,
        code: str,
        message: str,
        retryable: bool,
        disconnected: bool,
    ) -> EvidenceAndFindingsViewState:
        return EvidenceAndFindingsViewState(
            interface_version=self.interface_version,
            revision=revision,
            observed_at=observed_at,
            freshness=(
                Freshness.DISCONNECTED
                if disconnected
                else Freshness.FRESH
            ),
            age=timedelta(0),
            freshness_threshold=self._freshness_threshold,
            source=self._source(),
            context=context,
            phase=ViewPhase.FAILED,
            presentation=(
                EvidenceAndFindingsPresentationState.DISCONNECTED
                if disconnected
                else EvidenceAndFindingsPresentationState.FAILED
            ),
            last_reliable_data=None,
            error=StructuredFeatureError(
                code=code,
                message=message,
                retryable=retryable,
            ),
            completeness=Completeness.UNKNOWN,
        )

    def _age_state(
        self,
        state: EvidenceAndFindingsViewState,
    ) -> EvidenceAndFindingsViewState:
        if (
            state.last_reliable_data is None
            or state.freshness is Freshness.DISCONNECTED
        ):
            return state
        current_time = _aware(self._clock())
        elapsed = max(current_time - state.observed_at, timedelta(0))
        age = state.age + elapsed
        source_failed = (
            state.error is not None
            and state.error.code
            in {
                "evidence_and_findings_query_failed",
                "evidence_and_findings_mapping_failed",
                "evidence_and_findings_source_unavailable",
            }
        )
        stale = age > self._freshness_threshold
        if current_time == state.observed_at and age == state.age:
            return state
        return replace(
            state,
            revision=state.revision + 1,
            observed_at=current_time,
            freshness=(
                Freshness.STALE
                if stale or source_failed
                else Freshness.FRESH
            ),
            age=age,
            phase=(
                ViewPhase.DEGRADED
                if stale or source_failed
                else state.phase
            ),
            error=(
                state.error
                if source_failed
                else StructuredFeatureError(
                    code="evidence_and_findings_source_stale",
                    message=(
                        "Evidence is older than its freshness threshold."
                    ),
                    retryable=True,
                )
                if stale
                else state.error
            ),
        )

    def _store_and_notify(
        self,
        context: EvidenceAndFindingsContext,
        state: EvidenceAndFindingsViewState,
        *,
        expected_revision: int | None = None,
        expected_connection_sequence: int | None = None,
        source_revision: _SourceVersion | None = None,
    ) -> EvidenceAndFindingsViewState:
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
            if not self._source_revision_is_new_locked(
                context,
                state.source.generation,
                source_revision,
                state,
            ):
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
            if source_revision is not None:
                self._accepted_source_revisions[context] = (
                    state.source.generation,
                    source_revision,
                )
            deliveries = self._deliveries_for(context)
        for observer, subscription in deliveries:
            subscription.deliver(observer, state)
        return state

    def _source_revision_is_new_locked(
        self,
        context: EvidenceAndFindingsContext,
        generation: SourceGenerationId,
        source_revision: _SourceVersion | None,
        candidate: EvidenceAndFindingsViewState,
    ) -> bool:
        if source_revision is None:
            return True
        accepted = self._accepted_source_revisions.get(context)
        if accepted is None or accepted[0] != generation:
            return True
        previous = accepted[1]
        current = source_revision
        if current.revision is not None:
            if previous.revision is None:
                return True
            if current.revision > previous.revision:
                return True
            if current.revision < previous.revision:
                return False
            return self._equal_source_version_recovers_locked(
                context,
                candidate,
            )
        if previous.revision is not None:
            return False
        if current.identity is not None or previous.identity is not None:
            if current.identity is None or previous.identity is None:
                return current.identity is not None
            if current.identity == previous.identity:
                return self._equal_source_version_recovers_locked(
                    context,
                    candidate,
                )
            order = _compare_source_order(current.order, previous.order)
            if order is not None:
                return order
            if (
                current.created_at is None
                or previous.created_at is None
            ):
                return False
            return current.created_at > previous.created_at
        order = _compare_source_order(current.order, previous.order)
        if order is not None:
            return order
        if current.created_at is not None:
            if previous.created_at is None:
                return True
            if current.created_at > previous.created_at:
                return True
            if current.created_at < previous.created_at:
                return False
        elif previous.created_at is not None:
            return False
        return self._equal_source_version_recovers_locked(
            context,
            candidate,
        )

    def _equal_source_version_recovers_locked(
        self,
        context: EvidenceAndFindingsContext,
        candidate: EvidenceAndFindingsViewState,
    ) -> bool:
        visible = self._states.get(context)
        return bool(
            visible is not None
            and visible.freshness is not Freshness.FRESH
            and candidate.freshness is Freshness.FRESH
            and candidate.phase is ViewPhase.READY
            and candidate.presentation
            is EvidenceAndFindingsPresentationState.READY
            and candidate.error is None
            and candidate.completeness is visible.completeness
            and visible.last_reliable_data is not None
            and candidate.last_reliable_data == visible.last_reliable_data
        )

    def _deliveries_for(
        self,
        context: EvidenceAndFindingsContext,
    ) -> tuple[
        tuple[
            EvidenceAndFindingsObserver,
            _LiveEvidenceSubscription,
        ],
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
            raise RuntimeError("Evidence & Findings Adapter is closed")

    def _source(self) -> EvidenceAndFindingsSource:
        return EvidenceAndFindingsSource(
            kind=SourceKind.LIVE_RUNTIME,
            identity="frontend-v2-live-evidence",
            generation=self._connection_generation,
        )


def _map_record(
    context: EvidenceAndFindingsContext,
    record: dict[str, Any],
    payload: dict[str, Any],
    candidate_rows: tuple[dict[str, Any], ...],
) -> EvidenceAndFindingsData:
    selection = context.selection
    assert selection is not None
    candidates = tuple(
        _map_candidate(row, payload, selection.run_id)
        for row in candidate_rows
    )
    return EvidenceAndFindingsData(
        selection=selection,
        candidates=candidates,
        read_only_context=_map_read_only_context(record, payload),
    )


def _map_candidate(
    row: dict[str, Any],
    payload: dict[str, Any],
    selected_run_id: StrategyRunId,
) -> CandidateEvidence:
    candidate_id = _required_text(
        row.get("candidate_id") or row.get("id"),
        "candidate_id",
    )
    evidence_rows = _mapping_sequence(row.get("evidence"))
    legacy = not evidence_rows
    if legacy:
        evidence_rows = _legacy_evidence_rows(candidate_id, row)
    evidence = tuple(_map_evidence(item) for item in evidence_rows)
    comparisons = (
        tuple(
            _map_comparison(item)
            for item in _mapping_sequence(row.get("comparisons"))
        )
        if _mapping_sequence(row.get("comparisons"))
        else _derived_comparisons(candidate_id, evidence)
    )
    finding_rows = _mapping_sequence(row.get("findings"))
    findings = (
        tuple(_map_finding(item) for item in finding_rows)
        if finding_rows
        else _derived_findings(candidate_id, row, evidence, comparisons)
    )
    assumptions = _mapping_sequence(
        row.get("execution_assumptions")
        or payload.get("execution_assumptions")
    )
    provenance = _mapping(row.get("provenance"))
    if not provenance and legacy:
        provenance = _legacy_provenance(row)
    return CandidateEvidence(
        identity=DiagnosticCandidateId(candidate_id),
        label=_text(row.get("label")) or candidate_id,
        evidence=evidence,
        comparisons=comparisons,
        findings=findings,
        execution_assumptions=tuple(
            ExecutionAssumption(
                name=_required_text(item.get("name"), "assumption name"),
                requested_value=_text(
                    item.get("requested_value")
                )
                or "unavailable",
                effective_value=_text(
                    item.get("effective_value")
                )
                or "unavailable",
                override_reason=_optional_text(
                    item.get("override_reason")
                ),
            )
            for item in assumptions
        ),
        provenance=_map_provenance(provenance, selected_run_id),
        chart=_map_chart(row.get("chart")),
    )


def _map_chart(value: Any) -> DiagnosticEvidenceChart | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("chart payload must be a mapping when provided")
    row = _mapping(value)
    if not row:
        raise ValueError("chart payload cannot be empty when provided")
    raw_values = _value_sequence(row.get("values"))
    if len(raw_values) < 2:
        raise ValueError("chart values require at least two points")
    values = tuple(
        _finite_float(item, "chart value") for item in raw_values
    )
    raw_overlays = row.get("overlays")
    if not isinstance(raw_overlays, (list, tuple)) or any(
        not isinstance(item, dict) or not item for item in raw_overlays
    ):
        raise ValueError("chart overlays must be non-empty mappings")
    overlays = tuple(
        EvidenceChartOverlay(
            identity=_required_text(
                overlay.get("identity") or overlay.get("id"),
                "chart overlay identity",
            ),
            label=_required_text(
                overlay.get("label"),
                "chart overlay label",
            ),
            axis=EvidenceChartOverlayAxis(
                _required_text(
                    overlay.get("axis"),
                    "chart overlay axis",
                )
            ),
            coordinate=_finite_float(
                overlay.get("coordinate"),
                "chart overlay coordinate",
            ),
            interpretation=_required_text(
                overlay.get("interpretation"),
                "chart overlay interpretation",
            ),
            evidence_ids=tuple(
                EvidenceRecordId(item)
                for item in _string_tuple(overlay.get("evidence_ids"))
            ),
        )
        for overlay in (_mapping(item) for item in raw_overlays)
    )
    return DiagnosticEvidenceChart(
        identity=_required_text(
            row.get("identity") or row.get("id"),
            "chart identity",
        ),
        label=_required_text(row.get("label"), "chart label"),
        unit=_required_text(row.get("unit"), "chart unit"),
        values=values,
        overlays=overlays,
    )


def _map_evidence(row: dict[str, Any]) -> EvidenceRecord:
    coverage = _coverage(row.get("coverage"))
    comparison_id = _optional_text(
        row.get("comparison_evidence_id")
    )
    comparison_value = _optional_text(row.get("comparison_value"))
    return EvidenceRecord(
        identity=EvidenceRecordId(
            _required_text(
                row.get("id")
                or row.get("identity")
                or row.get("evidence_id"),
                "evidence id",
            )
        ),
        coverage=coverage,
        dimension=_dimension(row.get("dimension"), row.get("label")),
        label=_text(row.get("label")) or "Evidence",
        value=_text(row.get("value")) or "unavailable",
        comparison_evidence_id=(
            EvidenceRecordId(comparison_id)
            if comparison_id is not None
            else None
        ),
        comparison_value=comparison_value,
        unit=_text(row.get("unit")) or "value",
        availability=_availability(
            row.get("availability") or row.get("status")
        ),
        interpretation=(
            _text(row.get("interpretation"))
            or "No interpretation was persisted."
        ),
        counts_toward_formal_completeness=_boolean(
            row.get("counts_toward_formal_completeness"),
            default=(
                coverage is not EvidenceCoverage.QUICK_EXPERIMENT
            ),
        ),
    )


def _map_comparison(row: dict[str, Any]) -> EvidenceComparison:
    return EvidenceComparison(
        identity=EvidenceComparisonId(
            _required_text(
                row.get("id")
                or row.get("identity")
                or row.get("comparison_id"),
                "comparison id",
            )
        ),
        label=_text(row.get("label")) or "Evidence comparison",
        reference_evidence_id=EvidenceRecordId(
            _required_text(
                row.get("reference_evidence_id"),
                "reference evidence id",
            )
        ),
        observed_evidence_id=EvidenceRecordId(
            _required_text(
                row.get("observed_evidence_id"),
                "observed evidence id",
            )
        ),
        interpretation=(
            _text(row.get("interpretation"))
            or "No comparison interpretation was persisted."
        ),
    )


def _map_finding(row: dict[str, Any]) -> Finding:
    return Finding(
        identity=FindingId(
            _required_text(
                row.get("id")
                or row.get("identity")
                or row.get("finding_id"),
                "finding id",
            )
        ),
        title=_text(row.get("title")) or "Diagnostic finding",
        disposition=_disposition(row.get("disposition")),
        comparison_summary=(
            _text(row.get("comparison_summary"))
            or "No comparison summary was persisted."
        ),
        failure_reason=_optional_text(row.get("failure_reason")),
        evidence_ids=tuple(
            EvidenceRecordId(item)
            for item in _string_tuple(row.get("evidence_ids"))
        ),
        comparison_ids=tuple(
            EvidenceComparisonId(item)
            for item in _string_tuple(row.get("comparison_ids"))
        ),
        sensitivity_breakpoints=tuple(
            _map_breakpoint(item)
            for item in _mapping_sequence(
                row.get("sensitivity_breakpoints")
            )
        ),
    )


def _map_breakpoint(row: dict[str, Any]) -> SensitivityBreakpoint:
    return SensitivityBreakpoint(
        identity=SensitivityBreakpointId(
            _required_text(
                row.get("id")
                or row.get("identity")
                or row.get("breakpoint_id"),
                "breakpoint id",
            )
        ),
        assumption_name=(
            _text(row.get("assumption_name")) or "unknown assumption"
        ),
        threshold=_text(row.get("threshold")) or "unavailable",
        outcome=_text(row.get("outcome")) or "unavailable",
        evidence_ids=tuple(
            EvidenceRecordId(item)
            for item in _string_tuple(row.get("evidence_ids"))
        ),
    )


def _map_provenance(
    row: dict[str, Any],
    selected_run_id: StrategyRunId,
) -> EvidenceProvenance:
    source_run_ids = _string_tuple(row.get("source_run_ids"))
    if not source_run_ids:
        source_run_ids = (selected_run_id.value,)
    return EvidenceProvenance(
        artifact_hashes=_string_tuple(row.get("artifact_hashes")),
        source_run_ids=tuple(
            StrategyRunId(item) for item in source_run_ids
        ),
        runner_version=(
            _text(row.get("runner_version")) or "unavailable"
        ),
        build_version=_text(row.get("build_version")) or "unavailable",
        dependencies=tuple(
            DependencyProvenance(
                name=_required_text(item.get("name"), "dependency name"),
                version=_text(item.get("version")) or "unavailable",
                artifact_hash=(
                    _text(item.get("artifact_hash")) or "unavailable"
                ),
            )
            for item in _mapping_sequence(row.get("dependencies"))
        ),
    )


def _map_read_only_context(
    record: dict[str, Any],
    payload: dict[str, Any],
) -> ReadOnlyEvidenceContext:
    context = _mapping(payload.get("read_only_context"))
    runtime = _mapping(record.get("runtime_context"))
    if not runtime:
        runtime = _mapping(record.get("run"))
    return ReadOnlyEvidenceContext(
        market=_string_tuple(
            context.get("market") or runtime.get("market_context")
        ),
        account=_string_tuple(
            context.get("account") or runtime.get("account_context")
        ),
        positions=_string_tuple(
            context.get("positions") or runtime.get("position_context")
        ),
        orders=tuple(
            _map_order_trace(item)
            for item in _value_sequence(
                context.get("orders") or runtime.get("order_context")
            )
        ),
        fills=tuple(
            _map_fill_trace(item)
            for item in _value_sequence(
                context.get("fills") or runtime.get("fill_context")
            )
        ),
    )


def _map_order_trace(value: Any) -> OrderEvidenceTrace:
    row = _mapping(value)
    if row:
        return OrderEvidenceTrace(
            identity=_required_text(
                row.get("id") or row.get("identity"),
                "order evidence id",
            ),
            instrument=_text(
                row.get("instrument") or row.get("symbol")
            )
            or "unavailable",
            status=_text(row.get("status")) or "unavailable",
            diagnostic_note=(
                _text(row.get("diagnostic_note"))
                or "Read-only persisted order evidence."
            ),
        )
    parts = _trace_parts(value)
    return OrderEvidenceTrace(
        identity=parts[0],
        instrument=parts[1] if len(parts) > 1 else "unavailable",
        status=parts[2] if len(parts) > 2 else "unavailable",
        diagnostic_note="Read-only persisted order evidence.",
    )


def _map_fill_trace(value: Any) -> FillEvidenceTrace:
    row = _mapping(value)
    if row:
        return FillEvidenceTrace(
            identity=_required_text(
                row.get("id") or row.get("identity"),
                "fill evidence id",
            ),
            order_identity=(
                _text(row.get("order_id") or row.get("order_identity"))
                or "unavailable"
            ),
            instrument=_text(
                row.get("instrument") or row.get("symbol")
            )
            or "unavailable",
            quantity=_integer(row.get("quantity")),
            price=_text(row.get("price")) or "unavailable",
        )
    parts = _trace_parts(value)
    return FillEvidenceTrace(
        identity=parts[0],
        order_identity="unavailable",
        instrument=parts[1] if len(parts) > 1 else "unavailable",
        quantity=0,
        price=parts[2] if len(parts) > 2 else "unavailable",
    )


def _legacy_evidence_rows(
    candidate_id: str,
    candidate: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    details = _mapping(candidate.get("evidence_details"))
    statuses = _mapping(candidate.get("evidence_status"))
    names = tuple(sorted(set(details) | set(statuses)))
    baseline_name = next(
        (name for name in names if "baseline" in name.casefold()),
        names[0] if names else "",
    )
    baseline_id = (
        f"E-{_slug(candidate_id)}-{_slug(baseline_name)}"
        if baseline_name
        else None
    )
    rows = []
    for name in names:
        detail = _mapping(details.get(name))
        coverage = _legacy_coverage(name, detail)
        evidence_id = f"E-{_slug(candidate_id)}-{_slug(name)}"
        compared = baseline_id is not None and name != baseline_name
        rows.append(
            {
                "id": evidence_id,
                "coverage": coverage.value,
                "dimension": _legacy_dimension(name).value,
                "label": name.replace("_", " ").title(),
                "value": _text(
                    detail.get("value")
                    or detail.get("status")
                    or statuses.get(name)
                )
                or "missing",
                "comparison_evidence_id": (
                    baseline_id if compared else None
                ),
                "comparison_value": (
                    _text(statuses.get(baseline_name)) or "missing"
                    if compared
                    else None
                ),
                "unit": _text(detail.get("unit")) or "evidence status",
                "availability": _availability(
                    detail.get("status") or statuses.get(name)
                ).value,
                "interpretation": (
                    _text(detail.get("interpretation"))
                    or _text(detail.get("next_action"))
                    or "Persisted evidence aggregate detail."
                ),
                "counts_toward_formal_completeness": (
                    coverage is not EvidenceCoverage.QUICK_EXPERIMENT
                ),
            }
        )
    return tuple(rows)


def _derived_comparisons(
    candidate_id: str,
    evidence: tuple[EvidenceRecord, ...],
) -> tuple[EvidenceComparison, ...]:
    return tuple(
        EvidenceComparison(
            identity=EvidenceComparisonId(
                f"CMP-{_slug(candidate_id)}-{_slug(item.identity.value)}"
            ),
            label=f"Reference versus {item.label}",
            reference_evidence_id=item.comparison_evidence_id,
            observed_evidence_id=item.identity,
            interpretation=item.interpretation,
        )
        for item in evidence
        if item.comparison_evidence_id is not None
    )


def _derived_findings(
    candidate_id: str,
    candidate: dict[str, Any],
    evidence: tuple[EvidenceRecord, ...],
    comparisons: tuple[EvidenceComparison, ...],
) -> tuple[Finding, ...]:
    details = _mapping(candidate.get("evidence_details"))
    comparison_by_observed = {
        item.observed_evidence_id: item.identity for item in comparisons
    }
    findings = []
    for item in evidence:
        if item.availability is EvidenceAvailability.COMPLETE:
            continue
        raw_name = next(
            (
                name
                for name in details
                if _slug(name) in item.identity.value
            ),
            "",
        )
        detail = _mapping(details.get(raw_name))
        reasons = (
            _string_tuple(detail.get("blocking_metrics"))
            + _string_tuple(detail.get("validation_reasons"))
        )
        comparison_id = comparison_by_observed.get(item.identity)
        findings.append(
            Finding(
                identity=FindingId(
                    f"F-{_slug(candidate_id)}-{_slug(item.identity.value)}"
                ),
                title=f"{item.label} is {item.availability.value}",
                disposition=(
                    FindingDisposition.FAILED
                    if item.availability is EvidenceAvailability.FAILED
                    else FindingDisposition.CONCERN
                ),
                comparison_summary=item.interpretation,
                failure_reason=(
                    " · ".join(reasons)
                    or _optional_text(detail.get("next_action"))
                    or f"{item.label} is {item.availability.value}."
                ),
                evidence_ids=(item.identity,),
                comparison_ids=(
                    (comparison_id,)
                    if comparison_id is not None
                    else ()
                ),
                sensitivity_breakpoints=tuple(
                    _map_breakpoint(breakpoint)
                    for breakpoint in _mapping_sequence(
                        detail.get("sensitivity_breakpoints")
                    )
                ),
            )
        )
    return tuple(findings)


def _legacy_provenance(candidate: dict[str, Any]) -> dict[str, Any]:
    details = tuple(
        _mapping(item)
        for item in _mapping(
            candidate.get("evidence_details")
        ).values()
    )
    return {
        "artifact_hashes": tuple(
            value
            for item in details
            if (value := _optional_text(item.get("artifact_hash")))
            is not None
        ),
        "source_run_ids": tuple(
            dict.fromkeys(
                run_id
                for item in details
                for run_id in _string_tuple(item.get("source_run_ids"))
            )
        ),
        "runner_version": next(
            (
                value
                for item in details
                if (
                    value := _optional_text(
                        item.get("runner_version")
                    )
                )
                is not None
            ),
            "unavailable",
        ),
        "build_version": (
            _text(candidate.get("build_version")) or "unavailable"
        ),
        "dependencies": candidate.get("dependencies") or (),
    }


def _evidence_payload(record: dict[str, Any]) -> dict[str, Any]:
    for key in (
        "evidence_and_findings",
        "diagnostic_evidence",
        "evidence_package",
    ):
        nested = _mapping(record.get(key))
        if nested:
            return nested
    return record


def _candidate_rows(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    direct = _mapping_sequence(payload.get("candidates"))
    if direct:
        return direct
    aggregate = _mapping(
        payload.get("series_evidence_aggregate")
        or payload.get("evidence_aggregate")
    )
    if not aggregate and "candidate_summaries" in payload:
        aggregate = payload
    if not aggregate:
        nested = _mapping(payload.get("aggregate"))
        aggregate = _mapping(
            nested.get("series_evidence")
            or nested.get("series_evidence_aggregate")
        )
    return _mapping_sequence(aggregate.get("candidate_summaries"))


def _validate_record_selection(
    context: EvidenceAndFindingsContext,
    record: dict[str, Any],
) -> None:
    selection = context.selection
    assert selection is not None
    record_run_id = _optional_text(record.get("run_id"))
    if (
        record_run_id is not None
        and record_run_id != selection.run_id.value
    ):
        raise ValueError("Evidence run does not match the route context")
    raw = _mapping(record.get("selection"))
    expected = {
        "campaign_id": selection.campaign_id.value,
        "run_id": selection.run_id.value,
        "strategy_id": (
            selection.strategy_id.value
            if selection.strategy_id is not None
            else None
        ),
        "market_scenario_id": (
            selection.market_scenario_id.value
            if selection.market_scenario_id is not None
            else None
        ),
        "approved_recipe_id": (
            selection.approved_recipe_id.value
            if selection.approved_recipe_id is not None
            else None
        ),
        "reproduction_manifest_id": (
            selection.reproduction_manifest_id.value
            if selection.reproduction_manifest_id is not None
            else None
        ),
    }
    for name, expected_value in expected.items():
        actual = _optional_text(raw.get(name))
        if (
            actual is not None
            and expected_value is not None
            and actual != expected_value
        ):
            raise ValueError(
                f"Evidence {name} does not match the route context"
            )


def _data_completeness(
    data: EvidenceAndFindingsData,
) -> Completeness:
    if not data.candidates:
        return Completeness.PARTIAL
    required_coverage = {
        EvidenceCoverage.BASELINE,
        EvidenceCoverage.ISOLATED_SENSITIVITY,
        EvidenceCoverage.COMPOUND_SCENARIO,
    }
    manifest = data.selection.reproduction_manifest_id
    for candidate in data.candidates:
        formal = tuple(
            item
            for item in candidate.evidence
            if item.counts_toward_formal_completeness
        )
        if (
            {item.coverage for item in formal} < required_coverage
            or not all(
                item.availability is EvidenceAvailability.COMPLETE
                for item in formal
            )
        ):
            return Completeness.PARTIAL
        if not candidate.execution_assumptions or any(
            not assumption.requested_value
            or not assumption.effective_value
            or _status_token(assumption.requested_value) == "unavailable"
            or _status_token(assumption.effective_value) == "unavailable"
            or (
                assumption.requested_value != assumption.effective_value
                and not assumption.override_reason
            )
            for assumption in candidate.execution_assumptions
        ):
            return Completeness.PARTIAL
        provenance = candidate.provenance
        if (
            not provenance.artifact_hashes
            or not provenance.source_run_ids
            or _status_token(provenance.runner_version) == "unavailable"
            or _status_token(provenance.build_version) == "unavailable"
            or not provenance.dependencies
        ):
            return Completeness.PARTIAL
        if manifest is not None and not any(
            "manifest" in _status_token(dependency.name)
            and dependency.version == manifest.value
            and _status_token(dependency.artifact_hash) != "unavailable"
            for dependency in provenance.dependencies
        ):
            return Completeness.PARTIAL
        if not candidate.comparisons or not candidate.findings:
            return Completeness.PARTIAL
        for finding in candidate.findings:
            if (
                not finding.evidence_ids
                or not finding.comparison_ids
                or not finding.sensitivity_breakpoints
                or (
                    finding.disposition
                    in {FindingDisposition.CONCERN, FindingDisposition.FAILED}
                    and not finding.failure_reason
                )
                or any(
                    not breakpoint.evidence_ids
                    for breakpoint in finding.sensitivity_breakpoints
                )
            ):
                return Completeness.PARTIAL
    return Completeness.COMPLETE


def _coverage(value: Any) -> EvidenceCoverage:
    token = _status_token(value)
    aliases = {
        "baseline": EvidenceCoverage.BASELINE,
        "isolated": EvidenceCoverage.ISOLATED_SENSITIVITY,
        "isolated_sensitivity": EvidenceCoverage.ISOLATED_SENSITIVITY,
        "sensitivity": EvidenceCoverage.ISOLATED_SENSITIVITY,
        "compound": EvidenceCoverage.COMPOUND_SCENARIO,
        "compound_scenario": EvidenceCoverage.COMPOUND_SCENARIO,
        "quick": EvidenceCoverage.QUICK_EXPERIMENT,
        "quick_experiment": EvidenceCoverage.QUICK_EXPERIMENT,
    }
    if token not in aliases:
        raise ValueError(
            f"Unsupported evidence coverage: {token or 'empty'}"
        )
    return aliases[token]


def _dimension(value: Any, label: Any = None) -> EvidenceDimension:
    token = _status_token(value)
    for item in EvidenceDimension:
        if token == item.value:
            return item
    if token:
        raise ValueError(f"Unsupported evidence dimension: {token}")
    return _legacy_dimension(f"{_text(value)} {_text(label)}")


def _availability(value: Any) -> EvidenceAvailability:
    token = _status_token(value)
    aliases = {
        "complete": EvidenceAvailability.COMPLETE,
        "completed": EvidenceAvailability.COMPLETE,
        "pass": EvidenceAvailability.COMPLETE,
        "available": EvidenceAvailability.COMPLETE,
        "partial": EvidenceAvailability.PARTIAL,
        "warning": EvidenceAvailability.PARTIAL,
        "missing": EvidenceAvailability.MISSING,
        "unavailable": EvidenceAvailability.UNAVAILABLE,
        "not_available": EvidenceAvailability.UNAVAILABLE,
        "failed": EvidenceAvailability.FAILED,
        "fail": EvidenceAvailability.FAILED,
        "error": EvidenceAvailability.FAILED,
    }
    if not token:
        return EvidenceAvailability.MISSING
    return aliases.get(token, EvidenceAvailability.UNAVAILABLE)


def _disposition(value: Any) -> FindingDisposition:
    token = _status_token(value)
    aliases = {
        "supported": FindingDisposition.SUPPORTED,
        "pass": FindingDisposition.SUPPORTED,
        "concern": FindingDisposition.CONCERN,
        "warning": FindingDisposition.CONCERN,
        "failed": FindingDisposition.FAILED,
        "fail": FindingDisposition.FAILED,
        "not_assessed": FindingDisposition.NOT_ASSESSED,
        "missing": FindingDisposition.NOT_ASSESSED,
    }
    return aliases.get(token, FindingDisposition.NOT_ASSESSED)


def _legacy_coverage(
    name: str,
    detail: dict[str, Any],
) -> EvidenceCoverage:
    explicit = _optional_text(detail.get("coverage"))
    if explicit is not None:
        return _coverage(explicit)
    token = name.casefold()
    if "quick" in token:
        return EvidenceCoverage.QUICK_EXPERIMENT
    if "sensitivity" in token or "paired" in token:
        return EvidenceCoverage.ISOLATED_SENSITIVITY
    if any(
        marker in token
        for marker in ("hidden", "exploit", "compound", "parent", "research")
    ):
        return EvidenceCoverage.COMPOUND_SCENARIO
    return EvidenceCoverage.BASELINE


def _legacy_dimension(value: str) -> EvidenceDimension:
    token = value.casefold()
    if any(marker in token for marker in ("return", "pnl", "baseline")):
        return EvidenceDimension.RETURN
    if any(marker in token for marker in ("risk", "drawdown")):
        return EvidenceDimension.RISK
    if any(
        marker in token
        for marker in ("fee", "fill", "latency", "execution", "exploit")
    ):
        return EvidenceDimension.EXECUTION
    if any(marker in token for marker in ("exposure", "concentration")):
        return EvidenceDimension.EXPOSURE
    if any(marker in token for marker in ("stability", "hidden")):
        return EvidenceDimension.STABILITY
    return EvidenceDimension.DOMAIN


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _mapping_sequence(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        mapped
        for item in value
        if (mapped := _mapping(item))
    )


def _value_sequence(value: Any) -> tuple[Any, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return ()


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return ()
    return tuple(
        text
        for item in value
        if (text := _text(item))
    )


def _trace_parts(value: Any) -> tuple[str, ...]:
    text = _text(value) or "unavailable"
    return tuple(
        part.strip()
        for part in text.split("·")
        if part.strip()
    ) or ("unavailable",)


def _required_text(value: Any, label: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{label} is required")
    return text


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _status_token(value: Any) -> str:
    return _text(value).casefold().replace("-", "_").replace(" ", "_")


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a finite number") from error
    if not isfinite(parsed):
        raise ValueError(f"{label} must be a finite number")
    return parsed


def _boolean(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    token = _status_token(value)
    if token in {"1", "true", "yes", "on"}:
        return True
    if token in {"0", "false", "no", "off"}:
        return False
    raise ValueError("Evidence boolean value is invalid")


def _source_version(
    record: dict[str, Any],
    payload: dict[str, Any],
) -> _SourceVersion:
    revision = _positive_int(
        payload.get("revision")
        or payload.get("evidence_revision")
        or record.get("revision")
        or record.get("evidence_revision")
    )
    identity = _optional_text(
        payload.get("aggregate_hash")
        or payload.get("evidence_hash")
        or payload.get("record_hash")
        or record.get("aggregate_hash")
        or record.get("evidence_hash")
        or record.get("record_hash")
    )
    order = _positive_int(
        payload.get("_source_version_order")
        or record.get("_source_version_order")
    )
    aggregate_backed = bool(
        identity
        or _status_token(payload.get("record_kind"))
        == "series_evidence_aggregate_v1"
    )
    raw_created_at = (
        payload.get("created_at")
        or payload.get("updated_at")
        or record.get("created_at")
        or record.get("updated_at")
        if aggregate_backed
        else payload.get("updated_at")
        or payload.get("created_at")
        or record.get("updated_at")
        or record.get("created_at")
    )
    try:
        created_at = _optional_aware(raw_created_at)
    except (TypeError, ValueError):
        created_at = None
    return _SourceVersion(
        revision=revision,
        identity=identity,
        order=order,
        created_at=created_at,
    )


def _compare_source_order(
    current: int | None,
    previous: int | None,
) -> bool | None:
    if current is None and previous is None:
        return None
    if current is None:
        return False
    if previous is None:
        return True
    if current == previous:
        return None
    return current > previous


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _slug(value: str) -> str:
    normalized = "".join(
        character if character.isalnum() else "-"
        for character in value.upper()
    )
    return "-".join(part for part in normalized.split("-") if part)


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
        parsed = datetime.fromisoformat(
            value.strip().replace("Z", "+00:00")
        )
        return _aware(parsed)
    return None


__all__ = ["LiveEvidenceAndFindingsAdapter"]
