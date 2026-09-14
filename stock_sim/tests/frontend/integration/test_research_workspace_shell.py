"""V2.1 product navigation through AppContext and real QML input.

The six-route host without research_shell remains the explicit legacy entry.
These tests use the previously agreed public composition and native UI seams.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.app_context import build_app_context
from app.journey_recovery import JourneyWorkspaceRoute
from app.ui.journey_workspace import JourneyWorkspaceHost
from app.ui.main_window import MainWindow
from app.ui.accessibility import AccessibilityPreferences
from tests.frontend.contract.test_strategy_asset_queries_feature import composed


@pytest.fixture
def research_host(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    app = QApplication.instance() or QApplication([])
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake", runtime_gateway=object(),
    )
    host = None
    try:
        host = JourneyWorkspaceHost(
            context.run_monitoring_feature,
            context=context.run_monitoring_context,
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
            system_health_feature=context.system_health_feature,
            system_health_context=context.system_health_context,
            initial_route="strategy_library", research_shell=True,
        )
        host.resize(1426, 786)
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
