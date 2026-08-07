"""Live and deterministic adapters for System Health Feature Interface 1.0."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Event, RLock, Thread, current_thread

from app.event_bridge import (
    EventBridge,
    EventBridgeBatch,
    EventBridgeConnectionPhase,
    EventBridgeConnectionState,
)

from .run_monitoring import (
    Completeness,
    Freshness,
    SourceGenerationId,
    SourceKind,
    Subscription,
    ViewPhase,
)
from .strategy_diagnostics_v1_read_model import SourceRevisionToken
from .system_health import (
    DiagnosticCacheCompatibility,
    DiagnosticCacheFallbackState,
    DiagnosticCacheHealthClassification,
    DiagnosticCacheHealthComponent,
    DiagnosticCacheLastRefreshResult,
    DiagnosticCacheRecoveryPhase,
    DiagnosticCacheScope,
    DiagnosticQueueBlockageReason,
    DiagnosticQueueConsumerAvailability,
    DiagnosticQueueHealthClassification,
    DiagnosticQueueHealthComponent,
    DiagnosticQueueRecoveryPhase,
    DiagnosticQueueScope,
    RuntimeHealthClassification,
    RuntimeHealthComponent,
    RuntimeHealthComponentIdentity,
    RuntimeHealthRecoveryPhase,
    SystemHealthContext,
    SystemHealthError,
    SystemHealthErrorCode,
    SystemHealthObserver,
    SystemHealthPresentationState,
    SystemHealthSource,
    SystemHealthViewState,
)
from .system_health_application import (
    DiagnosticCacheApplicationAvailability,
    DiagnosticCacheApplicationError,
    DiagnosticCacheApplicationErrorCode,
    DiagnosticCacheApplicationObservation,
    DiagnosticCacheApplicationResult,
    DiagnosticQueueApplicationAvailability,
    DiagnosticQueueApplicationError,
    DiagnosticQueueApplicationErrorCode,
    DiagnosticQueueApplicationObservation,
    DiagnosticQueueApplicationResult,
    RuntimeHealthApplicationAvailability,
    RuntimeHealthApplicationError,
    RuntimeHealthApplicationErrorCode,
    RuntimeHealthApplicationObservation,
    RuntimeHealthApplicationResult,
    StrategyDiagnosticsV1SystemHealthApplication,
)
from .versioning import (
    SYSTEM_HEALTH_INTERFACE_VERSION,
    FeatureInterfaceVersion,
)


def _default_live_clock() -> datetime:
    return datetime.now(timezone.utc)


def _default_fake_clock() -> datetime:
    return datetime(2030, 1, 1, tzinfo=timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("System Health clock must be timezone-aware")
    return value


class _SystemHealthSubscription:
    def __init__(self, dispose: Callable[[], None]) -> None:
        self._dispose = dispose
        self._disposed = False
        self._last_delivered_revision = 0
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
        observer: SystemHealthObserver,
        state: SystemHealthViewState,
    ) -> None:
        with self._lock:
            if self._disposed or state.revision <= self._last_delivered_revision:
                return
            self._last_delivered_revision = state.revision
        observer(state)


class _SystemHealthProjection:
    """Own the immutable Runtime Health state machine shared by both seams."""

    def __init__(
        self,
        *,
        read_runtime_health: Callable[[], RuntimeHealthApplicationResult],
        read_diagnostic_queue_health: Callable[
            [], DiagnosticQueueApplicationResult
        ],
        read_diagnostic_cache_health: Callable[
            [], DiagnosticCacheApplicationResult
        ],
        source_kind: SourceKind,
        source_identity: str,
        clock: Callable[[], datetime],
        freshness_threshold: timedelta,
    ) -> None:
        if freshness_threshold <= timedelta(0):
            raise ValueError("System Health freshness threshold must be positive")
        self._read_runtime_health = read_runtime_health
        self._read_diagnostic_queue_health = read_diagnostic_queue_health
        self._read_diagnostic_cache_health = read_diagnostic_cache_health
        self._source_kind = source_kind
        self._source_identity = source_identity
        self._clock = clock
        self._freshness_threshold = freshness_threshold
        self._context = SystemHealthContext()
        self._generation = SourceGenerationId(1)
        self._connected = True
        self._revision = 0
        self._state: SystemHealthViewState | None = None
        self._last_reliable: RuntimeHealthComponent | None = None
        self._last_reliable_queue: DiagnosticQueueHealthComponent | None = None
        self._last_reliable_cache: DiagnosticCacheHealthComponent | None = None
        self._current_authoritative_key: tuple[str, ...] | None = None
        self._last_notified_authoritative_key: tuple[str, ...] | None = None
        self._subscriptions: dict[
            int,
            tuple[SystemHealthObserver, _SystemHealthSubscription],
        ] = {}
        self._next_subscription_id = 1
        self._closed = False
        self._transition_lock = RLock()
        self._lock = RLock()

    @property
    def interface_version(self) -> FeatureInterfaceVersion:
        return SYSTEM_HEALTH_INTERFACE_VERSION

    def snapshot(self, context: SystemHealthContext) -> SystemHealthViewState:
        self._require_context(context)
        with self._transition_lock:
            return self._snapshot_transition()

    def _snapshot_transition(self) -> SystemHealthViewState:
        with self._lock:
            self._ensure_open()
            state = self._state
            connected = self._connected
        if connected:
            return self._refresh(
                recovery_phase=RuntimeHealthRecoveryPhase.IDLE,
                notify=False,
            )
        if state is None:
            return self._publish_retained(
                recovery_phase=RuntimeHealthRecoveryPhase.DISCONNECTED,
                error=self._disconnected_error(),
                notify=False,
            )

        aged = self._age_state(state)
        if aged is not state:
            return self._store_and_deliver(aged)
        return state

    def subscribe(
        self,
        context: SystemHealthContext,
        observer: SystemHealthObserver,
    ) -> Subscription:
        state = self.snapshot(context)
        with self._lock:
            self._ensure_open()
            subscription_id = self._next_subscription_id
            self._next_subscription_id += 1
            subscription = _SystemHealthSubscription(
                lambda: self._remove_subscription(subscription_id)
            )
            self._subscriptions[subscription_id] = (observer, subscription)
            state = self._state or state
            self._last_notified_authoritative_key = (
                self._current_authoritative_key
            )
        subscription.deliver(observer, state)
        return subscription

    def close(self) -> None:
        # Do not wait for a backend read that is already in flight. Marking the
        # projection closed makes its post-read commit a no-op and lets Adapter
        # close remain bounded even when an Application dependency is blocked.
        with self._lock:
            if self._closed:
                return
            self._closed = True
            subscriptions = tuple(
                subscription
                for _, subscription in self._subscriptions.values()
            )
            self._subscriptions.clear()
        for subscription in subscriptions:
            subscription.mark_disposed()

    def publish_authoritative_observation(self) -> None:
        with self._transition_lock:
            with self._lock:
                if self._closed or not self._connected:
                    return
            self._refresh(
                recovery_phase=RuntimeHealthRecoveryPhase.IDLE,
                notify=True,
            )

    def publish_sampling_tick(self) -> None:
        with self._transition_lock:
            with self._lock:
                if self._closed:
                    return
                connected = self._connected
                state = self._state
            if connected:
                self._refresh_transition(
                    recovery_phase=RuntimeHealthRecoveryPhase.IDLE,
                    notify=True,
                    reread=False,
                )
                return
            if state is not None:
                aged = self._age_state(state)
                if aged is not state:
                    self._store_and_deliver(aged)

    def mark_disconnected(self, *, generation: int | None = None) -> None:
        with self._transition_lock:
            with self._lock:
                if self._closed or not self._connected:
                    return
                self._connected = False
                if generation is not None:
                    self._generation = SourceGenerationId(generation)
            self._publish_retained(
                recovery_phase=RuntimeHealthRecoveryPhase.DISCONNECTED,
                error=self._disconnected_error(),
                notify=True,
            )

    def mark_reconnected(self, *, generation: int | None = None) -> None:
        with self._transition_lock:
            with self._lock:
                if self._closed or self._connected:
                    return
                self._connected = True
                self._generation = SourceGenerationId(
                    generation
                    if generation is not None
                    else self._generation.value + 1
                )
                has_state = self._state is not None
            if not has_state:
                return
            self._publish_retained(
                recovery_phase=RuntimeHealthRecoveryPhase.REREADING,
                error=None,
                notify=True,
            )
            self._refresh(
                recovery_phase=RuntimeHealthRecoveryPhase.RECOVERED,
                notify=True,
                reread=True,
            )

    def set_generation(self, generation: int) -> None:
        with self._transition_lock:
            with self._lock:
                if not self._closed:
                    self._generation = SourceGenerationId(generation)

    def is_current_generation(self, generation: int) -> bool:
        with self._lock:
            return (
                not self._closed
                and self._connected
                and self._generation.value == generation
            )

    def _refresh(
        self,
        *,
        recovery_phase: RuntimeHealthRecoveryPhase,
        notify: bool,
        reread: bool = False,
    ) -> SystemHealthViewState:
        with self._transition_lock:
            return self._refresh_transition(
                recovery_phase=recovery_phase,
                notify=notify,
                reread=reread,
            )

    def _refresh_transition(
        self,
        *,
        recovery_phase: RuntimeHealthRecoveryPhase,
        notify: bool,
        reread: bool,
    ) -> SystemHealthViewState:
        result = self._read_runtime_health()
        queue_result = self._read_diagnostic_queue_health()
        cache_result = self._read_diagnostic_cache_health()
        authoritative_key = _authoritative_result_key(
            result,
            queue_result,
            cache_result,
        )
        now = _aware(self._clock())
        if notify and not reread and recovery_phase is RuntimeHealthRecoveryPhase.IDLE:
            with self._lock:
                current = self._state
                unchanged = (
                    authoritative_key
                    == self._last_notified_authoritative_key
                )
            if (
                current is not None
                and unchanged
                and not _needs_time_projection_update(current, now)
            ):
                return current
        with self._lock:
            self._ensure_open()
            revision = self._next_revision_locked()
            generation = self._generation
        queue_component = _project_queue_component(
            queue_result,
            revision=revision,
            now=now,
            freshness_threshold=self._freshness_threshold,
            last_reliable=self._last_reliable_queue,
            recovery_phase=recovery_phase,
            reread=reread,
        )
        cache_component = _project_cache_component(
            cache_result,
            revision=revision,
            now=now,
            freshness_threshold=self._freshness_threshold,
            last_reliable=self._last_reliable_cache,
            recovery_phase=recovery_phase,
            reread=reread,
        )
        if (
            result.availability is RuntimeHealthApplicationAvailability.READY
            and result.observation is not None
        ):
            component = RuntimeHealthComponent(
                identity=RuntimeHealthComponentIdentity.APPLICATION_RUNTIME,
                classification=result.observation.classification,
                revision=revision,
                observed_at=result.observation.observed_at,
                last_successful_observation_at=result.observation.observed_at,
                explanation=result.observation.explanation,
            )
            presentation = _presentation_for(component.classification)
            complete = component.classification in {
                RuntimeHealthClassification.HEALTHY,
                RuntimeHealthClassification.DEGRADED,
            }
            state = SystemHealthViewState(
                interface_version=SYSTEM_HEALTH_INTERFACE_VERSION,
                revision=revision,
                observed_at=now,
                last_reliable_at=component.observed_at,
                freshness=Freshness.FRESH,
                age=max(now - component.observed_at, timedelta(0)),
                freshness_threshold=self._freshness_threshold,
                source=SystemHealthSource(
                    kind=self._source_kind,
                    identity=self._source_identity,
                    generation=generation,
                ),
                context=self._context,
                phase=(ViewPhase.READY if complete else ViewPhase.DEGRADED),
                presentation=presentation,
                completeness=(Completeness.COMPLETE if complete else Completeness.PARTIAL),
                components=(component,),
                last_reliable_payload=component,
                recovery_phase=recovery_phase,
                diagnostic_queue=queue_component,
                diagnostic_cache=cache_component,
                error=None,
            )
        else:
            error = _feature_error(result, reread=reread)
            if self._last_reliable is not None:
                state = self._retained_state(
                    revision=revision,
                    observed_at=now,
                    generation=generation,
                    recovery_phase=(
                        RuntimeHealthRecoveryPhase.FAILED
                        if reread
                        else recovery_phase
                    ),
                    error=error,
                )
            else:
                unknown = result.availability is (
                    RuntimeHealthApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
                )
                state = SystemHealthViewState(
                    interface_version=SYSTEM_HEALTH_INTERFACE_VERSION,
                    revision=revision,
                    observed_at=now,
                    last_reliable_at=None,
                    freshness=Freshness.AWAITING_FIRST_STATE,
                    age=timedelta(0),
                    freshness_threshold=self._freshness_threshold,
                    source=SystemHealthSource(
                        kind=self._source_kind,
                        identity=self._source_identity,
                        generation=generation,
                    ),
                    context=self._context,
                    phase=ViewPhase.LOADING if unknown else ViewPhase.FAILED,
                    presentation=(
                        SystemHealthPresentationState.UNKNOWN
                        if unknown
                        else SystemHealthPresentationState.UNAVAILABLE
                    ),
                    completeness=Completeness.UNKNOWN,
                    components=(),
                    last_reliable_payload=None,
                    recovery_phase=(
                        RuntimeHealthRecoveryPhase.FAILED
                        if reread
                        else recovery_phase
                    ),
                    diagnostic_queue=queue_component,
                    diagnostic_cache=cache_component,
                    error=error,
                )
        with self._lock:
            self._current_authoritative_key = authoritative_key
            if notify:
                self._last_notified_authoritative_key = authoritative_key
        return self._store_and_deliver(state, notify=notify)

    def _publish_retained(
        self,
        *,
        recovery_phase: RuntimeHealthRecoveryPhase,
        error: SystemHealthError | None,
        notify: bool,
    ) -> SystemHealthViewState:
        with self._transition_lock:
            return self._publish_retained_transition(
                recovery_phase=recovery_phase,
                error=error,
                notify=notify,
            )

    def _publish_retained_transition(
        self,
        *,
        recovery_phase: RuntimeHealthRecoveryPhase,
        error: SystemHealthError | None,
        notify: bool,
    ) -> SystemHealthViewState:
        with self._lock:
            self._ensure_open()
            revision = self._next_revision_locked()
            generation = self._generation
        state = self._retained_state(
            revision=revision,
            observed_at=_aware(self._clock()),
            generation=generation,
            recovery_phase=recovery_phase,
            error=error,
        )
        return self._store_and_deliver(state, notify=notify)

    def _retained_state(
        self,
        *,
        revision: int,
        observed_at: datetime,
        generation: SourceGenerationId,
        recovery_phase: RuntimeHealthRecoveryPhase,
        error: SystemHealthError | None,
    ) -> SystemHealthViewState:
        reliable = self._last_reliable
        queue_component = _retained_queue_component(
            self._last_reliable_queue,
            revision=revision,
            now=observed_at,
            freshness_threshold=self._freshness_threshold,
            recovery_phase=recovery_phase,
        )
        cache_component = _retained_cache_component(
            self._last_reliable_cache,
            revision=revision,
            now=observed_at,
            freshness_threshold=self._freshness_threshold,
            recovery_phase=recovery_phase,
        )
        if reliable is None:
            return SystemHealthViewState(
                interface_version=SYSTEM_HEALTH_INTERFACE_VERSION,
                revision=revision,
                observed_at=observed_at,
                last_reliable_at=None,
                freshness=(
                    Freshness.DISCONNECTED
                    if recovery_phase is RuntimeHealthRecoveryPhase.DISCONNECTED
                    else Freshness.AWAITING_FIRST_STATE
                ),
                age=timedelta(0),
                freshness_threshold=self._freshness_threshold,
                source=SystemHealthSource(
                    kind=self._source_kind,
                    identity=self._source_identity,
                    generation=generation,
                ),
                context=self._context,
                phase=(
                    ViewPhase.FAILED
                    if recovery_phase
                    in {
                        RuntimeHealthRecoveryPhase.DISCONNECTED,
                        RuntimeHealthRecoveryPhase.FAILED,
                    }
                    else ViewPhase.LOADING
                ),
                presentation=(
                    SystemHealthPresentationState.UNAVAILABLE
                    if recovery_phase is RuntimeHealthRecoveryPhase.DISCONNECTED
                    else SystemHealthPresentationState.UNKNOWN
                ),
                completeness=Completeness.UNKNOWN,
                components=(),
                last_reliable_payload=None,
                recovery_phase=recovery_phase,
                diagnostic_queue=queue_component,
                diagnostic_cache=cache_component,
                error=error,
            )

        age = max(observed_at - reliable.observed_at, timedelta(0))
        is_stale = age > self._freshness_threshold
        classification = (
            RuntimeHealthClassification.STALE
            if is_stale
            else RuntimeHealthClassification.DEGRADED
        )
        component = replace(
            reliable,
            classification=classification,
            revision=revision,
            observed_at=observed_at,
            explanation=(
                "Runtime Health is stale; showing the last reliable observation."
                if is_stale
                else "Runtime Health is degraded; showing the last reliable observation."
            ),
        )
        return SystemHealthViewState(
            interface_version=SYSTEM_HEALTH_INTERFACE_VERSION,
            revision=revision,
            observed_at=observed_at,
            last_reliable_at=reliable.observed_at,
            freshness=(
                Freshness.STALE
                if is_stale
                or recovery_phase is not RuntimeHealthRecoveryPhase.DISCONNECTED
                else Freshness.DISCONNECTED
            ),
            age=age,
            freshness_threshold=self._freshness_threshold,
            source=SystemHealthSource(
                kind=self._source_kind,
                identity=self._source_identity,
                generation=generation,
            ),
            context=self._context,
            phase=ViewPhase.DEGRADED,
            presentation=(
                SystemHealthPresentationState.STALE
                if is_stale
                else SystemHealthPresentationState.DEGRADED
            ),
            completeness=Completeness.PARTIAL,
            components=(component,),
            last_reliable_payload=reliable,
            recovery_phase=recovery_phase,
            diagnostic_queue=queue_component,
            diagnostic_cache=cache_component,
            error=error,
        )

    def _age_state(self, state: SystemHealthViewState) -> SystemHealthViewState:
        reliable = state.last_reliable_payload
        if reliable is None:
            return state
        now = _aware(self._clock())
        age = max(now - reliable.observed_at, timedelta(0))
        if age == state.age:
            return state
        with self._lock:
            revision = self._next_revision_locked()
            generation = self._generation
        queue_component = _retained_queue_component(
            self._last_reliable_queue,
            revision=revision,
            now=now,
            freshness_threshold=self._freshness_threshold,
            recovery_phase=state.recovery_phase,
        )
        cache_component = _retained_cache_component(
            self._last_reliable_cache,
            revision=revision,
            now=now,
            freshness_threshold=self._freshness_threshold,
            recovery_phase=state.recovery_phase,
        )
        if age <= self._freshness_threshold:
            return replace(
                state,
                revision=revision,
                observed_at=now,
                age=age,
                source=replace(state.source, generation=generation),
                diagnostic_queue=queue_component,
                diagnostic_cache=cache_component,
            )
        if state.presentation is SystemHealthPresentationState.STALE:
            return replace(
                state,
                revision=revision,
                observed_at=now,
                age=age,
                source=replace(state.source, generation=generation),
                diagnostic_queue=queue_component,
                diagnostic_cache=cache_component,
            )
        return self._retained_state(
            revision=revision,
            observed_at=now,
            generation=generation,
            recovery_phase=state.recovery_phase,
            error=state.error,
        )

    def _store_and_deliver(
        self,
        state: SystemHealthViewState,
        *,
        notify: bool = True,
    ) -> SystemHealthViewState:
        with self._lock:
            if self._closed:
                return self._state or state
            if self._state is not None and state.revision <= self._state.revision:
                return self._state
            self._state = state
            if state.error is None and state.last_reliable_payload is not None:
                self._last_reliable = state.last_reliable_payload
            if state.diagnostic_queue.classification in {
                DiagnosticQueueHealthClassification.HEALTHY,
                DiagnosticQueueHealthClassification.DEGRADED,
            }:
                self._last_reliable_queue = state.diagnostic_queue
            if state.diagnostic_cache.classification in {
                DiagnosticCacheHealthClassification.HEALTHY,
                DiagnosticCacheHealthClassification.FALLBACK,
            }:
                self._last_reliable_cache = state.diagnostic_cache
            deliveries = tuple(self._subscriptions.values()) if notify else ()
        for observer, subscription in deliveries:
            subscription.deliver(observer, state)
        return state

    def _remove_subscription(self, subscription_id: int) -> None:
        with self._lock:
            self._subscriptions.pop(subscription_id, None)

    def _next_revision_locked(self) -> int:
        self._revision += 1
        return self._revision

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("System Health adapter is closed")

    @staticmethod
    def _require_context(context: SystemHealthContext) -> None:
        if not isinstance(context, SystemHealthContext):
            raise TypeError("context must be a SystemHealthContext")

    @staticmethod
    def _disconnected_error() -> SystemHealthError:
        return SystemHealthError(
            code=SystemHealthErrorCode.SOURCE_DISCONNECTED,
            explanation=(
                "Runtime Health is disconnected; the last reliable observation "
                "is retained when available."
            ),
            retryable=True,
        )


class LiveSystemHealthAdapter:
    """Live Feature seam backed by one shared DiagnosticsApplication."""

    def __init__(
        self,
        *,
        application_health: StrategyDiagnosticsV1SystemHealthApplication,
        event_bridge: EventBridge,
        clock: Callable[[], datetime] | None = None,
        freshness_threshold: timedelta = timedelta(seconds=30),
        sampling_interval: timedelta | None = timedelta(seconds=1),
    ) -> None:
        if sampling_interval is not None and sampling_interval <= timedelta(0):
            raise ValueError("System Health sampling interval must be positive")
        self._event_bridge = event_bridge
        self._closed = False
        self._lock = RLock()
        self._sampling_interval = sampling_interval
        self._worker_wake = Event()
        self._worker_thread: Thread | None = None
        self._pending_refresh_generation: int | None = None
        self._pending_connection_actions: list[
            tuple[EventBridgeConnectionPhase, int, bool]
        ] = []
        self._connection_sequence = 0
        self._connection_generation = 1
        self._dispose_connection_subscription: Callable[[], None] = lambda: None
        self._dispose_batch_subscription: Callable[[], None] = lambda: None
        active_clock = clock or _default_live_clock
        queue_reader = getattr(
            application_health,
            "read_diagnostic_queue_health",
            None,
        )
        cache_reader = getattr(
            application_health,
            "read_diagnostic_cache_health",
            None,
        )
        self._projection = _SystemHealthProjection(
            read_runtime_health=application_health.read_runtime_health,
            read_diagnostic_queue_health=(
                queue_reader
                if callable(queue_reader)
                else lambda: _unobserved_queue_result(active_clock())
            ),
            read_diagnostic_cache_health=(
                cache_reader
                if callable(cache_reader)
                else lambda: _unobserved_cache_result(active_clock())
            ),
            source_kind=SourceKind.LIVE_RUNTIME,
            source_identity="diagnostics_application",
            clock=active_clock,
            freshness_threshold=freshness_threshold,
        )
        self._dispose_connection_subscription = (
            event_bridge.subscribe_connection_state(
                self._on_connection_state,
                replay_current=True,
            )
        )
        self._dispose_batch_subscription = event_bridge.subscribe_batches(
            self._on_snapshot_batch
        )
        self._worker_thread = Thread(
            target=self._worker_loop,
            name="system-health-worker",
            daemon=True,
        )
        self._worker_thread.start()

    @property
    def interface_version(self) -> FeatureInterfaceVersion:
        return self._projection.interface_version

    def snapshot(self, context: SystemHealthContext) -> SystemHealthViewState:
        return self._projection.snapshot(context)

    def subscribe(
        self,
        context: SystemHealthContext,
        observer: SystemHealthObserver,
    ) -> Subscription:
        return self._projection.subscribe(context, observer)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            dispose_batches = self._dispose_batch_subscription
            dispose_connection = self._dispose_connection_subscription
            worker_thread = self._worker_thread
            self._worker_thread = None
            self._dispose_batch_subscription = lambda: None
            self._dispose_connection_subscription = lambda: None
            self._worker_wake.set()
        dispose_batches()
        dispose_connection()
        self._projection.close()
        if worker_thread is not None and worker_thread is not current_thread():
            worker_thread.join(timeout=0)

    def _on_snapshot_batch(self, batch: EventBridgeBatch) -> None:
        if not any(
            str(snapshot.get("feature", "")).casefold()
            in {
                "system_health",
                "diagnostic_tasks",
                "scenario_lab",
                "evidence_and_findings",
            }
            for snapshot in batch.snapshots
        ):
            return
        with self._lock:
            if (
                self._closed
                or batch.generation.value != self._connection_generation
            ):
                return
            self._pending_refresh_generation = batch.generation.value
            self._worker_wake.set()

    def _on_connection_state(self, state: EventBridgeConnectionState) -> None:
        with self._lock:
            if self._closed or state.sequence.value <= self._connection_sequence:
                return
            first_observation = self._connection_sequence == 0
            self._connection_sequence = state.sequence.value
            self._connection_generation = state.generation.value
            self._pending_connection_actions.append(
                (state.phase, state.generation.value, first_observation)
            )
            self._worker_wake.set()

    def _worker_loop(self) -> None:
        interval = self._sampling_interval
        timeout = None if interval is None else interval.total_seconds()
        while True:
            signaled = self._worker_wake.wait(timeout)
            self._worker_wake.clear()
            with self._lock:
                if self._closed:
                    return
                connection_actions = tuple(self._pending_connection_actions)
                self._pending_connection_actions.clear()
                refresh_generation = self._pending_refresh_generation
                self._pending_refresh_generation = None
            for phase, generation, first_observation in connection_actions:
                try:
                    if phase is EventBridgeConnectionPhase.DISCONNECTED:
                        self._projection.mark_disconnected(generation=generation)
                    elif first_observation:
                        self._projection.set_generation(generation)
                    else:
                        self._projection.mark_reconnected(generation=generation)
                except RuntimeError:
                    with self._lock:
                        if not self._closed:
                            raise
                    return
            should_refresh = not signaled or refresh_generation is not None
            if not should_refresh:
                continue
            if (
                refresh_generation is not None
                and not self._projection.is_current_generation(refresh_generation)
            ):
                continue
            try:
                if not signaled:
                    self._projection.publish_sampling_tick()
                else:
                    self._projection.publish_authoritative_observation()
            except RuntimeError:
                with self._lock:
                    if not self._closed:
                        raise
                return


class DeterministicFakeSystemHealthAdapter:
    """Deterministic fake for the external System Health Feature seam."""

    def __init__(
        self,
        *,
        initially_healthy: bool = False,
        clock: Callable[[], datetime] | None = None,
        freshness_threshold: timedelta = timedelta(seconds=30),
    ) -> None:
        self._now = _aware((clock or _default_fake_clock)())
        self._external_clock = clock
        self._healthy = initially_healthy
        self._failed = False
        self._queue_mode = "healthy" if initially_healthy else "unknown"
        self._cache_mode = "healthy" if initially_healthy else "unknown"
        self._queue_pending_count = 0
        self._queue_pending_since: datetime | None = None
        self._cache_last_refresh_at = self._now
        self._cache_generation = 1
        self._source_revision = 0
        self._projection = _SystemHealthProjection(
            read_runtime_health=self._read_runtime_health,
            read_diagnostic_queue_health=self._read_diagnostic_queue_health,
            read_diagnostic_cache_health=self._read_diagnostic_cache_health,
            source_kind=SourceKind.DETERMINISTIC_FAKE,
            source_identity="deterministic_system_health",
            clock=self._clock,
            freshness_threshold=freshness_threshold,
        )

    @property
    def interface_version(self) -> FeatureInterfaceVersion:
        return self._projection.interface_version

    def snapshot(self, context: SystemHealthContext) -> SystemHealthViewState:
        return self._projection.snapshot(context)

    def subscribe(
        self,
        context: SystemHealthContext,
        observer: SystemHealthObserver,
    ) -> Subscription:
        return self._projection.subscribe(context, observer)

    def close(self) -> None:
        self._projection.close()

    def advance_to_healthy(self) -> None:
        self._healthy = True
        self._failed = False
        self._queue_mode = "healthy"
        self._cache_mode = "healthy"
        self._cache_last_refresh_at = self._clock()
        self._cache_generation += 1
        self.publish_authoritative_observation()

    def advance_to_failed(self) -> None:
        self._failed = True
        self._queue_mode = "unavailable"
        self._cache_mode = "unavailable"
        self.publish_authoritative_observation()

    def advance_queue_to_backlog(self, *, pending_count: int = 2) -> None:
        if pending_count < 1:
            raise ValueError("backlog pending count must be positive")
        self._queue_mode = "backlog"
        self._queue_pending_count = pending_count
        self._queue_pending_since = self._clock()
        self.publish_authoritative_observation()

    def advance_queue_to_running(self) -> None:
        self._queue_mode = "running"
        self.publish_authoritative_observation()

    def advance_queue_to_blocked(self) -> None:
        self._queue_mode = "blocked"
        self.publish_authoritative_observation()

    def advance_queue_to_unavailable(self) -> None:
        self._queue_mode = "unavailable"
        self.publish_authoritative_observation()

    def advance_cache_to_fallback(self) -> None:
        self._cache_mode = "fallback"
        self._cache_last_refresh_at = self._clock()
        self._cache_generation += 1
        self.publish_authoritative_observation()

    def advance_cache_to_incompatible(self) -> None:
        self._cache_mode = "incompatible"
        self._cache_last_refresh_at = self._clock()
        self._cache_generation += 1
        self.publish_authoritative_observation()

    def advance_cache_to_unavailable(self) -> None:
        self._cache_mode = "unavailable"
        self.publish_authoritative_observation()

    def advance_cache_to_healthy(self) -> None:
        self._cache_mode = "healthy"
        self._cache_last_refresh_at = self._clock()
        self._cache_generation += 1
        self.publish_authoritative_observation()

    def publish_authoritative_observation(self) -> None:
        self._projection.publish_authoritative_observation()

    def advance_to_disconnected(self) -> None:
        self._projection.mark_disconnected()

    def advance_to_reconnected(self) -> None:
        self._projection.mark_reconnected()

    def advance_clock(self, delta: timedelta) -> None:
        if delta < timedelta(0):
            raise ValueError("Deterministic System Health clock cannot go backwards")
        self._now += delta

    def _clock(self) -> datetime:
        if self._external_clock is not None:
            return _aware(self._external_clock())
        return self._now

    def _read_runtime_health(self) -> RuntimeHealthApplicationResult:
        observed_at = self._clock()
        if self._failed:
            return RuntimeHealthApplicationResult(
                availability=RuntimeHealthApplicationAvailability.FAILED,
                observation=None,
                source_token=None,
                observed_at=observed_at,
                error=RuntimeHealthApplicationError(
                    code=RuntimeHealthApplicationErrorCode.READ_FAILED,
                    explanation="The deterministic Runtime Health read failed.",
                    retryable=True,
                ),
            )
        if not self._healthy:
            return RuntimeHealthApplicationResult(
                availability=(
                    RuntimeHealthApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
                ),
                observation=None,
                source_token=None,
                observed_at=observed_at,
                error=RuntimeHealthApplicationError(
                    code=(
                        RuntimeHealthApplicationErrorCode.NO_AUTHORITATIVE_OBSERVATION
                    ),
                    explanation=(
                        "No authoritative Runtime Health observation is available."
                    ),
                    retryable=True,
                ),
            )
        self._source_revision += 1
        return RuntimeHealthApplicationResult(
            availability=RuntimeHealthApplicationAvailability.READY,
            observation=RuntimeHealthApplicationObservation(
                classification=RuntimeHealthClassification.HEALTHY,
                observed_at=observed_at,
                explanation="Diagnostics runtime is ready.",
            ),
            source_token=SourceRevisionToken(
                hashlib.sha256(
                    f"deterministic-runtime-health-{self._source_revision}".encode(
                        "utf-8"
                    )
                ).hexdigest()
            ),
            observed_at=observed_at,
            error=None,
        )

    def _read_diagnostic_queue_health(self) -> DiagnosticQueueApplicationResult:
        observed_at = self._clock()
        if self._queue_mode == "unknown":
            return _unobserved_queue_result(observed_at)
        if self._queue_mode == "unavailable":
            return DiagnosticQueueApplicationResult(
                availability=DiagnosticQueueApplicationAvailability.FAILED,
                observation=None,
                source_token=None,
                observed_at=observed_at,
                error=DiagnosticQueueApplicationError(
                    code=DiagnosticQueueApplicationErrorCode.READ_FAILED,
                    explanation="The deterministic Diagnostic Queue read failed.",
                    retryable=True,
                ),
            )
        pending = self._queue_pending_count if self._queue_mode == "backlog" else 0
        running = 1 if self._queue_mode in {"backlog", "running"} else 0
        blocked = 1 if self._queue_mode == "blocked" else 0
        consumer = (
            DiagnosticQueueConsumerAvailability.BLOCKED
            if blocked
            else DiagnosticQueueConsumerAvailability.UNKNOWN
            if pending and not running
            else DiagnosticQueueConsumerAvailability.AVAILABLE
        )
        reason = (
            DiagnosticQueueBlockageReason.PAUSED_DIAGNOSTIC_WORK
            if blocked
            else DiagnosticQueueBlockageReason.RECOVERY_REQUIRED
            if pending
            else DiagnosticQueueBlockageReason.NONE
        )
        explanation = (
            "Diagnostic work is paused at a supported lifecycle boundary."
            if blocked
            else "Diagnostic work is queued and awaiting a consumer observation."
            if pending
            else "Diagnostic work is being consumed without a reported blockage."
            if running
            else "The Diagnostic Queue is empty and available."
        )
        token = hashlib.sha256(
            f"fake-queue|{self._queue_mode}|{pending}".encode("utf-8")
        ).hexdigest()
        return DiagnosticQueueApplicationResult(
            availability=DiagnosticQueueApplicationAvailability.READY,
            observation=DiagnosticQueueApplicationObservation(
                pending_count=pending,
                running_count=running,
                blocked_count=blocked,
                oldest_pending_at=(
                    self._queue_pending_since if pending else None
                ),
                consumer_availability=consumer,
                blockage_reason=reason,
                affected_scope=(
                    DiagnosticQueueScope.DIAGNOSTIC_TASK,
                    DiagnosticQueueScope.FORMAL_DIAGNOSTIC_CAMPAIGN,
                    DiagnosticQueueScope.CAMPAIGN_NODES,
                ),
                observed_at=observed_at,
                explanation=explanation,
            ),
            source_token=SourceRevisionToken(token),
            observed_at=observed_at,
            error=None,
        )

    def _read_diagnostic_cache_health(self) -> DiagnosticCacheApplicationResult:
        observed_at = self._clock()
        if self._cache_mode == "unknown":
            return _unobserved_cache_result(observed_at)
        if self._cache_mode == "unavailable":
            return DiagnosticCacheApplicationResult(
                availability=DiagnosticCacheApplicationAvailability.READY,
                observation=DiagnosticCacheApplicationObservation(
                    generation=self._cache_generation,
                    fallback=DiagnosticCacheFallbackState.UNAVAILABLE,
                    last_refresh_result=DiagnosticCacheLastRefreshResult.FAILED,
                    compatibility=DiagnosticCacheCompatibility.COMPATIBLE,
                    affected_scope=(
                        DiagnosticCacheScope.REFERENCE_MARKET_PATHS,
                        DiagnosticCacheScope.DIAGNOSTIC_EVIDENCE,
                    ),
                    last_refresh_at=observed_at,
                    observed_at=observed_at,
                    explanation="The deterministic Diagnostic Cache refresh failed.",
                ),
                source_token=SourceRevisionToken(
                    hashlib.sha256(b"fake-cache-unavailable").hexdigest()
                ),
                observed_at=observed_at,
                error=None,
            )
        fallback = (
            DiagnosticCacheFallbackState.ACTIVE
            if self._cache_mode == "fallback"
            else DiagnosticCacheFallbackState.UNAVAILABLE
            if self._cache_mode == "incompatible"
            else DiagnosticCacheFallbackState.PRIMARY
        )
        refresh_result = (
            DiagnosticCacheLastRefreshResult.FALLBACK_SUCCEEDED
            if self._cache_mode == "fallback"
            else DiagnosticCacheLastRefreshResult.FAILED
            if self._cache_mode == "incompatible"
            else DiagnosticCacheLastRefreshResult.SUCCEEDED
        )
        compatibility = (
            DiagnosticCacheCompatibility.INCOMPATIBLE
            if self._cache_mode == "incompatible"
            else DiagnosticCacheCompatibility.COMPATIBLE
        )
        explanation = (
            "The Diagnostic Cache observation is incompatible."
            if self._cache_mode == "incompatible"
            else "The Diagnostic Cache is serving a verified fallback."
            if self._cache_mode == "fallback"
            else "The Diagnostic Cache refresh completed successfully."
        )
        token = hashlib.sha256(
            f"fake-cache|{self._cache_mode}|{self._cache_generation}".encode(
                "utf-8"
            )
        ).hexdigest()
        return DiagnosticCacheApplicationResult(
            availability=DiagnosticCacheApplicationAvailability.READY,
            observation=DiagnosticCacheApplicationObservation(
                generation=self._cache_generation,
                fallback=fallback,
                last_refresh_result=refresh_result,
                compatibility=compatibility,
                affected_scope=(
                    DiagnosticCacheScope.REFERENCE_MARKET_PATHS,
                    DiagnosticCacheScope.DIAGNOSTIC_EVIDENCE,
                ),
                last_refresh_at=self._cache_last_refresh_at,
                observed_at=observed_at,
                explanation=explanation,
            ),
            source_token=SourceRevisionToken(token),
            observed_at=observed_at,
            error=None,
        )


def _authoritative_result_key(
    runtime: RuntimeHealthApplicationResult,
    queue: DiagnosticQueueApplicationResult,
    cache: DiagnosticCacheApplicationResult,
) -> tuple[str, ...]:
    return (
        *_application_result_key(runtime),
        *_application_result_key(queue),
        *_application_result_key(cache),
    )


def _application_result_key(result: object) -> tuple[str, str, str]:
    availability = getattr(getattr(result, "availability", None), "value", "unknown")
    source_token = getattr(getattr(result, "source_token", None), "value", "none")
    error_code = getattr(
        getattr(getattr(result, "error", None), "code", None),
        "value",
        "none",
    )
    return str(availability), str(source_token), str(error_code)


def _needs_time_projection_update(
    state: SystemHealthViewState,
    now: datetime,
) -> bool:
    elapsed = max(now - state.observed_at, timedelta(0))
    if elapsed <= timedelta(0):
        return False
    queue_age = state.diagnostic_queue.oldest_pending_age
    if queue_age is not None:
        if _age_bucket(queue_age + elapsed) != _age_bucket(queue_age):
            return True
    cache = state.diagnostic_cache
    if cache.freshness in {Freshness.FRESH, Freshness.STALE}:
        advanced_cache_age = cache.age + elapsed
        if _age_bucket(advanced_cache_age) != _age_bucket(cache.age):
            return True
        if (
            cache.freshness is Freshness.FRESH
            and advanced_cache_age > cache.freshness_threshold
        ):
            return True
    return False


def _age_bucket(value: timedelta) -> int:
    return max(int(value.total_seconds()), 0)


def _project_queue_component(
    result: DiagnosticQueueApplicationResult,
    *,
    revision: int,
    now: datetime,
    freshness_threshold: timedelta,
    last_reliable: DiagnosticQueueHealthComponent | None,
    recovery_phase: RuntimeHealthRecoveryPhase,
    reread: bool,
) -> DiagnosticQueueHealthComponent:
    observation = result.observation
    if (
        result.availability is DiagnosticQueueApplicationAvailability.READY
        and observation is not None
    ):
        age = max(now - observation.observed_at, timedelta(0))
        freshness = (
            Freshness.STALE if age > freshness_threshold else Freshness.FRESH
        )
        component_recovery = _queue_recovery_phase(recovery_phase, reread=reread)
        if freshness is Freshness.STALE:
            classification = DiagnosticQueueHealthClassification.STALE
        elif component_recovery is DiagnosticQueueRecoveryPhase.RECOVERING:
            classification = DiagnosticQueueHealthClassification.RECOVERING
        elif observation.consumer_availability is (
            DiagnosticQueueConsumerAvailability.UNAVAILABLE
        ):
            classification = DiagnosticQueueHealthClassification.UNAVAILABLE
        elif (
            observation.pending_count
            or observation.blocked_count
            or observation.consumer_availability
            in {
                DiagnosticQueueConsumerAvailability.BLOCKED,
                DiagnosticQueueConsumerAvailability.UNKNOWN,
            }
        ):
            classification = DiagnosticQueueHealthClassification.DEGRADED
        else:
            classification = DiagnosticQueueHealthClassification.HEALTHY
        return DiagnosticQueueHealthComponent(
            classification=classification,
            revision=revision,
            observed_at=observation.observed_at,
            freshness=freshness,
            age=age,
            freshness_threshold=freshness_threshold,
            pending_count=observation.pending_count,
            running_count=observation.running_count,
            blocked_count=observation.blocked_count,
            oldest_pending_age=(
                None
                if observation.oldest_pending_at is None
                else max(now - observation.oldest_pending_at, timedelta(0))
            ),
            consumer_availability=observation.consumer_availability,
            blockage_reason=observation.blockage_reason,
            affected_scope=observation.affected_scope,
            recovery_phase=component_recovery,
            explanation=observation.explanation,
            error=None,
        )
    if last_reliable is not None:
        return _retained_queue_component(
            last_reliable,
            revision=revision,
            now=now,
            freshness_threshold=freshness_threshold,
            recovery_phase=(
                RuntimeHealthRecoveryPhase.FAILED
                if reread
                else recovery_phase
            ),
            error=_queue_feature_error(result, reread=reread),
        )
    unknown = result.availability is (
        DiagnosticQueueApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
    )
    return DiagnosticQueueHealthComponent(
        classification=(
            DiagnosticQueueHealthClassification.UNKNOWN
            if unknown
            else DiagnosticQueueHealthClassification.UNAVAILABLE
        ),
        revision=revision,
        observed_at=now,
        freshness=Freshness.AWAITING_FIRST_STATE,
        age=timedelta(0),
        freshness_threshold=freshness_threshold,
        pending_count=0,
        running_count=0,
        blocked_count=0,
        oldest_pending_age=None,
        consumer_availability=(
            DiagnosticQueueConsumerAvailability.UNKNOWN
            if unknown
            else DiagnosticQueueConsumerAvailability.UNAVAILABLE
        ),
        blockage_reason=(
            DiagnosticQueueBlockageReason.UNKNOWN
            if unknown
            else DiagnosticQueueBlockageReason.SOURCE_UNAVAILABLE
        ),
        affected_scope=(DiagnosticQueueScope.DIAGNOSTIC_TASK,),
        recovery_phase=(
            DiagnosticQueueRecoveryPhase.FAILED_RECOVERY
            if reread
            else DiagnosticQueueRecoveryPhase.IDLE
        ),
        explanation=(
            "No authoritative Diagnostic Queue observation is available."
            if unknown
            else "The Diagnostic Queue observation is unavailable."
        ),
        error=_queue_feature_error(result, reread=reread),
    )


def _project_cache_component(
    result: DiagnosticCacheApplicationResult,
    *,
    revision: int,
    now: datetime,
    freshness_threshold: timedelta,
    last_reliable: DiagnosticCacheHealthComponent | None,
    recovery_phase: RuntimeHealthRecoveryPhase,
    reread: bool,
) -> DiagnosticCacheHealthComponent:
    observation = result.observation
    if (
        result.availability is DiagnosticCacheApplicationAvailability.READY
        and observation is not None
    ):
        age = max(now - observation.last_refresh_at, timedelta(0))
        freshness = (
            Freshness.STALE if age > freshness_threshold else Freshness.FRESH
        )
        recovery_failed = reread and (
            observation.last_refresh_result
            is DiagnosticCacheLastRefreshResult.FAILED
            or observation.compatibility
            is DiagnosticCacheCompatibility.INCOMPATIBLE
        )
        component_recovery = (
            DiagnosticCacheRecoveryPhase.FAILED_RECOVERY
            if recovery_failed
            else _cache_recovery_phase(recovery_phase, reread=reread)
        )
        if observation.compatibility is DiagnosticCacheCompatibility.INCOMPATIBLE:
            classification = DiagnosticCacheHealthClassification.INCOMPATIBLE
        elif freshness is Freshness.STALE:
            classification = DiagnosticCacheHealthClassification.STALE
        elif component_recovery is DiagnosticCacheRecoveryPhase.RECOVERING:
            classification = DiagnosticCacheHealthClassification.RECOVERING
        elif observation.fallback is DiagnosticCacheFallbackState.ACTIVE:
            classification = DiagnosticCacheHealthClassification.FALLBACK
        elif observation.last_refresh_result is DiagnosticCacheLastRefreshResult.FAILED:
            classification = DiagnosticCacheHealthClassification.UNAVAILABLE
        else:
            classification = DiagnosticCacheHealthClassification.HEALTHY
        return DiagnosticCacheHealthComponent(
            classification=classification,
            revision=revision,
            observed_at=observation.observed_at,
            freshness=freshness,
            age=age,
            freshness_threshold=freshness_threshold,
            generation=(
                None
                if observation.generation is None
                else SourceGenerationId(observation.generation)
            ),
            fallback=observation.fallback,
            last_refresh_result=observation.last_refresh_result,
            compatibility=observation.compatibility,
            affected_scope=observation.affected_scope,
            recovery_phase=component_recovery,
            explanation=observation.explanation,
            error=None,
        )
    if last_reliable is not None:
        return _retained_cache_component(
            last_reliable,
            revision=revision,
            now=now,
            freshness_threshold=freshness_threshold,
            recovery_phase=(
                RuntimeHealthRecoveryPhase.FAILED
                if reread
                else recovery_phase
            ),
            error=_cache_feature_error(result, reread=reread),
        )
    unknown = result.availability is (
        DiagnosticCacheApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
    )
    return DiagnosticCacheHealthComponent(
        classification=(
            DiagnosticCacheHealthClassification.UNKNOWN
            if unknown
            else DiagnosticCacheHealthClassification.UNAVAILABLE
        ),
        revision=revision,
        observed_at=now,
        freshness=Freshness.AWAITING_FIRST_STATE,
        age=timedelta(0),
        freshness_threshold=freshness_threshold,
        generation=None,
        fallback=(
            DiagnosticCacheFallbackState.UNKNOWN
            if unknown
            else DiagnosticCacheFallbackState.UNAVAILABLE
        ),
        last_refresh_result=(
            DiagnosticCacheLastRefreshResult.NOT_OBSERVED
            if unknown
            else DiagnosticCacheLastRefreshResult.FAILED
        ),
        compatibility=DiagnosticCacheCompatibility.UNKNOWN,
        affected_scope=(DiagnosticCacheScope.REFERENCE_MARKET_PATHS,),
        recovery_phase=(
            DiagnosticCacheRecoveryPhase.FAILED_RECOVERY
            if reread
            else DiagnosticCacheRecoveryPhase.IDLE
        ),
        explanation=(
            "No authoritative Diagnostic Cache observation is available."
            if unknown
            else "The Diagnostic Cache observation is unavailable."
        ),
        error=_cache_feature_error(result, reread=reread),
    )


def _retained_queue_component(
    reliable: DiagnosticQueueHealthComponent | None,
    *,
    revision: int,
    now: datetime,
    freshness_threshold: timedelta,
    recovery_phase: RuntimeHealthRecoveryPhase,
    error: SystemHealthError | None = None,
) -> DiagnosticQueueHealthComponent:
    if reliable is None:
        disconnected = recovery_phase is RuntimeHealthRecoveryPhase.DISCONNECTED
        return DiagnosticQueueHealthComponent(
            classification=DiagnosticQueueHealthClassification.UNAVAILABLE,
            revision=revision,
            observed_at=now,
            freshness=(
                Freshness.DISCONNECTED
                if disconnected
                else Freshness.AWAITING_FIRST_STATE
            ),
            age=timedelta(0),
            freshness_threshold=freshness_threshold,
            pending_count=0,
            running_count=0,
            blocked_count=0,
            oldest_pending_age=None,
            consumer_availability=DiagnosticQueueConsumerAvailability.UNAVAILABLE,
            blockage_reason=DiagnosticQueueBlockageReason.SOURCE_UNAVAILABLE,
            affected_scope=(DiagnosticQueueScope.DIAGNOSTIC_TASK,),
            recovery_phase=_queue_recovery_phase(recovery_phase, reread=False),
            explanation="The Diagnostic Queue observation is unavailable.",
            error=error,
        )
    elapsed = max(now - reliable.observed_at, timedelta(0))
    age = reliable.age + elapsed
    stale = age > freshness_threshold
    return replace(
        reliable,
        classification=(
            DiagnosticQueueHealthClassification.STALE
            if stale
            else DiagnosticQueueHealthClassification.DEGRADED
        ),
        revision=revision,
        observed_at=now,
        freshness=(
            Freshness.DISCONNECTED
            if recovery_phase is RuntimeHealthRecoveryPhase.DISCONNECTED and not stale
            else Freshness.STALE
        ),
        age=age,
        oldest_pending_age=(
            None
            if reliable.oldest_pending_age is None
            else reliable.oldest_pending_age + elapsed
        ),
        recovery_phase=_queue_recovery_phase(recovery_phase, reread=False),
        explanation="Diagnostic Queue is degraded; showing the last reliable state.",
        error=error,
    )


def _retained_cache_component(
    reliable: DiagnosticCacheHealthComponent | None,
    *,
    revision: int,
    now: datetime,
    freshness_threshold: timedelta,
    recovery_phase: RuntimeHealthRecoveryPhase,
    error: SystemHealthError | None = None,
) -> DiagnosticCacheHealthComponent:
    if reliable is None:
        disconnected = recovery_phase is RuntimeHealthRecoveryPhase.DISCONNECTED
        return DiagnosticCacheHealthComponent(
            classification=DiagnosticCacheHealthClassification.UNAVAILABLE,
            revision=revision,
            observed_at=now,
            freshness=(
                Freshness.DISCONNECTED
                if disconnected
                else Freshness.AWAITING_FIRST_STATE
            ),
            age=timedelta(0),
            freshness_threshold=freshness_threshold,
            generation=None,
            fallback=DiagnosticCacheFallbackState.UNAVAILABLE,
            last_refresh_result=DiagnosticCacheLastRefreshResult.NOT_OBSERVED,
            compatibility=DiagnosticCacheCompatibility.UNKNOWN,
            affected_scope=(DiagnosticCacheScope.REFERENCE_MARKET_PATHS,),
            recovery_phase=_cache_recovery_phase(recovery_phase, reread=False),
            explanation="The Diagnostic Cache observation is unavailable.",
            error=error,
        )
    elapsed = max(now - reliable.observed_at, timedelta(0))
    age = reliable.age + elapsed
    stale = age > freshness_threshold
    return replace(
        reliable,
        classification=(
            DiagnosticCacheHealthClassification.STALE
            if stale
            else DiagnosticCacheHealthClassification.DEGRADED
        ),
        revision=revision,
        observed_at=now,
        freshness=(
            Freshness.DISCONNECTED
            if recovery_phase is RuntimeHealthRecoveryPhase.DISCONNECTED and not stale
            else Freshness.STALE
        ),
        age=age,
        recovery_phase=_cache_recovery_phase(recovery_phase, reread=False),
        explanation="Diagnostic Cache is degraded; showing the last reliable state.",
        error=error,
    )


def _queue_recovery_phase(
    phase: RuntimeHealthRecoveryPhase,
    *,
    reread: bool,
) -> DiagnosticQueueRecoveryPhase:
    if reread:
        return DiagnosticQueueRecoveryPhase.RECOVERED
    if phase is RuntimeHealthRecoveryPhase.REREADING:
        return DiagnosticQueueRecoveryPhase.RECOVERING
    if phase is RuntimeHealthRecoveryPhase.RECOVERED:
        return DiagnosticQueueRecoveryPhase.RECOVERED
    if phase is RuntimeHealthRecoveryPhase.FAILED:
        return DiagnosticQueueRecoveryPhase.FAILED_RECOVERY
    return DiagnosticQueueRecoveryPhase.IDLE


def _cache_recovery_phase(
    phase: RuntimeHealthRecoveryPhase,
    *,
    reread: bool,
) -> DiagnosticCacheRecoveryPhase:
    if reread:
        return DiagnosticCacheRecoveryPhase.RECOVERED
    if phase is RuntimeHealthRecoveryPhase.REREADING:
        return DiagnosticCacheRecoveryPhase.RECOVERING
    if phase is RuntimeHealthRecoveryPhase.RECOVERED:
        return DiagnosticCacheRecoveryPhase.RECOVERED
    if phase is RuntimeHealthRecoveryPhase.FAILED:
        return DiagnosticCacheRecoveryPhase.FAILED_RECOVERY
    return DiagnosticCacheRecoveryPhase.IDLE


def _queue_feature_error(
    result: DiagnosticQueueApplicationResult,
    *,
    reread: bool,
) -> SystemHealthError:
    no_observation = result.availability is (
        DiagnosticQueueApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
    )
    return SystemHealthError(
        code=(
            SystemHealthErrorCode.DIAGNOSTIC_QUEUE_NO_AUTHORITATIVE_OBSERVATION
            if no_observation
            else SystemHealthErrorCode.DIAGNOSTIC_QUEUE_READ_FAILED
        ),
        explanation=(
            "No authoritative Diagnostic Queue observation is available."
            if no_observation
            else "The Diagnostic Queue recovery failed safely."
            if reread
            else "The Diagnostic Queue read failed safely."
        ),
        retryable=True if result.error is None else result.error.retryable,
    )


def _cache_feature_error(
    result: DiagnosticCacheApplicationResult,
    *,
    reread: bool,
) -> SystemHealthError:
    no_observation = result.availability is (
        DiagnosticCacheApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
    )
    return SystemHealthError(
        code=(
            SystemHealthErrorCode.DIAGNOSTIC_CACHE_NO_AUTHORITATIVE_OBSERVATION
            if no_observation
            else SystemHealthErrorCode.DIAGNOSTIC_CACHE_READ_FAILED
        ),
        explanation=(
            "No authoritative Diagnostic Cache observation is available."
            if no_observation
            else "The Diagnostic Cache recovery failed safely."
            if reread
            else "The Diagnostic Cache read failed safely."
        ),
        retryable=True if result.error is None else result.error.retryable,
    )


def _unobserved_queue_result(observed_at: datetime) -> DiagnosticQueueApplicationResult:
    return DiagnosticQueueApplicationResult(
        availability=(
            DiagnosticQueueApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
        ),
        observation=None,
        source_token=None,
        observed_at=_aware(observed_at),
        error=DiagnosticQueueApplicationError(
            code=DiagnosticQueueApplicationErrorCode.NO_AUTHORITATIVE_OBSERVATION,
            explanation="No authoritative Diagnostic Queue observation is available.",
            retryable=True,
        ),
    )


def _unobserved_cache_result(observed_at: datetime) -> DiagnosticCacheApplicationResult:
    return DiagnosticCacheApplicationResult(
        availability=(
            DiagnosticCacheApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
        ),
        observation=None,
        source_token=None,
        observed_at=_aware(observed_at),
        error=DiagnosticCacheApplicationError(
            code=DiagnosticCacheApplicationErrorCode.NO_AUTHORITATIVE_OBSERVATION,
            explanation="No authoritative Diagnostic Cache observation is available.",
            retryable=True,
        ),
    )


def _presentation_for(
    classification: RuntimeHealthClassification,
) -> SystemHealthPresentationState:
    return SystemHealthPresentationState(classification.value)


def _feature_error(
    result: RuntimeHealthApplicationResult,
    *,
    reread: bool,
) -> SystemHealthError:
    error = result.error
    if reread:
        return SystemHealthError(
            code=SystemHealthErrorCode.AUTHORITATIVE_REREAD_FAILED,
            explanation="The authoritative Runtime Health reread failed safely.",
            retryable=True,
        )
    if result.availability is (
        RuntimeHealthApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
    ):
        return SystemHealthError(
            code=SystemHealthErrorCode.NO_AUTHORITATIVE_OBSERVATION,
            explanation="No authoritative Runtime Health observation is available.",
            retryable=True,
        )
    return SystemHealthError(
        code=SystemHealthErrorCode.OBSERVATION_FAILED,
        explanation="The authoritative Runtime Health read failed safely.",
        retryable=(True if error is None else error.retryable),
        correlation_identity=None,
    )


__all__ = [
    "DeterministicFakeSystemHealthAdapter",
    "LiveSystemHealthAdapter",
]
