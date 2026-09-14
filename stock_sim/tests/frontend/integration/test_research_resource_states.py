"""Truthful empty/wait/error states through real application and product QML."""

import os
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QAccessible, QFont, QFontDatabase
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError

from app.app_context import build_app_context
from app.event_bridge import EventBridge
from app.features import LiveStrategyDiagnosticsV1ApplicationAdapter
from app.features.run_monitoring import Completeness, Freshness
from app.ui.journey_workspace import JourneyWorkspaceHost
from app.ui.accessibility import AccessibilityPreferences
from strategy_diagnostics import create_diagnostics_application
from tests.frontend.integration.test_research_resource_pages import until


def record_frame(host, name, record_property):
    QTest.qWait(40)
    record_property("logical_client", f"{host.width()}x{host.height()}")
    record_property("dpr", host.devicePixelRatioF())
    record_property("renderer", host.quickWindow().rendererInterface().graphicsApi().name)
    if evidence_dir := os.environ.get("STOCKSIM_QML_EVIDENCE_DIR"):
        destination = Path(evidence_dir)
        destination.mkdir(parents=True, exist_ok=True)
        assert host.grabFramebuffer().save(str(destination / f"{name}.png"))


@pytest.fixture
def empty_live_context(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    app = QApplication.instance() or QApplication([])
    if not QFontDatabase.families():
        assert QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc") >= 0
        app.setFont(QFont("Microsoft YaHei UI", 10))
    engine = create_engine(f"sqlite:///{tmp_path.as_posix()}/empty-research.sqlite",
                           connect_args={"check_same_thread": False})
    application = create_diagnostics_application()
    application.initialize_persistence(engine)
    bridge = EventBridge(subscribe_backend=False)
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"), run_monitoring_mode="live",
        strategy_diagnostics_application=application,
        strategy_diagnostics_read_model=LiveStrategyDiagnosticsV1ApplicationAdapter(application, engine),
        event_bridge=bridge, system_health_sampling_interval=None,
    )
    try:
        yield app, context, engine
    finally:
        context.close()
        bridge.stop()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        engine.dispose()


@pytest.mark.parametrize("size", [(960, 480), (960, 540), (1426, 786), (2600, 1400)])
@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_scenario_empty_message_requires_a_real_fresh_read(empty_live_context, size, scale, record_property):
    app, context, _ = empty_live_context
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature, scenario_lab_feature=context.scenario_lab_feature,
        scenario_lab_context=context.scenario_lab_context,
        initial_route="scenario_lab", research_shell=True,
        accessibility_preferences=AccessibilityPreferences(text_scale=scale, reduced_motion=True),
    )
    host.resize(*size)
    host.show()
    try:
        page = host.rootObject().findChild(QQuickItem, "researchScenarioPage")
        until(app, lambda: page.property("adapter").property("freshness") == "fresh")
        state = context.scenario_lab_feature.snapshot(context.scenario_lab_context)
        assert state.freshness is Freshness.FRESH
        assert state.completeness is Completeness.EMPTY
        assert state.source_revision is not None
        assert state.market_scenarios == ()
        assert state.approved_recipe_versions == ()
        assert state.recipe_drafts == ()
        catalog = host.rootObject().findChild(QQuickItem, "researchScenarioPageList")
        assert catalog.property("count") == 0
        details = host.rootObject().findChild(QQuickItem, "researchScenarioPageDetails")
        assert "当前没有可读取的旧场景、已批准版本或草稿" in details.property("text")
        interface = QAccessible.queryAccessibleInterface(details)
        assert interface is not None and interface.isValid()
        assert interface.role() is QAccessible.Role.EditableText
        assert interface.state().readOnly
        assert "精确资源详情" in interface.text(QAccessible.Text.Name)
        details.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
        assert details.hasActiveFocus() and details.property("readOnly")
        record_property("text_scale", scale)
        record_property("source_revision", state.source_revision.value)
        record_property("source_generation", state.source.generation.value)
        record_property("source_kind", state.source.kind.value)
        record_property("phase", state.phase.value)
        record_property("freshness", state.freshness.value)
        record_property("completeness", state.completeness.value)
        record_frame(host, f"scenario-empty-{size[0]}x{size[1]}-text{scale}", record_property)
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_initial_database_failure_is_not_reported_as_empty_and_can_recover(empty_live_context, scale, record_property):
    app, context, engine = empty_live_context
    host = None
    fault_installed = True

    def fail_read(connection, cursor, statement, parameters, execution_context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            raise OperationalError(statement, parameters, RuntimeError("private-empty-database-location"))

    event.listen(engine, "before_cursor_execute", fail_read)
    try:
        host = JourneyWorkspaceHost(
            context.run_monitoring_feature, scenario_lab_feature=context.scenario_lab_feature,
            strategy_library_feature=context.strategy_library_feature,
            strategy_library_queries=context.strategy_library_queries,
            feature_capabilities=context.feature_capabilities(),
            initial_route="scenario_lab", research_shell=True,
            accessibility_preferences=AccessibilityPreferences(text_scale=scale, reduced_motion=True),
        )
        host.resize(960, 480)
        host.show()
        root = host.rootObject()
        details = root.findChild(QQuickItem, "researchScenarioPageDetails")
        until(app, lambda: "场景资源观察暂不可用" in details.property("text"))
        assert "当前没有可读取" not in details.property("text")
        assert "private-empty-database-location" not in details.property("text")
        assert "重新进入场景库重试" in details.property("text")
        record_property("text_scale", scale)
        record_frame(host, f"scenario-unavailable-960x480-text{scale}", record_property)
        event.remove(engine, "before_cursor_execute", fail_read)
        fault_installed = False
        for name, route in (("strategyLibraryRouteNavigation", "strategy_library"),
                            ("scenarioLabRouteNavigation", "scenario_lab")):
            button = root.findChild(QQuickItem, name)
            assert button.isEnabled()
            button.forceActiveFocus()
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
            assert host.active_route.value == route
        until(app, lambda: "当前没有可读取的旧场景、已批准版本或草稿" in details.property("text"))
        state = context.scenario_lab_feature.snapshot(context.scenario_lab_context)
        assert state.freshness is Freshness.FRESH
        assert state.error is None and state.market_scenarios == ()
    finally:
        if fault_installed:
            event.remove(engine, "before_cursor_execute", fail_read)
        if host is not None:
            host.close_adapter()
            host.close()
            host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("route,page_name,expected", [
    ("diagnostic_tasks", "researchLabPage", "尚未选择旧任务"),
    ("evidence_and_findings", "researchArchivePage", "尚未选择旧运行的证据"),
])
@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_no_selection_does_not_claim_the_library_is_empty(empty_live_context, route, page_name, expected, scale, record_property):
    app, context, _ = empty_live_context
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        diagnostic_tasks_feature=context.diagnostic_tasks_feature,
        diagnostic_tasks_context=context.diagnostic_tasks_context,
        evidence_feature=context.evidence_and_findings_feature,
        evidence_context=context.evidence_and_findings_context,
        initial_route=route, research_shell=True,
        accessibility_preferences=AccessibilityPreferences(text_scale=scale, reduced_motion=True),
    )
    host.resize(960, 480)
    host.show()
    try:
        assert context.diagnostic_tasks_context.task_id is None
        assert context.evidence_and_findings_context.selection is None
        page = host.rootObject().findChild(QQuickItem, page_name)
        until(app, lambda: page.property("adapter").property("freshness") == "fresh")
        catalog = host.rootObject().findChild(QQuickItem, page_name + "List")
        assert catalog.property("count") == 0
        details = host.rootObject().findChild(QQuickItem, page_name + "Details")
        assert expected in details.property("text")
        assert "当前没有可读取的资源" not in details.property("text")
        details.forceActiveFocus()
        assert details.hasActiveFocus() and details.property("readOnly")
        record_property("text_scale", scale)
        record_frame(host, f"{page_name}-no-selection-960x480-text{scale}", record_property)
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
