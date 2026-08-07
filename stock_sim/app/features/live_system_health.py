"""Live and deterministic adapters for System Health Feature Interface 1.0."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import RLock, Timer

from app.event_bridge import (
    EventBridge,
    EventBridgeBatch,
    EventBridgeConnectionPhase,
    EventBridgeConnectionState,
    EventBridgeSourceMode,
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
    DiagnosticDataSourceComponentIdentity,
    DiagnosticDataSourceConnectionState,
    DiagnosticDataSourceFallbackState,
    DiagnosticDataSourceHealthClassification,
    DiagnosticDataSourceHealthComponent,
    DiagnosticDataSourceIdentity,
    DiagnosticDataSourceObservation,
    DiagnosticDataSourceRecoveryPhase,
    DiagnosticDataSourceRevision,
    DiagnosticDataSourceScope,
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
    DiagnosticDataSourceApplicationAvailability,
    DiagnosticDataSourceApplicationError,
    DiagnosticDataSourceApplicationErrorCode,
    DiagnosticDataSourceApplicationObservation,
    DiagnosticDataSourceApplicationResult,
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
        read_data_source_health: Callable[
            [], DiagnosticDataSourceApplicationResult
        ],
        source_kind: SourceKind,
        source_identity: str,
        clock: Callable[[], datetime],
        freshness_threshold: timedelta,
    ) -> None:
        if freshness_threshold <= timedelta(0):
            raise ValueError("System Health freshness threshold must be positive")
        self._read_runtime_health = read_runtime_health
        self._read_data_source_health = read_data_source_health
        self._source_kind = source_kind
        self._source_identity = source_identity
        self._clock = clock
        self._freshness_threshold = freshness_threshold
        self._context = SystemHealthContext()
        self._generation = SourceGenerationId(1)
        self._connected = True
        self._fallback_active = False
        self._revision = 0
        self._state: SystemHealthViewState | None = None
        self._last_reliable: RuntimeHealthComponent | None = None
        self._data_source_component: DiagnosticDataSourceHealthComponent | None = None
        self._data_source_revision = 0
        self._data_source_highest_seen_revision = 0
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
        self.mark_reconnected_with_source_mode(
            generation=generation,
            fallback=False,
        )

    def mark_reconnected_with_source_mode(
        self,
        *,
        generation: int | None = None,
        fallback: bool,
    ) -> None:
        with self._transition_lock:
            with self._lock:
                if self._closed:
                    return
                if self._connected and not fallback:
                    return
                if (
                    self._connected
                    and fallback
                    and self._data_source_component is not None
                    and self._data_source_component.fallback
                    is DiagnosticDataSourceFallbackState.ACTIVE
                ):
                    return
                self._connected = True
                self._fallback_active = fallback
                self._generation = SourceGenerationId(
                    generation
                    if generation is not None
                    else self._generation.value + 1
                )
                has_state = self._state is not None
                if has_state:
                    self._data_source_component = _retained_data_source_component(
                        self._data_source_component,
                        observed_at=_aware(self._clock()),
                        generation=self._generation,
                        connection=(
                            DiagnosticDataSourceConnectionState.RECONNECTING
                        ),
                        fallback=(
                            DiagnosticDataSourceFallbackState.ACTIVE
                            if fallback
                            else DiagnosticDataSourceFallbackState.PRIMARY
                        ),
                        recovery_phase=(
                            DiagnosticDataSourceRecoveryPhase.FALLBACK
                            if fallback
                            else DiagnosticDataSourceRecoveryPhase.RECONNECTING
                        ),
                        error=None,
                        freshness_threshold=self._freshness_threshold,
                    )
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

    def accept_data_source_revision(
        self,
        revision: int,
        *,
        generation: int,
    ) -> None:
        with self._transition_lock:
            with self._lock:
                if (
                    self._closed
                    or not self._connected
                    or generation != self._generation.value
                    or revision <= self._data_source_highest_seen_revision
                    or self._state is None
                ):
                    return
                self._data_source_highest_seen_revision = revision
                current = self._data_source_component
                fallback = (
                    (
                        DiagnosticDataSourceFallbackState.ACTIVE
                        if self._fallback_active
                        else DiagnosticDataSourceFallbackState.PRIMARY
                    )
                    if current is None
                    or current.fallback
                    is DiagnosticDataSourceFallbackState.UNAVAILABLE
                    else current.fallback
                )
            rereading = _retained_data_source_component(
                current,
                observed_at=_aware(self._clock()),
                generation=SourceGenerationId(generation),
                connection=DiagnosticDataSourceConnectionState.RECONNECTING,
                fallback=fallback,
                recovery_phase=DiagnosticDataSourceRecoveryPhase.REREADING,
                error=None,
                freshness_threshold=self._freshness_threshold,
            )
            self._publish_data_source_component(rereading)
        result = self._read_data_source_health()
        with self._transition_lock:
            with self._lock:
                if (
                    self._closed
                    or not self._connected
                    or generation != self._generation.value
                    or revision != self._data_source_highest_seen_revision
                ):
                    return
            if (
                result.availability
                is DiagnosticDataSourceApplicationAvailability.READY
                and result.observation is not None
            ):
                recovered = _accepted_data_source_component(
                    result,
                    revision=revision,
                    generation=SourceGenerationId(generation),
                    fallback=fallback,
                    recovery_phase=DiagnosticDataSourceRecoveryPhase.RECOVERED,
                    freshness_threshold=self._freshness_threshold,
                )
            else:
                recovered = _retained_data_source_component(
                    current,
                    observed_at=_aware(self._clock()),
                    generation=SourceGenerationId(generation),
                    connection=DiagnosticDataSourceConnectionState.RECONNECTING,
                    fallback=fallback,
                    recovery_phase=(
                        DiagnosticDataSourceRecoveryPhase.FAILED_RECOVERY
                    ),
                    error=_data_source_feature_error(result),
                    freshness_threshold=self._freshness_threshold,
                )
            self._publish_data_source_component(recovered)

    def _publish_data_source_component(
        self,
        component: DiagnosticDataSourceHealthComponent,
    ) -> None:
        with self._lock:
            if self._closed or self._state is None:
                return
            revision = self._next_revision_locked()
            state = replace(
                self._state,
                revision=revision,
                observed_at=_aware(self._clock()),
                source=replace(self._state.source, generation=self._generation),
                diagnostic_data_source=component,
            )
            state = _with_data_source_aggregate(state)
            self._data_source_component = component
        self._store_and_deliver(state, notify=True)

    def set_generation(self, generation: int, *, fallback: bool = False) -> None:
        with self._transition_lock:
            with self._lock:
                if not self._closed:
                    self._generation = SourceGenerationId(generation)
                    self._fallback_active = fallback

    def is_current_generation(self, generation: int) -> bool:
        with self._lock:
            return (
                not self._closed
                and self._connected
                and self._generation.value == generation
            )

    def current_generation(self) -> int:
        with self._lock:
            return self._generation.value

    def data_source_freshness_delay(self) -> float | None:
        with self._lock:
            if self._closed or self._data_source_component is None:
                return None
            component = self._data_source_component
        reliable = component.last_reliable_observation
        if reliable is None or component.freshness is Freshness.STALE:
            return None
        age = max(_aware(self._clock()) - reliable.observed_at, timedelta(0))
        return max(
            (component.freshness_threshold - age).total_seconds(),
            0.0,
        )

    def publish_data_source_freshness(self) -> None:
        with self._transition_lock:
            with self._lock:
                if self._closed or self._state is None:
                    return
                current = self._data_source_component
                if current is None:
                    return
                now = _aware(self._clock())
                aged = _age_data_source_component(current, observed_at=now)
                if aged == current:
                    return
                revision = self._next_revision_locked()
                state = replace(
                    self._state,
                    revision=revision,
                    observed_at=now,
                    source=replace(
                        self._state.source,
                        generation=self._generation,
                    ),
                    diagnostic_data_source=aged,
                )
                self._data_source_component = aged
            self._store_and_deliver(_with_data_source_aggregate(state))

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
        data_source_result = (
            self._read_data_source_health()
            if self._data_source_component is None
            else None
        )
        with self._lock:
            self._ensure_open()
            revision = self._next_revision_locked()
            generation = self._generation
        now = _aware(self._clock())
        if data_source_result is not None:
            if (
                data_source_result.availability
                is DiagnosticDataSourceApplicationAvailability.READY
                and data_source_result.observation is not None
            ):
                self._data_source_revision += 1
                self._data_source_highest_seen_revision = (
                    self._data_source_revision
                )
            self._data_source_component = _initial_data_source_component(
                data_source_result,
                revision=max(self._data_source_revision, 1),
                generation=generation,
                fallback_active=self._fallback_active,
                freshness_threshold=self._freshness_threshold,
            )

        data_source_component = self._data_source_component
        if data_source_component is None:
            data_source_component = _unavailable_data_source_component(
                observed_at=now,
                generation=generation,
                freshness_threshold=self._freshness_threshold,
            )
        else:
            data_source_component = _age_data_source_component(
                data_source_component,
                observed_at=now,
            )
        self._data_source_component = data_source_component
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
                diagnostic_data_source=data_source_component,
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
                    diagnostic_data_source=data_source_component,
                    last_reliable_payload=None,
                    recovery_phase=(
                        RuntimeHealthRecoveryPhase.FAILED
                        if reread
                        else recovery_phase
                    ),
                    error=error,
                )
        return self._store_and_deliver(
            _with_data_source_aggregate(state),
            notify=notify,
        )

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
            data_source = self._data_source_component
            if recovery_phase is RuntimeHealthRecoveryPhase.DISCONNECTED:
                self._data_source_component = _retained_data_source_component(
                    data_source,
                    observed_at=_aware(self._clock()),
                    generation=generation,
                    connection=DiagnosticDataSourceConnectionState.DISCONNECTED,
                    fallback=(
                        data_source.fallback
                        if data_source is not None
                        else DiagnosticDataSourceFallbackState.UNAVAILABLE
                    ),
                    recovery_phase=DiagnosticDataSourceRecoveryPhase.DISCONNECTED,
                    error=SystemHealthError(
                        code=SystemHealthErrorCode.DATA_SOURCE_DISCONNECTED,
                        explanation=(
                            "The diagnostic data source is disconnected; the last "
                            "reliable observation is retained when available."
                        ),
                        retryable=True,
                    ),
                    freshness_threshold=self._freshness_threshold,
                )
        state = self._retained_state(
            revision=revision,
            observed_at=_aware(self._clock()),
            generation=generation,
            recovery_phase=recovery_phase,
            error=error,
        )
        return self._store_and_deliver(
            _with_data_source_aggregate(state),
            notify=notify,
        )

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
                diagnostic_data_source=(
                    self._data_source_component
                    or _unavailable_data_source_component(
                        observed_at=observed_at,
                        generation=generation,
                        freshness_threshold=self._freshness_threshold,
                    )
                ),
                last_reliable_payload=None,
                recovery_phase=recovery_phase,
                error=error,
            )

        age = max(observed_at - reliable.observed_at, timedelta(0))
        is_stale = age >= self._freshness_threshold
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
            diagnostic_data_source=(
                self._data_source_component
                or _unavailable_data_source_component(
                    observed_at=observed_at,
                    generation=generation,
                    freshness_threshold=self._freshness_threshold,
                )
            ),
            last_reliable_payload=reliable,
            recovery_phase=recovery_phase,
            error=error,
        )

    def _age_state(self, state: SystemHealthViewState) -> SystemHealthViewState:
        reliable = state.last_reliable_payload
        now = _aware(self._clock())
        data_source = _age_data_source_component(
            state.diagnostic_data_source,
            observed_at=now,
        )
        self._data_source_component = data_source
        if reliable is None:
            if data_source is state.diagnostic_data_source:
                return state
            with self._lock:
                revision = self._next_revision_locked()
            return _with_data_source_aggregate(
                replace(
                    state,
                    revision=revision,
                    observed_at=now,
                    diagnostic_data_source=data_source,
                )
            )
        age = max(now - reliable.observed_at, timedelta(0))
        runtime_is_stale = bool(
            state.components
            and state.components[0].classification
            is RuntimeHealthClassification.STALE
        )
        runtime_should_be_stale = age >= self._freshness_threshold
        overall_age = max(age, data_source.age)
        if (
            data_source is state.diagnostic_data_source
            and runtime_is_stale is runtime_should_be_stale
            and overall_age == state.age
        ):
            return state
        with self._lock:
            revision = self._next_revision_locked()
            generation = self._generation
        if age < self._freshness_threshold:
            return _with_data_source_aggregate(
                replace(
                    state,
                    revision=revision,
                    observed_at=now,
                    age=age,
                    source=replace(state.source, generation=generation),
                    diagnostic_data_source=data_source,
                )
            )
        if runtime_is_stale:
            return _with_data_source_aggregate(
                replace(
                    state,
                    revision=revision,
                    observed_at=now,
                    age=age,
                    source=replace(state.source, generation=generation),
                    diagnostic_data_source=data_source,
                )
            )
        return _with_data_source_aggregate(
            self._retained_state(
                revision=revision,
                observed_at=now,
                generation=generation,
                recovery_phase=state.recovery_phase,
                error=state.error,
            )
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
        executor: Executor | None = None,
    ) -> None:
        self._closed = False
        self._lock = RLock()
        self._connection_sequence = 0
        self._connection_generation = event_bridge.connection_generation.value
        self._owns_executor = executor is None
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=f"system-health-{id(self):x}",
        )
        self._pending_data_source_delivery: tuple[int, int] | None = None
        self._data_source_refresh_scheduled = False
        self._highest_enqueued_revision = 0
        self._freshness_timer: Timer | None = None
        self._freshness_timer_sequence = 0
        self._dispose_connection_subscription: Callable[[], None] = lambda: None
        self._dispose_batch_subscription: Callable[[], None] = lambda: None
        self._projection = _SystemHealthProjection(
            read_runtime_health=application_health.read_runtime_health,
            read_data_source_health=(
                application_health.read_diagnostic_data_source_health
            ),
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
        state = self._projection.snapshot(context)
        self._schedule_freshness_deadline()
        return state

    def subscribe(
        self,
        context: SystemHealthContext,
        observer: SystemHealthObserver,
    ) -> Subscription:
        subscription = self._projection.subscribe(context, observer)
        self._schedule_freshness_deadline()
        return subscription

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            dispose_batches = self._dispose_batch_subscription
            dispose_connection = self._dispose_connection_subscription
            self._dispose_batch_subscription = lambda: None
            self._dispose_connection_subscription = lambda: None
            self._pending_data_source_delivery = None
            self._data_source_refresh_scheduled = False
            freshness_timer = self._freshness_timer
            self._freshness_timer = None
            self._freshness_timer_sequence += 1
        if freshness_timer is not None:
            freshness_timer.cancel()
        dispose_batches()
        dispose_connection()
        self._projection.close()
        if self._owns_executor:
            self._executor.shutdown(
                wait=False,
                cancel_futures=True,
            )

    def _on_snapshot_batch(self, batch: EventBridgeBatch) -> None:
        if not self._projection.is_current_generation(batch.generation.value):
            return
        data_source_revisions = tuple(
            revision
            for snapshot in batch.snapshots
            if _is_data_source_health_delivery(snapshot)
            if (revision := _source_revision(snapshot)) is not None
        )
        if data_source_revisions:
            self._schedule_data_source_revision(
                max(data_source_revisions),
                generation=batch.generation.value,
            )
        if any(_is_runtime_health_delivery(snapshot) for snapshot in batch.snapshots):
            self._projection.publish_authoritative_observation()

    def _schedule_data_source_revision(
        self,
        revision: int,
        *,
        generation: int,
    ) -> None:
        should_schedule = False
        with self._lock:
            if (
                self._closed
                or generation != self._connection_generation
                or revision <= self._highest_enqueued_revision
            ):
                return
            self._highest_enqueued_revision = revision
            pending = self._pending_data_source_delivery
            if pending is None or pending[0] != generation or revision > pending[1]:
                self._pending_data_source_delivery = (generation, revision)
            if not self._data_source_refresh_scheduled:
                self._data_source_refresh_scheduled = True
                should_schedule = True
        if should_schedule:
            try:
                self._executor.submit(self._drain_data_source_revisions)
            except RuntimeError:
                with self._lock:
                    if not self._closed:
                        self._data_source_refresh_scheduled = False
                        self._pending_data_source_delivery = None
                        raise

    def _drain_data_source_revisions(self) -> None:
        while True:
            with self._lock:
                if self._closed:
                    self._pending_data_source_delivery = None
                    self._data_source_refresh_scheduled = False
                    return
                pending = self._pending_data_source_delivery
                self._pending_data_source_delivery = None
                if pending is None:
                    self._data_source_refresh_scheduled = False
                    return
            generation, revision = pending
            self._projection.accept_data_source_revision(
                revision,
                generation=generation,
            )
            self._schedule_freshness_deadline()

    def _on_connection_state(self, state: EventBridgeConnectionState) -> None:
        with self._lock:
            if self._closed or state.sequence.value <= self._connection_sequence:
                return
            first_observation = self._connection_sequence == 0
            self._connection_sequence = state.sequence.value
            if state.generation.value != self._connection_generation:
                self._connection_generation = state.generation.value
                self._highest_enqueued_revision = 0
                self._pending_data_source_delivery = None
        if state.phase is EventBridgeConnectionPhase.DISCONNECTED:
            self._projection.mark_disconnected(generation=state.generation.value)
        elif first_observation:
            self._projection.set_generation(
                state.generation.value,
                fallback=(state.source_mode is EventBridgeSourceMode.FALLBACK),
            )
        else:
            self._projection.mark_reconnected_with_source_mode(
                generation=state.generation.value,
                fallback=(state.source_mode is EventBridgeSourceMode.FALLBACK),
            )
        self._schedule_freshness_deadline()

    def _schedule_freshness_deadline(self) -> None:
        delay = self._projection.data_source_freshness_delay()
        with self._lock:
            if self._closed:
                return
            previous = self._freshness_timer
            self._freshness_timer = None
            self._freshness_timer_sequence += 1
            sequence = self._freshness_timer_sequence
            if delay is None:
                timer = None
            else:
                timer = Timer(
                    max(delay, 0.001),
                    lambda: self._on_freshness_deadline(sequence),
                )
                timer.daemon = True
                self._freshness_timer = timer
        if previous is not None:
            previous.cancel()
        if timer is not None:
            timer.start()

    def _on_freshness_deadline(self, sequence: int) -> None:
        with self._lock:
            if self._closed or sequence != self._freshness_timer_sequence:
                return
            self._freshness_timer = None
        self._projection.publish_data_source_freshness()
        self._schedule_freshness_deadline()


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
        self._fail_data_source_reread = False
        self._source_revision = 0
        self._projection = _SystemHealthProjection(
            read_runtime_health=self._read_runtime_health,
            read_data_source_health=self._read_data_source_health,
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

    def advance_data_source_to_fallback(self) -> None:
        self._projection.mark_reconnected_with_source_mode(fallback=True)

    def deliver_data_source_revision(
        self,
        revision: int,
        *,
        generation: int | None = None,
    ) -> None:
        current_generation = (
            self._projection.current_generation()
            if generation is None
            else generation
        )
        self._projection.accept_data_source_revision(
            revision,
            generation=current_generation,
        )

    def fail_next_data_source_reread(self) -> None:
        self._fail_data_source_reread = True

    def advance_clock(self, delta: timedelta) -> None:
        if delta < timedelta(0):
            raise ValueError("Deterministic System Health clock cannot go backwards")
        self._now += delta
        self._projection.publish_data_source_freshness()

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

    def _read_data_source_health(self) -> DiagnosticDataSourceApplicationResult:
        observed_at = self._clock()
        if self._fail_data_source_reread:
            self._fail_data_source_reread = False
            return DiagnosticDataSourceApplicationResult(
                availability=DiagnosticDataSourceApplicationAvailability.FAILED,
                observation=None,
                source_token=None,
                observed_at=observed_at,
                error=DiagnosticDataSourceApplicationError(
                    code=DiagnosticDataSourceApplicationErrorCode.READ_FAILED,
                    explanation="The deterministic Data Source Health read failed.",
                    retryable=True,
                ),
            )
        if not self._healthy:
            return DiagnosticDataSourceApplicationResult(
                availability=(
                    DiagnosticDataSourceApplicationAvailability.NO_ADMITTED_SOURCE
                ),
                observation=None,
                source_token=None,
                observed_at=observed_at,
                error=DiagnosticDataSourceApplicationError(
                    code=(
                        DiagnosticDataSourceApplicationErrorCode.NO_ADMITTED_SOURCE
                    ),
                    explanation="No admitted diagnostic data source is available.",
                    retryable=True,
                ),
            )
        token = hashlib.sha256(b"deterministic-admitted-data-source").hexdigest()
        return DiagnosticDataSourceApplicationResult(
            availability=DiagnosticDataSourceApplicationAvailability.READY,
            observation=DiagnosticDataSourceApplicationObservation(
                identity=DiagnosticDataSourceIdentity(
                    public_id=f"admitted-source-{token[:16]}",
                    provider=f"Provider {token[:8]}",
                    dataset=f"Dataset {token[8:16]}",
                    version=f"Version {token[16:24]}",
                ),
                observed_at=observed_at,
                affected_scope=(
                    DiagnosticDataSourceScope.SCENARIO_INPUTS,
                    DiagnosticDataSourceScope.DIAGNOSTIC_EVIDENCE_INTERPRETATION,
                ),
            ),
            source_token=SourceRevisionToken(token),
            observed_at=observed_at,
            error=None,
        )


def _is_data_source_health_delivery(snapshot: dict[str, object]) -> bool:
    return (
        str(snapshot.get("feature", "")).casefold() == "system_health"
        and str(snapshot.get("component", "")).casefold()
        == "diagnostic_data_source"
    )


def _is_runtime_health_delivery(snapshot: dict[str, object]) -> bool:
    return (
        str(snapshot.get("feature", "")).casefold() == "system_health"
        and not _is_data_source_health_delivery(snapshot)
    )


def _source_revision(snapshot: dict[str, object]) -> int | None:
    value = snapshot.get("source_revision")
    if isinstance(value, bool):
        return None
    try:
        revision = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return revision if revision > 0 else None


def _initial_data_source_component(
    result: DiagnosticDataSourceApplicationResult,
    *,
    revision: int,
    generation: SourceGenerationId,
    fallback_active: bool,
    freshness_threshold: timedelta,
) -> DiagnosticDataSourceHealthComponent:
    if (
        result.availability is DiagnosticDataSourceApplicationAvailability.READY
        and result.observation is not None
    ):
        return _accepted_data_source_component(
            result,
            revision=revision,
            generation=generation,
            fallback=(
                DiagnosticDataSourceFallbackState.ACTIVE
                if fallback_active
                else DiagnosticDataSourceFallbackState.PRIMARY
            ),
            recovery_phase=(
                DiagnosticDataSourceRecoveryPhase.RECOVERED
                if fallback_active
                else DiagnosticDataSourceRecoveryPhase.IDLE
            ),
            freshness_threshold=freshness_threshold,
        )
    return _unavailable_data_source_component(
        observed_at=result.observed_at,
        generation=generation,
        connection=(
            DiagnosticDataSourceConnectionState.RECONNECTING
            if fallback_active
            else DiagnosticDataSourceConnectionState.UNAVAILABLE
        ),
        fallback=(
            DiagnosticDataSourceFallbackState.ACTIVE
            if fallback_active
            else DiagnosticDataSourceFallbackState.UNAVAILABLE
        ),
        recovery_phase=(
            DiagnosticDataSourceRecoveryPhase.FALLBACK
            if fallback_active
            else DiagnosticDataSourceRecoveryPhase.IDLE
        ),
        freshness_threshold=freshness_threshold,
    )


def _accepted_data_source_component(
    result: DiagnosticDataSourceApplicationResult,
    *,
    revision: int,
    generation: SourceGenerationId,
    fallback: DiagnosticDataSourceFallbackState,
    recovery_phase: DiagnosticDataSourceRecoveryPhase,
    freshness_threshold: timedelta,
) -> DiagnosticDataSourceHealthComponent:
    observation_result = result.observation
    if observation_result is None:
        raise ValueError("Accepted Data Source Health requires an observation")
    accepted_revision = DiagnosticDataSourceRevision(revision)
    age = max(
        result.observed_at - observation_result.observed_at,
        timedelta(0),
    )
    stale = age >= freshness_threshold
    observation = DiagnosticDataSourceObservation(
        identity=observation_result.identity,
        revision=accepted_revision,
        generation=generation,
        observed_at=observation_result.observed_at,
    )
    return DiagnosticDataSourceHealthComponent(
        identity=(
            DiagnosticDataSourceComponentIdentity.ADMITTED_HISTORICAL_MARKET_DATA
        ),
        classification=(
            DiagnosticDataSourceHealthClassification.STALE
            if stale
            else DiagnosticDataSourceHealthClassification.HEALTHY
        ),
        connection=DiagnosticDataSourceConnectionState.CONNECTED,
        fallback=fallback,
        accepted_revision=accepted_revision,
        accepted_generation=generation,
        observed_at=result.observed_at,
        freshness=Freshness.STALE if stale else Freshness.FRESH,
        age=age,
        freshness_threshold=freshness_threshold,
        last_reliable_observation=observation,
        affected_scope=observation_result.affected_scope,
        recovery_phase=recovery_phase,
        explanation=(
            "The authoritative diagnostic data-source reread succeeded, but the source observation remains stale."
            if stale
            and recovery_phase is DiagnosticDataSourceRecoveryPhase.RECOVERED
            else "The admitted diagnostic data source is stale."
            if stale
            else "The admitted diagnostic data source recovered through fallback."
            if fallback is DiagnosticDataSourceFallbackState.ACTIVE
            and recovery_phase is DiagnosticDataSourceRecoveryPhase.RECOVERED
            else "The admitted diagnostic data source is fresh."
        ),
        error=None,
    )


def _unavailable_data_source_component(
    *,
    observed_at: datetime,
    generation: SourceGenerationId,
    connection: DiagnosticDataSourceConnectionState = (
        DiagnosticDataSourceConnectionState.UNAVAILABLE
    ),
    fallback: DiagnosticDataSourceFallbackState = (
        DiagnosticDataSourceFallbackState.UNAVAILABLE
    ),
    recovery_phase: DiagnosticDataSourceRecoveryPhase = (
        DiagnosticDataSourceRecoveryPhase.IDLE
    ),
    freshness_threshold: timedelta,
) -> DiagnosticDataSourceHealthComponent:
    return DiagnosticDataSourceHealthComponent(
        identity=(
            DiagnosticDataSourceComponentIdentity.ADMITTED_HISTORICAL_MARKET_DATA
        ),
        classification=DiagnosticDataSourceHealthClassification.UNAVAILABLE,
        connection=connection,
        fallback=fallback,
        accepted_revision=None,
        accepted_generation=None,
        observed_at=observed_at,
        freshness=Freshness.AWAITING_FIRST_STATE,
        age=timedelta(0),
        freshness_threshold=freshness_threshold,
        last_reliable_observation=None,
        affected_scope=(
            DiagnosticDataSourceScope.SCENARIO_INPUTS,
            DiagnosticDataSourceScope.DIAGNOSTIC_EVIDENCE_INTERPRETATION,
        ),
        recovery_phase=recovery_phase,
        explanation="No admitted diagnostic data source is available.",
        error=SystemHealthError(
            code=SystemHealthErrorCode.DATA_SOURCE_UNAVAILABLE,
            explanation="No admitted diagnostic data source is available.",
            retryable=True,
        ),
    )


def _retained_data_source_component(
    previous: DiagnosticDataSourceHealthComponent | None,
    *,
    observed_at: datetime,
    generation: SourceGenerationId,
    connection: DiagnosticDataSourceConnectionState,
    fallback: DiagnosticDataSourceFallbackState,
    recovery_phase: DiagnosticDataSourceRecoveryPhase,
    error: SystemHealthError | None,
    freshness_threshold: timedelta,
) -> DiagnosticDataSourceHealthComponent:
    reliable = None if previous is None else previous.last_reliable_observation
    if reliable is None:
        return DiagnosticDataSourceHealthComponent(
            identity=(
                DiagnosticDataSourceComponentIdentity.ADMITTED_HISTORICAL_MARKET_DATA
            ),
            classification=DiagnosticDataSourceHealthClassification.UNAVAILABLE,
            connection=connection,
            fallback=fallback,
            accepted_revision=None,
            accepted_generation=None,
            observed_at=observed_at,
            freshness=(
                Freshness.DISCONNECTED
                if connection is DiagnosticDataSourceConnectionState.DISCONNECTED
                else Freshness.AWAITING_FIRST_STATE
            ),
            age=timedelta(0),
            freshness_threshold=freshness_threshold,
            last_reliable_observation=None,
            affected_scope=(
                DiagnosticDataSourceScope.SCENARIO_INPUTS,
                DiagnosticDataSourceScope.DIAGNOSTIC_EVIDENCE_INTERPRETATION,
            ),
            recovery_phase=recovery_phase,
            explanation="No reliable diagnostic data-source observation is available.",
            error=error,
        )
    age = max(observed_at - reliable.observed_at, timedelta(0))
    stale = age >= freshness_threshold
    recovering = recovery_phase in {
        DiagnosticDataSourceRecoveryPhase.FALLBACK,
        DiagnosticDataSourceRecoveryPhase.RECONNECTING,
        DiagnosticDataSourceRecoveryPhase.REREADING,
    }
    return DiagnosticDataSourceHealthComponent(
        identity=previous.identity,
        classification=(
            DiagnosticDataSourceHealthClassification.STALE
            if stale
            else DiagnosticDataSourceHealthClassification.RECOVERING
            if recovering
            else DiagnosticDataSourceHealthClassification.DEGRADED
        ),
        connection=connection,
        fallback=fallback,
        accepted_revision=previous.accepted_revision,
        accepted_generation=previous.accepted_generation,
        observed_at=observed_at,
        freshness=(
            Freshness.STALE
            if stale
            else Freshness.DISCONNECTED
            if connection is DiagnosticDataSourceConnectionState.DISCONNECTED
            else Freshness.FRESH
        ),
        age=age,
        freshness_threshold=freshness_threshold,
        last_reliable_observation=reliable,
        affected_scope=previous.affected_scope,
        recovery_phase=recovery_phase,
        explanation=(
            "Diagnostic data-source health is stale; showing the last reliable observation."
            if stale
            else "Diagnostic data-source recovery is in progress; showing the last reliable observation."
            if recovering
            else "Diagnostic data-source health is degraded; showing the last reliable observation."
        ),
        error=error,
    )


def _age_data_source_component(
    component: DiagnosticDataSourceHealthComponent,
    *,
    observed_at: datetime,
) -> DiagnosticDataSourceHealthComponent:
    reliable = component.last_reliable_observation
    if reliable is None:
        return component
    age = max(observed_at - reliable.observed_at, timedelta(0))
    if age == component.age:
        return component
    if age < component.freshness_threshold:
        return replace(component, observed_at=observed_at, age=age)
    return replace(
        component,
        classification=DiagnosticDataSourceHealthClassification.STALE,
        observed_at=observed_at,
        freshness=Freshness.STALE,
        age=age,
        explanation=(
            "Diagnostic data-source health is stale; showing the last reliable observation."
        ),
    )


def _data_source_feature_error(
    result: DiagnosticDataSourceApplicationResult,
) -> SystemHealthError:
    retryable = True if result.error is None else result.error.retryable
    return SystemHealthError(
        code=SystemHealthErrorCode.DATA_SOURCE_REREAD_FAILED,
        explanation="The authoritative diagnostic data-source reread failed safely.",
        retryable=retryable,
    )


def _presentation_for(
    classification: RuntimeHealthClassification,
) -> SystemHealthPresentationState:
    return SystemHealthPresentationState(classification.value)


def _with_data_source_aggregate(
    state: SystemHealthViewState,
) -> SystemHealthViewState:
    """Prevent Runtime Health from masking an unhealthy diagnostic source."""

    source = state.diagnostic_data_source
    aggregate = replace(
        state,
        freshness=_least_fresh(state.freshness, source.freshness),
        age=max(state.age, source.age),
    )
    if not state.components:
        return aggregate
    runtime_presentation = _presentation_for(state.components[0].classification)
    if runtime_presentation is not SystemHealthPresentationState.HEALTHY:
        return aggregate

    if (
        source.classification is DiagnosticDataSourceHealthClassification.HEALTHY
        and source.connection is DiagnosticDataSourceConnectionState.CONNECTED
        and source.fallback is DiagnosticDataSourceFallbackState.PRIMARY
    ):
        return replace(
            aggregate,
            phase=ViewPhase.READY,
            presentation=SystemHealthPresentationState.HEALTHY,
            completeness=Completeness.COMPLETE,
        )
    if (
        source.classification
        is DiagnosticDataSourceHealthClassification.UNAVAILABLE
        and source.last_reliable_observation is None
    ):
        return replace(
            aggregate,
            phase=ViewPhase.FAILED,
            presentation=SystemHealthPresentationState.UNAVAILABLE,
            completeness=Completeness.PARTIAL,
        )
    if source.classification is DiagnosticDataSourceHealthClassification.STALE:
        return replace(
            aggregate,
            phase=ViewPhase.DEGRADED,
            presentation=SystemHealthPresentationState.STALE,
            completeness=Completeness.PARTIAL,
        )
    return replace(
        aggregate,
        phase=ViewPhase.DEGRADED,
        presentation=SystemHealthPresentationState.DEGRADED,
        completeness=Completeness.PARTIAL,
    )


def _least_fresh(left: Freshness, right: Freshness) -> Freshness:
    """Return the finite overall freshness without hiding either component."""

    values = (left, right)
    if Freshness.AWAITING_FIRST_STATE in values:
        return Freshness.AWAITING_FIRST_STATE
    if Freshness.DISCONNECTED in values:
        return Freshness.DISCONNECTED
    if Freshness.STALE in values:
        return Freshness.STALE
    return Freshness.FRESH


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
