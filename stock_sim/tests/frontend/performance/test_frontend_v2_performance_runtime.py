import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_software_smoke_runs_the_live_eventbridge_to_qml_seam(tmp_path):
    report_path = tmp_path / "software-smoke.json"
    environment = os.environ.copy()
    environment["PYTHONWARNINGS"] = "ignore"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "stock_sim.release.frontend_v2_performance",
            "run-lane",
            "--lane",
            "software",
            "--duration-seconds",
            "0.75",
            "--source-commit",
            "a" * 40,
            "--output",
            str(report_path),
            "--smoke",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "smoke"
    assert report["lane"] == "software"
    assert report["graphics_api"] == "Software"
    assert report["duration_seconds"] >= 0.75
    assert report["fixture"] == {
        "identity": "frontend-v2-wave1-windows-v1",
        "source_points": 100_000,
        "visible_points": 4_000,
        "overlay_count": 3,
        "candidate_rows": 50,
        "source_cadence_ms": 50,
        "paint_cap_fps": 20,
        "duration_seconds": 60,
    }
    assert report["observed_fixture"] == {
        "source_points": 100_000,
        "visible_points": 4_000,
        "overlay_count": 3,
        "candidate_rows": 50,
        "source_cadence_ms": 50,
        "paint_cap_fps": 20,
    }
    assert report["production_path"] == [
        "EventBridge",
        "LiveRunMonitoringAdapter",
        "LiveEvidenceAndFindingsAdapter",
        "JourneyWorkspaceHost",
        "EvidenceChart.qml",
    ]
    assert report["metrics"]["event_to_visible"]["count"] > 0
    assert report["metrics"]["input_response"]["count"] > 0
    assert report["metrics"]["input_response"]["p95_ms"] <= 16.0
    assert report["metrics"]["visible_revisions"] > 0
    assert report["metrics"]["usable_state_ms"] <= 750.0
    assert report["metrics"]["peak_memory_mib"] <= 180.0
    assert report["metrics"]["max_main_thread_stall_ms"] <= 50.0
    assert report["metrics"]["main_thread_stalls_over_budget"] == 0
    assert report["revisions_strictly_monotonic"] is True
    assert report["terminal"]["phase"] == "completed"
    assert report["terminal"]["observed"] is True
    assert report["safety"] == {
        "manual_trading_action_count": 0,
        "read_only_context_visible": True,
    }
    assert report["errors"] == []


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="The production hardware lane targets Windows D3D11.",
)
def test_hardware_smoke_runs_the_same_live_qml_seam(tmp_path):
    report_path = tmp_path / "hardware-smoke.json"
    environment = os.environ.copy()
    environment["PYTHONWARNINGS"] = "ignore"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "stock_sim.release.frontend_v2_performance",
            "run-lane",
            "--lane",
            "hardware",
            "--duration-seconds",
            "0.75",
            "--source-commit",
            "a" * 40,
            "--output",
            str(report_path),
            "--smoke",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "smoke"
    assert report["lane"] == "hardware"
    assert report["graphics_api"] == "Direct3D11"
    assert report["duration_seconds"] >= 0.75
    assert report["observed_fixture"]["source_points"] == 100_000
    assert report["observed_fixture"]["visible_points"] == 4_000
    assert report["observed_fixture"]["overlay_count"] == 3
    assert report["observed_fixture"]["candidate_rows"] == 50
    assert report["metrics"]["event_to_visible"]["count"] > 0
    assert report["metrics"]["input_response"]["count"] > 0
    assert report["metrics"]["input_response"]["p95_ms"] <= 16.0
    assert report["metrics"]["usable_state_ms"] <= 750.0
    assert report["metrics"]["peak_memory_mib"] <= 180.0
    assert report["metrics"]["max_main_thread_stall_ms"] <= 50.0
    assert report["metrics"]["main_thread_stalls_over_budget"] == 0
    assert report["terminal"]["observed"] is True
    assert report["revisions_strictly_monotonic"] is True
    assert report["errors"] == []
