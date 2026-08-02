import gc
import os
from dataclasses import replace
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPointF, QTimer
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication

import setup_frontend_entry as entry
from app.features import (
    DeterministicFakeRunMonitoringAdapter,
    FormalDiagnosticCampaignId,
    RunMonitoringContext,
    RunMonitoringSelection,
    StrategyRunId,
)
from app.ui.main_window import MainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _release_closed_qml_hosts_between_tests():
    yield
    app = QApplication.instance()
    if app is None:
        return
    gc.collect()
    QCoreApplication.sendPostedEvents(
        None,
        QEvent.Type.DeferredDelete,
    )
    app.processEvents()
    gc.collect()


def test_route_flag_mounts_one_centralized_qml_workspace_with_loading_state():
    _app()
    feature = DeterministicFakeRunMonitoringAdapter()

    window = MainWindow(
        run_monitoring_feature=feature,
        frontend_v2_enabled=True,
    )

    host = window.centralWidget()
    root = host.rootObject()

    assert window.journey_workspace_active is True
    assert isinstance(host, QQuickWidget)
    assert host.objectName() == "journeyWorkspaceHost"
    assert len(window.findChildren(QQuickWidget)) == 1
    assert root is not None
    assert root.objectName() == "journeyWorkspace"
    assert root.property("screenState") == "loading"
    assert (
        "Observe a Strategy Run"
        in root.findChild(QObject, "runMonitoringSubtitle").property("text")
    )

    window.close()
    feature.close()


def test_workspace_exposes_every_approved_shared_token_family():
    _app()
    feature = DeterministicFakeRunMonitoringAdapter()
    window = MainWindow(
        run_monitoring_feature=feature,
        frontend_v2_enabled=True,
    )
    root = window.centralWidget().rootObject()
    tokens = root.findChild(QObject, "designTokens")

    assert tokens is not None
    assert tokens.property("background") is not None
    assert tokens.property("bodySize") > 0
    assert tokens.property("spaceMd") > 0
    assert tokens.property("focusWidth") > 0
    assert tokens.property("elevationRaised") > 0
    assert tokens.property("durationBrief") > 0
    assert isinstance(tokens.property("reducedMotion"), bool)
    assert tokens.property("durationReducedMotion") == 0
    assert tokens.property("durationForMotion") == (
        tokens.property("durationReducedMotion")
        if tokens.property("reducedMotion")
        else tokens.property("durationBrief")
    )

    window.close()
    feature.close()


def test_gui_entry_composes_qml_route_from_app_context_without_legacy_preload(
    monkeypatch,
):
    app = _app()
    feature = DeterministicFakeRunMonitoringAdapter()
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    monkeypatch.setattr(
        entry,
        "reset_app_context",
        lambda **_: SimpleNamespace(run_monitoring_feature=feature),
    )
    monkeypatch.setattr(entry, "start_frontend_bridge", lambda: None)
    monkeypatch.setattr(entry, "stop_frontend_bridge", lambda: None)
    monkeypatch.setattr(entry, "start_runtime_support_services", lambda: None)
    monkeypatch.setattr(entry, "register_builtin_panels", lambda: None)
    monkeypatch.setattr(entry, "register_ui_adapters", lambda: None)
    QTimer.singleShot(0, app.quit)

    window = entry._start_frontend(headless=False)

    assert window.journey_workspace_active is True
    assert window.list_open() == []
    assert len(window.findChildren(QQuickWidget)) == 1
    with pytest.raises(RuntimeError, match="closed"):
        feature.snapshot(RunMonitoringContext.no_selection())

    window.close()


def test_fake_feature_advances_qml_to_explicit_no_run_selected_empty_state():
    app = _app()
    feature = DeterministicFakeRunMonitoringAdapter()
    window = MainWindow(
        run_monitoring_feature=feature,
        frontend_v2_enabled=True,
    )
    root = window.centralWidget().rootObject()

    feature.advance_to_empty(RunMonitoringContext.no_selection())
    app.processEvents()

    visible_text = " ".join(
        str(item.property("text"))
        for item in root.findChildren(QObject)
        if item.metaObject().indexOfProperty("text") >= 0
        and item.property("text")
    )

    assert root.property("screenState") == "empty"
    assert root.property("headline") == "No Strategy Run selected"
    assert "Open an existing Formal Diagnostic Campaign or Strategy Run" in visible_text
    for forbidden in (
        "Start experiment",
        "Buy",
        "Sell",
        "Submit order",
        "Cancel order",
        "Replace order",
        "Bulk order",
    ):
        assert forbidden.casefold() not in visible_text.casefold()

    window.close()
    feature.close()


def test_fake_feature_renders_an_honest_disconnected_state():
    app = _app()
    feature = DeterministicFakeRunMonitoringAdapter()
    window = MainWindow(
        run_monitoring_feature=feature,
        frontend_v2_enabled=True,
    )
    root = window.centralWidget().rootObject()

    feature.advance_to_disconnected(RunMonitoringContext.no_selection())
    app.processEvents()

    assert root.property("screenState") == "disconnected"
    assert root.property("headline") == "Run Monitoring is disconnected"
    assert (
        "Runtime data is unavailable"
        in root.findChild(QObject, "runMonitoringDetail").property("text")
    )
    assert "No Strategy Run selected" not in root.property("headline")

    window.close()
    feature.close()


def test_existing_run_renders_live_diagnostic_identity_progress_and_commands():
    app = _app()
    feature = DeterministicFakeRunMonitoringAdapter()
    context = RunMonitoringContext.for_run(
        RunMonitoringSelection(
            campaign_id=FormalDiagnosticCampaignId("FDC-001"),
            run_id=StrategyRunId("RUN-001"),
        )
    )
    feature.advance_to_running(context)
    window = MainWindow(
        run_monitoring_feature=feature,
        run_monitoring_context=context,
        frontend_v2_enabled=True,
    )
    host = window.centralWidget()
    root = host.rootObject()

    visible_text = " ".join(
        str(item.property("text"))
        for item in root.findChildren(QObject)
        if item.metaObject().indexOfProperty("text") >= 0
        and item.property("text")
    )

    assert root.property("screenState") == "active"
    assert root.property("headline") == "Strategy Run is active"
    for expected in (
        "FDC-001",
        "RUN-001",
        "STRATEGY-MOMENTUM-001",
        "SCENARIO-BASELINE",
        "SCENARIO-SET-001",
        "RM-001",
        "NODE-03",
        "2 / 10",
        "Simulation Time",
        "Wall Time",
        "standard",
        "stress-1.6x",
        "Scenario override",
        "Spread widening",
        "Read-only diagnostic context",
        "Freshness",
        "age 0.0s / 5.0s",
    ):
        assert expected.casefold() in visible_text.casefold()

    pause = root.findChild(QObject, "pauseDiagnosticTask")
    resume = root.findChild(QObject, "resumeDiagnosticTask")
    cancel = root.findChild(QObject, "cancelDiagnosticTask")
    assert pause.property("enabled") is True
    assert resume.property("enabled") is False
    assert cancel.property("enabled") is True

    host._run_monitoring.pauseDiagnosticTask()
    app.processEvents()

    assert host._run_monitoring.lifecycle == "paused"
    assert pause.property("enabled") is False
    assert resume.property("enabled") is True
    assert cancel.property("enabled") is True
    assert "accepted" in host._run_monitoring.commandMessage.casefold()

    for forbidden in (
        "Start experiment",
        "Buy",
        "Sell",
        "Submit order",
        "Cancel order",
        "Replace order",
        "Bulk order",
    ):
        assert forbidden.casefold() not in visible_text.casefold()

    window.close()
    feature.close()


def test_diagnostic_command_feedback_does_not_overlap_the_button_row():
    app = _app()
    feature = DeterministicFakeRunMonitoringAdapter()
    context = RunMonitoringContext.for_run(
        RunMonitoringSelection(
            campaign_id=FormalDiagnosticCampaignId("FDC-001"),
            run_id=StrategyRunId("RUN-001"),
        )
    )
    feature.advance_to_running(context)
    window = MainWindow(
        run_monitoring_feature=feature,
        run_monitoring_context=context,
        frontend_v2_enabled=True,
    )
    window.resize(1440, 900)
    window.show()
    app.processEvents()
    root = window.centralWidget().rootObject()
    pause = root.findChild(QObject, "pauseDiagnosticTask")
    feedback = root.findChild(QObject, "diagnosticCommandFeedback")

    assert feedback is not None
    pause_top = pause.mapToItem(root, QPointF(0, 0)).y()
    feedback_top = feedback.mapToItem(root, QPointF(0, 0)).y()
    assert feedback_top >= pause_top + pause.property("height")

    window.close()
    feature.close()


def test_route_unmount_does_not_change_diagnostic_task_and_remount_sees_state():
    app = _app()
    feature = DeterministicFakeRunMonitoringAdapter()
    context = RunMonitoringContext.for_run(
        RunMonitoringSelection(
            campaign_id=FormalDiagnosticCampaignId("FDC-001"),
            run_id=StrategyRunId("RUN-001"),
        )
    )
    running = feature.advance_to_running(context)

    first = MainWindow(
        run_monitoring_feature=feature,
        run_monitoring_context=context,
        frontend_v2_enabled=True,
    )
    first.close()
    app.processEvents()

    after_unmount = feature.snapshot(context)
    assert after_unmount.revision == running.revision
    assert after_unmount.last_reliable_data.lifecycle.value == "running"

    second = MainWindow(
        run_monitoring_feature=feature,
        run_monitoring_context=context,
        frontend_v2_enabled=True,
    )
    app.processEvents()
    assert second.centralWidget()._run_monitoring.lifecycle == "running"
    assert second.centralWidget()._run_monitoring.progressText == "2 / 10"

    second.close()
    feature.close()


def test_route_remount_rediscovers_the_existing_task_handle():
    app = _app()
    feature = DeterministicFakeRunMonitoringAdapter()
    context = RunMonitoringContext.for_run(
        RunMonitoringSelection(
            campaign_id=FormalDiagnosticCampaignId("FDC-001"),
            run_id=StrategyRunId("RUN-001"),
        )
    )
    feature.advance_to_running(context)
    first = MainWindow(
        run_monitoring_feature=feature,
        run_monitoring_context=context,
        frontend_v2_enabled=True,
    )
    first_adapter = first.centralWidget()._run_monitoring

    first_adapter.pauseDiagnosticTask()
    app.processEvents()
    task_text = first_adapter.activeTaskText

    assert "FAKE-TASK-0001" in task_text
    assert "completed" in task_text
    assert "100%" in task_text
    first.close()
    app.processEvents()

    second = MainWindow(
        run_monitoring_feature=feature,
        run_monitoring_context=context,
        frontend_v2_enabled=True,
    )
    app.processEvents()
    second_adapter = second.centralWidget()._run_monitoring
    feedback = second.centralWidget().rootObject().findChild(
        QObject,
        "diagnosticCommandFeedback",
    )

    assert second_adapter.activeTaskText == task_text
    assert task_text in feedback.property("text")

    second.close()
    feature.close()


def test_route_flag_off_preserves_the_legacy_widgets_workspace():
    _app()
    feature = DeterministicFakeRunMonitoringAdapter()

    window = MainWindow(
        run_monitoring_feature=feature,
        frontend_v2_enabled=False,
    )
    legacy_layout = window.ensure_legacy_central_layout()

    assert window.journey_workspace_active is False
    assert legacy_layout is not None
    assert not isinstance(window.centralWidget(), QQuickWidget)
    assert window.findChildren(QQuickWidget) == []

    feature.close()


def test_release_close_mount_quiesces_real_qml_route_before_shutdown(
    monkeypatch,
):
    from stock_sim.release.frontend_v2_package_entry import (
        _close_mount,
        _schedule_closed_mount_release,
    )

    app = _app()
    events: list[str] = []
    state_change_count = 0
    feature = DeterministicFakeRunMonitoringAdapter()
    window = MainWindow(
        run_monitoring_feature=feature,
        frontend_v2_enabled=True,
    )
    host = window.centralWidget()
    root = host.rootObject()
    adapter = host._run_monitoring
    assert root is not None

    root.destroyed.connect(lambda *_: events.append("qml-root-destroyed"))

    def observe_state_change() -> None:
        nonlocal state_change_count
        state_change_count += 1

    adapter.stateChanged.connect(observe_state_change)
    original_adapter_close = adapter.close

    def close_adapter() -> None:
        events.append("run-adapter")
        original_adapter_close()

    monkeypatch.setattr(adapter, "close", close_adapter)

    class ClosingFeature:
        def __init__(self, name: str) -> None:
            self._name = name
            self.closed = False

        def close(self) -> None:
            events.append(self._name)
            self.closed = True

    diagnostic_feature = ClosingFeature("diagnostic-feature")
    evidence_feature = ClosingFeature("evidence-feature")
    original_feature_close = feature.close

    def close_run_feature() -> None:
        events.append("run-feature")
        original_feature_close()

    monkeypatch.setattr(feature, "close", close_run_feature)
    context = SimpleNamespace(
        diagnostic_tasks_feature=diagnostic_feature,
        run_monitoring_feature=feature,
        evidence_and_findings_feature=evidence_feature,
    )
    original_hide = window.hide
    original_close = window.close
    original_process_events = app.processEvents

    def hide_window() -> None:
        events.append("window-hide")
        original_hide()

    def close_window() -> bool:
        events.append("window-close")
        return original_close()

    def process_events() -> None:
        events.append("process-events")
        original_process_events()

    monkeypatch.setattr(window, "hide", hide_window)
    monkeypatch.setattr(window, "close", close_window)
    monkeypatch.setattr(app, "processEvents", process_events)
    window.show()
    original_process_events()
    late_state = replace(adapter._state, revision=adapter._state.revision + 1)

    _close_mount(
        app=app,
        context=context,
        window=window,
        host=host,
    )

    assert events == [
        "window-hide",
        "process-events",
        "run-adapter",
        "qml-root-destroyed",
        "process-events",
        "window-close",
        "process-events",
        "diagnostic-feature",
        "run-feature",
        "evidence-feature",
        "process-events",
    ]
    assert host.rootObject() is None
    assert host._workspace_closed is True
    assert diagnostic_feature.closed is True
    assert evidence_feature.closed is True

    state_changes_before_late_delivery = state_change_count
    adapter.deliveryRequested.emit(adapter._mount_generation.value, late_state)
    original_process_events()
    assert state_change_count == state_changes_before_late_delivery

    window_destroyed: list[bool] = []
    window.destroyed.connect(lambda *_: window_destroyed.append(True))
    events_before_release = tuple(events)
    _schedule_closed_mount_release(app=app, window=window)
    assert tuple(events) == events_before_release
    assert window_destroyed == []
