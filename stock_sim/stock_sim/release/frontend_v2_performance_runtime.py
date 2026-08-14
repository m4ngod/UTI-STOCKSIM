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
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from math import ceil, sin
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock, local
from time import monotonic, perf_counter_ns, sleep
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
from app.journey_recovery import (
    JourneyWorkspaceBookmark,
    JourneyWorkspaceRoute,
    encode_journey_workspace_bookmark,
    restore_journey_workspace_bookmark,
)
from app.state.settings_store import SettingsStore
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
    CompareStrategies,
    ComposeFormalScenarioSetCommand,
    CreateDiagnosticTask,
    DiagnosticActorId,
    DiagnosticCampaignCaseSelection,
    DiagnosticCampaignLayer,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    DiagnosticComparisonRole,
    DiagnosticEvidencePackageId,
    DiagnosticsApplicationIdentity,
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
    ScenarioLabContext,
    ScenarioLabCommandContentIdentity,
    ScenarioLabCommandDisposition,
    ScenarioLabCommandId,
    ScenarioLabCommandMetadata,
    ScenarioLabFeature,
    ScenarioLabIdempotencyIdentity,
    ScenarioSetId,
    SimulationTime,
    SourceRevisionToken,
    StartFormalDiagnosticCampaign,
    StrategyRunId,
    StrategyLibraryContext,
    StrategyLibraryFeature,
    StrategyComparisonDisposition,
    StrategySelectionDisposition,
    SelectFormalStrategySet,
    StrategyUnderTestId,
    TerminalOutcome,
    V1JourneySelector,
    ValidateDiagnosticTaskConfiguration,
    WallTime,
    canonical_scenario_lab_command_content_identity,
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
    WAVE3_PERFORMANCE_PRODUCTION_PATH,
    build_performance_metric,
    reference_fixture_digest,
    validate_performance_lane,
)
from .no_manual_trading_gate import audit_qml_text

UTC = timezone.utc
SOURCE_MARKER = "frontend-v2-performance-start"
END_MARKER = "frontend-v2-performance-end"


@dataclass(frozen=True, slots=True)
class _PerformanceIdentity:
    campaign_id: str
    run_id: str
    strategy_id: str
    scenario_id: str
    recipe_id: str
    evidence_package_id: str
    manifest_id: str


@dataclass(slots=True)
class _PerformanceStartupMarkers:
    runtime_started_ns: int
    qapplication_ready_ns: int | None = None
    window_create_started_ns: int | None = None
    window_created_ns: int | None = None
    window_bindings_ready_ns: int | None = None
    initial_route_ready_ns: int | None = None
    bridge_started_ns: int | None = None
    fixture_projection_ready_ns: int | None = None
    window_show_started_ns: int | None = None
    window_show_returned_ns: int | None = None
    window_shown_ns: int | None = None

    def phase_durations_ms(
        self,
        *,
        usable_visible_ns: int,
    ) -> dict[str, float]:
        fixed_order_markers = (
            ("runtime_started", self.runtime_started_ns),
            ("qapplication_ready", self.qapplication_ready_ns),
            ("window_create_started", self.window_create_started_ns),
            ("window_created", self.window_created_ns),
            ("window_bindings_ready", self.window_bindings_ready_ns),
            ("initial_route_ready", self.initial_route_ready_ns),
            ("bridge_started", self.bridge_started_ns),
            ("window_show_started", self.window_show_started_ns),
            ("window_show_returned", self.window_show_returned_ns),
            ("window_shown", self.window_shown_ns),
            (
                "fixture_projection_ready",
                self.fixture_projection_ready_ns,
            ),
        )
        all_markers = (
            *fixed_order_markers,
            ("usable_visible", usable_visible_ns),
        )
        missing = [
            name
            for name, value in all_markers
            if value is None or value <= 0
        ]
        if missing:
            raise RuntimeError(
                "Performance startup markers are incomplete: "
                + ", ".join(missing)
            )
        fixed_order_values = tuple(
            cast(int, value) for _, value in fixed_order_markers
        )
        if any(
            current < previous
            for previous, current in zip(
                fixed_order_values,
                fixed_order_values[1:],
            )
        ):
            raise RuntimeError(
                "Performance startup markers are out of order"
            )

        (
            runtime_started_ns,
            qapplication_ready_ns,
            window_create_started_ns,
            window_created_ns,
            window_bindings_ready_ns,
            initial_route_ready_ns,
            bridge_started_ns,
            window_show_started_ns,
            window_show_returned_ns,
            window_shown_ns,
            fixture_projection_ready_ns,
        ) = fixed_order_values
        if usable_visible_ns < max(
            fixture_projection_ready_ns,
            window_show_started_ns,
        ):
            raise RuntimeError(
                "Performance usable frame marker is out of order"
            )

        def elapsed_ms(start_ns: int, end_ns: int) -> float:
            return round((end_ns - start_ns) / 1_000_000, 6)

        return {
            "total_to_usable_visible": elapsed_ms(
                runtime_started_ns,
                usable_visible_ns,
            ),
            "qapplication_creation": elapsed_ms(
                runtime_started_ns,
                qapplication_ready_ns,
            ),
            "application_setup_before_window": elapsed_ms(
                qapplication_ready_ns,
                window_create_started_ns,
            ),
            "window_create": elapsed_ms(
                window_create_started_ns,
                window_created_ns,
            ),
            "window_created_to_shown": elapsed_ms(
                window_created_ns,
                window_shown_ns,
            ),
            "window_created_to_bindings_ready": elapsed_ms(
                window_created_ns,
                window_bindings_ready_ns,
            ),
            "bindings_to_initial_route_ready": elapsed_ms(
                window_bindings_ready_ns,
                initial_route_ready_ns,
            ),
            "initial_route_to_bridge_started": elapsed_ms(
                initial_route_ready_ns,
                bridge_started_ns,
            ),
            "bridge_started_to_projection_ready": elapsed_ms(
                bridge_started_ns,
                fixture_projection_ready_ns,
            ),
            "bridge_started_to_show_started": elapsed_ms(
                bridge_started_ns,
                window_show_started_ns,
            ),
            "window_show_call": elapsed_ms(
                window_show_started_ns,
                window_show_returned_ns,
            ),
            "show_started_to_usable_visible": elapsed_ms(
                window_show_started_ns,
                usable_visible_ns,
            ),
            "show_return_to_events_processed": elapsed_ms(
                window_show_returned_ns,
                window_shown_ns,
            ),
            "shown_to_projection_ready": elapsed_ms(
                window_shown_ns,
                fixture_projection_ready_ns,
            ),
            "projection_ready_to_usable_visible": elapsed_ms(
                fixture_projection_ready_ns,
                usable_visible_ns,
            ),
        }


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


class _PackagedPerformanceFixtureReadModel:
    """Fixed-load projection bound to one real persisted Diagnostics app."""

    def __init__(
        self,
        *,
        identity: _PerformanceIdentity,
        authoritative: LiveStrategyDiagnosticsV1ApplicationAdapter,
    ) -> None:
        self.identity = identity
        self._authoritative = authoritative
        selector = V1JourneySelector(
            campaign_id=FormalDiagnosticCampaignId(identity.campaign_id),
            run_id=StrategyRunId(identity.run_id),
            evidence_package_id=DiagnosticEvidencePackageId(
                identity.evidence_package_id
            ),
            manifest_id=ReproductionManifestId(identity.manifest_id),
        )
        authoritative_journey = authoritative.resolve_journey(selector)
        if (
            authoritative_journey.availability
            is not ApplicationReadAvailability.READY
            or authoritative_journey.value is None
            or authoritative_journey.error is not None
        ):
            raise RuntimeError(
                "Persisted performance Journey is not authoritative"
            )
        self._authoritative_journey = authoritative_journey.value
        for label, result in (
            ("Run", authoritative.read_run(self._authoritative_journey)),
            (
                "Evidence",
                authoritative.read_evidence(self._authoritative_journey),
            ),
        ):
            if (
                result.availability is not ApplicationReadAvailability.READY
                or result.value is None
                or result.error is not None
            ):
                raise RuntimeError(
                    f"Persisted performance {label} is not authoritative"
                )
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
    def application_identity(self) -> DiagnosticsApplicationIdentity:
        """Prove that this projection belongs to the authoritative app."""

        return self._authoritative.application_identity

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
            selector.campaign_id.value != self.identity.campaign_id
            or selector.run_id.value != self.identity.run_id
            or (
                selector.manifest_id is not None
                and selector.manifest_id.value != self.identity.manifest_id
            )
        ):
            return self._read_failure(
                code=ApplicationReadErrorCode.SELECTION_NOT_FOUND,
                message="The performance certification journey was not found.",
                retryable=False,
            )
        journey = self._authoritative_journey
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
        if journey != self._authoritative_journey:
            return self._read_failure(
                code=ApplicationReadErrorCode.IDENTITY_MISMATCH,
                message="The performance Run journey is not authoritative.",
                retryable=False,
            )
        selection = journey.run_context.selection
        if (
            selection is None
            or selection.run_id is None
            or selection.campaign_id.value != self.identity.campaign_id
            or selection.run_id.value != self.identity.run_id
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
            strategy_id=StrategyUnderTestId(self.identity.strategy_id),
            market_scenario_id=MarketScenarioId(self.identity.scenario_id),
            scenario_set_id=ScenarioSetId("SET-PERF-001"),
            reproduction_manifest_id=ReproductionManifestId(
                self.identity.manifest_id
            ),
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

        if journey != self._authoritative_journey:
            return self._read_failure(
                code=ApplicationReadErrorCode.IDENTITY_MISMATCH,
                message=(
                    "The performance Diagnostic Evidence journey is not "
                    "authoritative."
                ),
                retryable=False,
            )
        selection = journey.evidence_context.selection
        if (
            selection is None
            or selection.campaign_id.value != self.identity.campaign_id
            or selection.run_id.value != self.identity.run_id
        ):
            return self._read_failure(
                code=ApplicationReadErrorCode.IDENTITY_MISMATCH,
                message=(
                    "The performance Diagnostic Evidence identity does not "
                    "match its journey."
                ),
                retryable=False,
            )
        record = self.get_evidence_and_findings_snapshot(self.identity.run_id)
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

    def _run_source_token(
        self,
        revision: int,
        status: str,
        updated_at: datetime,
    ) -> SourceRevisionToken:
        payload = (
            f"{self.identity.campaign_id}|{self.identity.run_id}|"
            f"{revision}|{status}|{updated_at.isoformat()}"
        )
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
        if run_id != self.identity.run_id:
            return None
        with self._lock:
            revision = self._revision
            status = self._status
            updated_at = self._updated_at
            candidates = self._candidate_rows
        self._thread_reads.evidence_revision = revision
        return {
            "run_id": self.identity.run_id,
            "evidence_package_id": self.identity.evidence_package_id,
            "revision": revision,
            "updated_at": updated_at.isoformat(),
            "status": status,
            "content_digest": self._content_digest,
            "selection": {
                "campaign_id": self.identity.campaign_id,
                "run_id": self.identity.run_id,
                "strategy_id": self.identity.strategy_id,
                "market_scenario_id": self.identity.scenario_id,
                "approved_recipe_id": self.identity.recipe_id,
                "reproduction_manifest_id": self.identity.manifest_id,
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
                "source_run_ids": [self.identity.run_id],
                "runner_version": "frontend-v2-performance/1",
                "build_version": "uti-stocksim/wave1",
                "dependencies": [
                    {
                        "name": "reproduction-manifest",
                        "version": self.identity.manifest_id,
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

    @property
    def fixture(self) -> Any:
        return self._fixture

    @property
    def application_adapter(
        self,
    ) -> LiveStrategyDiagnosticsV1ApplicationAdapter:
        return self._adapter

    @property
    def performance_identity(self) -> _PerformanceIdentity:
        return _PerformanceIdentity(
            campaign_id=self._identity["campaign_identity"],
            run_id=self._identity["run_identity"],
            strategy_id=self._identity["strategy_identity"],
            scenario_id=self._identity["case_identity"],
            recipe_id=self._identity["approved_recipe_identity"],
            evidence_package_id=self._identity["evidence_package_identity"],
            manifest_id=self._identity["reproduction_manifest_identity"],
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

    probe: _RealV1PerformanceProbe | None = prepare_real_v1_performance_probe(
        fixture_archive_path=fixture_archive_path,
        expected_source_commit=expected_source_commit,
    )
    try:
        assert probe is not None
        probe.run_preflight(sample_count=2)
    finally:
        assert probe is not None
        probe.close()
    assert probe is not None
    evidence = probe.evidence()
    probe = None
    gc.collect()
    _trim_process_working_set()
    return evidence


class _MetricRecorder:
    def __init__(
        self,
        queries: _PackagedPerformanceFixtureReadModel,
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


def _scene_graph_revision_ready_for_composition(renderer: QObject) -> int:
    """Return only an exact revision carried by a complete chart geometry."""

    accepted_revision = int(renderer.property("acceptedRevision") or 0)
    frame_sequence = int(renderer.property("frameSequence") or 0)
    sample_point_count = int(renderer.property("samplePointCount") or 0)
    series_point_count = int(renderer.property("seriesPointCount") or 0)
    if (
        accepted_revision < 1
        or frame_sequence < 1
        or sample_point_count < 1
        or series_point_count != sample_point_count
    ):
        return 0
    return accepted_revision


class _QtPerformanceProbe(QObject):
    renderedFrameObserved = Signal(int, object)

    def __init__(
        self,
        *,
        app: QApplication,
        host: JourneyWorkspaceHost,
        recorder: _MetricRecorder,
        queries: _PackagedPerformanceFixtureReadModel,
        bridge: EventBridge,
        duration_seconds: float,
        process_started_ns: int,
        on_usable: Callable[[], None],
        on_measurement_active: Callable[[], None],
        on_finished: Callable[[], None],
    ) -> None:
        super().__init__(host)
        self._app = app
        self._host = host
        self._root: Any = None
        self._adapter: Any = None
        self._renderer: Any = None
        self._series_shape: Any = None
        self._candidate_repeater: Any = None
        self._context_panel: Any = None
        self._tab_findings: Any = None
        self._tab_assumptions: Any = None
        self._bind_qml_items()
        self._recorder = recorder
        self._queries = queries
        self._bridge = bridge
        self._duration_seconds = duration_seconds
        self._process_started_ns = process_started_ns
        self._on_usable = on_usable
        self._on_measurement_active = on_measurement_active
        self._on_finished = on_finished
        self._measurement_started_ns: int | None = None
        self._measurement_ended_ns: int | None = None
        self._started_at: datetime | None = None
        self._ended_at: datetime | None = None
        self._usable_state_ms: float | None = None
        self._usable_visible_ns: int | None = None
        self._pre_measurement_setup_started_ns: int | None = None
        self._pre_measurement_setup_ended_ns: int | None = None
        self._render_signals_connected = False
        self._graphics_api = "Unknown"
        self._last_stall_tick_ns: int | None = None
        self._source_events = 0
        self._pending_input: tuple[QQuickItem, str, int] | None = None
        self._terminal_sent_ns: int | None = None
        self._finished = False
        self._final_observed_fixture: dict[str, int] | None = None
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
    def usable_visible_ns(self) -> int:
        return int(self._usable_visible_ns or 0)

    @property
    def observed_fixture(self) -> dict[str, int]:
        if self._final_observed_fixture is not None:
            return dict(self._final_observed_fixture)
        return self._current_observed_fixture()

    def _current_observed_fixture(self) -> dict[str, int]:
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
        self._synchronized_revision = _scene_graph_revision_ready_for_composition(
            self._renderer
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
        if (
            self._usable_state_ms is None
            and revision > 0
            and self._fixture_is_usable()
        ):
            self._usable_state_ms = (visible_ns - self._process_started_ns) / 1_000_000
            self._usable_visible_ns = visible_ns
            self.read_only_context_visible = bool(
                self._context_panel.property("visible")
                and "read-only" in self._adapter.readOnlyContextText.lower()
            )
            self._adapter.setActiveTab("findings")
            self._prepare_after_usable()
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

    def _prepare_after_usable(self) -> None:
        """Complete certification setup after the first usable visible frame."""

        self._pre_measurement_setup_started_ns = perf_counter_ns()
        self.disconnect_render_signals()
        try:
            self._on_usable()
            self._bind_qml_items()
            if not self._fixture_is_usable():
                raise RuntimeError(
                    "Performance fixture was not usable after production setup"
                )
            self.connect_render_signals()
        except BaseException as error:
            self.errors.append(
                "Pre-measurement production setup failed: "
                f"{type(error).__name__}"
            )
            self._finish()
            return
        self._pre_measurement_setup_ended_ns = perf_counter_ns()
        QTimer.singleShot(0, self._start_measurement)

    def connect_render_signals(self) -> None:
        if self._render_signals_connected:
            return
        render_window = self._host.quickWindow()
        render_window.beforeSynchronizing.connect(
            self.before_synchronize,
            Qt.ConnectionType.DirectConnection,
        )
        render_window.afterRendering.connect(
            self.after_render,
            Qt.ConnectionType.DirectConnection,
        )
        self._render_signals_connected = True

    def disconnect_render_signals(self) -> None:
        if not self._render_signals_connected:
            return
        render_window = self._host.quickWindow()
        render_window.beforeSynchronizing.disconnect(self.before_synchronize)
        render_window.afterRendering.disconnect(self.after_render)
        self._render_signals_connected = False

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
                "run_id": self._queries.identity.run_id,
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
                "run_id": self._queries.identity.run_id,
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
        try:
            self._final_observed_fixture = (
                self._current_observed_fixture()
            )
        except BaseException as error:
            self._final_observed_fixture = {}
            self.errors.append(
                "Final performance fixture capture failed: "
                f"{type(error).__name__}"
            )
        finally:
            for timer in (
                self._terminal_timeout,
                self._watchdog,
                self._source_timer,
                self._stall_timer,
                self._memory_timer,
                self._input_timer,
            ):
                try:
                    timer.stop()
                except BaseException as error:
                    self.errors.append(
                        "Performance timer shutdown failed: "
                        f"{type(error).__name__}"
                    )
            try:
                self._sample_memory()
            except BaseException as error:
                self.errors.append(
                    "Final performance memory sample failed: "
                    f"{type(error).__name__}"
                )
            try:
                for error in self._host.errors():
                    self.errors.append(error.toString())
            except BaseException as error:
                self.errors.append(
                    "Final performance render error capture failed: "
                    f"{type(error).__name__}"
                )
            self._on_finished()

    def _bind_qml_items(self) -> None:
        """Bind the current Evidence route objects after any route remount."""

        root = self._host.rootObject()
        adapter = self._host._evidence_and_findings
        if root is None or adapter is None:
            raise RuntimeError("Evidence & Findings QML Adapter is unavailable")
        self._root = root
        self._adapter = adapter
        self._renderer = self._required_item("productionEvidenceChart")
        self._series_shape = self._required_object(
            "evidenceChartSeriesShape"
        )
        self._candidate_repeater = self._required_object(
            "evidenceCandidateRepeater"
        )
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


def _wait_for_diagnostic_task_terminal(
    feature: DiagnosticTasksFeature,
    task_id: DiagnosticTaskId,
    app: QApplication,
    *,
    timeout_seconds: float,
) -> DiagnosticTaskPresentation:
    context = DiagnosticTasksContext(task_id=task_id)
    latest = [feature.snapshot(context)]
    subscription = feature.subscribe(
        context,
        lambda state: latest.__setitem__(0, state),
    )
    try:
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            app.processEvents()
            state = latest[0]
            task = state.task
            if task is not None and task.lifecycle.value in {
                "completed",
                "failed",
            }:
                return task
            sleep(0.05)
    finally:
        subscription.dispose()
    raise RuntimeError(
        "Timed out waiting for real Diagnostic Task terminal state before "
        "renderer clock"
    )


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
    feature: DiagnosticTasksFeature,
) -> tuple[
    dict[str, Any],
    tuple[str, ...],
    tuple[str, ...],
    DiagnosticTaskId,
]:
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
            "task_id": task_id.value,
            "identity_graph": list(graph),
        },
        graph,
        qml_observation_graph,
        task_id,
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
    *,
    process_events: bool = True,
) -> bool:
    root = host.rootObject()
    adapter = host._diagnostic_tasks
    if root is None or adapter is None:
        return False
    if process_events:
        app.processEvents()
        app.processEvents()
    route = root.findChild(
        QObject,
        "diagnosticTasksRouteNavigation",
    )
    if route is None:
        return False
    accessible = QAccessible.queryAccessibleInterface(route)
    if accessible is None:
        return False
    observed_text = " ".join(
        (
            accessible.text(QAccessible.Text.Name),
            accessible.text(QAccessible.Text.Description),
        )
    ).lower()
    return bool(
        adapter.presentationState == "ready"
        and "inventory ready" in observed_text
    )


def _activate_setup_route(
    host: JourneyWorkspaceHost,
    app: QApplication,
    *,
    route: str,
    navigation_name: str,
    focus_property: str,
    status_name: str,
) -> tuple[bool, str]:
    root = host.rootObject()
    if root is None:
        raise RuntimeError("Journey Workspace QML did not load")
    navigation = root.findChild(QObject, navigation_name)
    if navigation is None:
        raise RuntimeError(f"Missing route navigation {navigation_name}")
    navigation.forceActiveFocus()
    for event_type in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QCoreApplication.sendEvent(
            navigation,
            QKeyEvent(
                event_type,
                Qt.Key.Key_Return,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
    for _ in range(4):
        app.processEvents()
    if root.property("activeRoute") != route:
        raise RuntimeError(f"Could not activate setup route {route}")
    focus_item = root.property(focus_property)
    status = root.findChild(QObject, status_name)
    if focus_item is None or status is None:
        raise RuntimeError(f"Setup route {route} is missing T08 semantics")
    accessible = QAccessible.queryAccessibleInterface(status)
    if accessible is None or not accessible.isValid():
        raise RuntimeError(f"Setup route {route} status is inaccessible")
    return bool(
        focus_item.property("activeFocus")
        and focus_item.property("focusVisible")
        and focus_item.property("visible")
    ), accessible.role().name


def _observe_wave3_setup_features(
    host: JourneyWorkspaceHost,
    app: QApplication,
) -> dict[str, Any]:
    strategy_adapter = host._strategy_library
    scenario_adapter = host._scenario_lab
    if strategy_adapter is None or scenario_adapter is None:
        raise RuntimeError("Wave 3 setup Feature Qt Adapters are unavailable")
    strategy_focus, strategy_role = _activate_setup_route(
        host,
        app,
        route="strategy_library",
        navigation_name="strategyLibraryRouteNavigation",
        focus_property="strategyLibraryInitialFocusItem",
        status_name="strategyLibraryAccessibleStatus",
    )
    scenario_focus, scenario_role = _activate_setup_route(
        host,
        app,
        route="scenario_lab",
        navigation_name="scenarioLabRouteNavigation",
        focus_property="scenarioLabInitialFocusItem",
        status_name="scenarioLabAccessibleStatus",
    )
    return {
        "presentation_states": {
            "strategy_library": strategy_adapter.presentationState,
            "scenario_lab": scenario_adapter.presentationState,
        },
        "freshness": {
            "strategy_library": strategy_adapter.freshness,
            "scenario_lab": scenario_adapter.freshness,
        },
        "qml_status_roles": {
            "strategy_library": strategy_role,
            "scenario_lab": scenario_role,
        },
        "initial_focus_observed": {
            "strategy_library": strategy_focus,
            "scenario_lab": scenario_focus,
        },
        "observed_before_load": True,
    }


def _prepare_wave3_setup_feature_load(
    strategy_feature: StrategyLibraryFeature,
    scenario_feature: ScenarioLabFeature,
) -> dict[str, Any]:
    """Run the fixed setup workload only through public Feature commands."""

    strategy_context = StrategyLibraryContext()
    strategy_before = strategy_feature.snapshot(strategy_context)
    strategy_inventory = strategy_before.last_reliable_inventory
    if (
        strategy_inventory is None
        or strategy_before.source_revision is None
    ):
        raise RuntimeError("Strategy Library inventory is unavailable")
    formal_entries = tuple(
        item
        for item in strategy_inventory.entries
        if item.required_for_v1_formal_campaign
    )
    if not formal_entries or any(
        item.guardrail_profile is None for item in formal_entries
    ):
        raise RuntimeError("Formal Strategy set is unavailable")
    comparison = strategy_feature.compare_strategies(
        CompareStrategies(
            strategy_ids=tuple(item.strategy_id for item in formal_entries),
            expected_source_revision=strategy_before.source_revision,
            expected_source_generation=strategy_before.source.generation,
        )
    )
    if comparison.disposition is not StrategyComparisonDisposition.AVAILABLE:
        raise RuntimeError("Formal Strategy comparison was not accepted")
    selection = strategy_feature.select_formal_strategy_set(
        SelectFormalStrategySet(
            strategy_ids=tuple(item.strategy_id for item in formal_entries),
            guardrail_profile_ids=tuple(
                item.guardrail_profile.profile_id
                for item in formal_entries
                if item.guardrail_profile is not None
            ),
            expected_source_revision=strategy_before.source_revision,
            expected_source_generation=strategy_before.source.generation,
            originating_view_revision=strategy_before.revision,
        )
    )
    if selection.disposition is not StrategySelectionDisposition.SELECTED:
        raise RuntimeError("Formal Strategy selection was not accepted")
    strategy_after = strategy_feature.snapshot(strategy_context)

    scenario_context = ScenarioLabContext()
    scenario_before = scenario_feature.snapshot(scenario_context)
    scenario_inventory = scenario_before.last_reliable_inventory
    if scenario_inventory is None or scenario_before.source_revision is None:
        raise RuntimeError("Scenario Lab inventory is unavailable")
    baseline = next(
        (
            item
            for item in scenario_inventory.market_scenarios
            if item.layer.value == "baseline"
        ),
        None,
    )
    if baseline is None:
        raise RuntimeError("Scenario Lab baseline is unavailable")
    metadata = ScenarioLabCommandMetadata(
        command_id=ScenarioLabCommandId(
            "performance-compose-formal-scenario-set"
        ),
        idempotency_identity=ScenarioLabIdempotencyIdentity(
            "performance-compose-formal-scenario-set-key"
        ),
        canonical_content_identity=ScenarioLabCommandContentIdentity(
            "pending-canonical-content"
        ),
        expected_source_revision=scenario_before.source_revision,
        expected_source_generation=scenario_before.source.generation,
    )
    compose = ComposeFormalScenarioSetCommand(
        metadata=metadata,
        baseline_case_id=baseline.scenario_id,
        isolated_case_ids=tuple(
            item.scenario_id
            for item in scenario_inventory.market_scenarios
            if item.layer.value == "isolated_sensitivity"
        ),
        compound_case_ids=tuple(
            item.scenario_id
            for item in scenario_inventory.market_scenarios
            if item.layer.value == "compound"
        ),
    )
    compose = replace(
        compose,
        metadata=replace(
            metadata,
            canonical_content_identity=(
                canonical_scenario_lab_command_content_identity(compose)
            ),
        ),
    )
    composed = scenario_feature.compose_scenario_set(compose)
    if (
        composed.receipt.disposition
        is not ScenarioLabCommandDisposition.ACCEPTED
    ):
        raise RuntimeError("Formal Scenario Set composition was not accepted")
    scenario_after = scenario_feature.snapshot(scenario_context)
    scenario_set = (
        None
        if not scenario_after.scenario_sets
        else scenario_after.scenario_sets[-1]
    )
    eligibility = (
        "unavailable"
        if scenario_set is None
        else str(
            getattr(
                scenario_set.eligibility,
                "value",
                scenario_set.eligibility,
            )
        )
    )
    return {
        "prepared_before_measurement": True,
        "accepted_setup_commands": [
            "compare_formal_strategy_set",
            "select_formal_strategy_set",
            "compose_visible_scenario_set",
        ],
        "accepted_revisions": {
            "strategy_library": [
                strategy_before.revision,
                strategy_after.revision,
            ],
            "scenario_lab": [
                scenario_before.revision,
                scenario_after.revision,
            ],
        },
        "comparison_count": len(comparison.entries),
        "strategy_selection_status": strategy_after.selection_status.value,
        "scenario_set_count": len(scenario_after.scenario_sets),
        "scenario_set_eligibility": eligibility,
    }


def _prepare_performance_journey_settings(settings_path: Path) -> None:
    """Persist the fixture's exact initial route through production settings."""

    bookmark = JourneyWorkspaceBookmark(
        last_route=JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS,
    )
    settings = SettingsStore(path=str(settings_path), auto_save=False)
    settings.update(
        journey_workspace_bookmark_json=(
            encode_journey_workspace_bookmark(bookmark)
        )
    )
    settings.get_state().save()
    restored = restore_journey_workspace_bookmark(
        settings.get_state().journey_workspace_bookmark_json
    )
    if (
        restored.migrated
        or restored.bookmark.last_route
        is not JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS
    ):
        raise RuntimeError(
            "Performance Journey route persistence did not restore exactly"
        )


def _ensure_performance_evidence_route(
    *,
    app: Any,
    host: Any,
    root: Any,
    navigate: Callable[..., Any],
) -> bool:
    """Navigate only when Evidence is not already the authoritative route."""

    if host.active_route is JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS:
        return False
    navigate(
        app=app,
        host=host,
        root=root,
        route="evidence_and_findings",
    )
    return True


def run_performance_lane(
    *,
    lane: str,
    duration_seconds: float,
    source_commit: str,
    smoke: bool,
    process_started_ns: int,
    integrated_v1_evidence: Mapping[str, Any] | None = None,
    fixture_archive_path: Path | None = None,
) -> dict[str, Any]:
    """Execute one isolated renderer lane and return its retained report."""

    if not smoke and fixture_archive_path is None:
        raise RuntimeError(
            "A certifying performance lane requires the packaged real V1 "
            "fixture archive"
        )
    real_v1_probe = prepare_real_v1_performance_probe(
        fixture_archive_path=fixture_archive_path,
        expected_source_commit=(
            None if fixture_archive_path is None else source_commit
        ),
    )
    try:
        real_v1_probe.run_preflight(sample_count=2)
        fixture = real_v1_probe.fixture
        identity = real_v1_probe.performance_identity
        queries = _PackagedPerformanceFixtureReadModel(
            identity=identity,
            authoritative=real_v1_probe.application_adapter,
        )
    except BaseException:
        real_v1_probe.close()
        raise
    performance_settings_path = (
        Path(fixture.database_path).parent
        / "frontend-v2-performance-settings.json"
    )
    _prepare_performance_journey_settings(performance_settings_path)
    ui_runtime_started_ns = perf_counter_ns()
    startup_markers = _PerformanceStartupMarkers(
        runtime_started_ns=ui_runtime_started_ns
    )
    existing_app = QApplication.instance()
    app = (
        QApplication([])
        if existing_app is None
        else cast(QApplication, existing_app)
    )
    startup_markers.qapplication_ready_ns = perf_counter_ns()
    from app.features import (
        LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
        LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter,
        LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter,
        LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter,
    )
    from app.features.diagnostic_setup import (
        DiagnosticSetupSelectionCoordinator,
    )
    from .frontend_v2_package_entry import (
        _configure_smoke_route_identity,
        _create_production_window,
        _navigate_route,
        _restore_environment,
        _settle_until,
    )

    setup_coordinator = DiagnosticSetupSelectionCoordinator()
    diagnostic_tasks_application = (
        LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
            fixture.application,
            setup_selection_provider=setup_coordinator.current,
        )
    )
    strategy_library_application = (
        LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
            fixture.application
        )
    )
    scenario_lab_application = (
        LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
            fixture.application
        )
    )
    system_health_application = (
        LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
            fixture.application
        )
    )
    previous_environment = _configure_smoke_route_identity(
        campaign_id=identity.campaign_id,
        run_id=identity.run_id,
        strategy_id=identity.strategy_id,
        case_id=identity.scenario_id,
        recipe_id=identity.recipe_id,
        evidence_package_id=identity.evidence_package_id,
        manifest_id=identity.manifest_id,
    )
    context: Any | None = None
    window: Any | None = None
    strategy_library: Any | None = None
    scenario_lab: Any | None = None
    diagnostic_tasks: Any | None = None
    wave3_setup_features: dict[str, Any] = {
        "feature_interfaces": [
            "StrategyLibraryFeature/1.0",
            "ScenarioLabFeature/1.0",
        ],
        "adapters": [
            "LiveStrategyLibraryAdapter",
            "LiveScenarioLabAdapter",
        ],
        "routes": ["strategy_library", "scenario_lab"],
        "presentation_states": {},
        "freshness": {},
        "qml_status_roles": {},
        "initial_focus_observed": {},
        "observed_before_load": False,
        "executed_during_active_load": False,
        "observed_during_active_load": False,
        "accepted_setup_commands": [],
        "accepted_revisions": {},
        "comparison_count": 0,
        "strategy_selection_status": "unavailable",
        "scenario_set_count": 0,
        "scenario_set_eligibility": "unavailable",
    }
    wave2_diagnostic_tasks: dict[str, Any] = {
        "feature_interface": (
            "DiagnosticTasksFeature/1.0"
        ),
        "application_interface": (
            "StrategyDiagnosticsV1DiagnosticTasksApplication/"
            f"{DIAGNOSTIC_TASKS_APPLICATION_INTERFACE_VERSION.render()}"
        ),
        "adapter": "LiveDiagnosticTasksAdapter",
        "accepted_command_ids": [],
        "result_command_ids": [],
        "accepted_command_observed": False,
        "task_handle_observed": False,
        "task_handle_ids": [],
        "handoff_observed": False,
        "terminal_observed": False,
        "executed_during_active_load": False,
        "observed_during_active_load": False,
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
    qml_observed_after_load = False
    final_qml_observation_errors: list[str] = []

    def quit_app() -> None:
        nonlocal qml_observed_after_load
        try:
            if host is not None:
                qml_observed_after_load = _qml_observes_ready_inventory(
                    host,
                    app,
                    process_events=False,
                )
        except BaseException as error:
            final_qml_observation_errors.append(
                "Final performance QML inventory capture failed: "
                f"{type(error).__name__}"
            )
        finally:
            finished[0] = True
            app.quit()

    def prepare_feature_load() -> None:
        nonlocal wave2_qml_observation_graph
        if (
            host is None
            or diagnostic_tasks is None
            or strategy_library is None
            or scenario_lab is None
        ):
            raise RuntimeError("Production Feature load is unavailable")
        root = host.rootObject()
        evidence_qt_adapter = host._evidence_and_findings
        if root is None or evidence_qt_adapter is None:
            raise RuntimeError("Production Evidence route is unavailable")
        wave2_diagnostic_tasks["observed_before_load"] = (
            _qml_observes_ready_inventory(host, app)
        )
        wave3_setup_features.update(
            _observe_wave3_setup_features(host, app)
        )
        wave3_setup_features.update(
            _prepare_wave3_setup_feature_load(
                strategy_library,
                scenario_lab,
            )
        )
        app.processEvents()
        workspace_state = diagnostic_tasks.snapshot(
            DiagnosticTasksContext.workspace()
        )
        inventory = workspace_state.last_reliable_inventory
        if inventory is None:
            raise RuntimeError(
                "Live Diagnostic Tasks inventory is unavailable"
            )
        wave2_qml_observation_graph = ()
        wave2_diagnostic_tasks.update(
            {
                "mode": "read_only_live_inventory_observation",
                "prepared_before_measurement": True,
                "inventory_counts": {
                    "strategies": len(inventory.strategies),
                    "approved_recipes": len(inventory.approved_recipes),
                    "market_scenarios": len(inventory.market_scenarios),
                },
                "observed_before_load": True,
            }
        )
        _ensure_performance_evidence_route(
            app=app,
            host=host,
            root=root,
            navigate=_navigate_route,
        )
        evidence_qt_adapter.setActiveTab("context")
        app.processEvents()
        app.processEvents()

    def observe_active_load() -> None:
        if (
            probe is None
            or not probe.measurement_active
            or host is None
            or diagnostic_tasks is None
        ):
            raise RuntimeError(
                "Production Feature load was not observed inside the active load"
            )
        wave3_setup_features["observed_during_active_load"] = True
        wave2_diagnostic_tasks.update(
            {
                "source_events_after_command": probe.source_events,
                "observed_during_active_load": bool(
                    wave2_diagnostic_tasks.get("observed_before_load")
                ),
            }
        )
        _ensure_performance_evidence_route(
            app=app,
            host=host,
            root=host.rootObject(),
            navigate=_navigate_route,
        )

    startup_markers.window_create_started_ns = perf_counter_ns()
    try:
        context, window, host = _create_production_window(
            event_bridge=bridge,
            strategy_diagnostics_application=fixture.application,
            strategy_diagnostics_read_model=queries,
            strategy_diagnostics_tasks_application=(
                diagnostic_tasks_application
            ),
            strategy_diagnostics_library_application=(
                strategy_library_application
            ),
            strategy_diagnostics_scenario_lab_application=(
                scenario_lab_application
            ),
            strategy_diagnostics_system_health_application=(
                system_health_application
            ),
            diagnostic_setup_selection_coordinator=setup_coordinator,
            settings_path=performance_settings_path,
        )
        startup_markers.window_created_ns = perf_counter_ns()
        strategy_library = context.strategy_library_feature
        scenario_lab = context.scenario_lab_feature
        diagnostic_tasks = context.diagnostic_tasks_feature
        run_feature = context.run_monitoring_feature
        evidence_feature = context.evidence_and_findings_feature
        dispose_batch_probe = bridge.subscribe_batches(
            recorder.record_batch
        )
        evidence_context = _evidence_context(identity)
        performance_subscription = evidence_feature.subscribe(
            evidence_context,
            recorder.record_feature_state,
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
        startup_markers.window_bindings_ready_ns = perf_counter_ns()
        _ensure_performance_evidence_route(
            app=app,
            host=host,
            root=root,
            navigate=_navigate_route,
        )
        evidence_qt_adapter.setActiveTab("context")
        startup_markers.initial_route_ready_ns = perf_counter_ns()

        bridge.start()
        startup_markers.bridge_started_ns = perf_counter_ns()
        window.resize(
            REFERENCE_MEASUREMENT_PROTOCOL.window_width,
            REFERENCE_MEASUREMENT_PROTOCOL.window_height,
        )
        window.move(-10_000, -10_000)
        startup_markers.window_show_started_ns = perf_counter_ns()
        window.show()
        startup_markers.window_show_returned_ns = perf_counter_ns()
        app.processEvents()
        startup_markers.window_shown_ns = perf_counter_ns()

        def initial_fixture_projection_ready() -> bool:
            renderer = root.findChild(QObject, "productionEvidenceChart")
            series_shape = root.findChild(QObject, "evidenceChartSeriesShape")
            candidate_repeater = root.findChild(
                QObject,
                "evidenceCandidateRepeater",
            )
            return bool(
                renderer is not None
                and series_shape is not None
                and candidate_repeater is not None
                and evidence_qt_adapter.presentationState == "ready"
                and evidence_qt_adapter.chartSourcePointCount
                == REFERENCE_FIXTURE.source_points
                and int(renderer.property("samplePointCount") or 0)
                == REFERENCE_FIXTURE.visible_points
                and int(renderer.property("seriesPointCount") or 0)
                == REFERENCE_FIXTURE.visible_points
                and int(renderer.property("overlayCount") or 0)
                == REFERENCE_FIXTURE.overlay_count
                and int(series_shape.property("seriesPointCount") or 0)
                == REFERENCE_FIXTURE.visible_points
                and int(candidate_repeater.property("count") or 0)
                == REFERENCE_FIXTURE.candidate_rows
            )

        try:
            _settle_until(
                app,
                initial_fixture_projection_ready,
                "real persisted performance Evidence projection",
                timeout_seconds=15.0,
            )
        except RuntimeError as error:
            raise RuntimeError(
                f"{error}; presentation={evidence_qt_adapter.presentationState}; "
                f"status={evidence_qt_adapter.statusText}; "
                f"chart_source_points="
                f"{evidence_qt_adapter.chartSourcePointCount}"
            ) from error
        startup_markers.fixture_projection_ready_ns = perf_counter_ns()
        probe = _QtPerformanceProbe(
            app=app,
            host=host,
            recorder=recorder,
            queries=queries,
            bridge=bridge,
            duration_seconds=duration_seconds,
            process_started_ns=ui_runtime_started_ns,
            on_usable=prepare_feature_load,
            on_measurement_active=observe_active_load,
            on_finished=quit_app,
        )
        probe.connect_render_signals()
        host.update()
        host.quickWindow().update()
        QTimer.singleShot(
            max(5_000, ceil((duration_seconds + 5.0) * 1_000)),
            app.quit,
        )
        app.exec()
        probe.errors.extend(final_qml_observation_errors)
        if not finished[0]:
            probe.errors.append("Performance lane watchdog expired")
        observed_fixture = probe.observed_fixture
        wave2_diagnostic_tasks["observed_after_load"] = (
            qml_observed_after_load
        )
    finally:
        cleanup_candidates: tuple[
            tuple[str, Callable[[], None] | None],
            ...,
        ] = (
            (
                "performance render probe",
                (
                    probe.disconnect_render_signals
                    if probe is not None
                    else None
                ),
            ),
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
                "Production MainWindow",
                window.close if window is not None else None,
            ),
            (
                "Strategy Library Feature",
                (
                    strategy_library.close
                    if strategy_library is not None
                    else None
                ),
            ),
            (
                "Scenario Lab Feature",
                scenario_lab.close if scenario_lab is not None else None,
            ),
            (
                "Diagnostic Tasks Feature",
                diagnostic_tasks.close if diagnostic_tasks is not None else None,
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
                "System Health Feature",
                (
                    context.system_health_feature.close
                    if context is not None
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
            ("real persisted V1 fixture", real_v1_probe.close),
            (
                "release environment",
                lambda: _restore_environment(previous_environment),
            ),
            ("Qt event drain", app.processEvents),
        )
        cleanup_actions = tuple(
            (label, action)
            for label, action in cleanup_candidates
            if action is not None
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
    integrated_v1_evidence = real_v1_probe.evidence()

    report = _build_report(
        lane=lane,
        source_commit=source_commit,
        smoke=smoke,
        probe=probe,
        recorder=recorder,
        observed_fixture=observed_fixture,
        real_v1_evidence=integrated_v1_evidence,
        wave3_setup_features=wave3_setup_features,
        wave2_diagnostic_tasks=wave2_diagnostic_tasks,
        startup_markers=startup_markers,
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
    wave3_setup_features: Mapping[str, Any],
    wave2_diagnostic_tasks: Mapping[str, Any],
    startup_markers: _PerformanceStartupMarkers,
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
        "schema_version": 3,
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
        "startup_phases_ms": startup_markers.phase_durations_ms(
            usable_visible_ns=probe.usable_visible_ns
        ),
        "production_path": list(WAVE3_PERFORMANCE_PRODUCTION_PATH),
        "integrated_v1_probe": (
            None
            if real_v1_evidence is None
            else dict(real_v1_evidence)
        ),
        "wave3_setup_features": dict(wave3_setup_features),
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
        "raw_samples": {
            "event_to_visible_ms": list(recorder.event_to_visible_ms),
            "input_response_ms": list(recorder.input_response_ms),
            "source_event_intervals_ms": source_intervals_ms,
            "main_thread_gaps_ms": list(recorder.main_thread_gaps_ms),
            "working_set_mib": list(recorder.memory_mib),
            "accepted_revision_to_source_revision": [
                {
                    "view_revision": view_revision,
                    "source_revision": source_revision,
                }
                for view_revision, source_revision in sorted(
                    recorder.view_to_source_revision.items()
                )
            ],
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


def _run_context(identity: _PerformanceIdentity) -> RunMonitoringContext:
    return RunMonitoringContext.for_run(
        RunMonitoringSelection(
            campaign_id=FormalDiagnosticCampaignId(identity.campaign_id),
            run_id=StrategyRunId(identity.run_id),
        )
    )


def _evidence_context(
    identity: _PerformanceIdentity,
) -> EvidenceAndFindingsContext:
    return EvidenceAndFindingsContext.for_selection(
        EvidenceAndFindingsSelection(
            campaign_id=FormalDiagnosticCampaignId(identity.campaign_id),
            run_id=StrategyRunId(identity.run_id),
            strategy_id=StrategyUnderTestId(identity.strategy_id),
            market_scenario_id=MarketScenarioId(identity.scenario_id),
            approved_recipe_id=ApprovedScenarioRecipeId(identity.recipe_id),
            reproduction_manifest_id=ReproductionManifestId(
                identity.manifest_id
            ),
        )
    )


__all__ = ["run_performance_lane"]
