"""Readable health summaries through public Feature updates and QML input."""

import os
from pathlib import Path

import pytest

from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtGui import QAccessible
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from app.journey_recovery import JourneyDiagnosticSelection, JourneyWorkspaceBookmark
from tests.frontend.contract.test_system_health_diagnostic_context_contract import _exact_context
from tests.frontend.integration.test_research_resource_pages import until
from tests.frontend.integration.test_research_workspace_shell import research_host


EXACT = _exact_context()
BOOKMARK = JourneyWorkspaceBookmark(diagnostic_selection=JourneyDiagnosticSelection(
    task_id=EXACT.task_id, task_revision=EXACT.task_revision,
    configuration_content_id=EXACT.configuration_content_id,
    task_handle_id=EXACT.task_handle_id, campaign_id=EXACT.campaign_id,
    campaign_revision=EXACT.campaign_revision, run_id=EXACT.run_id,
))


@pytest.fixture
def healthy_research_host(research_host):
    app, context, host = research_host
    popup = host.rootObject().findChild(QObject, "researchHealthPopup")
    # Runtime and data-source observations have independent delivery. A new
    # aggregate observation is required before both health and freshness hold.
    context.system_health_feature.advance_to_healthy()
    context.system_health_feature.deliver_data_source_revision(2)
    context.system_health_feature.publish_authoritative_observation()
    until(app, lambda: popup.property("adapter").property("overallClassification") == "healthy"
          and popup.property("adapter").property("freshness") == "fresh")
    return research_host


def test_health_header_explains_unavailable_persistence_and_freshness(healthy_research_host):
    app, context, host = healthy_research_host
    root = host.rootObject()
    button = root.findChild(QQuickItem, "researchHealthButton")
    popup = root.findChild(QObject, "researchHealthPopup")
    assert "正常" in button.property("text")
    assert "观察新鲜" in button.property("text")
    context.system_health_feature.advance_to_unavailable()
    until(app, lambda: popup.property("adapter").property("persistenceClassification") == "unavailable")
    assert "持久化不可用" in button.property("text")
    assert "观察新鲜" in button.property("text")
    assert "未关联任务" in button.property("text")
    assert button.isVisible() and button.isEnabled()
    accessible = QAccessible.queryAccessibleInterface(button)
    assert accessible.role() == QAccessible.Role.Button
    assert "持久化" in accessible.text(QAccessible.Text.Name)
    assert "观察新鲜" in accessible.text(QAccessible.Text.Name)


@pytest.mark.parametrize("research_host", [{"bookmark": BOOKMARK}], indirect=True)
def test_header_names_the_scope_of_the_current_impact(healthy_research_host):
    app, context, host = healthy_research_host
    root = host.rootObject()
    popup = root.findChild(QObject, "researchHealthPopup")
    context.system_health_feature.advance_to_unavailable()
    until(app, lambda: popup.property("adapter").property("persistenceClassification") == "unavailable")
    button = root.findChild(QQuickItem, "researchHealthButton")
    assert "持久化不可用" in button.property("text")
    assert "影响旧任务" in button.property("text")
    assert "运行" in button.property("text")


@pytest.mark.parametrize("research_host", [{"bookmark": BOOKMARK, "text_scale": 2.0}], indirect=True)
def test_long_header_reflows_and_keeps_full_accessible_scope_and_focus(healthy_research_host, record_property):
    app, context, host = healthy_research_host
    root = host.rootObject()
    popup = root.findChild(QObject, "researchHealthPopup")
    context.system_health_feature.advance_to_unavailable()
    until(app, lambda: popup.property("adapter").property("persistenceClassification") == "unavailable")
    button = root.findChild(QQuickItem, "researchHealthButton")
    original_route = host.active_route
    button.forceActiveFocus()
    for width, height in ((960, 480), (3840, 2160), (960, 540)):
        host.resize(width, height)
        QTest.qWait(30)
        assert button.hasActiveFocus()
        assert button.mapToScene(QPointF(0, 0)).x() >= 0
        assert button.mapToScene(QPointF(button.width(), button.height())).x() <= host.width()
        label = next(item for item in button.childItems() if item.property("text") == button.property("text"))
        assert label.mapToScene(QPointF(0, 0)).x() >= 0
        assert label.mapToScene(QPointF(label.width(), label.height())).x() <= host.width()
        accessible = QAccessible.queryAccessibleInterface(button)
        assert "持久化不可用" in accessible.text(QAccessible.Text.Name)
        assert "影响旧任务、任务进度、实验批次、运行" in accessible.text(QAccessible.Text.Name)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        QTest.qWait(20)
        assert popup.property("opened") and host.active_route == original_route
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Escape)
        QTest.qWait(20)
        assert button.hasActiveFocus() and not popup.property("opened")
        record_property(f"client_{width}x{height}", f"{host.width()}x{host.height()}@{host.devicePixelRatioF()}")
        if evidence_dir := os.environ.get("STOCKSIM_QML_EVIDENCE_DIR"):
            frame = host.grabFramebuffer()
            assert frame.save(str(Path(evidence_dir) / f"health-header-{width}x{height}-2.0.png"))


def test_header_does_not_call_an_unavailable_cache_normal(healthy_research_host):
    app, context, host = healthy_research_host
    root = host.rootObject()
    popup = root.findChild(QObject, "researchHealthPopup")
    context.system_health_feature.advance_cache_to_unavailable()
    until(app, lambda: popup.property("adapter").property("cacheClassification") == "unavailable")
    text = root.findChild(QQuickItem, "researchHealthButton").property("text")
    assert "系统状态 · 不可用" in text
    assert "缓存不可用" in text
    assert "正常" not in text


@pytest.mark.parametrize("research_host", [{"bookmark": BOOKMARK}], indirect=True)
def test_paused_queue_and_failed_task_are_not_labelled_as_system_faults(healthy_research_host):
    app, context, host = healthy_research_host
    root = host.rootObject()
    popup = root.findChild(QObject, "researchHealthPopup")
    button = root.findChild(QQuickItem, "researchHealthButton")
    context.system_health_feature.advance_queue_to_blocked()
    until(app, lambda: popup.property("adapter").property("queueClassification") == "degraded")
    assert "受限" in button.property("text")
    assert "不可用" not in button.property("text")
    context.system_health_feature.advance_to_healthy()
    context.system_health_feature.advance_context_to_failed()
    until(app, lambda: popup.property("adapter").property("diagnosticContextResolution") == "failed")
    assert "关联任务失败" in button.property("text")
    assert "系统故障" not in button.property("text")
    assert host.active_route.value == "strategy_library"


def test_partial_recovery_without_reliable_freshness_is_not_presented_as_normal(research_host):
    app, context, host = research_host
    root = host.rootObject()
    popup = root.findChild(QObject, "researchHealthPopup")
    context.system_health_feature.advance_to_healthy()
    context.system_health_feature.deliver_data_source_revision(2)
    until(app, lambda: popup.property("adapter").property("overallClassification") == "healthy")
    assert popup.property("adapter").property("freshness") == "awaiting_first_state"
    text = root.findChild(QQuickItem, "researchHealthButton").property("text")
    assert "系统状态 · 正常" not in text
    assert "尚无可靠观察" in text
    assert "未发现系统限制" not in text
