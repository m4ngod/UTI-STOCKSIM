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
    HealthCompatibilityState,
    PersistenceAvailability,
    PersistenceHealthComponent,
    PersistenceReopenVerification,
    RuntimeHealthClassification,
    RuntimeHealthComponent,
    RuntimeHealthRecoveryPhase,
    SystemHealthAffectedScope,
    SystemHealthComponent,
    SystemHealthComponentIdentity,
    SystemHealthContext,
    SystemHealthError,
    SystemHealthErrorCode,
    SystemHealthObserver,
    SystemHealthPresentationState,
    SystemHealthRecoveryExpectation,
    SystemHealthSource,
    SystemHealthViewState,
    VersionHealthComponent,
)
from .system_health_application import (
    PersistenceHealthApplicationObservation,
    RuntimeHealthApplicationAvailability,
    RuntimeHealthApplicationError,
    RuntimeHealthApplicationErrorCode,
    RuntimeHealthApplicationObservation,
    RuntimeHealthApplicationResult,
    StrategyDiagnosticsV1SystemHealthApplication,
    VersionHealthApplicationObservation,
)
from .versioning import ACTIVE_FEATURE_INTERFACES
from strategy_diagnostics.diagnostic_evidence import DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION
from strategy_diagnostics.persistence import DIAGNOSTIC_SCHEMA_REVISION
from strategy_diagnostics.reproduction import REPRODUCTION_MANIFEST_SCHEMA_VERSION
from strategy_diagnostics.versioning import STRATEGY_DIAGNOSTICS_RUNNER_VERSION
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
    """Own the immutable three-component health state machine shared by both seams."""

    def __init__(
        self,
        *,
        read_runtime_health: Callable[[], RuntimeHealthApplicationResult],
        read_persistence_health: Callable[[], PersistenceHealthApplicationObservation],
        read_version_health: Callable[[], VersionHealthApplicationObservation],
        source_kind: SourceKind,
        source_identity: str,
        clock: Callable[[], datetime],
        freshness_threshold: timedelta,
    ) -> None:
        if freshness_threshold <= timedelta(0):
            raise ValueError("System Health freshness threshold must be positive")
        self._read_runtime_health = read_runtime_health
        self._read_persistence_health = read_persistence_health
        self._read_version_health = read_version_health
        self._source_kind = source_kind
        self._source_identity = source_identity
        self._clock = clock
        self._freshness_threshold = freshness_threshold
        self._context = SystemHealthContext()
        self._generation = SourceGenerationId(1)
        self._connected = True
        self._revision = 0
        self._state: SystemHealthViewState | None = None
        self._last_reliable: tuple[SystemHealthComponent, ...] | None = None
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
        runtime_result = self._read_runtime_health()
        persistence_result = self._read_persistence_health()
        version_result = self._read_version_health()
        with self._lock:
            self._ensure_open()
            revision = self._next_revision_locked()
            generation = self._generation
            previous_components = self._last_reliable
        now = _aware(self._clock())
        components = _project_components(
            runtime_result=runtime_result,
            persistence_result=persistence_result,
            version_result=version_result,
            revision=revision,
            observed_at=now,
            freshness_threshold=self._freshness_threshold,
            recovery_phase=recovery_phase,
            previous_components=previous_components,
        )
        runtime_ready = (
            runtime_result.availability is RuntimeHealthApplicationAvailability.READY
            and runtime_result.observation is not None
        )
        reliable = runtime_ready and not any(
            component.classification
            in {
                RuntimeHealthClassification.INCOMPATIBLE,
                RuntimeHealthClassification.UNAVAILABLE,
                RuntimeHealthClassification.UNKNOWN,
            }
            for component in components
        )
        if reliable:
            presentation = _overall_presentation(
                components,
                recovery_phase=recovery_phase,
            )
            complete = presentation in {
                SystemHealthPresentationState.HEALTHY,
                SystemHealthPresentationState.RECOVERED,
            }
            reliable_at = max(
                component.last_successful_observation_at or component.observed_at
                for component in components
            )
            error = _overall_error(components)
            state = SystemHealthViewState(
                interface_version=SYSTEM_HEALTH_INTERFACE_VERSION,
                revision=revision,
                observed_at=now,
                last_reliable_at=reliable_at,
                freshness=Freshness.FRESH,
                age=max(now - reliable_at, timedelta(0)),
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
                components=components,
                last_reliable_payload=components,
                recovery_phase=recovery_phase,
                error=error,
            )
        elif previous_components is not None and not runtime_ready:
            error = _overall_error(
                components,
                runtime_error=_feature_error(
                    runtime_result,
                    reread=reread,
                ),
            )
            reliable_payload = _merge_reliable_components(
                previous_components,
                components,
            )
            retained = self._retained_state(
                revision=revision,
                observed_at=now,
                generation=generation,
                recovery_phase=(
                    RuntimeHealthRecoveryPhase.FAILED
                    if reread
                    else recovery_phase
                ),
                error=error,
                reliable_payload=reliable_payload,
            )
            current_presentation = _overall_presentation(
                components,
                recovery_phase=recovery_phase,
            )
            state = replace(
                retained,
                components=components,
                presentation=(
                    current_presentation
                    if current_presentation
                    is SystemHealthPresentationState.INCOMPATIBLE
                    else retained.presentation
                ),
                completeness=Completeness.PARTIAL,
                last_reliable_payload=reliable_payload,
                error=error,
            )
        else:
            error = _overall_error(
                components,
                runtime_error=(
                    None
                    if runtime_ready
                    else _feature_error(runtime_result, reread=reread)
                ),
            )
            presentation = _overall_presentation(
                components,
                recovery_phase=recovery_phase,
            )
            reliable_payload = _merge_reliable_components(
                previous_components,
                components,
            )
            prior = reliable_payload
            prior_successes = tuple(
                component.last_successful_observation_at or component.observed_at
                for component in prior
            )
            current_successes = tuple(
                component.last_successful_observation_at
                for component in components
                if component.last_successful_observation_at is not None
            )
            last_reliable_at: datetime | None = (
                max(prior_successes)
                if prior_successes
                else max(current_successes)
                if current_successes
                else None
            )
            unknown = presentation is SystemHealthPresentationState.UNKNOWN
            state = SystemHealthViewState(
                interface_version=SYSTEM_HEALTH_INTERFACE_VERSION,
                revision=revision,
                observed_at=now,
                last_reliable_at=last_reliable_at,
                freshness=(
                    Freshness.AWAITING_FIRST_STATE
                    if previous_components is None and unknown
                    else Freshness.FRESH
                ),
                age=(
                    timedelta(0)
                    if last_reliable_at is None
                    else max(now - last_reliable_at, timedelta(0))
                ),
                freshness_threshold=self._freshness_threshold,
                source=SystemHealthSource(
                    kind=self._source_kind,
                    identity=self._source_identity,
                    generation=generation,
                ),
                context=self._context,
                phase=(
                    ViewPhase.LOADING
                    if unknown and previous_components is None
                    else ViewPhase.FAILED
                    if presentation is SystemHealthPresentationState.UNAVAILABLE
                    else ViewPhase.DEGRADED
                ),
                presentation=presentation,
                completeness=(
                    Completeness.UNKNOWN
                    if unknown and previous_components is None
                    else Completeness.PARTIAL
                ),
                components=components,
                last_reliable_payload=(reliable_payload or None),
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
        reliable_payload: tuple[SystemHealthComponent, ...] | None = None,
    ) -> SystemHealthViewState:
        reliable = (
            self._last_reliable
            if reliable_payload is None
            else reliable_payload
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
                error=error,
            )

        reliable_at = min(
            component.last_successful_observation_at or component.observed_at
            for component in reliable
        )
        age = max(observed_at - reliable_at, timedelta(0))
        is_stale = age > self._freshness_threshold
        components = tuple(
            _retained_component(
                component,
                revision=revision,
                observed_at=observed_at,
                freshness_threshold=self._freshness_threshold,
                recovery_phase=recovery_phase,
            )
            for component in reliable
        )
        return SystemHealthViewState(
            interface_version=SYSTEM_HEALTH_INTERFACE_VERSION,
            revision=revision,
            observed_at=observed_at,
            last_reliable_at=reliable_at,
            freshness=(
                Freshness.STALE
                if is_stale
                else Freshness.DISCONNECTED
                if recovery_phase is RuntimeHealthRecoveryPhase.DISCONNECTED
                else Freshness.FRESH
            ),
            age=age,
            freshness_threshold=self._freshness_threshold,
            source=SystemHealthSource(
                kind=self._source_kind,
                identity=self._source_identity,
                generation=generation,
            ),
            context=self._context,
            phase=(
                ViewPhase.LOADING
                if recovery_phase is RuntimeHealthRecoveryPhase.REREADING
                else ViewPhase.DEGRADED
            ),
            presentation=(
                SystemHealthPresentationState.RECOVERING
                if recovery_phase is RuntimeHealthRecoveryPhase.REREADING
                else SystemHealthPresentationState.STALE
                if is_stale
                else SystemHealthPresentationState.DEGRADED
            ),
            completeness=Completeness.PARTIAL,
            components=components,
            last_reliable_payload=reliable,
            recovery_phase=recovery_phase,
            error=error,
        )

    def _age_state(self, state: SystemHealthViewState) -> SystemHealthViewState:
        reliable = state.last_reliable_payload
        if reliable is None:
            return state
        now = _aware(self._clock())
        reliable_at = min(
            component.last_successful_observation_at or component.observed_at
            for component in reliable
        )
        age = max(now - reliable_at, timedelta(0))
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
                components=_age_components(
                    state.components,
                    observed_at=now,
                    freshness_threshold=self._freshness_threshold,
                ),
                source=replace(state.source, generation=generation),
            )
        if state.presentation is SystemHealthPresentationState.STALE:
            return replace(
                state,
                revision=revision,
                observed_at=now,
                age=age,
                components=_age_components(
                    state.components,
                    observed_at=now,
                    freshness_threshold=self._freshness_threshold,
                ),
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
            if state.last_reliable_payload is not None:
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
            affected_scope=SystemHealthAffectedScope.APPLICATION_RUNTIME,
            retryable=True,
            recovery_expectation=SystemHealthRecoveryExpectation.SOURCE_RECONNECTION,
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
            read_persistence_health=application_health.read_persistence_health,
            read_version_health=application_health.read_version_health,
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
        self._degraded = False
        self._persistence_unavailable = False
        self._schema_incompatible = False
        self._manifest_incompatible = False
        self._source_revision = 0
        self._projection = _SystemHealthProjection(
            read_runtime_health=self._read_runtime_health,
            read_persistence_health=self._read_persistence_health,
            read_version_health=self._read_version_health,
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
        self._degraded = False
        self._persistence_unavailable = False
        self._schema_incompatible = False
        self._manifest_incompatible = False
        self.publish_authoritative_observation()

    def advance_to_degraded(self) -> None:
        self._healthy = True
        self._failed = False
        self._degraded = True
        self._persistence_unavailable = False
        self._schema_incompatible = False
        self._manifest_incompatible = False
        self.publish_authoritative_observation()

    def advance_to_unavailable(self) -> None:
        self._healthy = True
        self._failed = False
        self._degraded = False
        self._persistence_unavailable = True
        self._schema_incompatible = False
        self._manifest_incompatible = False
        self.publish_authoritative_observation()

    def advance_to_schema_incompatible(self) -> None:
        self._healthy = True
        self._failed = False
        self._degraded = False
        self._persistence_unavailable = False
        self._schema_incompatible = True
        self._manifest_incompatible = False
        self.publish_authoritative_observation()

    def advance_to_manifest_incompatible(self) -> None:
        self._healthy = True
        self._failed = False
        self._degraded = False
        self._persistence_unavailable = False
        self._schema_incompatible = False
        self._manifest_incompatible = True
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
                classification=(
                    RuntimeHealthClassification.DEGRADED
                    if self._degraded
                    else RuntimeHealthClassification.HEALTHY
                ),
                observed_at=observed_at,
                explanation=(
                    "Diagnostics runtime reports degraded availability."
                    if self._degraded
                    else "Diagnostics runtime is ready."
                ),
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

    def _read_persistence_health(self) -> PersistenceHealthApplicationObservation:
        observed_at = self._clock()
        if not self._healthy:
            return PersistenceHealthApplicationObservation(
                availability=PersistenceAvailability.UNKNOWN,
                schema_compatibility=HealthCompatibilityState.UNKNOWN,
                schema_head=None,
                supported_schema_head=DIAGNOSTIC_SCHEMA_REVISION,
                last_successful_durable_read_at=None,
                last_successful_durable_write_at=None,
                reopen_verification=PersistenceReopenVerification.UNKNOWN,
                observed_at=observed_at,
                error=RuntimeHealthApplicationError(
                    code=(
                        RuntimeHealthApplicationErrorCode.PERSISTENCE_NOT_INITIALIZED
                    ),
                    explanation=(
                        "No authoritative Diagnostic Persistence observation "
                        "is available."
                    ),
                    retryable=True,
                ),
            )
        availability = (
            PersistenceAvailability.UNAVAILABLE
            if self._persistence_unavailable
            else PersistenceAvailability.AVAILABLE
        )
        compatibility = (
            HealthCompatibilityState.INCOMPATIBLE
            if self._schema_incompatible
            else HealthCompatibilityState.UNKNOWN
            if self._persistence_unavailable
            else HealthCompatibilityState.COMPATIBLE
        )
        error = None
        if self._schema_incompatible:
            error = RuntimeHealthApplicationError(
                code=RuntimeHealthApplicationErrorCode.PERSISTENCE_SCHEMA_INCOMPATIBLE,
                explanation="Diagnostic Persistence schema is incompatible.",
                retryable=False,
            )
        elif self._persistence_unavailable:
            error = RuntimeHealthApplicationError(
                code=RuntimeHealthApplicationErrorCode.PERSISTENCE_READ_FAILED,
                explanation="Diagnostic Persistence is unavailable.",
                retryable=True,
            )
        return PersistenceHealthApplicationObservation(
            availability=availability,
            schema_compatibility=compatibility,
            schema_head=(None if self._persistence_unavailable else DIAGNOSTIC_SCHEMA_REVISION),
            supported_schema_head=DIAGNOSTIC_SCHEMA_REVISION,
            last_successful_durable_read_at=(
                None if self._persistence_unavailable else observed_at
            ),
            last_successful_durable_write_at=(
                None if self._persistence_unavailable else observed_at
            ),
            reopen_verification=(
                PersistenceReopenVerification.FAILED
                if self._persistence_unavailable or self._schema_incompatible
                else PersistenceReopenVerification.VERIFIED
            ),
            observed_at=observed_at,
            error=error,
        )

    def _read_version_health(self) -> VersionHealthApplicationObservation:
        observed_at = self._clock()
        compatibility = (
            HealthCompatibilityState.INCOMPATIBLE
            if self._manifest_incompatible
            else HealthCompatibilityState.COMPATIBLE
        )
        error = (
            RuntimeHealthApplicationError(
                code=RuntimeHealthApplicationErrorCode.MANIFEST_INCOMPATIBLE,
                explanation="The current Reproduction Manifest format is incompatible.",
                retryable=False,
            )
            if self._manifest_incompatible
            else None
        )
        return VersionHealthApplicationObservation(
            product_build="stock-sim/0.0.1",
            feature_interfaces=ACTIVE_FEATURE_INTERFACES,
            dependency_lock_identity=(
                "sha256:"
                + hashlib.sha256(b"deterministic-dependency-lock").hexdigest()
            ),
            release_manifest_compatibility=HealthCompatibilityState.COMPATIBLE,
            runner_version=STRATEGY_DIAGNOSTICS_RUNNER_VERSION,
            schema_version=DIAGNOSTIC_SCHEMA_REVISION,
            evidence_format_version=DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION,
            manifest_format_version=REPRODUCTION_MANIFEST_SCHEMA_VERSION,
            reproduction_manifest_compatibility=compatibility,
            observed_at=observed_at,
            error=error,
        )


def _project_components(
    *,
    runtime_result: RuntimeHealthApplicationResult,
    persistence_result: PersistenceHealthApplicationObservation,
    version_result: VersionHealthApplicationObservation,
    revision: int,
    observed_at: datetime,
    freshness_threshold: timedelta,
    recovery_phase: RuntimeHealthRecoveryPhase,
    previous_components: tuple[SystemHealthComponent, ...] | None,
) -> tuple[SystemHealthComponent, ...]:
    runtime_observation = runtime_result.observation
    previous_runtime = next(
        (
            component
            for component in previous_components or ()
            if isinstance(component, RuntimeHealthComponent)
        ),
        None,
    )
    runtime_classification = (
        runtime_observation.classification
        if runtime_observation is not None
        else RuntimeHealthClassification.UNKNOWN
        if runtime_result.availability
        is RuntimeHealthApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
        else RuntimeHealthClassification.UNAVAILABLE
    )
    runtime_observed_at = (
        runtime_observation.observed_at
        if runtime_observation is not None
        else runtime_result.observed_at
    )
    runtime = RuntimeHealthComponent(
        identity=SystemHealthComponentIdentity.APPLICATION_RUNTIME,
        classification=runtime_classification,
        revision=revision,
        observed_at=runtime_observed_at,
        last_successful_observation_at=(
            runtime_observation.observed_at
            if runtime_observation is not None
            else None
            if previous_runtime is None
            else previous_runtime.last_successful_observation_at
        ),
        explanation=_runtime_explanation(runtime_classification),
    )
    persistence_classification = _persistence_classification(persistence_result)
    persistence_error = _persistence_feature_error(persistence_result)
    previous_persistence = next(
        (
            component
            for component in previous_components or ()
            if isinstance(component, PersistenceHealthComponent)
        ),
        None,
    )
    durable_read_at = (
        persistence_result.last_successful_durable_read_at
        or (
            None
            if previous_persistence is None
            else previous_persistence.last_successful_durable_read_at
        )
    )
    durable_write_at = (
        persistence_result.last_successful_durable_write_at
        or (
            None
            if previous_persistence is None
            else previous_persistence.last_successful_durable_write_at
        )
    )
    persistence_last_success = (
        persistence_result.observed_at
        if persistence_result.availability
        in {PersistenceAvailability.AVAILABLE, PersistenceAvailability.DEGRADED}
        else (
            None
            if previous_persistence is None
            else previous_persistence.last_successful_observation_at
        )
    )
    persistence_age = max(
        observed_at - (persistence_last_success or observed_at),
        timedelta(0),
    )
    persistence = PersistenceHealthComponent(
        identity=SystemHealthComponentIdentity.DIAGNOSTIC_PERSISTENCE,
        classification=persistence_classification,
        revision=revision,
        observed_at=persistence_result.observed_at,
        last_successful_observation_at=persistence_last_success,
        freshness=(
            Freshness.STALE
            if persistence_age > freshness_threshold
            else Freshness.FRESH
        ),
        age=persistence_age,
        freshness_threshold=freshness_threshold,
        availability=persistence_result.availability,
        schema_compatibility=persistence_result.schema_compatibility,
        schema_head=persistence_result.schema_head,
        supported_schema_head=persistence_result.supported_schema_head,
        last_successful_durable_read_at=durable_read_at,
        last_successful_durable_write_at=durable_write_at,
        reopen_verification=persistence_result.reopen_verification,
        affected_scope=SystemHealthAffectedScope.DIAGNOSTIC_PERSISTENCE,
        recovery_phase=_component_recovery_phase(
            recovery_phase,
            persistence_classification,
        ),
        explanation=_persistence_explanation(persistence_classification),
        error=persistence_error,
    )
    version_classification = _version_classification(version_result)
    version_error = _version_feature_error(version_result)
    version = VersionHealthComponent(
        identity=SystemHealthComponentIdentity.VERSION_COMPATIBILITY,
        classification=version_classification,
        revision=revision,
        observed_at=version_result.observed_at,
        last_successful_observation_at=(
            version_result.observed_at
            if version_classification
            not in {
                RuntimeHealthClassification.UNAVAILABLE,
                RuntimeHealthClassification.UNKNOWN,
            }
            else None
        ),
        product_build=version_result.product_build,
        feature_interfaces=version_result.feature_interfaces,
        dependency_lock_identity=version_result.dependency_lock_identity,
        release_manifest_compatibility=(
            version_result.release_manifest_compatibility
        ),
        runner_version=version_result.runner_version,
        schema_version=version_result.schema_version,
        evidence_format_version=version_result.evidence_format_version,
        manifest_format_version=version_result.manifest_format_version,
        reproduction_manifest_compatibility=(
            version_result.reproduction_manifest_compatibility
        ),
        affected_scope=SystemHealthAffectedScope.VERSION_COMPATIBILITY,
        recovery_phase=_component_recovery_phase(
            recovery_phase,
            version_classification,
        ),
        explanation=_version_explanation(version_classification),
        error=version_error,
    )
    return (runtime, persistence, version)


def _merge_reliable_components(
    previous: tuple[SystemHealthComponent, ...] | None,
    current: tuple[SystemHealthComponent, ...],
) -> tuple[SystemHealthComponent, ...]:
    reliable = {
        component.identity: component
        for component in previous or ()
    }
    for component in current:
        if component.classification in {
            RuntimeHealthClassification.HEALTHY,
            RuntimeHealthClassification.DEGRADED,
            RuntimeHealthClassification.RECOVERED,
        }:
            reliable[component.identity] = component
    return tuple(
        reliable[identity]
        for identity in (
            SystemHealthComponentIdentity.APPLICATION_RUNTIME,
            SystemHealthComponentIdentity.DIAGNOSTIC_PERSISTENCE,
            SystemHealthComponentIdentity.VERSION_COMPATIBILITY,
        )
        if identity in reliable
    )


def _component_recovery_phase(
    requested: RuntimeHealthRecoveryPhase,
    classification: RuntimeHealthClassification,
) -> RuntimeHealthRecoveryPhase:
    if (
        requested is RuntimeHealthRecoveryPhase.RECOVERED
        and classification
        in {
            RuntimeHealthClassification.INCOMPATIBLE,
            RuntimeHealthClassification.UNAVAILABLE,
            RuntimeHealthClassification.UNKNOWN,
        }
    ):
        return RuntimeHealthRecoveryPhase.FAILED
    return requested


def _persistence_classification(
    result: PersistenceHealthApplicationObservation,
) -> RuntimeHealthClassification:
    if result.schema_compatibility is HealthCompatibilityState.INCOMPATIBLE:
        return RuntimeHealthClassification.INCOMPATIBLE
    if result.availability is PersistenceAvailability.UNAVAILABLE:
        return RuntimeHealthClassification.UNAVAILABLE
    if result.availability is PersistenceAvailability.UNKNOWN:
        return RuntimeHealthClassification.UNKNOWN
    if (
        result.availability is PersistenceAvailability.DEGRADED
        or result.schema_compatibility is HealthCompatibilityState.UNKNOWN
        or result.reopen_verification is not PersistenceReopenVerification.VERIFIED
    ):
        return RuntimeHealthClassification.DEGRADED
    return RuntimeHealthClassification.HEALTHY


def _version_classification(
    result: VersionHealthApplicationObservation,
) -> RuntimeHealthClassification:
    if result.release_manifest_compatibility is HealthCompatibilityState.INCOMPATIBLE:
        return RuntimeHealthClassification.INCOMPATIBLE
    if (
        result.reproduction_manifest_compatibility
        is HealthCompatibilityState.INCOMPATIBLE
    ):
        return RuntimeHealthClassification.INCOMPATIBLE
    if result.dependency_lock_identity is None:
        return RuntimeHealthClassification.UNAVAILABLE
    if result.release_manifest_compatibility is HealthCompatibilityState.UNKNOWN:
        return RuntimeHealthClassification.UNKNOWN
    if (
        result.reproduction_manifest_compatibility
        is HealthCompatibilityState.UNKNOWN
    ):
        return RuntimeHealthClassification.UNKNOWN
    return RuntimeHealthClassification.HEALTHY


def _overall_presentation(
    components: tuple[SystemHealthComponent, ...],
    *,
    recovery_phase: RuntimeHealthRecoveryPhase,
) -> SystemHealthPresentationState:
    if recovery_phase is RuntimeHealthRecoveryPhase.REREADING:
        return SystemHealthPresentationState.RECOVERING
    classifications = {component.classification for component in components}
    presentation_for = {
        RuntimeHealthClassification.INCOMPATIBLE: (
            SystemHealthPresentationState.INCOMPATIBLE
        ),
        RuntimeHealthClassification.UNAVAILABLE: (
            SystemHealthPresentationState.UNAVAILABLE
        ),
        RuntimeHealthClassification.STALE: SystemHealthPresentationState.STALE,
        RuntimeHealthClassification.DEGRADED: (
            SystemHealthPresentationState.DEGRADED
        ),
        RuntimeHealthClassification.UNKNOWN: SystemHealthPresentationState.UNKNOWN,
    }
    for classification in _classification_severity_order():
        if classification in classifications:
            return presentation_for[classification]
    if recovery_phase is RuntimeHealthRecoveryPhase.RECOVERED:
        return SystemHealthPresentationState.RECOVERED
    return SystemHealthPresentationState.HEALTHY


def _overall_error(
    components: tuple[SystemHealthComponent, ...],
    *,
    runtime_error: SystemHealthError | None = None,
) -> SystemHealthError | None:
    severity = {
        classification: index
        for index, classification in enumerate(_classification_severity_order())
    }
    candidates: list[tuple[int, int, SystemHealthError]] = []
    if runtime_error is not None and components:
        candidates.append(
            (
                severity.get(components[0].classification, len(severity)),
                0,
                runtime_error,
            )
        )
    for order, component in enumerate(components[1:], start=1):
        if (
            isinstance(component, (PersistenceHealthComponent, VersionHealthComponent))
            and component.error is not None
        ):
            candidates.append(
                (
                    severity.get(component.classification, len(severity)),
                    order,
                    component.error,
                )
            )
    if not candidates:
        return None
    return min(candidates)[2]


def _classification_severity_order() -> tuple[RuntimeHealthClassification, ...]:
    return (
        RuntimeHealthClassification.INCOMPATIBLE,
        RuntimeHealthClassification.UNAVAILABLE,
        RuntimeHealthClassification.STALE,
        RuntimeHealthClassification.DEGRADED,
        RuntimeHealthClassification.UNKNOWN,
    )


def _persistence_feature_error(
    result: PersistenceHealthApplicationObservation,
) -> SystemHealthError | None:
    if result.error is None:
        return None
    if result.schema_compatibility is HealthCompatibilityState.INCOMPATIBLE:
        code = SystemHealthErrorCode.PERSISTENCE_SCHEMA_INCOMPATIBLE
    elif result.availability is PersistenceAvailability.UNAVAILABLE:
        code = SystemHealthErrorCode.PERSISTENCE_UNAVAILABLE
    else:
        code = SystemHealthErrorCode.PERSISTENCE_NOT_INITIALIZED
    return SystemHealthError(
        code=code,
        explanation=_persistence_explanation(_persistence_classification(result)),
        affected_scope=SystemHealthAffectedScope.DIAGNOSTIC_PERSISTENCE,
        retryable=result.error.retryable,
        recovery_expectation=(
            SystemHealthRecoveryExpectation.COMPATIBLE_BUILD_REQUIRED
            if code is SystemHealthErrorCode.PERSISTENCE_SCHEMA_INCOMPATIBLE
            else SystemHealthRecoveryExpectation.INITIALIZATION_REQUIRED
            if code is SystemHealthErrorCode.PERSISTENCE_NOT_INITIALIZED
            else SystemHealthRecoveryExpectation.AUTOMATIC_RETRY
        ),
        correlation_identity=_safe_correlation_identity(
            result.error.correlation_identity
        ),
    )


def _version_feature_error(
    result: VersionHealthApplicationObservation,
) -> SystemHealthError | None:
    if result.error is None:
        return None
    if result.error.code is RuntimeHealthApplicationErrorCode.MANIFEST_UNAVAILABLE:
        code = SystemHealthErrorCode.REPRODUCTION_MANIFEST_UNAVAILABLE
    elif result.error.code is (
        RuntimeHealthApplicationErrorCode.RELEASE_MANIFEST_INCOMPATIBLE
    ):
        code = SystemHealthErrorCode.RELEASE_BINDING_INCOMPATIBLE
    elif result.error.code is (
        RuntimeHealthApplicationErrorCode.RELEASE_MANIFEST_UNAVAILABLE
    ):
        code = SystemHealthErrorCode.RELEASE_BINDING_UNAVAILABLE
    elif (
        result.reproduction_manifest_compatibility
        is HealthCompatibilityState.INCOMPATIBLE
    ):
        code = SystemHealthErrorCode.REPRODUCTION_MANIFEST_INCOMPATIBLE
    elif result.dependency_lock_identity is None:
        code = SystemHealthErrorCode.DEPENDENCY_LOCK_UNAVAILABLE
    else:
        code = SystemHealthErrorCode.VERSION_FACTS_UNAVAILABLE
    return SystemHealthError(
        code=code,
        explanation=_version_explanation(_version_classification(result)),
        affected_scope=(
            SystemHealthAffectedScope.REPRODUCTION_MANIFEST
            if code
            in {
                SystemHealthErrorCode.REPRODUCTION_MANIFEST_INCOMPATIBLE,
                SystemHealthErrorCode.REPRODUCTION_MANIFEST_UNAVAILABLE,
            }
            else SystemHealthAffectedScope.VERSION_COMPATIBILITY
        ),
        retryable=result.error.retryable,
        recovery_expectation=(
            SystemHealthRecoveryExpectation.COMPATIBLE_ARTIFACT_REQUIRED
            if code is SystemHealthErrorCode.REPRODUCTION_MANIFEST_INCOMPATIBLE
            else SystemHealthRecoveryExpectation.INITIALIZATION_REQUIRED
            if code is SystemHealthErrorCode.REPRODUCTION_MANIFEST_UNAVAILABLE
            else SystemHealthRecoveryExpectation.RELEASE_REPAIR_REQUIRED
            if code
            in {
                SystemHealthErrorCode.DEPENDENCY_LOCK_UNAVAILABLE,
                SystemHealthErrorCode.RELEASE_BINDING_INCOMPATIBLE,
                SystemHealthErrorCode.RELEASE_BINDING_UNAVAILABLE,
            }
            else SystemHealthRecoveryExpectation.AUTOMATIC_RETRY
        ),
        correlation_identity=_safe_correlation_identity(
            result.error.correlation_identity
        ),
    )


def _persistence_explanation(classification: RuntimeHealthClassification) -> str:
    return {
        RuntimeHealthClassification.HEALTHY: (
            "Diagnostic Persistence is available, compatible, and reopen verified."
        ),
        RuntimeHealthClassification.DEGRADED: (
            "Diagnostic Persistence has a limited verification state."
        ),
        RuntimeHealthClassification.UNAVAILABLE: (
            "Diagnostic Persistence is unavailable."
        ),
        RuntimeHealthClassification.INCOMPATIBLE: (
            "Diagnostic Persistence schema is incompatible with this build."
        ),
        RuntimeHealthClassification.UNKNOWN: (
            "Diagnostic Persistence compatibility is unknown."
        ),
    }.get(classification, "Diagnostic Persistence is not fully reliable.")


def _runtime_explanation(classification: RuntimeHealthClassification) -> str:
    return {
        RuntimeHealthClassification.HEALTHY: "Diagnostics runtime is ready.",
        RuntimeHealthClassification.DEGRADED: (
            "Diagnostics runtime reports degraded availability."
        ),
        RuntimeHealthClassification.UNAVAILABLE: (
            "Diagnostics runtime is unavailable."
        ),
        RuntimeHealthClassification.INCOMPATIBLE: (
            "Diagnostics runtime compatibility is incompatible."
        ),
        RuntimeHealthClassification.STALE: (
            "Diagnostics runtime observation is stale."
        ),
        RuntimeHealthClassification.RECOVERING: (
            "Diagnostics runtime observation is recovering."
        ),
        RuntimeHealthClassification.RECOVERED: (
            "Diagnostics runtime observation recovered."
        ),
        RuntimeHealthClassification.UNKNOWN: (
            "Diagnostics runtime availability is unknown."
        ),
    }[classification]


def _safe_correlation_identity(value: str | None) -> str | None:
    if value is None or not isinstance(value, str):
        return None
    normalized = value.strip()
    lowered = normalized.casefold()
    if (
        not normalized
        or len(normalized) > 128
        or not normalized.isascii()
        or not normalized[0].isalnum()
        or "-" not in normalized
        or any(
            not (character.isalnum() or character == "-")
            for character in normalized
        )
        or any(
            marker in lowered
            for marker in (
                "select",
                "insert",
                "update",
                "delete",
                "sqlite",
                "table",
                "token",
                "password",
                "secret",
            )
        )
    ):
        return None
    return normalized


def _version_explanation(classification: RuntimeHealthClassification) -> str:
    return {
        RuntimeHealthClassification.HEALTHY: (
            "Version identities and Reproduction Manifest format are compatible."
        ),
        RuntimeHealthClassification.UNAVAILABLE: (
            "Version compatibility facts are unavailable."
        ),
        RuntimeHealthClassification.INCOMPATIBLE: (
            "A release or Reproduction Manifest binding is incompatible."
        ),
        RuntimeHealthClassification.UNKNOWN: (
            "Version compatibility is unknown."
        ),
    }.get(classification, "Version compatibility is degraded.")


def _retained_component(
    component: SystemHealthComponent,
    *,
    revision: int,
    observed_at: datetime,
    freshness_threshold: timedelta,
    recovery_phase: RuntimeHealthRecoveryPhase,
) -> SystemHealthComponent:
    last_success = (
        component.last_successful_observation_at or component.observed_at
    )
    age = max(observed_at - last_success, timedelta(0))
    is_stale = age > freshness_threshold
    classification = (
        RuntimeHealthClassification.RECOVERING
        if recovery_phase is RuntimeHealthRecoveryPhase.REREADING
        else RuntimeHealthClassification.STALE
        if is_stale
        else RuntimeHealthClassification.DEGRADED
    )
    explanation = (
        "Health facts are being reread; showing the last reliable observation."
        if classification is RuntimeHealthClassification.RECOVERING
        else "Health facts are stale; showing the last reliable observation."
        if classification is RuntimeHealthClassification.STALE
        else "Health facts are degraded; showing the last reliable observation."
    )
    if isinstance(component, PersistenceHealthComponent):
        return replace(
            component,
            classification=classification,
            revision=revision,
            observed_at=observed_at,
            explanation=explanation,
            freshness=(Freshness.STALE if is_stale else Freshness.FRESH),
            age=age,
            recovery_phase=recovery_phase,
        )
    if not isinstance(component, RuntimeHealthComponent):
        return replace(
            component,
            classification=classification,
            revision=revision,
            observed_at=observed_at,
            explanation=explanation,
            recovery_phase=recovery_phase,
        )
    return replace(
        component,
        classification=classification,
        revision=revision,
        observed_at=observed_at,
        explanation=explanation,
    )


def _age_components(
    components: tuple[SystemHealthComponent, ...],
    *,
    observed_at: datetime,
    freshness_threshold: timedelta,
) -> tuple[SystemHealthComponent, ...]:
    aged: list[SystemHealthComponent] = []
    for component in components:
        if not isinstance(component, PersistenceHealthComponent):
            aged.append(component)
            continue
        last_success = (
            component.last_successful_observation_at or component.observed_at
        )
        age = max(observed_at - last_success, timedelta(0))
        aged.append(
            replace(
                component,
                age=age,
                freshness=(
                    Freshness.STALE
                    if age > freshness_threshold
                    else Freshness.FRESH
                ),
            )
        )
    return tuple(aged)


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
