"""Internal Qt Adapter and host for the centralized QML Journey Workspace."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import count
from pathlib import Path
from threading import Lock

from PySide6.QtCore import Property, QObject, Qt, QUrl, Signal, Slot
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
    deliveryRequested = Signal(int, object)

    def __init__(
        self,
        feature: EvidenceAndFindingsFeature,
        *,
        context: EvidenceAndFindingsContext | None = None,
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
        self._repair_local_selection()
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
    def evidenceTableText(self) -> str:  # noqa: N802
        candidate = self._candidate()
        if candidate is None:
            return ""
        records = candidate.evidence
        if self._evidence_filter != "all":
            records = tuple(
                item
                for item in records
                if self._evidence_filter
                in {item.dimension.value, item.coverage.value}
            )
        key = (
            (lambda item: (item.coverage.value, item.dimension.value))
            if self._sort_order == "coverage"
            else (lambda item: (item.dimension.value, item.coverage.value))
        )
        records = tuple(sorted(records, key=key))
        lines = []
        for item in records:
            comparison = ""
            if item.comparison_evidence_id is not None:
                comparison = (
                    f" · reference {item.comparison_evidence_id.value} "
                    f"{item.comparison_value}"
                )
            lines.append(
                f"{item.identity.value} · {_title(item.coverage)} · "
                f"{_title(item.dimension)} · {item.label} · "
                f"{item.value} {item.unit}{comparison} · "
                f"{item.availability.value} · {item.interpretation}"
            )
        return "\n".join(lines)

    @Property(str, notify=localStateChanged)  # type: ignore[arg-type]
    def findingNarrativeText(self) -> str:  # noqa: N802
        candidate = self._candidate()
        if candidate is None:
            return ""
        finding = next(
            (
                item
                for item in candidate.findings
                if item.identity.value == self._selected_finding
            ),
            None,
        )
        if finding is None:
            return ""
        citations = ", ".join(item.value for item in finding.evidence_ids)
        comparison_citations = ", ".join(
            item.value for item in finding.comparison_ids
        )
        return "\n".join(
            (
                f"{finding.identity.value} · {finding.title}",
                f"Disposition · {finding.disposition.value}",
                f"Comparison · {finding.comparison_summary}",
                f"Failure reason · {finding.failure_reason or 'none'}",
                f"Evidence citations · {citations}",
                f"Comparison citations · {comparison_citations}",
            )
        )

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
        self.localStateChanged.emit()

    @Slot(str)
    def selectFinding(self, identity: str) -> None:  # noqa: N802
        candidate = self._candidate()
        if candidate is None or identity not in {
            item.identity.value for item in candidate.findings
        }:
            return
        if identity != self._selected_finding:
            self._selected_finding = identity
            self.localStateChanged.emit()

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
        self.localStateChanged.emit()

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


def _title(value: EvidenceCoverage | EvidenceDimension) -> str:
    if value is EvidenceCoverage.QUICK_EXPERIMENT:
        return "Quick Experiment"
    return str(value.value).replace("_", " ").capitalize()


def _optional_identity(value: object | None) -> str:
    if value is None:
        return "Unavailable"
    return str(getattr(value, "value", "Unavailable"))


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
