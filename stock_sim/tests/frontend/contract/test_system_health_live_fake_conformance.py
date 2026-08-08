from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from threading import Event, Lock, Thread, current_thread
from time import monotonic

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.event_bridge import EventBridge
from app.features import (
    ACTIVE_FEATURE_INTERFACES,
    DiagnosticCacheCompatibility,
    DiagnosticCacheApplicationAvailability,
    DiagnosticCacheApplicationObservation,
    DiagnosticCacheApplicationResult,
    DiagnosticCacheFallbackState,
    DiagnosticCacheHealthClassification,
    DiagnosticCacheLastRefreshResult,
    DiagnosticCacheRecoveryPhase,
    DiagnosticCacheScope,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    DiagnosticQueueBlockageReason,
    DiagnosticQueueApplicationAvailability,
    DiagnosticQueueApplicationObservation,
    DiagnosticQueueApplicationResult,
    DiagnosticQueueConsumerAvailability,
    DiagnosticQueueHealthClassification,
    DiagnosticQueueScope,
    DiagnosticTaskTarget,
    DeterministicFakeSystemHealthAdapter,
    HealthCompatibilityState,
    LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter,
    LiveSystemHealthAdapter,
    PauseDiagnosticTarget,
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
    StartFormalDiagnosticCampaign,
    VersionHealthApplicationObservation,
)
from app.features.run_monitoring import Completeness, Freshness, ViewPhase
from strategy_diagnostics import create_diagnostics_application
from tests.frontend.contract.test_diagnostic_task_campaign_start_live_contract import (
    _approved_formal_task,
    _formal_live_stack,
)
from tests.frontend.contract.test_diagnostic_task_revision_approval_live_contract import (
    _read_task,
)
from tests.frontend.system_health_support import ApplicationDrivenCacheStore
from tests.strategy_diagnostics.test_recipe_lifecycle import (
    _baseline_payload,
    _RecipeFixtureSource,
)
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


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 2.0) -> None:
    deadline = monotonic() + timeout
    wake = Event()
    while not predicate():
        remaining = deadline - monotonic()
        assert remaining > 0
        wake.wait(min(remaining, 0.01))


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


@dataclass
class _QueueHarness:
    feature: SystemHealthFeature
    create_backlog: Callable[[], None]
    block: Callable[[], None]
    close: Callable[[], None]


@dataclass
class _CacheHarness:
    feature: SystemHealthFeature
    fail: Callable[[], None]
    recover: Callable[[], None]
    disconnect: Callable[[], None]
    reconnect: Callable[[], None]
    advance: Callable[[timedelta], None]
    close: Callable[[], None]


@dataclass
class _CacheCompatibilityHarness:
    feature: SystemHealthFeature
    make_incompatible: Callable[[], None]
    close: Callable[[], None]


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

        def read_diagnostic_queue_health(self):
            return application_health.read_diagnostic_queue_health()

        def read_diagnostic_cache_health(self):
            return application_health.read_diagnostic_cache_health()

    feature = LiveSystemHealthAdapter(
        application_health=_ControllableHealth(),
        event_bridge=bridge,
        clock=clock,
        freshness_threshold=timedelta(seconds=5),
        sampling_interval=None,
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


@pytest.fixture(params=("live", "fake"))
def queue_harness(request: pytest.FixtureRequest, tmp_path) -> _QueueHarness:
    if request.param == "fake":
        feature = DeterministicFakeSystemHealthAdapter(initially_healthy=True)
        return _QueueHarness(
            feature=feature,
            create_backlog=feature.advance_queue_to_backlog,
            block=feature.advance_queue_to_blocked,
            close=feature.close,
        )

    (
        _source,
        _artifact_store,
        _engine,
        application,
        _application_adapter,
        task_feature,
    ) = _formal_live_stack(tmp_path)
    health = LiveSystemHealthAdapter(
        application_health=LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
            application,
            clock=lambda: datetime(2030, 1, 2, tzinfo=timezone.utc),
        ),
        event_bridge=EventBridge(subscribe_backend=False),
        clock=lambda: datetime(2030, 1, 2, tzinfo=timezone.utc),
        sampling_interval=None,
    )
    task_id: str | None = None

    def create_backlog() -> None:
        nonlocal task_id
        approved = _approved_formal_task(task_feature)
        task_id = approved.task_id
        accepted = task_feature.start_formal_diagnostic_campaign(
            StartFormalDiagnosticCampaign(
                command_id=DiagnosticCommandId("start-command-health-110"),
                idempotency_key=DiagnosticCommandIdempotencyKey(
                    "start-idempotency-health-110"
                ),
                task_id=approved.task_id,
                expected_revision=approved.revision,
                approved_revision=approved.revision,
            )
        )
        assert accepted.accepted

    def block() -> None:
        assert task_id is not None
        running = _read_task(task_feature, task_id)
        paused = task_feature.pause_diagnostic_target(
            PauseDiagnosticTarget(
                command_id=DiagnosticCommandId("pause-command-health-110"),
                idempotency_key=DiagnosticCommandIdempotencyKey(
                    "pause-idempotency-health-110"
                ),
                target=DiagnosticTaskTarget(task_id),
                expected_revision=running.revision,
            )
        )
        assert paused.accepted

    def close() -> None:
        health.close()
        task_feature.close()

    return _QueueHarness(
        feature=health,
        create_backlog=create_backlog,
        block=block,
        close=close,
    )


@pytest.fixture(params=("live", "fake"))
def unavailable_queue_feature(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> SystemHealthFeature:
    if request.param == "fake":
        feature = DeterministicFakeSystemHealthAdapter(initially_healthy=False)
        feature.advance_queue_to_unavailable()
        yield feature
        feature.close()
        return

    application = create_diagnostics_application()
    application.start()

    def fail_queue_read(*_args, **_kwargs):
        raise OSError(r"C:\private\queue.db --credential hidden traceback")

    monkeypatch.setattr(
        application,
        "diagnostic_task_queue_health",
        fail_queue_read,
    )
    feature = LiveSystemHealthAdapter(
        application_health=LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
            application
        ),
        event_bridge=EventBridge(subscribe_backend=False),
        sampling_interval=None,
    )
    yield feature
    feature.close()


@pytest.fixture(params=("live", "fake"))
def cache_harness(request: pytest.FixtureRequest) -> _CacheHarness:
    if request.param == "fake":
        feature = DeterministicFakeSystemHealthAdapter(
            initially_healthy=True,
            freshness_threshold=timedelta(seconds=5),
        )
        return _CacheHarness(
            feature=feature,
            fail=feature.advance_cache_to_unavailable,
            recover=feature.advance_cache_to_healthy,
            disconnect=feature.advance_to_disconnected,
            reconnect=feature.advance_to_reconnected,
            advance=feature.advance_clock,
            close=feature.close,
        )

    clock = _Clock()
    source = _RecipeFixtureSource()
    store = ApplicationDrivenCacheStore(clock=clock)
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=store,
        recipe_clock=clock,
    )
    application.start()
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    draft = application.create_manual_recipe_draft(
        _baseline_payload(admission.segment.segment_id),
        author="researcher",
    )
    assert application.validate_recipe_draft(draft.draft_id).is_valid
    approved = application.approve_recipe_draft(draft.draft_id, actor="owner")
    application.materialize_baseline_reference_path(approved.version_id)
    bridge = EventBridge(subscribe_backend=False)
    feature = LiveSystemHealthAdapter(
        application_health=LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
            application,
            clock=clock,
        ),
        event_bridge=bridge,
        clock=clock,
        freshness_threshold=timedelta(seconds=5),
        sampling_interval=None,
    )

    def fail() -> None:
        store.fail_next_application_list()
        with pytest.raises(OSError):
            application.list_materialized_market_paths()

    def recover() -> None:
        application.list_materialized_market_paths()

    return _CacheHarness(
        feature=feature,
        fail=fail,
        recover=recover,
        disconnect=bridge.mark_disconnected,
        reconnect=bridge.mark_reconnected,
        advance=clock.advance,
        close=feature.close,
    )


@pytest.fixture(params=("live", "fake"))
def cache_compatibility_harness(
    request: pytest.FixtureRequest,
) -> _CacheCompatibilityHarness:
    if request.param == "fake":
        feature = DeterministicFakeSystemHealthAdapter(initially_healthy=True)
        feature.advance_cache_to_fallback()
        return _CacheCompatibilityHarness(
            feature=feature,
            make_incompatible=feature.advance_cache_to_incompatible,
            close=feature.close,
        )

    clock = _Clock()
    source = _RecipeFixtureSource()
    store = ApplicationDrivenCacheStore(
        clock=clock,
        fallback_on_first_put=True,
        incompatible_on_second_put=True,
    )
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=store,
        recipe_clock=clock,
    )
    application.start()
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    draft = application.create_manual_recipe_draft(
        _baseline_payload(admission.segment.segment_id),
        author="researcher",
    )
    assert application.validate_recipe_draft(draft.draft_id).is_valid
    approved = application.approve_recipe_draft(draft.draft_id, actor="owner")
    application.materialize_baseline_reference_path(
        approved.version_id
    )
    incompatible_payload = _baseline_payload(admission.segment.segment_id)
    incompatible_payload["name"] = "Incompatible cache publication"
    incompatible_payload["materialization_seed"] = 19
    incompatible_draft = application.create_manual_recipe_draft(
        incompatible_payload,
        author="researcher",
    )
    assert application.validate_recipe_draft(incompatible_draft.draft_id).is_valid
    incompatible_approved = application.approve_recipe_draft(
        incompatible_draft.draft_id,
        actor="owner",
    )
    feature = LiveSystemHealthAdapter(
        application_health=LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
            application,
            clock=clock,
        ),
        event_bridge=EventBridge(subscribe_backend=False),
        clock=clock,
        sampling_interval=None,
    )

    def make_incompatible() -> None:
        with pytest.raises(ValueError):
            application.materialize_baseline_reference_path(
                incompatible_approved.version_id
            )

    return _CacheCompatibilityHarness(
        feature=feature,
        make_incompatible=make_incompatible,
        close=feature.close,
    )


def test_live_and_fake_share_queue_normal_backlog_and_blocked_contract(
    queue_harness: _QueueHarness,
) -> None:
    try:
        normal = queue_harness.feature.snapshot(SystemHealthContext())
        assert normal.diagnostic_queue.classification is (
            DiagnosticQueueHealthClassification.HEALTHY
        )
        assert (
            normal.diagnostic_queue.pending_count,
            normal.diagnostic_queue.running_count,
            normal.diagnostic_queue.blocked_count,
        ) == (0, 0, 0)

        queue_harness.create_backlog()
        backlog = queue_harness.feature.snapshot(SystemHealthContext())
        assert backlog.diagnostic_queue.classification is (
            DiagnosticQueueHealthClassification.DEGRADED
        )
        assert backlog.diagnostic_queue.pending_count > 0
        assert backlog.diagnostic_queue.running_count > 0
        assert backlog.diagnostic_queue.oldest_pending_age is not None
        assert backlog.diagnostic_queue.consumer_availability is (
            DiagnosticQueueConsumerAvailability.AVAILABLE
        )
        assert DiagnosticQueueScope.CAMPAIGN_NODES in (
            backlog.diagnostic_queue.affected_scope
        )

        queue_harness.block()
        blocked = queue_harness.feature.snapshot(SystemHealthContext())
        assert blocked.diagnostic_queue.classification is (
            DiagnosticQueueHealthClassification.DEGRADED
        )
        assert blocked.diagnostic_queue.blocked_count > 0
        assert blocked.diagnostic_queue.consumer_availability is (
            DiagnosticQueueConsumerAvailability.BLOCKED
        )
        assert blocked.diagnostic_queue.blockage_reason is (
            DiagnosticQueueBlockageReason.PAUSED_DIAGNOSTIC_WORK
        )
        assert [normal.revision, backlog.revision, blocked.revision] == sorted(
            {normal.revision, backlog.revision, blocked.revision}
        )
        assert all(
            state.diagnostic_queue.revision == state.revision
            and state.diagnostic_cache.revision == state.revision
            for state in (normal, backlog, blocked)
        )
    finally:
        queue_harness.close()


def test_live_and_fake_never_present_unavailable_queue_as_healthy(
    unavailable_queue_feature: SystemHealthFeature,
) -> None:
    state = unavailable_queue_feature.snapshot(SystemHealthContext())
    queue = state.diagnostic_queue
    assert queue.classification is DiagnosticQueueHealthClassification.UNAVAILABLE
    assert queue.consumer_availability is (
        DiagnosticQueueConsumerAvailability.UNAVAILABLE
    )
    assert queue.blockage_reason is (
        DiagnosticQueueBlockageReason.SOURCE_UNAVAILABLE
    )
    assert queue.error is not None
    exposed = f"{queue.explanation} {queue.error.explanation}".casefold()
    for forbidden in ("c:\\", "queue.db", "credential", "traceback"):
        assert forbidden not in exposed


def test_live_and_fake_share_cache_fresh_stale_and_recovery_contract(
    cache_harness: _CacheHarness,
) -> None:
    observed: list = []
    subscription = cache_harness.feature.subscribe(
        SystemHealthContext(),
        observed.append,
    )
    try:
        fresh = observed[-1]
        assert fresh.diagnostic_cache.classification is (
            DiagnosticCacheHealthClassification.HEALTHY
        )
        assert fresh.diagnostic_cache.fallback is (
            DiagnosticCacheFallbackState.PRIMARY
        )
        assert fresh.diagnostic_cache.last_refresh_result is (
            DiagnosticCacheLastRefreshResult.SUCCEEDED
        )
        assert fresh.diagnostic_cache.compatibility is (
            DiagnosticCacheCompatibility.COMPATIBLE
        )
        reliable_generation = fresh.diagnostic_cache.generation

        cache_harness.advance(timedelta(seconds=6))
        stale = cache_harness.feature.snapshot(SystemHealthContext())
        assert stale.diagnostic_cache.classification is (
            DiagnosticCacheHealthClassification.STALE
        )
        assert stale.diagnostic_cache.freshness is Freshness.STALE
        assert stale.diagnostic_cache.generation == reliable_generation

        cache_harness.recover()
        recovered_fresh = cache_harness.feature.snapshot(SystemHealthContext())
        assert recovered_fresh.diagnostic_cache.classification is (
            DiagnosticCacheHealthClassification.HEALTHY
        )

        cache_harness.fail()
        unavailable = cache_harness.feature.snapshot(SystemHealthContext())
        assert unavailable.diagnostic_cache.classification is (
            DiagnosticCacheHealthClassification.UNAVAILABLE
        )
        assert unavailable.diagnostic_cache.last_refresh_result is (
            DiagnosticCacheLastRefreshResult.FAILED
        )
        assert unavailable.diagnostic_cache.generation == (
            recovered_fresh.diagnostic_cache.generation
        )

        cache_harness.disconnect()
        cache_harness.reconnect()
        _wait_until(
            lambda: observed[-1].diagnostic_cache.recovery_phase
            is DiagnosticCacheRecoveryPhase.FAILED_RECOVERY
        )
        failed_recovery = observed[-1]
        assert failed_recovery.diagnostic_cache.recovery_phase is (
            DiagnosticCacheRecoveryPhase.FAILED_RECOVERY
        )
        assert any(
            state.diagnostic_cache.recovery_phase
            is DiagnosticCacheRecoveryPhase.RECOVERING
            for state in observed
        )

        cache_harness.disconnect()
        cache_harness.recover()
        cache_harness.reconnect()
        _wait_until(
            lambda: observed[-1].diagnostic_cache.recovery_phase
            is DiagnosticCacheRecoveryPhase.RECOVERED
        )
        recovered = observed[-1]
        assert recovered.diagnostic_cache.recovery_phase is (
            DiagnosticCacheRecoveryPhase.RECOVERED
        )
        assert recovered.diagnostic_cache.classification is (
            DiagnosticCacheHealthClassification.HEALTHY
        )
        revisions = [state.revision for state in observed]
        assert revisions == sorted(set(revisions))
    finally:
        subscription.dispose()
        cache_harness.close()


def test_live_and_fake_share_cache_fallback_and_incompatible_contract(
    cache_compatibility_harness: _CacheCompatibilityHarness,
) -> None:
    try:
        fallback = cache_compatibility_harness.feature.snapshot(
            SystemHealthContext()
        )
        assert fallback.diagnostic_cache.classification is (
            DiagnosticCacheHealthClassification.FALLBACK
        )
        assert fallback.diagnostic_cache.fallback is (
            DiagnosticCacheFallbackState.ACTIVE
        )
        assert fallback.diagnostic_cache.last_refresh_result is (
            DiagnosticCacheLastRefreshResult.FALLBACK_SUCCEEDED
        )
        assert fallback.diagnostic_cache.compatibility is (
            DiagnosticCacheCompatibility.COMPATIBLE
        )

        cache_compatibility_harness.make_incompatible()
        incompatible = cache_compatibility_harness.feature.snapshot(
            SystemHealthContext()
        )
        assert incompatible.diagnostic_cache.classification is (
            DiagnosticCacheHealthClassification.INCOMPATIBLE
        )
        assert incompatible.diagnostic_cache.compatibility is (
            DiagnosticCacheCompatibility.INCOMPATIBLE
        )
        assert incompatible.diagnostic_cache.last_refresh_result is (
            DiagnosticCacheLastRefreshResult.FAILED
        )
        assert incompatible.diagnostic_cache.fallback is (
            DiagnosticCacheFallbackState.UNAVAILABLE
        )
        assert incompatible.revision > fallback.revision
    finally:
        cache_compatibility_harness.close()


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
        assert state.diagnostic_queue.classification is (
            DiagnosticQueueHealthClassification.UNKNOWN
        )
        assert state.diagnostic_cache.classification is (
            DiagnosticCacheHealthClassification.UNKNOWN
        )
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
        _wait_until(
            lambda: harness.feature.snapshot(
                SystemHealthContext()
            ).recovery_phase
            is RuntimeHealthRecoveryPhase.DISCONNECTED
        )
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
        _wait_until(
            lambda: observed[-1].recovery_phase
            is RuntimeHealthRecoveryPhase.FAILED
        )
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
        sampling_interval=None,
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
        reliable_queue = observed[-1].diagnostic_queue
        harness.disconnect()
        _wait_until(
            lambda: observed[-1].recovery_phase
            is RuntimeHealthRecoveryPhase.DISCONNECTED
        )
        degraded = observed[-1]
        assert degraded.presentation is SystemHealthPresentationState.DEGRADED
        assert degraded.recovery_phase is RuntimeHealthRecoveryPhase.DISCONNECTED
        assert degraded.last_reliable_payload == reliable
        assert degraded.diagnostic_queue.classification is (
            DiagnosticQueueHealthClassification.DEGRADED
        )
        assert degraded.diagnostic_queue.freshness is Freshness.DISCONNECTED
        assert degraded.diagnostic_queue.pending_count == (
            reliable_queue.pending_count
        )

        harness.advance(timedelta(seconds=6))
        stale = harness.feature.snapshot(SystemHealthContext())
        assert stale.presentation is SystemHealthPresentationState.STALE
        assert stale.freshness is Freshness.STALE
        assert stale.last_reliable_payload == reliable
        assert stale.diagnostic_queue.classification is (
            DiagnosticQueueHealthClassification.STALE
        )
        assert stale.diagnostic_queue.freshness is Freshness.STALE

        harness.reconnect()
        _wait_until(
            lambda: observed[-1].recovery_phase
            is RuntimeHealthRecoveryPhase.RECOVERED
        )
        recovered = observed[-1]
        assert any(
            state.recovery_phase is RuntimeHealthRecoveryPhase.REREADING
            and state.presentation is SystemHealthPresentationState.RECOVERING
            for state in observed
        )
        assert recovered.recovery_phase is RuntimeHealthRecoveryPhase.RECOVERED
        assert recovered.presentation is SystemHealthPresentationState.RECOVERED
        assert recovered.last_reliable_payload is not None
        assert recovered.diagnostic_queue.recovery_phase.value == "recovered"
        assert recovered.diagnostic_queue.classification is (
            DiagnosticQueueHealthClassification.HEALTHY
        )
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
        _wait_until(
            lambda: observed[-1].presentation
            is SystemHealthPresentationState.DEGRADED
        )
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
        sampling_interval=None,
    )
    observed: list = []
    subscription = feature.subscribe(SystemHealthContext(), observed.append)
    try:
        bridge.mark_disconnected()
        bridge.mark_reconnected()
        _wait_until(lambda: observed[-1].source.generation.value == 2)
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


def test_live_adapter_coalesces_related_snapshots_once_per_event_bridge_batch() -> None:
    clock = _Clock()
    application = create_diagnostics_application()
    bridge = EventBridge(subscribe_backend=False)
    feature = LiveSystemHealthAdapter(
        application_health=LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
            application,
            clock=clock,
        ),
        event_bridge=bridge,
        clock=clock,
        sampling_interval=None,
    )
    observed: list = []
    subscription = feature.subscribe(SystemHealthContext(), observed.append)
    try:
        delivered = len(observed)
        application.start()
        bridge.on_snapshot({"feature": "diagnostic_tasks"})
        bridge.on_snapshot({"feature": "scenario_lab"})
        bridge.on_snapshot({"feature": "system_health"})
        bridge.flush(force=True)
        _wait_until(lambda: len(observed) == delivered + 1)
        assert len(observed) == delivered + 1

        bridge.on_snapshot({"feature": "system_health"})
        bridge.flush(force=True)
        assert len(observed) == delivered + 1

        bridge.on_snapshot({"feature": "run_monitoring"})
        bridge.flush(force=True)
        assert len(observed) == delivered + 1
    finally:
        subscription.dispose()
        feature.close()


def test_event_delivery_is_not_suppressed_by_a_prior_non_notifying_snapshot() -> None:
    clock = _Clock()
    application = create_diagnostics_application()
    bridge = EventBridge(subscribe_backend=False)
    feature = LiveSystemHealthAdapter(
        application_health=LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
            application,
            clock=clock,
        ),
        event_bridge=bridge,
        clock=clock,
        sampling_interval=None,
    )
    observed: list = []
    subscription = feature.subscribe(SystemHealthContext(), observed.append)
    try:
        delivered = len(observed)
        application.start()
        ready_snapshot = feature.snapshot(SystemHealthContext())
        assert ready_snapshot.components[0].classification is (
            RuntimeHealthClassification.HEALTHY
        )
        assert len(observed) == delivered

        bridge.on_snapshot({"feature": "system_health"})
        bridge.flush(force=True)
        _wait_until(lambda: len(observed) == delivered + 1)

        assert len(observed) == delivered + 1
        assert observed[-1].components[0].classification is (
            RuntimeHealthClassification.HEALTHY
        )
        assert observed[-1].revision > ready_snapshot.revision
    finally:
        subscription.dispose()
        feature.close()


def test_live_adapter_samples_off_the_ui_thread_without_a_qml_poll() -> None:
    application = create_diagnostics_application()
    became_healthy = Event()
    feature = LiveSystemHealthAdapter(
        application_health=LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
            application
        ),
        event_bridge=EventBridge(subscribe_backend=False),
        sampling_interval=timedelta(milliseconds=10),
    )

    def observe(state) -> None:
        if any(
            component.identity
            is SystemHealthComponentIdentity.APPLICATION_RUNTIME
            and component.classification
            is RuntimeHealthClassification.HEALTHY
            for component in state.components
        ):
            became_healthy.set()

    subscription = feature.subscribe(SystemHealthContext(), observe)
    try:
        application.start()
        assert became_healthy.wait(timeout=2)
    finally:
        subscription.dispose()
        feature.close()


def test_unchanged_tokens_advance_visible_backlog_and_cache_age_buckets() -> None:
    clock = _Clock()
    started_at = clock()
    cache_read_completed = Event()

    class _StaticHealth:
        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            observed_at = clock()
            return RuntimeHealthApplicationResult(
                availability=RuntimeHealthApplicationAvailability.READY,
                observation=RuntimeHealthApplicationObservation(
                    classification=RuntimeHealthClassification.HEALTHY,
                    observed_at=observed_at,
                    explanation="The application runtime is available.",
                ),
                source_token=SourceRevisionToken("a" * 64),
                observed_at=observed_at,
                error=None,
            )

        def read_diagnostic_queue_health(
            self,
        ) -> DiagnosticQueueApplicationResult:
            observed_at = clock()
            return DiagnosticQueueApplicationResult(
                availability=DiagnosticQueueApplicationAvailability.READY,
                observation=DiagnosticQueueApplicationObservation(
                    pending_count=2,
                    running_count=1,
                    blocked_count=0,
                    oldest_pending_at=started_at,
                    consumer_availability=(
                        DiagnosticQueueConsumerAvailability.AVAILABLE
                    ),
                    blockage_reason=DiagnosticQueueBlockageReason.NONE,
                    affected_scope=(DiagnosticQueueScope.DIAGNOSTIC_TASK,),
                    observed_at=observed_at,
                    explanation="Diagnostic work is being consumed.",
                ),
                source_token=SourceRevisionToken("b" * 64),
                observed_at=observed_at,
                error=None,
            )

        def read_diagnostic_cache_health(
            self,
        ) -> DiagnosticCacheApplicationResult:
            observed_at = clock()
            result = DiagnosticCacheApplicationResult(
                availability=DiagnosticCacheApplicationAvailability.READY,
                observation=DiagnosticCacheApplicationObservation(
                    generation=1,
                    fallback=DiagnosticCacheFallbackState.PRIMARY,
                    last_refresh_result=(
                        DiagnosticCacheLastRefreshResult.SUCCEEDED
                    ),
                    compatibility=DiagnosticCacheCompatibility.COMPATIBLE,
                    affected_scope=(DiagnosticCacheScope.REFERENCE_MARKET_PATHS,),
                    last_refresh_at=started_at,
                    observed_at=observed_at,
                    explanation="The Diagnostic Cache refresh succeeded.",
                ),
                source_token=SourceRevisionToken("c" * 64),
                observed_at=observed_at,
                error=None,
            )
            cache_read_completed.set()
            return result

        def read_persistence_health(
            self,
        ) -> PersistenceHealthApplicationObservation:
            return _compatible_persistence(clock())

        def read_version_health(self) -> VersionHealthApplicationObservation:
            return _compatible_version(clock())

    bridge = EventBridge(subscribe_backend=False)
    feature = LiveSystemHealthAdapter(
        application_health=_StaticHealth(),  # type: ignore[arg-type]
        event_bridge=bridge,
        clock=clock,
        freshness_threshold=timedelta(seconds=2),
        sampling_interval=None,
    )
    observed: list = []
    subscription = feature.subscribe(SystemHealthContext(), observed.append)
    try:
        delivered = len(observed)
        cache_read_completed.clear()
        clock.advance(timedelta(milliseconds=900))
        bridge.on_snapshot({"feature": "system_health"})
        bridge.flush(force=True)
        assert cache_read_completed.wait(timeout=1)
        assert len(observed) == delivered

        cache_read_completed.clear()
        clock.advance(timedelta(milliseconds=200))
        bridge.on_snapshot({"feature": "system_health"})
        bridge.flush(force=True)
        _wait_until(lambda: len(observed) == delivered + 1)
        advanced = observed[-1]
        assert advanced.diagnostic_queue.oldest_pending_age is not None
        assert advanced.diagnostic_queue.oldest_pending_age >= timedelta(seconds=1)
        assert advanced.diagnostic_cache.age >= timedelta(seconds=1)

        clock.advance(timedelta(seconds=1))
        bridge.on_snapshot({"feature": "system_health"})
        bridge.flush(force=True)
        _wait_until(
            lambda: observed[-1].diagnostic_cache.classification
            is DiagnosticCacheHealthClassification.STALE
        )
        assert observed[-1].diagnostic_cache.age > timedelta(seconds=2)
    finally:
        subscription.dispose()
        feature.close()


def test_event_bridge_callback_only_signals_the_worker_for_authoritative_reads() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    worker_read_entered = Event()
    release_worker_read = Event()
    flush_returned = Event()
    healthy = RuntimeHealthApplicationResult(
        availability=RuntimeHealthApplicationAvailability.READY,
        observation=RuntimeHealthApplicationObservation(
            classification=RuntimeHealthClassification.HEALTHY,
            observed_at=now,
            explanation="The application runtime is available.",
        ),
        source_token=SourceRevisionToken("d" * 64),
        observed_at=now,
        error=None,
    )

    class _WorkerBlockingHealth:
        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            if current_thread().name == "system-health-worker":
                worker_read_entered.set()
                release_worker_read.wait(timeout=5)
            return healthy

        def read_persistence_health(
            self,
        ) -> PersistenceHealthApplicationObservation:
            return _compatible_persistence(now)

        def read_version_health(self) -> VersionHealthApplicationObservation:
            return _compatible_version(now)

    bridge = EventBridge(subscribe_backend=False)
    feature = LiveSystemHealthAdapter(
        application_health=_WorkerBlockingHealth(),  # type: ignore[arg-type]
        event_bridge=bridge,
        clock=lambda: now,
        sampling_interval=None,
    )
    feature.snapshot(SystemHealthContext())

    def flush_from_ui_caller() -> None:
        bridge.on_snapshot({"feature": "system_health"})
        bridge.flush(force=True)
        flush_returned.set()

    flush_thread = Thread(target=flush_from_ui_caller, name="simulated-ui-thread")
    try:
        flush_thread.start()
        assert flush_returned.wait(timeout=1)
        assert worker_read_entered.wait(timeout=1)
    finally:
        release_worker_read.set()
        flush_thread.join(timeout=2)
        feature.close()


def test_close_suppresses_a_late_sampler_callback_without_waiting_for_its_read() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    sampler_read_entered = Event()
    release_sampler_read = Event()
    sampler_read_finished = Event()
    close_returned = Event()
    healthy_result = RuntimeHealthApplicationResult(
        availability=RuntimeHealthApplicationAvailability.READY,
        observation=RuntimeHealthApplicationObservation(
            classification=RuntimeHealthClassification.HEALTHY,
            observed_at=now,
            explanation="The application runtime is available.",
        ),
        source_token=SourceRevisionToken("c" * 64),
        observed_at=now,
        error=None,
    )

    class _BlockingSamplerHealth:
        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            if current_thread().name == "system-health-worker":
                sampler_read_entered.set()
                try:
                    release_sampler_read.wait(timeout=5)
                finally:
                    sampler_read_finished.set()
            return healthy_result

        def read_persistence_health(
            self,
        ) -> PersistenceHealthApplicationObservation:
            return _compatible_persistence(now)

        def read_version_health(self) -> VersionHealthApplicationObservation:
            return _compatible_version(now)

    feature = LiveSystemHealthAdapter(
        application_health=_BlockingSamplerHealth(),  # type: ignore[arg-type]
        event_bridge=EventBridge(subscribe_backend=False),
        clock=lambda: now,
        sampling_interval=timedelta(milliseconds=1),
    )
    observed: list = []
    subscription = feature.subscribe(SystemHealthContext(), observed.append)
    delivered = len(observed)

    def close() -> None:
        feature.close()
        close_returned.set()

    close_thread = Thread(target=close)
    try:
        assert sampler_read_entered.wait(timeout=2)
        close_thread.start()
        assert close_returned.wait(timeout=1)
        assert len(observed) == delivered
        release_sampler_read.set()
        assert sampler_read_finished.wait(timeout=2)
        assert len(observed) == delivered
    finally:
        release_sampler_read.set()
        if close_thread.ident is not None:
            close_thread.join(timeout=2)
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
        sampling_interval=None,
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
        sampling_interval=None,
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
        sampling_interval=None,
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

        _wait_until(
            lambda: (
                feature.snapshot(SystemHealthContext()).presentation
                is SystemHealthPresentationState.DEGRADED
            )
        )
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
