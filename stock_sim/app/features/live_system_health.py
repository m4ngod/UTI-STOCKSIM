"""Live and deterministic adapters for System Health Feature Interface 1.0."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Event, RLock, Thread, Timer, current_thread

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
    DiagnosticDataSourceApplicationAvailability,
    DiagnosticDataSourceApplicationError,
    DiagnosticDataSourceApplicationErrorCode,
    DiagnosticDataSourceApplicationObservation,
    DiagnosticDataSourceApplicationResult,
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
    """Own the immutable finite health state machine shared by both seams."""

    def __init__(
        self,
        *,
        read_runtime_health: Callable[[], RuntimeHealthApplicationResult],
        read_diagnostic_data_source_health: Callable[
            [], DiagnosticDataSourceApplicationResult
        ],
        read_diagnostic_queue_health: Callable[
            [], DiagnosticQueueApplicationResult
        ],
        read_diagnostic_cache_health: Callable[
            [], DiagnosticCacheApplicationResult
        ],
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
        self._read_diagnostic_data_source_health = (
            read_diagnostic_data_source_health
        )
        self._read_diagnostic_queue_health = read_diagnostic_queue_health
        self._read_diagnostic_cache_health = read_diagnostic_cache_health
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
        self._last_reliable_queue: DiagnosticQueueHealthComponent | None = None
        self._last_reliable_cache: DiagnosticCacheHealthComponent | None = None
        self._data_source_component: DiagnosticDataSourceHealthComponent | None = None
        self._data_source_revision = 0
        self._data_source_highest_seen_revision = 0
        self._fallback_active = False
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
                if self._closed or self._connected:
                    return
                self._connected = True
                self._generation = SourceGenerationId(
                    generation
                    if generation is not None
                    else self._generation.value + 1
                )
                self._fallback_active = fallback
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
                ):
                    return
                self._data_source_highest_seen_revision = revision
                state = self._state
                current = self._data_source_component
                fallback_active = self._fallback_active
            if state is None:
                state = self._refresh_transition(
                    recovery_phase=RuntimeHealthRecoveryPhase.IDLE,
                    notify=False,
                    reread=False,
                )
                current = state.diagnostic_data_source
            now = _aware(self._clock())
            rereading = _retained_data_source_component(
                current,
                observed_at=now,
                connection=DiagnosticDataSourceConnectionState.RECONNECTING,
                fallback=(
                    DiagnosticDataSourceFallbackState.ACTIVE
                    if fallback_active
                    else DiagnosticDataSourceFallbackState.PRIMARY
                ),
                recovery_phase=DiagnosticDataSourceRecoveryPhase.REREADING,
                error=None,
                freshness_threshold=self._freshness_threshold,
            )
            self._publish_data_source_component(rereading)
            result = self._read_diagnostic_data_source_health()
            with self._lock:
                if (
                    self._closed
                    or generation != self._generation.value
                    or not self._connected
                ):
                    return
            if (
                result.availability
                is DiagnosticDataSourceApplicationAvailability.READY
                and result.observation is not None
            ):
                component = _accepted_data_source_component(
                    result.observation,
                    revision=revision,
                    generation=SourceGenerationId(generation),
                    observed_at=_aware(self._clock()),
                    fallback_active=fallback_active,
                    recovery_phase=DiagnosticDataSourceRecoveryPhase.RECOVERED,
                    freshness_threshold=self._freshness_threshold,
                )
                self._data_source_revision = revision
            else:
                component = _retained_data_source_component(
                    current,
                    observed_at=_aware(self._clock()),
                    connection=DiagnosticDataSourceConnectionState.RECONNECTING,
                    fallback=(
                        DiagnosticDataSourceFallbackState.ACTIVE
                        if fallback_active
                        else DiagnosticDataSourceFallbackState.PRIMARY
                    ),
                    recovery_phase=(
                        DiagnosticDataSourceRecoveryPhase.FAILED_RECOVERY
                    ),
                    error=_data_source_feature_error(result),
                    freshness_threshold=self._freshness_threshold,
                )
            self._publish_data_source_component(component)

    def publish_data_source_freshness(self) -> None:
        with self._transition_lock:
            with self._lock:
                if self._closed or self._data_source_component is None:
                    return
                current = self._data_source_component
            aged = _age_data_source_component(
                current,
                observed_at=_aware(self._clock()),
            )
            if aged != current:
                self._publish_data_source_component(aged)

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
                diagnostic_queue=replace(
                    self._state.diagnostic_queue,
                    revision=revision,
                ),
                diagnostic_cache=replace(
                    self._state.diagnostic_cache,
                    revision=revision,
                ),
            )
            if (
                component.recovery_phase
                is DiagnosticDataSourceRecoveryPhase.RECOVERED
                and component.classification
                is DiagnosticDataSourceHealthClassification.HEALTHY
                and component.fallback
                is DiagnosticDataSourceFallbackState.PRIMARY
            ):
                presentation = _overall_presentation(
                    state.components,
                    recovery_phase=state.recovery_phase,
                )
                complete = presentation in {
                    SystemHealthPresentationState.HEALTHY,
                    SystemHealthPresentationState.RECOVERED,
                }
                state = replace(
                    state,
                    phase=ViewPhase.READY if complete else ViewPhase.DEGRADED,
                    presentation=presentation,
                    completeness=(
                        Completeness.COMPLETE
                        if complete
                        else Completeness.PARTIAL
                    ),
                )
            self._data_source_component = component
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
        runtime_result = self._read_runtime_health()
        data_source_result = (
            self._read_diagnostic_data_source_health()
            if self._data_source_component is None
            else None
        )
        queue_result = self._read_diagnostic_queue_health()
        cache_result = self._read_diagnostic_cache_health()
        persistence_result = self._read_persistence_health()
        version_result = self._read_version_health()
        authoritative_key = _authoritative_result_key(
            runtime_result,
            queue_result,
            cache_result,
            persistence_result,
            version_result,
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
            previous_components = self._last_reliable
        if data_source_result is not None:
            if (
                data_source_result.availability
                is DiagnosticDataSourceApplicationAvailability.READY
                and data_source_result.observation is not None
            ):
                self._data_source_revision = 1
                self._data_source_highest_seen_revision = 1
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
                freshness_threshold=self._freshness_threshold,
            )
        else:
            data_source_component = _age_data_source_component(
                data_source_component,
                observed_at=now,
            )
        self._data_source_component = data_source_component
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
                diagnostic_data_source=data_source_component,
                diagnostic_queue=queue_component,
                diagnostic_cache=cache_component,
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
                diagnostic_data_source=data_source_component,
                diagnostic_queue=queue_component,
                diagnostic_cache=cache_component,
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
                diagnostic_data_source=data_source_component,
                diagnostic_queue=queue_component,
                diagnostic_cache=cache_component,
                error=error,
            )
        with self._lock:
            self._current_authoritative_key = authoritative_key
            if notify:
                self._last_notified_authoritative_key = authoritative_key
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
        reliable_payload: tuple[SystemHealthComponent, ...] | None = None,
    ) -> SystemHealthViewState:
        reliable = (
            self._last_reliable
            if reliable_payload is None
            else reliable_payload
        )
        current_data_source = self._data_source_component
        if recovery_phase is RuntimeHealthRecoveryPhase.DISCONNECTED:
            data_source_component = _retained_data_source_component(
                current_data_source,
                observed_at=observed_at,
                connection=DiagnosticDataSourceConnectionState.DISCONNECTED,
                fallback=(
                    current_data_source.fallback
                    if current_data_source is not None
                    else DiagnosticDataSourceFallbackState.UNAVAILABLE
                ),
                recovery_phase=DiagnosticDataSourceRecoveryPhase.DISCONNECTED,
                error=SystemHealthError(
                    code=SystemHealthErrorCode.DATA_SOURCE_DISCONNECTED,
                    explanation=(
                        "The diagnostic data source is disconnected; the last "
                        "reliable observation is retained when available."
                    ),
                    affected_scope=SystemHealthAffectedScope.DIAGNOSTIC_EVIDENCE,
                    retryable=True,
                    recovery_expectation=(
                        SystemHealthRecoveryExpectation.SOURCE_RECONNECTION
                    ),
                ),
                freshness_threshold=self._freshness_threshold,
            )
        elif recovery_phase is RuntimeHealthRecoveryPhase.REREADING:
            data_source_component = _retained_data_source_component(
                current_data_source,
                observed_at=observed_at,
                connection=DiagnosticDataSourceConnectionState.RECONNECTING,
                fallback=(
                    DiagnosticDataSourceFallbackState.ACTIVE
                    if self._fallback_active
                    else DiagnosticDataSourceFallbackState.PRIMARY
                ),
                recovery_phase=(
                    DiagnosticDataSourceRecoveryPhase.FALLBACK
                    if self._fallback_active
                    else DiagnosticDataSourceRecoveryPhase.RECONNECTING
                ),
                error=None,
                freshness_threshold=self._freshness_threshold,
            )
        elif current_data_source is None:
            data_source_component = _unavailable_data_source_component(
                observed_at=observed_at,
                freshness_threshold=self._freshness_threshold,
            )
        else:
            data_source_component = _age_data_source_component(
                current_data_source,
                observed_at=observed_at,
            )
        self._data_source_component = data_source_component
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
                diagnostic_data_source=data_source_component,
                diagnostic_queue=queue_component,
                diagnostic_cache=cache_component,
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
            diagnostic_data_source=data_source_component,
            diagnostic_queue=queue_component,
            diagnostic_cache=cache_component,
            error=error,
        )

    def _age_state(self, state: SystemHealthViewState) -> SystemHealthViewState:
        reliable = state.last_reliable_payload
        if reliable is None:
            return state
        now = _aware(self._clock())
        data_source_component = _age_data_source_component(
            state.diagnostic_data_source,
            observed_at=now,
        )
        self._data_source_component = data_source_component
        reliable_at = min(
            component.last_successful_observation_at or component.observed_at
            for component in reliable
        )
        age = max(now - reliable_at, timedelta(0))
        if (
            age == state.age
            and data_source_component is state.diagnostic_data_source
        ):
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
            return _with_data_source_aggregate(
                replace(
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
                    diagnostic_data_source=data_source_component,
                    diagnostic_queue=queue_component,
                    diagnostic_cache=cache_component,
                )
            )
        if state.presentation is SystemHealthPresentationState.STALE:
            return _with_data_source_aggregate(
                replace(
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
                    diagnostic_data_source=data_source_component,
                    diagnostic_queue=queue_component,
                    diagnostic_cache=cache_component,
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
            if state.last_reliable_payload is not None:
                self._last_reliable = state.last_reliable_payload
            self._data_source_component = state.diagnostic_data_source
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
        sampling_interval: timedelta | None = timedelta(seconds=1),
    ) -> None:
        if sampling_interval is not None and sampling_interval <= timedelta(0):
            raise ValueError("System Health sampling interval must be positive")
        self._event_bridge = event_bridge
        initial_connection = event_bridge.connection_state
        self._closed = False
        self._lock = RLock()
        self._sampling_interval = sampling_interval
        self._worker_wake = Event()
        self._worker_thread: Thread | None = None
        self._pending_refresh_generation: int | None = None
        self._pending_data_source_delivery: tuple[int, int] | None = None
        self._highest_enqueued_revision = 0
        self._pending_connection_actions: list[
            tuple[EventBridgeConnectionPhase, int, bool, bool]
        ] = []
        self._connection_sequence = initial_connection.sequence.value
        self._connection_generation = initial_connection.generation.value
        self._dispose_connection_subscription: Callable[[], None] = lambda: None
        self._dispose_batch_subscription: Callable[[], None] = lambda: None
        self._freshness_timer: Timer | None = None
        self._freshness_timer_sequence = 0
        active_clock = clock or _default_live_clock
        data_source_reader = getattr(
            application_health,
            "read_diagnostic_data_source_health",
            None,
        )
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
            read_diagnostic_data_source_health=(
                data_source_reader
                if callable(data_source_reader)
                else lambda: _unobserved_data_source_result(active_clock())
            ),
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
            read_persistence_health=application_health.read_persistence_health,
            read_version_health=application_health.read_version_health,
            source_kind=SourceKind.LIVE_RUNTIME,
            source_identity="diagnostics_application",
            clock=active_clock,
            freshness_threshold=freshness_threshold,
        )
        self._projection.set_generation(
            initial_connection.generation.value,
            fallback=(
                initial_connection.source_mode is EventBridgeSourceMode.FALLBACK
            ),
        )
        if initial_connection.phase is EventBridgeConnectionPhase.DISCONNECTED:
            self._projection.mark_disconnected(
                generation=initial_connection.generation.value
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
            worker_thread = self._worker_thread
            self._worker_thread = None
            self._dispose_batch_subscription = lambda: None
            self._dispose_connection_subscription = lambda: None
            self._pending_data_source_delivery = None
            freshness_timer = self._freshness_timer
            self._freshness_timer = None
            self._freshness_timer_sequence += 1
            self._worker_wake.set()
        if freshness_timer is not None:
            freshness_timer.cancel()
        dispose_batches()
        dispose_connection()
        self._projection.close()
        if worker_thread is not None and worker_thread is not current_thread():
            worker_thread.join(timeout=0)

    def _on_snapshot_batch(self, batch: EventBridgeBatch) -> None:
        relevant = tuple(
            snapshot
            for snapshot in batch.snapshots
            if str(snapshot.get("feature", "")).casefold()
            in {
                "system_health",
                "diagnostic_tasks",
                "scenario_lab",
                "evidence_and_findings",
            }
        )
        if not relevant:
            return
        data_source_revisions = tuple(
            revision
            for snapshot in relevant
            if _is_data_source_health_delivery(snapshot)
            if (revision := _source_revision(snapshot)) is not None
        )
        with self._lock:
            if (
                self._closed
                or batch.generation.value != self._connection_generation
            ):
                return
            if data_source_revisions:
                revision = max(data_source_revisions)
                if revision > self._highest_enqueued_revision:
                    self._highest_enqueued_revision = revision
                    pending = self._pending_data_source_delivery
                    if pending is None or revision > pending[1]:
                        self._pending_data_source_delivery = (
                            batch.generation.value,
                            revision,
                        )
            if any(
                not _is_data_source_health_delivery(snapshot)
                for snapshot in relevant
            ):
                self._pending_refresh_generation = batch.generation.value
            self._worker_wake.set()

    def _on_connection_state(self, state: EventBridgeConnectionState) -> None:
        with self._lock:
            if self._closed or state.sequence.value <= self._connection_sequence:
                return
            first_observation = self._connection_sequence == 0
            self._connection_sequence = state.sequence.value
            if state.generation.value != self._connection_generation:
                self._highest_enqueued_revision = 0
                self._pending_data_source_delivery = None
            self._connection_generation = state.generation.value
            self._pending_connection_actions.append(
                (
                    state.phase,
                    state.generation.value,
                    first_observation,
                    state.source_mode is EventBridgeSourceMode.FALLBACK,
                )
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
                data_source_delivery = self._pending_data_source_delivery
                self._pending_data_source_delivery = None
            for phase, generation, first_observation, fallback in connection_actions:
                try:
                    if phase is EventBridgeConnectionPhase.DISCONNECTED:
                        self._projection.mark_disconnected(generation=generation)
                    elif first_observation:
                        self._projection.set_generation(
                            generation,
                            fallback=fallback,
                        )
                    else:
                        self._projection.mark_reconnected_with_source_mode(
                            generation=generation,
                            fallback=fallback,
                        )
                except RuntimeError:
                    with self._lock:
                        if not self._closed:
                            raise
                    return
            if data_source_delivery is not None:
                generation, revision = data_source_delivery
                try:
                    self._projection.accept_data_source_revision(
                        revision,
                        generation=generation,
                    )
                    self._schedule_freshness_deadline()
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
        self._degraded = False
        self._fail_data_source_reread = False
        self._persistence_unavailable = False
        self._schema_incompatible = False
        self._manifest_incompatible = False
        self._queue_mode = "healthy" if initially_healthy else "unknown"
        self._cache_mode = "healthy" if initially_healthy else "unknown"
        self._queue_pending_count = 0
        self._queue_pending_since: datetime | None = None
        self._cache_last_refresh_at = self._now
        self._cache_generation = 1
        self._source_revision = 0
        self._projection = _SystemHealthProjection(
            read_runtime_health=self._read_runtime_health,
            read_diagnostic_data_source_health=(
                self._read_diagnostic_data_source_health
            ),
            read_diagnostic_queue_health=self._read_diagnostic_queue_health,
            read_diagnostic_cache_health=self._read_diagnostic_cache_health,
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
        self._queue_mode = "healthy"
        self._cache_mode = "healthy"
        self._cache_last_refresh_at = self._clock()
        self._cache_generation += 1
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
        self._projection.publish_sampling_tick()

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

    def _read_diagnostic_data_source_health(
        self,
    ) -> DiagnosticDataSourceApplicationResult:
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
                    explanation=(
                        "The deterministic Data Source Health read failed."
                    ),
                    retryable=True,
                ),
            )
        if not self._healthy:
            return _unobserved_data_source_result(observed_at)
        token = hashlib.sha256(
            b"deterministic-admitted-data-source"
        ).hexdigest()
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
                code=(
                    RuntimeHealthApplicationErrorCode.PERSISTENCE_SCHEMA_INCOMPATIBLE
                ),
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
            schema_head=(
                None
                if self._persistence_unavailable
                else DIAGNOSTIC_SCHEMA_REVISION
            ),
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
                explanation=(
                    "The current Reproduction Manifest format is incompatible."
                ),
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


def _is_data_source_health_delivery(snapshot: dict[str, object]) -> bool:
    return (
        str(snapshot.get("feature", "")).casefold() == "system_health"
        and str(snapshot.get("component", "")).casefold()
        == "diagnostic_data_source"
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


def _authoritative_result_key(
    runtime: RuntimeHealthApplicationResult,
    queue: DiagnosticQueueApplicationResult,
    cache: DiagnosticCacheApplicationResult,
    persistence: PersistenceHealthApplicationObservation,
    version: VersionHealthApplicationObservation,
) -> tuple[str, ...]:
    return (
        *_application_result_key(runtime),
        *_application_result_key(queue),
        *_application_result_key(cache),
        *_persistence_result_key(persistence),
        *_version_result_key(version),
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


def _persistence_result_key(
    result: PersistenceHealthApplicationObservation,
) -> tuple[str, ...]:
    return (
        result.availability.value,
        result.schema_compatibility.value,
        str(result.schema_head),
        result.supported_schema_head,
        result.reopen_verification.value,
        str(None if result.error is None else result.error.code.value),
    )


def _version_result_key(
    result: VersionHealthApplicationObservation,
) -> tuple[str, ...]:
    return (
        result.product_build,
        repr(result.feature_interfaces),
        str(result.dependency_lock_identity),
        result.release_manifest_compatibility.value,
        result.runner_version,
        result.schema_version,
        result.evidence_format_version,
        result.manifest_format_version,
        result.reproduction_manifest_compatibility.value,
        str(None if result.error is None else result.error.code.value),
    )


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
    data_source = state.diagnostic_data_source
    if data_source.last_reliable_observation is not None:
        advanced_data_source_age = data_source.age + elapsed
        if _age_bucket(advanced_data_source_age) != _age_bucket(data_source.age):
            return True
        if (
            data_source.freshness is Freshness.FRESH
            and advanced_data_source_age >= data_source.freshness_threshold
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
            error=(
                SystemHealthError(
                    code=SystemHealthErrorCode.DIAGNOSTIC_QUEUE_READ_FAILED,
                    explanation="The Diagnostic Queue consumer is unavailable.",
                    retryable=True,
                )
                if classification
                is DiagnosticQueueHealthClassification.UNAVAILABLE
                else None
            ),
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


def _unobserved_data_source_result(
    observed_at: datetime,
) -> DiagnosticDataSourceApplicationResult:
    return DiagnosticDataSourceApplicationResult(
        availability=(
            DiagnosticDataSourceApplicationAvailability.NO_ADMITTED_SOURCE
        ),
        observation=None,
        source_token=None,
        observed_at=_aware(observed_at),
        error=DiagnosticDataSourceApplicationError(
            code=DiagnosticDataSourceApplicationErrorCode.NO_ADMITTED_SOURCE,
            explanation="No admitted diagnostic data source is available.",
            retryable=True,
        ),
    )


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
            result.observation,
            revision=revision,
            generation=generation,
            observed_at=result.observed_at,
            fallback_active=fallback_active,
            recovery_phase=(
                DiagnosticDataSourceRecoveryPhase.RECOVERED
                if fallback_active
                else DiagnosticDataSourceRecoveryPhase.IDLE
            ),
            freshness_threshold=freshness_threshold,
        )
    return _unavailable_data_source_component(
        observed_at=result.observed_at,
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
    observation: DiagnosticDataSourceApplicationObservation,
    *,
    revision: int,
    generation: SourceGenerationId,
    observed_at: datetime,
    fallback_active: bool,
    recovery_phase: DiagnosticDataSourceRecoveryPhase,
    freshness_threshold: timedelta,
) -> DiagnosticDataSourceHealthComponent:
    age = max(observed_at - observation.observed_at, timedelta(0))
    stale = age >= freshness_threshold
    accepted = DiagnosticDataSourceObservation(
        identity=observation.identity,
        revision=DiagnosticDataSourceRevision(revision),
        generation=generation,
        observed_at=observation.observed_at,
    )
    return DiagnosticDataSourceHealthComponent(
        identity=(
            DiagnosticDataSourceComponentIdentity.ADMITTED_HISTORICAL_MARKET_DATA
        ),
        classification=(
            DiagnosticDataSourceHealthClassification.STALE
            if stale
            else DiagnosticDataSourceHealthClassification.DEGRADED
            if fallback_active
            else DiagnosticDataSourceHealthClassification.HEALTHY
        ),
        connection=DiagnosticDataSourceConnectionState.CONNECTED,
        fallback=(
            DiagnosticDataSourceFallbackState.ACTIVE
            if fallback_active
            else DiagnosticDataSourceFallbackState.PRIMARY
        ),
        accepted_revision=accepted.revision,
        accepted_generation=accepted.generation,
        observed_at=observed_at,
        freshness=Freshness.STALE if stale else Freshness.FRESH,
        age=age,
        freshness_threshold=freshness_threshold,
        last_reliable_observation=accepted,
        affected_scope=observation.affected_scope,
        recovery_phase=recovery_phase,
        explanation=(
            "Diagnostic data-source health is stale; showing the last reliable observation."
            if stale
            else "The admitted diagnostic data source recovered after an authoritative reread."
            if recovery_phase is DiagnosticDataSourceRecoveryPhase.RECOVERED
            else "The admitted diagnostic data source is serving a verified fallback."
            if fallback_active
            else "The admitted diagnostic data source is fresh."
        ),
        error=None,
    )


def _unavailable_data_source_component(
    *,
    observed_at: datetime,
    freshness_threshold: timedelta,
    connection: DiagnosticDataSourceConnectionState = (
        DiagnosticDataSourceConnectionState.UNAVAILABLE
    ),
    fallback: DiagnosticDataSourceFallbackState = (
        DiagnosticDataSourceFallbackState.UNAVAILABLE
    ),
    recovery_phase: DiagnosticDataSourceRecoveryPhase = (
        DiagnosticDataSourceRecoveryPhase.IDLE
    ),
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
            affected_scope=SystemHealthAffectedScope.DIAGNOSTIC_EVIDENCE,
            retryable=True,
            recovery_expectation=(
                SystemHealthRecoveryExpectation.INITIALIZATION_REQUIRED
            ),
        ),
    )


def _retained_data_source_component(
    previous: DiagnosticDataSourceHealthComponent | None,
    *,
    observed_at: datetime,
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
            "Diagnostic data-source health is stale; showing the last "
            "reliable observation."
            if stale
            else "Diagnostic data-source recovery is in progress; showing the "
            "last reliable observation."
            if recovering
            else "Diagnostic data-source health is degraded; showing the last "
            "reliable observation."
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
    return SystemHealthError(
        code=SystemHealthErrorCode.DATA_SOURCE_REREAD_FAILED,
        explanation="The authoritative diagnostic data-source reread failed safely.",
        affected_scope=SystemHealthAffectedScope.DIAGNOSTIC_EVIDENCE,
        retryable=True if result.error is None else result.error.retryable,
        recovery_expectation=SystemHealthRecoveryExpectation.AUTOMATIC_RETRY,
    )


def _with_data_source_aggregate(
    state: SystemHealthViewState,
) -> SystemHealthViewState:
    source = state.diagnostic_data_source
    aggregate = replace(
        state,
        freshness=_least_fresh(state.freshness, source.freshness),
        age=max(state.age, source.age),
    )
    if (
        source.classification is DiagnosticDataSourceHealthClassification.HEALTHY
        and source.connection is DiagnosticDataSourceConnectionState.CONNECTED
        and source.fallback is DiagnosticDataSourceFallbackState.PRIMARY
    ):
        return aggregate
    if (
        source.classification is DiagnosticDataSourceHealthClassification.UNAVAILABLE
        and source.last_reliable_observation is None
    ):
        source_presentation = SystemHealthPresentationState.UNAVAILABLE
        source_phase = ViewPhase.FAILED
    elif source.recovery_phase in {
        DiagnosticDataSourceRecoveryPhase.FALLBACK,
        DiagnosticDataSourceRecoveryPhase.RECONNECTING,
        DiagnosticDataSourceRecoveryPhase.REREADING,
    }:
        source_presentation = SystemHealthPresentationState.RECOVERING
        source_phase = ViewPhase.DEGRADED
    elif source.classification is DiagnosticDataSourceHealthClassification.STALE:
        source_presentation = SystemHealthPresentationState.STALE
        source_phase = ViewPhase.DEGRADED
    elif source.classification is DiagnosticDataSourceHealthClassification.RECOVERING:
        source_presentation = SystemHealthPresentationState.RECOVERING
        source_phase = ViewPhase.DEGRADED
    else:
        source_presentation = SystemHealthPresentationState.DEGRADED
        source_phase = ViewPhase.DEGRADED
    severity = (
        SystemHealthPresentationState.HEALTHY,
        SystemHealthPresentationState.RECOVERED,
        SystemHealthPresentationState.DEGRADED,
        SystemHealthPresentationState.RECOVERING,
        SystemHealthPresentationState.STALE,
        SystemHealthPresentationState.UNKNOWN,
        SystemHealthPresentationState.UNAVAILABLE,
        SystemHealthPresentationState.INCOMPATIBLE,
    )
    presentation = (
        source_presentation
        if severity.index(source_presentation) > severity.index(aggregate.presentation)
        else aggregate.presentation
    )
    return replace(
        aggregate,
        phase=(
            ViewPhase.FAILED
            if source_phase is ViewPhase.FAILED
            and aggregate.phase is not ViewPhase.FAILED
            else aggregate.phase
            if aggregate.phase is ViewPhase.FAILED
            else source_phase
        ),
        presentation=presentation,
        completeness=Completeness.PARTIAL,
    )


def _least_fresh(left: Freshness, right: Freshness) -> Freshness:
    values = (left, right)
    if Freshness.AWAITING_FIRST_STATE in values:
        return Freshness.AWAITING_FIRST_STATE
    if Freshness.DISCONNECTED in values:
        return Freshness.DISCONNECTED
    if Freshness.STALE in values:
        return Freshness.STALE
    return Freshness.FRESH

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
