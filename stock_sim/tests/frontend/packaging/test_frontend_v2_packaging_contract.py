import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, replace

import pytest

from stock_sim.release.frontend_v2_packaging import (
    EXPECTED_TOOLCHAIN,
    PROJECT_QML_ROOT,
    PROJECT_ROOT,
    AccessibilityGateEvidence,
    LockedPlatform,
    MandatoryReleaseGateEvidence,
    PackageKind,
    PerformanceGateEvidence,
    SafetyGateEvidence,
    audit_frontend_v2_surface,
    audit_nuitka_dependency_report,
    audit_packaged_formal_strategy_sources,
    certify_frontend_v2_release,
    classify_windows_operating_system,
    create_deterministic_package_archive,
    create_package_build_plans,
    deploy_scanned_qml_runtime,
    load_toolchain_lock,
    resolve_qml_dependency_closure,
    scan_qml_dependencies,
    toolchain_evidence_identity,
    verify_clean_room_report,
    verify_release_source,
    verify_running_toolchain,
    write_package_evidence,
    write_renderer_evidence,
)
from stock_sim.release.frontend_v2_packaging import (
    main as packaging_main,
)
from stock_sim.release.no_manual_trading_gate import (
    POLICY_VERSION,
    REQUIRED_GATE_SURFACES,
    audit_no_manual_trading_gate,
)
from strategy_diagnostics.formal_strategy_sources import (
    FORMAL_STRATEGY_SOURCE_BINDINGS,
)

_CLEAN_ROOM_JOURNEY = (
    (
        "launched_terminal_run",
        "run_monitoring",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "terminal_evidence",
        "evidence_and_findings",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "disconnected_run",
        "run_monitoring",
        "terminal",
        "ready",
        "disconnected",
        "fresh",
    ),
    (
        "disconnected_evidence",
        "evidence_and_findings",
        "terminal",
        "ready",
        "disconnected",
        "disconnected",
    ),
    (
        "reconnected_pending_run",
        "run_monitoring",
        "terminal",
        "ready",
        "stale",
        "stale",
    ),
    (
        "reconnected_pending_evidence",
        "evidence_and_findings",
        "terminal",
        "ready",
        "stale",
        "stale",
    ),
    (
        "reconnected_terminal_run",
        "run_monitoring",
        "terminal",
        "ready",
        "fresh",
        "stale",
    ),
    (
        "reconnected_evidence",
        "evidence_and_findings",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "remounted_terminal_run",
        "run_monitoring",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "remounted_terminal_evidence",
        "evidence_and_findings",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
)
_CLEAN_ROOM_IDENTITY_SETS = {
    "candidates": ["candidate-1"],
    "metrics": ["metric-1"],
    "comparisons": ["comparison-1"],
    "curves": ["curve-1"],
    "breakpoints": ["breakpoint-1"],
    "findings": ["finding-1"],
}
_CLEAN_ROOM_MANIFEST_IDENTITIES = ["RM-RC-001", "RM-RC-002"]
_CLEAN_ROOM_RUN_IDENTITIES = ["RUN-RC-001", "RUN-RC-002"]
_CLEAN_ROOM_RAW_ARTIFACT_HASHES = ["a" * 64, "b" * 64]
_CLEAN_ROOM_IDENTITY_GRAPH = sorted(
    {
        "FDC-RC-001",
        "CASE-RC-001",
        "RUN-RC-001",
        "STRATEGY-RC-001",
        "RECIPE-RC-001",
        "EVIDENCE-RC-001",
        "RM-RC-001",
        "DT-RC-001",
        "TASK-HANDLE-CREATE-RC-001",
        "TASK-HANDLE-VALIDATE-RC-001",
        "TASK-HANDLE-START-RC-001",
        *_CLEAN_ROOM_MANIFEST_IDENTITIES,
        *_CLEAN_ROOM_RUN_IDENTITIES,
        *_CLEAN_ROOM_RAW_ARTIFACT_HASHES,
        *(
            identity
            for identities in _CLEAN_ROOM_IDENTITY_SETS.values()
            for identity in identities
        ),
    }
)
_REQUIRED_QML_DEPENDENCY_MODULES = (
    "_duckdb",
    "app.features.live_strategy_library",
    "app.features.live_scenario_lab",
    "app.features.live_strategy_diagnostics_v1_application",
    "app.features.strategy_library_application",
    "app.features.scenario_lab_application",
    "duckdb",
    "persistence.models_training",
    "sqlalchemy.dialects.sqlite.pysqlite",
    "stock_sim.release.strategy_diagnostics_v1_release_fixture",
    "strategy_diagnostics.application",
    "strategy_diagnostics.diagnostic_evidence_storage",
    "strategy_diagnostics.live_minute_scenario_native_strategy",
    "strategy_diagnostics.market_paths",
    "strategy_diagnostics.persistence",
    "strategy_diagnostics.quentx_scenario_native_strategy",
    "strategy_diagnostics.strategy_inventory",
)


def _reopened_setup_ledger(
    drafts,
    validations,
    recipes,
    handles,
    paths,
    cases,
    *,
    formal_set="SCENARIO-SET-RC-001",
    scenario_selection="SCENARIO-SELECTION-RC-001",
    strategy_selection="STRATEGY-SELECTION-RC-001",
    setup_selection="SETUP-SELECTION-RC-001",
):
    return {
        "recipe_drafts": tuple(sorted(drafts)),
        "recipe_validations": tuple(sorted(validations)),
        "approved_recipes": tuple(sorted(recipes)),
        "materialization_task_handles": tuple(sorted(handles)),
        "materialized_paths": tuple(sorted(paths)),
        "materialized_scenarios": tuple(sorted(cases)),
        "draft_validation_approval_bindings": tuple(sorted(
            "|".join(values)
            for values in zip(drafts, validations, recipes, strict=True)
        )),
        "materialization_bindings": tuple(sorted(
            "|".join(values)
            for values in zip(recipes, handles, paths, strict=True)
        )),
        "campaign_case_bindings": tuple(sorted(
            "|".join(values)
            for values in zip(recipes, paths, cases, strict=True)
        )),
        "formal_scenario_sets": (formal_set,),
        "scenario_selection_contexts": (scenario_selection,),
        "scenario_selection_set_bindings": (
            f"{scenario_selection}|{formal_set}",
        ),
        "strategy_selection_contexts": (strategy_selection,),
        "setup_selection_contexts": (setup_selection,),
        "task_scenario_selection_contexts": (scenario_selection,),
    }
_REQUIRED_QML_FORMAL_STRATEGY_SOURCE_FILES = (
    (
        "strategy_diagnostics/formal_sources/"
        "live_minute_scenario_native_strategy.py.txt"
    ),
    (
        "strategy_diagnostics/formal_sources/"
        "quentx_scenario_native_strategy.py.txt"
    ),
)


def _nuitka_report_xml(
    *module_names,
    data_files=_REQUIRED_QML_FORMAL_STRATEGY_SOURCE_FILES,
):
    modules = "".join(
        f'<module name="{module_name}" />'
        for module_name in module_names
    )
    retained_data_files = "".join(
        f'<data_file name="{relative_path}" />'
        for relative_path in data_files
    )
    return (
        '<nuitka-compilation-report mode="standalone" completion="yes">'
        f"{modules}{retained_data_files}</nuitka-compilation-report>"
    )


def _write_bound_formal_strategy_sources(distribution_dir):
    for binding in FORMAL_STRATEGY_SOURCE_BINDINGS.values():
        destination = distribution_dir / binding.packaged_relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            (PROJECT_ROOT / binding.source_relative_path).read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )


def _write_clean_room_screenshots(root, lane):
    screenshots = []
    lane_dir = root / lane
    lane_dir.mkdir(parents=True, exist_ok=True)
    for stage, *_ in _CLEAN_ROOM_JOURNEY:
        relative_path = f"{lane}/{stage}.png"
        screenshot_path = root / relative_path
        screenshot_path.write_bytes(f"{lane}:{stage}".encode())
        screenshots.append(
            {
                "stage": stage,
                "relative_path": relative_path,
                "sha256": (
                    "sha256:"
                    + hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
                ),
            }
        )
    return screenshots


def _clean_room_lane(root, lane, graphics_api):
    installed_recipe_drafts = [
        f"RECIPE-DRAFT-RC-{index:03d}" for index in range(1, 15)
    ]
    installed_recipe_validations = [
        f"RECIPE-VALIDATION-RC-{index:03d}" for index in range(1, 15)
    ]
    installed_approved_recipes = [
        f"RECIPE-RC-{index:03d}" for index in range(1, 15)
    ]
    installed_materialization_handles = [
        f"MATERIALIZATION-TASK-RC-{index:03d}"
        for index in range(1, 15)
    ]
    installed_paths = [f"{index:064x}" for index in range(1, 15)]
    installed_scenarios = [
        f"CAMPAIGN-CASE-RC-{index:03d}" for index in range(1, 15)
    ]
    installed_identity_graph = sorted(
        {*_CLEAN_ROOM_IDENTITY_GRAPH, *installed_paths}
    )
    return {
        "exit_code": 0,
        "graphics_api": graphics_api,
        "source_commit": "abc123",
        "production_path": [
            "DiagnosticsApplication",
            "FileBackedV1Persistence",
            "LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter",
            "LiveStrategyLibraryAdapter",
            "LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter",
            "LiveScenarioLabAdapter",
            "LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter",
            "LiveDiagnosticTasksAdapter",
            "LiveStrategyDiagnosticsV1ApplicationAdapter",
            "EventBridge",
            "LiveRunMonitoringAdapter",
            "LiveEvidenceAndFindingsAdapter",
            "JourneyWorkspaceHost",
        ],
        "fixture_kind": "authoritative_writable_wave3_inputs",
        "strategy_selection_created_after_install": True,
        "recipe_draft_created_after_install": True,
        "recipe_validation_created_after_install": True,
        "recipe_approval_created_after_install": True,
        "reference_path_materialized_after_install": True,
        "scenario_set_created_after_install": True,
        "scenario_selection_created_after_install": True,
        "strategy_selection_context_identity": "STRATEGY-SELECTION-RC-001",
        "recipe_draft_identity": installed_recipe_drafts[0],
        "recipe_validation_identity": installed_recipe_validations[0],
        "materialization_task_handle_identity": (
            installed_materialization_handles[0]
        ),
        "materialized_path_identity": installed_paths[0],
        "materialized_scenario_identity": installed_scenarios[0],
        "terminal_campaign_case_identity": "CASE-RC-001",
        "terminal_selected_campaign_case_identity": installed_scenarios[0],
        "terminal_node_market_scenario_identity": installed_paths[0],
        "terminal_campaign_node_lifecycle": "completed",
        "terminal_case_manifest_binding_verified": True,
        "installed_setup_ledger_reopened": True,
        "reopened_installed_setup_ledger": _reopened_setup_ledger(
            installed_recipe_drafts,
            installed_recipe_validations,
            installed_approved_recipes,
            installed_materialization_handles,
            installed_paths,
            installed_scenarios,
        ),
        "formal_scenario_set_identity": "SCENARIO-SET-RC-001",
        "scenario_selection_context_identity": "SCENARIO-SELECTION-RC-001",
        "setup_selection_context_identity": "SETUP-SELECTION-RC-001",
        "installed_setup_command_kinds": [
            "compare_formal_strategy_set",
            "select_formal_strategy_set",
            "create_recipe_draft",
            "validate_recipe_draft",
            "approve_recipe",
            "materialize_reference_path",
            "compose_formal_scenario_set",
            "resolve_execution_assumptions",
            "select_formal_scenario_set",
        ],
        "installed_recipe_draft_identities": installed_recipe_drafts,
        "installed_recipe_validation_identities": (
            installed_recipe_validations
        ),
        "installed_approved_recipe_identities": installed_approved_recipes,
        "installed_materialization_task_handle_identities": (
            installed_materialization_handles
        ),
        "installed_materialized_path_identities": installed_paths,
        "installed_materialized_scenario_identities": installed_scenarios,
        "task_created_after_install": True,
        "campaign_created_after_install": True,
        "diagnostic_task_identity": "DT-RC-001",
        "accepted_command_kinds": [
            "create_diagnostic_task",
            "revise_configuration",
            "validate_configuration",
            "approve_configuration",
            "start_formal_diagnostic_campaign",
        ],
        "task_handle_identities": [
            "TASK-HANDLE-CREATE-RC-001",
            "TASK-HANDLE-VALIDATE-RC-001",
            "TASK-HANDLE-START-RC-001",
        ],
        "writable_persistence_verified": True,
        "application_reopened": True,
        "background_continuation_verified": True,
        "task_cancel_order_isolation_verified": True,
        "campaign_identity": "FDC-RC-001",
        "case_identity": "CASE-RC-001",
        "run_identity": "RUN-RC-001",
        "strategy_identity": "STRATEGY-RC-001",
        "approved_recipe_identity": "RECIPE-RC-001",
        "evidence_package_identity": "EVIDENCE-RC-001",
        "reproduction_manifest_identity": "RM-RC-001",
        "artifact_hashes": ["sha256:" + "a" * 64],
        "persistence_kind": "sqlite+json+parquet",
        "persistence_reopened": True,
        "application_read_model_interface": (
            "StrategyDiagnosticsV1ApplicationReadModel/1.0"
        ),
        "active_feature_interfaces": [
            "StrategyLibraryFeature/1.0",
            "ScenarioLabFeature/1.0",
            "DiagnosticTasksFeature/1.0",
            "RunMonitoringFeature/1.2",
            "EvidenceAndFindingsFeature/1.1",
        ],
        "campaign_status": "completed",
        "run_status": "completed",
        "evidence_status": "sealed",
        "expected_identity_graph": installed_identity_graph,
        "feature_identity_graph": installed_identity_graph,
        "qml_identity_graph_checkpoints": {
            stage: installed_identity_graph
            for stage, *_ in _CLEAN_ROOM_JOURNEY
        },
        "evidence_identity_sets": _CLEAN_ROOM_IDENTITY_SETS,
        "persisted_manifest_identities": (
            _CLEAN_ROOM_MANIFEST_IDENTITIES
        ),
        "persisted_run_identities": _CLEAN_ROOM_RUN_IDENTITIES,
        "raw_artifact_hashes": [
            *_CLEAN_ROOM_RAW_ARTIFACT_HASHES,
            *installed_paths,
        ],
        "keyboard_navigation_verified": True,
        "accessibility_preferences_verified": True,
        "accessibility_announcements": [
            "Run Monitoring disconnected",
            "Evidence and Findings disconnected",
            "Run Monitoring fresh",
            "Evidence and Findings fresh",
        ],
        "old_generation_rejected": True,
        "authoritative_reconnect_verified": True,
        "routes_rendered": [
            "strategy_library",
            "scenario_lab",
            "diagnostic_tasks",
            "run_monitoring",
            "evidence_and_findings",
        ],
        "connection_transitions": [
            "connected",
            "disconnected",
            "reconnected",
            "remounted",
            "closed",
        ],
        "observations": [
            {
                "stage": stage,
                "route": route,
                "run_state": run_state,
                "evidence_state": evidence_state,
                "run_freshness": run_freshness,
                "evidence_freshness": evidence_freshness,
            }
            for (
                stage,
                route,
                run_state,
                evidence_state,
                run_freshness,
                evidence_freshness,
            ) in _CLEAN_ROOM_JOURNEY
        ],
        "screenshots": _write_clean_room_screenshots(root, lane),
        "screenshots_distinct": True,
        "manual_trading_action_count": 0,
        "read_only_context_visible": True,
        "clean_exit": True,
        "errors": [],
    }


def test_exact_frontend_v2_toolchain_lock_matches_the_running_build_environment():
    lock = load_toolchain_lock()

    assert lock.toolchain == EXPECTED_TOOLCHAIN
    assert lock.toolchain.python == "3.11.9"
    assert lock.toolchain.pyside6 == "6.9.1"
    assert lock.toolchain.qt == "6.9.1"
    assert lock.toolchain.numpy == "2.3.1"
    assert lock.toolchain.nuitka == "2.6.8"
    assert lock.invalidation_policy == (
        "Any locked dependency version change invalidates all affected "
        "packaging and performance evidence."
    )
    assert verify_running_toolchain(lock) == ()
    assert toolchain_evidence_identity(lock).startswith("sha256:")


def test_toolchain_lock_rejects_a_different_build_architecture():
    lock = load_toolchain_lock()
    wrong_architecture = replace(
        lock,
        platform=LockedPlatform(
            operating_system=lock.platform.operating_system,
            architecture="arm64",
        ),
    )

    assert "architecture: expected arm64, observed x86_64" in (
        verify_running_toolchain(wrong_architecture)
    )


def test_windows_platform_lock_does_not_accept_server_builds():
    assert classify_windows_operating_system(
        build=26100,
        product_type=1,
    ) == "Windows 11"
    assert classify_windows_operating_system(
        build=26100,
        product_type=3,
    ) == "Windows Server"


def test_toolchain_lock_is_included_in_installed_release_package_data():
    import tomllib

    metadata = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert metadata["tool"]["setuptools"]["package-data"][
        "stock_sim.release"
    ] == ["*.json"]


def test_windows_offline_package_declares_binary_postgresql_driver():
    import tomllib

    metadata = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert "psycopg[binary]>=3.1" in metadata["project"]["dependencies"]


def test_integration_release_notes_keep_later_modules_and_waves_incomplete():
    release_notes = (
        PROJECT_ROOT
        / "docs"
        / "testing"
        / "frontend"
        / "strategy-diagnostics-v1-frontend-v2-integration-release.md"
    ).read_text(encoding="utf-8")

    assert "Integration Contract Vertical Slice" in release_notes
    assert "`RunMonitoringFeature` 1.2" in release_notes
    assert "`EvidenceAndFindingsFeature` 1.1" in release_notes
    assert "`DiagnosticTasksFeature` 1.0 is active" in release_notes
    assert "not an installed Wave 2 release-certification claim" in release_notes
    assert "Strategy Library is not complete" in release_notes
    assert "Scenario Lab is not complete" in release_notes
    assert "System Health is not complete" in release_notes
    assert "Waves 3–4 are not complete" in release_notes
    assert "manual trading" in release_notes.casefold()
    assert "HTTP" in release_notes
    assert "Widgets rollback" in release_notes


def test_qml_dependencies_are_discovered_from_source_imports_not_a_handwritten_list(
    tmp_path,
):
    fixture_root = tmp_path / "qml"
    fixture_root.mkdir()
    (fixture_root / "Fixture.qml").write_text(
        "import QtQuick 2.15\n"
        "import QtQuick.Dialogs 6.9\n"
        "Item {}\n",
        encoding="utf-8",
    )

    fixture_manifest = scan_qml_dependencies(fixture_root)
    project_manifest = scan_qml_dependencies(PROJECT_QML_ROOT)

    assert tuple(
        (dependency.module, dependency.version)
        for dependency in fixture_manifest.dependencies
    ) == (
        ("QtQuick", "2.15"),
        ("QtQuick.Dialogs", "6.9"),
    )
    assert fixture_manifest.scan_kind == "qml-source-import-scan"
    assert fixture_manifest.source_digest.startswith("sha256:")
    assert {
        (dependency.module, dependency.version)
        for dependency in project_manifest.dependencies
    } == {
        ("QtQuick", "2.15"),
        ("QtQuick.Controls", "2.15"),
        ("QtQuick.Layouts", "1.15"),
    }
    assert not any(
        dependency.module.startswith("QtWebEngine")
        for dependency in project_manifest.dependencies
    )


def test_qt_qmlimportscanner_resolves_the_transitive_qml_dependency_closure():
    closure = resolve_qml_dependency_closure(PROJECT_QML_ROOT)

    names = {dependency.name for dependency in closure.dependencies}
    assert "QtQuick" in names
    assert "QtQuick.Layouts" in names
    assert "QtQml" in names
    assert not any(
        name.startswith(("QtWebEngine", "QtWebView"))
        for name in names
    )
    assert closure.scanner == "pyside6-qmlimportscanner"
    assert closure.raw_output_digest.startswith("sha256:")


def test_package_smoke_observes_the_complete_production_journey(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QT_QUICK_BACKEND", "software")
    from stock_sim.release.frontend_v2_package_entry import (
        RendererLane,
        run_smoke_journey,
    )

    result = run_smoke_journey(
        report_dir=tmp_path,
        renderer_lane=RendererLane.SOFTWARE,
        capture_images=False,
    )

    assert tuple(
        observation.stage for observation in result.observations
    ) == tuple(stage for stage, *_ in _CLEAN_ROOM_JOURNEY)
    assert tuple(
        observation.run_freshness for observation in result.observations
    )[2:4] == (
        "disconnected",
        "disconnected",
    )
    assert result.observations[-1].headline == (
        "Strategy Run reached a terminal state"
    )
    assert result.errors == ()
    assert result.clean_exit is True


def test_minimal_package_smoke_captures_distinct_software_frames(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QT_QUICK_BACKEND", "software")
    from stock_sim.release.frontend_v2_package_entry import (
        RendererLane,
        run_smoke_journey,
    )

    result = run_smoke_journey(
        report_dir=tmp_path,
        renderer_lane=RendererLane.SOFTWARE,
        capture_images=True,
    )

    screenshot_digests = {
        observation.stage: hashlib.sha256(
            (tmp_path / observation.screenshot).read_bytes()
        ).digest()
        for observation in result.observations
        if observation.screenshot is not None
    }
    assert len(result.observations) == len(_CLEAN_ROOM_JOURNEY)
    # A sealed Formal Campaign is terminal from launch. Reconnect and remount
    # must reproduce the same trustworthy view, while each route still proves
    # a visually distinct connected and disconnected state.
    assert len(screenshot_digests) == len(_CLEAN_ROOM_JOURNEY)
    assert (
        screenshot_digests["launched_terminal_run"]
        != screenshot_digests["disconnected_run"]
    )
    assert (
        screenshot_digests["terminal_evidence"]
        != screenshot_digests["disconnected_evidence"]
    )


def test_qml_smoke_capture_renders_the_quick_framebuffer(tmp_path):
    from stock_sim.release.frontend_v2_package_entry import (
        _capture_qml_frame,
    )

    class CapturedImage:
        def __init__(self) -> None:
            self.saved_to = None

        def isNull(self) -> bool:  # noqa: N802 - Qt API convention
            return False

        def save(self, path: str, image_format: str) -> bool:
            self.saved_to = (path, image_format)
            return True

    class QuickHost:
        def __init__(self) -> None:
            self.image = CapturedImage()
            self.framebuffer_grabs = 0

        def grab(self):
            raise AssertionError("QWidget.grab() can return a stale QML frame")

        def grabFramebuffer(self):  # noqa: N802 - Qt API convention
            self.framebuffer_grabs += 1
            return self.image

    host = QuickHost()
    screenshot_path = tmp_path / "empty.png"

    _capture_qml_frame(host, screenshot_path)

    assert host.framebuffer_grabs == 1
    assert host.image.saved_to == (str(screenshot_path), "PNG")


def test_build_plans_share_one_commit_and_exclude_webengine_by_construction(
    tmp_path,
):
    plans = create_package_build_plans(
        output_root=tmp_path,
        source_commit="abc123",
    )

    assert tuple(plan.kind for plan in plans) == (
        PackageKind.WIDGETS_ROLLBACK,
        PackageKind.QML_JOURNEY,
    )
    assert {plan.source_commit for plan in plans} == {"abc123"}
    qml_plan = plans[1]
    widgets_plan = plans[0]
    assert qml_plan.source_imports == scan_qml_dependencies(PROJECT_QML_ROOT)
    assert qml_plan.resolved_qml_dependencies is not None
    assert "--standalone" in qml_plan.nuitka_command
    assert "--enable-plugin=pyside6" in qml_plan.nuitka_command
    assert any(
        argument.startswith("--include-data-dir=")
        for argument in qml_plan.nuitka_command
    )
    assert {
        "--include-module=stock_sim.release.strategy_diagnostics_v1_release_fixture",
        "--include-module=app.features.live_strategy_diagnostics_v1_application",
        "--include-module=strategy_diagnostics.application",
        "--include-module=strategy_diagnostics.persistence",
        "--include-module=strategy_diagnostics.market_paths",
        "--include-module=strategy_diagnostics.diagnostic_evidence_storage",
        "--include-module=strategy_diagnostics.quentx_scenario_native_strategy",
        "--include-module=strategy_diagnostics.live_minute_scenario_native_strategy",
        (
            "--include-data-files="
            f"{PROJECT_ROOT / 'strategy_diagnostics' / 'quentx_scenario_native_strategy.py'}"
            "=strategy_diagnostics/formal_sources/"
            "quentx_scenario_native_strategy.py.txt"
        ),
        (
            "--include-data-files="
            f"{PROJECT_ROOT / 'strategy_diagnostics' / 'live_minute_scenario_native_strategy.py'}"
            "=strategy_diagnostics/formal_sources/"
            "live_minute_scenario_native_strategy.py.txt"
        ),
        "--include-module=sqlalchemy.dialects.sqlite.pysqlite",
        "--include-package=duckdb",
        "--include-module=_duckdb",
    } <= set(qml_plan.nuitka_command)
    assert not any(
        "webengine" in argument.casefold()
        for plan in plans
        for argument in plan.nuitka_command
    )
    assert widgets_plan.resolved_qml_dependencies is None
    assert {
        "--include-package=psycopg",
        "--include-package=psycopg_binary",
    } <= set(widgets_plan.nuitka_command)


def test_qml_build_plan_keeps_app_context_but_excludes_legacy_and_network_namespaces(
    tmp_path,
):
    qml_plan = create_package_build_plans(
        output_root=tmp_path,
        source_commit="abc123",
    )[1]

    excluded = {
        argument.removeprefix("--nofollow-import-to=")
        for argument in qml_plan.nuitka_command
        if argument.startswith("--nofollow-import-to=")
    }

    assert "app.app_context" not in excluded
    assert {
        "app.legacy_panel_context",
        "app.controllers",
        "app.panels",
        "app.runtime_gateway",
        "app.services",
        "app.ui.adapters",
        "app.services.redis_subscriber",
        "aiohttp",
        "core.order",
        "httpx",
        "redis",
        "requests",
        "services.order_service",
        "services.runtime_command_service",
        "stock_sim.core.order",
        "stock_sim.services.order_service",
        "stock_sim.services.runtime_command_service",
        "urllib3",
        "websockets",
    } <= excluded


def test_widgets_build_plan_excludes_new_v1_seam_and_network_namespaces(
    tmp_path,
):
    widgets_plan = create_package_build_plans(
        output_root=tmp_path,
        source_commit="abc123",
    )[0]

    excluded = {
        argument.removeprefix("--nofollow-import-to=")
        for argument in widgets_plan.nuitka_command
        if argument.startswith("--nofollow-import-to=")
    }

    assert {
        "app.app_context",
        "app.event_bridge",
        "app.features",
        "app.services.redis_subscriber",
        "aiohttp",
        "httpx",
        "redis",
        "requests",
        "urllib3",
        "websockets",
    } <= excluded


def test_scanner_driven_qml_deployment_copies_modules_and_binary_closure(
    tmp_path,
):
    qml_plan = create_package_build_plans(
        output_root=tmp_path,
        source_commit="abc123",
    )[1]
    qml_plan.distribution_dir.mkdir(parents=True)

    deployment = deploy_scanned_qml_runtime(qml_plan)

    assert (
        qml_plan.distribution_dir
        / "PySide6"
        / "qml"
        / "QtQuick"
        / "Layouts"
        / "qmldir"
    ).is_file()
    assert (
        qml_plan.distribution_dir / "Qt6QuickLayouts.dll"
    ).is_file()
    assert "QtQuick.Layouts" in deployment.qml_modules
    assert not any(
        "webengine" in relative_path.casefold()
        for relative_path in deployment.deployed_files
    )


def test_package_evidence_records_checksums_sizes_delta_and_rollback(
    tmp_path,
):
    plans = create_package_build_plans(
        output_root=tmp_path / "packages",
        source_commit="abc123",
    )
    for plan in plans:
        plan.distribution_dir.mkdir(parents=True)
        (plan.distribution_dir / plan.executable_name).write_bytes(
            plan.kind.value.encode("utf-8")
        )
        report_modules = ["app.features.run_monitoring"]
        if plan.kind is PackageKind.QML_JOURNEY:
            report_modules.extend(_REQUIRED_QML_DEPENDENCY_MODULES)
        plan.nuitka_report.write_text(
            _nuitka_report_xml(*report_modules),
            encoding="utf-8",
        )
    qml_marker = (
        plans[1].distribution_dir
        / "PySide6"
        / "qml"
        / "QtQuick"
        / "qmldir"
    )
    qml_marker.parent.mkdir(parents=True)
    qml_marker.write_text("module QtQuick\n", encoding="utf-8")
    _write_bound_formal_strategy_sources(plans[1].distribution_dir)

    evidence = write_package_evidence(
        plans=plans,
        evidence_dir=tmp_path / "evidence",
    )

    assert evidence.source_commit == "abc123"
    assert evidence.qml_delta_bytes <= 50 * 1024 * 1024
    assert evidence.webengine_files == ()
    assert evidence.widgets_rollback.kind is PackageKind.WIDGETS_ROLLBACK
    assert evidence.qml_journey.kind is PackageKind.QML_JOURNEY
    assert evidence.widgets_rollback.tree_sha256.startswith("sha256:")
    assert evidence.qml_journey.tree_sha256.startswith("sha256:")
    assert {
        report.relative_path
        for report in evidence.dependency_reports
    } == {
        "qml-journey/nuitka-report.xml",
        "widgets-rollback/nuitka-report.xml",
    }
    assert {
        source.relative_path
        for source in evidence.formal_strategy_sources
    } == {
        (
            "qml-journey/frontend_v2_package_entry.dist/"
            + binding.packaged_relative_path
        )
        for binding in FORMAL_STRATEGY_SOURCE_BINDINGS.values()
    }
    manifest = tmp_path / "evidence" / "dependency-manifest.json"
    checksums = tmp_path / "evidence" / "SHA256SUMS.txt"
    assert manifest.is_file()
    assert checksums.is_file()
    assert "UTI-Widgets-Rollback.exe" in checksums.read_text(
        encoding="utf-8"
    )
    assert "UTI-Frontend-V2.exe" in checksums.read_text(
        encoding="utf-8"
    )


def test_packaged_formal_strategy_source_audit_rejects_ast_clean_tampering(
    tmp_path,
):
    distribution_dir = tmp_path / "frontend_v2_package_entry.dist"
    _write_bound_formal_strategy_sources(distribution_dir)
    assert audit_packaged_formal_strategy_sources(distribution_dir) == ()

    binding = next(iter(FORMAL_STRATEGY_SOURCE_BINDINGS.values()))
    (distribution_dir / binding.packaged_relative_path).write_text(
        "SOURCE_KIND = 'ast-clean-but-tampered'\n",
        encoding="utf-8",
    )

    assert audit_packaged_formal_strategy_sources(
        distribution_dir
    ) == (
        "Packaged audited formal strategy source digest does not match: "
        "strategy_diagnostics.quentx_scenario_native_strategy",
    )


def test_clean_room_report_requires_offline_windows_without_dev_tools(
    tmp_path,
):
    report_path = tmp_path / "clean-room-report.json"
    report_payload = {
        "schema_version": 3,
        "source_commit": "abc123",
        "archive_sha256": "sha256:package",
        "operating_system": "Microsoft Windows 11 Pro 10.0.26100",
        "architecture": "AMD64",
        "user_name": "WDAGUtilityAccount",
        "is_windows_sandbox": True,
        "network_enumeration_succeeded": True,
        "network_adapters_up": [],
        "python_on_path": False,
        "python_installations": [],
        "compiler_on_path": False,
        "compiler_installations": [],
        "dependency_cache_present": False,
        "dependency_cache_paths": [],
        "install_succeeded": True,
        "renderer_lanes": {
            lane: _clean_room_lane(tmp_path, lane, graphics_api)
            for lane, graphics_api in (
                ("hardware", "Direct3D11"),
                ("software", "Software"),
            )
        },
    }
    report_path.write_text(
        json.dumps(report_payload),
        encoding="utf-8-sig",
    )

    assert verify_clean_room_report(
        report_path,
        expected_source_commit="abc123",
        expected_archive_sha256="sha256:package",
    ) == ()

    duplicate_screenshot_report = json.loads(
        report_path.read_text(encoding="utf-8-sig")
    )
    software_screenshots = duplicate_screenshot_report["renderer_lanes"][
        "software"
    ]["screenshots"]
    software_loading = tmp_path / software_screenshots[0]["relative_path"]
    software_empty = tmp_path / software_screenshots[2]["relative_path"]
    software_empty.write_bytes(software_loading.read_bytes())
    software_screenshots[2]["sha256"] = software_screenshots[0]["sha256"]
    report_path.write_text(
        json.dumps(duplicate_screenshot_report),
        encoding="utf-8",
    )
    assert (
        "software renderer screenshots are not distinct"
        in verify_clean_room_report(
            report_path,
            expected_source_commit="abc123",
            expected_archive_sha256="sha256:package",
        )
    )

    duplicate_screenshot_report["renderer_lanes"]["software"][
        "screenshots"
    ] = _write_clean_room_screenshots(tmp_path, "software")
    duplicate_screenshot_report["renderer_lanes"]["software"][
        "screenshots"
    ][1]["sha256"] = "sha256:not-a-digest"
    report_path.write_text(
        json.dumps(duplicate_screenshot_report),
        encoding="utf-8",
    )
    assert (
        "software renderer screenshot digest is invalid"
        in verify_clean_room_report(
            report_path,
            expected_source_commit="abc123",
            expected_archive_sha256="sha256:package",
        )
    )

    duplicate_screenshot_report["renderer_lanes"]["software"][
        "screenshots"
    ] = _write_clean_room_screenshots(tmp_path, "software")
    tampered_screenshot = (
        tmp_path
        / duplicate_screenshot_report["renderer_lanes"]["software"][
            "screenshots"
        ][1]["relative_path"]
    )
    tampered_screenshot.write_bytes(b"tampered")
    report_path.write_text(
        json.dumps(duplicate_screenshot_report),
        encoding="utf-8",
    )
    assert (
        "software renderer screenshot checksum does not match"
        in verify_clean_room_report(
            report_path,
            expected_source_commit="abc123",
            expected_archive_sha256="sha256:package",
        )
    )

    duplicate_screenshot_report["renderer_lanes"]["software"][
        "screenshots"
    ] = _write_clean_room_screenshots(tmp_path, "software")
    duplicate_screenshot_report["renderer_lanes"]["software"][
        "screenshots"
    ][1]["relative_path"] = "../empty.png"
    report_path.write_text(
        json.dumps(duplicate_screenshot_report),
        encoding="utf-8",
    )
    assert (
        "software renderer screenshot path is unsafe"
        in verify_clean_room_report(
            report_path,
            expected_source_commit="abc123",
            expected_archive_sha256="sha256:package",
        )
    )

    duplicate_screenshot_report["renderer_lanes"]["software"][
        "screenshots"
    ] = _write_clean_room_screenshots(tmp_path, "software")
    missing_screenshot = (
        tmp_path
        / duplicate_screenshot_report["renderer_lanes"]["software"][
            "screenshots"
        ][1]["relative_path"]
    )
    missing_screenshot.unlink()
    report_path.write_text(
        json.dumps(duplicate_screenshot_report),
        encoding="utf-8",
    )
    assert (
        "software renderer screenshot is missing"
        in verify_clean_room_report(
            report_path,
            expected_source_commit="abc123",
            expected_archive_sha256="sha256:package",
        )
    )

    duplicate_screenshot_report["renderer_lanes"]["software"][
        "screenshots"
    ] = _write_clean_room_screenshots(tmp_path, "software")
    duplicate_screenshot_report["python_on_path"] = True
    report_path.write_text(
        json.dumps(duplicate_screenshot_report),
        encoding="utf-8",
    )
    assert "Python is available on PATH" in verify_clean_room_report(
        report_path,
        expected_source_commit="abc123",
        expected_archive_sha256="sha256:package",
    )


def test_clean_room_report_accepts_lane_local_generated_identities(tmp_path):
    hardware = _clean_room_lane(tmp_path, "hardware", "Direct3D11")
    software = _clean_room_lane(tmp_path, "software", "Software")
    software["diagnostic_task_identity"] = "DT-RC-SOFTWARE"
    software["task_handle_identities"] = [
        "TASK-HANDLE-CREATE-RC-SOFTWARE",
        "TASK-HANDLE-VALIDATE-RC-SOFTWARE",
        "TASK-HANDLE-START-RC-SOFTWARE",
    ]
    software["persisted_run_identities"] = [
        "RUN-RC-001",
        "RUN-RC-SOFTWARE",
    ]
    replacements = {
        "DT-RC-001": "DT-RC-SOFTWARE",
        "TASK-HANDLE-CREATE-RC-001": (
            "TASK-HANDLE-CREATE-RC-SOFTWARE"
        ),
        "TASK-HANDLE-VALIDATE-RC-001": (
            "TASK-HANDLE-VALIDATE-RC-SOFTWARE"
        ),
        "TASK-HANDLE-START-RC-001": (
            "TASK-HANDLE-START-RC-SOFTWARE"
        ),
        "RUN-RC-002": "RUN-RC-SOFTWARE",
    }
    software_graph = sorted(
        replacements.get(identity, identity)
        for identity in software["expected_identity_graph"]
    )
    software["expected_identity_graph"] = software_graph
    software["feature_identity_graph"] = software_graph
    software["qml_identity_graph_checkpoints"] = {
        stage: software_graph for stage, *_ in _CLEAN_ROOM_JOURNEY
    }
    report_path = tmp_path / "lane-local-clean-room-report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "source_commit": "abc123",
                "archive_sha256": "sha256:package",
                "operating_system": "Microsoft Windows 11 Pro 10.0.26100",
                "architecture": "AMD64",
                "user_name": "WDAGUtilityAccount",
                "is_windows_sandbox": True,
                "network_enumeration_succeeded": True,
                "network_adapters_up": [],
                "python_on_path": False,
                "python_installations": [],
                "compiler_on_path": False,
                "compiler_installations": [],
                "dependency_cache_present": False,
                "dependency_cache_paths": [],
                "install_succeeded": True,
                "renderer_lanes": {
                    "hardware": hardware,
                    "software": software,
                },
            }
        ),
        encoding="utf-8-sig",
    )

    assert verify_clean_room_report(
        report_path,
        expected_source_commit="abc123",
        expected_archive_sha256="sha256:package",
    ) == ()


def test_release_certification_is_blocked_until_clean_room_evidence_passes(
    tmp_path,
    monkeypatch,
):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    archives_dir = tmp_path / "archives"
    archives_dir.mkdir()
    qml_archive = archives_dir / "qml-journey-abc123.zip"
    widgets_archive = archives_dir / "widgets-rollback-abc123.zip"
    qml_archive.write_bytes(b"qml-package")
    widgets_archive.write_bytes(b"widgets-package")
    qml_sha256 = (
        "sha256:" + hashlib.sha256(qml_archive.read_bytes()).hexdigest()
    )
    widgets_sha256 = (
        "sha256:"
        + hashlib.sha256(widgets_archive.read_bytes()).hexdigest()
    )
    packages_dir = tmp_path / "packages"
    qml_distribution = (
        packages_dir
        / "qml-journey"
        / "frontend_v2_package_entry.dist"
    )
    _write_bound_formal_strategy_sources(qml_distribution)
    formal_strategy_sources = []
    for binding in FORMAL_STRATEGY_SOURCE_BINDINGS.values():
        retained_source = (
            qml_distribution / binding.packaged_relative_path
        )
        formal_strategy_sources.append(
            {
                "relative_path": (
                    retained_source.relative_to(packages_dir).as_posix()
                ),
                "size_bytes": retained_source.stat().st_size,
                "sha256": (
                    "sha256:"
                    + hashlib.sha256(
                        retained_source.read_bytes()
                    ).hexdigest()
                ),
            }
        )
    dependency_reports = []
    safe_dependency_xml_by_kind = {
        "widgets-rollback": (
            '<nuitka-compilation-report mode="standalone" '
            'completion="yes">'
            '<module name="frontend_widgets_rollback_entry" />'
            "</nuitka-compilation-report>"
        ),
        "qml-journey": _nuitka_report_xml(
            "app.features.run_monitoring",
            *_REQUIRED_QML_DEPENDENCY_MODULES,
        ),
    }
    for kind in ("widgets-rollback", "qml-journey"):
        dependency_report = packages_dir / kind / "nuitka-report.xml"
        dependency_report.parent.mkdir(parents=True, exist_ok=True)
        dependency_report.write_text(
            safe_dependency_xml_by_kind[kind],
            encoding="utf-8",
        )
        dependency_reports.append(
            {
                "relative_path": (
                    dependency_report.relative_to(packages_dir).as_posix()
                ),
                "size_bytes": dependency_report.stat().st_size,
                "sha256": (
                    "sha256:"
                    + hashlib.sha256(
                        dependency_report.read_bytes()
                    ).hexdigest()
                ),
            }
        )
    safety_evidence = asdict(
        audit_no_manual_trading_gate(
            PROJECT_ROOT,
            source_commit="abc123",
        )
    )
    (evidence_dir / "release-candidate-summary.json").write_text(
        json.dumps(
            {
                "source_commit": "abc123",
                "safety": safety_evidence,
                "packages": {
                    "dependency_reports": dependency_reports,
                    "formal_strategy_sources": formal_strategy_sources,
                },
                "archives": [
                    {
                        "relative_path": qml_archive.name,
                        "size_bytes": qml_archive.stat().st_size,
                        "sha256": qml_sha256,
                    },
                    {
                        "relative_path": widgets_archive.name,
                        "size_bytes": widgets_archive.stat().st_size,
                        "sha256": widgets_sha256,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    report = tmp_path / "clean-room-report.json"
    report.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "source_commit": "abc123",
                "archive_sha256": qml_sha256,
                "widgets_archive_sha256": widgets_sha256,
                "operating_system": "Microsoft Windows 11 Pro",
                    "architecture": "AMD64",
                    "user_name": "WDAGUtilityAccount",
                    "is_windows_sandbox": True,
                "network_enumeration_succeeded": True,
                "network_adapters_up": [],
                "python_on_path": False,
                "python_installations": [],
                "compiler_on_path": False,
                "compiler_installations": [],
                "dependency_cache_present": False,
                "dependency_cache_paths": [],
                "install_succeeded": True,
                "widgets_install_succeeded": True,
                "widgets_rollback": {
                    "exit_code": 0,
                    "source_commit": "abc123",
                    "mode": "read-only",
                    "placeholder_panels": [],
                    "real_panel_count": 8,
                    "manual_trading_action_count": 0,
                    "opened_panels": [
                        "diagnostics",
                        "market",
                        "orders",
                    ],
                    "clean_exit": True,
                    "errors": [],
                },
                "renderer_lanes": {
                    lane: _clean_room_lane(
                        tmp_path,
                        lane,
                        graphics_api,
                    )
                    for lane, graphics_api in (
                        ("hardware", "Direct3D11"),
                        ("software", "Software"),
                    )
                },
            }
        ),
        encoding="utf-8",
    )

    compromised = json.loads(report.read_text(encoding="utf-8"))
    compromised["renderer_lanes"]["software"]["errors"] = [
        "module missing"
    ]
    report.write_text(json.dumps(compromised), encoding="utf-8")
    try:
        certify_frontend_v2_release(
            output_root=tmp_path,
            source_commit="abc123",
            clean_room_report=report,
        )
    except RuntimeError as error:
        assert "software renderer reported errors" in str(error)
    else:
        raise AssertionError("Compromised clean-room evidence was accepted")
    assert not (evidence_dir / "release-summary.json").exists()

    compromised["renderer_lanes"]["software"]["errors"] = []
    report.write_text(json.dumps(compromised), encoding="utf-8")
    qml_dependency_report = (
        packages_dir / "qml-journey" / "nuitka-report.xml"
    )
    qml_dependency_report.write_text(
        (
            '<nuitka-compilation-report mode="standalone" '
            'completion="yes"><module name="services.order_service" />'
            "</nuitka-compilation-report>"
        ),
        encoding="utf-8",
    )
    try:
        certify_frontend_v2_release(
            output_root=tmp_path,
            source_commit="abc123",
            clean_room_report=report,
        )
    except RuntimeError as error:
        assert "dependency report checksum does not match" in str(error)
    else:
        raise AssertionError("Tampered dependency report was accepted")
    qml_dependency_report.write_text(
        safe_dependency_xml_by_kind["qml-journey"],
        encoding="utf-8",
    )

    retained_source = (
        qml_distribution
        / next(
            iter(FORMAL_STRATEGY_SOURCE_BINDINGS.values())
        ).packaged_relative_path
    )
    expected_source_bytes = retained_source.read_bytes()
    retained_source.write_text(
        "SOURCE_KIND = 'ast-clean-but-tampered'\n",
        encoding="utf-8",
    )
    try:
        certify_frontend_v2_release(
            output_root=tmp_path,
            source_commit="abc123",
            clean_room_report=report,
        )
    except RuntimeError as error:
        assert (
            "formal strategy source checksum does not match"
            in str(error)
        )
    else:
        raise AssertionError(
            "Tampered audited formal strategy source was accepted"
        )
    retained_source.write_bytes(expected_source_bytes)

    qml_archive.write_bytes(b"tampered")
    try:
        certify_frontend_v2_release(
            output_root=tmp_path,
            source_commit="abc123",
            clean_room_report=report,
        )
    except RuntimeError as error:
        assert "archive checksum does not match" in str(error)
    else:
        raise AssertionError("Tampered package archive was accepted")
    assert not (evidence_dir / "release-summary.json").exists()

    qml_archive.write_bytes(b"qml-package")
    report.write_text(json.dumps(compromised), encoding="utf-8-sig")
    expected_report_bytes = report.read_bytes()
    assert expected_report_bytes.startswith(b"\xef\xbb\xbf")

    def write_test_gates(**arguments):
        gate_path = (
            arguments["evidence_dir"]
            / "mandatory-release-gates.json"
        )
        gate_path.write_text("{}", encoding="utf-8")
        return MandatoryReleaseGateEvidence(
            source_commit="abc123",
            toolchain_identity="sha256:" + "1" * 64,
            accessibility=AccessibilityGateEvidence(
                issue_number=43,
                issue_url="https://example.invalid/43",
                source_commit="abc123",
                status="passed",
                test_count=10,
                junit_sha256="sha256:" + "2" * 64,
            ),
            safety=SafetyGateEvidence(
                issue_number=44,
                issue_url="https://example.invalid/44",
                source_commit="abc123",
                status="passed",
                report_sha256="sha256:" + "3" * 64,
            ),
            performance=PerformanceGateEvidence(
                issue_number=45,
                issue_url="https://example.invalid/45",
                source_commit="abc123",
                status="certified",
                fixture_archive_sha256="sha256:" + "7" * 64,
                certification_sha256="sha256:" + "4" * 64,
                hardware_report_sha256="sha256:" + "5" * 64,
                software_report_sha256="sha256:" + "6" * 64,
                safety_report_sha256="sha256:" + "3" * 64,
            ),
        )

    monkeypatch.setattr(
        "stock_sim.release.frontend_v2_packaging."
        "write_mandatory_release_gate_evidence",
        write_test_gates,
    )
    certification = certify_frontend_v2_release(
        output_root=tmp_path,
        source_commit="abc123",
        clean_room_report=report,
        accessibility_junit=tmp_path / "accessibility.xml",
        performance_evidence_dir=tmp_path / "performance",
    )

    assert certification.clean_room_report_sha256 == (
        "sha256:" + hashlib.sha256(expected_report_bytes).hexdigest()
    )
    assert (
        evidence_dir / "clean-room-report.json"
    ).read_bytes() == expected_report_bytes
    assert (evidence_dir / "release-summary.json").is_file()
    assert all(
        (evidence_dir / lane / f"{stage}.png").is_file()
        for lane in ("hardware", "software")
        for stage, *_ in _CLEAN_ROOM_JOURNEY
    )


def test_renderer_evidence_allows_lane_local_generated_identity_graphs(
    tmp_path,
):
    reports = {}
    for lane, graphics_api in (
        ("hardware", "Direct3D11"),
        ("software", "Software"),
    ):
        report_path = tmp_path / lane / "smoke-report.json"
        report_path.parent.mkdir()
        installed_recipe_drafts = [
            f"RECIPE-DRAFT-RC-{index:03d}" for index in range(1, 15)
        ]
        installed_recipe_validations = [
            f"RECIPE-VALIDATION-RC-{index:03d}"
            for index in range(1, 15)
        ]
        installed_approved_recipes = [
            f"RECIPE-RC-{index:03d}" for index in range(1, 15)
        ]
        installed_materialization_handles = [
            f"MATERIALIZATION-TASK-RC-{index:03d}"
            for index in range(1, 15)
        ]
        installed_paths = [f"{index:064x}" for index in range(1, 15)]
        installed_scenarios = [
            f"CAMPAIGN-CASE-RC-{index:03d}" for index in range(1, 15)
        ]
        installed_identity_graph = sorted(
            {*_CLEAN_ROOM_IDENTITY_GRAPH, *installed_paths}
        )
        report_path.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "source_commit": "abc123",
                    "renderer_lane": lane,
                    "graphics_api": graphics_api,
                    "production_path": [
                        "DiagnosticsApplication",
                        "FileBackedV1Persistence",
                        "LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter",
                        "LiveStrategyLibraryAdapter",
                        "LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter",
                        "LiveScenarioLabAdapter",
                        "LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter",
                        "LiveDiagnosticTasksAdapter",
                        "LiveStrategyDiagnosticsV1ApplicationAdapter",
                        "EventBridge",
                        "LiveRunMonitoringAdapter",
                        "LiveEvidenceAndFindingsAdapter",
                        "JourneyWorkspaceHost",
                    ],
                    "fixture_kind": "authoritative_writable_wave3_inputs",
                    "strategy_selection_created_after_install": True,
                    "recipe_draft_created_after_install": True,
                    "recipe_validation_created_after_install": True,
                    "recipe_approval_created_after_install": True,
                    "reference_path_materialized_after_install": True,
                    "scenario_set_created_after_install": True,
                    "scenario_selection_created_after_install": True,
                    "strategy_selection_context_identity": (
                        "STRATEGY-SELECTION-RC-001"
                    ),
                    "recipe_draft_identity": installed_recipe_drafts[0],
                    "recipe_validation_identity": (
                        installed_recipe_validations[0]
                    ),
                    "materialization_task_handle_identity": (
                        installed_materialization_handles[0]
                    ),
                    "materialized_path_identity": installed_paths[0],
                    "materialized_scenario_identity": installed_scenarios[0],
                    "terminal_campaign_case_identity": "CASE-RC-001",
                    "terminal_selected_campaign_case_identity": (
                        installed_scenarios[0]
                    ),
                    "terminal_node_market_scenario_identity": (
                        installed_paths[0]
                    ),
                    "terminal_campaign_node_lifecycle": "completed",
                    "terminal_case_manifest_binding_verified": True,
                    "installed_setup_ledger_reopened": True,
                    "reopened_installed_setup_ledger": (
                        _reopened_setup_ledger(
                            installed_recipe_drafts,
                            installed_recipe_validations,
                            installed_approved_recipes,
                            installed_materialization_handles,
                            installed_paths,
                            installed_scenarios,
                        )
                    ),
                    "formal_scenario_set_identity": "SCENARIO-SET-RC-001",
                    "scenario_selection_context_identity": (
                        "SCENARIO-SELECTION-RC-001"
                    ),
                    "setup_selection_context_identity": (
                        "SETUP-SELECTION-RC-001"
                    ),
                    "installed_setup_command_kinds": [
                        "compare_formal_strategy_set",
                        "select_formal_strategy_set",
                        "create_recipe_draft",
                        "validate_recipe_draft",
                        "approve_recipe",
                        "materialize_reference_path",
                        "compose_formal_scenario_set",
                        "resolve_execution_assumptions",
                        "select_formal_scenario_set",
                    ],
                    "installed_recipe_draft_identities": (
                        installed_recipe_drafts
                    ),
                    "installed_recipe_validation_identities": (
                        installed_recipe_validations
                    ),
                    "installed_approved_recipe_identities": (
                        installed_approved_recipes
                    ),
                    "installed_materialization_task_handle_identities": (
                        installed_materialization_handles
                    ),
                    "installed_materialized_path_identities": installed_paths,
                    "installed_materialized_scenario_identities": (
                        installed_scenarios
                    ),
                    "task_created_after_install": True,
                    "campaign_created_after_install": True,
                    "diagnostic_task_identity": "DT-RC-001",
                    "accepted_command_kinds": [
                        "create_diagnostic_task",
                        "revise_configuration",
                        "validate_configuration",
                        "approve_configuration",
                        "start_formal_diagnostic_campaign",
                    ],
                    "task_handle_identities": [
                        "TASK-HANDLE-CREATE-RC-001",
                        "TASK-HANDLE-VALIDATE-RC-001",
                        "TASK-HANDLE-START-RC-001",
                    ],
                    "writable_persistence_verified": True,
                    "application_reopened": True,
                    "background_continuation_verified": True,
                    "task_cancel_order_isolation_verified": True,
                    "campaign_identity": "FDC-RC-001",
                    "case_identity": "CASE-RC-001",
                    "run_identity": "RUN-RC-001",
                    "strategy_identity": "STRATEGY-RC-001",
                    "approved_recipe_identity": "RECIPE-RC-001",
                    "evidence_package_identity": "EVIDENCE-RC-001",
                    "reproduction_manifest_identity": "RM-RC-001",
                    "artifact_hashes": ["sha256:" + "a" * 64],
                    "persistence_kind": "sqlite+json+parquet",
                    "persistence_reopened": True,
                    "application_read_model_interface": (
                        "StrategyDiagnosticsV1ApplicationReadModel/1.0"
                    ),
                    "active_feature_interfaces": [
                        "StrategyLibraryFeature/1.0",
                        "ScenarioLabFeature/1.0",
                        "DiagnosticTasksFeature/1.0",
                        "RunMonitoringFeature/1.2",
                        "EvidenceAndFindingsFeature/1.1",
                    ],
                    "campaign_status": "completed",
                    "run_status": "completed",
                    "evidence_status": "sealed",
                    "expected_identity_graph": (
                        installed_identity_graph
                    ),
                    "feature_identity_graph": (
                        installed_identity_graph
                    ),
                    "qml_identity_graph_checkpoints": {
                        stage: installed_identity_graph
                        for stage, *_ in _CLEAN_ROOM_JOURNEY
                    },
                    "evidence_identity_sets": (
                        _CLEAN_ROOM_IDENTITY_SETS
                    ),
                    "persisted_manifest_identities": (
                        _CLEAN_ROOM_MANIFEST_IDENTITIES
                    ),
                    "persisted_run_identities": (
                        _CLEAN_ROOM_RUN_IDENTITIES
                    ),
                    "raw_artifact_hashes": (
                        [
                            *_CLEAN_ROOM_RAW_ARTIFACT_HASHES,
                            *installed_paths,
                        ]
                    ),
                    "keyboard_navigation_verified": True,
                    "accessibility_preferences_verified": True,
                    "accessibility_announcements": [
                        "Run Monitoring disconnected",
                        "Evidence and Findings disconnected",
                        "Run Monitoring fresh",
                        "Evidence and Findings fresh",
                    ],
                    "old_generation_rejected": True,
                    "authoritative_reconnect_verified": True,
                    "routes_rendered": [
                        "strategy_library",
                        "scenario_lab",
                        "diagnostic_tasks",
                        "run_monitoring",
                        "evidence_and_findings",
                    ],
                    "connection_transitions": [
                        "connected",
                        "disconnected",
                        "reconnected",
                        "remounted",
                        "closed",
                    ],
                    "observations": [
                        {
                            "stage": stage,
                            "route": route,
                            "run_state": run_state,
                            "evidence_state": evidence_state,
                            "run_freshness": run_freshness,
                            "evidence_freshness": evidence_freshness,
                        }
                        for (
                            stage,
                            route,
                            run_state,
                            evidence_state,
                            run_freshness,
                            evidence_freshness,
                        ) in _CLEAN_ROOM_JOURNEY
                    ],
                    "manual_trading_action_count": 0,
                    "read_only_context_visible": True,
                    "errors": [],
                    "clean_exit": True,
                }
            ),
            encoding="utf-8",
        )
        reports[lane] = report_path

    evidence = write_renderer_evidence(
        hardware_report=reports["hardware"],
        software_report=reports["software"],
        source_commit="abc123",
        evidence_dir=tmp_path / "evidence",
    )

    assert evidence.source_commit == "abc123"
    assert evidence.toolchain_identity.startswith("sha256:")
    assert evidence.hardware.graphics_api == "Direct3D11"
    assert evidence.software.graphics_api == "Software"
    assert evidence.hardware.journey_stages == (
        "launched_terminal_run",
        "terminal_evidence",
        "disconnected_run",
        "disconnected_evidence",
        "reconnected_pending_run",
        "reconnected_pending_evidence",
        "reconnected_terminal_run",
        "reconnected_evidence",
        "remounted_terminal_run",
        "remounted_terminal_evidence",
    )
    assert evidence.environment_identity
    assert (
        tmp_path / "evidence" / "renderer-gate-report.json"
    ).is_file()

    software_payload = json.loads(
        reports["software"].read_text(encoding="utf-8")
    )
    software_payload["diagnostic_task_identity"] = "DT-RC-SOFTWARE"
    software_payload["task_handle_identities"] = [
        "TASK-HANDLE-CREATE-RC-SOFTWARE",
        "TASK-HANDLE-VALIDATE-RC-SOFTWARE",
        "TASK-HANDLE-START-RC-SOFTWARE",
    ]
    software_payload["persisted_run_identities"] = [
        "RUN-RC-001",
        "RUN-RC-OTHER",
    ]
    replacements = {
        "DT-RC-001": "DT-RC-SOFTWARE",
        "TASK-HANDLE-CREATE-RC-001": (
            "TASK-HANDLE-CREATE-RC-SOFTWARE"
        ),
        "TASK-HANDLE-VALIDATE-RC-001": (
            "TASK-HANDLE-VALIDATE-RC-SOFTWARE"
        ),
        "TASK-HANDLE-START-RC-001": (
            "TASK-HANDLE-START-RC-SOFTWARE"
        ),
        "RUN-RC-002": "RUN-RC-OTHER",
    }
    drifted_graph = sorted(
        replacements.get(identity, identity)
        for identity in software_payload["expected_identity_graph"]
    )
    software_payload["expected_identity_graph"] = drifted_graph
    software_payload["feature_identity_graph"] = drifted_graph
    software_payload["qml_identity_graph_checkpoints"] = {
        stage: drifted_graph for stage, *_ in _CLEAN_ROOM_JOURNEY
    }
    reports["software"].write_text(
        json.dumps(software_payload),
        encoding="utf-8",
    )

    lane_local_evidence = write_renderer_evidence(
        hardware_report=reports["hardware"],
        software_report=reports["software"],
        source_commit="abc123",
        evidence_dir=tmp_path / "lane-local-evidence",
    )
    assert (
        lane_local_evidence.hardware.diagnostic_task_identity
        != lane_local_evidence.software.diagnostic_task_identity
    )
    assert (
        lane_local_evidence.hardware.task_handle_identities
        != lane_local_evidence.software.task_handle_identities
    )


def test_dependency_and_surface_audits_reject_manual_or_web_payloads(
    tmp_path,
):
    safe_report = tmp_path / "safe.xml"
    safe_report.write_text(
        """
        <nuitka-compilation-report mode="standalone" completion="yes">
          <module name="app.features.run_monitoring" />
          <module name="app.features.live_run_monitoring" />
          <module name="app.ui.journey_workspace" />
          <module name="app.ui.accessibility" />
          <module name="app.ui.evidence_chart" />
          <module name="app.event_bridge" />
          <module name="app.core_dto.snapshot" />
          <module name="infra.event_bus" />
          <module name="observability.metrics" />
          <module name="_duckdb" />
          <module name="app.features.live_strategy_diagnostics_v1_application" />
          <module name="app.features.live_strategy_library" />
          <module name="app.features.live_scenario_lab" />
          <module name="app.features.strategy_library_application" />
          <module name="app.features.scenario_lab_application" />
          <module name="duckdb" />
          <module name="persistence.models_training" />
          <module name="sqlalchemy.dialects.sqlite.pysqlite" />
          <module name="stock_sim.release.strategy_diagnostics_v1_release_fixture" />
          <module name="strategy_diagnostics.application" />
          <module name="strategy_diagnostics.diagnostic_evidence_storage" />
          <module name="strategy_diagnostics.live_minute_scenario_native_strategy" />
          <module name="strategy_diagnostics.market_paths" />
          <module name="strategy_diagnostics.persistence" />
          <module name="strategy_diagnostics.quentx_scenario_native_strategy" />
          <module name="strategy_diagnostics.strategy_inventory" />
          <data_file name="app/ui/qml/JourneyWorkspace.qml" />
          <data_file name="strategy_diagnostics/formal_sources/live_minute_scenario_native_strategy.py.txt" />
          <data_file name="strategy_diagnostics/formal_sources/quentx_scenario_native_strategy.py.txt" />
        </nuitka-compilation-report>
        """,
        encoding="utf-8",
    )
    unsafe_report = tmp_path / "unsafe.xml"
    unsafe_report.write_text(
        """
        <nuitka-compilation-report mode="standalone" completion="yes">
          <module name="app.panels.orders" />
          <module name="app.services.trading_service" />
          <module name="services.order_service" />
          <module name="stock_sim.persistence.models_order" />
          <module name="redis.client" />
          <module name="PySide6.QtWebEngineCore" />
        </nuitka-compilation-report>
        """,
        encoding="utf-8",
    )

    assert audit_nuitka_dependency_report(
        safe_report,
        package_kind=PackageKind.QML_JOURNEY,
    ) == ()
    unsafe_findings = audit_nuitka_dependency_report(
        unsafe_report,
        package_kind=PackageKind.QML_JOURNEY,
    )
    assert any("app.panels.orders" in finding for finding in unsafe_findings)
    assert any(
        "app.services.trading_service" in finding
        for finding in unsafe_findings
    )
    assert any(
        "services.order_service" in finding
        for finding in unsafe_findings
    )
    assert not any(
        "stock_sim.persistence.models_order" in finding
        for finding in unsafe_findings
    )
    assert any("QtWebEngineCore" in finding for finding in unsafe_findings)
    assert any("redis.client" in finding for finding in unsafe_findings)
    assert audit_frontend_v2_surface() == ()


def test_dependency_audit_accepts_nuitka_utf8_alias_with_non_ascii_path(
    tmp_path,
):
    report = tmp_path / "nuitka-utf8-alias.xml"
    report.write_bytes(
        (
            "<?xml version='1.0' encoding='utf8'?>\n"
            '<nuitka-compilation-report mode="standalone" '
            'completion="yes">\n'
            "  <python><search_path>"
            '<path value="T:\\文档\\release-input" />'
            "</search_path></python>\n"
            "</nuitka-compilation-report>\n"
        ).encode("utf-8")
    )

    assert audit_nuitka_dependency_report(
        report,
        package_kind=PackageKind.WIDGETS_ROLLBACK,
    ) == ()


def test_qml_dependency_audit_allows_production_main_window_host_only(
    tmp_path,
):
    host_report = tmp_path / "qml-production-host.xml"
    host_report.write_text(
        """
        <nuitka-compilation-report mode="standalone" completion="yes">
          <module name="app.app_context" />
          <module name="app.i18n.loader" />
          <module name="app.journey_recovery" />
          <module name="app.state.app_state" />
          <module name="app.state.layout_persistence" />
          <module name="app.state.settings_state" />
          <module name="app.state.version_store" />
          <module name="app.ui.docking" />
          <module name="app.ui.main_window" />
          <module name="app.ui.ui_refresh" />
          <module name="app.ui.journey_workspace" />
          <module name="_duckdb" />
          <module name="app.features.live_strategy_diagnostics_v1_application" />
          <module name="app.features.live_strategy_library" />
          <module name="app.features.live_scenario_lab" />
          <module name="app.features.strategy_library_application" />
          <module name="app.features.scenario_lab_application" />
          <module name="duckdb" />
          <module name="persistence.models_training" />
          <module name="sqlalchemy.dialects.sqlite.pysqlite" />
          <module name="stock_sim.release.strategy_diagnostics_v1_release_fixture" />
          <module name="strategy_diagnostics.application" />
          <module name="strategy_diagnostics.diagnostic_evidence_storage" />
          <module name="strategy_diagnostics.live_minute_scenario_native_strategy" />
          <module name="strategy_diagnostics.market_paths" />
          <module name="strategy_diagnostics.persistence" />
          <module name="strategy_diagnostics.quentx_scenario_native_strategy" />
          <module name="strategy_diagnostics.strategy_inventory" />
          <data_file name="strategy_diagnostics/formal_sources/live_minute_scenario_native_strategy.py.txt" />
          <data_file name="strategy_diagnostics/formal_sources/quentx_scenario_native_strategy.py.txt" />
        </nuitka-compilation-report>
        """,
        encoding="utf-8",
    )
    command_report = tmp_path / "qml-command-path.xml"
    command_report.write_text(
        """
        <nuitka-compilation-report mode="standalone" completion="yes">
          <module name="app.controllers.trading_controller" />
          <module name="app.panels.orders" />
          <module name="app.services.trading_service" />
          <module name="services.order_service" />
          <module name="services.runtime_command_service" />
          <module name="strategy_diagnostics.ptrade_host_worker" />
        </nuitka-compilation-report>
        """,
        encoding="utf-8",
    )

    assert audit_nuitka_dependency_report(
        host_report,
        package_kind=PackageKind.QML_JOURNEY,
    ) == ()
    command_findings = audit_nuitka_dependency_report(
        command_report,
        package_kind=PackageKind.QML_JOURNEY,
    )
    for module_name in (
        "app.controllers.trading_controller",
        "app.panels.orders",
        "app.services.trading_service",
        "services.order_service",
        "services.runtime_command_service",
        "strategy_diagnostics.ptrade_host_worker",
    ):
        assert any(
            module_name in finding for finding in command_findings
        )


@pytest.mark.parametrize(
    "missing_module",
    (
        "_duckdb",
        "strategy_diagnostics.quentx_scenario_native_strategy",
        "strategy_diagnostics.live_minute_scenario_native_strategy",
    ),
)
def test_qml_dependency_audit_requires_complete_real_v1_closure(
    tmp_path,
    missing_module,
):
    complete_report = tmp_path / "complete-real-v1.xml"
    complete_report.write_text(
        _nuitka_report_xml(*_REQUIRED_QML_DEPENDENCY_MODULES),
        encoding="utf-8",
    )
    assert audit_nuitka_dependency_report(
        complete_report,
        package_kind=PackageKind.QML_JOURNEY,
    ) == ()

    incomplete_report = tmp_path / "incomplete-real-v1.xml"
    incomplete_report.write_text(
        _nuitka_report_xml(
            *(
                module_name
                for module_name in _REQUIRED_QML_DEPENDENCY_MODULES
                if module_name != missing_module
            ),
        ),
        encoding="utf-8",
    )
    findings = audit_nuitka_dependency_report(
        incomplete_report,
        package_kind=PackageKind.QML_JOURNEY,
    )
    assert findings == (
        "Required real V1 module is absent from the QML "
        f"dependency closure: {missing_module}",
    )


@pytest.mark.parametrize(
    "missing_source",
    _REQUIRED_QML_FORMAL_STRATEGY_SOURCE_FILES,
)
def test_qml_dependency_audit_requires_auditable_strategy_sources(
    tmp_path,
    missing_source,
):
    report = tmp_path / "missing-formal-strategy-source.xml"
    report.write_text(
        _nuitka_report_xml(
            *_REQUIRED_QML_DEPENDENCY_MODULES,
            data_files=(
                source
                for source in _REQUIRED_QML_FORMAL_STRATEGY_SOURCE_FILES
                if source != missing_source
            ),
        ),
        encoding="utf-8",
    )

    assert audit_nuitka_dependency_report(
        report,
        package_kind=PackageKind.QML_JOURNEY,
    ) == (
        "Required audited formal strategy source is absent from the QML "
        f"package: {missing_source}",
    )


def test_widgets_dependency_audit_allows_read_only_trade_context_only(
    tmp_path,
):
    read_only_report = tmp_path / "widgets-read-only.xml"
    read_only_report.write_text(
        """
        <nuitka-compilation-report mode="standalone" completion="yes">
          <module name="app.core_dto.trade" />
          <module name="stock_sim.persistence.models_order" />
        </nuitka-compilation-report>
        """,
        encoding="utf-8",
    )
    command_report = tmp_path / "widgets-command-path.xml"
    command_report.write_text(
        """
        <nuitka-compilation-report mode="standalone" completion="yes">
          <module name="app.services.trading_service" />
          <module name="services.order_service" />
          <module name="services.runtime_command_service" />
        </nuitka-compilation-report>
        """,
        encoding="utf-8",
    )

    assert audit_nuitka_dependency_report(
        read_only_report,
        package_kind=PackageKind.WIDGETS_ROLLBACK,
    ) == ()
    command_findings = audit_nuitka_dependency_report(
        command_report,
        package_kind=PackageKind.WIDGETS_ROLLBACK,
    )
    assert any(
        "app.services.trading_service" in finding
        for finding in command_findings
    )
    assert any(
        "services.order_service" in finding
        for finding in command_findings
    )
    assert any(
        "services.runtime_command_service" in finding
        for finding in command_findings
    )


def test_widgets_dependency_audit_rejects_new_v1_seam_and_network_stack(
    tmp_path,
):
    report = tmp_path / "widgets-coupled.xml"
    report.write_text(
        """
        <nuitka-compilation-report mode="standalone" completion="yes">
          <module name="app.app_context" />
          <module name="app.event_bridge" />
          <module name="app.features.live_strategy_diagnostics_v1_application" />
          <module name="redis.client" />
          <module name="requests.sessions" />
        </nuitka-compilation-report>
        """,
        encoding="utf-8",
    )

    findings = audit_nuitka_dependency_report(
        report,
        package_kind=PackageKind.WIDGETS_ROLLBACK,
    )

    for module_name in (
        "app.app_context",
        "app.event_bridge",
        "app.features.live_strategy_diagnostics_v1_application",
        "redis.client",
        "requests.sessions",
    ):
        assert any(module_name in finding for finding in findings)


def test_dependency_audit_rejects_missing_project_modules_only(tmp_path):
    report = tmp_path / "missing-project-module.xml"
    report.write_text(
        """
        <nuitka-compilation-report mode="standalone" completion="yes">
          <module name="app.services.model_checkpoint_service">
            <module_usage
              name="persistence.models_training"
              finding="not-found"
              line="11"
            />
            <module_usage
              name="optional_vendor_acceleration"
              finding="not-found"
              line="12"
            />
          </module>
        </nuitka-compilation-report>
        """,
        encoding="utf-8",
    )

    findings = audit_nuitka_dependency_report(
        report,
        package_kind=PackageKind.WIDGETS_ROLLBACK,
    )

    assert any(
        "Missing project module" in finding
        and "persistence.models_training" in finding
        for finding in findings
    )
    assert not any(
        "optional_vendor_acceleration" in finding for finding in findings
    )


def test_widgets_rollback_entry_uses_the_real_read_only_migration_host():
    rollback_source = (
        PROJECT_ROOT
        / "stock_sim"
        / "release"
        / "frontend_widgets_rollback_entry.py"
    ).read_text(encoding="utf-8")

    assert "from app.ui.main_window import MainWindow" in rollback_source
    assert "from app.panels import" in rollback_source
    assert "register_builtin_panels" in rollback_source
    assert "register_ui_adapters" in rollback_source
    assert "rollback_read_only=True" in rollback_source
    assert "layout_store=layout_store" in rollback_source
    assert "from app.app_context" not in rollback_source
    assert "from app.event_bridge" not in rollback_source
    assert (
        "from app.legacy_panel_context import build_legacy_panel_context"
        in rollback_source
    )
    app_context_source = (
        PROJECT_ROOT / "app" / "app_context.py"
    ).read_text(encoding="utf-8")
    app_context_import_prefix = app_context_source.split(
        "def build_app_context",
        maxsplit=1,
    )[0]
    assert (
        "from app.legacy_panel_context import build_legacy_panel_context"
        not in app_context_import_prefix
    )
    assert (
        "from app.legacy_panel_context import build_legacy_panel_context"
        in app_context_source
    )
    assert "QMainWindow()" not in rollback_source
    assert "QLabel(" not in rollback_source


def test_widgets_rollback_smoke_needs_no_frontend_v2_seam_modules(
    tmp_path,
):
    script = r"""
import importlib.abc
import sys

blocked = ("app.app_context", "app.event_bridge", "app.features")

class BlockedFrontendV2Seam(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(
            fullname == prefix or fullname.startswith(prefix + ".")
            for prefix in blocked
        ):
            raise ModuleNotFoundError(fullname)
        return None

sys.meta_path.insert(0, BlockedFrontendV2Seam())

from stock_sim.release.frontend_widgets_rollback_entry import main

raise SystemExit(
    main(
        [
            "--source-commit",
            "abc123",
            "--smoke-report-dir",
            sys.argv[1],
        ]
    )
)
"""
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["STOCKSIM_ENABLE_REAL_UI"] = "1"
    report_dir = tmp_path / "widgets-no-seam"

    completed = subprocess.run(
        (sys.executable, "-c", script, str(report_dir)),
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(
        (report_dir / "smoke-report.json").read_text(encoding="utf-8")
    )
    assert report["placeholder_panels"] == []
    assert report["real_panel_count"] == 8
    assert report["manual_trading_action_count"] == 0
    assert report["clean_exit"] is True


def test_widgets_rollback_smoke_records_the_source_commit(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("STOCKSIM_ENABLE_REAL_UI", "1")

    report_dir = tmp_path / "widgets-smoke"

    completed = subprocess.run(
        (
            sys.executable,
            "-m",
            "stock_sim.release.frontend_widgets_rollback_entry",
            "--source-commit",
            "abc123",
            "--smoke-report-dir",
            str(report_dir),
        ),
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )

    report = json.loads(
        (report_dir / "smoke-report.json").read_text(encoding="utf-8")
    )
    assert completed.returncode == 0, completed.stderr
    assert report["source_commit"] == "abc123"
    assert report["mode"] == "read-only"
    assert report["placeholder_panels"] == []
    assert report["real_panel_count"] >= 3
    assert report["manual_trading_action_count"] == 0
    assert {
        "diagnostics",
        "market",
        "orders",
    } <= set(report["opened_panels"])
    assert report["clean_exit"] is True


def test_widgets_migration_host_accepts_an_isolated_read_only_panel_catalog(
    tmp_path,
):
    from PySide6.QtWidgets import QApplication, QLabel

    from app.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    assert app is not None
    widgets = {
        "diagnostics": QLabel("Diagnostics read-only"),
        "market": QLabel("Market read-only"),
    }
    descriptors = [
        {"name": name, "title": name.title()}
        for name in widgets
    ]

    class MemoryLayoutStore:
        def __init__(self):
            self.layout = {"panels": {}}

        def get(self):
            return self.layout

        def save(self, layout):
            self.layout = layout

    layout_store = MemoryLayoutStore()
    window = MainWindow(
        frontend_v2_enabled=False,
        rollback_read_only=True,
        layout_path=str(tmp_path / "layout.json"),
        panel_list=lambda: descriptors,
        panel_get=widgets.__getitem__,
        layout_store=layout_store,
    )

    assert window.open_panel("diagnostics") is widgets["diagnostics"]
    assert window.open_panel("market") is widgets["market"]
    assert window.open_panel("orders") is None
    assert set(window.list_open()) == {"diagnostics", "market"}
    window.close()
    assert set(layout_store.layout["panels"]) == {
        "diagnostics",
        "market",
    }


def test_release_source_verification_rejects_untracked_inputs(tmp_path):
    import subprocess

    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=repository, check=True)
    subprocess.run(
        ("git", "config", "user.name", "Release Test"),
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ("git", "config", "user.email", "release@example.invalid"),
        cwd=repository,
        check=True,
    )
    tracked = repository / "route.qml"
    tracked.write_text("import QtQuick 2.15\n", encoding="utf-8")
    subprocess.run(("git", "add", "route.qml"), cwd=repository, check=True)
    subprocess.run(
        ("git", "commit", "-q", "-m", "fixture"),
        cwd=repository,
        check=True,
    )
    commit = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    (repository / "untracked.qml").write_text(
        "import QtQuick.Layouts 2.15\n",
        encoding="utf-8",
    )

    try:
        verify_release_source(
            source_root=repository,
            source_commit=commit,
        )
    except RuntimeError as error:
        assert "clean working tree" in str(error)
        assert "untracked.qml" in str(error)
    else:
        raise AssertionError("Untracked packaging input was accepted")


def test_release_source_verification_rejects_ignored_qml_inputs(tmp_path):
    import subprocess

    repository = tmp_path / "repository"
    qml_root = repository / "app" / "ui" / "qml"
    qml_root.mkdir(parents=True)
    subprocess.run(("git", "init", "-q"), cwd=repository, check=True)
    subprocess.run(
        ("git", "config", "user.name", "Release Test"),
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ("git", "config", "user.email", "release@example.invalid"),
        cwd=repository,
        check=True,
    )
    (repository / ".gitignore").write_text(
        "app/ui/qml/Ignored.qml\n",
        encoding="utf-8",
    )
    (qml_root / "Tracked.qml").write_text(
        "import QtQuick 2.15\n",
        encoding="utf-8",
    )
    subprocess.run(
        ("git", "add", ".gitignore", "app/ui/qml/Tracked.qml"),
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ("git", "commit", "-q", "-m", "fixture"),
        cwd=repository,
        check=True,
    )
    commit = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    (qml_root / "Ignored.qml").write_text(
        "import QtQuick.Layouts 2.15\n",
        encoding="utf-8",
    )

    try:
        verify_release_source(
            source_root=repository,
            source_commit=commit,
        )
    except RuntimeError as error:
        assert "ignored or untracked release input" in str(error)
        assert "app/ui/qml/Ignored.qml" in str(error)
    else:
        raise AssertionError("Ignored QML packaging input was accepted")


def test_clean_room_script_fails_closed_on_inventory_or_lane_errors():
    script = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
    ).read_text(encoding="utf-8")

    assert "network_enumeration_succeeded" in script
    assert "python_installations" in script
    assert "compiler_installations" in script
    assert "dependency_cache_paths" in script
    assert "states_match" in script
    assert "screenshots_distinct" in script
    assert "$screenshotHashes" in script
    assert "schema_version = 3" in script
    assert '"--source-commit=$SourceCommit"' in script
    assert "production_path" in script
    assert (
        "LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter"
        in script
    )
    assert "LiveDiagnosticTasksAdapter" in script
    assert "real_v1_identity_valid" in script
    assert "campaign_identity" in script
    assert "evidence_package_identity" in script
    assert "application_read_model_interface" in script
    assert "active_feature_interfaces" in script
    assert "persistence_reopened" in script
    assert "persisted_manifest_identities" in script
    assert "persisted_run_identities" in script
    assert "raw_artifact_hashes" in script
    assert "routes_rendered" in script
    assert "connection_transitions" in script
    assert "observations" in script
    assert "manual_trading_action_count" in script
    assert "read_only_context_visible" in script
    assert "WidgetsPackageArchive" in script
    assert "ExpectedWidgetsArchiveSha256" in script
    assert "UTI-Widgets-Rollback.exe" in script
    assert "widgets_archive_sha256" in script
    assert "widgets_rollback" in script
    assert "expected_identity_graph" in script
    assert "feature_identity_graph" in script
    assert "qml_identity_graph_checkpoints" in script
    assert "evidence_identity_sets" in script
    assert "keyboard_navigation_verified" in script
    assert "accessibility_preferences_verified" in script
    assert "old_generation_rejected" in script
    assert "authoritative_reconnect_verified" in script
    assert "fixture_kind" in script
    assert "strategy_selection_created_after_install" in script
    assert "recipe_draft_created_after_install" in script
    assert "recipe_validation_created_after_install" in script
    assert "recipe_approval_created_after_install" in script
    assert "reference_path_materialized_after_install" in script
    assert "scenario_set_created_after_install" in script
    assert "scenario_selection_created_after_install" in script
    assert "strategy_selection_context_identity" in script
    assert "installed_setup_command_kinds" in script
    assert "installed_recipe_draft_identities" in script
    assert "installed_recipe_validation_identities" in script
    assert "installed_approved_recipe_identities" in script
    assert "installed_materialization_task_handle_identities" in script
    assert "installed_materialized_path_identities" in script
    assert "installed_materialized_scenario_identities" in script
    assert "terminal_campaign_case_identity" in script
    assert "terminal_selected_campaign_case_identity" in script
    assert "terminal_node_market_scenario_identity" in script
    assert "terminal_campaign_node_lifecycle" in script
    assert "terminal_case_manifest_binding_verified" in script
    assert "installed_setup_ledger_reopened" in script
    assert "reopened_installed_setup_ledger" in script
    assert "Test-ExactStringArray" in script
    assert "task_created_after_install" in script
    assert "campaign_created_after_install" in script
    assert "diagnostic_task_identity" in script
    assert "accepted_command_kinds" in script
    assert "task_handle_identities" in script
    assert "writable_persistence_verified" in script
    assert "application_reopened" in script
    assert "background_continuation_verified" in script
    assert "task_cancel_order_isolation_verified" in script
    assert (
        "$rendererLanes.hardware.campaign_identity -eq"
        not in script
    )
    assert (
        "$rendererLanes.hardware.diagnostic_task_identity -eq"
        not in script
    )
    assert (
        "$rendererLanes.hardware.task_handle_identities -join"
        not in script
    )
    assert (
        "$rendererLanes.hardware.artifact_hashes -join"
        not in script
    )
    assert "installed_wave3_journey_valid" in script
    assert (
        "StrategyLibraryFeature/1.0|"
        "ScenarioLabFeature/1.0|"
        "DiagnosticTasksFeature/1.0|"
        "RunMonitoringFeature/1.2|"
        "EvidenceAndFindingsFeature/1.1"
        in script
    )
    assert "$smoke.persistence_reopened -is [bool]" in script
    assert "$smoke.read_only_context_visible -is [bool]" in script
    assert "$smoke.clean_exit -is [bool]" in script
    assert "[bool]$smoke.persistence_reopened" not in script
    assert "[bool]$smoke.read_only_context_visible" not in script
    assert "$requiredVisualGroups" in script
    assert re.search(
        r"""
        \[IO\.File\]::WriteAllText\(
        \s*\$reportPath,
        \s*\$reportJson,
        \s*\[Text\.UTF8Encoding\]::new\(\$false\)
        \s*\)
        """,
        script,
        re.VERBOSE,
    )
    assert "clean_exit" in script
    assert "errors.Count -eq 0" in script
    assert "$pythonInstallations = @(" in script
    assert "$compilerInstallations = @(" in script
    assert "$dependencyCachePaths = @(" in script


def test_clean_room_error_normalizer_ignores_blank_json_error_values(
    monkeypatch,
):
    powershell = shutil.which("pwsh") or shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("PowerShell is required for the Windows gate")

    script_path = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
    )
    script = script_path.read_text(encoding="utf-8")
    assert script.count("ConvertTo-ReleaseErrorList -Errors") >= 2
    monkeypatch.setenv("ISSUE53_CLEAN_ROOM_SCRIPT", str(script_path))
    command = r"""
    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        $env:ISSUE53_CLEAN_ROOM_SCRIPT,
        [ref]$tokens,
        [ref]$parseErrors
    )
    if ($parseErrors.Count -ne 0) {
        throw "Clean-room script did not parse."
    }
    $normalizer = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq "ConvertTo-ReleaseErrorList"
    }, $true)
    if ($null -eq $normalizer) {
        throw "ConvertTo-ReleaseErrorList is unavailable."
    }
    Invoke-Expression $normalizer.Extent.Text
    $blank = @(ConvertTo-ReleaseErrorList -Errors "")
    $whitespace = @(ConvertTo-ReleaseErrorList -Errors @(" ", "`t"))
    $missing = @(ConvertTo-ReleaseErrorList -Errors $null)
    $real = @(
        ConvertTo-ReleaseErrorList -Errors @("first", "", "second")
    )
    if (
        $blank.Count -ne 0 -or
        $whitespace.Count -ne 0 -or
        $missing.Count -ne 0 -or
        $real.Count -ne 2 -or
        $real[0] -ne "first" -or
        $real[1] -ne "second"
    ) {
        throw "Release error normalization is incorrect."
    }
    """

    completed = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-Command",
            command,
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_clean_room_renderer_lane_reset_removes_stale_evidence(
    tmp_path,
    monkeypatch,
):
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is required for the Windows gate")

    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    lane_dir = evidence_root / "hardware"
    lane_dir.mkdir()
    (lane_dir / "smoke-report.json").write_text(
        '{"stale": true}',
        encoding="utf-8",
    )
    for state in ("loading", "empty", "disconnected"):
        (lane_dir / f"{state}.png").write_bytes(b"stale")

    script_path = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
    )
    monkeypatch.setenv("ISSUE37_CLEAN_ROOM_SCRIPT", str(script_path))
    monkeypatch.setenv("ISSUE37_EVIDENCE_DIR", str(evidence_root))
    command = r"""
    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        $env:ISSUE37_CLEAN_ROOM_SCRIPT,
        [ref]$tokens,
        [ref]$parseErrors
    )
    if ($parseErrors.Count -ne 0) {
        throw "Clean-room script did not parse."
    }
    $resetFunction = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq "Reset-RendererLaneEvidence"
    }, $true)
    if ($null -eq $resetFunction) {
        throw "Reset-RendererLaneEvidence is unavailable."
    }
    Invoke-Expression $resetFunction.Extent.Text
    Reset-RendererLaneEvidence `
        -EvidenceRoot $env:ISSUE37_EVIDENCE_DIR `
        -LaneDirectory $env:ISSUE37_LANE_DIR
    """

    def invoke_reset(target):
        monkeypatch.setenv("ISSUE37_LANE_DIR", str(target))
        return subprocess.run(
            [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-Command",
                command,
            ],
            capture_output=True,
            check=False,
            text=True,
            errors="backslashreplace",
        )

    completed = invoke_reset(lane_dir)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert lane_dir.is_dir()
    assert tuple(lane_dir.iterdir()) == ()

    nested_lane = evidence_root / "unrelated" / "hardware"
    nested_lane.mkdir(parents=True)
    nested_marker = nested_lane / "must-survive.txt"
    nested_marker.write_text("preserve", encoding="utf-8")
    nested_result = invoke_reset(nested_lane)
    assert nested_result.returncode != 0
    assert nested_marker.read_text(encoding="utf-8") == "preserve"

    outside_lane = tmp_path / "software"
    outside_lane.mkdir()
    outside_marker = outside_lane / "must-survive.txt"
    outside_marker.write_text("preserve", encoding="utf-8")
    outside_result = invoke_reset(outside_lane)
    assert outside_result.returncode != 0
    assert outside_marker.read_text(encoding="utf-8") == "preserve"


def test_package_archive_is_deterministic_and_installable_by_extraction(
    tmp_path,
):
    import zipfile

    plan = create_package_build_plans(
        output_root=tmp_path / "packages",
        source_commit="abc123",
    )[1]
    plan.distribution_dir.mkdir(parents=True)
    (plan.distribution_dir / plan.executable_name).write_bytes(b"exe")
    (plan.distribution_dir / "runtime.dll").write_bytes(b"dll")

    first = create_deterministic_package_archive(
        plan,
        archive_dir=tmp_path / "archives-a",
    )
    second = create_deterministic_package_archive(
        plan,
        archive_dir=tmp_path / "archives-b",
    )

    assert first.sha256 == second.sha256
    with zipfile.ZipFile(
        tmp_path / "archives-a" / first.relative_path
    ) as archive:
        assert archive.namelist() == [
            "qml-journey/UTI-Frontend-V2.exe",
            "qml-journey/runtime.dll",
        ]


def test_packaging_cli_can_emit_the_locked_build_plan_without_building(
    tmp_path,
    capsys,
):
    exit_code = packaging_main(
        [
            "--output-root",
            str(tmp_path / "release"),
            "--source-commit",
            "abc123",
            "--plan-only",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert '"source_commit": "abc123"' in output
    assert '"kind": "widgets-rollback"' in output
    assert '"kind": "qml-journey"' in output
    assert "nuitka" in output
