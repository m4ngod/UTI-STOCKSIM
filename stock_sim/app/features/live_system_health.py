"""Live and deterministic adapters for System Health Feature Interface 1.0."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import RLock

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
        source_kind: SourceKind,
        source_identity: str,
        clock: Callable[[], datetime],
        freshness_threshold: timedelta,
    ) -> None:
        if freshness_threshold <= timedelta(0):
            raise ValueError("System Health freshness threshold must be positive")
        self._read_runtime_health = read_runtime_health
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
        subscription.deliver(observer, state)
        return subscription

    def close(self) -> None:
        with self._transition_lock:
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
        with self._lock:
            self._ensure_open()
            revision = self._next_revision_locked()
            generation = self._generation
        now = _aware(self._clock())
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
                    error=error,
                )
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
        if age <= self._freshness_threshold:
            return replace(
                state,
                revision=revision,
                observed_at=now,
                age=age,
                source=replace(state.source, generation=generation),
            )
        if state.presentation is SystemHealthPresentationState.STALE:
            return replace(
                state,
                revision=revision,
                observed_at=now,
                age=age,
                source=replace(state.source, generation=generation),
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
    ) -> None:
        self._event_bridge = event_bridge
        self._closed = False
        self._lock = RLock()
        self._connection_sequence = 0
        self._dispose_connection_subscription: Callable[[], None] = lambda: None
        self._dispose_batch_subscription: Callable[[], None] = lambda: None
        self._projection = _SystemHealthProjection(
            read_runtime_health=application_health.read_runtime_health,
            source_kind=SourceKind.LIVE_RUNTIME,
            source_identity="diagnostics_application",
            clock=clock or _default_live_clock,
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
            self._dispose_batch_subscription = lambda: None
            self._dispose_connection_subscription = lambda: None
        dispose_batches()
        dispose_connection()
        self._projection.close()

    def _on_snapshot_batch(self, batch: EventBridgeBatch) -> None:
        if not self._projection.is_current_generation(batch.generation.value):
            return
        if not any(
            str(snapshot.get("feature", "")).casefold() == "system_health"
            for snapshot in batch.snapshots
        ):
            return
        self._projection.publish_authoritative_observation()

    def _on_connection_state(self, state: EventBridgeConnectionState) -> None:
        with self._lock:
            if self._closed or state.sequence.value <= self._connection_sequence:
                return
            first_observation = self._connection_sequence == 0
            self._connection_sequence = state.sequence.value
        if state.phase is EventBridgeConnectionPhase.DISCONNECTED:
            self._projection.mark_disconnected(generation=state.generation.value)
        elif first_observation:
            self._projection.set_generation(state.generation.value)
        else:
            self._projection.mark_reconnected(generation=state.generation.value)


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
        self._source_revision = 0
        self._projection = _SystemHealthProjection(
            read_runtime_health=self._read_runtime_health,
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
        self.publish_authoritative_observation()

    def advance_to_failed(self) -> None:
        self._failed = True
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
