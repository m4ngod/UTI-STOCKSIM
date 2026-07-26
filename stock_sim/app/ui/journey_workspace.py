"""Internal Qt Adapter and host for the centralized QML Journey Workspace."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Property, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QWidget

from app.features import (
    CancelDiagnosticTask,
    PauseDiagnosticTask,
    ResumeDiagnosticTask,
    RunMonitoringContext,
    RunMonitoringFeature,
    RunMonitoringViewState,
    Subscription,
)


_QML_ROOT = Path(__file__).resolve().parent / "qml"


class RunMonitoringQtAdapter(QObject):
    """Qt-only projection of the external typed Run Monitoring Interface."""

    stateChanged = Signal()
    commandChanged = Signal()
    deliveryRequested = Signal(object)

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
        self.deliveryRequested.connect(
            self._accept_state,
            Qt.ConnectionType.QueuedConnection,
        )
        self._subscription: Subscription | None = feature.subscribe(
            self._context,
            self._queue_state,
        )

    def _queue_state(self, state: RunMonitoringViewState) -> None:
        self.deliveryRequested.emit(state)

    @Slot(object)
    def _accept_state(self, state: RunMonitoringViewState) -> None:
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
        self._accept_state(self._feature.snapshot(self._context))

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
        subscription = self._subscription
        if subscription is None:
            return
        self._subscription = None
        subscription.dispose()


class JourneyWorkspaceHost(QQuickWidget):
    """Exactly one route-level QML host mounted by the Widgets MainWindow."""

    def __init__(
        self,
        feature: RunMonitoringFeature,
        *,
        context: RunMonitoringContext | None = None,
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
        self.setSource(QUrl.fromLocalFile(str(_QML_ROOT / "JourneyWorkspace.qml")))
        if self.status() == QQuickWidget.Status.Error:
            details = "; ".join(error.toString() for error in self.errors())
            raise RuntimeError(f"Failed to load Journey Workspace QML: {details}")

    def close_adapter(self) -> None:
        self._run_monitoring.close()


__all__ = ["JourneyWorkspaceHost", "RunMonitoringQtAdapter"]
