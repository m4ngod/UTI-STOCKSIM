"""Per-group health evidence through public Feature observations and actual QML."""

from dataclasses import replace
from datetime import timedelta
import os
from pathlib import Path

import pytest

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtGui import QAccessible, QFont, QFontDatabase
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.app_context import build_app_context
from app.event_bridge import EventBridge
from app.features import LiveStrategyDiagnosticsV1ApplicationAdapter
from app.features.system_health import RuntimeHealthClassification
from app.features.system_health_application import LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter
from app.ui.journey_workspace import JourneyWorkspaceHost
from tests.frontend.contract.test_diagnostic_task_campaign_start_live_contract import _formal_live_stack

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
    for name in ("数据源", "队列", "缓存", "持久化"):
        group = next(part for part in text.split("\n\n") if part.startswith(name + " · "))
        assert "时效 · 尚无可靠观察" in group
        assert "观察年龄 · 未知" in group
        assert "观察年龄 · 0.0 秒" not in group


def test_recovered_runtime_from_public_application_input_keeps_all_groups(tmp_path, monkeypatch):
    class RecoveredRuntimeInput(LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter):
        """Deliver a legal input at the public health-application boundary."""

        def read_runtime_health(self):
            result = super().read_runtime_health()
            assert result.observation is not None
            return replace(result, observation=replace(
                result.observation, classification=RuntimeHealthClassification.RECOVERED,
            ))

    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    app = QApplication.instance() or QApplication([])
    if not QFontDatabase.families():
        assert QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc") >= 0
        app.setFont(QFont("Microsoft YaHei UI", 10))
    _, _, engine, application, _, auxiliary = _formal_live_stack(tmp_path)
    bridge = EventBridge(subscribe_backend=False)
    context = host = None
    try:
        context = build_app_context(
            settings_path=str(tmp_path / "settings.json"), run_monitoring_mode="live",
            strategy_diagnostics_application=application,
            strategy_diagnostics_read_model=LiveStrategyDiagnosticsV1ApplicationAdapter(application, engine),
            strategy_diagnostics_system_health_application=RecoveredRuntimeInput(application),
            event_bridge=bridge, system_health_sampling_interval=None,
        )
        host = JourneyWorkspaceHost(context.run_monitoring_feature,
                                  system_health_feature=context.system_health_feature,
                                  research_shell=True)
        host.resize(1426, 786)
        host.show()
        root = host.rootObject()
        adapter = root.findChild(QObject, "researchHealthPopup").property("adapter")
        until(app, lambda: adapter.property("componentClassification") == "recovered")
        root.findChild(QQuickItem, "researchHealthButton").forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        facts = root.findChild(QQuickItem, "researchHealthFacts")
        text = QAccessible.queryAccessibleInterface(facts).text(QAccessible.Text.Value)
        assert "运行时 · 已恢复" in text
        for name in ("数据源", "队列", "缓存", "持久化", "版本兼容"):
            assert name + " · " in text
    finally:
        if host is not None:
            host.close_adapter()
            host.close()
            host.deleteLater()
        if context is not None:
            context.close()
        auxiliary.close()
        bridge.stop()
        engine.dispose()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


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
    assert facts.property("cursorPosition") == 0
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


@pytest.mark.parametrize("research_host", [{"bookmark": BOOKMARK, "text_scale": 2.0,
                                           "size": (960, 480)}], indirect=True)
@pytest.mark.parametrize("select", ["none", "forward", "backward"])
def test_observation_updates_preserve_reading_within_an_unchanged_section(healthy_research_host, select):
    app, context, host = healthy_research_host
    root = host.rootObject()
    root.findChild(QQuickItem, "researchHealthButton").forceActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
    facts = root.findChild(QQuickItem, "researchHealthFacts")
    facts.forceActiveFocus()
    token = "版本兼容 · 正常"
    before = facts.property("text")
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home, Qt.KeyboardModifier.ControlModifier)
    for _ in range(before.index(token)):
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Right)
    if select == "backward":
        for _ in token:
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Right)
        for _ in token:
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)
        assert facts.property("selectedText") == token
    elif select == "forward":
        for _ in token:
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
        assert facts.property("selectedText") == token
    else:
        assert before[facts.property("cursorPosition"):].startswith(token)
    context.system_health_feature.advance_clock(timedelta(seconds=31))
    until(app, lambda: "观察年龄 · 31.0 秒" in facts.property("text"))
    QTest.qWait(30)
    assert facts.hasActiveFocus()
    if select != "none":
        assert facts.property("selectedText") == token
        expected_end = "selectionStart" if select == "backward" else "selectionEnd"
        assert facts.property("cursorPosition") == facts.property(expected_end)
    else:
        assert facts.property("text")[facts.property("cursorPosition"):].startswith(token)
    bottom = facts.mapToScene(facts.property("cursorRectangle").bottomRight()).y()
    assert 0 < bottom <= host.height()
