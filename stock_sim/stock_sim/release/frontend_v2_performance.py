"""Frontend V2 live-QML performance certification."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from math import ceil
from time import perf_counter_ns
from typing import Any, Mapping, Sequence

from .frontend_v2_packaging import (
    REAL_V1_IDENTITY_FIELDS,
    TOOLCHAIN_LOCK_PATH,
    load_toolchain_lock,
)
from .no_manual_trading_gate import (
    audit_no_manual_trading_gate,
    verify_safety_gate_payload,
)


@dataclass(frozen=True, slots=True)
class PerformanceFixture:
    """The fixed #34 Windows workload."""

    identity: str
    source_points: int
    visible_points: int
    overlay_count: int
    candidate_rows: int
    source_cadence_ms: int
    paint_cap_fps: int
    duration_seconds: int


@dataclass(frozen=True, slots=True)
class PerformanceThresholds:
    """The fixed #34 release budgets, expressed in milliseconds and MiB."""

    event_to_visible_p95_ms: float
    input_p95_ms: float
    usable_state_ms: float
    main_thread_stall_ms: float
    peak_memory_mib: float
    terminal_visible_ms: float


@dataclass(frozen=True, slots=True)
class PerformanceMeasurementProtocol:
    """Locked clocks, endpoints, and sampling windows for #45 evidence."""

    usable_state_origin: str
    event_to_visible_origin: str
    event_to_visible_endpoint: str
    input_probe: str
    stall_probe_interval_ms: int
    memory_probe: str
    memory_probe_interval_ms: int
    memory_window_prep: str
    duration_clock: str
    window_width: int
    window_height: int


@dataclass(frozen=True, slots=True)
class PerformanceCertification:
    """Immutable aggregate result for the two renderer lanes."""

    schema_version: int
    status: str
    source_commit: str
    toolchain_lock_digest: str
    fixture_digest: str
    hardware_report_digest: str
    software_report_digest: str
    safety_report_digest: str
    failures: tuple[str, ...]


REFERENCE_FIXTURE = PerformanceFixture(
    identity="frontend-v2-wave1-windows-v1",
    source_points=100_000,
    visible_points=4_000,
    overlay_count=3,
    candidate_rows=50,
    source_cadence_ms=50,
    paint_cap_fps=20,
    duration_seconds=60,
)

PERFORMANCE_THRESHOLDS = PerformanceThresholds(
    event_to_visible_p95_ms=20.0,
    input_p95_ms=16.0,
    usable_state_ms=750.0,
    main_thread_stall_ms=50.0,
    peak_memory_mib=180.0,
    terminal_visible_ms=100.0,
)

REFERENCE_MEASUREMENT_PROTOCOL = PerformanceMeasurementProtocol(
    usable_state_origin="runtime_entry_before_qapplication",
    event_to_visible_origin="eventbridge_batch_acceptance",
    event_to_visible_endpoint="quick_window_after_rendering_revision",
    input_probe="qml_return_key_to_adapter_state",
    stall_probe_interval_ms=5,
    memory_probe="win32_process_working_set",
    memory_probe_interval_ms=100,
    memory_window_prep=(
        "gc_collect_then_empty_working_set_before_start_marker"
    ),
    duration_clock="perf_counter_ns",
    window_width=1_280,
    window_height=800,
)

REAL_V1_PERFORMANCE_PRODUCTION_PATH = (
    "DiagnosticsApplication",
    "FileBackedV1Persistence",
    "LiveStrategyDiagnosticsV1ApplicationAdapter",
)


def reference_fixture_digest() -> str:
    payload = json.dumps(
        asdict(REFERENCE_FIXTURE),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def build_performance_metric(samples: Sequence[float]) -> dict[str, Any]:
    """Build the canonical raw-sample payload and its derived summary."""

    rounded = [round(value, 6) for value in samples]
    ordered = sorted(rounded)
    return {
        "count": len(ordered),
        "p50_ms": _percentile(ordered, 0.50),
        "p95_ms": _percentile(ordered, 0.95),
        "max_ms": max(ordered) if ordered else None,
        "samples_digest": _sample_digest(rounded),
        "samples_ms": rounded,
    }


def validate_measurement_source_checkout(
    project_root: Path,
    *,
    expected_source_commit: str,
    allowed_untracked_paths: Sequence[Path] = (),
) -> tuple[str, ...]:
    """Bind certifying evidence to the exact clean Git checkout being run."""

    failures: list[str] = []
    root = project_root.resolve()
    repository_result = _run_git(root, "rev-parse", "--show-toplevel")
    if repository_result.returncode:
        return ("measurement source is not inside a Git checkout",)
    repository_root = Path(repository_result.stdout.strip()).resolve()

    head_result = _run_git(repository_root, "rev-parse", "HEAD")
    if head_result.returncode:
        failures.append("measurement source HEAD is unavailable")
    else:
        head = head_result.stdout.strip()
        if head != expected_source_commit:
            failures.append(
                "measurement source HEAD does not match requested commit: "
                f"{head}"
            )

    tracked_result = _run_git(
        repository_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    )
    if tracked_result.returncode:
        failures.append("measurement source tracked status is unavailable")
    elif tracked_result.stdout:
        failures.append("measurement source checkout has tracked changes")

    allowed = {
        (
            path.resolve()
            if path.is_absolute()
            else (root / path).resolve()
        )
        for path in allowed_untracked_paths
    }
    untracked_result = _run_git(
        repository_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    )
    if untracked_result.returncode:
        failures.append("measurement source untracked status is unavailable")
    else:
        unexpected = tuple(
            relative_path
            for relative_path in untracked_result.stdout.split("\0")
            if relative_path
            and (repository_root / relative_path).resolve() not in allowed
        )
        if unexpected:
            failures.append(
                "measurement source checkout has unexpected untracked files: "
                + ", ".join(unexpected)
            )
    return tuple(failures)


def validate_performance_lane(
    report: Mapping[str, Any],
    *,
    expected_lane: str,
    expected_source_commit: str,
    expected_toolchain_digest: str,
) -> tuple[str, ...]:
    """Return release-blocking findings for one retained renderer report."""

    failures: list[str] = []
    expected_api = (
        "Direct3D11" if expected_lane == "hardware" else "Software"
    )
    if report.get("schema_version") != 1:
        failures.append(f"{expected_lane} lane schema version is invalid")
    if report.get("status") != "passed":
        failures.append(f"{expected_lane} lane status is not passed")
    if report.get("lane") != expected_lane:
        failures.append(
            f"{expected_lane} report identifies lane {report.get('lane')!r}"
        )
    if report.get("graphics_api") != expected_api:
        failures.append(
            f"{expected_lane} renderer used {report.get('graphics_api')!r}; "
            f"expected {expected_api!r}"
        )
    if report.get("source_commit") != expected_source_commit:
        failures.append(
            f"{expected_lane} source commit does not match the "
            "certification source"
        )
    if report.get("toolchain_lock_digest") != expected_toolchain_digest:
        failures.append(
            f"{expected_lane} dependency lock digest does not match"
        )
    if report.get("fixture_digest") != reference_fixture_digest():
        failures.append(f"{expected_lane} fixture digest does not match")
    if report.get("fixture") != asdict(REFERENCE_FIXTURE):
        failures.append(
            f"{expected_lane} fixture does not match the fixed #34 workload"
        )
    expected_observed_fixture = {
        "source_points": REFERENCE_FIXTURE.source_points,
        "visible_points": REFERENCE_FIXTURE.visible_points,
        "overlay_count": REFERENCE_FIXTURE.overlay_count,
        "candidate_rows": REFERENCE_FIXTURE.candidate_rows,
        "source_cadence_ms": REFERENCE_FIXTURE.source_cadence_ms,
        "paint_cap_fps": REFERENCE_FIXTURE.paint_cap_fps,
    }
    if report.get("observed_fixture") != expected_observed_fixture:
        failures.append(
            f"{expected_lane} observed fixture does not match"
        )
    if report.get("measurement") != asdict(
        REFERENCE_MEASUREMENT_PROTOCOL
    ):
        failures.append(
            f"{expected_lane} measurement protocol does not match"
        )
    if report.get("sampling_policy") != "uniform_endpoints_v1":
        failures.append(
            f"{expected_lane} sampling policy does not match the "
            "production chart"
        )
    if (
        report.get("start_marker") != "frontend-v2-performance-start"
        or report.get("end_marker") != "frontend-v2-performance-end"
    ):
        failures.append(
            f"{expected_lane} explicit start/end markers are invalid"
        )
    duration_seconds = _number(report.get("duration_seconds"))
    if duration_seconds is None:
        failures.append(
            f"{expected_lane} continuous duration is unavailable"
        )
    elif duration_seconds < REFERENCE_FIXTURE.duration_seconds:
        failures.append(
            f"{expected_lane} continuous duration is below "
            f"{REFERENCE_FIXTURE.duration_seconds} seconds: "
            f"{report.get('duration_seconds')}"
        )
    if not report.get("started_at") or not report.get("ended_at"):
        failures.append(
            f"{expected_lane} wall-clock start/end metadata is unavailable"
        )
    failures.extend(
        _validate_real_v1_performance_probe(
            report.get("integrated_v1_probe"),
            expected_lane=expected_lane,
            renderer_started_at=report.get("started_at"),
        )
    )

    machine = _mapping(report.get("machine"))
    if (
        machine.get("operating_system") != "Windows 11"
        or str(machine.get("architecture") or "").lower()
        not in {"amd64", "x86_64"}
        or not machine.get("operating_system_version")
        or not machine.get("processor")
        or _number(machine.get("logical_cpu_count")) is None
        or _number(machine.get("total_memory_mib")) is None
    ):
        failures.append(
            f"{expected_lane} machine metadata is incomplete or unsupported"
        )

    locked_toolchain = asdict(load_toolchain_lock().toolchain)
    if report.get("build") != locked_toolchain:
        failures.append(
            f"{expected_lane} measured build does not match the "
            "locked toolchain"
        )

    metrics = _mapping(report.get("metrics"))
    event_metric = _mapping(metrics.get("event_to_visible"))
    event_p95 = _number(event_metric.get("p95_ms"))
    if event_p95 is None or _positive_count(event_metric.get("count")) is None:
        failures.append(
            f"{expected_lane} event-to-visible samples are unavailable"
        )
    elif event_p95 > PERFORMANCE_THRESHOLDS.event_to_visible_p95_ms:
        failures.append(
            f"{expected_lane} event-to-visible p95 exceeds "
            f"{PERFORMANCE_THRESHOLDS.event_to_visible_p95_ms:.1f} ms: "
            f"{event_metric.get('p95_ms')} ms"
        )

    input_metric = _mapping(metrics.get("input_response"))
    input_p95 = _number(input_metric.get("p95_ms"))
    if input_p95 is None or _positive_count(input_metric.get("count")) is None:
        failures.append(f"{expected_lane} input samples are unavailable")
    elif input_p95 > PERFORMANCE_THRESHOLDS.input_p95_ms:
        failures.append(
            f"{expected_lane} input p95 exceeds "
            f"{PERFORMANCE_THRESHOLDS.input_p95_ms:.1f} ms: "
            f"{input_metric.get('p95_ms')} ms"
        )

    usable_state_ms = _number(metrics.get("usable_state_ms"))
    if usable_state_ms is None:
        failures.append(f"{expected_lane} usable-state time is unavailable")
    elif usable_state_ms > PERFORMANCE_THRESHOLDS.usable_state_ms:
        failures.append(
            f"{expected_lane} usable-state time exceeds "
            f"{PERFORMANCE_THRESHOLDS.usable_state_ms:.1f} ms: "
            f"{metrics.get('usable_state_ms')} ms"
        )

    max_stall_ms = _number(metrics.get("max_main_thread_stall_ms"))
    if max_stall_ms is None:
        failures.append(
            f"{expected_lane} main-thread stall measurement is unavailable"
        )
    elif max_stall_ms > PERFORMANCE_THRESHOLDS.main_thread_stall_ms:
        failures.append(
            f"{expected_lane} main-thread stall exceeds "
            f"{PERFORMANCE_THRESHOLDS.main_thread_stall_ms:.1f} ms: "
            f"{metrics.get('max_main_thread_stall_ms')} ms"
        )
    over_budget = _nonnegative_int(
        metrics.get("main_thread_stalls_over_budget")
    )
    if over_budget is None:
        failures.append(
            f"{expected_lane} main-thread stall count is unavailable"
        )
    elif over_budget:
        failures.append(
            f"{expected_lane} recorded {over_budget} main-thread stall(s) "
            "over budget"
        )

    peak_memory_mib = _number(metrics.get("peak_memory_mib"))
    if peak_memory_mib is None:
        failures.append(f"{expected_lane} peak-memory measurement is unavailable")
    elif peak_memory_mib > PERFORMANCE_THRESHOLDS.peak_memory_mib:
        failures.append(
            f"{expected_lane} peak memory exceeds "
            f"{PERFORMANCE_THRESHOLDS.peak_memory_mib:.1f} MiB: "
            f"{metrics.get('peak_memory_mib')} MiB"
        )
    if _positive_count(metrics.get("source_events")) is None:
        failures.append(f"{expected_lane} source-event count is unavailable")
    if _positive_count(metrics.get("visible_revisions")) is None:
        failures.append(
            f"{expected_lane} visible-revision count is unavailable"
        )
    if _nonnegative_int(metrics.get("coalesced_source_events")) is None:
        failures.append(
            f"{expected_lane} coalescing metadata is unavailable"
        )

    revisions_value = report.get("accepted_revisions")
    revisions = (
        tuple(revisions_value)
        if isinstance(revisions_value, list)
        else ()
    )
    if (
        not revisions
        or any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in revisions
        )
        or any(
            current <= previous
            for previous, current in zip(revisions, revisions[1:])
        )
    ):
        failures.append(
            f"{expected_lane} accepted revisions are not strictly monotonic"
        )
    if report.get("revisions_strictly_monotonic") is not True:
        failures.append(
            f"{expected_lane} did not certify strict revision monotonicity"
        )

    terminal = _mapping(report.get("terminal"))
    if terminal.get("observed") is not True:
        failures.append(
            f"{expected_lane} terminal revision was not observed"
        )
    if terminal.get("phase") not in {"completed", "failed"}:
        failures.append(f"{expected_lane} terminal phase is invalid")
    terminal_visible_ms = _number(terminal.get("visible_ms"))
    if terminal_visible_ms is None:
        failures.append(
            f"{expected_lane} terminal visibility is unavailable"
        )
    elif terminal_visible_ms > PERFORMANCE_THRESHOLDS.terminal_visible_ms:
        failures.append(
            f"{expected_lane} terminal visibility exceeds "
            f"{PERFORMANCE_THRESHOLDS.terminal_visible_ms:.1f} ms: "
            f"{terminal.get('visible_ms')} ms"
        )
    if (
        _positive_count(terminal.get("source_revision")) is None
        or _positive_count(terminal.get("visible_revision")) is None
    ):
        failures.append(
            f"{expected_lane} terminal revision identity is unavailable"
        )

    safety = _mapping(report.get("safety"))
    if safety.get("manual_trading_action_count") != 0:
        failures.append(
            f"{expected_lane} performance fixture exposed "
            "manual-trading actions"
        )
    if safety.get("read_only_context_visible") is not True:
        failures.append(
            f"{expected_lane} performance fixture did not retain "
            "read-only context"
        )
    errors = report.get("errors")
    if not isinstance(errors, list) or errors:
        failures.append(f"{expected_lane} lane reported runtime errors")

    for metric_name, metric in (
        ("event-to-visible", event_metric),
        ("input", input_metric),
    ):
        samples_value = metric.get("samples_ms")
        raw_samples = (
            samples_value if isinstance(samples_value, list) else []
        )
        samples = tuple(
            float(value)
            for value in raw_samples
            if _number(value) is not None
        )
        if (
            not samples
            or len(samples) != len(raw_samples)
            or any(value < 0 for value in samples)
        ):
            failures.append(
                f"{expected_lane} {metric_name} sample payload is unavailable"
            )
            continue
        expected_metric = build_performance_metric(samples)
        if metric.get("samples_ms") != expected_metric["samples_ms"]:
            failures.append(
                f"{expected_lane} {metric_name} sample payload is not canonical"
            )
        if metric.get("samples_digest") != expected_metric["samples_digest"]:
            failures.append(
                f"{expected_lane} {metric_name} sample digest does not "
                "match samples"
            )
        if any(
            metric.get(field) != expected_metric[field]
            for field in ("count", "p50_ms", "p95_ms", "max_ms")
        ):
            failures.append(
                f"{expected_lane} {metric_name} sample summary does not "
                "match samples"
            )
    return tuple(failures)


def certify_performance_evidence(
    hardware_report: Mapping[str, Any],
    software_report: Mapping[str, Any],
    safety_report: Mapping[str, Any],
    *,
    expected_source_commit: str,
    expected_toolchain_digest: str,
) -> PerformanceCertification:
    """Bind both retained lanes and the #44 safety gate to one source."""

    hardware_digest = _payload_digest(hardware_report)
    software_digest = _payload_digest(software_report)
    safety_digest = _payload_digest(safety_report)
    failures = list(
        validate_performance_lane(
            hardware_report,
            expected_lane="hardware",
            expected_source_commit=expected_source_commit,
            expected_toolchain_digest=expected_toolchain_digest,
        )
    )
    failures.extend(
        validate_performance_lane(
            software_report,
            expected_lane="software",
            expected_source_commit=expected_source_commit,
            expected_toolchain_digest=expected_toolchain_digest,
        )
    )
    if hardware_digest == software_digest:
        failures.append(
            "hardware and software reports are not independent artifacts"
        )
    if _real_v1_workload_identity(
        hardware_report.get("integrated_v1_probe")
    ) != _real_v1_workload_identity(
        software_report.get("integrated_v1_probe")
    ):
        failures.append(
            "hardware and software real V1 probes do not identify the "
            "same persisted workload"
        )
    failures.extend(
        verify_safety_gate_payload(
            {"safety": safety_report},
            expected_source_commit=expected_source_commit,
        )
    )
    unique_failures = tuple(dict.fromkeys(failures))
    return PerformanceCertification(
        schema_version=1,
        status="certified" if not unique_failures else "blocked",
        source_commit=expected_source_commit,
        toolchain_lock_digest=expected_toolchain_digest,
        fixture_digest=reference_fixture_digest(),
        hardware_report_digest=hardware_digest,
        software_report_digest=software_digest,
        safety_report_digest=safety_digest,
        failures=unique_failures,
    )


def certify_performance_report_files(
    hardware_report_path: Path,
    software_report_path: Path,
    safety_report: Mapping[str, Any],
    *,
    expected_source_commit: str,
    expected_toolchain_digest: str,
    output_path: Path,
) -> PerformanceCertification:
    """Validate retained lane files and write their bound certification."""

    hardware_report = _load_report(hardware_report_path)
    software_report = _load_report(software_report_path)
    normalized_safety = json.loads(
        json.dumps(safety_report, sort_keys=True)
    )
    if not isinstance(normalized_safety, Mapping):
        raise ValueError("Safety report must be a JSON object")
    certification = certify_performance_evidence(
        hardware_report,
        software_report,
        normalized_safety,
        expected_source_commit=expected_source_commit,
        expected_toolchain_digest=expected_toolchain_digest,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(asdict(certification), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return certification


def _load_report(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"Performance report must be a JSON object: {path}")
    return payload


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _validate_real_v1_performance_probe(
    value: Any,
    *,
    expected_lane: str,
    renderer_started_at: Any,
) -> tuple[str, ...]:
    probe = _mapping(value)
    failures: list[str] = []

    def fail(message: str) -> None:
        failures.append(f"{expected_lane} real V1 probe {message}")

    if probe.get("schema_version") != 1:
        fail("schema version is invalid")
    if probe.get("production_path") != list(
        REAL_V1_PERFORMANCE_PRODUCTION_PATH
    ):
        fail("production path does not match")
    if (
        probe.get("persistence_kind") != "sqlite+json+parquet"
        or probe.get("persistence_reopened") is not True
    ):
        fail("did not reopen SQLite, JSON, and Parquet persistence")
    if (
        probe.get("application_read_model_interface")
        != "StrategyDiagnosticsV1ApplicationReadModel/1.0"
    ):
        fail("typed Application interface does not match")

    identities = tuple(
        probe.get(name) for name in REAL_V1_IDENTITY_FIELDS
    )
    if any(
        not isinstance(identity, str) or not identity
        for identity in identities
    ):
        fail("identity tuple is incomplete")
    identity_graph = probe.get("expected_identity_graph")
    if (
        not isinstance(identity_graph, list)
        or len(identity_graph) <= len(REAL_V1_IDENTITY_FIELDS)
        or identity_graph != sorted(set(identity_graph))
        or not set(identities).issubset(identity_graph)
    ):
        fail("identity graph is incomplete or non-canonical")

    artifact_hashes = probe.get("artifact_hashes")
    if (
        not isinstance(artifact_hashes, list)
        or not artifact_hashes
        or any(
            not _is_sha256_digest(artifact_hash)
            for artifact_hash in artifact_hashes
        )
    ):
        fail("artifact hashes are unavailable or invalid")

    if (
        probe.get("execution_phase")
        != "same-process-preflight-before-renderer-clock"
    ):
        fail(
            "execution phase does not prove same-process preflight before "
            "the renderer clock"
        )

    for phase in ("initial", "preflight"):
        counts = _mapping(probe.get(f"{phase}_read_counts"))
        minimum = 1 if phase == "initial" else 2
        if any(
            _positive_count(counts.get(operation)) is None
            or int(counts[operation]) < minimum
            for operation in (
                "resolve_journey",
                "read_run",
                "read_evidence",
            )
        ):
            fail(
                f"{phase} typed read counts do not prove "
                f"{minimum} complete sample(s)"
            )

    scheduled = _positive_count(
        probe.get("preflight_samples_scheduled")
    )
    completed = _positive_count(
        probe.get("preflight_samples_completed")
    )
    if (
        scheduled is None
        or completed is None
        or scheduled < 2
        or completed != scheduled
    ):
        fail("preflight samples are incomplete")
    preflight_window = _mapping(probe.get("preflight_window"))
    if (
        not preflight_window.get("started_at")
        or not preflight_window.get("ended_at")
    ):
        fail("preflight window is unavailable")
    preflight_started = _aware_datetime(
        preflight_window.get("started_at")
    )
    preflight_ended = _aware_datetime(preflight_window.get("ended_at"))
    renderer_started = _aware_datetime(renderer_started_at)
    if (
        preflight_started is None
        or preflight_ended is None
        or renderer_started is None
    ):
        fail("preflight timestamps are invalid or timezone-naive")
    elif preflight_started > preflight_ended:
        fail("preflight window order is invalid")
    elif preflight_ended > renderer_started:
        fail("preflight window overlaps renderer measurement")
    if (
        probe.get("fixture_closed") is not True
        or probe.get("fixture_storage_removed") is not True
        or probe.get("clean_exit") is not True
    ):
        fail("did not close persistence cleanly")
    errors = probe.get("errors")
    if not isinstance(errors, list) or errors:
        fail("reported runtime errors")
    return tuple(failures)


def _aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _real_v1_workload_identity(value: Any) -> tuple[Any, ...]:
    probe = _mapping(value)
    return (
        probe.get("production_path"),
        probe.get("persistence_kind"),
        probe.get("application_read_model_interface"),
        *(
            probe.get(name)
            for name in REAL_V1_IDENTITY_FIELDS
        ),
        probe.get("artifact_hashes"),
        probe.get("expected_identity_graph"),
    )


def _is_sha256_digest(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _positive_count(value: Any) -> int | None:
    count = _nonnegative_int(value)
    return count if count is not None and count > 0 else None


def _payload_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _percentile(
    ordered: Sequence[float],
    quantile: float,
) -> float | None:
    if not ordered:
        return None
    index = max(0, min(len(ordered) - 1, ceil(len(ordered) * quantile) - 1))
    return ordered[index]


def _sample_digest(samples: Sequence[float]) -> str:
    payload = json.dumps(samples, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _run_git(project_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(project_root), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _file_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _configure_renderer_environment(lane: str) -> None:
    if lane == "software":
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["QT_QUICK_BACKEND"] = "software"
        os.environ["QSG_RENDER_LOOP"] = "basic"
        os.environ.pop("QSG_RHI_BACKEND", None)
        return
    if lane != "hardware":
        raise ValueError(f"Unsupported renderer lane: {lane}")
    if sys.platform != "win32":
        raise RuntimeError("The hardware performance lane requires Windows")
    os.environ.pop("QT_QPA_PLATFORM", None)
    os.environ.pop("QT_QUICK_BACKEND", None)
    os.environ.pop("QSG_RENDER_LOOP", None)
    os.environ["QSG_RHI_BACKEND"] = "d3d11"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Certify Frontend V2 live-QML performance."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    lane_parser = commands.add_parser(
        "run-lane",
        help="Run one isolated hardware or software renderer lane.",
    )
    lane_parser.add_argument(
        "--lane",
        choices=("hardware", "software"),
        required=True,
    )
    lane_parser.add_argument(
        "--duration-seconds",
        type=float,
        default=float(REFERENCE_FIXTURE.duration_seconds),
    )
    lane_parser.add_argument("--source-commit", required=True)
    lane_parser.add_argument("--output", type=Path, required=True)
    lane_parser.add_argument(
        "--smoke",
        action="store_true",
        help="Allow a short non-certifying runtime probe.",
    )
    certify_parser = commands.add_parser(
        "certify",
        help="Bind hardware, software, and no-manual-trading evidence.",
    )
    certify_parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    certify_parser.add_argument("--source-commit", required=True)
    certify_parser.add_argument(
        "--hardware-report",
        type=Path,
        required=True,
    )
    certify_parser.add_argument(
        "--software-report",
        type=Path,
        required=True,
    )
    certify_parser.add_argument(
        "--safety-output",
        type=Path,
        required=True,
    )
    certify_parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    if arguments.command == "certify":
        source_failures = validate_measurement_source_checkout(
            arguments.project_root,
            expected_source_commit=arguments.source_commit,
            allowed_untracked_paths=(
                arguments.hardware_report.resolve(),
                arguments.software_report.resolve(),
                arguments.safety_output.resolve(),
                arguments.output.resolve(),
            ),
        )
        if source_failures:
            parser.error("; ".join(source_failures))
        safety_report = audit_no_manual_trading_gate(
            arguments.project_root,
            source_commit=arguments.source_commit,
        )
        safety_payload = asdict(safety_report)
        arguments.safety_output.parent.mkdir(parents=True, exist_ok=True)
        arguments.safety_output.write_text(
            json.dumps(safety_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        certification = certify_performance_report_files(
            arguments.hardware_report,
            arguments.software_report,
            safety_payload,
            expected_source_commit=arguments.source_commit,
            expected_toolchain_digest=_file_digest(TOOLCHAIN_LOCK_PATH),
            output_path=arguments.output,
        )
        print(json.dumps(asdict(certification), sort_keys=True))
        return 0 if certification.status == "certified" else 1
    if arguments.duration_seconds <= 0:
        parser.error("--duration-seconds must be positive")
    if (
        not arguments.smoke
        and arguments.duration_seconds < REFERENCE_FIXTURE.duration_seconds
    ):
        parser.error(
            "A certifying lane must run continuously for at least 60 seconds"
        )
    if not arguments.smoke:
        output_path = arguments.output.resolve()
        permitted_artifacts = tuple(
            output_path.parent / name
            for name in (
                "hardware.json",
                "software.json",
                "no-manual-trading.json",
                "certification.json",
            )
        )
        source_failures = validate_measurement_source_checkout(
            Path(__file__).resolve().parents[2],
            expected_source_commit=arguments.source_commit,
            allowed_untracked_paths=(
                output_path,
                *permitted_artifacts,
            ),
        )
        if source_failures:
            parser.error("; ".join(source_failures))
    _configure_renderer_environment(arguments.lane)
    from .frontend_v2_performance_runtime import (
        capture_real_v1_performance_preflight,
        run_performance_lane,
    )

    integrated_v1_evidence = (
        None
        if arguments.smoke
        else capture_real_v1_performance_preflight()
    )
    process_started_ns = perf_counter_ns()
    report = run_performance_lane(
        lane=arguments.lane,
        duration_seconds=arguments.duration_seconds,
        source_commit=arguments.source_commit,
        smoke=arguments.smoke,
        process_started_ns=process_started_ns,
        integrated_v1_evidence=integrated_v1_evidence,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True))
    if arguments.smoke:
        return 0 if not report.get("errors") else 1
    return 0 if report.get("status") == "passed" else 1


__all__ = [
    "PERFORMANCE_THRESHOLDS",
    "REFERENCE_FIXTURE",
    "REFERENCE_MEASUREMENT_PROTOCOL",
    "PerformanceFixture",
    "PerformanceCertification",
    "PerformanceMeasurementProtocol",
    "PerformanceThresholds",
    "build_performance_metric",
    "certify_performance_evidence",
    "certify_performance_report_files",
    "reference_fixture_digest",
    "validate_measurement_source_checkout",
    "validate_performance_lane",
]


if __name__ == "__main__":
    raise SystemExit(main())
