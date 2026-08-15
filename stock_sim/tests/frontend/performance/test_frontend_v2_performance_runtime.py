import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from time import perf_counter_ns
from types import SimpleNamespace

import pytest

from app.journey_recovery import (
    JourneyWorkspaceRoute,
    restore_journey_workspace_bookmark,
)
from app.state.settings_store import SettingsStore
from stock_sim.release import (
    frontend_v2_performance_runtime,
    strategy_diagnostics_v1_release_fixture,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_startup_markers_are_complete_ordered_and_compute_phases():
    marker_type = frontend_v2_performance_runtime._PerformanceStartupMarkers
    incomplete = marker_type(runtime_started_ns=1)
    with pytest.raises(RuntimeError, match="incomplete"):
        incomplete.phase_durations_ms(usable_visible_ns=12)

    markers = marker_type(
        runtime_started_ns=1,
        qapplication_ready_ns=2,
        window_create_started_ns=3,
        window_created_ns=4,
        window_bindings_ready_ns=5,
        initial_route_ready_ns=6,
        bridge_started_ns=7,
        window_show_started_ns=8,
        window_show_returned_ns=9,
        window_shown_ns=10,
        fixture_projection_ready_ns=11,
    )
    phases = markers.phase_durations_ms(usable_visible_ns=12)

    assert phases["total_to_usable_visible"] == 0.000011
    assert phases["projection_ready_to_usable_visible"] == 0.000001
    assert phases["show_started_to_usable_visible"] == 0.000004

    markers.fixture_projection_ready_ns = 7
    with pytest.raises(RuntimeError, match="out of order"):
        markers.phase_durations_ms(usable_visible_ns=12)

    markers.fixture_projection_ready_ns = 11
    markers.window_show_returned_ns = 10
    markers.window_shown_ns = 9
    with pytest.raises(RuntimeError, match="out of order"):
        markers.phase_durations_ms(usable_visible_ns=12)


def test_performance_fixture_persists_evidence_as_its_initial_route(tmp_path):
    settings_path = tmp_path / "performance-settings.json"

    frontend_v2_performance_runtime._prepare_performance_journey_settings(
        settings_path
    )

    stored = SettingsStore(path=str(settings_path), auto_save=False).get_state()
    restored = restore_journey_workspace_bookmark(
        stored.journey_workspace_bookmark_json
    )
    assert restored.bookmark.last_route is (
        JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS
    )
    assert restored.migrated is False


def test_performance_route_ensure_skips_reactivating_current_evidence():
    calls = []
    host = SimpleNamespace(
        active_route=JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS
    )

    changed = frontend_v2_performance_runtime._ensure_performance_evidence_route(
        app=object(),
        host=host,
        root=object(),
        navigate=lambda **kwargs: calls.append(kwargs),
    )

    assert changed is False
    assert calls == []


def test_performance_route_ensure_navigates_from_another_route():
    calls = []
    host = SimpleNamespace(active_route=JourneyWorkspaceRoute.SCENARIO_LAB)

    changed = frontend_v2_performance_runtime._ensure_performance_evidence_route(
        app="app",
        host=host,
        root="root",
        navigate=lambda **kwargs: calls.append(kwargs),
    )

    assert changed is True
    assert calls == [
        {
            "app": "app",
            "host": host,
            "root": "root",
            "route": "evidence_and_findings",
        }
    ]


def test_visibility_accepts_only_a_complete_scene_graph_frame_for_composition():
    class Renderer:
        def __init__(self):
            self.values = {
                "acceptedRevision": 7,
                "frameSequence": 10,
                "samplePointCount": 0,
                "seriesPointCount": 0,
            }

        def property(self, name):
            return self.values[name]

    renderer = Renderer()

    assert (
        frontend_v2_performance_runtime
        ._scene_graph_revision_ready_for_composition(renderer)
        == 0
    )

    renderer.values["samplePointCount"] = 4_000
    renderer.values["seriesPointCount"] = 4_000

    assert (
        frontend_v2_performance_runtime
        ._scene_graph_revision_ready_for_composition(renderer)
        == 7
    )

    renderer.values["frameSequence"] = 0
    assert (
        frontend_v2_performance_runtime
        ._scene_graph_revision_ready_for_composition(renderer)
        == 0
    )

    renderer.values["frameSequence"] = 11
    renderer.values["acceptedRevision"] = 0
    assert (
        frontend_v2_performance_runtime
        ._scene_graph_revision_ready_for_composition(renderer)
        == 0
    )

    renderer.values["acceptedRevision"] = 8
    renderer.values["seriesPointCount"] = 3_999
    assert (
        frontend_v2_performance_runtime
        ._scene_graph_revision_ready_for_composition(renderer)
        == 0
    )


def test_measurement_setup_runs_after_usable_and_before_sampling(monkeypatch):
    events = []

    def prepare_after_usable():
        assert probe._usable_state_ms == 42.0
        events.append("prepare")

    probe = SimpleNamespace(
        _usable_state_ms=42.0,
        _on_usable=prepare_after_usable,
        disconnect_render_signals=lambda: events.append("disconnect"),
        _bind_qml_items=lambda: events.append("bind"),
        _fixture_is_usable=lambda: True,
        connect_render_signals=lambda: events.append("connect"),
        _pre_measurement_setup_started_ns=None,
        _pre_measurement_setup_ended_ns=None,
        _start_measurement=lambda: events.append("measure"),
        _finish=lambda: events.append("finish"),
        errors=[],
    )
    clock = iter((1_000, 4_000))
    monkeypatch.setattr(
        frontend_v2_performance_runtime,
        "perf_counter_ns",
        lambda: next(clock),
    )
    monkeypatch.setattr(
        frontend_v2_performance_runtime.QTimer,
        "singleShot",
        lambda _delay, callback: callback(),
    )

    frontend_v2_performance_runtime._QtPerformanceProbe._prepare_after_usable(
        probe
    )

    assert events == [
        "disconnect",
        "prepare",
        "bind",
        "connect",
        "measure",
    ]
    assert probe._pre_measurement_setup_started_ns == 1_000
    assert probe._pre_measurement_setup_ended_ns == 4_000
    assert probe.errors == []


def test_measurement_setup_failure_is_redacted_and_finishes_before_sampling(
    monkeypatch,
):
    events = []

    def fail_setup():
        raise RuntimeError("sensitive path and payload")

    probe = SimpleNamespace(
        _usable_state_ms=42.0,
        _on_usable=fail_setup,
        disconnect_render_signals=lambda: events.append("disconnect"),
        _bind_qml_items=lambda: events.append("bind"),
        _fixture_is_usable=lambda: True,
        connect_render_signals=lambda: events.append("connect"),
        _pre_measurement_setup_started_ns=None,
        _pre_measurement_setup_ended_ns=None,
        _start_measurement=lambda: events.append("measure"),
        _finish=lambda: events.append("finish"),
        errors=[],
    )
    monkeypatch.setattr(
        frontend_v2_performance_runtime,
        "perf_counter_ns",
        lambda: 1_000,
    )
    monkeypatch.setattr(
        frontend_v2_performance_runtime.QTimer,
        "singleShot",
        lambda _delay, callback: callback(),
    )

    frontend_v2_performance_runtime._QtPerformanceProbe._prepare_after_usable(
        probe
    )

    assert events == ["disconnect", "finish"]
    assert probe._pre_measurement_setup_ended_ns is None
    assert probe.errors == [
        "Pre-measurement production setup failed: RuntimeError"
    ]


def test_finish_preserves_primary_error_when_final_fixture_capture_fails():
    events = []

    class Timer:
        def __init__(self, name):
            self.name = name

        def stop(self):
            events.append(f"stop:{self.name}")

    def fail_fixture_capture():
        raise RuntimeError("sensitive destroyed QML wrapper")

    probe = SimpleNamespace(
        _finished=False,
        _final_observed_fixture=None,
        _current_observed_fixture=fail_fixture_capture,
        _terminal_timeout=Timer("terminal"),
        _watchdog=Timer("watchdog"),
        _source_timer=Timer("source"),
        _stall_timer=Timer("stall"),
        _memory_timer=Timer("memory"),
        _input_timer=Timer("input"),
        _sample_memory=lambda: events.append("sample-memory"),
        _host=SimpleNamespace(errors=lambda: ()),
        _on_finished=lambda: events.append("finished"),
        errors=["primary performance failure"],
    )

    frontend_v2_performance_runtime._QtPerformanceProbe._finish(probe)

    assert probe._finished is True
    assert probe._final_observed_fixture == {}
    assert events == [
        "stop:terminal",
        "stop:watchdog",
        "stop:source",
        "stop:stall",
        "stop:memory",
        "stop:input",
        "sample-memory",
        "finished",
    ]
    assert probe.errors == [
        "primary performance failure",
        "Final performance fixture capture failed: RuntimeError",
    ]


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
    assert events[:2] == [
        ("renderer", "hardware"),
        ("clock", None),
    ]
    assert events[2][0] == "lane"
    assert events[2][1]["fixture_archive_path"] == fixture_archive
    assert "integrated_v1_evidence" not in events[2][1]


def test_lane_closes_real_probe_when_projection_constructor_fails(
    monkeypatch,
):
    class Probe:
        def __init__(self):
            self.closed = False

        def run_preflight(self, *, sample_count):
            assert sample_count == 2

        fixture = object()
        performance_identity = object()
        application_adapter = object()

        def close(self):
            self.closed = True

    probe = Probe()
    monkeypatch.setattr(
        frontend_v2_performance_runtime,
        "prepare_real_v1_performance_probe",
        lambda **_kwargs: probe,
    )

    def fail_projection(**_kwargs):
        raise RuntimeError("injected performance projection failure")

    monkeypatch.setattr(
        frontend_v2_performance_runtime,
        "_PackagedPerformanceFixtureReadModel",
        fail_projection,
    )

    with pytest.raises(
        RuntimeError,
        match="injected performance projection failure",
    ):
        frontend_v2_performance_runtime.run_performance_lane(
            lane="software",
            duration_seconds=0.1,
            source_commit="a" * 40,
            smoke=True,
            process_started_ns=perf_counter_ns(),
        )

    assert probe.closed is True


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
    assert "Internal C++ object" not in completed.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == 4
    assert report["status"] == "smoke"
    assert report["lane"] == "software"
    assert report["graphics_api"] == "Software"
    assert "performance_gate_policy" not in report
    assert report["duration_seconds"] >= 0.75
    startup = report["startup_phases_ms"]
    assert startup["total_to_usable_visible"] == pytest.approx(
        report["metrics"]["usable_state_ms"],
        abs=0.001,
    )
    assert startup["window_create"] > 0
    assert startup["bridge_started_to_show_started"] >= 0
    assert startup["shown_to_projection_ready"] >= 0
    assert startup["show_started_to_usable_visible"] >= 0
    assert all(value >= 0 for value in startup.values())
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
    assert report["production_path"] == list(
        frontend_v2_performance_runtime.WAVE3_PERFORMANCE_PRODUCTION_PATH
    )
    wave3_setup = report["wave3_setup_features"]
    assert wave3_setup["feature_interfaces"] == [
        "StrategyLibraryFeature/1.0",
        "ScenarioLabFeature/1.0",
    ]
    assert wave3_setup["adapters"] == [
        "LiveStrategyLibraryAdapter",
        "LiveScenarioLabAdapter",
    ]
    assert wave3_setup["routes"] == [
        "strategy_library",
        "scenario_lab",
    ]
    assert wave3_setup["presentation_states"] == {
        "strategy_library": "ready",
        "scenario_lab": "ready",
    }
    assert wave3_setup["freshness"] == {
        "strategy_library": "fresh",
        "scenario_lab": "fresh",
    }
    assert wave3_setup["qml_status_roles"] == {
        "strategy_library": "StatusBar",
        "scenario_lab": "StatusBar",
    }
    assert wave3_setup["initial_focus_observed"] == {
        "strategy_library": True,
        "scenario_lab": True,
    }
    assert wave3_setup["observed_before_load"] is True
    assert wave3_setup["prepared_before_measurement"] is True
    assert wave3_setup["observed_during_active_load"] is True
    assert wave3_setup["executed_during_active_load"] is False
    assert wave3_setup["accepted_setup_commands"] == [
        "compare_formal_strategy_set",
        "select_formal_strategy_set",
        "compose_visible_scenario_set",
    ]
    assert wave3_setup["comparison_count"] == 2
    assert wave3_setup["strategy_selection_status"] == "current"
    assert wave3_setup["scenario_set_count"] >= 1
    assert wave3_setup["scenario_set_eligibility"] in {
        "formal_campaign_eligible",
        "quick_experiment_only",
    }
    for revisions in wave3_setup["accepted_revisions"].values():
        assert len(revisions) == 2
        assert revisions[1] > revisions[0]
    wave2_load = report["wave2_diagnostic_tasks"]
    assert wave2_load["feature_interface"] == "DiagnosticTasksFeature/1.0"
    assert wave2_load["application_interface"] == (
        "StrategyDiagnosticsV1DiagnosticTasksApplication/1.0"
    )
    assert wave2_load["adapter"] == "LiveDiagnosticTasksAdapter"
    assert wave2_load["mode"] == "read_only_live_inventory_observation"
    assert wave2_load["accepted_command_ids"] == []
    assert wave2_load["result_command_ids"] == []
    assert wave2_load["accepted_command_observed"] is False
    assert wave2_load["task_handle_observed"] is False
    assert wave2_load["task_handle_ids"] == []
    assert wave2_load["handoff_observed"] is False
    assert wave2_load["terminal_observed"] is False
    assert wave2_load["prepared_before_measurement"] is True
    assert wave2_load["observed_during_active_load"] is True
    assert wave2_load["executed_during_active_load"] is False
    assert wave2_load["source_events_before_command"] == 0
    assert wave2_load["source_events_after_command"] > 0
    assert wave2_load["observed_before_load"] is True
    assert wave2_load["observed_after_load"] is True
    assert wave2_load["task_lifecycle"] == "not_started"
    assert wave2_load["identity_graph"] == []
    assert all(
        wave2_load["inventory_counts"][name] > 0
        for name in ("strategies", "approved_recipes", "market_scenarios")
    )
    assert report["integrated_v1_probe"]["clean_exit"] is True
    assert report["metrics"]["event_to_visible"]["count"] > 0
    assert report["metrics"]["input_response"]["count"] > 0
    assert report["metrics"]["visible_revisions"] > 0
    assert report["raw_samples"]["main_thread_gaps_ms"]
    assert report["raw_samples"]["working_set_mib"]
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
    assert report["schema_version"] == 4
    assert report["status"] == "smoke"
    assert report["lane"] == "hardware"
    assert report["graphics_api"] == "Direct3D11"
    assert report["performance_gate_policy"] == asdict(
        frontend_v2_performance_runtime.HARDWARE_USABLE_STATE_CALIBRATION
    )
    assert report["duration_seconds"] >= 0.75
    assert report["observed_fixture"]["source_points"] == 100_000
    assert report["observed_fixture"]["visible_points"] == 4_000
    assert report["observed_fixture"]["overlay_count"] == 3
    assert report["observed_fixture"]["candidate_rows"] == 50
    assert report["metrics"]["event_to_visible"]["count"] > 0
    assert report["metrics"]["input_response"]["count"] > 0
    assert report["terminal"]["observed"] is True
    assert report["revisions_strictly_monotonic"] is True
    assert report["errors"] == []
