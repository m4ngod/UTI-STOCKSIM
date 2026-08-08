from __future__ import annotations

import inspect
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta, timezone
from threading import Event
from time import monotonic

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DatabaseError

from app.event_bridge import EventBridge
from app.features import (
    DiagnosticDataSourceApplicationAvailability,
    DiagnosticDataSourceApplicationErrorCode,
    DiagnosticDataSourceScope,
    DiagnosticCacheApplicationAvailability,
    DiagnosticCacheCompatibility,
    DiagnosticCacheFallbackState,
    DiagnosticCacheHealthClassification,
    DiagnosticCacheLastRefreshResult,
    DiagnosticQueueApplicationAvailability,
    DiagnosticQueueBlockageReason,
    DiagnosticQueueConsumerAvailability,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    HealthCompatibilityState,
    PersistenceAvailability,
    PersistenceReopenVerification,
    RUNTIME_HEALTH_APPLICATION_INTERFACE_VERSION,
    LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter,
    LiveSystemHealthAdapter,
    RuntimeHealthApplicationAvailability,
    RuntimeHealthApplicationErrorCode,
    RuntimeHealthClassification,
    RuntimeHealthRecoveryPhase,
    StrategyDiagnosticsV1SystemHealthApplication,
    SystemHealthContext,
    StartFormalDiagnosticCampaign,
    SystemHealthAffectedScope,
    SystemHealthErrorCode,
    SystemHealthPresentationState,
    SystemHealthRecoveryExpectation,
)
from strategy_diagnostics import (
    AdmissionCheck,
    HistoricalSegmentSelection,
    HistoricalSourceInspection,
    InMemoryHistoricalSource,
    SourceArtifact,
    SourceProvenance,
    create_diagnostics_application,
)
from strategy_diagnostics.market_paths import InMemoryMarketPathArtifactStore
from tests.frontend.system_health_support import ApplicationDrivenCacheStore
from tests.frontend.contract.test_diagnostic_task_campaign_start_live_contract import (
    _approved_formal_task,
    _formal_live_stack,
)
from tests.strategy_diagnostics.test_recipe_lifecycle import (
    _baseline_payload,
    _RecipeFixtureSource,
)
from strategy_diagnostics.reproduction import REPRODUCTION_MANIFEST_SCHEMA_VERSION


NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
REQUIRED_SOURCE_CHECKS = (
    "bar_continuity",
    "instrument_coverage",
    "eligible_universe",
    "trading_status",
    "st_status",
    "suspension_state",
    "industry_as_of",
    "adjustment_consistency",
    "causal_availability",
    "required_fields",
    "missing_data",
    "duplicates",
    "timestamps",
)


def _application_with_admitted_source(
    *,
    provider: object = "BaoStock",
    dataset: object = "local-a-share-fixture",
    version: object = "fixture-2026-07-21",
    source_observed_at: datetime | None = None,
):
    selection = HistoricalSegmentSelection(
        market="mainland-a-share",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
    )
    inspection = HistoricalSourceInspection(
        selection=selection,
        label="A-share diagnostic interval",
        provenance=SourceProvenance(
            provider=provider,  # type: ignore[arg-type]
            dataset=dataset,  # type: ignore[arg-type]
            version=version,  # type: ignore[arg-type]
            observed_at=(
                source_observed_at
                or datetime(2026, 7, 21, 23, 0, tzinfo=timezone.utc)
            ),
        ),
        artifacts=(
            SourceArtifact(
                name="daily-unadjusted",
                content_hash="1" * 64,
                row_count=60,
            ),
        ),
        eligible_instrument_count=120,
        trading_day_count=2,
        bar_count=60,
        checks=tuple(
            AdmissionCheck(
                code=code,
                passed=True,
                summary=f"{code} passed.",
            )
            for code in REQUIRED_SOURCE_CHECKS
        ),
    )
    application = create_diagnostics_application(
        historical_source=InMemoryHistoricalSource((inspection,))
    )
    application.start()
    admission = application.admit_historical_segment(selection)
    assert admission.status == "admitted"
    return application


def _readmit_default_source(application) -> None:
    admission = application.admit_historical_segment(
        HistoricalSegmentSelection(
            market="mainland-a-share",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 3),
        )
    )
    assert admission.status == "admitted"


def _application_with_malformed_recovery_source():
    reliable_selection = HistoricalSegmentSelection(
        market="mainland-a-share",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
    )
    malformed_selection = HistoricalSegmentSelection(
        market="mainland-a-share",
        start_date=date(2024, 1, 4),
        end_date=date(2024, 1, 5),
    )

    def inspection(
        selection: HistoricalSegmentSelection,
        *,
        provider: object,
        observed_at: datetime,
        digest_character: str,
    ) -> HistoricalSourceInspection:
        return HistoricalSourceInspection(
            selection=selection,
            label="A-share diagnostic interval",
            provenance=SourceProvenance(
                provider=provider,  # type: ignore[arg-type]
                dataset="local-a-share-fixture",
                version="fixture-2026-07-21",
                observed_at=observed_at,
            ),
            artifacts=(
                SourceArtifact(
                    name="daily-unadjusted",
                    content_hash=digest_character * 64,
                    row_count=60,
                ),
            ),
            eligible_instrument_count=120,
            trading_day_count=2,
            bar_count=60,
            checks=tuple(
                AdmissionCheck(
                    code=code,
                    passed=True,
                    summary=f"{code} passed.",
                )
                for code in REQUIRED_SOURCE_CHECKS
            ),
        )

    application = create_diagnostics_application(
        historical_source=InMemoryHistoricalSource(
            (
                inspection(
                    reliable_selection,
                    provider="BaoStock",
                    observed_at=datetime(2029, 12, 31, tzinfo=timezone.utc),
                    digest_character="1",
                ),
                inspection(
                    malformed_selection,
                    provider=123,
                    observed_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
                    digest_character="2",
                ),
            )
        )
    )
    application.start()
    admission = application.admit_historical_segment(reliable_selection)
    assert admission.status == "admitted"
    return application, malformed_selection


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 2.0) -> None:
    deadline = monotonic() + timeout
    wake = Event()
    while not predicate():
        remaining = deadline - monotonic()
        assert remaining > 0
        wake.wait(min(remaining, 0.01))


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


def test_runtime_health_application_1_0_reads_the_real_diagnostics_application() -> None:
    application = create_diagnostics_application()
    adapter = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        application,
        clock=lambda: NOW,
    )

    unavailable = adapter.read_runtime_health()
    assert adapter.interface_version.render() == "1.0"
    assert unavailable.availability is (
        RuntimeHealthApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
    )
    assert unavailable.observation is None
    assert unavailable.source_token is None
    assert unavailable.error is not None
    assert unavailable.error.code is (
        RuntimeHealthApplicationErrorCode.NO_AUTHORITATIVE_OBSERVATION
    )

    application.start()
    ready = adapter.read_runtime_health()

    assert ready.availability is RuntimeHealthApplicationAvailability.READY
    assert ready.observation is not None
    assert ready.observation.classification is RuntimeHealthClassification.HEALTHY
    assert ready.observation.observed_at == NOW
    assert ready.source_token is not None
    assert ready.error is None
    with pytest.raises(FrozenInstanceError):
        ready.observation.explanation = "mutable"  # type: ignore[misc]


def test_runtime_health_application_interface_is_small_and_read_only() -> None:
    assert RUNTIME_HEALTH_APPLICATION_INTERFACE_VERSION.render() == "1.0"
    operations = {
        name
        for name, member in inspect.getmembers(
            StrategyDiagnosticsV1SystemHealthApplication,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    assert operations == {
        "read_diagnostic_data_source_health",
        "read_runtime_health",
        "read_diagnostic_queue_health",
        "read_diagnostic_cache_health",
        "read_persistence_health",
        "read_version_health",
    }


def test_system_health_application_reads_a_safe_admitted_data_source() -> None:
    adapter = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        _application_with_admitted_source(),
        clock=lambda: NOW,
    )

    result = adapter.read_diagnostic_data_source_health()

    assert result.availability is DiagnosticDataSourceApplicationAvailability.READY
    assert result.observation is not None
    assert result.observation.identity.provider == "BaoStock"
    assert result.observation.identity.dataset.startswith("Dataset ")
    assert result.observation.identity.version.startswith("Version ")
    assert result.observation.identity.public_id.startswith("admitted-source-")
    assert result.observation.affected_scope == (
        DiagnosticDataSourceScope.SCENARIO_INPUTS,
        DiagnosticDataSourceScope.DIAGNOSTIC_EVIDENCE_INTERPRETATION,
    )
    assert result.source_token is not None
    assert result.error is None
    with pytest.raises(FrozenInstanceError):
        result.observation.identity.provider = "mutable"  # type: ignore[misc]


def test_data_source_application_redacts_raw_failure_details() -> None:
    class _ThrowingApplication:
        def list_historical_segments(self) -> object:
            raise OSError(
                r"C:\secrets\source.db?token=super-secret SELECT market_payload"
            )

    result = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        _ThrowingApplication(),  # type: ignore[arg-type]
        clock=lambda: NOW,
    ).read_diagnostic_data_source_health()

    assert result.availability is DiagnosticDataSourceApplicationAvailability.FAILED
    assert result.error is not None
    exposed = result.error.explanation.casefold()
    for forbidden in (
        "c:\\",
        "source.db",
        "token",
        "secret",
        "select",
        "market_payload",
    ):
        assert forbidden not in exposed


def test_data_source_application_projects_untrusted_provenance_opaquely() -> None:
    adapter = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        _application_with_admitted_source(
            provider="Authorization: Bearer sk-live-provider-secret",
            dataset="api_key=dataset-secret@example.test:6379",
            version="<script>cookie=version-secret</script>",
        ),
        clock=lambda: NOW,
    )

    result = adapter.read_diagnostic_data_source_health()

    assert result.availability is DiagnosticDataSourceApplicationAvailability.READY
    assert result.observation is not None
    identity = result.observation.identity
    assert identity.provider.startswith("Provider ")
    assert identity.dataset.startswith("Dataset ")
    assert identity.version.startswith("Version ")
    exposed = repr(result).casefold()
    for forbidden in (
        "authorization",
        "bearer",
        "sk-live",
        "api_key",
        "dataset-secret",
        "example.test",
        "script",
        "cookie",
        "version-secret",
    ):
        assert forbidden not in exposed


def test_data_source_application_fails_safely_for_malformed_provenance() -> None:
    adapter = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        _application_with_admitted_source(provider=123),
        clock=lambda: NOW,
    )

    result = adapter.read_diagnostic_data_source_health()

    assert result.availability is DiagnosticDataSourceApplicationAvailability.FAILED
    assert result.observation is None
    assert result.source_token is None
    assert result.error is not None
    assert result.error.code is DiagnosticDataSourceApplicationErrorCode.READ_FAILED
    assert result.error.explanation == (
        "The authoritative diagnostic data-source read failed safely."
    )


def test_queue_and_cache_health_read_only_seam_uses_supported_application_behavior() -> None:
    source = _RecipeFixtureSource()
    artifact_store = InMemoryMarketPathArtifactStore(clock=lambda: NOW)
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=artifact_store,
        recipe_clock=lambda: NOW,
        diagnostic_task_clock=lambda: NOW,
    )
    application.start()
    adapter = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        application,
        clock=lambda: NOW,
    )

    empty_queue = adapter.read_diagnostic_queue_health()
    assert empty_queue.availability is DiagnosticQueueApplicationAvailability.READY
    assert empty_queue.observation is not None
    assert (
        empty_queue.observation.pending_count,
        empty_queue.observation.running_count,
        empty_queue.observation.blocked_count,
    ) == (0, 0, 0)
    assert empty_queue.observation.oldest_pending_at is None
    assert empty_queue.observation.consumer_availability is (
        DiagnosticQueueConsumerAvailability.AVAILABLE
    )
    assert empty_queue.observation.blockage_reason is (
        DiagnosticQueueBlockageReason.NONE
    )

    unobserved_cache = adapter.read_diagnostic_cache_health()
    assert unobserved_cache.availability is (
        DiagnosticCacheApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
    )
    assert unobserved_cache.observation is None

    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    draft = application.create_manual_recipe_draft(
        _baseline_payload(admission.segment.segment_id),
        author="researcher",
    )
    assert application.validate_recipe_draft(draft.draft_id).is_valid
    approved = application.approve_recipe_draft(draft.draft_id, actor="owner")
    application.materialize_baseline_reference_path(approved.version_id)

    before_observation = artifact_store.diagnostic_cache_health()
    cache = adapter.read_diagnostic_cache_health()
    after_observation = artifact_store.diagnostic_cache_health()

    assert cache.availability is DiagnosticCacheApplicationAvailability.READY
    assert cache.observation is not None
    assert cache.observation.generation >= 1
    assert cache.observation.fallback is DiagnosticCacheFallbackState.PRIMARY
    assert cache.observation.last_refresh_result is (
        DiagnosticCacheLastRefreshResult.SUCCEEDED
    )
    assert cache.observation.compatibility is (
        DiagnosticCacheCompatibility.COMPATIBLE
    )
    assert before_observation == after_observation


def test_runtime_health_application_redacts_raw_failure_details(caplog) -> None:
    class _ThrowingApplication:
        def status(self) -> object:
            raise OSError(
                r"C:\secrets\runtime.exe --token super-secret SELECT * FROM users"
            )

        def diagnostic_task_queue_health(self) -> object:
            raise OSError(
                r"C:\private\task.db --credential queue-secret traceback payload"
            )

        def diagnostic_cache_health(self) -> object:
            raise OSError(
                r"C:\private\cache.bin --token cache-secret SELECT raw_value"
            )

    adapter = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        _ThrowingApplication(),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    results = (
        adapter.read_runtime_health(),
        adapter.read_diagnostic_queue_health(),
        adapter.read_diagnostic_cache_health(),
    )

    assert results[0].availability is RuntimeHealthApplicationAvailability.FAILED
    assert results[0].error is not None
    assert results[0].error.code is RuntimeHealthApplicationErrorCode.READ_FAILED
    for result in results:
        assert result.error is not None
        exposed = result.error.explanation.casefold()
        for forbidden in (
            "c:\\",
            "runtime.exe",
            "task.db",
            "cache.bin",
            "token",
            "credential",
            "secret",
            "select",
            "users",
            "payload",
            "traceback",
            "raw_value",
        ):
            assert forbidden not in exposed
    assert caplog.text == ""


def test_first_incompatible_cache_observation_keeps_typed_state_without_generation(
) -> None:
    source = _RecipeFixtureSource()
    store = ApplicationDrivenCacheStore(
        clock=lambda: NOW,
        incompatible_on_first_put=True,
    )
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=store,
        recipe_clock=lambda: NOW,
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
    with pytest.raises(ValueError):
        application.materialize_baseline_reference_path(approved.version_id)

    application_adapter = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        application,
        clock=lambda: NOW,
    )
    result = application_adapter.read_diagnostic_cache_health()
    assert result.availability is DiagnosticCacheApplicationAvailability.READY
    assert result.observation is not None
    assert result.observation.generation is None
    assert result.observation.compatibility is (
        DiagnosticCacheCompatibility.INCOMPATIBLE
    )

    feature = LiveSystemHealthAdapter(
        application_health=application_adapter,
        event_bridge=EventBridge(subscribe_backend=False),
        clock=lambda: NOW,
        sampling_interval=None,
    )
    try:
        component = feature.snapshot(SystemHealthContext()).diagnostic_cache
        assert component.classification is (
            DiagnosticCacheHealthClassification.INCOMPATIBLE
        )
        assert component.generation is None
    finally:
        feature.close()


def test_sql_queue_health_uses_one_bounded_active_target_projection(tmp_path) -> None:
    (
        _source,
        _artifact_store,
        engine,
        application,
        _application_adapter,
        task_feature,
    ) = _formal_live_stack(tmp_path)
    try:
        approved = _approved_formal_task(task_feature)
        accepted = task_feature.start_formal_diagnostic_campaign(
            StartFormalDiagnosticCampaign(
                command_id=DiagnosticCommandId("start-command-bounded-health-110"),
                idempotency_key=DiagnosticCommandIdempotencyKey(
                    "start-idempotency-bounded-health-110"
                ),
                task_id=approved.task_id,
                expected_revision=approved.revision,
                approved_revision=approved.revision,
            )
        )
        assert accepted.accepted
        statements: list[str] = []

        def capture_statement(
            _connection,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            statements.append(str(statement).casefold())

        event.listen(engine, "before_cursor_execute", capture_statement)
        try:
            result = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
                application,
                clock=lambda: NOW,
            ).read_diagnostic_queue_health()
        finally:
            event.remove(engine, "before_cursor_execute", capture_statement)

        assert result.availability is DiagnosticQueueApplicationAvailability.READY
        assert result.observation is not None
        assert len(statements) == 1
        assert "diagnostic_lifecycle_targets" in statements[0]
        for forbidden in (
            "configuration_json",
            "diagnostic_task_handles",
            "diagnostic_task_validations",
            "diagnostic_task_campaign_handoffs",
        ):
            assert forbidden not in statements[0]
    finally:
        task_feature.close()


def test_persistence_health_observes_real_durable_read_write_and_reopen(
    tmp_path,
) -> None:
    database = tmp_path / "diagnostic-health.sqlite3"
    first_engine = create_engine(f"sqlite+pysqlite:///{database}")
    first_application = create_diagnostics_application()
    first_application.start()
    first_report = first_application.initialize_persistence(first_engine)
    first = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        first_application,
        clock=lambda: NOW,
    ).read_persistence_health()

    assert first_report.applied_revisions
    assert first.availability is PersistenceAvailability.AVAILABLE
    assert first.schema_compatibility is HealthCompatibilityState.COMPATIBLE
    assert first.schema_head == first.supported_schema_head
    assert first.last_successful_durable_read_at is not None
    assert first.last_successful_durable_write_at is not None
    assert first.reopen_verification is (
        PersistenceReopenVerification.NOT_YET_VERIFIED
    )
    same_owner_report = first_application.initialize_persistence(first_engine)
    same_owner = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        first_application,
        clock=lambda: NOW,
    ).read_persistence_health()
    assert same_owner_report.applied_revisions == ()
    assert same_owner.reopen_verification is (
        PersistenceReopenVerification.NOT_YET_VERIFIED
    )
    first_engine.dispose()

    reopened_engine = create_engine(f"sqlite+pysqlite:///{database}")
    reopened_application = create_diagnostics_application()
    reopened_application.start()
    reopened_report = reopened_application.initialize_persistence(reopened_engine)
    reopened = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        reopened_application,
        clock=lambda: NOW,
    ).read_persistence_health()

    assert reopened_report.applied_revisions == ()
    assert reopened.reopen_verification is PersistenceReopenVerification.VERIFIED
    assert reopened.last_successful_durable_write_at == (
        first.last_successful_durable_write_at
    )
    reopened_engine.dispose()


def test_version_health_reads_the_exact_registry_lock_and_format_identities() -> None:
    application = _application_with_admitted_source(source_observed_at=NOW)
    version = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        application,
        clock=lambda: NOW,
        current_manifest_format_provider=(
            lambda: REPRODUCTION_MANIFEST_SCHEMA_VERSION
        ),
    ).read_version_health()

    assert version.product_build == "stock-sim/0.0.1"
    assert tuple(
        (item.name.value, item.version.render())
        for item in version.feature_interfaces
    ) == (
        ("StrategyLibraryFeature", "1.0"),
        ("ScenarioLabFeature", "1.0"),
        ("DiagnosticTasksFeature", "1.0"),
        ("RunMonitoringFeature", "1.2"),
        ("EvidenceAndFindingsFeature", "1.1"),
        ("SystemHealthFeature", "1.0"),
    )
    assert version.dependency_lock_identity == (
        "sha256:f53b1b7245e48a33420ee7a2657c7d7bedc35a61cefbe0fc86ce0a1232bfaf1f"
    )
    assert version.release_manifest_compatibility is (
        HealthCompatibilityState.COMPATIBLE
    )
    assert version.runner_version == "strategy-diagnostics-v1"
    assert version.schema_version == (
        "0021_diagnostic_selection_dependency_invalidation"
    )
    assert version.evidence_format_version == "diagnostic-evidence.v1"
    assert version.manifest_format_version == "reproduction-manifest.v1"
    assert version.reproduction_manifest_compatibility is (
        HealthCompatibilityState.COMPATIBLE
    )
    assert version.error is None


def test_version_health_rejects_a_readable_lock_that_breaks_release_binding(
    tmp_path,
) -> None:
    source_lock = (
        Path(__file__).parents[3]
        / "stock_sim"
        / "release"
        / "frontend_v2_toolchain.lock.json"
    )
    original_lock = json.loads(source_lock.read_text(encoding="utf-8"))
    changed_lock = json.loads(json.dumps(original_lock))
    changed_lock["toolchain"]["python"] = "99.99.99"
    lock_fixture = tmp_path / "readable-mutated-lock.json"
    lock_fixture.write_text(json.dumps(changed_lock), encoding="utf-8")
    application = _application_with_admitted_source(source_observed_at=NOW)

    version = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        application,
        clock=lambda: NOW,
        dependency_lock_path=lock_fixture,
        current_manifest_format_provider=(
            lambda: REPRODUCTION_MANIFEST_SCHEMA_VERSION
        ),
        release_manifest_provider=(
            lambda: {"schema_version": 1, "toolchain_lock": original_lock}
        ),
    ).read_version_health()

    assert version.dependency_lock_identity is not None
    assert version.release_manifest_compatibility is (
        HealthCompatibilityState.INCOMPATIBLE
    )
    assert version.error is not None
    assert version.error.code is (
        RuntimeHealthApplicationErrorCode.RELEASE_MANIFEST_INCOMPATIBLE
    )
    assert lock_fixture.name.casefold() not in repr(version).casefold()


def test_version_health_without_release_binding_is_unknown_not_healthy(
    tmp_path,
) -> None:
    application = _application_with_admitted_source(source_observed_at=NOW)
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'release-binding-missing.sqlite3'}"
    )
    application.initialize_persistence(engine)
    _readmit_default_source(application)
    adapter = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        application,
        clock=lambda: NOW,
        current_manifest_format_provider=(
            lambda: REPRODUCTION_MANIFEST_SCHEMA_VERSION
        ),
        release_manifest_provider=lambda: None,
    )

    version = adapter.read_version_health()

    assert version.release_manifest_compatibility is (
        HealthCompatibilityState.UNKNOWN
    )
    assert version.error is not None
    assert version.error.code is (
        RuntimeHealthApplicationErrorCode.RELEASE_MANIFEST_UNAVAILABLE
    )
    feature = LiveSystemHealthAdapter(
        application_health=adapter,
        event_bridge=EventBridge(subscribe_backend=False),
        clock=lambda: NOW,
    )
    try:
        state = feature.snapshot(SystemHealthContext())

        assert state.presentation is SystemHealthPresentationState.DEGRADED
        assert state.error is not None
        assert state.error.code is SystemHealthErrorCode.RELEASE_BINDING_UNAVAILABLE
        assert state.error.affected_scope is (
            SystemHealthAffectedScope.VERSION_COMPATIBILITY
        )
        assert state.error.recovery_expectation is (
            SystemHealthRecoveryExpectation.RELEASE_REPAIR_REQUIRED
        )
    finally:
        feature.close()
        engine.dispose()


def test_version_health_without_a_selected_manifest_is_unknown_not_healthy(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("STOCKSIM_FRONTEND_V2_EVIDENCE_PACKAGE_ID", raising=False)
    monkeypatch.delenv(
        "STOCKSIM_FRONTEND_V2_REPRODUCTION_MANIFEST_ID",
        raising=False,
    )
    database = tmp_path / "manifest-unknown.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    seed = create_diagnostics_application()
    seed.start()
    seed.initialize_persistence(engine)
    application = _application_with_admitted_source(source_observed_at=NOW)
    application.initialize_persistence(engine)
    _readmit_default_source(application)
    adapter = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        application,
        clock=lambda: NOW,
    )
    version = adapter.read_version_health()

    assert version.reproduction_manifest_compatibility is (
        HealthCompatibilityState.UNKNOWN
    )
    assert version.error is not None
    assert version.error.code is RuntimeHealthApplicationErrorCode.MANIFEST_UNAVAILABLE
    feature = LiveSystemHealthAdapter(
        application_health=adapter,
        event_bridge=EventBridge(subscribe_backend=False),
        clock=lambda: NOW,
    )
    try:
        state = feature.snapshot(SystemHealthContext())
        persistence = state.components[1]

        assert state.presentation is SystemHealthPresentationState.UNKNOWN
        assert state.error is not None
        assert state.error.code is (
            SystemHealthErrorCode.REPRODUCTION_MANIFEST_UNAVAILABLE
        )
        assert state.error.affected_scope is (
            SystemHealthAffectedScope.REPRODUCTION_MANIFEST
        )
        assert state.error.recovery_expectation is (
            SystemHealthRecoveryExpectation.INITIALIZATION_REQUIRED
        )
        assert state.last_reliable_payload is not None
        assert tuple(item.identity for item in state.last_reliable_payload) == (
            state.components[0].identity,
            persistence.identity,
        )
        durable_read = persistence.last_successful_durable_read_at
        durable_write = persistence.last_successful_durable_write_at

        engine.dispose()
        database.write_bytes(b"controlled unavailable fixture")
        unavailable = feature.snapshot(SystemHealthContext())

        assert unavailable.presentation is SystemHealthPresentationState.UNAVAILABLE
        assert unavailable.components[1].last_successful_durable_read_at == (
            durable_read
        )
        assert unavailable.components[1].last_successful_durable_write_at == (
            durable_write
        )
    finally:
        feature.close()
        engine.dispose()


def test_version_health_reads_the_selected_persisted_manifest_format(
    monkeypatch,
) -> None:
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2_EVIDENCE_PACKAGE_ID", "evidence-1")
    monkeypatch.setenv(
        "STOCKSIM_FRONTEND_V2_REPRODUCTION_MANIFEST_ID",
        "manifest-1",
    )
    application = create_diagnostics_application()
    application.start()
    monkeypatch.setattr(
        application,
        "read_reproduction_manifest_format_identity",
        lambda _evidence_id, _manifest_id: (
            REPRODUCTION_MANIFEST_SCHEMA_VERSION
        ),
    )

    version = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        application,
        clock=lambda: NOW,
    ).read_version_health()

    assert version.reproduction_manifest_compatibility is (
        HealthCompatibilityState.COMPATIBLE
    )
    assert version.error is None


def test_copied_controlled_persistence_fixtures_fail_closed_without_leaks(
    tmp_path,
) -> None:
    source = tmp_path / "source.sqlite3"
    source_engine = create_engine(f"sqlite+pysqlite:///{source}")
    source_application = create_diagnostics_application()
    source_application.start()
    source_application.initialize_persistence(source_engine)
    source_engine.dispose()

    unavailable_fixture = tmp_path / "unavailable-copy.sqlite3"
    shutil.copy2(source, unavailable_fixture)
    unavailable_fixture.write_bytes(b"controlled unavailable fixture")
    unavailable_engine = create_engine(
        f"sqlite+pysqlite:///{unavailable_fixture}"
    )
    unavailable_application = create_diagnostics_application()
    unavailable_application.start()
    with pytest.raises(DatabaseError):
        unavailable_application.initialize_persistence(unavailable_engine)
    unavailable_adapter = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        unavailable_application,
        clock=lambda: NOW,
    )
    unavailable = unavailable_adapter.read_persistence_health()

    assert unavailable.availability is PersistenceAvailability.UNAVAILABLE
    assert unavailable.schema_compatibility is HealthCompatibilityState.UNKNOWN
    assert unavailable.last_successful_durable_read_at is None
    assert unavailable.error is not None
    exposed = repr(unavailable).casefold()
    for forbidden in (
        unavailable_fixture.name.casefold(),
        "sqlite+pysqlite",
        "select ",
        "traceback",
    ):
        assert forbidden not in exposed
    unavailable_feature = LiveSystemHealthAdapter(
        application_health=unavailable_adapter,
        event_bridge=EventBridge(subscribe_backend=False),
        clock=lambda: NOW,
    )
    try:
        unavailable_state = unavailable_feature.snapshot(SystemHealthContext())
        assert unavailable_state.presentation is (
            SystemHealthPresentationState.UNAVAILABLE
        )
        assert unavailable_state.components[1].availability is (
            PersistenceAvailability.UNAVAILABLE
        )
    finally:
        unavailable_feature.close()
    unavailable_engine.dispose()

    incompatible_fixture = tmp_path / "schema-incompatible-copy.sqlite3"
    shutil.copy2(source, incompatible_fixture)
    fixture_engine = create_engine(f"sqlite+pysqlite:///{incompatible_fixture}")
    with fixture_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO diagnostic_schema_migrations "
                "(revision, applied_at_utc) VALUES "
                "(:revision, :applied_at_utc)"
            ),
            {
                "revision": "9999_controlled_future_revision",
                "applied_at_utc": NOW.isoformat(),
            },
        )
    fixture_engine.dispose()
    incompatible_engine = create_engine(
        f"sqlite+pysqlite:///{incompatible_fixture}"
    )
    incompatible_application = create_diagnostics_application()
    incompatible_application.start()
    with pytest.raises(ValueError, match="incompatible diagnostic schema"):
        incompatible_application.initialize_persistence(incompatible_engine)
    incompatible_adapter = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        incompatible_application,
        clock=lambda: NOW,
    )
    incompatible = incompatible_adapter.read_persistence_health()

    assert incompatible.availability is PersistenceAvailability.AVAILABLE
    assert incompatible.schema_compatibility is (
        HealthCompatibilityState.INCOMPATIBLE
    )
    assert incompatible.schema_head is None
    assert incompatible.reopen_verification is PersistenceReopenVerification.FAILED
    assert incompatible.error is not None
    assert incompatible.error.code is (
        RuntimeHealthApplicationErrorCode.PERSISTENCE_SCHEMA_INCOMPATIBLE
    )
    assert incompatible_fixture.name.casefold() not in repr(incompatible).casefold()
    incompatible_feature = LiveSystemHealthAdapter(
        application_health=incompatible_adapter,
        event_bridge=EventBridge(subscribe_backend=False),
        clock=lambda: NOW,
    )
    try:
        incompatible_state = incompatible_feature.snapshot(SystemHealthContext())
        assert incompatible_state.presentation is (
            SystemHealthPresentationState.INCOMPATIBLE
        )
        assert incompatible_state.components[1].schema_compatibility is (
            HealthCompatibilityState.INCOMPATIBLE
        )
    finally:
        incompatible_feature.close()
    incompatible_engine.dispose()


def test_copied_controlled_manifest_fixture_reports_incompatible_format(
    tmp_path,
) -> None:
    source = tmp_path / "supported-manifest.json"
    source.write_text(
        json.dumps({"schema_version": "reproduction-manifest.v1"}),
        encoding="utf-8",
    )
    fixture = tmp_path / "manifest-incompatible-copy.json"
    shutil.copy2(source, fixture)
    fixture.write_text(
        json.dumps({"schema_version": "reproduction-manifest.v999"}),
        encoding="utf-8",
    )
    application = create_diagnostics_application()
    application.start()
    adapter = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        application,
        clock=lambda: NOW,
        current_manifest_format_provider=(
            lambda: str(json.loads(fixture.read_text(encoding="utf-8"))["schema_version"])
        ),
    )

    version = adapter.read_version_health()

    assert version.reproduction_manifest_compatibility is (
        HealthCompatibilityState.INCOMPATIBLE
    )
    assert version.error is not None
    assert version.error.code is RuntimeHealthApplicationErrorCode.MANIFEST_INCOMPATIBLE
    exposed = repr(version).casefold()
    for forbidden in (fixture.name.casefold(), str(fixture.parent).casefold(), "traceback"):
        assert forbidden not in exposed


def test_default_live_provider_reads_future_manifest_format_from_copied_persistence(
    monkeypatch,
    tmp_path,
) -> None:
    source = tmp_path / "manifest-source.sqlite3"
    source_engine = create_engine(f"sqlite+pysqlite:///{source}")
    seed = create_diagnostics_application()
    seed.start()
    seed.initialize_persistence(source_engine)
    with source_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO diagnostic_reproduction_manifests ("
                "manifest_id, run_id, evidence_package_id, schema_version, "
                "numeric_tolerance, manifest_content_hash, manifest_json"
                ") VALUES ("
                ":manifest_id, :run_id, :evidence_package_id, :schema_version, "
                ":numeric_tolerance, :manifest_content_hash, :manifest_json"
                ")"
            ),
            {
                "manifest_id": "future-manifest",
                "run_id": "future-run",
                "evidence_package_id": "future-evidence",
                "schema_version": "reproduction-manifest.v999",
                "numeric_tolerance": "0.001",
                "manifest_content_hash": "future-format-fixture",
                "manifest_json": json.dumps(
                    {
                        "schema_version": "reproduction-manifest.v999",
                        "manifest_id": "future-manifest",
                    }
                ),
            },
        )
    source_engine.dispose()
    fixture = tmp_path / "manifest-incompatible-copy.sqlite3"
    shutil.copy2(source, fixture)
    fixture_engine = create_engine(f"sqlite+pysqlite:///{fixture}")
    application = create_diagnostics_application()
    application.start()
    application.initialize_persistence(fixture_engine)
    monkeypatch.setenv(
        "STOCKSIM_FRONTEND_V2_EVIDENCE_PACKAGE_ID",
        "future-evidence",
    )
    monkeypatch.setenv(
        "STOCKSIM_FRONTEND_V2_REPRODUCTION_MANIFEST_ID",
        "future-manifest",
    )

    version = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        application,
        clock=lambda: NOW,
    ).read_version_health()

    assert version.reproduction_manifest_compatibility is (
        HealthCompatibilityState.INCOMPATIBLE
    )
    assert version.error is not None
    assert version.error.code is RuntimeHealthApplicationErrorCode.MANIFEST_INCOMPATIBLE
    exposed = repr(version).casefold()
    for forbidden in (
        fixture.name.casefold(),
        str(fixture.parent).casefold(),
        "diagnostic_reproduction_manifests",
        "select ",
        "traceback",
    ):
        assert forbidden not in exposed
    fixture_engine.dispose()


def test_copied_file_fixture_flows_through_live_feature_stale_and_recovery(
    tmp_path,
) -> None:
    source = tmp_path / "source.sqlite3"
    source_engine = create_engine(f"sqlite+pysqlite:///{source}")
    source_application = create_diagnostics_application()
    source_application.start()
    source_application.initialize_persistence(source_engine)
    source_engine.dispose()
    fixture = tmp_path / "reopen-copy.sqlite3"
    shutil.copy2(source, fixture)
    engine = create_engine(f"sqlite+pysqlite:///{fixture}")
    application = _application_with_admitted_source(source_observed_at=NOW)
    report = application.initialize_persistence(engine)
    _readmit_default_source(application)
    now = [NOW]
    bridge = EventBridge(subscribe_backend=False)
    feature = LiveSystemHealthAdapter(
        application_health=LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
            application,
            clock=lambda: now[0],
            current_manifest_format_provider=(
                lambda: REPRODUCTION_MANIFEST_SCHEMA_VERSION
            ),
        ),
        event_bridge=bridge,
        clock=lambda: now[0],
        freshness_threshold=timedelta(seconds=5),
    )
    observed = []
    subscription = feature.subscribe(SystemHealthContext(), observed.append)
    try:
        compatible = observed[-1]
        assert report.applied_revisions == ()
        assert compatible.presentation is SystemHealthPresentationState.HEALTHY
        assert compatible.components[1].reopen_verification is (
            PersistenceReopenVerification.VERIFIED
        )

        bridge.mark_disconnected()
        _wait_until(
            lambda: observed[-1].recovery_phase
            is RuntimeHealthRecoveryPhase.DISCONNECTED
        )
        now[0] += timedelta(seconds=6)
        stale = feature.snapshot(SystemHealthContext())
        assert stale.presentation is SystemHealthPresentationState.STALE

        bridge.mark_reconnected()
        _wait_until(
            lambda: observed[-1].recovery_phase
            is RuntimeHealthRecoveryPhase.RECOVERED
        )
        assert any(
            state.presentation is SystemHealthPresentationState.RECOVERING
            for state in observed
        )
        bridge.on_snapshot(
            {
                "feature": "system_health",
                "component": "diagnostic_data_source",
                "source_revision": 2,
            },
            generation=2,
        )
        bridge.flush(force=True)
        _wait_until(
            lambda: observed[-1].diagnostic_data_source.recovery_phase.value
            == "recovered"
        )
        assert observed[-1].presentation is SystemHealthPresentationState.STALE
    finally:
        subscription.dispose()
        feature.close()
        engine.dispose()
