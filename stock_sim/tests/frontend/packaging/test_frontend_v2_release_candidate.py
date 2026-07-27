from __future__ import annotations

import hashlib
import json
import os
from shutil import copy2
import subprocess
import sys
import xml.etree.ElementTree as ET

from stock_sim.release.frontend_v2_packaging import (
    PROJECT_ROOT,
    TOOLCHAIN_LOCK_PATH,
    verify_clean_room_report,
    write_mandatory_release_gate_evidence,
)


EXPECTED_JOURNEY = (
    (
        "launched_active_run",
        "run_monitoring",
        "active",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "active_evidence",
        "evidence_and_findings",
        "active",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "disconnected_run",
        "run_monitoring",
        "active",
        "ready",
        "disconnected",
        "disconnected",
    ),
    (
        "disconnected_evidence",
        "evidence_and_findings",
        "active",
        "ready",
        "disconnected",
        "disconnected",
    ),
    (
        "reconnected_run",
        "run_monitoring",
        "active",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "reconnected_evidence",
        "evidence_and_findings",
        "active",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "completed_run",
        "run_monitoring",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
    (
        "completed_evidence",
        "evidence_and_findings",
        "terminal",
        "ready",
        "fresh",
        "fresh",
    ),
)


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
        "AppContext",
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
    assert result.run_identity == "RUN-RC-001"
    assert result.routes_rendered == (
        "run_monitoring",
        "evidence_and_findings",
    )
    assert result.connection_transitions == (
        "connected",
        "disconnected",
        "reconnected",
        "completed",
    )
    assert result.manual_trading_action_count == 0
    assert result.read_only_context_visible is True
    assert result.errors == ()
    assert result.clean_exit is True
    assert "STOCKSIM_FRONTEND_V2" not in os.environ


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
    "AppContext",
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
        timeout=30,
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
                "AppContext",
                "EventBridge",
                "LiveRunMonitoringAdapter",
                "LiveEvidenceAndFindingsAdapter",
                "JourneyWorkspaceHost",
            ],
            "run_identity": "RUN-RC-001",
            "routes_rendered": [
                "run_monitoring",
                "evidence_and_findings",
            ],
            "connection_transitions": [
                "connected",
                "disconnected",
                "reconnected",
                "completed",
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
        "software renderer did not use the production EventBridge path"
        in verify_clean_room_report(
            report_path,
            expected_source_commit="abc123",
            expected_archive_sha256="sha256:package",
        )
    )

    compromised["renderer_lanes"]["software"]["production_path"] = [
        "AppContext",
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
    "test_live_journey_certifies_keyboard_narrator_terminal_and_remount",
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
    for name in (
        "hardware.json",
        "software.json",
        "no-manual-trading.json",
        "certification.json",
    ):
        copy2(source / name, target / name)
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
    assert "from app.app_context import build_app_context" in source
    assert "from app.ui.main_window import MainWindow" in source
    assert "_UnavailableRuntimeQueries" not in source
    assert "window = QMainWindow()" not in source
