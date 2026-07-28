import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter_ns

import pytest

from stock_sim.release import frontend_v2_performance_runtime
from stock_sim.release import strategy_diagnostics_v1_release_fixture


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_runtime_release_decision_delegates_to_central_validator(monkeypatch):
    report = {
        "lane": "hardware",
        "source_commit": "a" * 40,
        "toolchain_lock_digest": f"sha256:{'b' * 64}",
    }
    captured = {}

    def fake_validate(
        candidate,
        *,
        expected_lane,
        expected_source_commit,
        expected_toolchain_digest,
    ):
        captured.update(
            candidate=candidate,
            expected_lane=expected_lane,
            expected_source_commit=expected_source_commit,
            expected_toolchain_digest=expected_toolchain_digest,
        )
        return ("central gate failed",)

    monkeypatch.setattr(
        frontend_v2_performance_runtime,
        "validate_performance_lane",
        fake_validate,
        raising=False,
    )

    assert frontend_v2_performance_runtime._runtime_threshold_failures(
        report
    ) == ("central gate failed",)
    assert captured == {
        "candidate": report,
        "expected_lane": "hardware",
        "expected_source_commit": "a" * 40,
        "expected_toolchain_digest": f"sha256:{'b' * 64}",
    }


def test_probe_factory_closes_fixture_when_probe_construction_fails(
    monkeypatch,
):
    class Fixture:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    fixture = Fixture()
    storage_roots = []

    def create_fixture(*, database_path, artifact_root):
        storage_roots.append(database_path.parent)
        assert artifact_root.parent == database_path.parent
        return fixture

    def fail_probe(**_kwargs):
        raise RuntimeError("injected probe failure")

    monkeypatch.setattr(
        strategy_diagnostics_v1_release_fixture,
        "create_file_backed_formal_v1_release_fixture",
        create_fixture,
    )
    monkeypatch.setattr(
        frontend_v2_performance_runtime,
        "_RealV1PerformanceProbe",
        fail_probe,
    )

    with pytest.raises(RuntimeError, match="injected probe failure"):
        frontend_v2_performance_runtime.prepare_real_v1_performance_probe()

    assert fixture.closed is True
    assert storage_roots and not storage_roots[0].exists()


def test_lane_closes_first_feature_when_second_constructor_fails(
    monkeypatch,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    class Feature:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    run_feature = Feature()
    monkeypatch.setattr(
        frontend_v2_performance_runtime,
        "LiveRunMonitoringAdapter",
        lambda **_kwargs: run_feature,
    )

    def fail_evidence(**_kwargs):
        raise RuntimeError("injected evidence feature failure")

    monkeypatch.setattr(
        frontend_v2_performance_runtime,
        "LiveEvidenceAndFindingsAdapter",
        fail_evidence,
    )

    with pytest.raises(
        RuntimeError,
        match="injected evidence feature failure",
    ):
        frontend_v2_performance_runtime.run_performance_lane(
            lane="software",
            duration_seconds=0.1,
            source_commit="a" * 40,
            smoke=True,
            process_started_ns=perf_counter_ns(),
        )

    assert run_feature.closed is True


def test_lane_stops_partially_started_event_bridge(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    captured = []

    def fail_start(bridge):
        captured.append(bridge)
        bridge._running = True
        bridge._local_subscribed = True
        raise RuntimeError("injected EventBridge start failure")

    monkeypatch.setattr(
        frontend_v2_performance_runtime.EventBridge,
        "start",
        fail_start,
    )

    with pytest.raises(
        RuntimeError,
        match="injected EventBridge start failure",
    ):
        frontend_v2_performance_runtime.run_performance_lane(
            lane="software",
            duration_seconds=0.1,
            source_commit="a" * 40,
            smoke=True,
            process_started_ns=perf_counter_ns(),
        )

    assert len(captured) == 1
    bridge = captured[0]
    assert bridge._running is False
    assert bridge._th is None
    assert bridge._local_subscribed is False
    assert bridge._batch_observers == {}
    assert bridge._connection_observers == {}


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
        "PerformanceLoadProjectionReadModel",
        "EventBridge",
        "LiveRunMonitoringAdapter",
        "LiveEvidenceAndFindingsAdapter",
        "JourneyWorkspaceHost",
        "EvidenceChart.qml",
    ]
    assert report["integrated_v1_probe"] is None
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
