from __future__ import annotations

import gc
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.features import (
    DeterministicFakeRunMonitoringAdapter,
    DeterministicFakeStrategyLibraryAdapter,
    LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter,
    LiveStrategyLibraryAdapter,
    StrategyLibraryContext,
)
from app.ui.journey_workspace import JourneyWorkspaceHost
from app.ui.main_window import MainWindow
from strategy_diagnostics import create_diagnostics_application


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _quick_item(root: QQuickItem, object_name: str) -> QQuickItem | None:
    pending = [root]
    while pending:
        item = pending.pop()
        if item.objectName() == object_name:
            return item
        pending.extend(item.childItems())
    return None


def _quick_items(root: QQuickItem) -> tuple[QQuickItem, ...]:
    found: list[QQuickItem] = []
    pending = [root]
    while pending:
        item = pending.pop()
        found.append(item)
        pending.extend(item.childItems())
    return tuple(found)


@pytest.fixture(autouse=True)
def _release_closed_qml_hosts_between_tests():
    yield
    app = QApplication.instance()
    if app is None:
        return
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()


def test_production_workspace_browses_and_searches_strategy_library() -> None:
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    strategy_feature = DeterministicFakeStrategyLibraryAdapter()
    host = JourneyWorkspaceHost(
        run_feature,
        strategy_library_feature=strategy_feature,
        strategy_library_context=StrategyLibraryContext(),
        initial_route="strategy_library",
    )
    app.processEvents()
    root = host.rootObject()

    assert root is not None
    assert root.property("activeRoute") == "strategy_library"
    assert root.findChild(QObject, "strategyLibraryRouteNavigation") is not None
    assert root.findChild(QObject, "strategyLibraryPage") is not None
    assert host._strategy_library.presentationState == "ready"
    assert host._strategy_library.entryCount == 2
    repeater = root.findChild(QObject, "strategyLibraryEntryRepeater")
    assert repeater is not None
    assert repeater.property("count") == 2
    assert tuple(
        item["displayName"] for item in host._strategy_library.entries
    ) == (
        "QuentX Live Minute Scenario-native",
        "QuentX 5.2.3 Scenario-native",
    )

    visible_text = " ".join(
        str(item.property("text"))
        for item in _quick_items(root)
        if item.metaObject().indexOfProperty("text") >= 0
        and item.property("text")
    )
    for expected in (
        "Strategy Library",
        "PTrade surface",
        "Guardrail profile",
        "Formal Campaign ready",
    ):
        assert expected.casefold() in visible_text.casefold()

    host._strategy_library.setSearchText("live minute")
    app.processEvents()

    assert host._strategy_library.entryCount == 1
    assert "Live Minute" in host._strategy_library.entries[0]["displayName"]
    host.close_adapter()
    run_feature.close()
    strategy_feature.close()


def test_strategy_library_route_contains_no_trading_or_admin_actions() -> None:
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    strategy_feature = DeterministicFakeStrategyLibraryAdapter()
    host = JourneyWorkspaceHost(
        run_feature,
        strategy_library_feature=strategy_feature,
        initial_route="strategy_library",
    )
    app.processEvents()
    root = host.rootObject()
    assert root is not None

    visible_text = " ".join(
        str(item.property("text"))
        for item in root.findChildren(QObject)
        if item.metaObject().indexOfProperty("text") >= 0
        and item.property("text")
    ).casefold()
    for forbidden in (
        "buy",
        "sell",
        "submit order",
        "cancel order",
        "replace order",
        "register strategy",
        "import strategy",
        "retire strategy",
        "edit source",
        "execute strategy",
    ):
        assert forbidden not in visible_text
    host.close_adapter()
    run_feature.close()
    strategy_feature.close()


def test_main_window_starts_frontend_v2_at_strategy_library_when_available() -> None:
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    strategy_feature = DeterministicFakeStrategyLibraryAdapter()
    bookmarks = []

    window = MainWindow(
        strategy_library_feature=strategy_feature,
        strategy_library_context=StrategyLibraryContext(),
        strategy_library_bookmark_sink=bookmarks.append,
        run_monitoring_feature=run_feature,
        frontend_v2_enabled=True,
    )
    app.processEvents()
    host = window.centralWidget()

    assert host.rootObject().property("activeRoute") == "strategy_library"
    assert host._strategy_library is not None
    host._strategy_library.selectFormalSet()
    app.processEvents()
    assert host._strategy_library._state.selection is not None
    assert bookmarks[-1].selections == (
        host._strategy_library._state.selection.selections
    )
    window.close()
    run_feature.close()
    strategy_feature.close()


def test_live_strategy_library_traces_public_inventory_into_qml() -> None:
    app = _app()
    application = create_diagnostics_application()
    application.start()
    strategy_application = (
        LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(application)
    )
    strategy_feature = LiveStrategyLibraryAdapter(
        application=strategy_application
    )
    run_feature = DeterministicFakeRunMonitoringAdapter()
    host = JourneyWorkspaceHost(
        run_feature,
        strategy_library_feature=strategy_feature,
        initial_route="strategy_library",
    )
    app.processEvents()
    root = host.rootObject()

    assert root is not None
    assert host._strategy_library.presentationState == "ready"
    assert host._strategy_library.sourceRevision != "Unavailable"
    assert host._strategy_library.entryCount == 2
    repeater = root.findChild(QObject, "strategyLibraryEntryRepeater")
    assert repeater is not None
    assert repeater.property("count") == 2
    assert {
        item["strategyId"] for item in host._strategy_library.entries
    } == {
        "quentx-5.2.3-scenario-native",
        "quentx-live-minute-scenario-native",
    }
    host.close_adapter()
    strategy_feature.close()
    run_feature.close()


def test_strategy_library_inspection_shows_complete_compatibility_and_guardrails() -> None:
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    strategy_feature = DeterministicFakeStrategyLibraryAdapter()
    host = JourneyWorkspaceHost(
        run_feature,
        strategy_library_feature=strategy_feature,
        initial_route="strategy_library",
    )
    app.processEvents()
    root = host.rootObject()
    assert root is not None
    entry = host._strategy_library.entries[0]
    strategy_id = entry["strategyId"]
    card = _quick_item(root, f"strategyLibraryEntry-{strategy_id}")
    assert card is not None
    card.setProperty("expanded", True)
    app.processEvents()

    details = _quick_item(root, f"strategyLibraryDetails-{strategy_id}")
    assert details is not None
    assert details.property("visible") is True
    text = " ".join(
        str(item.property("text"))
        for item in _quick_items(details)
        if item.metaObject().indexOfProperty("text") >= 0
        and item.property("text")
    )
    for expected in (
        "Lifecycle callbacks",
        entry["lifecycleCallbacks"][0],
        "Scheduled callbacks",
        entry["scheduledCallbacks"][0],
        "Context fields",
        entry["contextFields"][0],
        "Portfolio fields",
        entry["portfolioFields"][0],
        "History units",
        entry["historyUnits"][0],
        "Guardrail threshold",
        entry["guardrailThresholds"][0]["metric"],
        entry["guardrailThresholds"][0]["operator"],
        entry["guardrailThresholds"][0]["value"],
    ):
        assert expected in text
    host.close_adapter()
    run_feature.close()
    strategy_feature.close()


def test_strategy_library_route_restores_meaningful_keyboard_focus() -> None:
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    strategy_feature = DeterministicFakeStrategyLibraryAdapter()
    host = JourneyWorkspaceHost(
        run_feature,
        strategy_library_feature=strategy_feature,
        initial_route="strategy_library",
    )
    host.resize(1280, 720)
    host.show()
    app.processEvents()
    root = host.rootObject()
    assert root is not None
    search = root.findChild(QQuickItem, "strategyLibrarySearchInput")
    strategy_route = root.findChild(
        QQuickItem,
        "strategyLibraryRouteNavigation",
    )
    run_route = root.findChild(QQuickItem, "runMonitoringRouteNavigation")
    assert search is not None
    assert strategy_route is not None
    assert run_route is not None

    search.forceActiveFocus()
    app.processEvents()
    assert search.property("activeFocus") is True

    run_route.forceActiveFocus()
    QTest.keyClick(host, Qt.Key.Key_Return)
    app.processEvents()
    assert root.property("activeRoute") == "run_monitoring"

    strategy_route.forceActiveFocus()
    QTest.keyClick(host, Qt.Key.Key_Return)
    app.processEvents()
    assert root.property("activeRoute") == "strategy_library"
    assert search.property("activeFocus") is True
    host.close_adapter()
    run_feature.close()
    strategy_feature.close()


def test_strategy_library_compares_dimensions_and_selects_exact_formal_set() -> None:
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    strategy_feature = DeterministicFakeStrategyLibraryAdapter()
    host = JourneyWorkspaceHost(
        run_feature,
        strategy_library_feature=strategy_feature,
        initial_route="strategy_library",
    )
    app.processEvents()
    root = host.rootObject()
    assert root is not None

    host._strategy_library.compareFormalSet()
    host._strategy_library.selectFormalSet()
    app.processEvents()

    assert host._strategy_library.comparisonCount == 2
    assert host._strategy_library.selectionStatus == "current"
    assert len(host._strategy_library.selectionContextId) == 64
    assert root.findChild(QObject, "strategyLibraryCompareFormalSet") is not None
    assert root.findChild(QObject, "strategyLibrarySelectFormalSet") is not None
    visible_text = " ".join(
        str(item.property("text"))
        for item in _quick_items(root)
        if item.metaObject().indexOfProperty("text") >= 0
        and item.property("text")
    )
    for expected in (
        "Identity and version",
        "Source identity",
        "Source lineage",
        "Compatibility",
        "Declared capabilities",
        "Candidate data policy",
        "Guardrail profile",
        "Guardrail threshold",
        "Dependency provenance",
        "Diagnostic applicability",
    ):
        assert expected in visible_text
    for entry in host._strategy_library.comparisonEntries:
        assert entry["sourceHash"] in visible_text
        assert entry["manifestHash"] in visible_text
        for capability in entry["capabilities"]:
            assert capability in visible_text
        for threshold in entry["guardrailThresholds"]:
            assert threshold["metric"] in visible_text
            assert threshold["operator"] in visible_text
            assert threshold["value"] in visible_text
        for dependency in entry["dependencies"]:
            assert dependency["identity"] in visible_text
            assert dependency["contentHash"] in visible_text
    assert "leaderboard" not in visible_text.casefold()
    assert "recommended strategy" not in visible_text.casefold()
    strategy_feature.advance_to_disconnected()
    app.processEvents()
    assert host._strategy_library.comparisonCount == 0
    host.close_adapter()
    run_feature.close()
    strategy_feature.close()


def test_strategy_selection_survives_qml_host_remount_without_floating() -> None:
    app = _app()
    strategy_feature = DeterministicFakeStrategyLibraryAdapter()
    bookmarks = []
    first_run = DeterministicFakeRunMonitoringAdapter()
    first = JourneyWorkspaceHost(
        first_run,
        strategy_library_feature=strategy_feature,
        strategy_library_bookmark_sink=bookmarks.append,
        initial_route="strategy_library",
    )
    app.processEvents()
    first._strategy_library.selectFormalSet()
    app.processEvents()
    assert bookmarks
    bookmark = bookmarks[-1]
    assert bookmark.source_generation is not None
    first.close_adapter()
    first_run.close()
    strategy_feature.close()

    second_run = DeterministicFakeRunMonitoringAdapter()
    reopened_strategy = DeterministicFakeStrategyLibraryAdapter()
    second = JourneyWorkspaceHost(
        second_run,
        strategy_library_feature=reopened_strategy,
        strategy_library_context=StrategyLibraryContext(
            focus_strategy_id=bookmark.focus_strategy_id,
            selection_bookmark=bookmark,
        ),
        initial_route="strategy_library",
    )
    app.processEvents()

    assert second._strategy_library.selectionStatus == "current"
    assert second._strategy_library.sourceGeneration > (
        bookmark.source_generation.value
    )
    assert second._strategy_library.focusRestorationTarget == (
        "select_formal_set"
    )
    root = second.rootObject()
    assert root is not None
    focus_control = _quick_item(
        root,
        "strategyLibrarySelectFormalSet",
    )
    assert focus_control is not None
    assert focus_control.property("activeFocus") is True
    second.close_adapter()
    second_run.close()
    reopened_strategy.close()
