from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from stock_sim.release import frontend_v2_performance
from stock_sim.release.no_manual_trading_gate import (
    audit_python_imports,
    audit_python_text,
)
from stock_sim.release.frontend_v2_performance import (
    PERFORMANCE_THRESHOLDS,
    REFERENCE_FIXTURE,
    REFERENCE_MEASUREMENT_PROTOCOL,
    certify_performance_evidence,
    certify_performance_report_files,
    reference_fixture_digest,
    validate_performance_lane,
)


SOURCE_COMMIT = "a" * 40
TOOLCHAIN_DIGEST = f"sha256:{'b' * 64}"
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _passing_real_v1_probe() -> dict[str, object]:
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
        "application_read_model_interface": (
            "StrategyDiagnosticsV1ApplicationReadModel/1.0"
        ),
        **identities,
        "artifact_hashes": [f"sha256:{'c' * 64}"],
        "expected_identity_graph": sorted(
            {*identities.values(), "METRIC-REAL-001"}
        ),
        "initial_read_counts": {
            "resolve_journey": 1,
            "read_run": 1,
            "read_evidence": 1,
        },
        "measurement_read_counts": {
            "resolve_journey": 3,
            "read_run": 3,
            "read_evidence": 3,
        },
        "measurement_samples_scheduled": 3,
        "measurement_samples_completed": 3,
        "measurement_window": {
            "started_at": "2026-07-26T12:00:00+00:00",
            "ended_at": "2026-07-26T12:01:00+00:00",
        },
        "fixture_closed": True,
        "fixture_storage_removed": True,
        "errors": [],
        "clean_exit": True,
    }


def _sample_metric(
    *,
    p50_ms: float,
    p95_ms: float,
    max_ms: float,
) -> dict[str, object]:
    samples = [p50_ms] * 10 + [p95_ms] * 9 + [max_ms]
    payload = json.dumps(samples, separators=(",", ":")).encode("utf-8")
    return {
        "count": len(samples),
        "p50_ms": p50_ms,
        "p95_ms": p95_ms,
        "max_ms": max_ms,
        "samples_digest": f"sha256:{hashlib.sha256(payload).hexdigest()}",
        "samples_ms": samples,
    }


def _passing_lane_report(lane: str = "hardware") -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "passed",
        "lane": lane,
        "graphics_api": (
            "Direct3D11" if lane == "hardware" else "Software"
        ),
        "source_commit": SOURCE_COMMIT,
        "toolchain_lock_digest": TOOLCHAIN_DIGEST,
        "fixture": {
            "identity": REFERENCE_FIXTURE.identity,
            "source_points": REFERENCE_FIXTURE.source_points,
            "visible_points": REFERENCE_FIXTURE.visible_points,
            "overlay_count": REFERENCE_FIXTURE.overlay_count,
            "candidate_rows": REFERENCE_FIXTURE.candidate_rows,
            "source_cadence_ms": REFERENCE_FIXTURE.source_cadence_ms,
            "paint_cap_fps": REFERENCE_FIXTURE.paint_cap_fps,
            "duration_seconds": REFERENCE_FIXTURE.duration_seconds,
        },
        "fixture_digest": reference_fixture_digest(),
        "observed_fixture": {
            "source_points": REFERENCE_FIXTURE.source_points,
            "visible_points": REFERENCE_FIXTURE.visible_points,
            "overlay_count": REFERENCE_FIXTURE.overlay_count,
            "candidate_rows": REFERENCE_FIXTURE.candidate_rows,
            "source_cadence_ms": REFERENCE_FIXTURE.source_cadence_ms,
            "paint_cap_fps": REFERENCE_FIXTURE.paint_cap_fps,
        },
        "measurement": asdict(REFERENCE_MEASUREMENT_PROTOCOL),
        "sampling_policy": "uniform_endpoints_v1",
        "start_marker": "frontend-v2-performance-start",
        "end_marker": "frontend-v2-performance-end",
        "started_at": "2026-07-26T12:00:00+00:00",
        "ended_at": "2026-07-26T12:01:00+00:00",
        "duration_seconds": 60.0,
        "integrated_v1_probe": _passing_real_v1_probe(),
        "machine": {
            "operating_system": "Windows 11",
            "operating_system_version": "10.0.26100",
            "architecture": "AMD64",
            "processor": "reference-cpu",
            "logical_cpu_count": 16,
            "total_memory_mib": 32_768.0,
        },
        "build": {
            "python": "3.11.9",
            "pyside6": "6.9.1",
            "qt": "6.9.1",
            "numpy": "2.3.1",
            "nuitka": "2.6.8",
        },
        "metrics": {
            "event_to_visible": _sample_metric(
                p50_ms=8.0,
                p95_ms=19.0,
                max_ms=20.0,
            ),
            "input_response": _sample_metric(
                p50_ms=4.0,
                p95_ms=15.0,
                max_ms=16.0,
            ),
            "usable_state_ms": 700.0,
            "max_main_thread_stall_ms": 49.0,
            "main_thread_stalls_over_budget": 0,
            "peak_memory_mib": 179.0,
            "source_events": 1_200,
            "visible_revisions": 1_000,
            "coalesced_source_events": 200,
        },
        "accepted_revisions": [1, 2, 4, 7],
        "revisions_strictly_monotonic": True,
        "terminal": {
            "phase": "completed",
            "source_revision": 1_201,
            "visible_revision": 1_001,
            "visible_ms": 99.0,
            "observed": True,
        },
        "safety": {
            "manual_trading_action_count": 0,
            "read_only_context_visible": True,
        },
        "errors": [],
    }


def _passing_safety_report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "policy_version": "frontend-v2-no-manual-trading-v1",
        "source_commit": SOURCE_COMMIT,
        "status": "passed",
        "source_digest": f"sha256:{'e' * 64}",
        "adapter_modes": ["deterministic_fake", "live"],
        "checked_surfaces": [
            "feature_interfaces",
            "qml_adapter_slots",
            "qml_object_tree",
            "journey_navigation",
            "shortcut_allowlist",
            "telemetry_registry",
            "runtime_dispatch_live",
            "runtime_dispatch_deterministic_fake",
            "read_only_diagnostic_context",
            "release_blocking",
        ],
        "runtime_test_file_digest": f"sha256:{'f' * 64}",
        "runtime_test_exit_code": 0,
        "runtime_test_cases": [
            (
                "test_qml_object_tree_navigation_and_runtime_surface_are_safe"
                "[deterministic_fake]"
            ),
            (
                "test_qml_object_tree_navigation_and_runtime_surface_are_safe"
                "[live]"
            ),
            (
                "test_order_and_fill_evidence_renders_only_as_non_editable_"
                "context[deterministic_fake]"
            ),
            (
                "test_order_and_fill_evidence_renders_only_as_non_editable_"
                "context[live]"
            ),
            (
                "test_live_cancel_diagnostic_task_cannot_reach_order_"
                "cancellation"
            ),
        ],
        "findings": [],
    }


def test_reference_fixture_and_release_thresholds_are_locked():
    assert REFERENCE_FIXTURE.identity == "frontend-v2-wave1-windows-v1"
    assert REFERENCE_FIXTURE.source_points == 100_000
    assert REFERENCE_FIXTURE.visible_points == 4_000
    assert REFERENCE_FIXTURE.overlay_count == 3
    assert REFERENCE_FIXTURE.candidate_rows == 50
    assert REFERENCE_FIXTURE.source_cadence_ms == 50
    assert REFERENCE_FIXTURE.paint_cap_fps == 20
    assert REFERENCE_FIXTURE.duration_seconds == 60

    assert PERFORMANCE_THRESHOLDS.event_to_visible_p95_ms == 20.0
    assert PERFORMANCE_THRESHOLDS.input_p95_ms == 16.0
    assert PERFORMANCE_THRESHOLDS.usable_state_ms == 750.0
    assert PERFORMANCE_THRESHOLDS.main_thread_stall_ms == 50.0
    assert PERFORMANCE_THRESHOLDS.peak_memory_mib == 180.0
    assert PERFORMANCE_THRESHOLDS.terminal_visible_ms == 100.0
    assert REFERENCE_MEASUREMENT_PROTOCOL.window_width == 1_280
    assert REFERENCE_MEASUREMENT_PROTOCOL.window_height == 800
    assert REFERENCE_MEASUREMENT_PROTOCOL.stall_probe_interval_ms == 5
    assert REFERENCE_MEASUREMENT_PROTOCOL.memory_probe_interval_ms == 100
    assert (
        REFERENCE_MEASUREMENT_PROTOCOL.input_probe
        == "qml_return_key_to_adapter_state"
    )
    assert (
        REFERENCE_MEASUREMENT_PROTOCOL.event_to_visible_endpoint
        == "quick_window_after_rendering_revision"
    )
    assert (
        REFERENCE_MEASUREMENT_PROTOCOL.memory_window_prep
        == "gc_collect_then_empty_working_set_before_start_marker"
    )


def test_performance_harness_has_no_transaction_or_forbidden_renderer_surface():
    for relative_path in (
        "stock_sim/release/frontend_v2_performance.py",
        "stock_sim/release/frontend_v2_performance_runtime.py",
    ):
        source_path = PROJECT_ROOT / relative_path
        content = source_path.read_text(encoding="utf-8")
        assert audit_python_text(relative_path, content) == ()
        assert audit_python_imports(
            relative_path,
            content,
            package_name="stock_sim.release",
        ) == ()
        assert "QQuickPaintedItem" not in content
        assert "pyqtgraph" not in content
        assert "WebEngine" not in content


def test_lane_validation_blocks_event_to_visible_p95_over_budget():
    report = _passing_lane_report()
    report["metrics"]["event_to_visible"]["p95_ms"] = 20.001

    failures = validate_performance_lane(
        report,
        expected_lane="hardware",
        expected_source_commit=SOURCE_COMMIT,
        expected_toolchain_digest=TOOLCHAIN_DIGEST,
    )

    assert failures == (
        "hardware event-to-visible p95 exceeds 20.0 ms: 20.001 ms",
        "hardware event-to-visible sample summary does not match samples",
    )


def test_lane_validation_recomputes_raw_sample_digest_and_summary():
    digest_tampered = _passing_lane_report()
    digest_tampered["metrics"]["event_to_visible"][
        "samples_digest"
    ] = f"sha256:{'0' * 64}"
    summary_tampered = _passing_lane_report()
    summary_tampered["metrics"]["input_response"]["p95_ms"] = 14.0

    digest_failures = validate_performance_lane(
        digest_tampered,
        expected_lane="hardware",
        expected_source_commit=SOURCE_COMMIT,
        expected_toolchain_digest=TOOLCHAIN_DIGEST,
    )
    summary_failures = validate_performance_lane(
        summary_tampered,
        expected_lane="hardware",
        expected_source_commit=SOURCE_COMMIT,
        expected_toolchain_digest=TOOLCHAIN_DIGEST,
    )

    assert (
        "hardware event-to-visible sample digest does not match samples"
        in digest_failures
    )
    assert (
        "hardware input sample summary does not match samples"
        in summary_failures
    )


def test_measurement_source_checkout_binds_head_and_cleanliness(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()

    def git(*arguments):
        return subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init")
    git("config", "user.email", "performance-test@example.invalid")
    git("config", "user.name", "Performance Test")
    tracked = repository / "tracked.py"
    tracked.write_text("LOCKED = True\n", encoding="utf-8")
    git("add", "tracked.py")
    git("commit", "-m", "fixture")
    source_commit = git("rev-parse", "HEAD")
    allowed_report = repository / "hardware.json"
    allowed_report.write_text("{}\n", encoding="utf-8")

    assert (
        frontend_v2_performance.validate_measurement_source_checkout(
            repository,
            expected_source_commit=source_commit,
            allowed_untracked_paths=(allowed_report,),
        )
        == ()
    )
    wrong_head = (
        frontend_v2_performance.validate_measurement_source_checkout(
            repository,
            expected_source_commit="0" * 40,
            allowed_untracked_paths=(allowed_report,),
        )
    )
    assert any("HEAD does not match" in failure for failure in wrong_head)

    tracked.write_text("LOCKED = False\n", encoding="utf-8")
    dirty = frontend_v2_performance.validate_measurement_source_checkout(
        repository,
        expected_source_commit=source_commit,
        allowed_untracked_paths=(allowed_report,),
    )
    assert any("tracked changes" in failure for failure in dirty)

    tracked.write_text("LOCKED = True\n", encoding="utf-8")
    unexpected = repository / "rogue.py"
    unexpected.write_text("ROGUE = True\n", encoding="utf-8")
    untracked = frontend_v2_performance.validate_measurement_source_checkout(
        repository,
        expected_source_commit=source_commit,
        allowed_untracked_paths=(allowed_report,),
    )
    assert any("unexpected untracked files" in failure for failure in untracked)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    (
        (
            lambda report: report.update(status="failed"),
            "hardware lane status is not passed",
        ),
        (
            lambda report: report.update(graphics_api="Software"),
            "hardware renderer used 'Software'; expected 'Direct3D11'",
        ),
        (
            lambda report: report.update(source_commit="working-tree"),
            "hardware source commit does not match the certification source",
        ),
        (
            lambda report: report.update(toolchain_lock_digest="sha256:wrong"),
            "hardware dependency lock digest does not match",
        ),
        (
            lambda report: report.update(fixture_digest="sha256:wrong"),
            "hardware fixture digest does not match",
        ),
        (
            lambda report: report["fixture"].update(candidate_rows=49),
            "hardware fixture does not match the fixed #34 workload",
        ),
        (
            lambda report: report["observed_fixture"].update(
                candidate_rows=49
            ),
            "hardware observed fixture does not match",
        ),
        (
            lambda report: report.update(duration_seconds=59.999),
            "hardware continuous duration is below 60 seconds: 59.999",
        ),
        (
            lambda report: report["metrics"]["input_response"].update(
                p95_ms=16.001
            ),
            "hardware input p95 exceeds 16.0 ms: 16.001 ms",
        ),
        (
            lambda report: report["metrics"].update(usable_state_ms=750.001),
            "hardware usable-state time exceeds 750.0 ms: 750.001 ms",
        ),
        (
            lambda report: report["metrics"].update(
                max_main_thread_stall_ms=50.001
            ),
            "hardware main-thread stall exceeds 50.0 ms: 50.001 ms",
        ),
        (
            lambda report: report["metrics"].update(
                main_thread_stalls_over_budget=1
            ),
            "hardware recorded 1 main-thread stall(s) over budget",
        ),
        (
            lambda report: report["metrics"].update(peak_memory_mib=180.001),
            "hardware peak memory exceeds 180.0 MiB: 180.001 MiB",
        ),
        (
            lambda report: report.update(accepted_revisions=[1, 4, 4, 7]),
            "hardware accepted revisions are not strictly monotonic",
        ),
        (
            lambda report: report.update(
                revisions_strictly_monotonic=False
            ),
            "hardware did not certify strict revision monotonicity",
        ),
        (
            lambda report: report["terminal"].update(observed=False),
            "hardware terminal revision was not observed",
        ),
        (
            lambda report: report["terminal"].update(visible_ms=100.001),
            "hardware terminal visibility exceeds 100.0 ms: 100.001 ms",
        ),
        (
            lambda report: report["safety"].update(
                manual_trading_action_count=1
            ),
            "hardware performance fixture exposed manual-trading actions",
        ),
        (
            lambda report: report["safety"].update(
                read_only_context_visible=False
            ),
            "hardware performance fixture did not retain read-only context",
        ),
        (
            lambda report: report.update(errors=["QML warning"]),
            "hardware lane reported runtime errors",
        ),
        (
            lambda report: report.update(start_marker="missing"),
            "hardware explicit start/end markers are invalid",
        ),
        (
            lambda report: report.pop("measurement"),
            "hardware measurement protocol does not match",
        ),
        (
            lambda report: report.pop("integrated_v1_probe"),
            "hardware real V1 probe schema version is invalid",
        ),
        (
            lambda report: report["integrated_v1_probe"][
                "measurement_read_counts"
            ].update(read_evidence=1),
            (
                "hardware real V1 probe measurement typed read counts "
                "do not prove 2 complete sample(s)"
            ),
        ),
        (
            lambda report: report["integrated_v1_probe"].update(
                clean_exit=False
            ),
            (
                "hardware real V1 probe did not close its worker and "
                "persistence cleanly"
            ),
        ),
        (
            lambda report: report["build"].update(qt="6.9.2"),
            "hardware measured build does not match the locked toolchain",
        ),
    ),
)
def test_lane_validation_blocks_every_release_gate_drift(
    mutation,
    expected,
):
    report = deepcopy(_passing_lane_report())
    mutation(report)

    failures = validate_performance_lane(
        report,
        expected_lane="hardware",
        expected_source_commit=SOURCE_COMMIT,
        expected_toolchain_digest=TOOLCHAIN_DIGEST,
    )

    assert expected in failures


def test_certification_requires_two_independent_lanes_and_the_safety_gate():
    hardware = _passing_lane_report("hardware")
    software = _passing_lane_report("software")
    safety = _passing_safety_report()

    certification = certify_performance_evidence(
        hardware,
        software,
        safety,
        expected_source_commit=SOURCE_COMMIT,
        expected_toolchain_digest=TOOLCHAIN_DIGEST,
    )

    assert certification.status == "certified"
    assert certification.failures == ()
    assert certification.hardware_report_digest.startswith("sha256:")
    assert certification.software_report_digest.startswith("sha256:")
    assert certification.safety_report_digest.startswith("sha256:")
    assert (
        certification.hardware_report_digest
        != certification.software_report_digest
    )

    invalid = certify_performance_evidence(
        hardware,
        deepcopy(hardware),
        safety,
        expected_source_commit=SOURCE_COMMIT,
        expected_toolchain_digest=TOOLCHAIN_DIGEST,
    )

    assert invalid.status == "blocked"
    assert "software report identifies lane 'hardware'" in invalid.failures
    assert (
        "hardware and software reports are not independent artifacts"
        in invalid.failures
    )

    mismatched_workload = deepcopy(software)
    mismatched_workload["integrated_v1_probe"][
        "run_identity"
    ] = "RUN-REAL-OTHER"
    mismatched_workload["integrated_v1_probe"][
        "expected_identity_graph"
    ] = sorted(
        (
            set(
                mismatched_workload["integrated_v1_probe"][
                    "expected_identity_graph"
                ]
            )
            - {"RUN-REAL-001"}
        )
        | {"RUN-REAL-OTHER"}
    )
    mismatched = certify_performance_evidence(
        hardware,
        mismatched_workload,
        safety,
        expected_source_commit=SOURCE_COMMIT,
        expected_toolchain_digest=TOOLCHAIN_DIGEST,
    )
    assert mismatched.status == "blocked"
    assert (
        "hardware and software real V1 probes do not identify the "
        "same persisted workload"
    ) in mismatched.failures


def test_report_file_certification_retains_the_bound_aggregate(tmp_path):
    hardware_path = tmp_path / "hardware.json"
    software_path = tmp_path / "software.json"
    output_path = tmp_path / "certification.json"
    hardware_path.write_text(
        json.dumps(_passing_lane_report("hardware")),
        encoding="utf-8",
    )
    software_path.write_text(
        json.dumps(_passing_lane_report("software")),
        encoding="utf-8",
    )

    certification = certify_performance_report_files(
        hardware_path,
        software_path,
        _passing_safety_report(),
        expected_source_commit=SOURCE_COMMIT,
        expected_toolchain_digest=TOOLCHAIN_DIGEST,
        output_path=output_path,
    )

    assert certification.status == "certified"
    assert json.loads(output_path.read_text(encoding="utf-8")) == json.loads(
        json.dumps(asdict(certification))
    )


def test_report_file_certification_normalizes_dataclass_tuple_fields(tmp_path):
    hardware_path = tmp_path / "hardware.json"
    software_path = tmp_path / "software.json"
    hardware_path.write_text(
        json.dumps(_passing_lane_report("hardware")),
        encoding="utf-8",
    )
    software_path.write_text(
        json.dumps(_passing_lane_report("software")),
        encoding="utf-8",
    )
    safety = _passing_safety_report()
    for key in (
        "adapter_modes",
        "checked_surfaces",
        "runtime_test_cases",
        "findings",
    ):
        safety[key] = tuple(safety[key])

    certification = certify_performance_report_files(
        hardware_path,
        software_path,
        safety,
        expected_source_commit=SOURCE_COMMIT,
        expected_toolchain_digest=TOOLCHAIN_DIGEST,
        output_path=tmp_path / "certification.json",
    )

    assert certification.status == "certified"
    assert certification.failures == ()
