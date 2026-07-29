from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from shutil import copy2
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

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
        "disconnected",
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
        "fresh",
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
    from stock_sim.release import (
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
    assert hashlib.sha256(fixture_archive.read_bytes()).hexdigest() == (
        original_archive_hash
    )
    assert not tuple(
        path
        for path in report_dir.rglob("*")
        if path.name == "strategy-diagnostics-v1.sqlite3"
    )


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
        capture_images=False,
    )

    assert result.production_path == (
        "DiagnosticsApplication",
        "FileBackedV1Persistence",
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
        "RunMonitoringFeature/1.2",
        "EvidenceAndFindingsFeature/1.1",
    )
    assert result.campaign_status == "completed"
    assert result.run_status == "completed"
    assert result.evidence_status == "sealed"
    assert result.expected_identity_graph
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
    completed = subprocess.run(
        (sys.executable, "-c", script, str(tmp_path)),
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
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
        renderer_lanes[lane] = {
            "exit_code": 0,
            "graphics_api": graphics_api,
            "source_commit": "abc123",
            "production_path": [
                "DiagnosticsApplication",
                "FileBackedV1Persistence",
                "LiveStrategyDiagnosticsV1ApplicationAdapter",
                "EventBridge",
                "LiveRunMonitoringAdapter",
                "LiveEvidenceAndFindingsAdapter",
                "JourneyWorkspaceHost",
            ],
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
                "RunMonitoringFeature/1.2",
                "EvidenceAndFindingsFeature/1.1",
            ],
            "campaign_status": "completed",
            "run_status": "completed",
            "evidence_status": "sealed",
            "expected_identity_graph": _IDENTITY_GRAPH,
            "feature_identity_graph": _IDENTITY_GRAPH,
            "qml_identity_graph_checkpoints": {
                stage: _IDENTITY_GRAPH
                for stage, *_ in EXPECTED_JOURNEY
            },
            "evidence_identity_sets": _IDENTITY_SETS,
            "persisted_manifest_identities": (
                _PERSISTED_MANIFEST_IDENTITIES
            ),
            "persisted_run_identities": _PERSISTED_RUN_IDENTITIES,
            "raw_artifact_hashes": _RAW_ARTIFACT_HASHES,
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

    compromised = json.loads(report_path.read_text(encoding="utf-8"))
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


def test_compiled_smoke_defaults_to_the_packaged_sealed_v1_fixture(
    tmp_path,
    monkeypatch,
):
    from stock_sim.release import frontend_v2_package_entry as package_entry
    from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
        FORMAL_V1_RELEASE_FIXTURE_ARCHIVE,
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
        executable.parent / FORMAL_V1_RELEASE_FIXTURE_ARCHIVE
    )


def test_release_smoke_joins_live_features_before_deleting_qt_mount(
    monkeypatch,
):
    import shiboken6

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
        deleted = False

        def close_adapter(self):
            events.append("adapter")
            self._workspace_closed = True

        def deleteLater(self):
            events.append("host-delete")
            self.deleted = True

    class Window:
        deleted = False

        def close(self):
            events.append("window")

        def deleteLater(self):
            events.append("window-delete")
            self.deleted = True

        def isVisible(self):
            if self.deleted:
                raise RuntimeError("wrapped C++ object is deleted")
            return False

    class App:
        def sendPostedEvents(self, *_args):
            events.append("deferred-delete")

        def processEvents(self):
            events.append("process-events")

    context = type(
        "Context",
        (),
        {
            "run_monitoring_feature": Feature("run-feature"),
            "evidence_and_findings_feature": Feature("evidence-feature"),
        },
    )()
    host = Host()
    window = Window()
    monkeypatch.setattr(
        shiboken6,
        "isValid",
        lambda item: not item.deleted,
    )

    _close_mount(
        app=App(),
        context=context,
        window=window,
        host=host,
    )

    assert events == [
        "adapter",
        "run-feature",
        "evidence-feature",
        "window",
        "host-delete",
        "window-delete",
        "deferred-delete",
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
        timeout=240,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [
        {"clean_exit": True, "errors": []},
        {"clean_exit": True, "errors": []},
    ]


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

    run_feature = Resource()
    evidence_feature = Resource()

    class Context:
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

    assert run_feature.closed is True
    assert evidence_feature.closed is True
