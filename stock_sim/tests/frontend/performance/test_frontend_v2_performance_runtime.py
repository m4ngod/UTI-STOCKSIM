import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter_ns
from types import SimpleNamespace

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


def test_probe_factory_reopens_the_supplied_sealed_fixture_without_execution(
    tmp_path,
    monkeypatch,
):
    archive_path = tmp_path / "shared-v1-fixture.zip"
    archive_path.write_bytes(b"sealed")
    fixture = SimpleNamespace()
    calls = []

    def extract_fixture(*, archive_path, bundle_root):
        calls.append(("extract", archive_path, bundle_root))

    def open_fixture(*, bundle_root, expected_source_commit):
        calls.append(("open", bundle_root, expected_source_commit))
        return fixture

    monkeypatch.setattr(
        strategy_diagnostics_v1_release_fixture,
        "create_file_backed_formal_v1_release_fixture",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("a certifying lane regenerated V1 state")
        ),
    )
    monkeypatch.setattr(
        strategy_diagnostics_v1_release_fixture,
        "extract_sealed_formal_v1_release_fixture_archive",
        extract_fixture,
    )
    monkeypatch.setattr(
        strategy_diagnostics_v1_release_fixture,
        "open_sealed_formal_v1_release_fixture",
        open_fixture,
    )
    monkeypatch.setattr(
        frontend_v2_performance_runtime,
        "_RealV1PerformanceProbe",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    probe = (
        frontend_v2_performance_runtime.prepare_real_v1_performance_probe(
            fixture_archive_path=archive_path,
            expected_source_commit="a" * 40,
        )
    )
    try:
        assert probe.fixture is fixture
        assert probe.fixture_archive_digest == (
            "sha256:"
            "c9d0036bed6744bcdf692fc980d8717d7e5f5a"
            "4f4e8266b4a84982602fb1cd09"
        )
        assert calls[0][0:2] == ("extract", archive_path.resolve())
        assert calls[1] == (
            "open",
            calls[0][2],
            "a" * 40,
        )
    finally:
        probe.temporary_directory.cleanup()


def test_real_v1_preflight_closes_and_releases_before_renderer_clock(
    monkeypatch,
):
    events = []

    class Probe:
        def run_preflight(self, *, sample_count):
            events.append(("preflight", sample_count))

        def close(self):
            events.append(("close", None))

        def evidence(self):
            events.append(("evidence", None))
            return {
                "execution_phase": (
                    "same-process-preflight-before-renderer-clock"
                ),
                "clean_exit": True,
            }

    monkeypatch.setattr(
        frontend_v2_performance_runtime,
        "prepare_real_v1_performance_probe",
        lambda **_kwargs: Probe(),
    )
    monkeypatch.setattr(
        frontend_v2_performance_runtime.gc,
        "collect",
        lambda: events.append(("gc", None)),
    )
    monkeypatch.setattr(
        frontend_v2_performance_runtime,
        "_trim_process_working_set",
        lambda: events.append(("trim", None)),
    )

    evidence = (
        frontend_v2_performance_runtime
        .capture_real_v1_performance_preflight()
    )

    assert evidence["clean_exit"] is True
    assert events == [
        ("preflight", 2),
        ("close", None),
        ("evidence", None),
        ("gc", None),
        ("trim", None),
    ]


def test_certifying_cli_finishes_real_v1_preflight_before_renderer_clock(
    tmp_path,
    monkeypatch,
):
    from stock_sim.release import frontend_v2_performance

    events = []
    evidence = {
        "execution_phase": "same-process-preflight-before-renderer-clock",
        "clean_exit": True,
    }

    monkeypatch.setattr(
        frontend_v2_performance,
        "validate_measurement_source_checkout",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        frontend_v2_performance,
        "_configure_renderer_environment",
        lambda lane: events.append(("renderer", lane)),
    )
    monkeypatch.setattr(
        frontend_v2_performance_runtime,
        "prepare_real_v1_performance_probe",
        lambda: (_ for _ in ()).throw(
            AssertionError("legacy in-window probe path was used")
        ),
    )
    monkeypatch.setattr(
        frontend_v2_performance_runtime,
        "capture_real_v1_performance_preflight",
        lambda **kwargs: events.append(("preflight", kwargs)) or evidence,
        raising=False,
    )
    monkeypatch.setattr(
        frontend_v2_performance,
        "perf_counter_ns",
        lambda: events.append(("clock", None)) or 123,
    )

    def run_lane(**kwargs):
        events.append(("lane", kwargs))
        return {"status": "passed", "errors": []}

    monkeypatch.setattr(
        frontend_v2_performance_runtime,
        "run_performance_lane",
        run_lane,
    )
    output = tmp_path / "hardware.json"
    fixture_archive = tmp_path / "shared-v1-fixture.zip"
    fixture_archive.write_bytes(b"sealed")

    result = frontend_v2_performance.main(
        (
            "run-lane",
            "--lane",
            "hardware",
            "--duration-seconds",
            "60",
            "--source-commit",
            "a" * 40,
            "--output",
            str(output),
            "--fixture-archive",
            str(fixture_archive),
        )
    )

    assert result == 0
    assert events[:3] == [
        ("renderer", "hardware"),
        (
            "preflight",
            {
                "fixture_archive_path": fixture_archive,
                "expected_source_commit": "a" * 40,
            },
        ),
        ("clock", None),
    ]
    assert events[3][0] == "lane"
    assert events[3][1]["integrated_v1_evidence"] is evidence
    assert "real_v1_probe" not in events[3][1]


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
