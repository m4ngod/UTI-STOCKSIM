from __future__ import annotations

from dataclasses import fields
import json
from pathlib import Path

from stock_sim.release.frontend_v2_package_entry import (
    ACTIVE_JOURNEY_ROUTES,
    PRODUCTION_PATH,
    PackageSmokeResult,
    _run_installed_migration_report,
)
from stock_sim.release.frontend_v2_packaging import (
    CLEAN_ROOM_REPORT_SCHEMA_VERSION,
    load_toolchain_lock,
)
from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
    create_sealed_wave2_release_input_fixture,
    write_sealed_wave2_release_input_fixture_archive,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]


EXPECTED_PRODUCTION_DEPENDENCIES = {
    "PySide6": "6.9.1",
    "PySide6-Addons": "6.9.1",
    "PySide6-Essentials": "6.9.1",
    "SQLAlchemy": "2.0.49",
    "asn1crypto": "1.5.1",
    "duckdb": "1.5.4",
    "greenlet": "3.4.0",
    "numpy": "2.3.1",
    "pg8000": "1.31.5",
    "psycopg": "3.2.9",
    "psycopg-binary": "3.2.9",
    "pydantic": "1.10.26",
    "pyqtgraph": "0.13.7",
    "python-dateutil": "2.9.0.post0",
    "redis": "7.4.0",
    "scramp": "1.4.8",
    "shiboken6": "6.9.1",
    "six": "1.17.0",
    "typing-extensions": "4.15.0",
    "tzdata": "2025.2",
}
EXPECTED_BUILD_DEPENDENCIES = {
    "Nuitka": "2.6.8",
    "ordered-set": "4.1.0",
    "zstandard": "0.25.0",
}
SOURCE_COMMIT = "a" * 40


def test_issue_118_lock_captures_the_complete_production_and_build_closure():
    lock = load_toolchain_lock()

    assert lock.schema_version == 2
    assert lock.production_dependencies == EXPECTED_PRODUCTION_DEPENDENCIES
    assert lock.build_dependencies == EXPECTED_BUILD_DEPENDENCIES

    payload = json.loads(
        (
            PROJECT_ROOT
            / "stock_sim"
            / "release"
            / "frontend_v2_toolchain.lock.json"
        ).read_text(encoding="utf-8")
    )
    assert payload["production_dependencies"] == (
        EXPECTED_PRODUCTION_DEPENDENCIES
    )
    assert payload["build_dependencies"] == EXPECTED_BUILD_DEPENDENCIES


def test_issue_118_installed_journey_contract_covers_six_live_features():
    assert ACTIVE_JOURNEY_ROUTES == (
        "strategy_library",
        "scenario_lab",
        "diagnostic_tasks",
        "run_monitoring",
        "evidence_and_findings",
        "system_health",
    )
    assert PRODUCTION_PATH[-3:] == (
        "LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter",
        "LiveSystemHealthAdapter",
        "JourneyWorkspaceHost",
    )

    result_fields = {item.name for item in fields(PackageSmokeResult)}
    assert {
        "queued_state_observed",
        "running_state_observed",
        "partial_state_observed",
        "controlled_failure_observed",
        "safe_failure_reason_verified",
        "retry_idempotency_verified",
        "duplicate_work_count",
        "terminal_completion_observed",
        "system_health_context_verified",
        "system_health_identity_graph",
        "system_health_accessibility_verified",
        "focus_restoration_verified",
        "accessibility_checkpoints",
        "installed_accessibility_verified",
        "no_color_only_meaning_verified",
        "chart_narrative_table_revision_verified",
        "manual_trading_route_audits",
    }.issubset(result_fields)


def test_issue_118_supported_data_copy_never_queries_storage_directly():
    source = (
        PROJECT_ROOT
        / "stock_sim"
        / "release"
        / "wave4_supported_data_copy.py"
    ).read_text(encoding="utf-8")

    assert "strategy_run_status" in source
    assert "from sqlalchemy" not in source
    assert ".connect()" not in source
    assert "diagnostic_run_orders" not in source


def test_issue_118_clean_room_contract_is_installed_schema_four():
    assert CLEAN_ROOM_REPORT_SCHEMA_VERSION == 4

    packaging_source = (
        PROJECT_ROOT
        / "stock_sim"
        / "release"
        / "frontend_v2_packaging.py"
    ).read_text(encoding="utf-8")
    clean_room_source = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
    ).read_text(encoding="utf-8")
    performance_source = (
        PROJECT_ROOT
        / "stock_sim"
        / "release"
        / "frontend_v2_performance_runtime.py"
    ).read_text(encoding="utf-8")
    sandbox_source = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_windows_sandbox.ps1"
    ).read_text(encoding="utf-8")

    for required in (
        "installed_performance",
        "fresh_install_migration",
        "copied_wave3_migration",
        "candidate_widgets_candidate_rollback",
        "observation_ledger_readiness",
    ):
        assert required in packaging_source
        assert required in clean_room_source

    assert "--performance-report" in clean_room_source
    assert '$rollbackLanes[$lane] = Invoke-InstalledRollbackLane' in (
        clean_room_source
    )
    assert "$candidateBeforePath" not in clean_room_source
    assert 'foreach ($lane in @("hardware", "software"))' in (
        clean_room_source
    )
    assert "DeterministicFakeStrategyLibraryAdapter" not in performance_source
    assert "DeterministicFakeScenarioLabAdapter" not in performance_source
    assert "DeterministicFakeDiagnosticTasksAdapter" not in performance_source
    for required_accessibility_probe in (
        "UIAutomationClient",
        "Narrator.exe",
        "TextScaleFactor",
        "LogPixels",
        "Graphics]::FromHwnd",
        "observed_window_dpi_x -ge 192",
        "InvokePattern",
        "TogglePattern",
        "SelectionItemPattern",
        "ValuePattern",
        "forbidden_action_count",
        "UTI_STOCKSIM_UIA_CHECKPOINT_ACK_DIR",
        "installedAccessibilityCheckpointMarker",
        "lifecycle_state_observed",
    ):
        assert required_accessibility_probe in clean_room_source
    assert "<AudioOutput>Disable</AudioOutput>" in sandbox_source


def test_issue_118_installed_migration_modes_use_real_public_persistence(
    tmp_path,
):
    fixture_root = tmp_path / "sealed-wave3"
    fixture_archive = tmp_path / "sealed-wave3.zip"
    create_sealed_wave2_release_input_fixture(
        bundle_root=fixture_root,
        source_commit=SOURCE_COMMIT,
    )
    write_sealed_wave2_release_input_fixture_archive(
        bundle_root=fixture_root,
        archive_path=fixture_archive,
    )

    for kind in ("fresh", "copied-wave3"):
        report_path = tmp_path / f"{kind}.json"
        assert _run_installed_migration_report(
            report_path=report_path,
            migration_kind=kind,
            work_root=tmp_path / f"{kind}-work",
            source_commit=SOURCE_COMMIT,
            fixture_archive_path=fixture_archive,
        ) == 0
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["passed"] is True
        assert report["schema_migration_verified"] is True
        assert report["bookmark_migration_verified"] is True
        assert report["deterministic"] is True
        assert report["idempotent"] is True
        assert report["identity_retention_verified"] is True
        assert report["reopen_verified"] is True
        assert report["destructive_migration"] is False
        assert report["clean_exit"] is True
        assert report["source_schema_revision"] == report["target_schema_revision"]
        assert report["first_reopen_applied_revisions"] == []
        assert report["second_reopen_applied_revisions"] == []
        if kind == "fresh":
            assert report["initial_applied_revisions"]
            assert report["initial_applied_revisions"][-1] == (
                report["target_schema_revision"]
            )
            assert report["initial_file_inventory"] == (
                report["final_file_inventory"]
            )
        else:
            assert report["initial_applied_revisions"] == []
