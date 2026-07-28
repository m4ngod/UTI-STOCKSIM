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
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from math import ceil, sin
from pathlib import Path
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
from PySide6.QtGui import QKeyEvent
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication

from app.event_bridge import EventBridge, EventBridgeBatch
from app.features import (
    APPLICATION_READ_MODEL_INTERFACE_VERSION,
    ApplicationReadAvailability,
    ApplicationReadError,
    ApplicationReadErrorCode,
    ApplicationReadModelVersion,
    ApplicationReadResult,
    ApprovedScenarioRecipeId,
    DiagnosticTaskCapabilities,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsData,
    EvidenceAndFindingsSelection,
    EvidenceCoverage,
    ExecutionAssumption,
    FormalDiagnosticCampaignId,
    LiveEvidenceAndFindingsAdapter,
    LiveRunMonitoringAdapter,
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
    StrategyRunId,
    StrategyUnderTestId,
    TerminalOutcome,
    V1JourneySelector,
    WallTime,
)
from app.ui.journey_workspace import JourneyWorkspaceHost

from .frontend_v2_packaging import (
    TOOLCHAIN_LOCK_PATH,
    running_toolchain,
)
from .frontend_v2_performance import (
    PERFORMANCE_THRESHOLDS,
    REFERENCE_FIXTURE,
    REFERENCE_MEASUREMENT_PROTOCOL,
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


class _PerformanceRuntimeQueries:
    """Thread-safe typed Run fixture plus the pre-#51 Evidence query fixture."""

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
        del journey
        return self._read_failure(
            code=ApplicationReadErrorCode.READ_FAILED,
            message="Typed Evidence reads are introduced by Issue #51.",
            retryable=False,
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


class _MetricRecorder:
    def __init__(self, queries: _PerformanceRuntimeQueries) -> None:
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
        queries: _PerformanceRuntimeQueries,
        bridge: EventBridge,
        duration_seconds: float,
        process_started_ns: int,
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
            max(1, ceil(self._duration_seconds * 1_000)),
            self._publish_terminal,
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


def run_performance_lane(
    *,
    lane: str,
    duration_seconds: float,
    source_commit: str,
    smoke: bool,
    process_started_ns: int,
) -> dict[str, Any]:
    """Execute one isolated renderer lane and return its retained report."""

    app = QApplication.instance() or QApplication([])
    queries = _PerformanceRuntimeQueries()
    recorder = _MetricRecorder(queries)
    bridge = EventBridge(
        flush_interval_ms=REFERENCE_FIXTURE.source_cadence_ms,
        max_batch_size=500,
        subscribe_backend=False,
    )
    dispose_batch_probe = bridge.subscribe_batches(recorder.record_batch)
    run_feature = LiveRunMonitoringAdapter(
        application_read_model=queries,
        event_bridge=bridge,
    )
    evidence_feature = LiveEvidenceAndFindingsAdapter(
        runtime_gateway=queries,
        event_bridge=bridge,
    )
    evidence_context = _evidence_context()
    performance_subscription = evidence_feature.subscribe(
        evidence_context,
        recorder.record_feature_state,
    )
    host = JourneyWorkspaceHost(
        run_feature,
        context=_run_context(),
        evidence_feature=evidence_feature,
        evidence_context=evidence_context,
    )
    root = host.rootObject()
    if root is None:
        raise RuntimeError("Journey Workspace QML did not load")
    root.setProperty("activeRoute", "evidence_and_findings")
    evidence_qt_adapter = host._evidence_and_findings
    if evidence_qt_adapter is None:
        raise RuntimeError("Evidence & Findings Qt Adapter is unavailable")
    evidence_qt_adapter.setActiveTab("context")

    bridge.start()
    finished = [False]

    def quit_app() -> None:
        finished[0] = True
        app.quit()

    host.resize(
        REFERENCE_MEASUREMENT_PROTOCOL.window_width,
        REFERENCE_MEASUREMENT_PROTOCOL.window_height,
    )
    host.move(-10_000, -10_000)
    host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
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

    performance_subscription.dispose()
    host.close_adapter()
    host.close()
    run_feature.close()
    evidence_feature.close()
    dispose_batch_probe()
    bridge.stop()
    app.processEvents()

    report = _build_report(
        lane=lane,
        source_commit=source_commit,
        smoke=smoke,
        probe=probe,
        recorder=recorder,
        observed_fixture=observed_fixture,
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
        "schema_version": 1,
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
        "production_path": [
            "EventBridge",
            "LiveRunMonitoringAdapter",
            "LiveEvidenceAndFindingsAdapter",
            "JourneyWorkspaceHost",
            "EvidenceChart.qml",
        ],
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
