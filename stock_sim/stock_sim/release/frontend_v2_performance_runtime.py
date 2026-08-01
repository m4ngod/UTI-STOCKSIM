"""Qt runtime for the Frontend V2 performance lane.

This module is imported only after the caller configures the requested Qt
renderer.  It deliberately drives the production EventBridge, live Feature
Adapters, internal Qt Adapters, and centralized Journey Workspace.
"""

from __future__ import annotations

import ctypes
import gc
import hashlib
import json
import os
import platform
from array import array
from collections.abc import Callable, Mapping
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from math import ceil, sin
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock, local
from time import perf_counter_ns
from typing import Any, cast

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QObject,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QAccessible, QKeyEvent
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication

from app.event_bridge import EventBridge, EventBridgeBatch
from app.features import (
    APPLICATION_READ_MODEL_INTERFACE_VERSION,
    DIAGNOSTIC_TASKS_APPLICATION_INTERFACE_VERSION,
    ApplicationReadAvailability,
    ApplicationReadError,
    ApplicationReadErrorCode,
    ApplicationReadModelVersion,
    ApplicationReadResult,
    ApproveDiagnosticTaskConfiguration,
    ApprovedScenarioRecipeId,
    CreateDiagnosticTask,
    DeterministicFakeDiagnosticTasksAdapter,
    DiagnosticActorId,
    DiagnosticCampaignCaseSelection,
    DiagnosticCampaignLayer,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    DiagnosticComparisonRole,
    DiagnosticEvidencePackageId,
    DiagnosticStrategySelection,
    DiagnosticTaskCapabilities,
    DiagnosticTaskConfiguration,
    DiagnosticTaskId,
    DiagnosticTaskPresentation,
    DiagnosticTasksContext,
    DiagnosticTasksFeature,
    DiagnosticTasksInventory,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsData,
    EvidenceAndFindingsSelection,
    EvidenceCoverage,
    ExecutionAssumption,
    FormalDiagnosticCampaignId,
    LiveEvidenceAndFindingsAdapter,
    LiveRunMonitoringAdapter,
    LiveStrategyDiagnosticsV1ApplicationAdapter,
    MarketScenarioId,
    ReadOnlyDiagnosticContext,
    ReproductionManifestId,
    ResolvedV1Journey,
    RunLifecyclePhase,
    RunMonitoringContext,
    RunMonitoringData,
    RunMonitoringSelection,
    RunProgress,
    ScenarioSetId,
    SimulationTime,
    SourceRevisionToken,
    StartFormalDiagnosticCampaign,
    StrategyRunId,
    StrategyUnderTestId,
    TerminalOutcome,
    V1JourneySelector,
    ValidateDiagnosticTaskConfiguration,
    WallTime,
)
from app.ui.journey_workspace import JourneyWorkspaceHost

from .frontend_v2_packaging import (
    REAL_V1_IDENTITY_FIELDS,
    TOOLCHAIN_LOCK_PATH,
    running_toolchain,
)
from .frontend_v2_performance import (
    PERFORMANCE_THRESHOLDS,
    REAL_V1_PERFORMANCE_PRODUCTION_PATH,
    REFERENCE_FIXTURE,
    REFERENCE_MEASUREMENT_PROTOCOL,
    WAVE2_PERFORMANCE_COMMAND_IDS,
    WAVE2_PERFORMANCE_PRODUCTION_PATH,
    build_performance_metric,
    reference_fixture_digest,
    validate_performance_lane,
)
from .no_manual_trading_gate import audit_qml_text

UTC = timezone.utc
RUN_ID = "RUN-PERF-001"
CAMPAIGN_ID = "FDC-PERF-001"
STRATEGY_ID = "STRATEGY-PERF-001"
SCENARIO_ID = "SCENARIO-PERF-001"
RECIPE_ID = "RECIPE-PERF-001"
MANIFEST_ID = "RM-PERF-001"
SOURCE_MARKER = "frontend-v2-performance-start"
END_MARKER = "frontend-v2-performance-end"


class _ProcessMemoryCountersEx(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
_PSAPI = ctypes.WinDLL("psapi", use_last_error=True)
_KERNEL32.GetCurrentProcess.restype = ctypes.c_void_p
_PSAPI.GetProcessMemoryInfo.argtypes = (
    ctypes.c_void_p,
    ctypes.POINTER(_ProcessMemoryCountersEx),
    ctypes.c_ulong,
)
_PSAPI.GetProcessMemoryInfo.restype = ctypes.c_int
_PSAPI.EmptyWorkingSet.argtypes = (ctypes.c_void_p,)
_PSAPI.EmptyWorkingSet.restype = ctypes.c_int
_KERNEL32.GlobalMemoryStatusEx.argtypes = (ctypes.POINTER(_MemoryStatusEx),)
_KERNEL32.GlobalMemoryStatusEx.restype = ctypes.c_int


def _trim_process_working_set() -> None:
    """Discard cold startup pages before the continuous-run memory window."""
    if not _PSAPI.EmptyWorkingSet(_KERNEL32.GetCurrentProcess()):
        raise ctypes.WinError(ctypes.get_last_error())


class _PerformanceLoadProjectionReadModel:
    """Thread-safe fixed-load projection used only for SLA measurement."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._thread_reads = local()
        self._revision = 1
        self._status = "running"
        self._updated_at = datetime.now(UTC)
        self._chart_values = tuple(
            100.0
            + sin(index / 137.0) * 2.5
            + sin(index / 997.0) * 1.25
            + (index / REFERENCE_FIXTURE.source_points) * 0.5
            for index in range(REFERENCE_FIXTURE.source_points)
        )
        self._candidate_rows = tuple(
            self._candidate_row(index)
            for index in range(REFERENCE_FIXTURE.candidate_rows)
        )
        content_hasher = hashlib.sha256()
        content_hasher.update(
            json.dumps(
                {
                    "fixture": asdict(REFERENCE_FIXTURE),
                    "candidate_ids": [
                        item["candidate_id"] for item in self._candidate_rows
                    ],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        content_hasher.update(array("d", self._chart_values).tobytes())
        self._content_digest = f"sha256:{content_hasher.hexdigest()}"
        self._evidence_projection_cache: dict[
            tuple[str, EvidenceAndFindingsContext],
            EvidenceAndFindingsData,
        ] = {}

    @property
    def current_evidence_read_revision(self) -> int:
        return int(getattr(self._thread_reads, "evidence_revision", 0))

    def advance(self, *, terminal: str | None = None) -> int:
        with self._lock:
            self._revision += 1
            if terminal is not None:
                self._status = terminal
            self._updated_at = datetime.now(UTC)
            return self._revision

    @property
    def interface_version(self) -> ApplicationReadModelVersion:
        return APPLICATION_READ_MODEL_INTERFACE_VERSION

    def resolve_journey(
        self,
        selector: V1JourneySelector,
    ) -> ApplicationReadResult[ResolvedV1Journey]:
        if (
            selector.campaign_id.value != CAMPAIGN_ID
            or selector.run_id.value != RUN_ID
            or (
                selector.manifest_id is not None
                and selector.manifest_id.value != MANIFEST_ID
            )
        ):
            return self._read_failure(
                code=ApplicationReadErrorCode.SELECTION_NOT_FOUND,
                message="The performance certification journey was not found.",
                retryable=False,
            )
        journey = ResolvedV1Journey(
            run_context=_run_context(),
            evidence_context=_evidence_context(),
            evidence_package_id=selector.evidence_package_id,
            campaign_case_id=MarketScenarioId(SCENARIO_ID),
            campaign_layer=EvidenceCoverage.COMPOUND_SCENARIO,
        )
        revision, status, updated_at = self._run_source_state()
        return ApplicationReadResult(
            availability=ApplicationReadAvailability.READY,
            source_token=self._run_source_token(revision, status, updated_at),
            source_observed_at=updated_at,
            value=journey,
            error=None,
        )

    def read_run(
        self,
        journey: ResolvedV1Journey,
    ) -> ApplicationReadResult[RunMonitoringData]:
        selection = journey.run_context.selection
        if (
            selection is None
            or selection.run_id is None
            or selection.campaign_id.value != CAMPAIGN_ID
            or selection.run_id.value != RUN_ID
        ):
            return self._read_failure(
                code=ApplicationReadErrorCode.IDENTITY_MISMATCH,
                message="The performance Run identity does not match its journey.",
                retryable=False,
            )
        revision, status, updated_at = self._run_source_state()
        lifecycle = {
            "running": RunLifecyclePhase.RUNNING,
            "completed": RunLifecyclePhase.COMPLETED,
            "failed": RunLifecyclePhase.FAILED,
            "canceled": RunLifecyclePhase.CANCELED,
        }.get(status, RunLifecyclePhase.QUEUED)
        terminal_outcome = {
            RunLifecyclePhase.COMPLETED: TerminalOutcome.COMPLETED,
            RunLifecyclePhase.FAILED: TerminalOutcome.FAILED,
            RunLifecyclePhase.CANCELED: TerminalOutcome.CANCELED,
        }.get(lifecycle)
        terminal = terminal_outcome is not None
        started_at = updated_at - timedelta(minutes=5)
        data = RunMonitoringData(
            selection=selection,
            strategy_id=StrategyUnderTestId(STRATEGY_ID),
            market_scenario_id=MarketScenarioId(SCENARIO_ID),
            scenario_set_id=ScenarioSetId("SET-PERF-001"),
            reproduction_manifest_id=ReproductionManifestId(MANIFEST_ID),
            task_id=None,
            lifecycle=lifecycle,
            terminal_outcome=terminal_outcome,
            progress=RunProgress(
                current_node_id=(
                    "NODE-PERF-TERMINAL" if terminal else "NODE-PERF-RUNNING"
                ),
                current_node_label=(
                    "Evidence ready" if terminal else "Running fixed fixture"
                ),
                completed=5 if terminal else 3,
                total=5,
            ),
            simulation_time=SimulationTime(
                sim_day=5 if terminal else 3,
                instant=updated_at - timedelta(days=1),
            ),
            wall_time=WallTime(
                started_at=started_at,
                observed_at=updated_at,
                elapsed=updated_at - started_at,
            ),
            execution_assumptions=(
                ExecutionAssumption(
                    name="fee_multiplier",
                    requested_value="1.0x",
                    effective_value="1.6x",
                    override_reason="Approved Scenario Recipe override",
                ),
            ),
            alerts=(),
            context=ReadOnlyDiagnosticContext(
                market=("600519.SH · diagnostic market context",),
                account=("MODEL-PERF-00 · research account",),
                positions=("600519.SH · +100 · evidence snapshot",),
                orders=("ORD-PERF-001 · read-only evidence trace",),
                fills=("FILL-PERF-001 · read-only evidence trace",),
            ),
            capabilities=DiagnosticTaskCapabilities(False, False, False),
            active_task=None,
        )
        return ApplicationReadResult(
            availability=ApplicationReadAvailability.READY,
            source_token=self._run_source_token(revision, status, updated_at),
            source_observed_at=updated_at,
            value=data,
            error=None,
        )

    def read_evidence(
        self,
        journey: ResolvedV1Journey,
    ) -> ApplicationReadResult[EvidenceAndFindingsData]:
        from app.features.live_evidence_and_findings import (
            _candidate_rows,
            _evidence_payload,
            _map_record,
        )

        selection = journey.evidence_context.selection
        if (
            selection is None
            or selection.campaign_id.value != CAMPAIGN_ID
            or selection.run_id.value != RUN_ID
        ):
            return self._read_failure(
                code=ApplicationReadErrorCode.IDENTITY_MISMATCH,
                message=(
                    "The performance Diagnostic Evidence identity does not "
                    "match its journey."
                ),
                retryable=False,
            )
        record = self.get_evidence_and_findings_snapshot(RUN_ID)
        if record is None:
            return self._read_failure(
                code=ApplicationReadErrorCode.EVIDENCE_PENDING,
                message="Performance Diagnostic Evidence is pending.",
                retryable=True,
            )
        cache_key = (self._content_digest, journey.evidence_context)
        with self._lock:
            data = self._evidence_projection_cache.get(cache_key)
        try:
            if data is None:
                payload = _evidence_payload(record)
                mapped = _map_record(
                    journey.evidence_context,
                    record,
                    payload,
                    _candidate_rows(payload),
                )
                with self._lock:
                    data = self._evidence_projection_cache.setdefault(
                        cache_key,
                        mapped,
                    )
        except Exception:
            return self._read_failure(
                code=ApplicationReadErrorCode.EVIDENCE_MAPPING_FAILED,
                message="Performance Diagnostic Evidence is invalid.",
                retryable=False,
            )
        revision, status, updated_at = self._run_source_state()
        return ApplicationReadResult(
            availability=ApplicationReadAvailability.READY,
            source_token=self._run_source_token(
                revision,
                status,
                updated_at,
            ),
            source_observed_at=updated_at,
            value=data,
            error=None,
        )

    def _run_source_state(self) -> tuple[int, str, datetime]:
        with self._lock:
            return self._revision, self._status, self._updated_at

    @staticmethod
    def _run_source_token(
        revision: int,
        status: str,
        updated_at: datetime,
    ) -> SourceRevisionToken:
        payload = f"{CAMPAIGN_ID}|{RUN_ID}|{revision}|{status}|{updated_at.isoformat()}"
        return SourceRevisionToken(hashlib.sha256(payload.encode("utf-8")).hexdigest())

    @staticmethod
    def _read_failure(
        *,
        code: ApplicationReadErrorCode,
        message: str,
        retryable: bool,
    ) -> ApplicationReadResult[Any]:
        return ApplicationReadResult(
            availability=ApplicationReadAvailability.FAILED,
            source_token=None,
            source_observed_at=None,
            value=None,
            error=ApplicationReadError(
                code=code,
                message=message,
                retryable=retryable,
            ),
        )

    def get_evidence_and_findings_snapshot(
        self,
        run_id: str,
    ) -> dict[str, Any] | None:
        if run_id != RUN_ID:
            return None
        with self._lock:
            revision = self._revision
            status = self._status
            updated_at = self._updated_at
            candidates = self._candidate_rows
        self._thread_reads.evidence_revision = revision
        return {
            "run_id": RUN_ID,
            "revision": revision,
            "updated_at": updated_at.isoformat(),
            "status": status,
            "content_digest": self._content_digest,
            "selection": {
                "campaign_id": CAMPAIGN_ID,
                "run_id": RUN_ID,
                "strategy_id": STRATEGY_ID,
                "market_scenario_id": SCENARIO_ID,
                "approved_recipe_id": RECIPE_ID,
                "reproduction_manifest_id": MANIFEST_ID,
            },
            "candidates": candidates,
            "read_only_context": {
                "market": ["600519.SH · closed diagnostic session"],
                "account": ["MODEL-PERF-00 · simulated research account"],
                "positions": ["600519.SH · +100 · evidence snapshot"],
                "orders": [
                    {
                        "id": "ORD-PERF-001",
                        "instrument": "600519.SH",
                        "status": "filled",
                        "diagnostic_note": "Read-only execution trace.",
                    }
                ],
                "fills": [
                    {
                        "id": "FILL-PERF-001",
                        "order_id": "ORD-PERF-001",
                        "instrument": "600519.SH",
                        "quantity": 100,
                        "price": "1500.00",
                    }
                ],
            },
        }

    def _candidate_row(self, index: int) -> dict[str, Any]:
        suffix = f"{index:02d}"
        candidate_id = f"MODEL-PERF-{suffix}"
        baseline_id = f"E-{suffix}-BASE"
        isolated_id = f"E-{suffix}-ISO"
        compound_id = f"E-{suffix}-COMPOUND"
        comparison_id = f"CMP-{suffix}-FEE"
        finding_id = f"F-{suffix}-FEE"
        breakpoint_id = f"BP-{suffix}-FEE"
        row: dict[str, Any] = {
            "candidate_id": candidate_id,
            "label": f"Performance candidate {suffix}",
            "evidence": [
                {
                    "id": baseline_id,
                    "coverage": "baseline",
                    "dimension": "return",
                    "label": "Baseline return",
                    "value": f"{7.0 + index / 100:.2f}",
                    "unit": "%",
                    "availability": "complete",
                    "interpretation": "Fixed-fixture baseline evidence.",
                },
                {
                    "id": isolated_id,
                    "coverage": "isolated_sensitivity",
                    "dimension": "execution",
                    "label": "Fee sensitivity",
                    "value": "-1.8",
                    "comparison_evidence_id": baseline_id,
                    "comparison_value": "7.0",
                    "unit": "return delta points",
                    "availability": "complete",
                    "interpretation": "Fees weaken the baseline result.",
                },
                {
                    "id": compound_id,
                    "coverage": "compound_scenario",
                    "dimension": "stability",
                    "label": "Compound stability",
                    "value": "61",
                    "comparison_evidence_id": baseline_id,
                    "comparison_value": "83",
                    "unit": "% stable windows",
                    "availability": "complete",
                    "interpretation": "Compound stress reduces stability.",
                },
            ],
            "comparisons": [
                {
                    "id": comparison_id,
                    "label": "Baseline versus fee sensitivity",
                    "reference_evidence_id": baseline_id,
                    "observed_evidence_id": isolated_id,
                    "interpretation": "Effective fees reduce the result.",
                }
            ],
            "findings": [
                {
                    "id": finding_id,
                    "title": "Fees break the baseline result",
                    "disposition": "concern",
                    "comparison_summary": "The fee case is weaker.",
                    "failure_reason": "Turnover amplifies effective fees.",
                    "evidence_ids": [baseline_id, isolated_id],
                    "comparison_ids": [comparison_id],
                    "sensitivity_breakpoints": [
                        {
                            "id": breakpoint_id,
                            "assumption_name": "fee_multiplier",
                            "threshold": "1.6x",
                            "outcome": "Excess return becomes non-positive.",
                            "evidence_ids": [baseline_id, isolated_id],
                        }
                    ],
                }
            ],
            "execution_assumptions": [
                {
                    "name": "fee_multiplier",
                    "requested_value": "1.0x",
                    "effective_value": "1.6x",
                    "override_reason": "Approved Scenario Recipe override",
                }
            ],
            "provenance": {
                "artifact_hashes": [f"sha256:performance-{suffix}"],
                "source_run_ids": [RUN_ID],
                "runner_version": "frontend-v2-performance/1",
                "build_version": "uti-stocksim/wave1",
                "dependencies": [
                    {
                        "name": "reproduction-manifest",
                        "version": MANIFEST_ID,
                        "artifact_hash": "sha256:performance-manifest",
                    }
                ],
            },
        }
        if index == 0:
            row["chart"] = {
                "identity": "MODEL-PERF-00-diagnostic-series",
                "label": "Fixed diagnostic evidence path",
                "unit": "normalized evidence value",
                "values": self._chart_values,
                "overlays": [
                    {
                        "identity": "OV-PERF-LOW",
                        "label": "Lower evidence threshold",
                        "axis": "horizontal",
                        "coordinate": 98.5,
                        "interpretation": "Lower diagnostic threshold.",
                        "evidence_ids": [baseline_id],
                    },
                    {
                        "identity": "OV-PERF-HIGH",
                        "label": "Upper evidence threshold",
                        "axis": "horizontal",
                        "coordinate": 102.5,
                        "interpretation": "Upper diagnostic threshold.",
                        "evidence_ids": [isolated_id],
                    },
                    {
                        "identity": "OV-PERF-BREAK",
                        "label": "Sensitivity breakpoint",
                        "axis": "vertical",
                        "coordinate": 60_000,
                        "interpretation": "Fixed-fixture sensitivity point.",
                        "evidence_ids": [compound_id],
                    },
                ],
            }
        return row


class _RealV1PerformanceProbe:
    """Verify the reopened V1 product before the renderer clock starts."""

    def __init__(
        self,
        *,
        temporary_directory: TemporaryDirectory[str],
        fixture: Any,
        fixture_archive_digest: str | None = None,
    ) -> None:
        self._temporary_directory = temporary_directory
        self._storage_root = Path(temporary_directory.name)
        self._fixture = fixture
        self._fixture_archive_digest = fixture_archive_digest
        self._adapter = LiveStrategyDiagnosticsV1ApplicationAdapter(
            fixture.application,
            fixture.engine,
        )
        self._selector = V1JourneySelector(
            campaign_id=FormalDiagnosticCampaignId(
                fixture.campaign.campaign_id
            ),
            run_id=StrategyRunId(fixture.selected_run.run_id),
            evidence_package_id=DiagnosticEvidencePackageId(
                fixture.evidence_package.evidence_package_id
            ),
            manifest_id=ReproductionManifestId(
                fixture.selected_manifest.manifest_id
            ),
        )
        specification = fixture.selected_run.specification
        self._identity = {
            "campaign_identity": fixture.campaign.campaign_id,
            "case_identity": fixture.selected_manifest.case_id,
            "run_identity": fixture.selected_run.run_id,
            "strategy_identity": specification.strategy_id,
            "approved_recipe_identity": specification.recipe_version_id,
            "evidence_package_identity": (
                fixture.evidence_package.evidence_package_id
            ),
            "reproduction_manifest_identity": (
                fixture.selected_manifest.manifest_id
            ),
        }
        if tuple(self._identity) != REAL_V1_IDENTITY_FIELDS:
            raise RuntimeError(
                "Real V1 probe identity fields do not match the release "
                "contract"
            )
        interface_version = self._adapter.interface_version
        self._application_interface = (
            "StrategyDiagnosticsV1ApplicationReadModel/"
            f"{interface_version.major}.{interface_version.minor}"
        )
        self._artifact_hashes = tuple(fixture.artifact_hashes)
        self._expected_identity_graph = tuple(
            fixture.expected_identity_graph
        )
        self._lock = RLock()
        self._initial_read_counts = {
            "resolve_journey": 0,
            "read_run": 0,
            "read_evidence": 0,
        }
        self._preflight_read_counts = {
            "resolve_journey": 0,
            "read_run": 0,
            "read_evidence": 0,
        }
        self._preflight_samples_scheduled = 0
        self._preflight_samples_completed = 0
        self._preflight_started_at: datetime | None = None
        self._preflight_ended_at: datetime | None = None
        self._errors: list[str] = []
        self._closed = False
        self._sample(preflight=False)
        if self._errors:
            errors = "; ".join(self._errors)
            self.close()
            raise RuntimeError(
                "Real V1 performance probe preparation failed: "
                f"{errors}"
            )

    def run_preflight(self, *, sample_count: int = 2) -> None:
        if sample_count < 2:
            raise ValueError(
                "Real V1 preflight requires at least two complete samples"
            )
        with self._lock:
            if self._closed:
                raise RuntimeError("Real V1 preflight is already closed")
            if self._preflight_started_at is not None:
                raise RuntimeError("Real V1 preflight already ran")
            self._preflight_started_at = datetime.now(UTC)
        for _ in range(sample_count):
            with self._lock:
                self._preflight_samples_scheduled += 1
            self._sample(preflight=True)
        with self._lock:
            self._preflight_ended_at = datetime.now(UTC)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._fixture.close()
        except Exception as error:
            with self._lock:
                self._errors.append(
                    "Real V1 fixture cleanup failed: "
                    f"{type(error).__name__}"
                )
        try:
            self._temporary_directory.cleanup()
        except Exception as error:
            with self._lock:
                self._errors.append(
                    "Real V1 temporary storage cleanup failed: "
                    f"{type(error).__name__}"
                )

    def evidence(self) -> dict[str, Any]:
        with self._lock:
            errors = tuple(self._errors)
            initial_counts = dict(self._initial_read_counts)
            preflight_counts = dict(self._preflight_read_counts)
            scheduled = self._preflight_samples_scheduled
            completed = self._preflight_samples_completed
            started_at = self._preflight_started_at
            ended_at = self._preflight_ended_at
        storage_removed = not self._storage_root.exists()
        clean_exit = bool(
            self._closed
            and self._fixture.closed
            and storage_removed
            and not errors
        )
        return {
            "schema_version": 1,
            "production_path": list(
                REAL_V1_PERFORMANCE_PRODUCTION_PATH
            ),
            "persistence_kind": "sqlite+json+parquet",
            "persistence_reopened": True,
            "fixture_archive_digest": self._fixture_archive_digest,
            "application_read_model_interface": (
                self._application_interface
            ),
            **self._identity,
            "artifact_hashes": list(self._artifact_hashes),
            "expected_identity_graph": list(
                self._expected_identity_graph
            ),
            "initial_read_counts": initial_counts,
            "execution_phase": (
                "same-process-preflight-before-renderer-clock"
            ),
            "preflight_read_counts": preflight_counts,
            "preflight_samples_scheduled": scheduled,
            "preflight_samples_completed": completed,
            "preflight_window": {
                "started_at": (
                    None if started_at is None else started_at.isoformat()
                ),
                "ended_at": (
                    None if ended_at is None else ended_at.isoformat()
                ),
            },
            "fixture_closed": self._fixture.closed,
            "fixture_storage_removed": storage_removed,
            "errors": list(errors),
            "clean_exit": clean_exit,
        }

    def _sample(self, *, preflight: bool) -> None:
        counts = (
            self._preflight_read_counts
            if preflight
            else self._initial_read_counts
        )
        try:
            journey_result = self._adapter.resolve_journey(self._selector)
            journey = _require_ready_v1_value(
                journey_result,
                "resolve_journey",
            )
            run_result = self._adapter.read_run(journey)
            run_data = _require_ready_v1_value(
                run_result,
                "read_run",
            )
            evidence_result = self._adapter.read_evidence(journey)
            evidence_data = _require_ready_v1_value(
                evidence_result,
                "read_evidence",
            )
            self._validate_identity(journey, run_data, evidence_data)
            with self._lock:
                for name in counts:
                    counts[name] += 1
        except Exception as error:
            with self._lock:
                self._errors.append(
                    "Real V1 performance read failed: "
                    f"{type(error).__name__}"
                )
        finally:
            if preflight:
                with self._lock:
                    self._preflight_samples_completed += 1

    def _validate_identity(
        self,
        journey: Any,
        run_data: Any,
        evidence_data: Any,
    ) -> None:
        run_selection = journey.run_context.selection
        evidence_selection = journey.evidence_context.selection
        if run_selection is None or evidence_selection is None:
            raise RuntimeError("Real V1 journey selection is unavailable")
        observed = {
            "campaign_identity": run_selection.campaign_id.value,
            "case_identity": journey.campaign_case_id.value,
            "run_identity": run_selection.run_id.value,
            "strategy_identity": evidence_selection.strategy_id.value,
            "approved_recipe_identity": (
                evidence_selection.approved_recipe_id.value
            ),
            "evidence_package_identity": (
                journey.evidence_package_id.value
            ),
            "reproduction_manifest_identity": (
                evidence_selection.reproduction_manifest_id.value
            ),
        }
        if observed != self._identity:
            raise RuntimeError("Real V1 journey identity changed")
        if (
            run_data.selection != run_selection
            or evidence_data.selection != evidence_selection
        ):
            raise RuntimeError(
                "Real V1 typed read identity does not match its journey"
            )
        if not set(self._identity.values()).issubset(
            self._expected_identity_graph
        ):
            raise RuntimeError(
                "Real V1 fixture identity graph is incomplete"
            )


def _require_ready_v1_value(
    result: ApplicationReadResult[Any],
    operation: str,
) -> Any:
    if (
        result.availability is not ApplicationReadAvailability.READY
        or result.value is None
        or result.error is not None
    ):
        raise RuntimeError(
            f"Real V1 {operation} did not return authoritative data"
        )
    return result.value


def prepare_real_v1_performance_probe(
    *,
    fixture_archive_path: Path | None = None,
    expected_source_commit: str | None = None,
) -> _RealV1PerformanceProbe:
    """Open the real V1 fixture before the startup clock begins."""

    from .strategy_diagnostics_v1_release_fixture import (
        FORMAL_V1_RELEASE_FIXTURE_DIRNAME,
        create_file_backed_formal_v1_release_fixture,
        extract_sealed_formal_v1_release_fixture_archive,
        open_sealed_formal_v1_release_fixture,
    )

    if (fixture_archive_path is None) != (expected_source_commit is None):
        raise ValueError(
            "fixture_archive_path and expected_source_commit must be "
            "provided together"
        )
    temporary_directory = TemporaryDirectory(
        prefix="uti-stocksim-performance-real-v1-"
    )
    storage_root = Path(temporary_directory.name)
    fixture = None
    fixture_archive_digest = None
    try:
        if fixture_archive_path is None:
            fixture = create_file_backed_formal_v1_release_fixture(
                database_path=(
                    storage_root / "strategy-diagnostics-v1.sqlite3"
                ),
                artifact_root=storage_root / "artifacts",
            )
        else:
            fixture_archive_digest = (
                "sha256:"
                + hashlib.sha256(
                    fixture_archive_path.resolve().read_bytes()
                ).hexdigest()
            )
            bundle_root = (
                storage_root / FORMAL_V1_RELEASE_FIXTURE_DIRNAME
            )
            extract_sealed_formal_v1_release_fixture_archive(
                archive_path=fixture_archive_path.resolve(),
                bundle_root=bundle_root,
            )
            fixture = open_sealed_formal_v1_release_fixture(
                bundle_root=bundle_root,
                expected_source_commit=expected_source_commit,
            )
        return _RealV1PerformanceProbe(
            temporary_directory=temporary_directory,
            fixture=fixture,
            fixture_archive_digest=fixture_archive_digest,
        )
    except BaseException:
        if fixture is not None and not fixture.closed:
            try:
                fixture.close()
            except BaseException:
                pass
        temporary_directory.cleanup()
        raise


def capture_real_v1_performance_preflight(
    *,
    fixture_archive_path: Path | None = None,
    expected_source_commit: str | None = None,
) -> dict[str, Any]:
    """Capture and release real V1 evidence before timing the renderer."""

    probe = prepare_real_v1_performance_probe(
        fixture_archive_path=fixture_archive_path,
        expected_source_commit=expected_source_commit,
    )
    try:
        probe.run_preflight(sample_count=2)
    finally:
        probe.close()
    evidence = probe.evidence()
    probe = None
    gc.collect()
    _trim_process_working_set()
    return evidence


class _MetricRecorder:
    def __init__(
        self,
        queries: _PerformanceLoadProjectionReadModel,
    ) -> None:
        self._queries = queries
        self._lock = RLock()
        self.batch_acceptance_ns: dict[int, int] = {}
        self.view_to_source_revision: dict[int, int] = {}
        self.source_event_ns: list[int] = []
        self.event_to_visible_ms: list[float] = []
        self.input_response_ms: list[float] = []
        self.accepted_revisions: list[int] = []
        self.main_thread_gaps_ms: list[float] = []
        self.memory_mib: list[float] = []
        self.terminal_source_revision = 0
        self.terminal_visible_revision = 0
        self.terminal_visible_ms: float | None = None

    def record_batch(self, batch: EventBridgeBatch) -> None:
        accepted_ns = perf_counter_ns()
        with self._lock:
            for snapshot in batch.snapshots:
                revision = snapshot.get("source_revision")
                if isinstance(revision, int) and not isinstance(revision, bool):
                    self.batch_acceptance_ns[revision] = accepted_ns

    def record_feature_state(self, state: Any) -> None:
        source_revision = self._queries.current_evidence_read_revision
        if source_revision < 1:
            return
        with self._lock:
            self.view_to_source_revision[int(state.revision)] = source_revision

    def record_visible_revision(self, view_revision: int, visible_ns: int) -> None:
        with self._lock:
            if self.accepted_revisions and view_revision <= self.accepted_revisions[-1]:
                return
            self.accepted_revisions.append(view_revision)
            source_revision = self.view_to_source_revision.get(view_revision)
            accepted_ns = (
                None
                if source_revision is None
                else self.batch_acceptance_ns.get(source_revision)
            )
            if accepted_ns is not None:
                self.event_to_visible_ms.append((visible_ns - accepted_ns) / 1_000_000)
            if (
                source_revision == self.terminal_source_revision
                and accepted_ns is not None
            ):
                self.terminal_visible_revision = view_revision
                self.terminal_visible_ms = (visible_ns - accepted_ns) / 1_000_000


class _QtPerformanceProbe(QObject):
    renderedFrameObserved = Signal(int, object)

    def __init__(
        self,
        *,
        app: QApplication,
        host: JourneyWorkspaceHost,
        recorder: _MetricRecorder,
        queries: _PerformanceLoadProjectionReadModel,
        bridge: EventBridge,
        duration_seconds: float,
        process_started_ns: int,
        on_measurement_active: Callable[[], None],
        on_finished: Callable[[], None],
    ) -> None:
        super().__init__(host)
        self._app = app
        self._host = host
        self._root = host.rootObject()
        self._adapter = host._evidence_and_findings
        if self._root is None or self._adapter is None:
            raise RuntimeError("Evidence & Findings QML Adapter is unavailable")
        self._renderer = self._required_item("productionEvidenceChart")
        self._candidate_repeater = self._required_object("evidenceCandidateRepeater")
        self._context_panel = self._required_item("evidenceContextPanel")
        loader = self._required_item("evidenceAndFindingsPageLoader")
        page = loader.property("item")
        if not isinstance(page, QQuickItem):
            raise RuntimeError("Evidence & Findings QML page is unavailable")
        self._tab_findings = page.property("firstTabControl")
        self._tab_assumptions = page.property("secondTabControl")
        if not isinstance(self._tab_findings, QQuickItem) or not isinstance(
            self._tab_assumptions, QQuickItem
        ):
            raise RuntimeError("Evidence QML tab controls are unavailable")
        self._recorder = recorder
        self._queries = queries
        self._bridge = bridge
        self._duration_seconds = duration_seconds
        self._process_started_ns = process_started_ns
        self._on_measurement_active = on_measurement_active
        self._on_finished = on_finished
        self._measurement_started_ns: int | None = None
        self._measurement_ended_ns: int | None = None
        self._started_at: datetime | None = None
        self._ended_at: datetime | None = None
        self._usable_state_ms: float | None = None
        self._graphics_api = "Unknown"
        self._last_stall_tick_ns: int | None = None
        self._source_events = 0
        self._pending_input: tuple[QQuickItem, str, int] | None = None
        self._terminal_sent_ns: int | None = None
        self._finished = False
        self.errors: list[str] = []
        self.read_only_context_visible = False
        self.manual_action_count = _manual_action_count(self._root)
        self._synchronized_revision = 0
        self.renderedFrameObserved.connect(
            self._record_rendered_frame,
            Qt.ConnectionType.QueuedConnection,
        )

        self._watchdog = QTimer(self)
        self._watchdog.setTimerType(Qt.TimerType.PreciseTimer)
        self._watchdog.setInterval(1)
        self._watchdog.timeout.connect(self._watch)
        self._watchdog.start()

        self._source_timer = QTimer(self)
        self._source_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._source_timer.setInterval(REFERENCE_FIXTURE.source_cadence_ms)
        self._source_timer.timeout.connect(self._publish_source_event)

        self._stall_timer = QTimer(self)
        self._stall_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._stall_timer.setInterval(5)
        self._stall_timer.timeout.connect(self._sample_main_thread)

        self._memory_timer = QTimer(self)
        self._memory_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._memory_timer.setInterval(100)
        self._memory_timer.timeout.connect(self._sample_memory)

        self._input_timer = QTimer(self)
        self._input_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._input_timer.setInterval(250)
        self._input_timer.timeout.connect(self._send_input)

        self._terminal_timeout = QTimer(self)
        self._terminal_timeout.setSingleShot(True)
        self._terminal_timeout.timeout.connect(self._terminal_timed_out)

    @property
    def duration_seconds(self) -> float:
        if self._measurement_started_ns is None or self._measurement_ended_ns is None:
            return 0.0
        return (
            self._measurement_ended_ns - self._measurement_started_ns
        ) / 1_000_000_000

    @property
    def started_at(self) -> datetime:
        return self._started_at or datetime.now(UTC)

    @property
    def ended_at(self) -> datetime:
        return self._ended_at or datetime.now(UTC)

    @property
    def usable_state_ms(self) -> float:
        return float(self._usable_state_ms or 0.0)

    @property
    def observed_fixture(self) -> dict[str, int]:
        return {
            "source_points": self._adapter.chartSourcePointCount,
            "visible_points": int(self._renderer.property("samplePointCount") or 0),
            "overlay_count": int(self._renderer.property("overlayCount") or 0),
            "candidate_rows": int(self._candidate_repeater.property("count") or 0),
            "source_cadence_ms": self._source_timer.interval(),
            "paint_cap_fps": (self._adapter._chart_frame_gate.max_frames_per_second),
        }

    @property
    def graphics_api(self) -> str:
        return self._graphics_api

    @property
    def source_events(self) -> int:
        return self._source_events

    @property
    def measurement_active(self) -> bool:
        return (
            self._measurement_started_ns is not None
            and self._measurement_ended_ns is None
            and self._source_events > 0
        )

    @Slot()
    def before_synchronize(self) -> None:
        self._synchronized_revision = int(
            self._renderer.property("acceptedRevision") or 0
        )

    @Slot()
    def after_render(self) -> None:
        self.renderedFrameObserved.emit(
            self._synchronized_revision,
            perf_counter_ns(),
        )

    @Slot(int, object)
    def _record_rendered_frame(
        self,
        revision: int,
        visible_ns_value: object,
    ) -> None:
        if self._finished:
            return
        visible_ns = int(cast(int, visible_ns_value))
        self._graphics_api = (
            self._host.quickWindow().rendererInterface().graphicsApi().name
        )
        if revision > 0:
            self._recorder.record_visible_revision(revision, visible_ns)
        if self._usable_state_ms is None and self._fixture_is_usable():
            self._usable_state_ms = (visible_ns - self._process_started_ns) / 1_000_000
            self.read_only_context_visible = bool(
                self._context_panel.property("visible")
                and "read-only" in self._adapter.readOnlyContextText.lower()
            )
            self._adapter.setActiveTab("findings")
            QTimer.singleShot(0, self._start_measurement)
        if (
            self._recorder.terminal_visible_ms is not None
            and self._terminal_sent_ns is not None
        ):
            self._finish()

    def _fixture_is_usable(self) -> bool:
        expected = {
            "source_points": REFERENCE_FIXTURE.source_points,
            "visible_points": REFERENCE_FIXTURE.visible_points,
            "overlay_count": REFERENCE_FIXTURE.overlay_count,
            "candidate_rows": REFERENCE_FIXTURE.candidate_rows,
            "source_cadence_ms": REFERENCE_FIXTURE.source_cadence_ms,
            "paint_cap_fps": REFERENCE_FIXTURE.paint_cap_fps,
        }
        return bool(
            self.observed_fixture == expected
            and self._context_panel.property("visible")
        )

    @Slot()
    def _start_measurement(self) -> None:
        if self._measurement_started_ns is not None:
            return
        gc.collect()
        _trim_process_working_set()
        self._measurement_started_ns = perf_counter_ns()
        self._started_at = datetime.now(UTC)
        self._last_stall_tick_ns = self._measurement_started_ns
        self._sample_memory()
        self._source_timer.start()
        self._stall_timer.start()
        self._memory_timer.start()
        self._input_timer.start()
        QTimer.singleShot(
            REFERENCE_FIXTURE.source_cadence_ms
            + max(1, REFERENCE_FIXTURE.source_cadence_ms // 2),
            self._run_measurement_active_load,
        )
        QTimer.singleShot(
            max(1, ceil(self._duration_seconds * 1_000)),
            self._publish_terminal,
        )

    @Slot()
    def _run_measurement_active_load(self) -> None:
        if self._measurement_ended_ns is not None:
            self.errors.append(
                "Wave 2 command load missed the active measurement window"
            )
            return
        if self._measurement_started_ns is None or self._source_events < 1:
            QTimer.singleShot(1, self._run_measurement_active_load)
            return
        try:
            self._on_measurement_active()
        except BaseException as error:
            self.errors.append(
                "Wave 2 command load failed: "
                f"{type(error).__name__}: {error}"
            )

    @Slot()
    def _publish_source_event(self) -> None:
        source_ns = perf_counter_ns()
        revision = self._queries.advance()
        self._recorder.source_event_ns.append(source_ns)
        self._source_events += 1
        self._bridge.on_snapshot(
            {
                "run_id": RUN_ID,
                "source_revision": revision,
                "status": "running",
            }
        )

    @Slot()
    def _publish_terminal(self) -> None:
        if self._terminal_sent_ns is not None:
            return
        if self._measurement_started_ns is None:
            return
        now_ns = perf_counter_ns()
        measurement_deadline_ns = self._measurement_started_ns + ceil(
            self._duration_seconds * 1_000_000_000
        )
        remaining_ns = measurement_deadline_ns - now_ns
        if remaining_ns > 0:
            QTimer.singleShot(
                max(1, ceil(remaining_ns / 1_000_000)),
                self._publish_terminal,
            )
            return
        self._source_timer.stop()
        self._input_timer.stop()
        self._measurement_ended_ns = now_ns
        self._ended_at = datetime.now(UTC)
        revision = self._queries.advance(terminal="completed")
        self._recorder.terminal_source_revision = revision
        self._terminal_sent_ns = perf_counter_ns()
        self._source_events += 1
        self._bridge.on_snapshot(
            {
                "run_id": RUN_ID,
                "source_revision": revision,
                "status": "completed",
            }
        )
        self._terminal_timeout.start(2_000)

    @Slot()
    def _terminal_timed_out(self) -> None:
        self.errors.append(
            "Terminal completed revision was not visible within 2 seconds"
        )
        self._finish()

    @Slot()
    def _sample_main_thread(self) -> None:
        now_ns = perf_counter_ns()
        previous = self._last_stall_tick_ns
        self._last_stall_tick_ns = now_ns
        if previous is not None:
            self._recorder.main_thread_gaps_ms.append((now_ns - previous) / 1_000_000)

    @Slot()
    def _sample_memory(self) -> None:
        rss = _process_working_set_bytes()
        self._recorder.memory_mib.append(rss / (1024 * 1024))

    @Slot()
    def _send_input(self) -> None:
        if self._pending_input is not None:
            return
        target = (
            self._tab_assumptions
            if self._adapter.activeTab != "assumptions"
            else self._tab_findings
        )
        target.forceActiveFocus()
        expected_tab = str(target.property("choiceValue"))
        started_ns = perf_counter_ns()
        self._pending_input = (target, expected_tab, started_ns)
        QCoreApplication.sendEvent(
            target,
            QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_Return,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        QCoreApplication.sendEvent(
            target,
            QKeyEvent(
                QEvent.Type.KeyRelease,
                Qt.Key.Key_Return,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        self._watch()

    @Slot()
    def _watch(self) -> None:
        pending = self._pending_input
        if pending is not None:
            target, expected_tab, started_ns = pending
            if self._adapter.activeTab == expected_tab:
                self._recorder.input_response_ms.append(
                    (perf_counter_ns() - started_ns) / 1_000_000
                )
                self._pending_input = None
            elif perf_counter_ns() - started_ns > 100_000_000:
                self.errors.append(
                    f"Input response timed out for {target.objectName()}"
                )
                self._pending_input = None

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._terminal_timeout.stop()
        self._watchdog.stop()
        self._source_timer.stop()
        self._stall_timer.stop()
        self._memory_timer.stop()
        self._input_timer.stop()
        self._sample_memory()
        for error in self._host.errors():
            self.errors.append(error.toString())
        self._on_finished()

    def _required_item(self, object_name: str) -> QQuickItem:
        item = self._root.findChild(QQuickItem, object_name)
        if item is None:
            raise RuntimeError(f"QML item is unavailable: {object_name}")
        return cast(QQuickItem, item)

    def _required_object(self, object_name: str) -> QObject:
        item = self._root.findChild(QObject, object_name)
        if item is None:
            raise RuntimeError(f"QML object is unavailable: {object_name}")
        return cast(QObject, item)


def _diagnostic_configuration(
    inventory: DiagnosticTasksInventory,
) -> DiagnosticTaskConfiguration:
    recipe_by_id = {
        item.recipe_version_id: item for item in inventory.approved_recipes
    }
    baseline_case_id = next(
        item.campaign_case_id
        for item in inventory.market_scenarios
        if item.layer is DiagnosticCampaignLayer.BASELINE
    )
    return DiagnosticTaskConfiguration.create(
        strategy_selections=tuple(
            DiagnosticStrategySelection(
                strategy_id=item.strategy_id,
                strategy_version=item.strategy_version,
                compatibility_manifest_hash=item.compatibility_manifest_hash,
                guardrail_profile_id=item.guardrail_profile_id,
                guardrail_profile_version=item.guardrail_profile_version,
            )
            for item in inventory.strategies
        ),
        campaign_case_selections=tuple(
            DiagnosticCampaignCaseSelection(
                layer=item.layer,
                recipe_version_id=item.recipe_version_id,
                recipe_content_hash=recipe_by_id[
                    item.recipe_version_id
                ].content_hash,
                market_scenario_id=item.market_scenario_id,
                campaign_case_id=item.campaign_case_id,
                comparison_role=(
                    DiagnosticComparisonRole.CONTROL
                    if item.layer is DiagnosticCampaignLayer.BASELINE
                    else DiagnosticComparisonRole.COMPARE_TO_BASELINE
                ),
                baseline_campaign_case_id=(
                    None
                    if item.layer is DiagnosticCampaignLayer.BASELINE
                    else baseline_case_id
                ),
                execution_policy_values=item.execution_policy_values,
            )
            for item in inventory.market_scenarios
        ),
    )


def _wave2_performance_feature() -> DeterministicFakeDiagnosticTasksAdapter:
    seed = DeterministicFakeDiagnosticTasksAdapter()
    workspace = DiagnosticTasksContext.workspace()
    seed.snapshot(workspace)
    inventory = seed.snapshot(workspace).last_reliable_inventory
    seed.close()
    if inventory is None:
        raise RuntimeError("Diagnostic Tasks seed inventory is unavailable")
    baseline = inventory.market_scenarios[0]
    isolated = tuple(
        replace(
            baseline,
            market_scenario_id=type(baseline.market_scenario_id)(
                f"sha256:performance-isolated-scenario-{index:02d}"
            ),
            campaign_case_id=type(baseline.campaign_case_id)(
                f"performance-isolated-campaign-case-{index:02d}"
            ),
            layer=DiagnosticCampaignLayer.ISOLATED_SENSITIVITY,
            comparison_requirement="compare_to_baseline",
        )
        for index in range(1, 13)
    )
    compound = replace(
        baseline,
        market_scenario_id=type(baseline.market_scenario_id)(
            "sha256:performance-compound-scenario"
        ),
        campaign_case_id=type(baseline.campaign_case_id)(
            "performance-compound-campaign-case"
        ),
        layer=DiagnosticCampaignLayer.COMPOUND,
        comparison_requirement="compare_to_baseline",
    )
    return DeterministicFakeDiagnosticTasksAdapter(
        inventory=replace(
            inventory,
            market_scenarios=(baseline, *isolated, compound),
        )
    )


def _read_diagnostic_task(
    feature: DiagnosticTasksFeature,
    task_id: DiagnosticTaskId,
) -> DiagnosticTaskPresentation:
    context = DiagnosticTasksContext(task_id=task_id)
    feature.snapshot(context)
    state = feature.snapshot(context)
    if state.task is None:
        raise RuntimeError("Diagnostic Tasks performance task is unavailable")
    return state.task


def _identity_graph(
    task: DiagnosticTaskPresentation,
    command_ids: tuple[str, ...],
) -> tuple[str, ...]:
    identities = [
        *command_ids,
        task.task_id.value,
        *(handle.identity.value for handle in task.task_handles),
    ]
    handoff = task.handoff
    if handoff.campaign_id is not None:
        identities.append(handoff.campaign_id.value)
    for node in handoff.campaign_nodes:
        identities.append(node.campaign_node_id.value)
        for attempt in node.attempts:
            identities.append(attempt.attempt_id.value)
            for run in attempt.runs:
                identities.append(run.run_id.value)
                if run.reproduction_manifest_id is not None:
                    identities.append(run.reproduction_manifest_id.value)
    if handoff.evidence_package_id is not None:
        identities.append(handoff.evidence_package_id.value)
    if handoff.reproduction_manifest_id is not None:
        identities.append(handoff.reproduction_manifest_id.value)
    return tuple(dict.fromkeys(identities))


def _prepare_wave2_diagnostic_task_load(
    feature: DeterministicFakeDiagnosticTasksAdapter,
) -> tuple[dict[str, Any], tuple[str, ...], tuple[str, ...]]:
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    inventory = feature.snapshot(workspace).last_reliable_inventory
    if inventory is None:
        raise RuntimeError("Diagnostic Tasks performance inventory is unavailable")
    configuration = _diagnostic_configuration(inventory)
    accepted_command_ids = WAVE2_PERFORMANCE_COMMAND_IDS
    create = feature.create_diagnostic_task(
        CreateDiagnosticTask(
            command_id=DiagnosticCommandId(accepted_command_ids[0]),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "performance-create-diagnostic-task-key"
            ),
            configuration=configuration,
        )
    )
    if create.affected_task_id is None:
        raise RuntimeError(f"Diagnostic Task create failed: {create.message}")
    task_id = create.affected_task_id
    task = _read_diagnostic_task(feature, task_id)
    validate = feature.validate_configuration(
        ValidateDiagnosticTaskConfiguration(
            command_id=DiagnosticCommandId(accepted_command_ids[1]),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "performance-validate-diagnostic-task-key"
            ),
            task_id=task_id,
            expected_revision=task.revision,
        )
    )
    task = _read_diagnostic_task(feature, task_id)
    validation = task.validation
    if (
        validation.validation_id is None
        or validation.validation_revision is None
        or validation.validated_revision is None
        or validation.configuration_content_identity is None
    ):
        raise RuntimeError("Diagnostic Task validation did not become durable")
    approve = feature.approve_configuration(
        ApproveDiagnosticTaskConfiguration(
            command_id=DiagnosticCommandId(accepted_command_ids[2]),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "performance-approve-diagnostic-task-key"
            ),
            task_id=task_id,
            expected_revision=task.revision,
            validation_id=validation.validation_id,
            validation_revision=validation.validation_revision,
            validated_revision=validation.validated_revision,
            configuration_content_id=(
                validation.configuration_content_identity
            ),
            actor_id=DiagnosticActorId("performance-release-owner"),
        )
    )
    task = _read_diagnostic_task(feature, task_id)
    start = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId(accepted_command_ids[3]),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "performance-start-diagnostic-campaign-key"
            ),
            task_id=task_id,
            expected_revision=task.revision,
            approved_revision=task.revision,
        )
    )
    feature.advance_evidence_available(task_id)
    task = _read_diagnostic_task(feature, task_id)
    feature.snapshot(workspace)
    feature.snapshot(workspace)
    results = (create, validate, approve, start)
    result_command_ids = tuple(
        result.command_id.value for result in results
    )
    graph = _identity_graph(task, result_command_ids)
    qml_observation_graph = tuple(
        identity
        for identity in graph
        if identity not in result_command_ids
        and all(
            identity != node.campaign_node_id.value
            for node in task.handoff.campaign_nodes
        )
    )
    handles = tuple(
        result.task_handle
        for result in results
        if result.task_handle is not None
    )
    return (
        {
            "feature_interface": (
                f"DiagnosticTasksFeature/{feature.interface_version.render()}"
            ),
            "application_interface": (
                "StrategyDiagnosticsV1DiagnosticTasksApplication/"
                f"{DIAGNOSTIC_TASKS_APPLICATION_INTERFACE_VERSION.render()}"
            ),
            "adapter": type(feature).__name__,
            "accepted_command_ids": list(accepted_command_ids),
            "result_command_ids": list(result_command_ids),
            "accepted_command_observed": (
                result_command_ids == accepted_command_ids
                and all(result.accepted for result in results)
            ),
            "task_handle_observed": bool(handles)
            and all(
                handle.identity.value in graph
                for handle in handles
            ),
            "task_handle_ids": [
                handle.identity.value for handle in handles
            ],
            "handoff_observed": task.handoff.ready_for_run_monitoring,
            "terminal_observed": task.lifecycle.value == "completed",
            "executed_during_active_load": False,
            "source_events_before_command": 0,
            "source_events_after_command": 0,
            "observed_before_load": False,
            "observed_after_load": False,
            "task_lifecycle": task.lifecycle.value,
            "identity_graph": list(graph),
        },
        graph,
        qml_observation_graph,
    )


def _qml_observes_identity_graph(
    host: JourneyWorkspaceHost,
    app: QApplication,
    identity_graph: tuple[str, ...],
) -> bool:
    root = host.rootObject()
    if root is None or not root.setProperty("activeRoute", "diagnostic_tasks"):
        return False
    app.processEvents()
    app.processEvents()
    summary = root.findChild(QObject, "diagnosticTasksAccessibleSummary")
    if summary is None:
        return False
    accessible = QAccessible.queryAccessibleInterface(summary)
    if accessible is None:
        return False
    observed_text = " ".join(
        (
            accessible.text(QAccessible.Text.Name),
            accessible.text(QAccessible.Text.Description),
        )
    )
    return all(identity in observed_text for identity in identity_graph)


def _qml_observes_ready_inventory(
    host: JourneyWorkspaceHost,
    app: QApplication,
) -> bool:
    root = host.rootObject()
    adapter = host._diagnostic_tasks
    if (
        root is None
        or adapter is None
        or not root.setProperty("activeRoute", "diagnostic_tasks")
    ):
        return False
    app.processEvents()
    app.processEvents()
    return bool(
        adapter.presentationState == "ready"
        and root.findChild(
            QObject,
            "diagnosticTasksAccessibleSummary",
        )
        is not None
    )


def run_performance_lane(
    *,
    lane: str,
    duration_seconds: float,
    source_commit: str,
    smoke: bool,
    process_started_ns: int,
    integrated_v1_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one isolated renderer lane and return its retained report."""

    if not smoke and integrated_v1_evidence is None:
        raise RuntimeError(
            "A certifying performance lane requires real V1 preflight "
            "evidence"
        )
    existing_app = QApplication.instance()
    app = (
        QApplication([])
        if existing_app is None
        else cast(QApplication, existing_app)
    )
    queries = _PerformanceLoadProjectionReadModel()
    diagnostic_tasks = _wave2_performance_feature()
    wave2_diagnostic_tasks: dict[str, Any] = {
        "feature_interface": (
            f"DiagnosticTasksFeature/"
            f"{diagnostic_tasks.interface_version.render()}"
        ),
        "application_interface": (
            "StrategyDiagnosticsV1DiagnosticTasksApplication/"
            f"{DIAGNOSTIC_TASKS_APPLICATION_INTERFACE_VERSION.render()}"
        ),
        "adapter": type(diagnostic_tasks).__name__,
        "accepted_command_ids": list(WAVE2_PERFORMANCE_COMMAND_IDS),
        "result_command_ids": [],
        "accepted_command_observed": False,
        "task_handle_observed": False,
        "task_handle_ids": [],
        "handoff_observed": False,
        "terminal_observed": False,
        "executed_during_active_load": False,
        "source_events_before_command": 0,
        "source_events_after_command": 0,
        "observed_before_load": False,
        "observed_after_load": False,
        "task_lifecycle": "not_started",
        "identity_graph": [],
    }
    wave2_qml_observation_graph: tuple[str, ...] = ()
    recorder = _MetricRecorder(queries)
    bridge = EventBridge(
        flush_interval_ms=REFERENCE_FIXTURE.source_cadence_ms,
        max_batch_size=500,
        subscribe_backend=False,
    )
    run_feature: LiveRunMonitoringAdapter | None = None
    evidence_feature: LiveEvidenceAndFindingsAdapter | None = None
    dispose_batch_probe: Callable[[], None] | None = None
    performance_subscription: Any | None = None
    host: JourneyWorkspaceHost | None = None
    probe: _QtPerformanceProbe | None = None
    observed_fixture: Mapping[str, int] | None = None
    cleanup_errors: list[str] = []
    finished = [False]

    def quit_app() -> None:
        finished[0] = True
        app.quit()

    def run_wave2_active_load() -> None:
        nonlocal wave2_qml_observation_graph
        if probe is None or not probe.measurement_active:
            raise RuntimeError(
                "Wave 2 commands were not started inside the active load"
            )
        source_events_before = probe.source_events
        report, _identity_graph_value, qml_graph = (
            _prepare_wave2_diagnostic_task_load(diagnostic_tasks)
        )
        report["executed_during_active_load"] = probe.measurement_active
        report["source_events_before_command"] = source_events_before
        report["source_events_after_command"] = probe.source_events
        report["observed_before_load"] = wave2_diagnostic_tasks[
            "observed_before_load"
        ]
        wave2_diagnostic_tasks.clear()
        wave2_diagnostic_tasks.update(report)
        wave2_qml_observation_graph = qml_graph

    try:
        run_feature = LiveRunMonitoringAdapter(
            application_read_model=queries,
            event_bridge=bridge,
        )
        evidence_feature = LiveEvidenceAndFindingsAdapter(
            application_read_model=queries,
            event_bridge=bridge,
        )
        dispose_batch_probe = bridge.subscribe_batches(
            recorder.record_batch
        )
        evidence_context = _evidence_context()
        performance_subscription = evidence_feature.subscribe(
            evidence_context,
            recorder.record_feature_state,
        )
        host = JourneyWorkspaceHost(
            run_feature,
            context=_run_context(),
            diagnostic_tasks_feature=diagnostic_tasks,
            diagnostic_tasks_context=DiagnosticTasksContext.workspace(),
            evidence_feature=evidence_feature,
            evidence_context=evidence_context,
        )
        root = host.rootObject()
        if root is None:
            raise RuntimeError("Journey Workspace QML did not load")
        evidence_qt_adapter = host._evidence_and_findings
        if evidence_qt_adapter is None:
            raise RuntimeError(
                "Evidence & Findings Qt Adapter is unavailable"
            )
        diagnostic_qt_adapter = host._diagnostic_tasks
        if diagnostic_qt_adapter is None:
            raise RuntimeError("Diagnostic Tasks Qt Adapter is unavailable")
        wave2_diagnostic_tasks["observed_before_load"] = (
            _qml_observes_ready_inventory(host, app)
        )
        diagnostic_qt_adapter.campaignHandoffReady.disconnect(
            host._open_run_monitoring_handoff
        )
        diagnostic_qt_adapter.evidenceHandoffReady.disconnect(
            host._open_evidence_and_findings_handoff
        )
        host._run_monitoring.select_context(_run_context())
        evidence_qt_adapter.select_context(evidence_context)
        root.setProperty("activeRoute", "evidence_and_findings")
        evidence_qt_adapter.setActiveTab("context")

        bridge.start()
        host.resize(
            REFERENCE_MEASUREMENT_PROTOCOL.window_width,
            REFERENCE_MEASUREMENT_PROTOCOL.window_height,
        )
        host.move(-10_000, -10_000)
        host.setAttribute(
            Qt.WidgetAttribute.WA_DontShowOnScreen,
            True,
        )
        host.show()
        app.processEvents()
        probe = _QtPerformanceProbe(
            app=app,
            host=host,
            recorder=recorder,
            queries=queries,
            bridge=bridge,
            duration_seconds=duration_seconds,
            process_started_ns=process_started_ns,
            on_measurement_active=run_wave2_active_load,
            on_finished=quit_app,
        )
        host.quickWindow().beforeSynchronizing.connect(
            probe.before_synchronize,
            Qt.ConnectionType.DirectConnection,
        )
        host.quickWindow().afterRendering.connect(
            probe.after_render,
            Qt.ConnectionType.DirectConnection,
        )
        host.update()
        host.quickWindow().update()
        QTimer.singleShot(
            max(5_000, ceil((duration_seconds + 5.0) * 1_000)),
            app.quit,
        )
        app.exec()
        if not finished[0]:
            probe.errors.append("Performance lane watchdog expired")
        observed_fixture = probe.observed_fixture
        qml_observed_after_load = (
            _qml_observes_identity_graph(
                host,
                app,
                wave2_qml_observation_graph,
            )
        )
        wave2_diagnostic_tasks["observed_after_load"] = (
            qml_observed_after_load
        )
        wave2_diagnostic_tasks["task_handle_observed"] = bool(
            wave2_diagnostic_tasks.get("task_handle_observed")
            and qml_observed_after_load
        )
    finally:
        cleanup_actions: tuple[
            tuple[str, Callable[[], None]],
            ...,
        ] = tuple(
            item
            for item in (
                (
                    "performance subscription",
                    (
                        performance_subscription.dispose
                        if performance_subscription is not None
                        else None
                    ),
                ),
                (
                    "Journey Workspace adapter",
                    host.close_adapter if host is not None else None,
                ),
                (
                    "Journey Workspace host",
                    host.close if host is not None else None,
                ),
                (
                    "Diagnostic Tasks Feature",
                    diagnostic_tasks.close,
                ),
                (
                    "Run Monitoring Feature",
                    (
                        run_feature.close
                        if run_feature is not None
                        else None
                    ),
                ),
                (
                    "Evidence and Findings Feature",
                    (
                        evidence_feature.close
                        if evidence_feature is not None
                        else None
                    ),
                ),
                (
                    "EventBridge batch probe",
                    dispose_batch_probe,
                ),
                (
                    "EventBridge",
                    bridge.stop,
                ),
                ("Qt event drain", app.processEvents),
            )
            if item[1] is not None
        )
        for label, action in cleanup_actions:
            try:
                action()
            except BaseException as error:
                cleanup_errors.append(
                    f"{label} cleanup failed: {type(error).__name__}"
                )

    if probe is None or observed_fixture is None:
        raise RuntimeError("Performance lane did not produce a report")
    probe.errors.extend(cleanup_errors)

    report = _build_report(
        lane=lane,
        source_commit=source_commit,
        smoke=smoke,
        probe=probe,
        recorder=recorder,
        observed_fixture=observed_fixture,
        real_v1_evidence=integrated_v1_evidence,
        wave2_diagnostic_tasks=wave2_diagnostic_tasks,
    )
    return report


def _build_report(
    *,
    lane: str,
    source_commit: str,
    smoke: bool,
    probe: _QtPerformanceProbe,
    recorder: _MetricRecorder,
    observed_fixture: Mapping[str, int],
    real_v1_evidence: Mapping[str, Any] | None,
    wave2_diagnostic_tasks: Mapping[str, Any],
) -> dict[str, Any]:
    event_metric = build_performance_metric(recorder.event_to_visible_ms)
    input_metric = build_performance_metric(recorder.input_response_ms)
    source_intervals_ms = [
        (current - previous) / 1_000_000
        for previous, current in zip(
            recorder.source_event_ns,
            recorder.source_event_ns[1:],
        )
    ]
    max_stall_ms = max(recorder.main_thread_gaps_ms, default=0.0)
    peak_memory_mib = max(recorder.memory_mib, default=0.0)
    revisions = list(recorder.accepted_revisions)
    monotonic = bool(revisions) and all(
        current > previous for previous, current in zip(revisions, revisions[1:])
    )
    expected_api = "Direct3D11" if lane == "hardware" else "Software"
    runtime_errors = list(dict.fromkeys(probe.errors))
    if probe.graphics_api != expected_api:
        runtime_errors.append(
            f"Renderer used {probe.graphics_api!r}; expected {expected_api!r}"
        )
    terminal_visible_ms = recorder.terminal_visible_ms
    report: dict[str, Any] = {
        "schema_version": 2,
        "status": "smoke" if smoke else "passed",
        "lane": lane,
        "graphics_api": probe.graphics_api,
        "source_commit": source_commit,
        "toolchain_lock_digest": _file_digest(TOOLCHAIN_LOCK_PATH),
        "fixture": asdict(REFERENCE_FIXTURE),
        "fixture_digest": reference_fixture_digest(),
        "measurement": asdict(REFERENCE_MEASUREMENT_PROTOCOL),
        "observed_fixture": dict(observed_fixture),
        "sampling_policy": "uniform_endpoints_v1",
        "production_path": list(WAVE2_PERFORMANCE_PRODUCTION_PATH),
        "integrated_v1_probe": (
            None
            if real_v1_evidence is None
            else dict(real_v1_evidence)
        ),
        "wave2_diagnostic_tasks": dict(wave2_diagnostic_tasks),
        "start_marker": SOURCE_MARKER,
        "end_marker": END_MARKER,
        "started_at": probe.started_at.isoformat(),
        "ended_at": probe.ended_at.isoformat(),
        "duration_seconds": round(probe.duration_seconds, 6),
        "machine": _machine_metadata(),
        "build": asdict(running_toolchain()),
        "metrics": {
            "event_to_visible": event_metric,
            "input_response": input_metric,
            "source_cadence": build_performance_metric(source_intervals_ms),
            "usable_state_ms": round(probe.usable_state_ms, 6),
            "max_main_thread_stall_ms": round(max_stall_ms, 6),
            "main_thread_stalls_over_budget": sum(
                gap > PERFORMANCE_THRESHOLDS.main_thread_stall_ms
                for gap in recorder.main_thread_gaps_ms
            ),
            "peak_memory_mib": round(peak_memory_mib, 6),
            "source_events": probe.source_events,
            "visible_revisions": len(revisions),
            "coalesced_source_events": max(
                0,
                probe.source_events - len(recorder.event_to_visible_ms),
            ),
        },
        "accepted_revisions": revisions,
        "revisions_strictly_monotonic": monotonic,
        "terminal": {
            "phase": "completed",
            "source_revision": recorder.terminal_source_revision,
            "visible_revision": recorder.terminal_visible_revision,
            "visible_ms": (
                None if terminal_visible_ms is None else round(terminal_visible_ms, 6)
            ),
            "observed": terminal_visible_ms is not None,
        },
        "safety": {
            "manual_trading_action_count": probe.manual_action_count,
            "read_only_context_visible": (probe.read_only_context_visible),
        },
        "errors": runtime_errors,
    }
    if not smoke:
        local_failures = _runtime_threshold_failures(report)
        if local_failures:
            report["status"] = "failed"
            report["errors"] = list(dict.fromkeys([*runtime_errors, *local_failures]))
    return report


def _runtime_threshold_failures(
    report: Mapping[str, Any],
) -> tuple[str, ...]:
    return validate_performance_lane(
        report,
        expected_lane=cast(str, report["lane"]),
        expected_source_commit=cast(str, report["source_commit"]),
        expected_toolchain_digest=cast(
            str,
            report["toolchain_lock_digest"],
        ),
    )


def _file_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _machine_metadata() -> dict[str, Any]:
    return {
        "operating_system": "Windows 11",
        "operating_system_version": platform.version(),
        "architecture": platform.machine(),
        "processor": platform.processor() or "unknown",
        "logical_cpu_count": os.cpu_count() or 1,
        "total_memory_mib": round(
            _total_physical_memory_bytes() / (1024 * 1024),
            3,
        ),
    }


def _process_working_set_bytes() -> int:
    counters = _ProcessMemoryCountersEx()
    counters.cb = ctypes.sizeof(counters)
    process = _KERNEL32.GetCurrentProcess()
    success = _PSAPI.GetProcessMemoryInfo(
        process,
        ctypes.byref(counters),
        counters.cb,
    )
    if not success:
        raise OSError("GetProcessMemoryInfo failed")
    return int(counters.WorkingSetSize)


def _total_physical_memory_bytes() -> int:
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    if not _KERNEL32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("GlobalMemoryStatusEx failed")
    return int(status.ullTotalPhys)


def _manual_action_count(root: QObject) -> int:
    count = 0
    for item in (root, *root.findChildren(QObject)):
        object_name = str(item.objectName() or "")
        if audit_qml_text("performance-runtime-object-tree", object_name):
            count += 1
    return count


def _run_context() -> RunMonitoringContext:
    return RunMonitoringContext.for_run(
        RunMonitoringSelection(
            campaign_id=FormalDiagnosticCampaignId(CAMPAIGN_ID),
            run_id=StrategyRunId(RUN_ID),
        )
    )


def _evidence_context() -> EvidenceAndFindingsContext:
    return EvidenceAndFindingsContext.for_selection(
        EvidenceAndFindingsSelection(
            campaign_id=FormalDiagnosticCampaignId(CAMPAIGN_ID),
            run_id=StrategyRunId(RUN_ID),
            strategy_id=StrategyUnderTestId(STRATEGY_ID),
            market_scenario_id=MarketScenarioId(SCENARIO_ID),
            approved_recipe_id=ApprovedScenarioRecipeId(RECIPE_ID),
            reproduction_manifest_id=ReproductionManifestId(MANIFEST_ID),
        )
    )


__all__ = ["run_performance_lane"]
