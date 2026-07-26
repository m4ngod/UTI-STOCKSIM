"""Internal Qt Adapter and host for the centralized QML Journey Workspace."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import count
from math import ceil
from pathlib import Path
from threading import Lock
from time import monotonic_ns
from typing import Callable

from PySide6.QtCore import (
    Property,
    QObject,
    QPointF,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QWidget

from app.features import (
    CancelDiagnosticTask,
    CandidateEvidence,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsFeature,
    EvidenceAndFindingsSubscription,
    EvidenceAndFindingsViewState,
    EvidenceCoverage,
    EvidenceDimension,
    PauseDiagnosticTask,
    ResumeDiagnosticTask,
    RunMonitoringContext,
    RunMonitoringFeature,
    RunMonitoringViewState,
    Subscription,
)
from .evidence_chart import (
    EvidenceChartFrameGate,
    EvidenceChartFrameGateResult,
    EvidenceChartPresentation,
    EvidenceChartRenderFrame,
    EvidenceChartSamplingPolicy,
    EvidenceChartViewport,
    build_evidence_chart_presentation,
)


_QML_ROOT = Path(__file__).resolve().parent / "qml"
_MOUNT_GENERATIONS = count(1)
_MOUNT_GENERATION_LOCK = Lock()


@dataclass(frozen=True, slots=True)
class ViewMountGenerationId:
    value: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, int) or self.value < 1:
            raise ValueError("View mount generation must be positive")


def _next_mount_generation() -> ViewMountGenerationId:
    with _MOUNT_GENERATION_LOCK:
        return ViewMountGenerationId(next(_MOUNT_GENERATIONS))


class RunMonitoringQtAdapter(QObject):
    """Qt-only projection of the external typed Run Monitoring Interface."""

    stateChanged = Signal()
    commandChanged = Signal()
    deliveryRequested = Signal(int, object)

    def __init__(
        self,
        feature: RunMonitoringFeature,
        *,
        context: RunMonitoringContext | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._feature = feature
        self._context = context or RunMonitoringContext.no_selection()
        self._state = feature.snapshot(self._context)
        self._mount_generation = _next_mount_generation()
        self._closed = False
        self.deliveryRequested.connect(
            self._accept_state,
            Qt.ConnectionType.QueuedConnection,
        )
        self._subscription: Subscription | None = feature.subscribe(
            self._context,
            self._queue_state,
        )

    def _queue_state(self, state: RunMonitoringViewState) -> None:
        if self._closed:
            return
        self.deliveryRequested.emit(self._mount_generation.value, state)

    @Slot(int, object)
    def _accept_state(
        self,
        mount_generation: int,
        state: RunMonitoringViewState,
    ) -> None:
        if (
            self._closed
            or mount_generation != self._mount_generation.value
        ):
            return
        if state.context != self._context:
            return
        if state.revision <= self._state.revision:
            return
        self._state = state
        self.stateChanged.emit()

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def presentationState(self) -> str:  # noqa: N802 - QML property convention
        return str(self._state.presentation.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def phase(self) -> str:
        return str(self._state.phase.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def freshness(self) -> str:
        return str(self._state.freshness.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def ageText(self) -> str:  # noqa: N802 - QML property convention
        return f"{self._state.age.total_seconds():.1f}s"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def freshnessThresholdText(self) -> str:  # noqa: N802
        return f"{self._state.freshness_threshold.total_seconds():.1f}s"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def completeness(self) -> str:
        return str(self._state.completeness.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def revisionText(self) -> str:  # noqa: N802 - QML property convention
        return f"r{self._state.revision}"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def observedAtText(self) -> str:  # noqa: N802 - QML property convention
        return str(self._state.observed_at.isoformat())

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def sourceIdentity(self) -> str:  # noqa: N802 - QML property convention
        return str(self._state.source.identity)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def sourceGenerationText(self) -> str:  # noqa: N802
        return f"g{self._state.source.generation.value}"

    @Property(int, constant=True)
    def mountGeneration(self) -> int:  # noqa: N802
        return self._mount_generation.value

    @Property(str, constant=True)
    def mountGenerationText(self) -> str:  # noqa: N802
        return f"m{self._mount_generation.value}"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def campaignIdentity(self) -> str:  # noqa: N802
        selection = self._state.context.selection
        return "" if selection is None else selection.campaign_id.value

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def runIdentity(self) -> str:  # noqa: N802
        selection = self._state.context.selection
        if selection is None or selection.run_id is None:
            return ""
        return str(selection.run_id.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def strategyIdentity(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.strategy_id is None:
            return "Unavailable"
        return str(data.strategy_id.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def marketScenarioIdentity(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.market_scenario_id is None:
            return "Unavailable"
        return str(data.market_scenario_id.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def scenarioSetIdentity(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.scenario_set_id is None:
            return "Unavailable"
        return str(data.scenario_set_id.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def reproductionManifestIdentity(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.reproduction_manifest_id is None:
            return "Unavailable"
        return str(data.reproduction_manifest_id.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def lifecycle(self) -> str:
        data = self._state.last_reliable_data
        return "" if data is None else data.lifecycle.value

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def terminalOutcome(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.terminal_outcome is None:
            return ""
        return str(data.terminal_outcome.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def currentNodeText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        return (
            f"{data.progress.current_node_id} · "
            f"{data.progress.current_node_label}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def progressText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        return f"{data.progress.completed} / {data.progress.total}"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def simulationTimeText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        return (
            f"Day {data.simulation_time.sim_day} · "
            f"{data.simulation_time.instant.isoformat()}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def wallTimeText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        seconds = int(data.wall_time.elapsed.total_seconds())
        return f"{data.wall_time.observed_at.isoformat()} · elapsed {seconds}s"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def executionAssumptionsText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        return "\n".join(
            (
                f"{item.name}: requested {item.requested_value}; "
                f"effective {item.effective_value}"
                + (
                    f"; override {item.override_reason}"
                    if item.override_reason
                    else ""
                )
            )
            for item in data.execution_assumptions
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def alertsText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        return "\n".join(
            f"{item.severity.value.upper()} · {item.message}"
            for item in data.alerts
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def diagnosticContextText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        context = data.context
        return "\n".join(
            (
                f"Market · {', '.join(context.market) or 'none'}",
                f"Account · {', '.join(context.account) or 'none'}",
                f"Positions · {', '.join(context.positions) or 'none'}",
                f"Orders · {', '.join(context.orders) or 'none'}",
                f"Fills · {', '.join(context.fills) or 'none'}",
            )
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canPause(self) -> bool:  # noqa: N802
        data = self._state.last_reliable_data
        return bool(
            data is not None
            and self._state.freshness.value == "fresh"
            and data.capabilities.can_pause
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canResume(self) -> bool:  # noqa: N802
        data = self._state.last_reliable_data
        return bool(
            data is not None
            and self._state.freshness.value == "fresh"
            and data.capabilities.can_resume
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def canCancel(self) -> bool:  # noqa: N802
        data = self._state.last_reliable_data
        return bool(
            data is not None
            and self._state.freshness.value == "fresh"
            and data.capabilities.can_cancel
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def activeTaskText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.active_task is None:
            return ""
        task = data.active_task
        details = [
            task.identity.value,
            task.phase.value,
            f"{round(task.progress * 100)}%",
            "cancelable" if task.cancelable else "not cancelable",
        ]
        if task.result:
            details.append(task.result)
        if task.error is not None:
            details.extend((task.error.code, task.error.message))
        return " · ".join(details)

    @Property(str, notify=commandChanged)  # type: ignore[arg-type]
    def commandMessage(self) -> str:  # noqa: N802
        return getattr(self, "_command_message", "")

    @Slot()
    def refresh(self) -> None:
        self._accept_state(
            self._mount_generation.value,
            self._feature.snapshot(self._context),
        )

    @Slot()
    def pauseDiagnosticTask(self) -> None:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.task_id is None:
            self._set_command_message("Diagnostic task is unavailable.")
            return
        result = self._feature.pause_diagnostic_task(
            PauseDiagnosticTask(
                target_id=data.task_id,
                expected_revision=self._state.revision,
            )
        )
        self._set_command_message(result.message)

    @Slot()
    def resumeDiagnosticTask(self) -> None:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.task_id is None:
            self._set_command_message("Diagnostic task is unavailable.")
            return
        result = self._feature.resume_diagnostic_task(
            ResumeDiagnosticTask(
                target_id=data.task_id,
                expected_revision=self._state.revision,
            )
        )
        self._set_command_message(result.message)

    @Slot()
    def cancelDiagnosticTask(self) -> None:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or data.task_id is None:
            self._set_command_message("Diagnostic task is unavailable.")
            return
        result = self._feature.cancel_diagnostic_task(
            CancelDiagnosticTask(
                target_id=data.task_id,
                expected_revision=self._state.revision,
            )
        )
        self._set_command_message(result.message)

    def _set_command_message(self, message: str) -> None:
        if getattr(self, "_command_message", "") == message:
            return
        self._command_message = message
        self.commandChanged.emit()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()
        try:
            self.deliveryRequested.disconnect(self._accept_state)
        except (RuntimeError, TypeError):
            pass


class EvidenceAndFindingsQtAdapter(QObject):
    """Qt projection plus local-only research exploration state."""

    stateChanged = Signal()
    localStateChanged = Signal()
    chartPresentationChanged = Signal()
    chartInteractionChanged = Signal()
    deliveryRequested = Signal(int, object)

    def __init__(
        self,
        feature: EvidenceAndFindingsFeature,
        *,
        context: EvidenceAndFindingsContext | None = None,
        chart_clock: Callable[[], int] = monotonic_ns,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._feature = feature
        self._context = context or EvidenceAndFindingsContext.no_selection()
        self._state = feature.snapshot(self._context)
        self._mount_generation = _next_mount_generation()
        self._closed = False
        self._selected_candidate = ""
        self._selected_finding = ""
        self._evidence_filter = "all"
        self._sort_order = "dimension"
        self._active_tab = "findings"
        self._viewport_intent = "overview"
        self._selected_point_source_index: int | None = None
        self._selected_overlay = ""
        self._selected_breakpoint = ""
        self._chart_clock = chart_clock
        self._chart_frame_gate = EvidenceChartFrameGate(
            max_frames_per_second=20
        )
        self._pending_chart_presentations: list[
            EvidenceChartPresentation
        ] = []
        self._chart_interaction_enabled = True
        self._chart_timer = QTimer(self)
        self._chart_timer.setSingleShot(True)
        self._chart_timer.timeout.connect(self.flush_chart_frames)
        self._repair_local_selection()
        self._chart_presentation = self._build_chart_presentation()
        self._chart_frame_sequence = 1
        initial_gate = self._chart_frame_gate.offer(
            self._chart_presentation.frame,
            now_ns=self._chart_clock(),
        )
        if not initial_gate.committed:
            raise RuntimeError(
                "Initial Evidence chart presentation was not committed"
            )
        self.deliveryRequested.connect(
            self._accept_state,
            Qt.ConnectionType.QueuedConnection,
        )
        self._subscription: EvidenceAndFindingsSubscription | None = (
            feature.subscribe(
                self._context,
                self._queue_state,
            )
        )

    def _queue_state(self, state: EvidenceAndFindingsViewState) -> None:
        if not self._closed:
            self.deliveryRequested.emit(self._mount_generation.value, state)

    @Slot(int, object)
    def _accept_state(
        self,
        mount_generation: int,
        state: EvidenceAndFindingsViewState,
    ) -> None:
        if self._closed or mount_generation != self._mount_generation.value:
            return
        if state.context != self._context or state.revision <= self._state.revision:
            return
        self._state = state
        self._repair_local_selection()
        self._offer_chart_presentation(
            self._build_chart_presentation(),
            local=False,
        )
        self.stateChanged.emit()
        self.localStateChanged.emit()

    def _repair_local_selection(self) -> None:
        data = self._state.last_reliable_data
        candidates = () if data is None else data.candidates
        candidate_ids = {item.identity.value for item in candidates}
        if self._selected_candidate not in candidate_ids:
            self._selected_candidate = (
                candidates[0].identity.value if candidates else ""
            )
        candidate = self._candidate()
        findings = () if candidate is None else candidate.findings
        finding_ids = {item.identity.value for item in findings}
        if self._selected_finding not in finding_ids:
            self._selected_finding = (
                findings[0].identity.value if findings else ""
            )
        chart = None if candidate is None else candidate.chart
        overlay_ids = (
            set() if chart is None else {item.identity for item in chart.overlays}
        )
        if self._selected_overlay not in overlay_ids:
            self._selected_overlay = (
                chart.overlays[0].identity
                if chart is not None and chart.overlays
                else ""
            )
        breakpoints = tuple(
            breakpoint
            for finding in findings
            for breakpoint in finding.sensitivity_breakpoints
        )
        breakpoint_ids = {item.identity.value for item in breakpoints}
        if self._selected_breakpoint not in breakpoint_ids:
            self._selected_breakpoint = (
                breakpoints[0].identity.value if breakpoints else ""
            )
        if chart is None:
            self._selected_point_source_index = None

    def _candidate(self) -> CandidateEvidence | None:
        data = self._state.last_reliable_data
        if data is None:
            return None
        return next(
            (
                item
                for item in data.candidates
                if item.identity.value == self._selected_candidate
            ),
            None,
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def presentationState(self) -> str:  # noqa: N802
        return str(self._state.presentation.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def phase(self) -> str:
        return str(self._state.phase.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def freshness(self) -> str:
        return str(self._state.freshness.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def completeness(self) -> str:
        return str(self._state.completeness.value)

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def revisionText(self) -> str:  # noqa: N802
        return f"r{self._state.revision}"

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def sourceText(self) -> str:  # noqa: N802
        return (
            f"{self._state.source.identity} · "
            f"g{self._state.source.generation.value}"
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def statusText(self) -> str:  # noqa: N802
        error = self._state.error
        details = (
            f"{self.freshness} · {self.phase} · {self.completeness}"
        )
        if error is not None:
            return f"{details} · {error.message}"
        return details

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def pinnedIdentitiesText(self) -> str:  # noqa: N802
        selection = self._state.context.selection
        if selection is None:
            return "No Formal Diagnostic Campaign or Strategy Run selected."
        return "\n".join(
            (
                f"Campaign · {selection.campaign_id.value}",
                f"Run · {selection.run_id.value}",
                (
                    "Strategy Under Test · "
                    f"{_optional_identity(selection.strategy_id)}"
                ),
                (
                    "Market Scenario · "
                    f"{_optional_identity(selection.market_scenario_id)}"
                ),
                (
                    "Approved Scenario Recipe · "
                    f"{_optional_identity(selection.approved_recipe_id)}"
                ),
                (
                    "Reproduction Manifest · "
                    f"{_optional_identity(selection.reproduction_manifest_id)}"
                ),
            )
        )

    @Property(bool, notify=stateChanged)  # type: ignore[arg-type]
    def hasReliableData(self) -> bool:  # noqa: N802
        return self._state.last_reliable_data is not None

    @Property("QVariantList", notify=localStateChanged)  # type: ignore[arg-type]
    def candidateIdentities(self) -> list[str]:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return []
        return [item.identity.value for item in data.candidates]

    @Property("QVariantList", notify=localStateChanged)  # type: ignore[arg-type]
    def findingIdentities(self) -> list[str]:  # noqa: N802
        candidate = self._candidate()
        if candidate is None:
            return []
        return [item.identity.value for item in candidate.findings]

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def candidateSummaryText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return "No candidate evidence is available."
        return "  ·  ".join(
            f"{item.identity.value} — {item.label}" for item in data.candidates
        )

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def selectedCandidateIdentity(self) -> str:  # noqa: N802
        return self._selected_candidate

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def selectedFindingIdentity(self) -> str:  # noqa: N802
        return self._selected_finding

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def evidenceFilter(self) -> str:  # noqa: N802
        return self._evidence_filter

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def sortOrder(self) -> str:  # noqa: N802
        return self._sort_order

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def activeTab(self) -> str:  # noqa: N802
        return self._active_tab

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def viewportIntent(self) -> str:  # noqa: N802
        return self._viewport_intent

    @Property(int, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartAcceptedRevision(self) -> int:  # noqa: N802
        return self._chart_presentation.frame.revision

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartAcceptedRevisionText(self) -> str:  # noqa: N802
        return f"r{self.chartAcceptedRevision}"

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartSourceIdentity(self) -> str:  # noqa: N802
        return self._chart_presentation.source_identity

    @Property(int, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartSourcePointCount(self) -> int:  # noqa: N802
        return self._chart_presentation.source_point_count

    @Property(int, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartVisiblePointCount(self) -> int:  # noqa: N802
        sample = self._chart_presentation.sample
        return 0 if sample is None else len(sample.points)

    @Property(int, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartOverlayCount(self) -> int:  # noqa: N802
        return len(self._chart_presentation.overlay_identities)

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartSamplingPolicy(self) -> str:  # noqa: N802
        sample = self._chart_presentation.sample
        return (
            EvidenceChartSamplingPolicy.UNIFORM_ENDPOINTS_V1.value
            if sample is None
            else sample.key.policy.value
        )

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartNarrativeText(self) -> str:  # noqa: N802
        return self._chart_presentation.narrative_text

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartTableText(self) -> str:  # noqa: N802
        return self._chart_presentation.table_text

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartAccessibleText(self) -> str:  # noqa: N802
        return self._chart_presentation.accessible_text

    @Property("QVariantList", notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartOverlayIdentities(self) -> list[str]:  # noqa: N802
        return list(self._chart_presentation.overlay_identities)

    @Property("QVariantList", notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartOverlayModels(self) -> list[dict[str, object]]:  # noqa: N802
        frame = self._chart_presentation.frame
        return [
            {
                "identity": item.identity,
                "axis": item.axis.value,
                "position": item.normalized_coordinate,
                "selected": (
                    item.identity == frame.selected_overlay_identity
                ),
            }
            for item in frame.overlays
        ]

    @Property("QVariantList", notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartNormalizedPoints(self) -> list[QPointF]:  # noqa: N802
        sample = self._chart_presentation.sample
        if sample is None:
            return []
        return [
            QPointF(item.normalized_x, item.normalized_y)
            for item in sample.points
        ]

    @Property(int, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartFrameSequence(self) -> int:  # noqa: N802
        return self._chart_frame_sequence

    @Property(bool, notify=chartInteractionChanged)  # type: ignore[arg-type]
    def chartInteractionEnabled(self) -> bool:  # noqa: N802
        return self._chart_interaction_enabled

    @Property("QVariantList", notify=chartPresentationChanged)  # type: ignore[arg-type]
    def chartBreakpointIdentities(self) -> list[str]:  # noqa: N802
        return list(self._chart_presentation.breakpoint_identities)

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def selectedChartOverlayIdentity(self) -> str:  # noqa: N802
        return self._chart_presentation.selected_overlay_identity

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def selectedChartFindingIdentity(self) -> str:  # noqa: N802
        return self._chart_presentation.selected_finding_identity

    @Property(str, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def selectedChartBreakpointIdentity(self) -> str:  # noqa: N802
        return self._chart_presentation.selected_breakpoint_identity

    @Property(int, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def selectedChartPointIndex(self) -> int:  # noqa: N802
        selected = self._chart_presentation.selected_point_source_index
        return -1 if selected is None else selected

    @Property(float, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def selectedChartPointX(self) -> float:  # noqa: N802
        selected = self._chart_presentation.frame.selected_point
        return -1.0 if selected is None else selected[0]

    @Property(float, notify=chartPresentationChanged)  # type: ignore[arg-type]
    def selectedChartPointY(self) -> float:  # noqa: N802
        selected = self._chart_presentation.frame.selected_point
        return -1.0 if selected is None else selected[1]

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def coverageText(self) -> str:  # noqa: N802
        return (
            "Baseline  ·  Isolated sensitivity  ·  Compound scenario  ·  "
            "Quick Experiment — exploratory only; does not satisfy formal coverage."
        )

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def comparisonText(self) -> str:  # noqa: N802
        candidate = self._candidate()
        if candidate is None:
            return ""
        records = {item.identity: item for item in candidate.evidence}
        lines = [f"TYPED COMPARISONS · {candidate.identity.value}"]
        for comparison in candidate.comparisons:
            reference = records[comparison.reference_evidence_id]
            observed = records[comparison.observed_evidence_id]
            lines.extend(
                (
                    f"{comparison.identity.value} · {comparison.label}",
                    (
                        f"Reference {reference.identity.value} · "
                        f"{reference.value} {reference.unit} · "
                        f"Observed {observed.identity.value} · "
                        f"{observed.value} {observed.unit}"
                    ),
                )
            )
        return "\n".join(lines)

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def breakpointsText(self) -> str:  # noqa: N802
        candidate = self._candidate()
        if candidate is None:
            return ""
        breakpoints = tuple(
            breakpoint
            for finding in candidate.findings
            for breakpoint in finding.sensitivity_breakpoints
        )
        return "\n".join(
            (
                f"Sensitivity Breakpoint · {item.identity.value} · "
                f"{item.assumption_name} {item.threshold} · {item.outcome} · "
                f"evidence {', '.join(ref.value for ref in item.evidence_ids)}"
            )
            for item in breakpoints
        )

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def assumptionsText(self) -> str:  # noqa: N802
        candidate = self._candidate()
        if candidate is None:
            return ""
        return "\n".join(
            (
                f"{item.name} · requested {item.requested_value} · "
                f"effective {item.effective_value}"
                + (
                    f" · override {item.override_reason}"
                    if item.override_reason
                    else " · no override"
                )
            )
            for item in candidate.execution_assumptions
        )

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def provenanceText(self) -> str:  # noqa: N802
        candidate = self._candidate()
        if candidate is None:
            return ""
        provenance = candidate.provenance
        dependencies = ", ".join(
            f"{item.name} {item.version} {item.artifact_hash}"
            for item in provenance.dependencies
        )
        return "\n".join(
            (
                f"Artifact hashes · {', '.join(provenance.artifact_hashes)}",
                (
                    "Source runs · "
                    f"{', '.join(item.value for item in provenance.source_run_ids)}"
                ),
                f"Runner · {provenance.runner_version}",
                f"Build · {provenance.build_version}",
                f"Dependencies · {dependencies}",
            )
        )

    @Property(str, notify=stateChanged)  # type: ignore[arg-type]
    def readOnlyContextText(self) -> str:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None:
            return ""
        context = data.read_only_context
        orders = ", ".join(
            f"{item.identity} {item.status} ({item.diagnostic_note})"
            for item in context.orders
        )
        fills = ", ".join(
            (
                f"{item.identity} from {item.order_identity} · "
                f"{item.quantity} @ {item.price}"
            )
            for item in context.fills
        )
        return "\n".join(
            (
                "Orders and fills are read-only evidence traces.",
                f"Market · {', '.join(context.market)}",
                f"Account · {', '.join(context.account)}",
                f"Positions · {', '.join(context.positions)}",
                f"Orders · {orders}",
                f"Fills · {fills}",
            )
        )

    @Slot(str)
    def selectCandidate(self, identity: str) -> None:  # noqa: N802
        data = self._state.last_reliable_data
        if data is None or identity not in {
            item.identity.value for item in data.candidates
        }:
            return
        if identity == self._selected_candidate:
            return
        self._selected_candidate = identity
        self._selected_finding = ""
        self._repair_local_selection()
        self._publish_local_change()

    @Slot(str)
    def selectFinding(self, identity: str) -> None:  # noqa: N802
        candidate = self._candidate()
        if candidate is None or identity not in {
            item.identity.value for item in candidate.findings
        }:
            return
        if identity != self._selected_finding:
            self._selected_finding = identity
            self._publish_local_change()

    @Slot(float)
    def selectChartPointAtRatio(self, ratio: float) -> None:  # noqa: N802
        if not self._chart_interaction_enabled:
            return
        sample = self._chart_presentation.sample
        if sample is None or not sample.points:
            return
        bounded = max(0.0, min(float(ratio), 1.0))
        sample_index = round(bounded * (len(sample.points) - 1))
        source_index = sample.points[sample_index].source_index
        if source_index == self._selected_point_source_index:
            return
        self._selected_point_source_index = source_index
        self._publish_local_change()

    @Slot(int)
    def stepChartPoint(self, direction: int) -> None:  # noqa: N802
        if not self._chart_interaction_enabled:
            return
        sample = self._chart_presentation.sample
        if sample is None or not sample.points or direction == 0:
            return
        current_index = next(
            (
                index
                for index, point in enumerate(sample.points)
                if point.source_index == self._selected_point_source_index
            ),
            len(sample.points) - 1,
        )
        target_index = max(
            0,
            min(
                current_index + (1 if direction > 0 else -1),
                len(sample.points) - 1,
            ),
        )
        source_index = sample.points[target_index].source_index
        if source_index == self._selected_point_source_index:
            return
        self._selected_point_source_index = source_index
        self._publish_local_change()

    @Slot(str)
    def selectChartOverlay(self, identity: str) -> None:  # noqa: N802
        if (
            not self._chart_interaction_enabled
            or identity not in self._chart_presentation.overlay_identities
            or identity == self._selected_overlay
        ):
            return
        self._selected_overlay = identity
        self._publish_local_change()

    @Slot(str)
    def selectChartBreakpoint(self, identity: str) -> None:  # noqa: N802
        if (
            not self._chart_interaction_enabled
            or identity not in self._chart_presentation.breakpoint_identities
            or identity == self._selected_breakpoint
        ):
            return
        self._selected_breakpoint = identity
        self._publish_local_change()

    @Slot(str)
    def setEvidenceFilter(self, value: str) -> None:  # noqa: N802
        allowed = {"all"} | {item.value for item in EvidenceCoverage} | {
            item.value for item in EvidenceDimension
        }
        self._set_local("_evidence_filter", value, allowed)

    @Slot(str)
    def setSortOrder(self, value: str) -> None:  # noqa: N802
        self._set_local("_sort_order", value, {"dimension", "coverage"})

    @Slot(str)
    def setActiveTab(self, value: str) -> None:  # noqa: N802
        self._set_local(
            "_active_tab",
            value,
            {"findings", "assumptions", "provenance", "context"},
        )

    @Slot(str)
    def setViewportIntent(self, value: str) -> None:  # noqa: N802
        self._set_local(
            "_viewport_intent",
            value,
            {"overview", "baseline", "sensitivity", "compound_stress"},
        )

    def _set_local(
        self,
        attribute: str,
        value: str,
        allowed: set[str],
    ) -> None:
        if value not in allowed or getattr(self, attribute) == value:
            return
        setattr(self, attribute, value)
        self._publish_local_change()

    def _publish_local_change(self) -> None:
        self._offer_chart_presentation(
            self._build_chart_presentation(),
            local=True,
        )
        self.localStateChanged.emit()

    def _build_chart_presentation(self) -> EvidenceChartPresentation:
        return build_evidence_chart_presentation(
            self._state,
            self._candidate(),
            selected_finding_identity=self._selected_finding,
            viewport=_chart_viewport(self._viewport_intent),
            selected_point_source_index=self._selected_point_source_index,
            selected_overlay_identity=self._selected_overlay,
            selected_breakpoint_identity=self._selected_breakpoint,
            evidence_filter=self._evidence_filter,
            sort_order=self._sort_order,
        )

    def _offer_chart_presentation(
        self,
        presentation: EvidenceChartPresentation,
        *,
        local: bool,
    ) -> None:
        self._selected_point_source_index = (
            presentation.selected_point_source_index
        )
        self._selected_overlay = presentation.selected_overlay_identity
        self._selected_breakpoint = presentation.selected_breakpoint_identity
        self._pending_chart_presentations.append(presentation)
        now_ns = self._chart_clock()
        result = (
            self._chart_frame_gate.offer_local(
                presentation.frame,
                now_ns=now_ns,
            )
            if local
            else self._chart_frame_gate.offer(
                presentation.frame,
                now_ns=now_ns,
            )
        )
        if not result.accepted:
            self._pending_chart_presentations.pop()
        self._apply_chart_gate_result(result)

    def flush_chart_frames(self) -> None:
        self._apply_chart_gate_result(
            self._chart_frame_gate.flush(now_ns=self._chart_clock())
        )

    def _apply_chart_gate_result(
        self,
        result: EvidenceChartFrameGateResult,
    ) -> None:
        for frame in result.committed:
            presentation_index = self._matching_chart_presentation_index(
                frame
            )
            if presentation_index is None:
                continue
            presentation = self._pending_chart_presentations[
                presentation_index
            ]
            del self._pending_chart_presentations[: presentation_index + 1]
            self._chart_presentation = presentation
            self._chart_frame_sequence += 1
            self.chartPresentationChanged.emit()
        due_in_ns = result.due_in_ns
        if due_in_ns is None:
            self._chart_timer.stop()
        else:
            self._chart_timer.start(max(1, ceil(due_in_ns / 1_000_000)))
        self._sync_chart_interaction_enabled()

    def _sync_chart_interaction_enabled(self) -> None:
        enabled = not self._pending_chart_presentations
        if enabled == self._chart_interaction_enabled:
            return
        self._chart_interaction_enabled = enabled
        self.chartInteractionChanged.emit()

    def _matching_chart_presentation_index(
        self,
        frame: EvidenceChartRenderFrame,
    ) -> int | None:
        for index in range(
            len(self._pending_chart_presentations) - 1,
            -1,
            -1,
        ):
            candidate = self._pending_chart_presentations[index].frame
            if (
                candidate.revision == frame.revision
                and candidate.points is frame.points
                and candidate.overlays is frame.overlays
                and candidate.selected_point
                == frame.selected_point
                and candidate.selected_overlay_identity
                == frame.selected_overlay_identity
                and candidate.selected_finding_identity
                == frame.selected_finding_identity
                and candidate.selected_breakpoint_identity
                == frame.selected_breakpoint_identity
            ):
                return index
        return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._chart_timer.stop()
        self._pending_chart_presentations.clear()
        subscription = self._subscription
        self._subscription = None
        if subscription is not None:
            subscription.dispose()
        try:
            self.deliveryRequested.disconnect(self._accept_state)
        except (RuntimeError, TypeError):
            pass


def _title(value: EvidenceCoverage | EvidenceDimension) -> str:
    if value is EvidenceCoverage.QUICK_EXPERIMENT:
        return "Quick Experiment"
    return str(value.value).replace("_", " ").capitalize()


def _optional_identity(value: object | None) -> str:
    if value is None:
        return "Unavailable"
    return str(getattr(value, "value", "Unavailable"))


def _chart_viewport(intent: str) -> EvidenceChartViewport:
    viewports = {
        "overview": EvidenceChartViewport(0.0, 1.0),
        "baseline": EvidenceChartViewport(0.0, 0.25),
        "sensitivity": EvidenceChartViewport(0.25, 0.7),
        "compound_stress": EvidenceChartViewport(0.7, 1.0),
    }
    return viewports.get(intent, viewports["overview"])


class JourneyWorkspaceHost(QQuickWidget):
    """Exactly one route-level QML host mounted by the Widgets MainWindow."""

    def __init__(
        self,
        feature: RunMonitoringFeature,
        *,
        context: RunMonitoringContext | None = None,
        evidence_feature: EvidenceAndFindingsFeature | None = None,
        evidence_context: EvidenceAndFindingsContext | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("journeyWorkspaceHost")
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self._run_monitoring = RunMonitoringQtAdapter(
            feature,
            context=context,
            parent=self,
        )
        self.rootContext().setContextProperty(
            "runMonitoring",
            self._run_monitoring,
        )
        self._evidence_and_findings = (
            EvidenceAndFindingsQtAdapter(
                evidence_feature,
                context=evidence_context,
                parent=self,
            )
            if evidence_feature is not None
            else None
        )
        self.rootContext().setContextProperty(
            "evidenceAndFindings",
            self._evidence_and_findings,
        )
        self.setSource(QUrl.fromLocalFile(str(_QML_ROOT / "JourneyWorkspace.qml")))
        if self.status() == QQuickWidget.Status.Error:
            details = "; ".join(error.toString() for error in self.errors())
            raise RuntimeError(f"Failed to load Journey Workspace QML: {details}")

    def close_adapter(self) -> None:
        self._run_monitoring.close()
        if self._evidence_and_findings is not None:
            self._evidence_and_findings.close()


__all__ = [
    "EvidenceAndFindingsQtAdapter",
    "JourneyWorkspaceHost",
    "RunMonitoringQtAdapter",
]
