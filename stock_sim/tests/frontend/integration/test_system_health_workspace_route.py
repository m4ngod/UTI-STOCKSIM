from __future__ import annotations

import gc
import os
from pathlib import Path
from types import SimpleNamespace
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.app_context import build_app_context
from app.event_bridge import EventBridge
from app.features import (
    DeterministicFakeRunMonitoringAdapter,
    DeterministicFakeSystemHealthAdapter,
    LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
    LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter,
    LiveSystemHealthAdapter,
    StrategyDiagnosticsV1ApplicationReadModel,
    SystemHealthContext,
    SystemHealthFeature,
    diagnostics_application_identity,
)
from app.journey_recovery import JourneyWorkspaceBookmark, JourneyWorkspaceRoute
from app.ui.main_window import MainWindow
from strategy_diagnostics import create_diagnostics_application


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _release_closed_qml_hosts_between_tests():
    yield
    application = QApplication.instance()
    if application is None:
        return
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()
    gc.collect()


def _visible_text(root: QObject) -> str:
    return " ".join(
        str(item.property("text"))
        for item in root.findChildren(QObject)
        if item.metaObject().indexOfProperty("text") >= 0
        and item.property("visible")
        and item.property("text")
    )


def test_app_context_composes_system_health_as_the_sixth_feature(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        runtime_gateway=object(),
    )
    try:
        assert isinstance(context.system_health_feature, SystemHealthFeature)
        assert context.system_health_feature.interface_version.render() == "1.0"
        assert context.system_health_context == SystemHealthContext()
    finally:
        context.strategy_library_feature.close()
        context.scenario_lab_feature.close()
        context.diagnostic_tasks_feature.close()
        context.run_monitoring_feature.close()
        context.evidence_and_findings_feature.close()
        context.system_health_feature.close()


def test_live_app_context_uses_one_diagnostics_application_for_every_adapter(
    tmp_path,
    monkeypatch,
) -> None:
    app = _app()
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    context = build_app_context(
        settings_path=str(tmp_path / "live-settings.json"),
        run_monitoring_mode="live",
        event_bridge=EventBridge(subscribe_backend=False),
        runtime_gateway=object(),
    )
    window = None
    try:
        adapters = (
            context.strategy_diagnostics_read_model,
            context.strategy_diagnostics_tasks_application,
            context.strategy_diagnostics_library_application,
            context.strategy_diagnostics_scenario_lab_application,
            context.strategy_diagnostics_system_health_application,
        )
        canonical = context.strategy_diagnostics_application
        assert canonical is not None
        expected_identity = diagnostics_application_identity(canonical)
        assert {
            adapter.application_identity for adapter in adapters
        } == {expected_identity}
        assert isinstance(context.system_health_feature, LiveSystemHealthAdapter)

        window = MainWindow(
            strategy_library_feature=context.strategy_library_feature,
            strategy_library_context=context.strategy_library_context,
            scenario_lab_feature=context.scenario_lab_feature,
            scenario_lab_context=context.scenario_lab_context,
            diagnostic_tasks_feature=context.diagnostic_tasks_feature,
            diagnostic_tasks_context=context.diagnostic_tasks_context,
            diagnostic_setup_selection_coordinator=(
                context.diagnostic_setup_selection_coordinator
            ),
            run_monitoring_feature=context.run_monitoring_feature,
            run_monitoring_context=context.run_monitoring_context,
            evidence_and_findings_feature=(
                context.evidence_and_findings_feature
            ),
            evidence_and_findings_context=(
                context.evidence_and_findings_context
            ),
            system_health_feature=context.system_health_feature,
            system_health_context=context.system_health_context,
            journey_workspace_bookmark=JourneyWorkspaceBookmark(
                last_route=JourneyWorkspaceRoute.SYSTEM_HEALTH
            ),
            frontend_v2_enabled=True,
        )
        app.processEvents()
        root = window.centralWidget().rootObject()
        visible = _visible_text(root)

        assert root.property("activeRoute") == "system_health"
        assert root.findChild(QObject, "systemHealthPage") is not None
        status = root.findChild(QObject, "systemHealthAccessibleStatus")
        assert status is not None
        assert "healthy" in str(status.property("accessibleName")).casefold()
        assert "Application runtime" in visible
        assert "No infrastructure controls" in visible
    finally:
        if window is not None:
            window.close()
        context.strategy_library_feature.close()
        context.scenario_lab_feature.close()
        context.diagnostic_tasks_feature.close()
        context.run_monitoring_feature.close()
        context.evidence_and_findings_feature.close()
        context.system_health_feature.close()


def test_partial_live_composition_reuses_the_injected_diagnostics_application(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    diagnostics_application = create_diagnostics_application()
    diagnostics_application.start()
    tasks_application = (
        LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
            diagnostics_application
        )
    )
    context = build_app_context(
        settings_path=str(tmp_path / "partial-live-settings.json"),
        run_monitoring_mode="live",
        event_bridge=EventBridge(subscribe_backend=False),
        runtime_gateway=object(),
        strategy_diagnostics_application=diagnostics_application,
        strategy_diagnostics_read_model=cast(
            StrategyDiagnosticsV1ApplicationReadModel,
            SimpleNamespace(
                application_identity=diagnostics_application_identity(
                    diagnostics_application
                )
            ),
        ),
        strategy_diagnostics_tasks_application=tasks_application,
    )
    try:
        assert (
            context.strategy_diagnostics_application
            is diagnostics_application
        )
        health = context.system_health_feature.snapshot(SystemHealthContext())
        assert health.presentation.value == "healthy"
    finally:
        context.strategy_library_feature.close()
        context.scenario_lab_feature.close()
        context.diagnostic_tasks_feature.close()
        context.run_monitoring_feature.close()
        context.evidence_and_findings_feature.close()
        context.system_health_feature.close()


def test_partial_live_composition_requires_an_explicit_canonical_application(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")

    with pytest.raises(ValueError, match="explicit shared DiagnosticsApplication"):
        build_app_context(
            settings_path=str(tmp_path / "invalid-partial-settings.json"),
            run_monitoring_mode="live",
            event_bridge=EventBridge(subscribe_backend=False),
            runtime_gateway=object(),
            strategy_diagnostics_read_model=cast(
                StrategyDiagnosticsV1ApplicationReadModel,
                object(),
            ),
        )


def test_live_composition_rejects_an_adapter_owned_by_another_application(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    canonical = create_diagnostics_application()
    foreign = create_diagnostics_application()
    foreign.start()

    with pytest.raises(ValueError, match="does not belong"):
        build_app_context(
            settings_path=str(tmp_path / "mixed-ownership-settings.json"),
            run_monitoring_mode="live",
            event_bridge=EventBridge(subscribe_backend=False),
            runtime_gateway=object(),
            strategy_diagnostics_application=canonical,
            strategy_diagnostics_tasks_application=(
                LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
                    foreign
                )
            ),
        )


def test_system_health_timer_rereads_real_application_state() -> None:
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    diagnostics_application = create_diagnostics_application()
    health_feature = LiveSystemHealthAdapter(
        application_health=(
            LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
                diagnostics_application
            )
        ),
        event_bridge=EventBridge(subscribe_backend=False),
    )
    window = MainWindow(
        run_monitoring_feature=run_feature,
        system_health_feature=health_feature,
        system_health_context=SystemHealthContext(),
        journey_workspace_bookmark=JourneyWorkspaceBookmark(
            last_route=JourneyWorkspaceRoute.SYSTEM_HEALTH
        ),
        frontend_v2_enabled=True,
    )
    try:
        window.show()
        app.processEvents()
        root = window.centralWidget().rootObject()
        status = root.findChild(QObject, "systemHealthAccessibleStatus")
        assert status is not None
        assert "unknown" in str(status.property("accessibleName")).casefold()

        diagnostics_application.start()
        QTest.qWait(1100)
        app.processEvents()

        assert "healthy" in str(status.property("accessibleName")).casefold()
    finally:
        window.close()
        run_feature.close()
        health_feature.close()


def test_system_health_qml_surface_has_no_web_or_control_plane_imports() -> None:
    page = Path(__file__).parents[3] / "app" / "ui" / "qml" / "SystemHealthPage.qml"
    source = page.read_text(encoding="utf-8").casefold()

    for forbidden in (
        "webengine",
        "webview",
        "restart",
        "reconnect",
        "clear cache",
        "purge",
        "migrate",
        "buy",
        "sell",
        "broker",
        "submit order",
    ):
        assert forbidden not in source


def test_system_health_keyboard_focus_enters_and_leaves_the_read_only_page() -> None:
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    health_feature = DeterministicFakeSystemHealthAdapter(initially_healthy=True)
    window = MainWindow(
        run_monitoring_feature=run_feature,
        system_health_feature=health_feature,
        system_health_context=SystemHealthContext(),
        journey_workspace_bookmark=JourneyWorkspaceBookmark(
            last_route=JourneyWorkspaceRoute.SYSTEM_HEALTH
        ),
        frontend_v2_enabled=True,
    )
    try:
        host = window.centralWidget()
        window.show()
        app.processEvents()
        root = host.rootObject()
        status = root.findChild(QQuickItem, "systemHealthAccessibleStatus")
        route = root.findChild(QQuickItem, "systemHealthRouteNavigation")

        assert status is not None and route is not None
        assert status.property("activeFocus") is True
        QTest.keyClick(host, Qt.Key.Key_Backtab)
        app.processEvents()
        assert route.property("activeFocus") is True
        health_feature.publish_authoritative_observation()
        app.processEvents()
        assert route.property("activeFocus") is True
        QTest.keyClick(host, Qt.Key.Key_Return)
        app.processEvents()
        assert status.property("activeFocus") is True
    finally:
        window.close()
        run_feature.close()
        health_feature.close()
