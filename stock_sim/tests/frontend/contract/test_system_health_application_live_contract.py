from __future__ import annotations

import inspect
import json
import shutil
from pathlib import Path
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DatabaseError

from app.features import (
    HealthCompatibilityState,
    PersistenceAvailability,
    PersistenceReopenVerification,
    RUNTIME_HEALTH_APPLICATION_INTERFACE_VERSION,
    LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter,
    LiveSystemHealthAdapter,
    RuntimeHealthApplicationAvailability,
    RuntimeHealthApplicationErrorCode,
    RuntimeHealthClassification,
    StrategyDiagnosticsV1SystemHealthApplication,
    SystemHealthAffectedScope,
    SystemHealthContext,
    SystemHealthErrorCode,
    SystemHealthPresentationState,
    SystemHealthRecoveryExpectation,
)
from app.event_bridge import EventBridge
from strategy_diagnostics import create_diagnostics_application
from strategy_diagnostics.reproduction import REPRODUCTION_MANIFEST_SCHEMA_VERSION


NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


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
        "read_runtime_health",
        "read_persistence_health",
        "read_version_health",
    }


def test_runtime_health_application_redacts_raw_failure_details(caplog) -> None:
    class _ThrowingApplication:
        def status(self) -> object:
            raise OSError(
                r"C:\secrets\runtime.exe --token super-secret SELECT * FROM users"
            )

    result = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        _ThrowingApplication(),  # type: ignore[arg-type]
        clock=lambda: NOW,
    ).read_runtime_health()

    assert result.availability is RuntimeHealthApplicationAvailability.FAILED
    assert result.error is not None
    assert result.error.code is RuntimeHealthApplicationErrorCode.READ_FAILED
    exposed = result.error.explanation.casefold()
    for forbidden in ("c:\\", "runtime.exe", "token", "secret", "select", "users"):
        assert forbidden not in exposed
        assert forbidden not in caplog.text.casefold()


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
    application = create_diagnostics_application()
    application.start()
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
    application = create_diagnostics_application()
    application.start()

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
    application = create_diagnostics_application()
    application.start()
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'release-binding-missing.sqlite3'}"
    )
    application.initialize_persistence(engine)
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
    application = create_diagnostics_application()
    application.start()
    application.initialize_persistence(engine)
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
    application = create_diagnostics_application()
    application.start()
    report = application.initialize_persistence(engine)
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
        now[0] += timedelta(seconds=6)
        stale = feature.snapshot(SystemHealthContext())
        assert stale.presentation is SystemHealthPresentationState.STALE

        bridge.mark_reconnected()
        assert any(
            state.presentation is SystemHealthPresentationState.RECOVERING
            for state in observed
        )
        assert observed[-1].presentation is SystemHealthPresentationState.RECOVERED
    finally:
        subscription.dispose()
        feature.close()
        engine.dispose()
