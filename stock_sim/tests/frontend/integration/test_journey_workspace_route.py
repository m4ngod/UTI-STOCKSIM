import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QObject, QTimer
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication

import setup_frontend_entry as entry
from app.features import (
    DeterministicFakeRunMonitoringAdapter,
    RunMonitoringContext,
)
from app.ui.main_window import MainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


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
    assert tokens.property("durationForMotion") == 0

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
        lambda: SimpleNamespace(run_monitoring_feature=feature),
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
