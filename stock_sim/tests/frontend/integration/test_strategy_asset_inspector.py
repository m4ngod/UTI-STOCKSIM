from __future__ import annotations

import gc
import os
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QAccessible, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.ui.journey_workspace import JourneyWorkspaceHost
from app.ui.main_window import MainWindow
from app.ui.accessibility import AccessibilityPreferences
from tests.frontend.contract.test_strategy_asset_queries_feature import composed


@pytest.fixture(autouse=True)
def release_qml_hosts():
    yield
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    gc.collect()


@pytest.mark.parametrize("size", ((960, 480), (960, 540), (1426, 786), (2560, 1440), (3840, 2160)))
@pytest.mark.parametrize("scale", (1.0, 2.0))
def test_product_inspector_reads_exact_asset_and_returns_keyboard_focus(composed, size, scale, record_property):
    context, executor, bridge, inventory = composed
    app = QApplication.instance()
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        strategy_library_feature=context.strategy_library_feature,
        strategy_library_queries=context.strategy_library_queries,
        feature_capabilities=context.feature_capabilities(),
        accessibility_preferences=AccessibilityPreferences(text_scale=scale, reduced_motion=True),
        initial_route="strategy_library",
    )
    host.resize(*size)
    host.show()
    app.processEvents()
    root = host.rootObject()
    trigger = root.findChild(QObject, "strategyExactAssetsButton")
    assert trigger is not None
    interface = QAccessible.queryAccessibleInterface(trigger)
    assert interface.role() == QAccessible.Role.Button
    assert interface.text(QAccessible.Text.Name) == "检查精确资产"
    trigger.forceActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
    app.processEvents()
    status = root.findChild(QObject, "strategyExactAssetStatus")
    assert "读取" in status.property("text")
    popup = root.findChild(QObject, "strategyExactAssetInspector")
    assert popup.property("width") <= host.width()
    assert popup.property("height") <= host.height()
    record_property("logical_client", f"{host.width()}x{host.height()}")
    record_property("dpr", host.devicePixelRatioF())
    record_property("text_scale", scale)
    executor.run_next()
    app.processEvents()
    app.processEvents()
    picker = root.findChild(QObject, "strategyExactAssetPicker")
    picker.forceActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Down)
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
    app.processEvents()
    query = root.findChild(QObject, "strategyExactAssetQueryButton")
    assert query.property("enabled")
    query.forceActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
    app.processEvents()
    assert context.strategy_library_queries.snapshot().request is not None
    executor.run_next()
    app.processEvents()
    app.processEvents()
    detail = root.findChild(QObject, "strategyExactAssetResult")
    QTest.qWait(30)
    assert "SHA-256" in detail.property("text")
    assert "legacy_strategy" in detail.property("text")
    detail_interface = QAccessible.queryAccessibleInterface(detail)
    assert detail_interface.role() == QAccessible.Role.EditableText
    assert detail_interface.state().readOnly
    assert "SHA-256" in detail_interface.text(QAccessible.Text.Value)
    assert detail.property("activeFocusOnTab")
    detail.forceActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Home, Qt.KeyboardModifier.ControlModifier)
    QTest.qWait(20)
    body = root.findChild(QObject, "strategyExactAssetBody")
    cursor = detail.property("cursorRectangle")
    cursor_point = detail.mapToScene(QPointF(cursor.x(), cursor.y()))
    body_point = body.mapToScene(QPointF(0, 0))
    assert cursor_point.y() >= body_point.y() - 1
    assert cursor_point.y() + cursor.height() <= body_point.y() + body.height() + 1
    query_interface = QAccessible.queryAccessibleInterface(query)
    assert query_interface.role() == QAccessible.Role.Button
    assert query_interface.state().focusable and not query_interface.state().disabled
    if evidence_dir := os.environ.get("STOCKSIM_QML_EVIDENCE_DIR"):
        destination = Path(evidence_dir)
        destination.mkdir(parents=True, exist_ok=True)
        kind = context.strategy_library_queries.snapshot().source_kind.value
        assert host.grab().save(str(destination / f"inspector-{kind}-{size[0]}x{size[1]}-text{scale}.png"))
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Escape)
    app.processEvents()
    assert trigger.hasActiveFocus()
    host.close()
    host.deleteLater()
    app.processEvents()


def test_main_window_composes_the_same_query_extension(composed, tmp_path):
    context, executor, bridge, inventory = composed
    app = QApplication.instance()
    window = MainWindow(
        strategy_library_feature=context.strategy_library_feature,
        strategy_library_queries=context.strategy_library_queries,
        feature_capabilities=context.feature_capabilities(),
        run_monitoring_feature=context.run_monitoring_feature,
        frontend_v2_enabled=True, layout_path=str(tmp_path / "layout.json"),
    )
    window.show()
    app.processEvents()
    host = window.centralWidget()
    trigger = host.rootObject().findChild(QObject, "strategyExactAssetsButton")
    trigger.forceActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
    app.processEvents()
    assert context.strategy_library_queries.snapshot().phase.value == "loading"
    executor.run_next()
    app.processEvents()
    window.close()
    window.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("scale", (1.0, 2.0))
@pytest.mark.parametrize("high_contrast", (False, True))
def test_read_only_result_has_a_visible_keyboard_focus_indicator(composed, scale, high_contrast):
    """Inspect painted focus, not a private background-item implementation."""
    context, executor, bridge, inventory = composed
    app = QApplication.instance()
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        strategy_library_feature=context.strategy_library_feature,
        strategy_library_queries=context.strategy_library_queries,
        feature_capabilities=context.feature_capabilities(), initial_route="strategy_library",
        accessibility_preferences=AccessibilityPreferences(
            text_scale=scale, reduced_motion=True, high_contrast=high_contrast,
        ),
    )
    host.resize(1426, 1080)
    host.show()
    app.processEvents()
    try:
        root = host.rootObject()
        root.findChild(QObject, "strategyExactAssetsButton").forceActiveFocus()
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        executor.run_next()
        QTest.qWait(20)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Tab)
        assert host.quickWindow().activeFocusItem().objectName() == "strategyExactAssetPicker"
        detail = root.findChild(QObject, "strategyExactAssetResult")
        focus_rgb = QColor("#ffff00" if high_contrast else "#9fbfff").rgb()

        def painted_focus_pixels():
            # Read the current Quick render target, not QWidget's potentially
            # stale composited backing store. The immutable f354f03 baseline
            # reproduces stale widget captures after a correct focus change.
            frame = host.grabFramebuffer()
            dpr = frame.devicePixelRatio()
            origin = detail.mapToScene(QPointF(0, 0))
            # The top edge is blank of text: an insertion cursor cannot pass.
            left = round((origin.x() + detail.width() * 0.2) * dpr)
            right = round((origin.x() + detail.width() * 0.8) * dpr)
            top = round(origin.y() * dpr)
            assert 0 <= left < right < frame.width()
            assert 0 <= top < top + round(3 * dpr) < frame.height()
            return sum(frame.pixel(x, y) == focus_rgb
                       for x in range(left, right)
                       for y in range(top, top + round(3 * dpr))), right - left

        before, _ = painted_focus_pixels()
        assert before == 0
        # With no version selected, the disabled query action is skipped.
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Tab)
        QTest.qWait(20)
        assert detail.hasActiveFocus()
        painted, sampled_width = painted_focus_pixels()
        assert painted >= sampled_width, "Read-only keyboard target has no visible focus edge"
    finally:
        host.close()
        host.deleteLater()
        app.processEvents()


def test_product_accessible_root_tracks_keyboard_focus(composed, tmp_path):
    """Check the public accessible tree, not just the painted active-focus ring."""
    context, executor, bridge, inventory = composed
    app = QApplication.instance()
    window = MainWindow(
        strategy_library_feature=context.strategy_library_feature,
        strategy_library_queries=context.strategy_library_queries,
        feature_capabilities=context.feature_capabilities(),
        run_monitoring_feature=context.run_monitoring_feature,
        frontend_v2_enabled=True, layout_path=str(tmp_path / "layout.json"),
    )
    window.resize(1100, 700)
    window.show()
    QTest.qWait(20)
    host = window.centralWidget()
    root = host.rootObject()
    trigger = root.findChild(QObject, "strategyExactAssetsButton")

    def assert_accessible_focus(expected):
        interface = window.windowHandle().accessibleRoot()
        # The focused leaf must also remain reachable in the original Qt tree.
        descendants = [interface]
        descendant_ids = set()
        while descendants:
            descendant = descendants.pop()
            identity = QAccessible.uniqueId(descendant)
            if identity in descendant_ids:
                continue
            descendant_ids.add(identity)
            descendants.extend(child for index in range(descendant.childCount())
                               if (child := descendant.child(index)) is not None)
        assert QAccessible.uniqueId(QAccessible.queryAccessibleInterface(expected)) in descendant_ids
        path = []
        visited = set()
        while interface is not None:
            identity = QAccessible.uniqueId(interface)
            if identity in visited:
                break
            visited.add(identity)
            path.append(interface.text(QAccessible.Text.Name))
            child = interface.focusChild()
            if child is None:
                break
            interface = child
        assert interface is not None
        assert interface.object() == expected, path
        assert interface.state().focused, path

    try:
        search = root.findChild(QObject, "strategyLibrarySearchInput")
        search.forceActiveFocus()
        QTest.qWait(10)
        assert_accessible_focus(search)
        trigger.forceActiveFocus()
        QTest.qWait(10)
        assert_accessible_focus(trigger)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
        executor.run_next()
        QTest.qWait(20)
        refresh = root.findChild(QObject, "strategyExactAssetRefreshButton")
        assert_accessible_focus(refresh)
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Tab)
        QTest.qWait(10)
        assert_accessible_focus(root.findChild(QObject, "strategyExactAssetPicker"))
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Escape)
        QTest.qWait(10)
        assert_accessible_focus(trigger)
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("composed,expected", (
    (("fake", "empty"), "没有可读取的旧策略资产"),
    (("live", "normal"), "读取受限"),
    (("fake", "normal"), "读取受限"),
), indirect=("composed",))
def test_product_inspector_distinguishes_empty_from_read_failure(composed, expected):
    context, executor, bridge, inventory = composed
    app = QApplication.instance()
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        strategy_library_feature=context.strategy_library_feature,
        strategy_library_queries=context.strategy_library_queries,
        feature_capabilities=context.feature_capabilities(), initial_route="strategy_library",
    )
    host.resize(960, 480)
    host.show()
    app.processEvents()


    root = host.rootObject()
    trigger = root.findChild(QObject, "strategyExactAssetsButton")
    trigger.forceActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
    app.processEvents()
    if inventory.entries:
        executor.fail_next()
    else:
        executor.run_next()
    app.processEvents()
    app.processEvents()
    status = root.findChild(QObject, "strategyExactAssetStatus")
    assert expected in status.property("text")
    assert not root.findChild(QObject, "strategyExactAssetQueryButton").property("enabled")
    assert "SHA-256" not in root.findChild(QObject, "strategyExactAssetResult").property("text")
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Escape)
    app.processEvents()
    assert trigger.hasActiveFocus()
    host.close()
    host.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("scale", (1.0, 2.0))
def test_product_inspector_tab_cycle_and_same_target_read_continuity(composed, scale):
    context, executor, bridge, inventory = composed
    app = QApplication.instance()
    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        strategy_library_feature=context.strategy_library_feature,
        strategy_library_queries=context.strategy_library_queries,
        feature_capabilities=context.feature_capabilities(), initial_route="strategy_library",
        accessibility_preferences=AccessibilityPreferences(text_scale=scale, reduced_motion=True),
    )
    host.resize(960, 480)
    host.show()
    app.processEvents()
    root = host.rootObject()
    trigger = root.findChild(QObject, "strategyExactAssetsButton")
    trigger.forceActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
    app.processEvents()
    executor.run_next()
    QTest.qWait(20)
    refresh = root.findChild(QObject, "strategyExactAssetRefreshButton")
    assert refresh.hasActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Tab)
    assert host.quickWindow().activeFocusItem().objectName() == "strategyExactAssetPicker"
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Down)
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Return)
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Tab)
    query = root.findChild(QObject, "strategyExactAssetQueryButton")
    assert query.hasActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
    executor.run_next()
    QTest.qWait(20)
    detail = root.findChild(QObject, "strategyExactAssetResult")
    assert "SHA-256" in detail.property("text")
    required = {"strategyExactAssetCloseButton", "strategyExactAssetRefreshButton", "strategyExactAssetPicker",
                "strategyExactAssetQueryButton", "strategyExactAssetResult"}
    for modifier in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier):
        visited = set()
        for _ in range(10):
            QTest.keyClick(host.quickWindow(), Qt.Key.Key_Tab, modifier)
            QTest.qWait(5)
            focused = host.quickWindow().activeFocusItem().objectName()
            assert focused in required, f"Modal focus escaped to {focused}"
            visited.add(focused)
        assert visited == required
    # Reach the query action with Tab only, never force focus inside the popup.
    for _ in range(6):
        if query.hasActiveFocus():
            break
        QTest.keyClick(host.quickWindow(), Qt.Key.Key_Tab)
    assert query.hasActiveFocus()
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Space)
    app.processEvents()
    assert "SHA-256" in detail.property("text")
    assert "保留的已验证内容" in detail.property("text")
    executor.fail_next()
    QTest.qWait(20)
    assert "SHA-256" in detail.property("text")
    assert "保留的已验证内容" in detail.property("text")
    QTest.keyClick(host.quickWindow(), Qt.Key.Key_Escape)
    app.processEvents()
    assert trigger.hasActiveFocus()
    host.close()
    host.deleteLater()
    app.processEvents()
