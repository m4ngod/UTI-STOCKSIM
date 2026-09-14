"""Per-group health evidence through public Feature observations and actual QML."""

from datetime import timedelta
import os
from pathlib import Path

import pytest

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAccessible
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from tests.frontend.integration.test_research_health_summary import BOOKMARK, healthy_research_host
from tests.frontend.integration.test_research_workspace_shell import research_host
from tests.frontend.integration.test_research_resource_pages import until


def test_each_group_exposes_its_observation_and_expiry_basis(healthy_research_host):
    _, _, host = healthy_research_host
    root = host.rootObject()
    root.findChild(QQuickItem, "researchHealthButton").forceActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
    assert root.findChild(QObject, "researchHealthPopup").property("opened")
    text = root.findChild(QQuickItem, "researchHealthFacts").property("text")
    for name in ("运行时", "数据源", "队列", "缓存", "持久化", "版本兼容"):
        group = next(part for part in text.split("\n\n") if part.startswith(name + " · "))
        assert "观察记录 · 2030-01-01T00:00:00+00:00" in group
        assert "当前影响 · 未关联任务" in group
        assert "诊断 · " in group
        if name in ("运行时", "版本兼容"):
            assert "独立过期阈值 · 未提供" in group
            assert "最近成功观察 · 2030-01-01T00:00:00+00:00" in group
        else:
            assert "过期阈值 · 30.0 秒" in group
            assert "观察年龄 · 0.0 秒" in group


def test_failed_queue_read_keeps_its_stale_observation_in_details_and_header(healthy_research_host):
    app, context, host = healthy_research_host
    root = host.rootObject()
    popup = root.findChild(QObject, "researchHealthPopup")
    context.system_health_feature.advance_queue_to_unavailable()
    until(app, lambda: popup.property("adapter").property("queueFreshness") == "stale")
    text = root.findChild(QQuickItem, "researchHealthFacts").property("text")
    queue = next(part for part in text.split("\n\n") if part.startswith("队列 · "))
    assert "队列 · 受限" in queue
    assert "时效 · 已过期" in queue
    assert "观察记录 · 2030-01-01T00:00:00+00:00" in queue
    assert "diagnostic_queue_read_failed" in queue
    header = root.findChild(QQuickItem, "researchHealthButton").property("text")
    assert "队列受限" in header
    assert "观察过期" in header
    assert "观察新鲜" not in header


def test_elapsed_data_and_cache_keep_their_own_age_and_reliable_time(healthy_research_host):
    app, context, host = healthy_research_host
    root = host.rootObject()
    popup = root.findChild(QObject, "researchHealthPopup")
    context.system_health_feature.advance_clock(timedelta(seconds=31))
    until(app, lambda: popup.property("adapter").property("dataSourceFreshness") == "stale"
          and popup.property("adapter").property("cacheFreshness") == "stale")
    text = root.findChild(QQuickItem, "researchHealthFacts").property("text")
    data = next(part for part in text.split("\n\n") if part.startswith("数据源 · "))
    cache = next(part for part in text.split("\n\n") if part.startswith("缓存 · "))
    queue = next(part for part in text.split("\n\n") if part.startswith("队列 · "))
    assert "最近可靠观察 · 2030-01-01T00:00:00+00:00" in data
    for group in (data, cache):
        assert "观察年龄 · 31.0 秒" in group
        assert "时效 · 已过期" in group
    assert "时效 · 新鲜" in queue
    assert "观察年龄 · 0.0 秒" in queue
    assert "观察记录 · 2030-01-01T00:00:31+00:00" in queue


def test_missing_observation_does_not_report_a_reliable_zero_age(research_host):
    app, _, host = research_host
    root = host.rootObject()
    facts = root.findChild(QQuickItem, "researchHealthFacts")
    until(app, lambda: "数据源 · " in facts.property("text"))
    text = facts.property("text")
    for name in ("数据源", "队列", "缓存"):
        group = next(part for part in text.split("\n\n") if part.startswith(name + " · "))
        assert "时效 · 尚无可靠观察" in group
        assert "观察年龄 · 未知" in group
        assert "观察年龄 · 0.0 秒" not in group


@pytest.mark.parametrize("research_host", [
    {"bookmark": BOOKMARK, "size": (1426, 786), "text_scale": 1.0},
    {"bookmark": BOOKMARK, "size": (960, 480), "text_scale": 2.0},
], indirect=True)
def test_all_group_details_are_keyboard_readable_and_read_only(healthy_research_host, record_property):
    app, _, host = healthy_research_host
    root = host.rootObject()
    button = root.findChild(QQuickItem, "researchHealthButton")
    button.forceActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
    facts = root.findChild(QQuickItem, "researchHealthFacts")
    accessible = QAccessible.queryAccessibleInterface(facts)
    assert accessible.state().readOnly
    value = accessible.text(QAccessible.Text.Value)
    for name in ("运行时", "数据源", "队列", "缓存", "持久化", "版本兼容"):
        assert name + " · 正常" in value
    facts.forceActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home, Qt.KeyboardModifier.ControlModifier)
    QTest.qWait(30)
    if evidence_dir := os.environ.get("STOCKSIM_QML_EVIDENCE_DIR"):
        assert host.grabFramebuffer().save(str(Path(evidence_dir) / f"health-details-top-{host.width()}x{host.height()}.png"))
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
    QTest.qWait(30)
    assert facts.property("cursorPosition") == len(facts.property("text"))
    bottom = facts.mapToScene(facts.property("cursorRectangle").bottomRight()).y()
    assert 0 < bottom <= host.height()
    assert facts.hasActiveFocus()
    if evidence_dir := os.environ.get("STOCKSIM_QML_EVIDENCE_DIR"):
        assert host.grabFramebuffer().save(str(Path(evidence_dir) / f"health-details-end-{host.width()}x{host.height()}.png"))
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Escape)
    app.processEvents()
    assert button.hasActiveFocus()
    assert host.active_route.value == "strategy_library"
    record_property("logical_client", f"{host.width()}x{host.height()}")
    record_property("dpr", host.devicePixelRatioF())
    record_property("text_scale", root.property("designSystem").property("textScale"))


@pytest.mark.parametrize("research_host", [{"bookmark": BOOKMARK, "text_scale": 2.0,
                                           "size": (960, 480)}], indirect=True)
def test_observation_updates_do_not_pull_the_reader_away_from_the_end(healthy_research_host):
    app, context, host = healthy_research_host
    root = host.rootObject()
    root.findChild(QQuickItem, "researchHealthButton").forceActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
    facts = root.findChild(QQuickItem, "researchHealthFacts")
    facts.forceActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
    QTest.qWait(30)
    assert facts.property("cursorPosition") == len(facts.property("text"))
    context.system_health_feature.advance_clock(timedelta(seconds=31))
    until(app, lambda: "观察年龄 · 31.0 秒" in facts.property("text"))
    QTest.qWait(30)
    assert facts.hasActiveFocus()
    assert facts.property("cursorPosition") == len(facts.property("text"))
    bottom = facts.mapToScene(facts.property("cursorRectangle").bottomRight()).y()
    assert 0 < bottom <= host.height()
