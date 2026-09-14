"""V2.1 product navigation through AppContext and real QML input.

The six-route host without research_shell remains the explicit legacy entry.
These tests use the previously agreed public composition and native UI seams.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QAccessible, QFont, QFontDatabase
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.app_context import build_app_context
from app.features import (
    FormalDiagnosticCampaignId, RunMonitoringContext, RunMonitoringSelection,
    StrategyRunId,
)
from app.journey_recovery import JourneyWorkspaceBookmark, JourneyWorkspaceRoute
from app.ui.journey_workspace import JourneyWorkspaceHost
from app.ui.main_window import MainWindow
from app.ui.accessibility import AccessibilityPreferences
from tests.frontend.contract.test_strategy_asset_queries_feature import composed

EXACT_RUN_CONTEXT = RunMonitoringContext.for_run(RunMonitoringSelection(
    campaign_id=FormalDiagnosticCampaignId("RESEARCH-CAMPAIGN-EXACT"),
    run_id=StrategyRunId("RESEARCH-RUN-EXACT"),
))


@pytest.fixture
def research_host(tmp_path, monkeypatch, request):
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    app = QApplication.instance() or QApplication([])
    if not QFontDatabase.families():
        # Isolated offscreen runs lack system font enumeration. Use the same
        # existing CJK font as the other QML fixtures, within this process only.
        assert QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc") >= 0
        app.setFont(QFont("Microsoft YaHei UI", 10))
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake", runtime_gateway=object(),
    )
    host = None
    try:
        requested = getattr(request, "param", {})
        options = requested if isinstance(requested, dict) else {"context": requested}
        host = JourneyWorkspaceHost(
            context.run_monitoring_feature,
            context=options.get("context", context.run_monitoring_context),
            journey_workspace_bookmark=options.get("bookmark"),
            strategy_library_feature=context.strategy_library_feature,
            strategy_library_context=context.strategy_library_context,
            strategy_library_queries=context.strategy_library_queries,
            feature_capabilities=context.feature_capabilities(),
            scenario_lab_feature=context.scenario_lab_feature,
            scenario_lab_context=context.scenario_lab_context,
            diagnostic_tasks_feature=context.diagnostic_tasks_feature,
            diagnostic_tasks_context=context.diagnostic_tasks_context,
            diagnostic_setup_selection_coordinator=context.diagnostic_setup_selection_coordinator,
            evidence_feature=context.evidence_and_findings_feature,
            evidence_context=context.evidence_and_findings_context,
            system_health_feature=(
                context.system_health_feature if options.get("health_available", True) else None
            ),
            system_health_context=context.system_health_context,
            initial_route=options.get("initial_route", "strategy_library"),
            accessibility_preferences=AccessibilityPreferences(
                text_scale=options.get("text_scale", 1.0), reduced_motion=True,
            ),
            research_shell=True,
        )
        host.resize(*options.get("size", (1426, 786)))
        host.show()
        QTest.qWait(60)
        yield app, context, host
    finally:
        if host is not None:
            host.close_adapter()
            host.close()
            host.deleteLater()
        context.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def visual_items(root):
    yield root
    for child in root.childItems():
        yield from visual_items(child)


def test_four_primary_pages_are_keyboard_operable_without_health_destination(research_host):
    _, _, host = research_host
    root = host.rootObject()
    navigation = [item for item in visual_items(root)
                  if item.property("primaryDestination") is True]
    assert [item.property("text") for item in navigation] == [
        "组合库", "场景库", "实验室", "实验档案",
    ]
    expected = [JourneyWorkspaceRoute.STRATEGY_LIBRARY,
                JourneyWorkspaceRoute.SCENARIO_LAB,
                JourneyWorkspaceRoute.DIAGNOSTIC_TASKS,
                JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS]
    for button, route in zip(navigation, expected, strict=True):
        assert button.isVisible() and button.isEnabled()
        button.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        QTest.qWait(20)
        assert host.active_route is route
    health = root.findChild(QQuickItem, "researchHealthButton")
    assert health is not None and health.isVisible()
    assert health not in navigation


@pytest.mark.parametrize("route", [
    "strategy_library", "scenario_lab", "diagnostic_tasks", "evidence_and_findings",
])
def test_page_status_and_heading_expose_their_visible_accessible_names(research_host, route):
    _, _, host = research_host
    assert host.activate_route(JourneyWorkspaceRoute(route))
    QTest.qWait(40)
    messages = []
    for item in visual_items(host.rootObject()):
        if not item.isVisible() or not item.property("text"):
            continue
        interface = QAccessible.queryAccessibleInterface(item)
        if interface is not None and interface.role() in (
            QAccessible.Role.StatusBar, QAccessible.Role.Heading,
        ):
            messages.append((interface.role(), item.property("text"),
                             interface.text(QAccessible.Text.Name)))
    assert {role for role, _, _ in messages} == {
        QAccessible.Role.StatusBar, QAccessible.Role.Heading,
    }
    assert all(name == message for _, message, name in messages), messages


def test_health_overlay_heading_exposes_its_visible_accessible_name(research_host):
    _, _, host = research_host
    assert host.activate_route(JourneyWorkspaceRoute.SYSTEM_HEALTH)
    QTest.qWait(40)
    headings = []
    for item in visual_items(host.quickWindow().contentItem()):
        if not item.isVisible() or item.property("text") != "系统状态":
            continue
        interface = QAccessible.queryAccessibleInterface(item)
        if interface is not None and interface.role() is QAccessible.Role.Heading:
            headings.append(interface.text(QAccessible.Text.Name))
    assert headings == ["系统状态"]


def test_combination_details_expose_readonly_state_and_allow_keyboard_reading(research_host):
    _, _, host = research_host
    details = host.rootObject().findChild(QQuickItem, "researchAssetDetails")
    interface = QAccessible.queryAccessibleInterface(details)
    assert interface is not None and interface.state().readOnly
    details.forceActiveFocus()
    original = details.property("text")
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_X)
    assert details.property("text") == original
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
    assert details.property("cursorPosition") == len(original)


@pytest.mark.parametrize("research_host", [
    {"context": EXACT_RUN_CONTEXT, "size": size, "text_scale": scale}
    for size in ((960, 480), (960, 540), (1426, 786), (2600, 1400))
    for scale in (1.0, 2.0)
], indirect=True)
def test_legacy_run_route_observes_exact_run_instead_of_inactive_task_summary(research_host, record_property):
    _, context, host = research_host
    selection = EXACT_RUN_CONTEXT.selection
    assert selection is not None and selection.run_id is not None
    context.run_monitoring_feature.advance_to_running(EXACT_RUN_CONTEXT)
    assert host.activate_route(JourneyWorkspaceRoute.RUN_MONITORING)
    QTest.qWait(50)
    summary = host.rootObject().findChild(QQuickItem, "researchExistingResourceSummary")
    assert summary.isVisible()
    assert selection.run_id.value in summary.property("text")
    assert "running" in summary.property("text")
    assert "2 / 10" in summary.property("text")
    interface = QAccessible.queryAccessibleInterface(summary)
    assert interface is not None and interface.isValid()
    assert interface.role() is QAccessible.Role.EditableText
    assert interface.text(QAccessible.Text.Name) == "当前兼容资源状态"
    assert selection.run_id.value in interface.text(QAccessible.Text.Value)
    assert interface.state().readOnly
    summary.forceActiveFocus()
    original_text = summary.property("text")
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_X)
    assert summary.property("text") == original_text
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
    QTest.qWait(30)
    assert summary.hasActiveFocus()
    assert summary.property("cursorPosition") == len(summary.property("text"))
    cursor = summary.mapRectToScene(summary.property("cursorRectangle"))
    assert cursor.top() >= 0 and cursor.bottom() <= host.height()
    record_property("logical_client", f"{host.width()}x{host.height()}")
    record_property("dpr", host.devicePixelRatioF())
    record_property("text_scale", host.rootObject().findChild(QObject, "designTokens").property("textScale"))
    record_property("renderer", host.quickWindow().rendererInterface().graphicsApi().name)
    context.run_monitoring_feature.advance_to_completed(EXACT_RUN_CONTEXT)
    QTest.qWait(50)
    assert selection.run_id.value in summary.property("text")
    assert "completed" in summary.property("text")


@pytest.mark.parametrize("research_host", [EXACT_RUN_CONTEXT], indirect=True)
def test_legacy_health_entry_overlays_the_observed_run_without_replacing_it(research_host):
    _, context, host = research_host
    context.run_monitoring_feature.advance_to_running(EXACT_RUN_CONTEXT)
    assert host.activate_route(JourneyWorkspaceRoute.RUN_MONITORING)
    QTest.qWait(30)
    root = host.rootObject()
    assert host.activate_route(JourneyWorkspaceRoute.SYSTEM_HEALTH)
    QTest.qWait(30)
    popup = root.findChild(QObject, "researchHealthPopup")
    assert host.active_route is JourneyWorkspaceRoute.RUN_MONITORING
    assert popup.property("opened") is True
    # Completion arrives while the legacy health entry is open. Observation of
    # this exact run must continue; opening health is not a page replacement.
    context.run_monitoring_feature.advance_to_completed(EXACT_RUN_CONTEXT)
    QTest.qWait(30)
    summary = root.findChild(QQuickItem, "researchExistingResourceSummary")
    assert summary.isVisible()
    assert "RESEARCH-RUN-EXACT" in summary.property("text")
    assert "completed" in summary.property("text")
    assert host.journey_context.route is JourneyWorkspaceRoute.RUN_MONITORING
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Escape)
    QTest.qWait(30)
    assert popup.property("opened") is False
    assert root.findChild(QQuickItem, "researchHealthButton").hasActiveFocus()
    assert host.active_route is JourneyWorkspaceRoute.RUN_MONITORING


@pytest.mark.parametrize("research_host,expected", [
    ({"initial_route": "system_health", "bookmark": JourneyWorkspaceBookmark(
        last_route=JourneyWorkspaceRoute.SYSTEM_HEALTH)}, JourneyWorkspaceRoute.STRATEGY_LIBRARY),
    ({"initial_route": "system_health", "bookmark": JourneyWorkspaceBookmark(
        last_route=JourneyWorkspaceRoute.SCENARIO_LAB)}, JourneyWorkspaceRoute.SCENARIO_LAB),
], indirect=["research_host"])
def test_initial_health_entry_uses_saved_parent_or_explained_combination_fallback(
    research_host, expected,
):
    _, _, host = research_host
    root = host.rootObject()
    popup = root.findChild(QObject, "researchHealthPopup")
    assert host.active_route is expected
    assert host.journey_context.route is expected
    assert popup.property("opened") is True
    assert root.findChild(QQuickItem, "researchHealthCloseButton").hasActiveFocus()
    if expected is JourneyWorkspaceRoute.STRATEGY_LIBRARY:
        assert "原页面" in host.recovery_state.explanation
        assert "组合库" in host.recovery_state.explanation
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Escape)
    QTest.qWait(30)
    assert popup.property("opened") is False
    assert root.findChild(QQuickItem, "researchHealthButton").hasActiveFocus()
    # A later hide/show does not replay the migrated startup action.
    host.hide()
    host.show()
    QTest.qWait(40)
    assert popup.property("opened") is False
    assert host.active_route is expected


@pytest.mark.parametrize("research_host", [
    {"initial_route": "system_health", "health_available": False,
     "bookmark": JourneyWorkspaceBookmark(last_route=JourneyWorkspaceRoute.SYSTEM_HEALTH)},
    {"initial_route": "system_health", "health_available": False,
     "bookmark": JourneyWorkspaceBookmark(last_route=JourneyWorkspaceRoute.SCENARIO_LAB)},
], indirect=True)
def test_initial_missing_health_explains_its_unavailability_even_with_a_safe_parent(research_host):
    _, _, host = research_host
    root = host.rootObject()
    assert host.active_route is not JourneyWorkspaceRoute.SYSTEM_HEALTH
    assert root.findChild(QObject, "researchHealthPopup").property("opened") is False
    assert host.recovery_state.reason.value != "exact"
    assert "系统状态观察不可用" in host.recovery_state.explanation
    assert "已映射" not in host.recovery_state.explanation
    assert root.property("routeRecoveryMessage") == host.recovery_state.explanation
    assert root.findChild(QQuickItem, "researchHealthButton").isVisible()


@pytest.mark.parametrize("research_host", [
    {"size": (960, 480), "text_scale": 2.0},
    {"size": (1426, 786), "text_scale": 1.0},
], indirect=True)
def test_health_overlay_supports_readonly_keyboard_reading_and_modal_focus(
    research_host, record_property,
):
    _, _, host = research_host
    assert host.activate_route(JourneyWorkspaceRoute.SYSTEM_HEALTH)
    QTest.qWait(30)
    root = host.rootObject()
    facts = root.findChild(QQuickItem, "researchHealthFacts")
    close = root.findChild(QQuickItem, "researchHealthCloseButton")
    assert close.hasActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Tab)
    assert facts.hasActiveFocus()
    assert QAccessible.queryAccessibleInterface(facts).state().readOnly
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
    QTest.qWait(30)
    assert facts.property("cursorPosition") == len(facts.property("text"))
    cursor = facts.property("cursorRectangle")
    bottom = facts.mapToScene(QPointF(cursor.x(), cursor.bottom())).y()
    assert 0 < bottom <= host.height()
    scale = root.findChild(QObject, "designTokens").property("textScale")
    record_property("logical_client", f"{host.width()}x{host.height()}")
    record_property("dpr", host.devicePixelRatioF())
    record_property("text_scale", scale)
    record_property("keyboard_text_end_visible", True)
    if evidence_dir := os.environ.get("STOCKSIM_QML_EVIDENCE_DIR"):
        destination = Path(evidence_dir)
        destination.mkdir(parents=True, exist_ok=True)
        frame = host.grabFramebuffer()
        assert not frame.isNull()
        assert frame.save(str(destination / f"health-keyboard-{host.width()}x{host.height()}-{scale}.png"))
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Tab)
    assert close.hasActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Backtab)
    assert facts.hasActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Escape)
    QTest.qWait(30)
    assert root.findChild(QQuickItem, "researchHealthButton").hasActiveFocus()


def test_health_overlay_keeps_page_observation_and_returns_keyboard_focus(research_host):
    app, context, host = research_host
    # Runtime availability, admitted data revision and the aggregate observation
    # are independent source events. Unknown data must not become healthy merely
    # because the runtime becomes available.
    context.system_health_feature.advance_to_healthy()
    context.system_health_feature.deliver_data_source_revision(1)
    context.system_health_feature.publish_authoritative_observation()
    root = host.rootObject()
    assert host.activate_route(JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS)
    QTest.qWait(50)
    health = root.findChild(QQuickItem, "researchHealthButton")
    health.forceActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
    QTest.qWait(50)
    popup = root.findChild(QObject, "researchHealthPopup")
    assert popup is not None and popup.property("opened") is True
    assert host.active_route is JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS
    facts = root.findChild(QQuickItem, "researchHealthFacts")
    assert facts is not None and facts.property("readOnly") is True
    for heading in ("运行时", "数据源", "队列", "缓存", "持久化", "版本兼容"):
        assert heading in facts.property("text")
    for _ in range(100):
        app.processEvents()
        if host.accessibility_snapshot().system_health_freshness == "fresh":
            break
        QTest.qWait(20)
    assert host.accessibility_snapshot().system_health_freshness == "fresh"
    facts.forceActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Escape)
    QTest.qWait(30)
    assert popup.property("opened") is False
    assert health.hasActiveFocus()
    assert host.active_route is JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS


@pytest.mark.parametrize("size,scale", [((1426, 786), 1.0), ((960, 480), 2.0)])
def test_combination_page_reads_the_same_exact_application_asset_in_both_layouts(
    composed, size, scale, record_property,
):
    app = QApplication.instance()
    context, executor, _, inventory = composed
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        strategy_library_feature=context.strategy_library_feature,
        strategy_library_queries=context.strategy_library_queries,
        feature_capabilities=context.feature_capabilities(),
        initial_route="strategy_library", research_shell=True,
        accessibility_preferences=AccessibilityPreferences(text_scale=scale, reduced_motion=True),
    )
    host.resize(*size)
    host.show()
    try:
        app.processEvents()
        root = host.rootObject()
        # Opening the actual page, not a debug action, starts the catalog read.
        assert context.strategy_library_queries.snapshot().phase.value == "loading"
        executor.run_next()
        app.processEvents()
        app.processEvents()
        catalog = root.findChild(QQuickItem, "researchAssetList")
        assert catalog is not None and catalog.property("count") == len(inventory.entries)
        toggle = root.findChild(QQuickItem, "researchAssetListButton")
        if toggle.isVisible():
            toggle.forceActiveFocus()
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        catalog.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Down)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        QTest.qWait(20)
        query = root.findChild(QQuickItem, "researchAssetReadButton")
        assert query.isEnabled() and query.isVisible()
        query.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        executor.run_next()
        app.processEvents()
        app.processEvents()
        observed = context.strategy_library_queries.snapshot()
        target = observed.request.target
        exact = next(entry for entry in inventory.entries
                     if entry.strategy_id == target.lineage_id)
        assert observed.result.asset.strategy_version == exact.strategy_version
        details = root.findChild(QQuickItem, "researchAssetDetails")
        assert target.content_hash in details.property("text")
        assert target.version_id in details.property("text")
        assert details.property("readOnly") is True
        assert "不会自动生成因子或组合" in details.property("text")
        interface = QAccessible.queryAccessibleInterface(details)
        assert interface is not None and interface.state().readOnly
        assert target.content_hash in interface.text(QAccessible.Text.Value)
        details.forceActiveFocus()
        original_text = details.property("text")
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_X)
        assert details.property("text") == original_text
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
        QTest.qWait(30)
        assert details.hasActiveFocus()
        assert details.property("cursorPosition") == len(original_text)
        cursor = details.mapRectToScene(details.property("cursorRectangle"))
        assert cursor.top() >= 0 and cursor.bottom() <= host.height()
        record_property("logical_client", f"{host.width()}x{host.height()}")
        record_property("dpr", host.devicePixelRatioF())
        record_property("text_scale", scale)
        if evidence_dir := os.environ.get("STOCKSIM_QML_EVIDENCE_DIR"):
            destination = Path(evidence_dir)
            destination.mkdir(parents=True, exist_ok=True)
            kind = observed.source_kind.value
            QTest.qWait(60)
            app.processEvents()
            assert host.grab().save(str(destination / f"research-{kind}-{size[0]}x{size[1]}-text{scale}.png"))
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("composed,failed", [(("fake", "empty"), False), ("live", True), ("fake", True)], indirect=["composed"])
def test_combination_page_explains_empty_or_failed_source_without_enabling_a_read(composed, failed):
    app = QApplication.instance()
    context, executor, _, _ = composed
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        strategy_library_feature=context.strategy_library_feature,
        strategy_library_queries=context.strategy_library_queries,
        feature_capabilities=context.feature_capabilities(),
        initial_route="strategy_library", research_shell=True,
    )
    host.resize(960, 480)
    host.show()
    try:
        app.processEvents()


        root = host.rootObject()
        assert not root.findChild(QQuickItem, "researchAssetReadButton").isEnabled()
        if failed:
            executor.fail_next()
        else:
            executor.run_next()
        app.processEvents()
        app.processEvents()
        visible_text = "\n".join(str(item.property("text") or "") for item in visual_items(root))
        assert ("读取受限" if failed else "没有可读取的旧策略资产") in visible_text
        assert "private-source-path" not in visible_text
        assert not root.findChild(QQuickItem, "researchAssetReadButton").isEnabled()
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_same_window_reflow_keeps_list_focus_visible_and_preserves_exact_selection(composed):
    app = QApplication.instance()
    context, executor, _, _ = composed
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        strategy_library_feature=context.strategy_library_feature,
        strategy_library_queries=context.strategy_library_queries,
        feature_capabilities=context.feature_capabilities(),
        initial_route="strategy_library", research_shell=True,
    )
    host.resize(1426, 786)
    host.show()
    try:
        app.processEvents()
        executor.run_next()
        QTest.qWait(50)
        root = host.rootObject()
        catalog = root.findChild(QQuickItem, "researchAssetList")
        drawer = root.findChild(QObject, "researchAssetListDrawer")
        toggle = root.findChild(QQuickItem, "researchAssetListButton")
        query = root.findChild(QQuickItem, "researchAssetReadButton")
        catalog.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Down)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
        selected_index = catalog.property("currentIndex")
        expected = context.strategy_library_queries.snapshot().assets[selected_index].reference
        catalog.forceActiveFocus()
        assert catalog.hasActiveFocus()

        host.resize(960, 480)
        QTest.qWait(50)
        assert drawer.property("opened") is True
        assert catalog.isVisible() and catalog.hasActiveFocus()
        assert catalog.property("currentIndex") == selected_index

        host.resize(1426, 786)
        QTest.qWait(50)
        assert drawer.property("opened") is False
        assert catalog.isVisible() and catalog.hasActiveFocus()
        host.resize(960, 480)
        QTest.qWait(50)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Escape)
        QTest.qWait(30)
        assert drawer.property("opened") is False
        assert toggle.isVisible() and toggle.hasActiveFocus()
        assert query.isEnabled()
        query.forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        executor.run_next()
        app.processEvents()
        assert context.strategy_library_queries.snapshot().result.request.target == expected

        # Resizing a focused detail must not steal focus into the object drawer.
        details = root.findChild(QQuickItem, "researchAssetDetails")
        details.forceActiveFocus()
        host.resize(1426, 786)
        QTest.qWait(30)
        host.resize(960, 480)
        QTest.qWait(30)
        assert drawer.property("opened") is False
        assert details.hasActiveFocus()
    finally:
        host.close_adapter()
        host.close()
        host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("research_shell", [True, False])
def test_opt_in_health_restore_does_not_overwrite_legacy_bookmark_sink(
    composed, tmp_path, research_shell,
):
    app = QApplication.instance()
    context, _, _, _ = composed
    original = JourneyWorkspaceBookmark(last_route=JourneyWorkspaceRoute.SYSTEM_HEALTH)
    saved = []
    window = MainWindow(
        run_monitoring_feature=context.run_monitoring_feature,
        strategy_library_feature=context.strategy_library_feature,
        strategy_library_queries=context.strategy_library_queries,
        feature_capabilities=context.feature_capabilities(),
        system_health_feature=context.system_health_feature,
        journey_workspace_bookmark=original,
        journey_workspace_bookmark_sink=saved.append,
        frontend_v2_enabled=True, research_shell=research_shell,
        layout_path=str(tmp_path / "layout.json"),
    )
    try:
        window.resize(960, 480)
        window.show()
        QTest.qWait(50)
        host = window.centralWidget()
        if research_shell:
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Escape)
        assert host.activate_route(JourneyWorkspaceRoute.RUN_MONITORING)
        assert host.activate_route(JourneyWorkspaceRoute.STRATEGY_LIBRARY)
        QTest.qWait(30)
    finally:
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    assert original.last_route is JourneyWorkspaceRoute.SYSTEM_HEALTH
    if research_shell:
        assert saved == []
    else:
        assert saved and saved[-1].last_route is JourneyWorkspaceRoute.STRATEGY_LIBRARY


def test_main_window_can_compose_research_shell_without_legacy_minimum_height(composed, tmp_path):
    app = QApplication.instance()
    context, executor, _, _ = composed
    window = MainWindow(
        run_monitoring_feature=context.run_monitoring_feature,
        strategy_library_feature=context.strategy_library_feature,
        strategy_library_queries=context.strategy_library_queries,
        feature_capabilities=context.feature_capabilities(),
        frontend_v2_enabled=True, research_shell=True,
        layout_path=str(tmp_path / "layout.json"),
    )
    try:
        window.resize(960, 480)
        window.show()
        app.processEvents()
        host = window.centralWidget()
        assert host.rootObject().objectName() == "researchWorkspace"
        assert host.height() <= 480
        assert host.activate_route(JourneyWorkspaceRoute.STRATEGY_LIBRARY)
        executor.run_next()
        app.processEvents()
        assert context.strategy_library_queries.snapshot().assets
    finally:
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
