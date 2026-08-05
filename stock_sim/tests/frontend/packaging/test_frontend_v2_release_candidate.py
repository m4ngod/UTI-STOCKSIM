from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
from shutil import copy2, rmtree
import subprocess
import sys
from tempfile import mkdtemp
import xml.etree.ElementTree as ET

import pytest
from sqlalchemy import text
from sqlalchemy.engine.result import MappingResult

from stock_sim.release.frontend_v2_packaging import (
    PROJECT_ROOT,
    TOOLCHAIN_LOCK_PATH,
    verify_clean_room_report,
    write_mandatory_release_gate_evidence,
)
from stock_sim.release.frontend_v2_performance import (
    certify_performance_evidence,
)
from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
    FORMAL_V1_RELEASE_FIXTURE_ARCHIVE,
    WAVE2_RELEASE_INPUT_FIXTURE_ARCHIVE,
)


EXPECTED_JOURNEY = (
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


def test_clean_room_route_failure_names_all_five_active_routes() -> None:
    source = (
        PROJECT_ROOT
        / "stock_sim"
        / "release"
        / "frontend_v2_packaging.py"
    ).read_text(encoding="utf-8")

    assert "did not render all five active routes" in source
    assert "did not render all four active routes" not in source
    assert "did not render all three active routes" not in source
_IDENTITY_SETS = {
    "candidates": ["candidate-1"],
    "metrics": ["metric-1"],
    "comparisons": ["comparison-1"],
    "curves": ["curve-1"],
    "breakpoints": ["breakpoint-1"],
    "findings": ["finding-1"],
}
_PERSISTED_MANIFEST_IDENTITIES = ["RM-RC-001", "RM-RC-002"]
_PERSISTED_RUN_IDENTITIES = ["RUN-RC-001", "RUN-RC-002"]
_RAW_ARTIFACT_HASHES = ["a" * 64, "b" * 64]
_IDENTITY_GRAPH = sorted(
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
        *_PERSISTED_MANIFEST_IDENTITIES,
        *_PERSISTED_RUN_IDENTITIES,
        *_RAW_ARTIFACT_HASHES,
        *(
            identity
            for identities in _IDENTITY_SETS.values()
            for identity in identities
        ),
    }
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


def _passing_real_v1_performance_probe():
    identities = {
        "campaign_identity": "FDC-REAL-001",
        "case_identity": "CASE-REAL-001",
        "run_identity": "RUN-REAL-001",
        "strategy_identity": "STRATEGY-REAL-001",
        "approved_recipe_identity": "RECIPE-REAL-001",
        "evidence_package_identity": "EVIDENCE-REAL-001",
        "reproduction_manifest_identity": "RM-REAL-001",
    }
    return {
        "schema_version": 1,
        "production_path": [
            "DiagnosticsApplication",
            "FileBackedV1Persistence",
            "LiveStrategyDiagnosticsV1ApplicationAdapter",
        ],
        "persistence_kind": "sqlite+json+parquet",
        "persistence_reopened": True,
        "fixture_archive_digest": "sha256:" + "d" * 64,
        "application_read_model_interface": (
            "StrategyDiagnosticsV1ApplicationReadModel/1.0"
        ),
        **identities,
        "artifact_hashes": ["sha256:" + "c" * 64],
        "expected_identity_graph": sorted(
            {*identities.values(), "METRIC-REAL-001"}
        ),
        "initial_read_counts": {
            "resolve_journey": 1,
            "read_run": 1,
            "read_evidence": 1,
        },
        "execution_phase": (
            "same-process-preflight-before-renderer-clock"
        ),
        "preflight_read_counts": {
            "resolve_journey": 2,
            "read_run": 2,
            "read_evidence": 2,
        },
        "preflight_samples_scheduled": 2,
        "preflight_samples_completed": 2,
        "preflight_window": {
            "started_at": "2000-01-01T00:00:00+00:00",
            "ended_at": "2000-01-01T00:00:05+00:00",
        },
        "fixture_closed": True,
        "fixture_storage_removed": True,
        "errors": [],
        "clean_exit": True,
    }


def _passing_wave2_performance_load():
    command_ids = [
        "performance-create-diagnostic-task",
        "performance-validate-diagnostic-task",
        "performance-approve-diagnostic-task",
        "performance-start-diagnostic-campaign",
    ]
    task_handle_ids = ["diagnostic-task-handle-performance"]
    return {
        "feature_interface": "DiagnosticTasksFeature/1.0",
        "application_interface": (
            "StrategyDiagnosticsV1DiagnosticTasksApplication/1.0"
        ),
        "adapter": "DeterministicFakeDiagnosticTasksAdapter",
        "accepted_command_ids": command_ids,
        "result_command_ids": command_ids,
        "accepted_command_observed": True,
        "task_handle_observed": True,
        "task_handle_ids": task_handle_ids,
        "handoff_observed": True,
        "terminal_observed": True,
        "executed_during_active_load": True,
        "source_events_before_command": 2,
        "source_events_after_command": 2,
        "observed_before_load": True,
        "observed_after_load": True,
        "task_lifecycle": "completed",
        "identity_graph": [
            *command_ids,
            "diagnostic-task-performance",
            *task_handle_ids,
            "formal-diagnostic-campaign-performance",
            "campaign-node-performance",
            "campaign-attempt-performance",
            "strategy-run-performance",
            "diagnostic-evidence-package-performance",
            "reproduction-manifest-performance",
        ],
    }


def _write_journey_screenshots(root, lane):
    lane_dir = root / lane
    lane_dir.mkdir(parents=True)
    screenshots = []
    for (
        stage,
        route,
        run_state,
        evidence_state,
        run_freshness,
        evidence_freshness,
    ) in EXPECTED_JOURNEY:
        relative_path = f"{lane}/{stage}.png"
        screenshot_path = root / relative_path
        screenshot_path.write_bytes(
            (
                f"{lane}:{stage}:{route}:{run_state}:{evidence_state}:"
                f"{run_freshness}:{evidence_freshness}"
            ).encode()
        )
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


def test_installed_smoke_reopens_a_sealed_real_v1_fixture(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QT_QUICK_BACKEND", "software")
    from sqlalchemy import text

    from stock_sim.release import (
        frontend_v2_package_entry as release_entry,
        strategy_diagnostics_v1_release_fixture as fixture_module,
    )
    from stock_sim.release.frontend_v2_package_entry import (
        RendererLane,
        run_smoke_journey,
    )
    from stock_sim.release.frontend_v2_packaging import (
        create_package_build_plans,
        stage_packaged_formal_v1_release_fixture,
    )
    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        FORMAL_V1_RELEASE_FIXTURE_ARCHIVE,
    )

    source_commit = "a" * 40
    qml_plan = create_package_build_plans(
        output_root=tmp_path / "packages",
        source_commit=source_commit,
    )[1]
    manifest = stage_packaged_formal_v1_release_fixture(qml_plan)
    fixture_archive = (
        qml_plan.distribution_dir / FORMAL_V1_RELEASE_FIXTURE_ARCHIVE
    )
    original_archive_hash = hashlib.sha256(
        fixture_archive.read_bytes()
    ).hexdigest()

    def reject_runtime_generation(**_kwargs):
        raise AssertionError(
            "Installed smoke must not regenerate the Formal Campaign"
        )

    monkeypatch.setattr(
        fixture_module,
        "create_file_backed_formal_v1_release_fixture",
        reject_runtime_generation,
    )
    created_mount_count = 0
    create_production_window = release_entry._create_production_window

    def observed_create_production_window(**arguments):
        nonlocal created_mount_count
        created_mount_count += 1
        return create_production_window(**arguments)

    monkeypatch.setattr(
        release_entry,
        "_create_production_window",
        observed_create_production_window,
    )
    report_dir = tmp_path / "installed-smoke"
    result = run_smoke_journey(
        report_dir=report_dir,
        renderer_lane=RendererLane.SOFTWARE,
        source_commit=source_commit,
        capture_images=False,
        fixture_archive_path=fixture_archive,
    )

    assert manifest.source_commit == source_commit
    assert result.source_commit == source_commit
    assert result.campaign_identity == manifest.campaign_id
    assert result.evidence_package_identity == manifest.evidence_package_id
    assert result.reproduction_manifest_identity == (
        manifest.selected_manifest_id
    )
    assert result.persistence_reopened is True
    assert result.errors == ()
    assert result.clean_exit is True
    assert created_mount_count == 2
    assert hashlib.sha256(fixture_archive.read_bytes()).hexdigest() == (
        original_archive_hash
    )
    assert not tuple(
        path
        for path in report_dir.rglob("*")
        if path.name == "strategy-diagnostics-v1.sqlite3"
    )


def test_installed_wave2_smoke_creates_task_and_campaign_after_install(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QT_QUICK_BACKEND", "software")
    from stock_sim.release import frontend_v2_package_entry as release_entry
    from stock_sim.release.frontend_v2_package_entry import (
        RendererLane,
        run_smoke_journey,
    )
    from stock_sim.release.frontend_v2_packaging import (
        create_package_build_plans,
        stage_packaged_wave2_release_input_fixture,
    )
    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        _open_file_backed_wave2_release_input_fixture,
        extract_sealed_wave2_release_input_fixture_archive,
        open_sealed_wave2_release_input_fixture,
    )
    from strategy_diagnostics.application import DiagnosticsApplication

    source_commit = "b" * 40
    qml_plan = create_package_build_plans(
        output_root=tmp_path / "packages",
        source_commit=source_commit,
    )[1]
    manifest = stage_packaged_wave2_release_input_fixture(qml_plan)
    fixture_archive = (
        qml_plan.distribution_dir / WAVE2_RELEASE_INPUT_FIXTURE_ARCHIVE
    )
    original_archive_hash = hashlib.sha256(
        fixture_archive.read_bytes()
    ).hexdigest()

    assert manifest.initial_diagnostic_task_count == 0
    assert manifest.initial_formal_campaign_count == 0
    assert manifest.initial_recipe_draft_count == 0
    assert manifest.initial_approved_recipe_count == 0
    assert manifest.initial_materialized_path_count == 0
    assert manifest.initial_campaign_case_count == 0
    assert manifest.authoritative_input_identities

    audited_bundle = tmp_path / "audited-wave2-input-fixture"
    extract_sealed_wave2_release_input_fixture_archive(
        archive_path=fixture_archive,
        bundle_root=audited_bundle,
    )
    audited_fixture = open_sealed_wave2_release_input_fixture(
        bundle_root=audited_bundle,
        expected_source_commit=source_commit,
    )
    try:
        assert audited_fixture.persisted_diagnostic_task_count == (
            manifest.initial_diagnostic_task_count
        )
        assert audited_fixture.persisted_formal_campaign_count == (
            manifest.initial_formal_campaign_count
        )
        with audited_fixture.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO diagnostic_campaigns ("
                    "campaign_id, campaign_type, status, schema_version, "
                    "specification_json, snapshot_json, updated_at_utc"
                    ") VALUES ("
                    "'unexpected-campaign', 'formal', 'planned', "
                    "'diagnostic_campaign.v1', '{}', '{}', "
                    "'2026-08-01T00:00:00+00:00'"
                    ")"
                )
            )
    finally:
        audited_fixture.close()
    with pytest.raises(
        RuntimeError,
        match="pre-created Formal Campaign",
    ):
        _open_file_backed_wave2_release_input_fixture(
            database_path=(
                audited_bundle / "strategy-diagnostics-v1.sqlite3"
            ),
            artifact_root=audited_bundle / "artifacts",
        )

    active_mounts: set[int] = set()
    created_mount_count = 0
    terminal_advance_quiesced = False
    terminal_mapping_iteration_active = False
    create_production_window = release_entry._create_production_window
    close_mount = release_entry._close_mount
    advance_campaign = DiagnosticsApplication.advance_diagnostic_campaign
    mapping_result_iter = MappingResult.__iter__

    def observed_create_production_window(**arguments):
        nonlocal created_mount_count
        created = create_production_window(**arguments)
        created_mount_count += 1
        active_mounts.add(id(created[2]))
        return created

    def observed_close_mount(**arguments):
        close_mount(**arguments)
        active_mounts.discard(id(arguments["host"]))

    def observed_advance_campaign(self, *arguments, **keyword_arguments):
        nonlocal terminal_advance_quiesced
        nonlocal terminal_mapping_iteration_active
        if keyword_arguments.get("max_cases") == 64:
            terminal_advance_quiesced = True
            assert not active_mounts, (
                "Installed background completion must not race live QML "
                "Adapter executor threads"
            )
            terminal_mapping_iteration_active = True
        try:
            return advance_campaign(self, *arguments, **keyword_arguments)
        finally:
            terminal_mapping_iteration_active = False

    def reject_live_terminal_mapping_iteration(self):
        if terminal_mapping_iteration_active:
            raise AssertionError(
                "Installed terminal continuation must materialize SQLAlchemy "
                "mapping rows before Python-level iteration"
            )
        return mapping_result_iter(self)

    monkeypatch.setattr(
        release_entry,
        "_create_production_window",
        observed_create_production_window,
    )
    monkeypatch.setattr(
        release_entry,
        "_close_mount",
        observed_close_mount,
    )
    monkeypatch.setattr(
        DiagnosticsApplication,
        "advance_diagnostic_campaign",
        observed_advance_campaign,
    )
    monkeypatch.setattr(
        MappingResult,
        "__iter__",
        reject_live_terminal_mapping_iteration,
    )

    report_dir = tmp_path / "installed-wave2-smoke"
    result = run_smoke_journey(
        report_dir=report_dir,
        renderer_lane=RendererLane.SOFTWARE,
        source_commit=source_commit,
        capture_images=False,
        fixture_archive_path=fixture_archive,
    )

    assert result.source_commit == source_commit
    assert result.fixture_kind == "authoritative_writable_wave3_inputs"
    assert result.strategy_selection_created_after_install is True
    assert result.recipe_draft_created_after_install is True
    assert result.recipe_validation_created_after_install is True
    assert result.recipe_approval_created_after_install is True
    assert result.reference_path_materialized_after_install is True
    assert result.scenario_set_created_after_install is True
    assert result.scenario_selection_created_after_install is True
    assert result.strategy_selection_context_identity
    assert result.recipe_draft_identity
    assert result.recipe_validation_identity
    assert result.approved_recipe_identity
    assert result.materialization_task_handle_identity
    assert result.materialized_path_identity
    assert result.materialized_scenario_identity
    assert result.terminal_campaign_case_identity == result.case_identity
    assert result.terminal_selected_campaign_case_identity == (
        result.materialized_scenario_identity
    )
    assert result.terminal_node_market_scenario_identity == (
        result.materialized_path_identity
    )
    assert result.terminal_campaign_node_lifecycle == "completed"
    assert result.terminal_case_manifest_binding_verified is True
    assert result.installed_setup_ledger_reopened is True
    assert result.reopened_installed_setup_ledger == (
        _reopened_setup_ledger(
            result.installed_recipe_draft_identities,
            result.installed_recipe_validation_identities,
            result.installed_approved_recipe_identities,
            result.installed_materialization_task_handle_identities,
            result.installed_materialized_path_identities,
            result.installed_materialized_scenario_identities,
            formal_set=result.formal_scenario_set_identity,
            scenario_selection=result.scenario_selection_context_identity,
            strategy_selection=result.strategy_selection_context_identity,
            setup_selection=result.setup_selection_context_identity,
        )
    )
    assert result.formal_scenario_set_identity
    assert result.scenario_selection_context_identity
    assert result.setup_selection_context_identity
    assert result.installed_setup_command_kinds == (
        "compare_formal_strategy_set",
        "select_formal_strategy_set",
        "create_recipe_draft",
        "validate_recipe_draft",
        "approve_recipe",
        "materialize_reference_path",
        "compose_formal_scenario_set",
        "resolve_execution_assumptions",
        "select_formal_scenario_set",
    )
    assert result.task_created_after_install is True
    assert result.campaign_created_after_install is True
    assert result.diagnostic_task_identity
    assert result.campaign_identity
    assert result.accepted_command_kinds == (
        "create_diagnostic_task",
        "revise_configuration",
        "validate_configuration",
        "approve_configuration",
        "start_formal_diagnostic_campaign",
    )
    assert len(result.task_handle_identities) >= 3
    assert result.writable_persistence_verified is True
    assert result.application_reopened is True
    assert result.background_continuation_verified is True
    assert terminal_advance_quiesced is True
    assert created_mount_count == 2
    assert not active_mounts
    assert result.task_cancel_order_isolation_verified is True
    assert result.campaign_status == "completed"
    assert result.evidence_status == "sealed"
    assert result.errors == ()
    assert result.clean_exit is True
    assert hashlib.sha256(fixture_archive.read_bytes()).hexdigest() == (
        original_archive_hash
    )
    assert not tuple(
        path
        for path in report_dir.rglob("*")
        if path.name == "strategy-diagnostics-v1.sqlite3"
    )


def test_wave2_smoke_clears_and_restores_stale_route_identities(
    monkeypatch,
):
    from stock_sim.release.frontend_v2_package_entry import (
        _configure_wave2_smoke_environment,
        _restore_environment,
    )

    identity_names = (
        "STOCKSIM_FRONTEND_V2_CAMPAIGN_ID",
        "STOCKSIM_FRONTEND_V2_RUN_ID",
        "STOCKSIM_FRONTEND_V2_STRATEGY_ID",
        "STOCKSIM_FRONTEND_V2_MARKET_SCENARIO_ID",
        "STOCKSIM_FRONTEND_V2_APPROVED_RECIPE_ID",
        "STOCKSIM_FRONTEND_V2_EVIDENCE_PACKAGE_ID",
        "STOCKSIM_FRONTEND_V2_REPRODUCTION_MANIFEST_ID",
    )
    for name in identity_names:
        monkeypatch.setenv(name, f"stale-{name.casefold()}")

    previous = _configure_wave2_smoke_environment()
    try:
        assert all(name not in os.environ for name in identity_names)
    finally:
        _restore_environment(previous)

    assert all(os.environ[name].startswith("stale-") for name in identity_names)


def test_sealed_v1_fixture_manifest_rejects_storage_tampering(tmp_path):
    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        FORMAL_V1_RELEASE_FIXTURE_MANIFEST,
        load_sealed_formal_v1_release_fixture_manifest,
    )

    bundle_root = tmp_path / "fixture"
    bundle_root.mkdir()
    retained_file = bundle_root / "v1.sqlite3"
    retained_file.write_bytes(b"sealed")
    retained_hash = hashlib.sha256(retained_file.read_bytes()).hexdigest()
    (bundle_root / FORMAL_V1_RELEASE_FIXTURE_MANIFEST).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_commit": "a" * 40,
                "campaign_id": "campaign-1",
                "selected_run_id": "run-1",
                "evidence_package_id": "evidence-1",
                "selected_manifest_id": "manifest-1",
                "artifact_hashes": ["sha256:" + "b" * 64],
                "expected_identity_graph": [
                    "campaign-1",
                    "evidence-1",
                    "manifest-1",
                    "run-1",
                ],
                "files": [
                    {
                        "relative_path": "v1.sqlite3",
                        "size_bytes": retained_file.stat().st_size,
                        "sha256": f"sha256:{retained_hash}",
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    manifest = load_sealed_formal_v1_release_fixture_manifest(
        bundle_root
    )
    assert manifest.campaign_id == "campaign-1"

    retained_file.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="inventory does not match"):
        load_sealed_formal_v1_release_fixture_manifest(bundle_root)


def test_release_fixture_identity_graph_matches_the_full_persisted_scope():
    from pathlib import Path
    from types import SimpleNamespace

    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        FileBackedFormalV1ReleaseFixture,
    )

    selected_specification = SimpleNamespace(
        strategy_id="strategy-selected",
        recipe_version_id="recipe-selected",
        materialization_hash="1" * 64,
        recipe_content_hash="2" * 64,
    )
    sibling_specification = SimpleNamespace(
        materialization_hash="7" * 64,
        recipe_content_hash="8" * 64,
    )
    selected_manifest = SimpleNamespace(
        manifest_id="manifest-selected",
        case_id="case-selected",
        run_id="run-selected",
        run_artifact_hash="3" * 64,
        evidence_artifact_hash="4" * 64,
        measurement_artifact_hash="5" * 64,
        manifest_content_hash="6" * 64,
        specification=selected_specification,
    )
    sibling_manifest = SimpleNamespace(
        manifest_id="manifest-sibling",
        case_id="case-sibling",
        run_id="run-sibling",
        run_artifact_hash="9" * 64,
        evidence_artifact_hash="a" * 64,
        measurement_artifact_hash="b" * 64,
        manifest_content_hash="c" * 64,
        specification=sibling_specification,
    )
    evidence_payload = {
        "status": "sealed",
        "measurement_artifact_hash": "d" * 64,
        "metrics": [
            {
                "strategy_id": "candidate",
                "strategy_version": "v1",
                "metric_id": "metric-1",
            }
        ],
        "comparisons": [{"comparison_id": "comparison-1"}],
        "sensitivity_curves": [{"curve_id": "curve-1"}],
        "sensitivity_breakpoints": [
            {"breakpoint_id": "breakpoint-1"}
        ],
        "diagnostic_findings": [{"finding_id": "finding-1"}],
    }
    fixture = FileBackedFormalV1ReleaseFixture(
        application=SimpleNamespace(),
        engine=SimpleNamespace(),
        campaign=SimpleNamespace(campaign_id="campaign-1"),
        selected_run=SimpleNamespace(
            run_id="run-selected",
            specification=selected_specification,
        ),
        evidence_package=SimpleNamespace(
            evidence_package_id="evidence-1",
            artifact_hash="e" * 64,
            sealed_payload=lambda: evidence_payload,
        ),
        selected_manifest=selected_manifest,
        manifests=(selected_manifest, sibling_manifest),
        database_path=Path("v1.sqlite3"),
        artifact_root=Path("artifacts"),
    )

    expected = {
        "campaign-1",
        "case-selected",
        "run-selected",
        "run-sibling",
        "strategy-selected",
        "recipe-selected",
        "evidence-1",
        "manifest-selected",
        "manifest-sibling",
        "candidate@v1",
        "metric-1",
        "comparison-1",
        "curve-1",
        "breakpoint-1",
        "finding-1",
        *fixture.raw_artifact_hashes,
    }
    assert set(fixture.expected_identity_graph) == expected


def test_sealed_v1_fixture_archive_rejects_path_traversal(tmp_path):
    import zipfile

    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        extract_sealed_formal_v1_release_fixture_archive,
    )

    archive_path = tmp_path / "unsafe.zip"
    escaped_path = tmp_path / "escaped.txt"
    with zipfile.ZipFile(archive_path, mode="w") as archive:
        archive.writestr("../escaped.txt", b"unsafe")

    with pytest.raises(RuntimeError, match="path is unsafe"):
        extract_sealed_formal_v1_release_fixture_archive(
            archive_path=archive_path,
            bundle_root=tmp_path / "extracted",
        )
    assert not escaped_path.exists()


def test_installed_smoke_uses_the_production_event_bridge_journey(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QT_QUICK_BACKEND", "software")
    monkeypatch.delenv("STOCKSIM_FRONTEND_V2", raising=False)
    from stock_sim.release.frontend_v2_package_entry import (
        RendererLane,
        run_smoke_journey,
    )

    result = run_smoke_journey(
        report_dir=tmp_path,
        renderer_lane=RendererLane.SOFTWARE,
        capture_images=True,
    )

    assert result.production_path == (
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
    )
    assert tuple(
        (
            observation.stage,
            observation.route,
            observation.run_state,
            observation.evidence_state,
            observation.run_freshness,
            observation.evidence_freshness,
        )
        for observation in result.observations
    ) == EXPECTED_JOURNEY
    assert result.campaign_identity
    assert result.case_identity
    assert result.run_identity
    assert result.strategy_identity
    assert result.approved_recipe_identity
    assert result.evidence_package_identity
    assert result.reproduction_manifest_identity
    assert result.artifact_hashes
    assert result.persistence_kind == "sqlite+json+parquet"
    assert result.persistence_reopened is True
    assert (
        result.application_read_model_interface
        == "StrategyDiagnosticsV1ApplicationReadModel/1.0"
    )
    assert result.active_feature_interfaces == (
        "StrategyLibraryFeature/1.0",
        "ScenarioLabFeature/1.0",
        "DiagnosticTasksFeature/1.0",
        "RunMonitoringFeature/1.2",
        "EvidenceAndFindingsFeature/1.1",
    )
    assert result.campaign_status == "completed"
    assert result.run_status == "completed"
    assert result.evidence_status == "sealed"
    assert result.expected_identity_graph
    assert result.diagnostic_task_identity in result.expected_identity_graph
    assert set(result.task_handle_identities).issubset(
        result.expected_identity_graph
    )
    assert (
        result.feature_identity_graph
        == result.expected_identity_graph
    )
    assert set(result.qml_identity_graph_checkpoints) == {
        stage for stage, *_ in EXPECTED_JOURNEY
    }
    assert all(
        checkpoint == result.expected_identity_graph
        for checkpoint in result.qml_identity_graph_checkpoints.values()
    )
    assert all(
        set(result.task_handle_identities).issubset(checkpoint)
        for checkpoint in result.qml_identity_graph_checkpoints.values()
    )
    assert set(result.evidence_identity_sets) == {
        "candidates",
        "metrics",
        "comparisons",
        "curves",
        "breakpoints",
        "findings",
    }
    assert len(result.persisted_manifest_identities) > 1
    assert (
        result.reproduction_manifest_identity
        in result.persisted_manifest_identities
    )
    assert len(result.persisted_run_identities) > 1
    assert result.run_identity in result.persisted_run_identities
    assert set(result.raw_artifact_hashes) == {
        value.removeprefix("sha256:")
        for value in result.artifact_hashes
    }
    assert set(
        (
            *result.persisted_manifest_identities,
            *result.persisted_run_identities,
            *result.raw_artifact_hashes,
        )
    ).issubset(result.expected_identity_graph)
    assert result.keyboard_navigation_verified is True
    assert result.accessibility_preferences_verified is True
    assert result.old_generation_rejected is True
    assert result.authoritative_reconnect_verified is True
    assert result.routes_rendered == (
        "strategy_library",
        "scenario_lab",
        "diagnostic_tasks",
        "run_monitoring",
        "evidence_and_findings",
    )
    assert result.connection_transitions == (
        "connected",
        "disconnected",
        "reconnected",
        "remounted",
        "closed",
    )
    assert result.manual_trading_action_count == 0
    assert result.read_only_context_visible is True
    assert result.errors == ()
    assert result.clean_exit is True
    assert "STOCKSIM_FRONTEND_V2" not in os.environ

    from PySide6.QtGui import QImage

    terminal_evidence = QImage(
        str(tmp_path / "terminal_evidence.png")
    )
    assert terminal_evidence.isNull() is False
    viewport_left = int(terminal_evidence.width() * 0.30)
    viewport_top = int(terminal_evidence.height() * 0.05)
    viewport_right = int(terminal_evidence.width() * 0.94)
    viewport_bottom = int(terminal_evidence.height() * 0.94)
    visible_content_pixels = sum(
        max(
            terminal_evidence.pixelColor(x, y).red(),
            terminal_evidence.pixelColor(x, y).green(),
            terminal_evidence.pixelColor(x, y).blue(),
        )
        > 25
        for y in range(viewport_top, viewport_bottom)
        for x in range(viewport_left, viewport_right)
    )
    assert visible_content_pixels > 0


def test_smoke_observation_snapshots_state_before_frame_capture(
    tmp_path,
    monkeypatch,
):
    from stock_sim.release import frontend_v2_package_entry as package_entry

    class FakeObject:
        def __init__(self, **properties):
            self.properties = properties

        def property(self, name):
            return self.properties[name]

    root = FakeObject(
        screenState="active",
        evidenceScreenState="ready",
        headline="Active diagnostic run",
        detail="Evidence is ready",
    )
    run_adapter = FakeObject(
        freshness="fresh",
        phase="ready",
        revisionText="r1",
        sourceGenerationText="g1",
    )
    evidence_adapter = FakeObject(
        freshness="fresh",
        phase="degraded",
        revisionText="r1",
    )
    host = FakeObject()
    host._run_monitoring = run_adapter
    host._evidence_and_findings = evidence_adapter

    def capture_after_freshness_timer_fires(_host, _path, **_kwargs):
        run_adapter.properties["freshness"] = "stale"
        run_adapter.properties["revisionText"] = "r2"

    monkeypatch.setattr(
        package_entry,
        "_capture_qml_frame",
        capture_after_freshness_timer_fires,
    )

    with pytest.raises(
        RuntimeError,
        match="state changed during frame capture",
    ):
        package_entry._observe_state(
            app=object(),
            root=root,
            host=host,
            report_dir=tmp_path,
            stage="active_evidence",
            route="evidence_and_findings",
            capture_images=True,
        )


def test_v2_app_context_uses_only_the_read_only_runtime_boundary(
    tmp_path,
    monkeypatch,
):
    from app.app_context import build_app_context
    from app.diagnostics_runtime_gateway import DiagnosticsRuntimeGateway
    from app.event_bridge import EventBridge

    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="live",
        event_bridge=EventBridge(subscribe_backend=False),
    )

    assert isinstance(
        context.runtime_gateway,
        DiagnosticsRuntimeGateway,
    )
    assert context.trading_service is None
    assert context.trading_controller is None
    for forbidden in (
        "submit_order",
        "cancel_order",
        "replace_order",
        "dispatch",
    ):
        assert not hasattr(context.runtime_gateway, forbidden)
    context.run_monitoring_feature.close()
    context.evidence_and_findings_feature.close()


def test_qml_production_journey_never_imports_legacy_panel_registry(
    tmp_path,
):
    script = """
import importlib.abc
from pathlib import Path
import sys

class RejectLegacyPanels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "app.panels" or fullname.startswith("app.panels."):
            raise ModuleNotFoundError(
                f"legacy panel module excluded: {fullname}"
            )
        return None

sys.meta_path.insert(0, RejectLegacyPanels())

from stock_sim.release.frontend_v2_package_entry import (
    RendererLane,
    run_smoke_journey,
)

result = run_smoke_journey(
    report_dir=Path(sys.argv[1]),
    renderer_lane=RendererLane.SOFTWARE,
    source_commit="1" * 40,
    capture_images=False,
)
assert result.production_path == (
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
)
assert result.manual_trading_action_count == 0
assert result.clean_exit is True
"""
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["QT_QUICK_BACKEND"] = "software"
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        (sys.executable, "-c", script, str(tmp_path)),
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="backslashreplace",
        timeout=480,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_widgets_rollback_smoke_never_imports_command_runtime_gateway(
    tmp_path,
):
    script = """
import builtins
import sys

original_import = builtins.__import__
forbidden_command_modules = (
    "app.runtime_gateway",
    "app.controllers.trading_controller",
    "app.services.trading_service",
    "app.panels.market.trade_dialog",
    "core.order",
    "services.order_service",
    "services.runtime_command_service",
    "stock_sim.core.order",
    "stock_sim.services.order_service",
    "stock_sim.services.runtime_command_service",
)

def reject_command_gateway(name, *args, **kwargs):
    if any(
        name == prefix or name.startswith(prefix + ".")
        for prefix in forbidden_command_modules
    ):
        raise ModuleNotFoundError(
            f"command-capable module excluded: {name}"
        )
    return original_import(name, *args, **kwargs)

builtins.__import__ = reject_command_gateway

from stock_sim.release.frontend_widgets_rollback_entry import main

raise SystemExit(
    main(
        [
            "--smoke-report-dir",
            sys.argv[1],
            "--source-commit",
            "1" * 40,
        ]
    )
)
"""
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["QT_QUICK_BACKEND"] = "software"
    completed = subprocess.run(
        (sys.executable, "-c", script, str(tmp_path)),
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(
        (tmp_path / "smoke-report.json").read_text(encoding="utf-8")
    )
    assert report["placeholder_panels"] == []
    assert report["real_panel_count"] == 8
    assert report["manual_trading_action_count"] == 0
    assert report["clean_exit"] is True


def test_clean_room_report_requires_the_complete_production_journey(
    tmp_path,
):
    renderer_lanes = {}
    for lane, graphics_api in (
        ("hardware", "Direct3D11"),
        ("software", "Software"),
    ):
        installed_recipe_drafts = [
            "RECIPE-DRAFT-RC-001",
            *(f"RECIPE-DRAFT-RC-{index:03d}" for index in range(2, 15)),
        ]
        installed_recipe_validations = [
            "RECIPE-VALIDATION-RC-001",
            *(
                f"RECIPE-VALIDATION-RC-{index:03d}"
                for index in range(2, 15)
            ),
        ]
        installed_approved_recipes = [
            "RECIPE-RC-001",
            *(f"RECIPE-RC-{index:03d}" for index in range(2, 15)),
        ]
        installed_materialization_handles = [
            "MATERIALIZATION-TASK-RC-001",
            *(
                f"MATERIALIZATION-TASK-RC-{index:03d}"
                for index in range(2, 15)
            ),
        ]
        installed_paths = [f"{index:064x}" for index in range(1, 15)]
        installed_scenarios = [
            "CAMPAIGN-CASE-RC-001",
            *(f"CAMPAIGN-CASE-RC-{index:03d}" for index in range(2, 15)),
        ]
        installed_identity_graph = sorted(
            {*_IDENTITY_GRAPH, *installed_paths}
        )
        renderer_lanes[lane] = {
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
            "recipe_draft_identity": "RECIPE-DRAFT-RC-001",
            "recipe_validation_identity": "RECIPE-VALIDATION-RC-001",
            "materialization_task_handle_identity": "MATERIALIZATION-TASK-RC-001",
            "materialized_path_identity": installed_paths[0],
            "materialized_scenario_identity": installed_scenarios[0],
            "terminal_campaign_case_identity": "CASE-RC-001",
            "terminal_selected_campaign_case_identity": (
                installed_scenarios[0]
            ),
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
            "expected_identity_graph": installed_identity_graph,
            "feature_identity_graph": installed_identity_graph,
            "qml_identity_graph_checkpoints": {
                stage: installed_identity_graph
                for stage, *_ in EXPECTED_JOURNEY
            },
            "evidence_identity_sets": _IDENTITY_SETS,
            "persisted_manifest_identities": (
                _PERSISTED_MANIFEST_IDENTITIES
            ),
            "persisted_run_identities": _PERSISTED_RUN_IDENTITIES,
            "raw_artifact_hashes": [
                *_RAW_ARTIFACT_HASHES,
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
                ) in EXPECTED_JOURNEY
            ],
            "screenshots": _write_journey_screenshots(tmp_path, lane),
            "screenshots_distinct": True,
            "manual_trading_action_count": 0,
            "read_only_context_visible": True,
            "clean_exit": True,
            "errors": [],
        }

    report_path = tmp_path / "clean-room-report.json"
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
                "renderer_lanes": renderer_lanes,
            }
        ),
        encoding="utf-8",
    )

    assert verify_clean_room_report(
        report_path,
        expected_source_commit="abc123",
        expected_archive_sha256="sha256:package",
    ) == ()

    baseline = json.loads(report_path.read_text(encoding="utf-8"))
    for field_name, compromised_value, expected_failure in (
        (
            "fixture_kind",
            "sealed_completed_v1",
            "did not use the authoritative writable Wave 3 input fixture",
        ),
        (
            "recipe_draft_created_after_install",
            False,
            "did not create a Scenario Recipe Draft after install",
        ),
        (
            "reference_path_materialized_after_install",
            False,
            "did not materialize a Reference Market Path after install",
        ),
        (
            "materialized_path_identity",
            "",
            "materialized Reference Market Path identity is unavailable",
        ),
        (
            "installed_setup_command_kinds",
            ["compare_formal_strategy_set"],
            "did not accept the exact Strategy/Recipe/Path/Scenario setup",
        ),
        (
            "installed_materialized_path_identities",
            [f"{index:064x}" for index in range(1, 14)],
            "does not contain the complete 14-case installed formal Recipe",
        ),
        (
            "materialized_scenario_identity",
            "CAMPAIGN-CASE-RC-002",
            "is not bound to the terminal installed Recipe identity",
        ),
        (
            "terminal_campaign_case_identity",
            "CASE-RC-STALE",
            "terminal Manifest execution Case identity is not bound",
        ),
        (
            "terminal_selected_campaign_case_identity",
            "CAMPAIGN-CASE-RC-STALE",
            "terminal execution Case is not bound to the selected installed",
        ),
        (
            "terminal_node_market_scenario_identity",
            f"{99:064x}",
            "terminal Campaign node is not bound to the selected installed",
        ),
        (
            "terminal_campaign_node_lifecycle",
            "running",
            "terminal Campaign node is not completed",
        ),
        (
            "terminal_case_manifest_binding_verified",
            False,
            "terminal Campaign Case to execution Case/Manifest binding was not",
        ),
        (
            "installed_setup_ledger_reopened",
            False,
            "installed setup ledger was not authoritatively re-read",
        ),
        (
            "reopened_installed_setup_ledger",
            {
                **_reopened_setup_ledger(
                    installed_recipe_drafts,
                    installed_recipe_validations,
                    installed_approved_recipes,
                    installed_materialization_handles,
                    installed_paths,
                    installed_scenarios,
                ),
                "recipe_drafts": tuple(installed_recipe_drafts[1:]),
            },
            "installed setup ledger was not authoritatively re-read",
        ),
        (
            "reopened_installed_setup_ledger",
            {
                **_reopened_setup_ledger(
                    installed_recipe_drafts,
                    installed_recipe_validations,
                    installed_approved_recipes,
                    installed_materialization_handles,
                    installed_paths,
                    installed_scenarios,
                ),
                "setup_selection_contexts": ("SETUP-SELECTION-STALE",),
            },
            "installed setup ledger was not authoritatively re-read",
        ),
        (
            "task_created_after_install",
            False,
            "did not create a Diagnostic Task after install",
        ),
        (
            "campaign_created_after_install",
            False,
            "did not create a Formal Diagnostic Campaign after install",
        ),
        (
            "diagnostic_task_identity",
            "",
            "Diagnostic Task identity is unavailable",
        ),
        (
            "accepted_command_kinds",
            ["create_diagnostic_task"],
            "did not accept the exact create/revise/validate/approve/start",
        ),
        (
            "task_handle_identities",
            ["duplicated-handle", "duplicated-handle"],
            "persistent TaskHandle identities are incomplete or invalid",
        ),
        (
            "writable_persistence_verified",
            False,
            "did not verify writable persistence",
        ),
        (
            "application_reopened",
            False,
            "did not reopen the Application over persisted state",
        ),
        (
            "background_continuation_verified",
            False,
            "did not keep the Campaign nonterminal through route",
        ),
        (
            "task_cancel_order_isolation_verified",
            False,
            "did not verify Diagnostic Task cancel/order isolation",
        ),
    ):
        compromised = json.loads(json.dumps(baseline))
        compromised["renderer_lanes"]["software"][field_name] = (
            compromised_value
        )
        report_path.write_text(json.dumps(compromised), encoding="utf-8")
        assert any(
            failure.startswith("software renderer")
            and expected_failure in failure
            for failure in verify_clean_room_report(
                report_path,
                expected_source_commit="abc123",
                expected_archive_sha256="sha256:package",
            )
        )

    compromised = json.loads(json.dumps(baseline))
    compromised["renderer_lanes"]["software"]["production_path"] = [
        "DeterministicFakeRunMonitoringAdapter",
        "JourneyWorkspaceHost",
    ]
    report_path.write_text(json.dumps(compromised), encoding="utf-8")
    assert (
        "software renderer did not use the real V1 "
        "Application-to-Feature path"
        in verify_clean_room_report(
            report_path,
            expected_source_commit="abc123",
            expected_archive_sha256="sha256:package",
        )
    )

    compromised["renderer_lanes"]["software"]["production_path"] = [
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
    ]
    compromised["is_windows_sandbox"] = False
    report_path.write_text(json.dumps(compromised), encoding="utf-8")
    assert (
        "Clean-room report was not produced by Windows Sandbox"
        in verify_clean_room_report(
            report_path,
            expected_source_commit="abc123",
            expected_archive_sha256="sha256:package",
        )
    )


REQUIRED_ACCESSIBILITY_TESTS = (
    "test_narrator_sees_named_state_progress_commands_and_no_trading_actions",
    "test_keyboard_route_actions_restore_meaningful_visible_focus_immediately",
    "test_evidence_semantics_keep_chart_narrative_and_table_on_one_revision",
    "test_state_changes_remain_distinguishable_and_repair_focus_without_color",
    "test_remount_reestablishes_meaningful_keyboard_focus_without_state_mutation",
    "test_200_percent_text_scale_scrolls_focused_content_and_reduces_motion",
    "test_shared_default_and_high_contrast_tokens_meet_wcag_aa_ratios",
    (
        "test_accessible_journey_renders_at_200_percent_in_supported_lanes"
        "[software-Software]"
    ),
    (
        "test_accessible_journey_renders_at_200_percent_in_supported_lanes"
        "[hardware-Direct3D11]"
    ),
    (
        "test_file_backed_formal_campaign_reopens_and_traces_exact_ids_"
        "through_qml"
    ),
    "test_release_evidence_records_verified_source_and_toolchain",
)


def _write_accessibility_junit(
    path,
    *,
    source_commit,
    names=REQUIRED_ACCESSIBILITY_TESTS,
):
    suite = ET.Element(
        "testsuite",
        {
            "name": "frontend-v2-accessibility",
            "tests": str(len(names)),
            "failures": "0",
            "errors": "0",
            "skipped": "0",
        },
    )
    properties = ET.SubElement(suite, "properties")
    ET.SubElement(
        properties,
        "property",
        {
            "name": "frontend_v2_source_commit",
            "value": source_commit,
        },
    )
    ET.SubElement(
        properties,
        "property",
        {
            "name": "frontend_v2_toolchain_lock_sha256",
            "value": (
                "sha256:"
                + hashlib.sha256(TOOLCHAIN_LOCK_PATH.read_bytes()).hexdigest()
            ),
        },
    )
    for name in names:
        ET.SubElement(
            suite,
            "testcase",
            {
                "classname": "frontend.accessibility",
                "name": name,
            },
        )
    ET.ElementTree(suite).write(
        path,
        encoding="utf-8",
        xml_declaration=True,
    )


def _copy_performance_evidence(root):
    source_commit = "1acb1b76c9d4d389d49087a401512499f223fd72"
    source = (
        PROJECT_ROOT
        / "docs"
        / "testing"
        / "frontend"
        / "evidence"
        / "issue-45"
        / source_commit
    )
    target = root / "performance"
    target.mkdir()
    fixture_archive = target / FORMAL_V1_RELEASE_FIXTURE_ARCHIVE
    fixture_archive.write_bytes(b"sealed-v1-fixture")
    fixture_archive_digest = (
        "sha256:"
        + hashlib.sha256(fixture_archive.read_bytes()).hexdigest()
    )
    for name in (
        "hardware.json",
        "software.json",
        "no-manual-trading.json",
    ):
        copy2(source / name, target / name)
    hardware_path = target / "hardware.json"
    software_path = target / "software.json"
    hardware = json.loads(hardware_path.read_text(encoding="utf-8"))
    software = json.loads(software_path.read_text(encoding="utf-8"))
    for report in (hardware, software):
        report["schema_version"] = 3
        report["production_path"] = [
            "PerformanceLoadProjectionReadModel",
            "DeterministicFakeStrategyLibraryAdapter",
            "DeterministicFakeScenarioLabAdapter",
            "DeterministicFakeDiagnosticTasksAdapter",
            "EventBridge",
            "LiveRunMonitoringAdapter",
            "LiveEvidenceAndFindingsAdapter",
            "JourneyWorkspaceHost",
            "StrategyLibraryPage.qml",
            "ScenarioLabPage.qml",
            "DiagnosticTasksPage.qml",
            "EvidenceChart.qml",
        ]
        report["wave3_setup_features"] = {
            "feature_interfaces": [
                "StrategyLibraryFeature/1.0",
                "ScenarioLabFeature/1.0",
            ],
            "adapters": [
                "DeterministicFakeStrategyLibraryAdapter",
                "DeterministicFakeScenarioLabAdapter",
            ],
            "routes": ["strategy_library", "scenario_lab"],
            "presentation_states": {
                "strategy_library": "ready",
                "scenario_lab": "ready",
            },
            "freshness": {
                "strategy_library": "fresh",
                "scenario_lab": "fresh",
            },
            "qml_status_roles": {
                "strategy_library": "StatusBar",
                "scenario_lab": "StatusBar",
            },
            "initial_focus_observed": {
                "strategy_library": True,
                "scenario_lab": True,
            },
            "observed_before_load": True,
            "executed_during_active_load": True,
            "accepted_setup_commands": [
                "compare_formal_strategy_set",
                "select_formal_strategy_set",
                "compose_visible_scenario_set",
            ],
            "accepted_revisions": {
                "strategy_library": [2, 3],
                "scenario_lab": [2, 3],
            },
            "comparison_count": 2,
            "strategy_selection_status": "current",
            "scenario_set_count": 1,
            "scenario_set_eligibility": "formal_campaign_eligible",
        }
        report["wave2_diagnostic_tasks"] = (
            _passing_wave2_performance_load()
        )
        report["integrated_v1_probe"] = (
            _passing_real_v1_performance_probe()
        )
        report["integrated_v1_probe"][
            "fixture_archive_digest"
        ] = fixture_archive_digest
    hardware_path.write_text(
        json.dumps(hardware),
        encoding="utf-8",
    )
    software_path.write_text(
        json.dumps(software),
        encoding="utf-8",
    )
    safety = json.loads(
        (target / "no-manual-trading.json").read_text(encoding="utf-8")
    )
    toolchain_digest = (
        "sha256:"
        + hashlib.sha256(TOOLCHAIN_LOCK_PATH.read_bytes()).hexdigest()
    )
    certification = certify_performance_evidence(
        hardware,
        software,
        safety,
        expected_source_commit=source_commit,
        expected_toolchain_digest=toolchain_digest,
    )
    (target / "certification.json").write_text(
        json.dumps(asdict(certification)),
        encoding="utf-8",
    )
    return source_commit, target


def test_mandatory_release_gates_are_recomputed_and_bound_to_one_build(
    tmp_path,
):
    source_commit, performance_dir = _copy_performance_evidence(tmp_path)
    accessibility_junit = tmp_path / "accessibility.xml"
    _write_accessibility_junit(
        accessibility_junit,
        source_commit=source_commit,
    )
    safety = json.loads(
        (performance_dir / "no-manual-trading.json").read_text(
            encoding="utf-8"
        )
    )

    evidence = write_mandatory_release_gate_evidence(
        accessibility_junit=accessibility_junit,
        performance_evidence_dir=performance_dir,
        candidate={"safety": safety},
        source_commit=source_commit,
        evidence_dir=tmp_path / "release-evidence",
    )

    assert evidence.source_commit == source_commit
    assert evidence.accessibility.status == "passed"
    assert evidence.accessibility.issue_number == 43
    assert evidence.accessibility.test_count == len(
        REQUIRED_ACCESSIBILITY_TESTS
    )
    assert evidence.safety.status == "passed"
    assert evidence.safety.issue_number == 44
    assert evidence.performance.status == "certified"
    assert evidence.performance.issue_number == 45
    assert evidence.performance.fixture_archive_sha256.startswith("sha256:")
    assert evidence.performance.hardware_report_sha256.startswith("sha256:")
    assert evidence.performance.software_report_sha256.startswith("sha256:")
    assert (
        tmp_path / "release-evidence" / "mandatory-release-gates.json"
    ).is_file()
    assert (
        tmp_path
        / "release-evidence"
        / "gates"
        / "accessibility"
        / "junit.xml"
    ).is_file()
    assert (
        tmp_path
        / "release-evidence"
        / "gates"
        / "performance"
        / FORMAL_V1_RELEASE_FIXTURE_ARCHIVE
    ).read_bytes() == b"sealed-v1-fixture"


def test_mandatory_release_gates_accept_parameterized_accessibility_cases(
    tmp_path,
):
    source_commit, performance_dir = _copy_performance_evidence(tmp_path)
    accessibility_junit = tmp_path / "accessibility.xml"
    base_name = (
        "test_shared_default_and_high_contrast_tokens_meet_wcag_aa_ratios"
    )
    parameterized_names = tuple(
        name for name in REQUIRED_ACCESSIBILITY_TESTS if name != base_name
    ) + (
        f"{base_name}[None]",
        f"{base_name}[preferences1]",
    )
    _write_accessibility_junit(
        accessibility_junit,
        source_commit=source_commit,
        names=parameterized_names,
    )
    safety = json.loads(
        (performance_dir / "no-manual-trading.json").read_text(
            encoding="utf-8"
        )
    )

    evidence = write_mandatory_release_gate_evidence(
        accessibility_junit=accessibility_junit,
        performance_evidence_dir=performance_dir,
        candidate={"safety": safety},
        source_commit=source_commit,
        evidence_dir=tmp_path / "release-evidence",
    )

    assert evidence.accessibility.status == "passed"
    assert evidence.accessibility.test_count == len(parameterized_names)


def test_mandatory_release_gates_fail_closed_on_missing_accessibility_coverage(
    tmp_path,
):
    source_commit, performance_dir = _copy_performance_evidence(tmp_path)
    accessibility_junit = tmp_path / "accessibility.xml"
    _write_accessibility_junit(
        accessibility_junit,
        source_commit=source_commit,
        names=REQUIRED_ACCESSIBILITY_TESTS[:-1],
    )
    safety = json.loads(
        (performance_dir / "no-manual-trading.json").read_text(
            encoding="utf-8"
        )
    )

    try:
        write_mandatory_release_gate_evidence(
            accessibility_junit=accessibility_junit,
            performance_evidence_dir=performance_dir,
            candidate={"safety": safety},
            source_commit=source_commit,
            evidence_dir=tmp_path / "release-evidence",
        )
    except RuntimeError as error:
        assert "accessibility coverage is incomplete" in str(error)
    else:
        raise AssertionError("Incomplete accessibility evidence was accepted")


def test_mandatory_release_gates_reject_a_tampered_performance_aggregate(
    tmp_path,
):
    source_commit, performance_dir = _copy_performance_evidence(tmp_path)
    accessibility_junit = tmp_path / "accessibility.xml"
    _write_accessibility_junit(
        accessibility_junit,
        source_commit=source_commit,
    )
    safety = json.loads(
        (performance_dir / "no-manual-trading.json").read_text(
            encoding="utf-8"
        )
    )
    certification_path = performance_dir / "certification.json"
    certification = json.loads(
        certification_path.read_text(encoding="utf-8")
    )
    certification["hardware_report_digest"] = "sha256:" + "0" * 64
    certification_path.write_text(
        json.dumps(certification),
        encoding="utf-8",
    )

    try:
        write_mandatory_release_gate_evidence(
            accessibility_junit=accessibility_junit,
            performance_evidence_dir=performance_dir,
            candidate={"safety": safety},
            source_commit=source_commit,
            evidence_dir=tmp_path / "release-evidence",
        )
    except RuntimeError as error:
        assert "performance aggregate does not match raw evidence" in str(
            error
        )
    else:
        raise AssertionError("Tampered performance evidence was accepted")


def test_mandatory_release_gates_reject_a_tampered_v1_fixture_archive(
    tmp_path,
):
    source_commit, performance_dir = _copy_performance_evidence(tmp_path)
    accessibility_junit = tmp_path / "accessibility.xml"
    _write_accessibility_junit(
        accessibility_junit,
        source_commit=source_commit,
    )
    safety = json.loads(
        (performance_dir / "no-manual-trading.json").read_text(
            encoding="utf-8"
        )
    )
    (
        performance_dir / FORMAL_V1_RELEASE_FIXTURE_ARCHIVE
    ).write_bytes(b"tampered-v1-fixture")

    with pytest.raises(
        RuntimeError,
        match="does not match the retained fixture archive checksum",
    ):
        write_mandatory_release_gate_evidence(
            accessibility_junit=accessibility_junit,
            performance_evidence_dir=performance_dir,
            candidate={"safety": safety},
            source_commit=source_commit,
            evidence_dir=tmp_path / "release-evidence",
        )


def test_mandatory_release_gates_reject_unbound_accessibility_evidence(
    tmp_path,
):
    source_commit, performance_dir = _copy_performance_evidence(tmp_path)
    accessibility_junit = tmp_path / "accessibility.xml"
    _write_accessibility_junit(
        accessibility_junit,
        source_commit="0" * 40,
    )
    safety = json.loads(
        (performance_dir / "no-manual-trading.json").read_text(
            encoding="utf-8"
        )
    )

    try:
        write_mandatory_release_gate_evidence(
            accessibility_junit=accessibility_junit,
            performance_evidence_dir=performance_dir,
            candidate={"safety": safety},
            source_commit=source_commit,
            evidence_dir=tmp_path / "release-evidence",
        )
    except RuntimeError as error:
        assert "accessibility source identity" in str(error)
    else:
        raise AssertionError("Mismatched accessibility source was accepted")


def test_windows_sandbox_runner_is_offline_bounded_and_self_terminating():
    script = (
        PROJECT_ROOT
        / "scripts"
        / "run_frontend_v2_windows_sandbox.ps1"
    ).read_text(encoding="utf-8")

    assert "WindowsSandbox.exe" in script
    assert "<Networking>Disable</Networking>" in script
    assert "<VGpu>Enable</VGpu>" in script
    assert "<ReadOnly>true</ReadOnly>" in script
    assert "run_frontend_v2_clean_room.ps1" in script
    assert "WidgetsPackageArchive" in script
    assert "ExpectedWidgetsArchiveSha256" in script
    assert "C:\\ReleaseInputWidgets" in script
    assert "1200" in script
    assert "sandbox-exit-code.txt" in script
    assert "shutdown.exe /s /t 0" in script
    assert "Test-Path -LiteralPath $exitCodePath" in script
    assert "Start-Sleep -Milliseconds 500" in script
    assert "WaitForExit" not in script
    assert "$sandboxShutdownDeadline" in script
    assert "$remainingSandboxProcesses" in script
    assert "TimeoutSeconds" in script
    assert "clean-room-report.json" in script
    assert "'^[0-9a-f]{40}$'" in script
    assert "'^sha256:[0-9a-f]{64}$'" in script
    assert "'^[A-Za-z0-9][A-Za-z0-9._-]*$'" in script


def test_default_installed_entry_uses_the_production_app_context():
    source = (
        PROJECT_ROOT
        / "stock_sim"
        / "release"
        / "frontend_v2_package_entry.py"
    ).read_text(encoding="utf-8")

    assert "DeterministicFake" not in source
    assert "_ReleaseCandidateRuntimeQueries" not in source
    assert "get_evidence_and_findings_snapshot" not in source
    assert "create_file_backed_formal_v1_release_fixture" in source
    assert "open_sealed_formal_v1_release_fixture" in source
    assert "_installed_fixture_archive_path" in source
    assert "--ptrade-host-worker" not in source
    assert "SubprocessPTradeStrategyHost" not in source
    assert "LiveStrategyDiagnosticsV1ApplicationAdapter" in source
    assert "from app.app_context import build_app_context" in source
    assert "from app.ui.main_window import MainWindow" in source
    assert "_UnavailableRuntimeQueries" not in source
    assert "window = QMainWindow()" not in source
    assert source.index(
        '"EventBridge",\n        bridge.stop,'
    ) < source.index("    bridge.start()")


def test_installed_entry_avoids_compiled_qt_test_and_accessibility_introspection():
    source = (
        PROJECT_ROOT
        / "stock_sim"
        / "release"
        / "frontend_v2_package_entry.py"
    ).read_text(encoding="utf-8")

    assert "QTest" not in source
    assert "QAccessible" not in source
    assert "QKeyEvent" in source


def test_packaged_accessible_names_have_one_authoritative_qml_source():
    entry_source = (
        PROJECT_ROOT
        / "stock_sim"
        / "release"
        / "frontend_v2_package_entry.py"
    ).read_text(encoding="utf-8")
    journey_source = (
        PROJECT_ROOT / "app" / "ui" / "qml" / "JourneyWorkspace.qml"
    ).read_text(encoding="utf-8")
    chart_source = (
        PROJECT_ROOT / "app" / "ui" / "qml" / "EvidenceChart.qml"
    ).read_text(encoding="utf-8")

    assert "_PACKAGED_ACCESSIBLE_NAME_BY_OBJECT_NAME" not in entry_source
    assert journey_source.count(
        "Accessible.name: accessibleName"
    ) == 5
    assert journey_source.count(
        "Accessible.description: accessibleDescription"
    ) == 5
    assert "Accessible.name: accessibleName" in chart_source
    assert "Accessible.description: accessibleDescription" in chart_source


def test_packaged_no_trading_inventory_fails_closed_without_semantics():
    from stock_sim.release.frontend_v2_package_entry import (
        _unapproved_interactive_action_count,
    )

    class MetaObject:
        def __init__(self, property_names):
            self.property_names = frozenset(property_names)

        def indexOfProperty(self, property_name):
            return 0 if property_name in self.property_names else -1

    class Item:
        def __init__(self, **properties):
            self.properties = properties
            self._meta = MetaObject(properties)

        def metaObject(self):
            return self._meta

        def property(self, property_name):
            return self.properties.get(property_name)

    class Root(Item):
        def __init__(self, children):
            super().__init__(
                objectName="root",
                activeFocusOnTab=False,
            )
            self.children = children

        def findChildren(self, _object_type):
            return self.children

    approved_action = Item(
        objectName="approvedAction",
        activeFocusOnTab=True,
        accessibleName="Open Diagnostic Tasks",
    )
    missing_semantics = Item(
        objectName="unknownKeyboardAction",
        activeFocusOnTab=True,
    )
    known_text_input = Item(
        objectName="diagnosticTaskApprovalActorInput",
        activeFocusOnTab=True,
    )

    assert _unapproved_interactive_action_count(
        Root((approved_action, missing_semantics, known_text_input))
    ) == 1


def test_release_certification_does_not_expand_the_application_command_api():
    import inspect

    from strategy_diagnostics.application import DiagnosticsApplication

    parameters = inspect.signature(
        DiagnosticsApplication.create_manual_recipe_draft
    ).parameters

    assert "recipe_id" not in parameters


def test_release_packaging_has_no_secondary_process_fixture_path():
    source = (
        PROJECT_ROOT
        / "stock_sim"
        / "release"
        / "frontend_v2_packaging.py"
    ).read_text(encoding="utf-8")

    assert "SubprocessPTradeStrategyHost" not in source


def test_compiled_smoke_defaults_to_the_packaged_wave2_input_fixture(
    tmp_path,
    monkeypatch,
):
    from stock_sim.release import frontend_v2_package_entry as package_entry
    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        WAVE2_RELEASE_INPUT_FIXTURE_ARCHIVE,
    )

    executable = tmp_path / "installed" / "UTI-Frontend-V2.exe"
    monkeypatch.setitem(package_entry.__dict__, "__compiled__", object())
    monkeypatch.setattr(package_entry.sys, "argv", [str(executable)])
    observed = {}

    class PassingSmoke:
        errors = ()
        clean_exit = True
        manual_trading_action_count = 0
        read_only_context_visible = True
        fixture_kind = "authoritative_writable_wave3_inputs"
        strategy_selection_created_after_install = True
        recipe_draft_created_after_install = True
        recipe_validation_created_after_install = True
        recipe_approval_created_after_install = True
        reference_path_materialized_after_install = True
        scenario_set_created_after_install = True
        scenario_selection_created_after_install = True
        strategy_selection_context_identity = "strategy-selection-installed"
        recipe_draft_identity = "recipe-draft-installed-01"
        recipe_validation_identity = "recipe-validation-installed-01"
        approved_recipe_identity = "recipe-version-installed-01"
        materialization_task_handle_identity = "materialize-installed-01"
        materialized_path_identity = f"{1:064x}"
        materialized_scenario_identity = "campaign-case-installed-01"
        case_identity = "sensitivity-case-installed-01"
        terminal_campaign_case_identity = case_identity
        terminal_selected_campaign_case_identity = (
            materialized_scenario_identity
        )
        terminal_node_market_scenario_identity = materialized_path_identity
        terminal_campaign_node_lifecycle = "completed"
        terminal_case_manifest_binding_verified = True
        formal_scenario_set_identity = "formal-scenario-set-installed"
        scenario_selection_context_identity = "scenario-selection-installed"
        setup_selection_context_identity = "setup-selection-installed"
        installed_setup_command_kinds = (
            "compare_formal_strategy_set",
            "select_formal_strategy_set",
            "create_recipe_draft",
            "validate_recipe_draft",
            "approve_recipe",
            "materialize_reference_path",
            "compose_formal_scenario_set",
            "resolve_execution_assumptions",
            "select_formal_scenario_set",
        )
        installed_recipe_draft_identities = tuple(
            f"recipe-draft-installed-{index:02d}"
            for index in range(1, 15)
        )
        installed_recipe_validation_identities = tuple(
            f"recipe-validation-installed-{index:02d}"
            for index in range(1, 15)
        )
        installed_approved_recipe_identities = tuple(
            f"recipe-version-installed-{index:02d}"
            for index in range(1, 15)
        )
        installed_materialization_task_handle_identities = tuple(
            f"materialize-installed-{index:02d}"
            for index in range(1, 15)
        )
        installed_materialized_path_identities = tuple(
            f"{index:064x}" for index in range(1, 15)
        )
        installed_materialized_scenario_identities = tuple(
            f"campaign-case-installed-{index:02d}"
            for index in range(1, 15)
        )
        installed_setup_ledger_reopened = True
        reopened_installed_setup_ledger = _reopened_setup_ledger(
            installed_recipe_draft_identities,
            installed_recipe_validation_identities,
            installed_approved_recipe_identities,
            installed_materialization_task_handle_identities,
            installed_materialized_path_identities,
            installed_materialized_scenario_identities,
            formal_set=formal_scenario_set_identity,
            scenario_selection=scenario_selection_context_identity,
            strategy_selection=strategy_selection_context_identity,
            setup_selection=setup_selection_context_identity,
        )
        task_created_after_install = True
        campaign_created_after_install = True
        diagnostic_task_identity = "diagnostic-task-installed"
        accepted_command_kinds = (
            "create_diagnostic_task",
            "revise_configuration",
            "validate_configuration",
            "approve_configuration",
            "start_formal_diagnostic_campaign",
        )
        task_handle_identities = (
            "diagnostic-task-handle-create",
            "diagnostic-task-handle-validate",
            "diagnostic-task-handle-start",
        )
        writable_persistence_verified = True
        application_reopened = True
        background_continuation_verified = True
        task_cancel_order_isolation_verified = True

    def record_smoke(**arguments):
        observed.update(arguments)
        return PassingSmoke()

    monkeypatch.setattr(package_entry, "run_smoke_journey", record_smoke)

    exit_code = package_entry.main(
        (
            "--renderer-lane=software",
            f"--smoke-report-dir={tmp_path / 'report'}",
            f"--source-commit={'a' * 40}",
            "--no-images",
        )
    )

    assert exit_code == 0
    assert observed["fixture_archive_path"] == (
        executable.parent / WAVE2_RELEASE_INPUT_FIXTURE_ARCHIVE
    )
    assert observed["defer_native_teardown"] is True

    class MissingRecipeFamilySmoke(PassingSmoke):
        installed_materialized_scenario_identities = (
            PassingSmoke.installed_materialized_scenario_identities[:-1]
        )

    monkeypatch.setattr(
        package_entry,
        "run_smoke_journey",
        lambda **_arguments: MissingRecipeFamilySmoke(),
    )
    assert (
        package_entry.main(
            (
                "--renderer-lane=software",
                f"--smoke-report-dir={tmp_path / 'incomplete-recipes'}",
                f"--source-commit={'a' * 40}",
                "--no-images",
            )
        )
        == 1
    )

    class MissingReopenedSetupLedgerSmoke(PassingSmoke):
        reopened_installed_setup_ledger = {
            **PassingSmoke.reopened_installed_setup_ledger,
            "recipe_drafts": (
                PassingSmoke.installed_recipe_draft_identities[1:]
            ),
        }

    monkeypatch.setattr(
        package_entry,
        "run_smoke_journey",
        lambda **_arguments: MissingReopenedSetupLedgerSmoke(),
    )
    assert (
        package_entry.main(
            (
                "--renderer-lane=software",
                f"--smoke-report-dir={tmp_path / 'missing-reopen-ledger'}",
                f"--source-commit={'a' * 40}",
                "--no-images",
            )
        )
        == 1
    )

    class MissingTaskHandlesSmoke(PassingSmoke):
        task_handle_identities = ()

    monkeypatch.setattr(
        package_entry,
        "run_smoke_journey",
        lambda **_arguments: MissingTaskHandlesSmoke(),
    )
    assert (
        package_entry.main(
            (
                "--renderer-lane=software",
                f"--smoke-report-dir={tmp_path / 'incomplete-report'}",
                f"--source-commit={'a' * 40}",
                "--no-images",
            )
        )
        == 1
    )

    class MissingBackgroundContinuationSmoke(PassingSmoke):
        background_continuation_verified = False

    monkeypatch.setattr(
        package_entry,
        "run_smoke_journey",
        lambda **_arguments: MissingBackgroundContinuationSmoke(),
    )
    assert (
        package_entry.main(
            (
                "--renderer-lane=software",
                f"--smoke-report-dir={tmp_path / 'no-background-report'}",
                f"--source-commit={'a' * 40}",
                "--no-images",
            )
        )
        == 1
    )


def test_release_smoke_stops_bridge_before_final_fixture_disposal(
    tmp_path,
    monkeypatch,
):
    from app.event_bridge import EventBridge
    from stock_sim.release import frontend_v2_package_entry as release_entry
    from stock_sim.release.frontend_v2_package_entry import RendererLane
    from stock_sim.release.frontend_v2_packaging import (
        create_package_build_plans,
        stage_packaged_formal_v1_release_fixture,
    )
    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        FORMAL_V1_RELEASE_FIXTURE_ARCHIVE,
        FileBackedFormalV1ReleaseFixture,
    )

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QT_QUICK_BACKEND", "software")
    bridge_stopped = False
    quiesced_mount_count = 0
    scheduled_mount_count = 0
    start_bridge = EventBridge.start
    stop_bridge = EventBridge.stop
    close_fixture = FileBackedFormalV1ReleaseFixture.close
    close_mount = release_entry._close_mount
    schedule_closed_mount_release = (
        release_entry._schedule_closed_mount_release
    )
    source_commit = "c" * 40
    qml_plan = create_package_build_plans(
        output_root=tmp_path / "packages",
        source_commit=source_commit,
    )[1]
    stage_packaged_formal_v1_release_fixture(qml_plan)
    fixture_archive = (
        qml_plan.distribution_dir / FORMAL_V1_RELEASE_FIXTURE_ARCHIVE
    )

    def observed_stop(bridge):
        nonlocal bridge_stopped
        stop_bridge(bridge)
        bridge_stopped = True

    def observed_close(fixture):
        assert bridge_stopped, (
            "The EventBridge thread must stop before final fixture disposal"
        )
        assert quiesced_mount_count > 0
        assert scheduled_mount_count == quiesced_mount_count, (
            "Every retired native QML mount must be scheduled for owned "
            "application shutdown before final "
            "fixture disposal; "
            f"quiesced={quiesced_mount_count}, "
            f"scheduled={scheduled_mount_count}"
        )
        assert observed_bridge._running is False
        assert (
            observed_bridge._th is None
            or not observed_bridge._th.is_alive()
        )
        close_fixture(fixture)

    def observed_close_mount(**kwargs):
        nonlocal quiesced_mount_count
        close_mount(**kwargs)
        quiesced_mount_count += 1

    def observed_schedule_closed_mount_release(**kwargs):
        nonlocal scheduled_mount_count
        assert bridge_stopped, (
            "Native QML objects must not be force-released while the "
            "EventBridge worker is still alive"
        )
        assert observed_bridge is not None
        assert (
            observed_bridge._th is None
            or not observed_bridge._th.is_alive()
        )
        schedule_closed_mount_release(**kwargs)
        scheduled_mount_count += 1

    monkeypatch.setattr(EventBridge, "stop", observed_stop)
    monkeypatch.setattr(
        release_entry,
        "_close_mount",
        observed_close_mount,
    )
    monkeypatch.setattr(
        release_entry,
        "_schedule_closed_mount_release",
        observed_schedule_closed_mount_release,
    )
    monkeypatch.setattr(
        FileBackedFormalV1ReleaseFixture,
        "close",
        observed_close,
    )
    observed_bridge = None

    def capture_bridge_start(bridge):
        nonlocal observed_bridge
        observed_bridge = bridge
        start_bridge(bridge)

    monkeypatch.setattr(EventBridge, "start", capture_bridge_start)

    result = release_entry.run_smoke_journey(
        report_dir=tmp_path / "bridge-before-fixture",
        renderer_lane=RendererLane.SOFTWARE,
        source_commit=source_commit,
        capture_images=False,
        fixture_archive_path=fixture_archive,
    )

    assert result.clean_exit is True
    assert result.errors == ()


def test_release_file_backed_fixture_close_is_idempotent(
    tmp_path,
    monkeypatch,
):
    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        create_file_backed_formal_v1_release_fixture,
        create_file_backed_wave2_release_input_fixture,
    )

    fixtures = (
        create_file_backed_formal_v1_release_fixture(
            database_path=tmp_path / "formal" / "fixture.sqlite3",
            artifact_root=tmp_path / "formal" / "artifacts",
        ),
        create_file_backed_wave2_release_input_fixture(
            database_path=tmp_path / "wave2" / "fixture.sqlite3",
            artifact_root=tmp_path / "wave2" / "artifacts",
        ),
    )
    for fixture in fixtures:
        dispose_calls = 0
        dispose = fixture.engine.dispose

        def observed_dispose():
            nonlocal dispose_calls
            dispose_calls += 1
            dispose()

        monkeypatch.setattr(fixture.engine, "dispose", observed_dispose)
        fixture.close()
        fixture.close()

        assert dispose_calls == 1
        assert fixture.closed is True


def test_compiled_release_fixture_close_defers_native_engine_disposal(
    tmp_path,
    monkeypatch,
):
    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        create_file_backed_formal_v1_release_fixture,
        create_file_backed_wave2_release_input_fixture,
    )

    fixtures = (
        create_file_backed_formal_v1_release_fixture(
            database_path=tmp_path / "formal" / "fixture.sqlite3",
            artifact_root=tmp_path / "formal" / "artifacts",
        ),
        create_file_backed_wave2_release_input_fixture(
            database_path=tmp_path / "wave2" / "fixture.sqlite3",
            artifact_root=tmp_path / "wave2" / "artifacts",
        ),
    )
    for fixture in fixtures:
        dispose_calls = 0

        def observed_dispose():
            nonlocal dispose_calls
            dispose_calls += 1

        monkeypatch.setattr(fixture.engine, "dispose", observed_dispose)
        fixture.close(dispose_engine=False)
        fixture.close(dispose_engine=False)

        assert dispose_calls == 0
        assert fixture.closed is True
        assert fixture.engine_disposed is False

        fixture.close()

        assert dispose_calls == 1
        assert fixture.engine_disposed is True


def test_compiled_smoke_retains_deferred_fixture_until_process_exit():
    import gc
    import weakref

    from stock_sim.release import frontend_v2_package_entry as release_entry

    class DeferredFixture:
        def __init__(self) -> None:
            self.closed = False
            self.dispose_engine = None

        def close(self, *, dispose_engine=True) -> None:
            self.closed = True
            self.dispose_engine = dispose_engine

    fixture = DeferredFixture()
    fixture_reference = weakref.ref(fixture)
    retained_count = len(
        release_entry._PROCESS_EXIT_RETAINED_NATIVE_RESOURCES
    )

    try:
        release_entry._close_release_fixture(
            fixture,
            defer_native_teardown=True,
        )
        del fixture
        gc.collect()

        assert fixture_reference() is not None
        assert fixture_reference().closed is True
        assert fixture_reference().dispose_engine is False
    finally:
        del release_entry._PROCESS_EXIT_RETAINED_NATIVE_RESOURCES[
            retained_count:
        ]


def test_release_serialization_uses_the_shared_application_gate_directly():
    from app.features._diagnostics_application_access import (
        shared_diagnostics_application_access_gate,
    )
    from stock_sim.release.frontend_v2_package_entry import (
        _serialized_application_access,
    )

    class Application:
        pass

    application = Application()

    assert _serialized_application_access(application) is (
        shared_diagnostics_application_access_gate(application)
    )


def test_compiled_smoke_retains_production_mount_owners_until_process_exit(
    tmp_path,
):
    from stock_sim.release.frontend_v2_packaging import (
        create_package_build_plans,
        stage_packaged_wave2_release_input_fixture,
    )

    audit_path = tmp_path / "compiled-process-lifetime-audit.json"
    source_commit = "d" * 40
    qml_plan = create_package_build_plans(
        output_root=tmp_path / "packages",
        source_commit=source_commit,
    )[1]
    stage_packaged_wave2_release_input_fixture(qml_plan)
    fixture_archive = (
        qml_plan.distribution_dir / WAVE2_RELEASE_INPUT_FIXTURE_ARCHIVE
    )
    short_runtime_root = Path(mkdtemp(prefix="uti-i62-"))
    script = r"""
import json
import os
from pathlib import Path
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"

from stock_sim.release import frontend_v2_package_entry as release_entry

created_mount_ids = []
closed_fixture_ids = []
create_production_window = release_entry._create_production_window
close_release_fixture = release_entry._close_release_fixture

def observed_create_production_window(**arguments):
    created = create_production_window(**arguments)
    created_mount_ids.append(tuple(id(owner) for owner in created))
    return created

def observed_close_release_fixture(fixture, *, defer_native_teardown):
    closed_fixture_ids.append(id(fixture))
    close_release_fixture(
        fixture,
        defer_native_teardown=defer_native_teardown,
    )

release_entry._create_production_window = observed_create_production_window
release_entry._close_release_fixture = observed_close_release_fixture
result = release_entry.run_smoke_journey(
    report_dir=Path(sys.argv[1]),
    renderer_lane=release_entry.RendererLane.SOFTWARE,
    source_commit=sys.argv[3],
    capture_images=False,
    fixture_archive_path=Path(sys.argv[4]),
    defer_native_teardown=True,
)
retained_ids = {
    id(resource)
    for resource in release_entry._PROCESS_EXIT_RETAINED_NATIVE_RESOURCES
}
payload = {
    "clean_exit": result.clean_exit,
    "errors": list(result.errors),
    "process_exit_environment_retained": (
        os.environ.get("STOCKSIM_FRONTEND_V2") == "1"
        and os.environ.get("STOCKSIM_TEXT_SCALE_PERCENT") == "200"
        and os.environ.get("STOCKSIM_REDUCED_MOTION") == "1"
        and os.environ.get("STOCKSIM_HIGH_CONTRAST") == "1"
    ),
    "mount_count": len(created_mount_ids),
    "mount_owners_retained": all(
        owner_id in retained_ids
        for mount_ids in created_mount_ids
        for owner_id in mount_ids
    ),
    "fixture_count": len(set(closed_fixture_ids)),
    "fixtures_retained": all(
        fixture_id in retained_ids
        for fixture_id in closed_fixture_ids
    ),
}
Path(sys.argv[2]).write_text(
    json.dumps(payload, sort_keys=True),
    encoding="utf-8",
)
release_entry._run_process_entry(
    compiled=True,
    arguments=("--smoke-report-dir=" + sys.argv[1],),
    run=lambda: (
        0
        if (
            payload["clean_exit"]
            and not payload["errors"]
            and payload["process_exit_environment_retained"]
            and payload["mount_count"] == 2
            and payload["mount_owners_retained"]
            and payload["fixture_count"] >= 3
            and payload["fixtures_retained"]
        )
        else 1
    ),
)
"""
    try:
        completed = subprocess.run(
            (
                sys.executable,
                "-c",
                script,
                str(short_runtime_root / "report"),
                str(audit_path),
                source_commit,
                str(fixture_archive),
            ),
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=900,
        )

        assert completed.returncode == 0, completed.stderr
        assert json.loads(audit_path.read_text(encoding="utf-8")) == {
            "clean_exit": True,
            "errors": [],
            "fixture_count": 3,
            "fixtures_retained": True,
            "mount_count": 2,
            "mount_owners_retained": True,
            "process_exit_environment_retained": True,
        }
    finally:
        rmtree(short_runtime_root, ignore_errors=True)


def test_compiled_fixture_persistence_is_owned_by_the_report_directory(
    tmp_path,
):
    from contextlib import ExitStack

    from sqlalchemy import create_engine, text

    from stock_sim.release.frontend_v2_package_entry import (
        _packaged_fixture_persistence_root,
    )

    report_dir = tmp_path / "installed-smoke-report"
    lifecycle_checks = []
    with ExitStack() as cleanup:
        persistence_root = _packaged_fixture_persistence_root(
            report_dir=report_dir,
            cleanup=cleanup,
            lifecycle_checks=lifecycle_checks,
            defer_native_teardown=True,
            temporary_directory_prefix="uti-wave2-runtime-",
        )
        persistence_root.mkdir(parents=True)
        database_path = persistence_root / "fixture.sqlite3"
        engine = create_engine(f"sqlite:///{database_path}")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE probe (value INTEGER)"))

    assert persistence_root == report_dir / "v1-persistence"
    assert database_path.exists()
    assert lifecycle_checks == []
    engine.dispose()


def test_release_smoke_quiesces_qml_before_closing_live_features():
    from stock_sim.release.frontend_v2_package_entry import (
        _close_mount,
        _mount_is_closed,
    )

    events: list[str] = []

    class Feature:
        _closed = False

        def __init__(self, name):
            self.name = name

        def close(self):
            events.append(self.name)
            self._closed = True

    class Host:
        _workspace_closed = False

        def close_adapter(self, *, unload_qml=True):
            events.append(f"adapter:unload={unload_qml}")
            self._workspace_closed = True

    class Window:
        visible = True

        def hide(self):
            events.append("window-hide")
            self.visible = False

        def close(self):
            events.append("window")
            self.visible = False

        def deleteLater(self):
            raise AssertionError(
                "A mounted QObject must not be deleted while Python "
                "references remain live"
            )

        def isVisible(self):
            return self.visible

    class App:
        def sendPostedEvents(self, *_args):
            raise AssertionError(
                "The release journey must not force deferred QObject "
                "deletion"
            )

        def processEvents(self):
            events.append("process-events")

    context = type(
        "Context",
        (),
        {
            "strategy_library_feature": Feature("strategy-feature"),
            "scenario_lab_feature": Feature("scenario-feature"),
            "diagnostic_tasks_feature": Feature("diagnostic-feature"),
            "run_monitoring_feature": Feature("run-feature"),
            "evidence_and_findings_feature": Feature("evidence-feature"),
        },
    )()
    host = Host()
    window = Window()

    _close_mount(
        app=App(),
        context=context,
        window=window,
        host=host,
    )

    assert events == [
        "window-hide",
        "process-events",
        "adapter:unload=False",
        "process-events",
        "window",
        "process-events",
        "strategy-feature",
        "scenario-feature",
        "diagnostic-feature",
        "run-feature",
        "evidence-feature",
        "process-events",
    ]
    assert _mount_is_closed(context, window, host) is True


def test_release_smoke_repeats_real_qt_journey_in_one_process(tmp_path):
    script = r"""
import json
import os
from pathlib import Path
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"

from stock_sim.release.frontend_v2_package_entry import (
    RendererLane,
    run_smoke_journey,
)

root = Path(sys.argv[1])
results = [
    run_smoke_journey(
        report_dir=root / f"journey-{index}",
        renderer_lane=RendererLane.SOFTWARE,
        capture_images=False,
    )
    for index in range(2)
]
payload = [
    {
        "clean_exit": result.clean_exit,
        "errors": list(result.errors),
    }
    for result in results
]
print(json.dumps(payload, sort_keys=True))
raise SystemExit(
    0
    if all(result.clean_exit and not result.errors for result in results)
    else 1
)
"""
    completed = subprocess.run(
        (sys.executable, "-c", script, str(tmp_path)),
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=900,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [
        {"clean_exit": True, "errors": []},
        {"clean_exit": True, "errors": []},
    ]


def test_release_smoke_main_shuts_down_its_owned_qapplication(tmp_path):
    from stock_sim.release.frontend_v2_packaging import (
        create_package_build_plans,
        stage_packaged_wave2_release_input_fixture,
    )
    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        WAVE2_RELEASE_INPUT_FIXTURE_ARCHIVE,
    )

    source_commit = "d" * 40
    qml_plan = create_package_build_plans(
        output_root=tmp_path / "packages",
        source_commit=source_commit,
    )[1]
    stage_packaged_wave2_release_input_fixture(qml_plan)
    fixture_archive = (
        qml_plan.distribution_dir / WAVE2_RELEASE_INPUT_FIXTURE_ARCHIVE
    )
    script = r"""
import json
import os
from pathlib import Path
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"

from PySide6.QtWidgets import QApplication
from stock_sim.release.frontend_v2_package_entry import main

exit_code = main(
    (
        "--renderer-lane",
        "software",
        "--smoke-report-dir",
        str(Path(sys.argv[1]) / "main-owned-application"),
        "--fixture-archive",
        sys.argv[2],
        "--source-commit",
        sys.argv[3],
        "--no-images",
    )
)
print(
    json.dumps(
        {
            "application_shutdown": QApplication.instance() is None,
            "exit_code": exit_code,
        },
        sort_keys=True,
    )
)
raise SystemExit(
    0
    if exit_code == 0 and QApplication.instance() is None
    else 1
)
"""
    environment = os.environ.copy()
    environment["PYTHONFAULTHANDLER"] = "1"
    completed = subprocess.run(
        (
            sys.executable,
            "-c",
            script,
            str(tmp_path),
            str(fixture_archive),
            source_commit,
        ),
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=900,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "application_shutdown": True,
        "exit_code": 0,
    }


def test_smoke_application_shutdown_survives_earlier_cleanup_error(
    monkeypatch,
):
    from PySide6.QtWidgets import QApplication
    from stock_sim.release.frontend_v2_package_entry import (
        _shutdown_smoke_application,
    )

    events: list[str] = []

    class Application:
        shutdown_complete = False

        def closeAllWindows(self):
            events.append("close-all-windows")
            raise RuntimeError("window cleanup failed")

        def processEvents(self):
            events.append("process-events")

        def shutdown(self):
            events.append("shutdown")
            self.shutdown_complete = True

    app = Application()
    monkeypatch.setattr(
        QApplication,
        "instance",
        lambda: None if app.shutdown_complete else app,
    )
    errors: list[str] = []

    _shutdown_smoke_application(errors)

    assert events == [
        "close-all-windows",
        "shutdown",
    ]
    assert errors == [
        "QApplication closeAllWindows failed: RuntimeError",
    ]


def test_compiled_smoke_defers_all_qt_shutdown_to_process_exit(
    monkeypatch,
):
    from PySide6.QtWidgets import QApplication
    from stock_sim.release.frontend_v2_package_entry import (
        _shutdown_smoke_application,
    )

    events: list[str] = []

    class Application:
        def closeAllWindows(self):
            raise AssertionError(
                "compiled smoke must terminate before Qt window teardown"
            )

        def shutdown(self):
            raise AssertionError(
                "compiled smoke must terminate before Qt static shutdown"
            )

    app = Application()
    monkeypatch.setattr(QApplication, "instance", lambda: app)
    errors: list[str] = []

    _shutdown_smoke_application(
        errors,
        run_qt_teardown=False,
    )

    assert events == []
    assert errors == []


def test_terminal_campaign_does_not_advance_after_mount_quiescence_failure():
    from stock_sim.release.frontend_v2_package_entry import (
        _advance_installed_wave2_campaign_after_mount_quiescence,
    )

    class Application:
        advanced = False

        def advance_diagnostic_campaign(self, *_arguments, **_keyword_arguments):
            self.advanced = True
            raise AssertionError(
                "backend continuation must remain blocked after close failure"
            )

    application = Application()
    cleanup_errors: list[str] = []

    def failed_mount_close() -> None:
        cleanup_errors.append(
            "Run Monitoring Feature cleanup failed: RuntimeError"
        )

    with pytest.raises(
        RuntimeError,
        match="terminal continuation mount quiescence failed",
    ):
        _advance_installed_wave2_campaign_after_mount_quiescence(
            application=application,
            campaign_id="diagnostic-campaign-quiescence-probe",
            close_mount=failed_mount_close,
            stop_event_bridge=lambda: pytest.fail(
                "EventBridge must remain running until mount close succeeds"
            ),
            cleanup_errors=cleanup_errors,
        )

    assert application.advanced is False


def test_terminal_campaign_stops_event_bridge_before_backend_continuation():
    from types import SimpleNamespace

    from stock_sim.release.frontend_v2_package_entry import (
        _advance_installed_wave2_campaign_after_mount_quiescence,
    )

    events: list[str] = []

    class Application:
        def advance_diagnostic_campaign(self, *_arguments, **_keyword_arguments):
            events.append("advance-campaign")
            return SimpleNamespace(status="completed", cases=())

    _advance_installed_wave2_campaign_after_mount_quiescence(
        application=Application(),
        campaign_id="diagnostic-campaign-background-probe",
        close_mount=lambda: events.append("close-mount"),
        stop_event_bridge=lambda: events.append("stop-event-bridge"),
        cleanup_errors=[],
    )

    assert events == [
        "close-mount",
        "stop-event-bridge",
        "advance-campaign",
    ]


def test_application_reopen_stops_event_bridge_before_fixture_transition():
    from stock_sim.release.frontend_v2_package_entry import (
        _reopen_active_installed_wave2_fixture_after_frontend_quiescence,
    )

    events: list[str] = []
    reopened_fixture = object()

    observed_fixture = (
        _reopen_active_installed_wave2_fixture_after_frontend_quiescence(
            close_mount=lambda: events.append("close-mount"),
            stop_event_bridge=lambda: events.append("stop-event-bridge"),
            close_fixture=lambda: events.append("close-fixture"),
            reopen_fixture=lambda: (
                events.append("reopen-fixture") or reopened_fixture
            ),
            cleanup_errors=[],
        )
    )

    assert observed_fixture is reopened_fixture
    assert events == [
        "close-mount",
        "stop-event-bridge",
        "close-fixture",
        "reopen-fixture",
    ]


def test_mount_quiescence_failure_is_reported_before_application_reopen():
    from stock_sim.release.frontend_v2_package_entry import (
        _quiesce_installed_wave2_mount,
    )

    cleanup_errors: list[str] = []

    def failed_mount_close() -> None:
        cleanup_errors.append(
            "Run Monitoring Feature cleanup failed: RuntimeError"
        )

    with pytest.raises(
        RuntimeError,
        match="active Application reopen mount quiescence failed",
    ):
        _quiesce_installed_wave2_mount(
            close_mount=failed_mount_close,
            cleanup_errors=cleanup_errors,
            operation="active Application reopen",
        )


def test_only_compiled_smoke_bypasses_interpreter_static_teardown():
    from stock_sim.release.frontend_v2_package_entry import (
        _run_process_entry,
    )

    terminated: list[int] = []

    with pytest.raises(
        RuntimeError,
        match="OS-level process termination unexpectedly returned",
    ):
        _run_process_entry(
            compiled=True,
            arguments=("--smoke-report-dir=C:/release-report",),
            run=lambda: 0,
            terminate=terminated.append,
        )

    assert terminated == [0]
    with pytest.raises(SystemExit) as source_exit:
        _run_process_entry(
            compiled=False,
            arguments=("--smoke-report-dir=C:/release-report",),
            run=lambda: 1,
            terminate=terminated.append,
        )
    assert source_exit.value.code == 1
    with pytest.raises(SystemExit) as interactive_exit:
        _run_process_entry(
            compiled=True,
            arguments=(),
            run=lambda: 2,
            terminate=terminated.append,
        )
    assert interactive_exit.value.code == 2
    assert terminated == [0]


def test_successful_compiled_smoke_exits_before_python_stream_teardown(
    monkeypatch,
):
    import stock_sim.release.frontend_v2_package_entry as package_entry

    events: list[str] = []

    class Stream:
        def __init__(self, label: str) -> None:
            self._label = label

        def flush(self) -> None:
            events.append(f"flush:{self._label}")

    with pytest.raises(
        RuntimeError,
        match="OS-level process termination unexpectedly returned",
    ):
        with monkeypatch.context() as patch:
            patch.setattr(package_entry.sys, "stdout", Stream("stdout"))
            patch.setattr(package_entry.sys, "stderr", Stream("stderr"))
            package_entry._run_process_entry(
                compiled=True,
                arguments=("--smoke-report-dir=C:/release-report",),
                run=lambda: events.append("run") or 0,
                terminate=lambda code: events.append(f"terminate:{code}"),
            )

    assert events == ["run", "terminate:0"]


def test_compiled_smoke_suspends_cyclic_gc_until_os_termination_returns():
    from stock_sim.release.frontend_v2_package_entry import (
        _run_process_entry,
    )

    events: list[str] = []

    with pytest.raises(
        RuntimeError,
        match="OS-level process termination unexpectedly returned",
    ):
        _run_process_entry(
            compiled=True,
            arguments=("--smoke-report-dir=C:/release-report",),
            run=lambda: events.append("run") or 0,
            terminate=lambda code: events.append(f"terminate:{code}"),
            cyclic_gc_enabled=lambda: True,
            suspend_cyclic_gc=lambda: events.append("suspend-gc"),
            resume_cyclic_gc=lambda: events.append("resume-gc"),
        )

    assert events == [
        "suspend-gc",
        "run",
        "terminate:0",
        "resume-gc",
    ]


def test_compiled_smoke_system_exit_zero_flushes_diagnostics(
    monkeypatch,
):
    import stock_sim.release.frontend_v2_package_entry as package_entry

    events: list[str] = []

    class Stream:
        def __init__(self, label: str) -> None:
            self._label = label

        def flush(self) -> None:
            events.append(f"flush:{self._label}")

    def show_help() -> int:
        events.append("run")
        raise SystemExit(0)

    with pytest.raises(
        RuntimeError,
        match="OS-level process termination unexpectedly returned",
    ):
        with monkeypatch.context() as patch:
            patch.setattr(package_entry.sys, "stdout", Stream("stdout"))
            patch.setattr(package_entry.sys, "stderr", Stream("stderr"))
            package_entry._run_process_entry(
                compiled=True,
                arguments=("--smoke-report-dir=C:/release-report", "--help"),
                run=show_help,
                terminate=lambda code: events.append(f"terminate:{code}"),
            )

    assert events == [
        "run",
        "flush:stdout",
        "flush:stderr",
        "terminate:0",
    ]


def test_compiled_smoke_failure_still_bypasses_static_teardown(capsys):
    from stock_sim.release.frontend_v2_package_entry import (
        _run_process_entry,
    )

    terminated: list[int] = []

    def fail_smoke() -> int:
        raise RuntimeError("smoke failed before returning")

    with pytest.raises(
        RuntimeError,
        match="OS-level process termination unexpectedly returned",
    ):
        _run_process_entry(
            compiled=True,
            arguments=("--smoke-report-dir", "C:/release-report"),
            run=fail_smoke,
            terminate=terminated.append,
        )

    assert terminated == [1]
    assert "RuntimeError: smoke failed before returning" in capsys.readouterr().err


def test_compiled_smoke_preserves_argparse_exit_code():
    from stock_sim.release.frontend_v2_package_entry import (
        _run_process_entry,
    )

    terminated: list[int] = []

    def reject_arguments() -> int:
        raise SystemExit(2)

    with pytest.raises(
        RuntimeError,
        match="OS-level process termination unexpectedly returned",
    ):
        _run_process_entry(
            compiled=True,
            arguments=("--smoke-report-dir",),
            run=reject_arguments,
            terminate=terminated.append,
        )

    assert terminated == [2]


def test_smoke_mode_rejects_an_abbreviated_selector(tmp_path, monkeypatch):
    from stock_sim.release import frontend_v2_package_entry as package_entry

    monkeypatch.setattr(
        package_entry,
        "run_smoke_journey",
        lambda **_arguments: pytest.fail(
            "an abbreviated selector must not enter smoke mode"
        ),
    )

    with pytest.raises(SystemExit) as rejected:
        package_entry.main(
            ("--smoke-report", str(tmp_path / "abbreviated-report"))
        )

    assert rejected.value.code == 2


def test_production_window_factory_closes_features_when_window_fails(
    tmp_path,
    monkeypatch,
):
    from app import app_context
    from app.ui import main_window
    from stock_sim.release.frontend_v2_package_entry import (
        _create_production_window,
    )

    class Resource:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    strategy_feature = Resource()
    scenario_feature = Resource()
    diagnostic_feature = Resource()
    run_feature = Resource()
    evidence_feature = Resource()

    class Context:
        strategy_library_feature = strategy_feature
        strategy_library_context = object()
        scenario_lab_feature = scenario_feature
        scenario_lab_context = object()
        diagnostic_tasks_feature = diagnostic_feature
        diagnostic_tasks_context = object()
        run_monitoring_feature = run_feature
        run_monitoring_context = object()
        evidence_and_findings_feature = evidence_feature
        evidence_and_findings_context = object()

    monkeypatch.setattr(
        app_context,
        "build_app_context",
        lambda **_kwargs: Context(),
    )

    def fail_window(**_kwargs):
        raise RuntimeError("injected window failure")

    monkeypatch.setattr(main_window, "MainWindow", fail_window)

    with pytest.raises(RuntimeError, match="injected window failure"):
        _create_production_window(
            event_bridge=object(),
            settings_path=tmp_path / "settings.json",
        )

    assert strategy_feature.closed is True
    assert scenario_feature.closed is True
    assert diagnostic_feature.closed is True
    assert run_feature.closed is True
    assert evidence_feature.closed is True
