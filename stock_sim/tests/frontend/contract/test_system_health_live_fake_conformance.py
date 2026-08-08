from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from threading import Event, Lock, Thread

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.event_bridge import EventBridge
from app.features import (
    ACTIVE_FEATURE_INTERFACES,
    DeterministicFakeSystemHealthAdapter,
    HealthCompatibilityState,
    LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter,
    LiveSystemHealthAdapter,
    RuntimeHealthClassification,
    RuntimeHealthApplicationAvailability,
    RuntimeHealthApplicationError,
    RuntimeHealthApplicationErrorCode,
    RuntimeHealthApplicationObservation,
    RuntimeHealthApplicationResult,
    RuntimeHealthRecoveryPhase,
    PersistenceAvailability,
    PersistenceHealthApplicationObservation,
    PersistenceReopenVerification,
    SystemHealthComponentIdentity,
    SourceRevisionToken,
    SystemHealthContext,
    SystemHealthFeature,
    SystemHealthPresentationState,
    VersionHealthApplicationObservation,
)
from app.features.run_monitoring import Completeness, Freshness, ViewPhase
from strategy_diagnostics import create_diagnostics_application
from strategy_diagnostics.diagnostic_evidence import DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION
from strategy_diagnostics.persistence import DIAGNOSTIC_SCHEMA_REVISION
from strategy_diagnostics.reproduction import REPRODUCTION_MANIFEST_SCHEMA_VERSION
from strategy_diagnostics.versioning import STRATEGY_DIAGNOSTICS_RUNNER_VERSION


@pytest.fixture(autouse=True)
def _controlled_release_binding(tmp_path, monkeypatch) -> None:
    lock_path = (
        Path(__file__).parents[3]
        / "stock_sim"
        / "release"
        / "frontend_v2_toolchain.lock.json"
    )
    release_manifest = tmp_path / "dependency-manifest.json"
    release_manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "toolchain_lock": json.loads(lock_path.read_text(encoding="utf-8")),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "STOCKSIM_FRONTEND_V2_RELEASE_MANIFEST_PATH",
        str(release_manifest),
    )


@dataclass
class _Clock:
    now: datetime = datetime(2030, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


@dataclass
class _Harness:
    feature: SystemHealthFeature
    become_healthy: Callable[[], None]
    publish_change: Callable[[], None]
    disconnect: Callable[[], None]
    reconnect: Callable[[], None]
    fail: Callable[[], None]
    advance: Callable[[timedelta], None]
    degrade: Callable[[], None]
    unavailable: Callable[[], None]
    schema_incompatible: Callable[[], None]
    manifest_incompatible: Callable[[], None]


def _compatible_persistence(now: datetime) -> PersistenceHealthApplicationObservation:
    return PersistenceHealthApplicationObservation(
        availability=PersistenceAvailability.AVAILABLE,
        schema_compatibility=HealthCompatibilityState.COMPATIBLE,
        schema_head=DIAGNOSTIC_SCHEMA_REVISION,
        supported_schema_head=DIAGNOSTIC_SCHEMA_REVISION,
        last_successful_durable_read_at=now,
        last_successful_durable_write_at=now,
        reopen_verification=PersistenceReopenVerification.VERIFIED,
        observed_at=now,
        error=None,
    )


def _compatible_version(now: datetime) -> VersionHealthApplicationObservation:
    return VersionHealthApplicationObservation(
        product_build="stock-sim/0.0.1",
        feature_interfaces=ACTIVE_FEATURE_INTERFACES,
        dependency_lock_identity="sha256:" + "0" * 64,
        release_manifest_compatibility=HealthCompatibilityState.COMPATIBLE,
        runner_version=STRATEGY_DIAGNOSTICS_RUNNER_VERSION,
        schema_version=DIAGNOSTIC_SCHEMA_REVISION,
        evidence_format_version=DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION,
        manifest_format_version=REPRODUCTION_MANIFEST_SCHEMA_VERSION,
        reproduction_manifest_compatibility=HealthCompatibilityState.COMPATIBLE,
        observed_at=now,
        error=None,
    )


def _healthy_runtime(now: datetime) -> RuntimeHealthApplicationResult:
    return RuntimeHealthApplicationResult(
        availability=RuntimeHealthApplicationAvailability.READY,
        observation=RuntimeHealthApplicationObservation(
            classification=RuntimeHealthClassification.HEALTHY,
            observed_at=now,
            explanation="Diagnostics runtime is ready.",
        ),
        source_token=SourceRevisionToken("a" * 64),
        observed_at=now,
        error=None,
    )


def _live_harness(*, initially_healthy: bool) -> _Harness:
    clock = _Clock()
    application = create_diagnostics_application()
    if initially_healthy:
        application.start()
        engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        application.initialize_persistence(engine)
        application = create_diagnostics_application()
        application.start()
        application.initialize_persistence(engine)
    bridge = EventBridge(subscribe_backend=False)
    application_health = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        application,
        clock=clock,
        current_manifest_format_provider=(
            lambda: REPRODUCTION_MANIFEST_SCHEMA_VERSION
        ),
    )
    failed = False
    degraded = False
    persistence_unavailable = False
    persistence_schema_incompatible = False
    reproduction_manifest_incompatible = False

    def read_runtime_health() -> RuntimeHealthApplicationResult:
        if not failed:
            return application_health.read_runtime_health()
        return RuntimeHealthApplicationResult(
            availability=RuntimeHealthApplicationAvailability.FAILED,
            observation=None,
            source_token=None,
            observed_at=clock(),
            error=RuntimeHealthApplicationError(
                code=RuntimeHealthApplicationErrorCode.READ_FAILED,
                explanation=(
                    r"C:\secrets\runtime.exe --token super-secret SELECT users"
                ),
                retryable=True,
            ),
        )

    class _ControllableHealth:
        interface_version = application_health.interface_version

        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            result = read_runtime_health()
            if (
                degraded
                and result.observation is not None
                and result.availability is RuntimeHealthApplicationAvailability.READY
            ):
                return replace(
                    result,
                    observation=replace(
                        result.observation,
                        classification=RuntimeHealthClassification.DEGRADED,
                        explanation="Diagnostics runtime is degraded.",
                    ),
                )
            return result

        def read_persistence_health(self):
            result = application_health.read_persistence_health()
            if persistence_unavailable:
                return replace(
                    result,
                    availability=PersistenceAvailability.UNAVAILABLE,
                    schema_compatibility=HealthCompatibilityState.UNKNOWN,
                    last_successful_durable_read_at=None,
                    last_successful_durable_write_at=None,
                    reopen_verification=PersistenceReopenVerification.FAILED,
                    error=RuntimeHealthApplicationError(
                        code=(
                            RuntimeHealthApplicationErrorCode.PERSISTENCE_READ_FAILED
                        ),
                        explanation="Diagnostic Persistence is unavailable.",
                        retryable=True,
                        correlation_identity=r"C:\private\diagnostics.sqlite",
                    ),
                )
            if persistence_schema_incompatible:
                return replace(
                    result,
                    schema_compatibility=HealthCompatibilityState.INCOMPATIBLE,
                    reopen_verification=PersistenceReopenVerification.FAILED,
                    error=RuntimeHealthApplicationError(
                        code=(
                            RuntimeHealthApplicationErrorCode.PERSISTENCE_SCHEMA_INCOMPATIBLE
                        ),
                        explanation="Diagnostic Persistence schema is incompatible.",
                        retryable=False,
                    ),
                )
            return result

        def read_version_health(self):
            result = application_health.read_version_health()
            if reproduction_manifest_incompatible:
                return replace(
                    result,
                    reproduction_manifest_compatibility=(
                        HealthCompatibilityState.INCOMPATIBLE
                    ),
                    error=RuntimeHealthApplicationError(
                        code=RuntimeHealthApplicationErrorCode.MANIFEST_INCOMPATIBLE,
                        explanation=(
                            "The current Reproduction Manifest format is incompatible."
                        ),
                        retryable=False,
                    ),
                )
            return result

    feature = LiveSystemHealthAdapter(
        application_health=_ControllableHealth(),
        event_bridge=bridge,
        clock=clock,
        freshness_threshold=timedelta(seconds=5),
    )

    def become_healthy() -> None:
        application.start()
        bridge.on_snapshot({"feature": "system_health"})
        bridge.flush(force=True)

    def publish_change() -> None:
        bridge.on_snapshot({"feature": "system_health"})
        bridge.flush(force=True)

    def fail() -> None:
        nonlocal failed
        failed = True
        publish_change()

    def degrade() -> None:
        nonlocal degraded, persistence_unavailable
        nonlocal persistence_schema_incompatible, reproduction_manifest_incompatible
        degraded = True
        persistence_unavailable = False
        persistence_schema_incompatible = False
        reproduction_manifest_incompatible = False
        publish_change()

    def unavailable() -> None:
        nonlocal degraded, persistence_unavailable
        nonlocal persistence_schema_incompatible, reproduction_manifest_incompatible
        degraded = False
        persistence_unavailable = True
        persistence_schema_incompatible = False
        reproduction_manifest_incompatible = False
        publish_change()

    def schema_incompatible() -> None:
        nonlocal degraded, persistence_unavailable
        nonlocal persistence_schema_incompatible, reproduction_manifest_incompatible
        degraded = False
        persistence_unavailable = False
        persistence_schema_incompatible = True
        reproduction_manifest_incompatible = False
        publish_change()

    def manifest_incompatible() -> None:
        nonlocal degraded, persistence_unavailable
        nonlocal persistence_schema_incompatible, reproduction_manifest_incompatible
        degraded = False
        persistence_unavailable = False
        persistence_schema_incompatible = False
        reproduction_manifest_incompatible = True
        publish_change()

    return _Harness(
        feature=feature,
        become_healthy=become_healthy,
        publish_change=publish_change,
        disconnect=lambda: bridge.mark_disconnected(),
        reconnect=lambda: bridge.mark_reconnected(),
        fail=fail,
        advance=clock.advance,
        degrade=degrade,
        unavailable=unavailable,
        schema_incompatible=schema_incompatible,
        manifest_incompatible=manifest_incompatible,
    )


def _fake_harness(*, initially_healthy: bool) -> _Harness:
    feature = DeterministicFakeSystemHealthAdapter(
        initially_healthy=initially_healthy,
        freshness_threshold=timedelta(seconds=5),
    )
    return _Harness(
        feature=feature,
        become_healthy=feature.advance_to_healthy,
        publish_change=feature.publish_authoritative_observation,
        disconnect=feature.advance_to_disconnected,
        reconnect=feature.advance_to_reconnected,
        fail=feature.advance_to_failed,
        advance=feature.advance_clock,
        degrade=feature.advance_to_degraded,
        unavailable=feature.advance_to_unavailable,
        schema_incompatible=feature.advance_to_schema_incompatible,
        manifest_incompatible=feature.advance_to_manifest_incompatible,
    )


@pytest.fixture(params=(_live_harness, _fake_harness), ids=("live", "fake"))
def harness_factory(request: pytest.FixtureRequest) -> Callable[..., _Harness]:
    return request.param


def test_live_and_fake_share_the_initial_authoritative_health_contract(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(initially_healthy=True)
    try:
        state = harness.feature.snapshot(SystemHealthContext())

        assert state.presentation is SystemHealthPresentationState.HEALTHY
        assert state.phase is ViewPhase.READY
        assert state.freshness is Freshness.FRESH
        assert state.completeness is Completeness.COMPLETE
        assert state.last_reliable_payload is state.components
        assert state.components[0].classification is (
            RuntimeHealthClassification.HEALTHY
        )
        with pytest.raises(FrozenInstanceError):
            state.revision = 99  # type: ignore[misc]
    finally:
        harness.feature.close()


def test_live_and_fake_share_persistence_and_version_compatibility_contract(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(initially_healthy=True)
    try:
        compatible = harness.feature.snapshot(SystemHealthContext())
        assert tuple(item.identity for item in compatible.components) == (
            SystemHealthComponentIdentity.APPLICATION_RUNTIME,
            SystemHealthComponentIdentity.DIAGNOSTIC_PERSISTENCE,
            SystemHealthComponentIdentity.VERSION_COMPATIBILITY,
        )
        persistence = compatible.components[1]
        version = compatible.components[2]
        assert persistence.availability is PersistenceAvailability.AVAILABLE
        assert persistence.reopen_verification is (
            PersistenceReopenVerification.VERIFIED
        )
        assert version.reproduction_manifest_compatibility is (
            HealthCompatibilityState.COMPATIBLE
        )
        assert version.feature_interfaces == ACTIVE_FEATURE_INTERFACES
        assert version.dependency_lock_identity.startswith("sha256:")
        assert version.release_manifest_compatibility is (
            HealthCompatibilityState.COMPATIBLE
        )

        harness.schema_incompatible()
        schema_incompatible = harness.feature.snapshot(SystemHealthContext())
        assert schema_incompatible.presentation is (
            SystemHealthPresentationState.INCOMPATIBLE
        )
        assert schema_incompatible.components[1].schema_compatibility is (
            HealthCompatibilityState.INCOMPATIBLE
        )

        harness.manifest_incompatible()
        manifest_incompatible = harness.feature.snapshot(SystemHealthContext())
        assert manifest_incompatible.presentation is (
            SystemHealthPresentationState.INCOMPATIBLE
        )
        assert manifest_incompatible.components[2].reproduction_manifest_compatibility is (
            HealthCompatibilityState.INCOMPATIBLE
        )
        assert manifest_incompatible.components[1].schema_compatibility is (
            HealthCompatibilityState.COMPATIBLE
        )
        assert manifest_incompatible.error is not None
        assert manifest_incompatible.error.code.value == (
            "reproduction_manifest_incompatible"
        )
        assert manifest_incompatible.error.affected_scope.value == (
            "reproduction_manifest"
        )
    finally:
        harness.feature.close()


def test_unknown_is_never_presented_as_healthy(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(initially_healthy=False)
    try:
        state = harness.feature.snapshot(SystemHealthContext())

        assert state.presentation is SystemHealthPresentationState.UNKNOWN
        assert len(state.components) == 3
        assert state.components[0].classification is (
            RuntimeHealthClassification.UNKNOWN
        )
        assert state.components[1].availability is PersistenceAvailability.UNKNOWN
        assert state.last_reliable_payload is not None
        assert tuple(
            component.identity for component in state.last_reliable_payload
        ) == (SystemHealthComponentIdentity.VERSION_COMPATIBILITY,)
        assert state.completeness is Completeness.UNKNOWN
        assert state.error is not None
    finally:
        harness.feature.close()


def test_live_and_fake_share_degraded_and_unavailable_states(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(initially_healthy=True)
    try:
        harness.feature.snapshot(SystemHealthContext())
        harness.degrade()
        degraded = harness.feature.snapshot(SystemHealthContext())
        assert degraded.presentation is SystemHealthPresentationState.DEGRADED
        assert degraded.components[0].classification is (
            RuntimeHealthClassification.DEGRADED
        )
        durable_read = degraded.components[1].last_successful_durable_read_at
        durable_write = degraded.components[1].last_successful_durable_write_at

        harness.unavailable()
        unavailable = harness.feature.snapshot(SystemHealthContext())
        assert unavailable.presentation is SystemHealthPresentationState.UNAVAILABLE
        assert unavailable.components[1].availability is (
            PersistenceAvailability.UNAVAILABLE
        )
        assert unavailable.components[1].last_successful_durable_read_at == durable_read
        assert unavailable.components[1].last_successful_durable_write_at == durable_write
        assert unavailable.error is not None
        assert unavailable.error.correlation_identity is None
    finally:
        harness.feature.close()


def test_runtime_failure_does_not_hide_valid_persistence_and_version_slices() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)

    class _IndependentSlices:
        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            return RuntimeHealthApplicationResult(
                availability=RuntimeHealthApplicationAvailability.FAILED,
                observation=None,
                source_token=None,
                observed_at=now,
                error=RuntimeHealthApplicationError(
                    code=RuntimeHealthApplicationErrorCode.READ_FAILED,
                    explanation="The authoritative Runtime Health read failed safely.",
                    retryable=True,
                ),
            )

        def read_persistence_health(self) -> PersistenceHealthApplicationObservation:
            return _compatible_persistence(now)

        def read_version_health(self) -> VersionHealthApplicationObservation:
            return _compatible_version(now)

    feature = LiveSystemHealthAdapter(
        application_health=_IndependentSlices(),  # type: ignore[arg-type]
        event_bridge=EventBridge(subscribe_backend=False),
        clock=lambda: now,
    )
    try:
        state = feature.snapshot(SystemHealthContext())

        assert state.presentation is SystemHealthPresentationState.UNAVAILABLE
        assert len(state.components) == 3
        assert state.components[0].classification is (
            RuntimeHealthClassification.UNAVAILABLE
        )
        assert state.components[1].availability is PersistenceAvailability.AVAILABLE
        assert state.components[2].reproduction_manifest_compatibility is (
            HealthCompatibilityState.COMPATIBLE
        )
    finally:
        feature.close()


def test_runtime_failure_still_refreshes_reliable_independent_slices() -> None:
    clock = _Clock()

    class _MutableSlices:
        runtime_failed = False
        persistence_unavailable = False

        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            if not self.runtime_failed:
                return _healthy_runtime(clock())
            return RuntimeHealthApplicationResult(
                availability=RuntimeHealthApplicationAvailability.FAILED,
                observation=None,
                source_token=None,
                observed_at=clock(),
                error=RuntimeHealthApplicationError(
                    code=RuntimeHealthApplicationErrorCode.READ_FAILED,
                    explanation="The authoritative Runtime Health read failed safely.",
                    retryable=True,
                ),
            )

        def read_persistence_health(self) -> PersistenceHealthApplicationObservation:
            if not self.persistence_unavailable:
                return _compatible_persistence(clock())
            return replace(
                _compatible_persistence(clock()),
                availability=PersistenceAvailability.UNAVAILABLE,
                schema_compatibility=HealthCompatibilityState.UNKNOWN,
                last_successful_durable_read_at=None,
                last_successful_durable_write_at=None,
                reopen_verification=PersistenceReopenVerification.FAILED,
                error=RuntimeHealthApplicationError(
                    code=RuntimeHealthApplicationErrorCode.PERSISTENCE_READ_FAILED,
                    explanation="Diagnostic Persistence is unavailable.",
                    retryable=True,
                ),
            )

        def read_version_health(self) -> VersionHealthApplicationObservation:
            return _compatible_version(clock())

    source = _MutableSlices()
    feature = LiveSystemHealthAdapter(
        application_health=source,  # type: ignore[arg-type]
        event_bridge=EventBridge(subscribe_backend=False),
        clock=clock,
    )
    try:
        initial = feature.snapshot(SystemHealthContext())
        clock.advance(timedelta(seconds=2))
        source.runtime_failed = True
        refreshed = feature.snapshot(SystemHealthContext())
        reliable = refreshed.last_reliable_payload

        assert reliable is not None
        persistence = next(
            item
            for item in reliable
            if item.identity
            is SystemHealthComponentIdentity.DIAGNOSTIC_PERSISTENCE
        )
        assert persistence.last_successful_durable_read_at == clock()
        assert refreshed.last_reliable_at == initial.components[0].observed_at
        assert refreshed.age == timedelta(seconds=2)

        latest_durable_read = persistence.last_successful_durable_read_at
        clock.advance(timedelta(seconds=2))
        source.persistence_unavailable = True
        unavailable = feature.snapshot(SystemHealthContext())

        assert unavailable.components[1].last_successful_durable_read_at == (
            latest_durable_read
        )
    finally:
        feature.close()


def test_snapshot_aging_updates_persistence_component_before_and_after_threshold(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(initially_healthy=True)
    try:
        initial = harness.feature.snapshot(SystemHealthContext())
        harness.disconnect()
        harness.advance(timedelta(seconds=2))
        fresh = harness.feature.snapshot(SystemHealthContext())

        assert fresh.last_reliable_at == initial.last_reliable_at
        assert fresh.age == timedelta(seconds=2)
        assert fresh.components[1].age == timedelta(seconds=2)
        assert fresh.components[1].freshness is Freshness.FRESH

        harness.advance(timedelta(seconds=4))
        stale = harness.feature.snapshot(SystemHealthContext())

        assert stale.age == timedelta(seconds=6)
        assert stale.components[1].age == timedelta(seconds=6)
        assert stale.components[1].freshness is Freshness.STALE
        assert stale.presentation is SystemHealthPresentationState.STALE
    finally:
        harness.feature.close()


def test_failed_reconnect_marks_the_failed_component_not_recovered() -> None:
    clock = _Clock()
    bridge = EventBridge(subscribe_backend=False)

    class _ReconnectSource:
        persistence_unavailable = False

        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            return _healthy_runtime(clock())

        def read_persistence_health(self) -> PersistenceHealthApplicationObservation:
            if not self.persistence_unavailable:
                return _compatible_persistence(clock())
            return replace(
                _compatible_persistence(clock()),
                availability=PersistenceAvailability.UNAVAILABLE,
                schema_compatibility=HealthCompatibilityState.UNKNOWN,
                last_successful_durable_read_at=None,
                last_successful_durable_write_at=None,
                reopen_verification=PersistenceReopenVerification.FAILED,
                error=RuntimeHealthApplicationError(
                    code=RuntimeHealthApplicationErrorCode.PERSISTENCE_READ_FAILED,
                    explanation="Diagnostic Persistence is unavailable.",
                    retryable=True,
                ),
            )

        def read_version_health(self) -> VersionHealthApplicationObservation:
            return _compatible_version(clock())

    source = _ReconnectSource()
    feature = LiveSystemHealthAdapter(
        application_health=source,  # type: ignore[arg-type]
        event_bridge=bridge,
        clock=clock,
    )
    observed = []
    subscription = feature.subscribe(SystemHealthContext(), observed.append)
    try:
        source.persistence_unavailable = True
        bridge.mark_disconnected()
        bridge.mark_reconnected()
        failed = observed[-1]

        assert failed.recovery_phase is RuntimeHealthRecoveryPhase.FAILED
        assert failed.components[1].availability is (
            PersistenceAvailability.UNAVAILABLE
        )
        assert failed.components[1].recovery_phase is (
            RuntimeHealthRecoveryPhase.FAILED
        )
        assert failed.components[2].recovery_phase is (
            RuntimeHealthRecoveryPhase.RECOVERED
        )
    finally:
        subscription.dispose()
        feature.close()


def test_overall_error_matches_the_component_driving_incompatible_presentation() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)

    class _ConflictingSeveritySource:
        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            return _healthy_runtime(now)

        def read_persistence_health(self) -> PersistenceHealthApplicationObservation:
            return replace(
                _compatible_persistence(now),
                availability=PersistenceAvailability.UNAVAILABLE,
                schema_compatibility=HealthCompatibilityState.UNKNOWN,
                last_successful_durable_read_at=None,
                last_successful_durable_write_at=None,
                reopen_verification=PersistenceReopenVerification.FAILED,
                error=RuntimeHealthApplicationError(
                    code=RuntimeHealthApplicationErrorCode.PERSISTENCE_READ_FAILED,
                    explanation="Diagnostic Persistence is unavailable.",
                    retryable=True,
                ),
            )

        def read_version_health(self) -> VersionHealthApplicationObservation:
            return replace(
                _compatible_version(now),
                reproduction_manifest_compatibility=(
                    HealthCompatibilityState.INCOMPATIBLE
                ),
                error=RuntimeHealthApplicationError(
                    code=RuntimeHealthApplicationErrorCode.MANIFEST_INCOMPATIBLE,
                    explanation=(
                        "The current Reproduction Manifest format is incompatible."
                    ),
                    retryable=False,
                ),
            )

    feature = LiveSystemHealthAdapter(
        application_health=_ConflictingSeveritySource(),  # type: ignore[arg-type]
        event_bridge=EventBridge(subscribe_backend=False),
        clock=lambda: now,
    )
    try:
        state = feature.snapshot(SystemHealthContext())

        assert state.presentation is SystemHealthPresentationState.INCOMPATIBLE
        assert state.error is not None
        assert state.error.code.value == "reproduction_manifest_incompatible"
        assert state.error.affected_scope.value == "reproduction_manifest"
    finally:
        feature.close()


def test_raw_filename_correlation_is_removed_before_the_feature_seam() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)

    class _UnsafeCorrelationSource:
        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            return RuntimeHealthApplicationResult(
                availability=RuntimeHealthApplicationAvailability.FAILED,
                observation=None,
                source_token=None,
                observed_at=now,
                error=RuntimeHealthApplicationError(
                    code=RuntimeHealthApplicationErrorCode.READ_FAILED,
                    explanation="The authoritative Runtime Health read failed safely.",
                    retryable=True,
                    correlation_identity="diagnostics.sqlite3",
                ),
            )

        def read_persistence_health(self) -> PersistenceHealthApplicationObservation:
            return _compatible_persistence(now)

        def read_version_health(self) -> VersionHealthApplicationObservation:
            return _compatible_version(now)

    feature = LiveSystemHealthAdapter(
        application_health=_UnsafeCorrelationSource(),  # type: ignore[arg-type]
        event_bridge=EventBridge(subscribe_backend=False),
        clock=lambda: now,
    )
    try:
        state = feature.snapshot(SystemHealthContext())

        assert state.error is not None
        assert state.error.correlation_identity is None
        assert "diagnostics.sqlite3" not in repr(state).casefold()
    finally:
        feature.close()


def test_connected_snapshot_rereads_the_real_diagnostics_application() -> None:
    clock = _Clock()
    application = create_diagnostics_application()
    feature = LiveSystemHealthAdapter(
        application_health=(
            LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
                application,
                clock=clock,
                current_manifest_format_provider=(
                    lambda: REPRODUCTION_MANIFEST_SCHEMA_VERSION
                ),
            )
        ),
        event_bridge=EventBridge(subscribe_backend=False),
        clock=clock,
    )
    try:
        unavailable = feature.snapshot(SystemHealthContext())
        application.start()
        engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        application.initialize_persistence(engine)
        healthy = feature.snapshot(SystemHealthContext())

        assert unavailable.presentation is SystemHealthPresentationState.UNKNOWN
        assert healthy.presentation is SystemHealthPresentationState.DEGRADED
        assert healthy.components[1].reopen_verification is (
            PersistenceReopenVerification.NOT_YET_VERIFIED
        )
        assert healthy.revision > unavailable.revision
        assert healthy.last_reliable_payload is not None
    finally:
        feature.close()


def test_disconnect_staleness_and_reconnect_retain_last_reliable_state(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(initially_healthy=True)
    observed: list = []
    subscription = harness.feature.subscribe(SystemHealthContext(), observed.append)
    try:
        reliable = observed[-1].last_reliable_payload
        harness.disconnect()
        degraded = observed[-1]
        assert degraded.presentation is SystemHealthPresentationState.DEGRADED
        assert degraded.recovery_phase is RuntimeHealthRecoveryPhase.DISCONNECTED
        assert degraded.last_reliable_payload == reliable

        harness.advance(timedelta(seconds=6))
        stale = harness.feature.snapshot(SystemHealthContext())
        assert stale.presentation is SystemHealthPresentationState.STALE
        assert stale.freshness is Freshness.STALE
        assert stale.last_reliable_payload == reliable

        harness.reconnect()
        recovered = observed[-1]
        assert any(
            state.recovery_phase is RuntimeHealthRecoveryPhase.REREADING
            and state.presentation is SystemHealthPresentationState.RECOVERING
            for state in observed
        )
        assert recovered.recovery_phase is RuntimeHealthRecoveryPhase.RECOVERED
        assert recovered.presentation is SystemHealthPresentationState.RECOVERED
        assert recovered.last_reliable_payload is not None
        assert [state.revision for state in observed] == sorted(
            {state.revision for state in observed}
        )
    finally:
        subscription.dispose()
        harness.feature.close()


def test_subscription_dispose_and_adapter_close_are_idempotent_and_terminal(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(initially_healthy=True)
    observed: list = []
    subscription = harness.feature.subscribe(SystemHealthContext(), observed.append)
    delivered = len(observed)

    subscription.dispose()
    subscription.dispose()
    harness.publish_change()
    assert len(observed) == delivered

    harness.feature.close()
    harness.feature.close()
    harness.publish_change()
    assert len(observed) == delivered


def test_read_failure_retains_safe_degraded_then_stale_last_reliable_state(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(initially_healthy=True)
    observed: list = []
    subscription = harness.feature.subscribe(SystemHealthContext(), observed.append)
    try:
        reliable = observed[-1].last_reliable_payload
        harness.fail()
        failed = observed[-1]

        assert failed.presentation is SystemHealthPresentationState.DEGRADED
        assert reliable is not None
        assert failed.last_reliable_payload is not None
        assert failed.last_reliable_payload[0] == reliable[0]
        assert failed.last_reliable_payload[1:] == failed.components[1:]
        assert failed.error is not None
        exposed = failed.error.explanation.casefold()
        for forbidden in ("c:\\", "runtime.exe", "token", "secret", "select"):
            assert forbidden not in exposed
        serialized = repr(failed).casefold()
        for forbidden in (
            "c:\\secrets",
            "runtime.exe",
            "super-secret",
            "select users",
            "traceback",
        ):
            assert forbidden not in serialized

        harness.advance(timedelta(seconds=6))
        stale = harness.feature.snapshot(SystemHealthContext())
        assert stale.presentation is SystemHealthPresentationState.STALE
        assert stale.last_reliable_payload is not None
        assert failed.last_reliable_payload is not None
        assert stale.last_reliable_payload[0] == failed.last_reliable_payload[0]
        assert stale.last_reliable_payload[1:] == stale.components[1:]
    finally:
        subscription.dispose()
        harness.feature.close()


def test_live_adapter_rejects_batches_from_an_old_connection_generation() -> None:
    clock = _Clock()
    application = create_diagnostics_application()
    application.start()
    bridge = EventBridge(subscribe_backend=False)
    feature = LiveSystemHealthAdapter(
        application_health=(
            LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
                application,
                clock=clock,
            )
        ),
        event_bridge=bridge,
        clock=clock,
    )
    observed: list = []
    subscription = feature.subscribe(SystemHealthContext(), observed.append)
    try:
        bridge.mark_disconnected()
        bridge.mark_reconnected()
        delivered = tuple(state.revision for state in observed)

        bridge.on_snapshot({"feature": "run_monitoring"})
        bridge.flush(force=True)

        assert tuple(state.revision for state in observed) == delivered

        bridge.on_snapshot(
            {"feature": "system_health", "sequence": "old"},
            generation=1,
        )
        bridge.flush(force=True)

        assert tuple(state.revision for state in observed) == delivered
        assert observed[-1].source.generation.value == 2
    finally:
        subscription.dispose()
        feature.close()


def test_live_adapter_replays_a_disconnect_during_construction() -> None:
    class _DisconnectingBridge(EventBridge):
        replay_requested = False

        def subscribe_connection_state(
            self,
            observer,
            *,
            replay_current: bool = False,
        ):
            self.replay_requested = replay_current
            self.mark_disconnected()
            return super().subscribe_connection_state(
                observer,
                replay_current=replay_current,
            )

    clock = _Clock()
    application = create_diagnostics_application()
    application.start()
    bridge = _DisconnectingBridge(subscribe_backend=False)
    feature = LiveSystemHealthAdapter(
        application_health=(
            LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
                application,
                clock=clock,
            )
        ),
        event_bridge=bridge,
        clock=clock,
    )
    try:
        state = feature.snapshot(SystemHealthContext())

        assert bridge.replay_requested is True
        assert state.recovery_phase is RuntimeHealthRecoveryPhase.DISCONNECTED
        assert state.freshness is Freshness.DISCONNECTED
        assert state.presentation is SystemHealthPresentationState.UNAVAILABLE
    finally:
        feature.close()


def test_concurrent_healthy_then_failed_reads_preserve_last_reliable_state() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    first_read_entered = Event()
    release_first_read = Event()
    read_lock = Lock()
    read_calls = 0
    healthy_result = RuntimeHealthApplicationResult(
        availability=RuntimeHealthApplicationAvailability.READY,
        observation=RuntimeHealthApplicationObservation(
            classification=RuntimeHealthClassification.HEALTHY,
            observed_at=now,
            explanation="The application runtime is available.",
        ),
        source_token=SourceRevisionToken("0" * 64),
        observed_at=now,
        error=None,
    )
    failed_result = RuntimeHealthApplicationResult(
        availability=RuntimeHealthApplicationAvailability.FAILED,
        observation=None,
        source_token=None,
        observed_at=now,
        error=RuntimeHealthApplicationError(
            code=RuntimeHealthApplicationErrorCode.READ_FAILED,
            explanation="The authoritative Runtime Health read failed safely.",
            retryable=True,
        ),
    )

    class _ApplicationHealth:
        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            nonlocal read_calls
            with read_lock:
                read_calls += 1
                call = read_calls
            if call == 1:
                first_read_entered.set()
                release_first_read.wait(timeout=5)
                return healthy_result
            return failed_result

        def read_persistence_health(self) -> PersistenceHealthApplicationObservation:
            return _compatible_persistence(now)

        def read_version_health(self) -> VersionHealthApplicationObservation:
            return _compatible_version(now)

    feature = LiveSystemHealthAdapter(
        application_health=_ApplicationHealth(),  # type: ignore[arg-type]
        event_bridge=EventBridge(subscribe_backend=False),
        clock=lambda: now,
    )
    states = []
    errors: list[BaseException] = []

    def take_snapshot() -> None:
        try:
            states.append(feature.snapshot(SystemHealthContext()))
        except BaseException as error:  # noqa: BLE001 - preserve thread failure
            errors.append(error)

    first = Thread(target=take_snapshot)
    second = Thread(target=take_snapshot)
    second_started = False
    try:
        first.start()
        assert first_read_entered.wait(timeout=5)
        second.start()
        second_started = True
        release_first_read.set()
        first.join(timeout=5)
        second.join(timeout=5)
        assert not first.is_alive()
        assert not second.is_alive()
        assert errors == []

        stored = feature.snapshot(SystemHealthContext())
        assert len(states) == 2
        assert states[0].presentation is SystemHealthPresentationState.HEALTHY
        assert states[1].presentation is SystemHealthPresentationState.DEGRADED
        assert states[1].last_reliable_payload is not None
        assert states[1].last_reliable_payload[0] == states[0].components[0]
        assert states[1].last_reliable_payload[1:] == states[1].components[1:]
        assert [state.revision for state in states] == [1, 2]
        assert stored.revision == 3
        assert stored.last_reliable_payload is not None
        assert stored.last_reliable_payload[0] == states[0].components[0]
        assert stored.last_reliable_payload[1:] == stored.components[1:]
    finally:
        release_first_read.set()
        first.join(timeout=5)
        if second_started:
            second.join(timeout=5)
        feature.close()


def test_disconnect_waits_for_an_inflight_read_and_remains_degraded() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    second_read_entered = Event()
    release_second_read = Event()
    disconnect_attempted = Event()
    read_lock = Lock()
    read_calls = 0
    healthy_result = RuntimeHealthApplicationResult(
        availability=RuntimeHealthApplicationAvailability.READY,
        observation=RuntimeHealthApplicationObservation(
            classification=RuntimeHealthClassification.HEALTHY,
            observed_at=now,
            explanation="The application runtime is available.",
        ),
        source_token=SourceRevisionToken("1" * 64),
        observed_at=now,
        error=None,
    )

    class _SlowApplicationHealth:
        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            nonlocal read_calls
            with read_lock:
                read_calls += 1
                call = read_calls
            if call == 2:
                second_read_entered.set()
                release_second_read.wait(timeout=5)
            return healthy_result

        def read_persistence_health(self) -> PersistenceHealthApplicationObservation:
            return _compatible_persistence(now)

        def read_version_health(self) -> VersionHealthApplicationObservation:
            return _compatible_version(now)

    bridge = EventBridge(subscribe_backend=False)
    feature = LiveSystemHealthAdapter(
        application_health=_SlowApplicationHealth(),  # type: ignore[arg-type]
        event_bridge=bridge,
        clock=lambda: now,
    )
    feature.snapshot(SystemHealthContext())
    reread_states = []
    errors: list[BaseException] = []

    def reread() -> None:
        try:
            reread_states.append(feature.snapshot(SystemHealthContext()))
        except BaseException as error:  # noqa: BLE001 - preserve thread failure
            errors.append(error)

    def disconnect() -> None:
        disconnect_attempted.set()
        bridge.mark_disconnected()

    reread_thread = Thread(target=reread)
    disconnect_thread = Thread(target=disconnect)
    disconnect_started = False
    try:
        reread_thread.start()
        assert second_read_entered.wait(timeout=5)
        disconnect_thread.start()
        disconnect_started = True
        assert disconnect_attempted.wait(timeout=5)
        release_second_read.set()
        reread_thread.join(timeout=5)
        disconnect_thread.join(timeout=5)
        assert not reread_thread.is_alive()
        assert not disconnect_thread.is_alive()
        assert errors == []

        disconnected = feature.snapshot(SystemHealthContext())
        assert reread_states[0].presentation is (
            SystemHealthPresentationState.HEALTHY
        )
        assert disconnected.presentation is (
            SystemHealthPresentationState.DEGRADED
        )
        assert disconnected.recovery_phase is (
            RuntimeHealthRecoveryPhase.DISCONNECTED
        )
        assert disconnected.last_reliable_payload is not None
        assert disconnected.revision > reread_states[0].revision
    finally:
        release_second_read.set()
        reread_thread.join(timeout=5)
        if disconnect_started:
            disconnect_thread.join(timeout=5)
        feature.close()
