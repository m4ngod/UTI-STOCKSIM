import os
from time import monotonic, sleep

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QAccessible, QAccessibleActionInterface
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from app.app_context import build_app_context
from app.event_bridge import EventBridge
from app.features import (
    ApprovedScenarioRecipeId,
    DeterministicFakeDiagnosticTasksAdapter,
    DeterministicFakeEvidenceAndFindingsAdapter,
    DeterministicFakeScenarioLabAdapter,
    DeterministicFakeStrategyLibraryAdapter,
    DeterministicFakeRunMonitoringAdapter,
    DeterministicFakeSystemHealthAdapter,
    DiagnosticTasksContext,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsSelection,
    FormalDiagnosticCampaignId,
    LiveDiagnosticTasksAdapter,
    LiveEvidenceAndFindingsAdapter,
    LiveRunMonitoringAdapter,
    LiveScenarioLabAdapter,
    LiveStrategyLibraryAdapter,
    LiveSystemHealthAdapter,
    MarketScenarioId,
    ReproductionManifestId,
    RunMonitoringContext,
    RunMonitoringSelection,
    StrategyRunId,
    StrategyUnderTestId,
    ScenarioLabContext,
    StrategyLibraryContext,
    SystemHealthContext,
)
from app.journey_recovery import (
    JourneyFocusReturnToken,
    JourneyPresentationSelection,
    JourneyWorkspaceBookmark,
    JourneyWorkspaceRoute,
)
from app.ui.accessibility import AccessibilityPreferences
from app.ui.journey_workspace import JourneyWorkspaceHost
from app.ui.main_window import MainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _run_context() -> RunMonitoringContext:
    return RunMonitoringContext.for_run(
        RunMonitoringSelection(
            campaign_id=FormalDiagnosticCampaignId("FDC-001"),
            run_id=StrategyRunId("RUN-001"),
        )
    )


def _evidence_context() -> EvidenceAndFindingsContext:
    return EvidenceAndFindingsContext.for_selection(
        EvidenceAndFindingsSelection(
            campaign_id=FormalDiagnosticCampaignId("FDC-001"),
            run_id=StrategyRunId("RUN-001"),
            strategy_id=StrategyUnderTestId("STRATEGY-MOMENTUM-001"),
            market_scenario_id=MarketScenarioId("SCENARIO-BASELINE"),
            approved_recipe_id=ApprovedScenarioRecipeId("RECIPE-001"),
            reproduction_manifest_id=ReproductionManifestId("RM-001"),
        )
    )


def _mounted_host(
    *,
    preferences: AccessibilityPreferences | None = None,
    run_context: RunMonitoringContext | None = None,
    system_health_feature: DeterministicFakeSystemHealthAdapter | None = None,
    initial_route: str = "run_monitoring",
    evidence_ready: bool = True,
    show_host: bool = True,
) -> tuple[
    JourneyWorkspaceHost,
    DeterministicFakeRunMonitoringAdapter,
    DeterministicFakeEvidenceAndFindingsAdapter,
]:
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    evidence_feature = DeterministicFakeEvidenceAndFindingsAdapter()
    strategy_feature = DeterministicFakeStrategyLibraryAdapter()
    scenario_feature = DeterministicFakeScenarioLabAdapter()
    diagnostic_feature = DeterministicFakeDiagnosticTasksAdapter()
    selected_system_health_feature = (
        system_health_feature
        or DeterministicFakeSystemHealthAdapter(initially_healthy=True)
    )
    selected_run_context = run_context or _run_context()
    if selected_run_context == RunMonitoringContext.no_selection():
        run_feature.advance_to_empty(selected_run_context)
    else:
        run_feature.advance_to_running(selected_run_context)
    if evidence_ready:
        evidence_feature.advance_to_completed(_evidence_context())
    host = JourneyWorkspaceHost(
        run_feature,
        context=selected_run_context,
        strategy_library_feature=strategy_feature,
        strategy_library_context=StrategyLibraryContext(),
        scenario_lab_feature=scenario_feature,
        scenario_lab_context=ScenarioLabContext(),
        diagnostic_tasks_feature=diagnostic_feature,
        diagnostic_tasks_context=DiagnosticTasksContext.workspace(),
        evidence_feature=evidence_feature,
        evidence_context=_evidence_context(),
        system_health_feature=selected_system_health_feature,
        system_health_context=SystemHealthContext(),
        accessibility_preferences=preferences,
        initial_route=initial_route,
    )
    host.resize(1280, 720)
    if show_host:
        host.show()
    app.processEvents()
    host._accessibility_feature_owners = (
        strategy_feature,
        scenario_feature,
        diagnostic_feature,
        selected_system_health_feature,
    )
    return host, run_feature, evidence_feature


def _interface(item: QObject):
    interface = QAccessible.queryAccessibleInterface(item)
    assert interface is not None
    assert interface.isValid()
    return interface


def _accessible_name(item: QObject) -> str:
    return _interface(item).text(QAccessible.Text.Name)


def _settle(app: QApplication) -> None:
    app.processEvents()
    app.processEvents()


def _wait_for(predicate, app: QApplication, message: str) -> None:
    deadline = monotonic() + 8
    while monotonic() < deadline:
        _settle(app)
        if predicate():
            return
        sleep(0.01)
    raise AssertionError(message)


def _close(
    host: JourneyWorkspaceHost,
    run_feature: DeterministicFakeRunMonitoringAdapter,
    evidence_feature: DeterministicFakeEvidenceAndFindingsAdapter,
) -> None:
    _close_host(host)
    for feature in getattr(host, "_accessibility_feature_owners", ()):
        feature.close()
    run_feature.close()
    evidence_feature.close()


def _close_host(host: JourneyWorkspaceHost) -> None:
    app = _app()
    host.close_adapter()
    host.close()
    host.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_narrator_sees_named_state_progress_commands_and_no_trading_actions():
    host, run_feature, evidence_feature = _mounted_host()
    root = host.rootObject()

    status = root.findChild(QObject, "runMonitoringAccessibleStatus")
    progress = root.findChild(QObject, "runMonitoringAccessibleProgress")
    pause = root.findChild(QObject, "pauseDiagnosticTask")
    route = root.findChild(QObject, "runMonitoringRouteNavigation")
    diagnostic_route = root.findChild(
        QObject,
        "diagnosticTasksRouteNavigation",
    )

    status_interface = _interface(status)
    progress_interface = _interface(progress)
    pause_interface = _interface(pause)
    route_interface = _interface(route)
    diagnostic_route_interface = _interface(diagnostic_route)

    assert status_interface.role() == QAccessible.Role.StatusBar
    assert "active" in status_interface.text(QAccessible.Text.Name).casefold()
    assert "fresh" in status_interface.text(
        QAccessible.Text.Description
    ).casefold()
    assert progress_interface.role() == QAccessible.Role.StaticText
    assert "2 / 10" in progress_interface.text(QAccessible.Text.Name)
    assert "2 / 10" in progress_interface.text(
        QAccessible.Text.Description
    )
    assert pause_interface.role() == QAccessible.Role.Button
    assert "diagnostic task" in _accessible_name(pause).casefold()
    assert "order" in pause_interface.text(
        QAccessible.Text.Description
    ).casefold()
    assert bool(route_interface.state().selected) is True
    assert bool(route_interface.state().focusable) is True
    assert str(root.property("screenState")).casefold() in (
        route_interface.text(QAccessible.Text.Name).casefold()
    )
    assert str(root.property("diagnosticTasksInventoryState")).casefold() in (
        diagnostic_route_interface.text(QAccessible.Text.Name).casefold()
    )
    assert QAccessibleActionInterface.pressAction() in (
        route_interface.actionInterface().actionNames()
    )

    accessible_text = " ".join(
        _accessible_name(item)
        for item in root.findChildren(QObject)
        if QAccessible.queryAccessibleInterface(item) is not None
    ).casefold()
    for forbidden in (
        "trader",
        "start experiment",
        "buy",
        "sell",
        "submit order",
        "cancel order",
        "replace order",
        "bulk order",
    ):
        assert forbidden not in accessible_text

    _close(host, run_feature, evidence_feature)


def test_six_route_journey_is_keyboard_operable_and_narrator_named():
    app = _app()
    host, run_feature, evidence_feature = _mounted_host()
    root = host.rootObject()
    routes = (
        (
            "strategy_library",
            "strategyLibraryRouteNavigation",
            "strategyLibraryInitialFocusItem",
            "strategyLibraryAccessibleStatus",
        ),
        (
            "scenario_lab",
            "scenarioLabRouteNavigation",
            "scenarioLabInitialFocusItem",
            "scenarioLabAccessibleStatus",
        ),
        (
            "diagnostic_tasks",
            "diagnosticTasksRouteNavigation",
            "diagnosticTasksInitialFocusItem",
            "diagnosticTasksAccessibleStatus",
        ),
        (
            "run_monitoring",
            "runMonitoringRouteNavigation",
            "runMonitoringInitialFocusItem",
            "runMonitoringAccessibleStatus",
        ),
        (
            "evidence_and_findings",
            "evidenceAndFindingsRouteNavigation",
            "evidenceInitialFocusItem",
            "evidenceAccessibleStatus",
        ),
        (
            "system_health",
            "systemHealthRouteNavigation",
            "systemHealthInitialFocusItem",
            "systemHealthAccessibleStatus",
        ),
    )

    for route, navigation_name, focus_property, status_name in routes:
        navigation = root.findChild(QQuickItem, navigation_name)
        assert navigation is not None
        navigation.forceActiveFocus()
        QTest.keyClick(host, Qt.Key.Key_Return)
        _settle(app)
        assert root.property("activeRoute") == route
        focus_item = root.property(focus_property) or navigation
        assert focus_item.property("activeFocus") is True
        assert focus_item.property("focusVisible") is True
        assert focus_item.property("visible") is True
        status = root.findChild(QObject, status_name)
        assert status is not None
        status_interface = _interface(status)
        assert status_interface.role() == QAccessible.Role.StatusBar
        assert status_interface.text(QAccessible.Text.Name).strip()
        assert status_interface.text(QAccessible.Text.Description).strip()

    _close(host, run_feature, evidence_feature)


@pytest.mark.parametrize("run_state", ("terminal", "no_selection"))
def test_run_monitoring_initial_focus_seam_matches_runtime_fallback(run_state):
    app = _app()
    context = (
        RunMonitoringContext.no_selection()
        if run_state == "no_selection"
        else _run_context()
    )
    host, run_feature, evidence_feature = _mounted_host(run_context=context)
    if run_state == "terminal":
        run_feature.advance_to_completed(context)
        _settle(app)

    root = host.rootObject()
    focus_item = root.property("runMonitoringInitialFocusItem")
    navigation = root.findChild(QQuickItem, "runMonitoringRouteNavigation")
    assert focus_item.objectName() == navigation.objectName()
    assert focus_item.property("activeFocus") is True
    assert focus_item.property("focusVisible") is True
    assert focus_item.property("visible") is True
    assert focus_item.property("enabled") is True

    _close(host, run_feature, evidence_feature)


def test_setup_comparisons_expose_revision_synchronized_narrative_alternatives():
    app = _app()
    host, run_feature, evidence_feature = _mounted_host()
    root = host.rootObject()

    host._strategy_library.compareFormalSet()
    _settle(app)
    root.setProperty("activeRoute", "strategy_library")
    _settle(app)
    strategy_narrative = root.findChild(
        QObject,
        "strategyLibraryComparisonNarrative",
    )
    strategy_interface = _interface(strategy_narrative)
    strategy_text = " ".join(
        (
            strategy_interface.text(QAccessible.Text.Name),
            strategy_interface.text(QAccessible.Text.Description),
        )
    )
    assert host._strategy_library.sourceRevision in strategy_text
    assert str(host._strategy_library.sourceGeneration) in strategy_text
    for entry in host._strategy_library.comparisonEntries:
        for exact_value in (
            entry["strategyId"],
            entry["strategyVersion"],
            *entry["lineage"],
            entry["sourceModule"],
            entry["sourcePath"],
            entry["sourceHash"],
            entry["surfaceVersion"],
            entry["manifestHash"],
            *entry["capabilities"],
            entry["candidateDataPolicy"],
            entry["guardrailProfileId"],
            entry["guardrailProfileVersion"],
        ):
            assert str(exact_value) in strategy_text
        for threshold in entry["guardrailThresholds"]:
            assert (
                f'{threshold["metric"]} {threshold["operator"]} '
                f'{threshold["value"]}'
            ) in strategy_text
        for dependency in entry["dependencies"]:
            for exact_value in (
                dependency["kind"],
                dependency["identity"],
                dependency["version"],
                dependency["contentHash"],
                "available" if dependency["available"] else "unavailable",
                (
                    "compatible"
                    if dependency["compatible"]
                    else "incompatible"
                ),
                (
                    "ready"
                    if dependency["available"] and dependency["compatible"]
                    else "blocked"
                ),
            ):
                assert str(exact_value) in strategy_text
        assert (
            "Formal Campaign ready"
            if entry["formalCampaignEligible"]
            else "Unavailable"
        ) in strategy_text

    root.setProperty("activeRoute", "scenario_lab")
    _settle(app)
    scenario_narrative = root.findChild(
        QObject,
        "scenarioLabSemanticNarrative",
    )
    scenario_interface = _interface(scenario_narrative)
    scenario_text = " ".join(
        (
            scenario_interface.text(QAccessible.Text.Name),
            scenario_interface.text(QAccessible.Text.Description),
        )
    )
    assert host._scenario_lab.sourceRevision in scenario_text
    for semantic in (
        "Baseline",
        "Isolated Sensitivity",
        "Compound",
        "Quick Experiment",
        "requested",
        "effective",
        "override",
    ):
        assert semantic.casefold() in scenario_text.casefold()

    _close(host, run_feature, evidence_feature)


def test_keyboard_route_actions_restore_meaningful_visible_focus_immediately():
    app = _app()
    host, run_feature, evidence_feature = _mounted_host()
    root = host.rootObject()
    pause = root.findChild(QQuickItem, "pauseDiagnosticTask")
    evidence_route = root.findChild(
        QQuickItem,
        "evidenceAndFindingsRouteNavigation",
    )
    run_route = root.findChild(QQuickItem, "runMonitoringRouteNavigation")

    pause.forceActiveFocus()
    app.processEvents()
    assert pause.property("activeFocus") is True
    assert pause.property("focusVisible") is True

    evidence_route.forceActiveFocus()
    QTest.keyClick(host, Qt.Key.Key_Return)
    app.processEvents()
    assert root.property("activeRoute") == "evidence_and_findings"

    candidate = root.property("evidenceInitialFocusItem")
    assert candidate is not None
    assert candidate.property("activeFocus") is True
    assert candidate.property("focusVisible") is True

    finding = root.property("evidenceFindingFocusItem")
    finding.forceActiveFocus()
    app.processEvents()
    assert finding.property("activeFocus") is True

    run_route.forceActiveFocus()
    QTest.keyClick(host, Qt.Key.Key_Space)
    app.processEvents()
    assert root.property("activeRoute") == "run_monitoring"
    assert pause.property("activeFocus") is True

    evidence_route.forceActiveFocus()
    _interface(evidence_route).actionInterface().doAction(
        QAccessibleActionInterface.pressAction()
    )
    app.processEvents()
    assert root.property("activeRoute") == "evidence_and_findings"
    restored_candidate = root.property("evidenceInitialFocusItem")
    assert restored_candidate is not None
    assert restored_candidate is not finding
    assert restored_candidate.property("activeFocus") is True
    assert restored_candidate.property("focusVisible") is True

    _close(host, run_feature, evidence_feature)


def test_evidence_semantics_keep_chart_narrative_and_table_on_one_revision():
    app = _app()
    host, run_feature, evidence_feature = _mounted_host()
    root = host.rootObject()
    root.setProperty("activeRoute", "evidence_and_findings")
    app.processEvents()
    adapter = host._evidence_and_findings

    status = root.findChild(QObject, "evidenceAccessibleStatus")
    chart = root.findChild(QObject, "evidenceChartPointSelection")
    narrative = root.findChild(QObject, "evidenceChartAccessibleNarrative")
    table = root.findChild(QObject, "evidenceChartAccessibleTable")
    finding = root.property("evidenceFindingFocusItem")
    alternate_finding = root.property("evidenceAlternateFindingFocusItem")

    revision = f"r{adapter.chartAcceptedRevision}"
    assert _interface(status).role() == QAccessible.Role.StatusBar
    assert revision in _accessible_name(narrative)
    assert revision in _accessible_name(table)
    assert "F-MODEL-B17-01" in _accessible_name(finding)
    assert bool(_interface(finding).state().selected) is True
    alternate_interface = _interface(alternate_finding)
    alternate_interface.actionInterface().doAction(
        QAccessibleActionInterface.pressAction()
    )
    app.processEvents()
    assert adapter.selectedFindingIdentity == "F-MODEL-B17-02"
    assert bool(alternate_interface.state().selected) is True
    assert "F-MODEL-B17-02" in _accessible_name(narrative)
    _wait_for(
        lambda: adapter.chartInteractionEnabled,
        app,
        "chart interaction did not re-enable after finding selection",
    )

    chart.forceActiveFocus()
    app.processEvents()
    assert chart.property("activeFocus") is True
    chart_interface = _interface(chart)
    assert chart_interface.role() == QAccessible.Role.Slider
    assert QAccessibleActionInterface.increaseAction() in (
        chart_interface.actionInterface().actionNames()
    )
    assert QAccessibleActionInterface.decreaseAction() in (
        chart_interface.actionInterface().actionNames()
    )
    before = adapter.selectedChartPointIndex
    chart_interface.actionInterface().doAction(
        QAccessibleActionInterface.decreaseAction()
    )
    _wait_for(
        lambda: adapter.selectedChartPointIndex < before,
        app,
        "accessible decrease action did not select the previous chart point",
    )
    assert revision in _accessible_name(narrative)
    assert revision in _accessible_name(table)
    assert f"#{adapter.selectedChartPointIndex}" in _accessible_name(narrative)
    assert f"#{adapter.selectedChartPointIndex}" in _accessible_name(table)

    _close(host, run_feature, evidence_feature)


def test_state_changes_remain_distinguishable_and_repair_focus_without_color():
    app = _app()
    host, run_feature, evidence_feature = _mounted_host()
    root = host.rootObject()
    run_status = root.findChild(QObject, "runMonitoringAccessibleStatus")
    pause = root.findChild(QQuickItem, "pauseDiagnosticTask")
    run_route = root.findChild(QQuickItem, "runMonitoringRouteNavigation")
    evidence_route = root.findChild(
        QQuickItem,
        "evidenceAndFindingsRouteNavigation",
    )

    run_route.forceActiveFocus()
    run_feature.advance_to_partial(_run_context())
    _settle(app)
    assert "partial" in _accessible_name(run_status).casefold()
    assert run_route.property("activeFocus") is True

    pause.forceActiveFocus()
    _settle(app)
    assert pause.property("activeFocus") is True

    run_feature.advance_to_stale(_run_context())
    _settle(app)
    assert "stale" in _interface(run_status).text(
        QAccessible.Text.Description
    ).casefold()

    run_feature.advance_to_disconnected(_run_context())
    _settle(app)
    assert "disconnected" in _accessible_name(run_status).casefold()
    assert run_route.property("activeFocus") is True

    run_feature.advance_to_reconnected(_run_context())
    _settle(app)
    assert "fresh" in _interface(run_status).text(
        QAccessible.Text.Description
    ).casefold()
    assert run_route.property("activeFocus") is True

    run_feature.advance_to_failed(_run_context())
    _settle(app)
    assert "failed" in _accessible_name(run_status).casefold()
    assert "diagnostic run failed" in _interface(run_status).text(
        QAccessible.Text.Description
    ).casefold()
    assert run_route.property("activeFocus") is True

    root.setProperty("activeRoute", "evidence_and_findings")
    app.processEvents()
    evidence_status = root.findChild(QObject, "evidenceAccessibleStatus")
    evidence_route_status = root.findChild(
        QObject,
        "evidenceRouteFreshnessStatus",
    )
    assert _interface(evidence_route_status).role() == (
        QAccessible.Role.StatusBar
    )
    finding = root.property("evidenceFindingFocusItem")
    evidence_route.forceActiveFocus()

    evidence_feature.advance_to_partial(_evidence_context())
    _settle(app)
    assert "partial" in _interface(evidence_status).text(
        QAccessible.Text.Description
    ).casefold()
    assert evidence_route.property("activeFocus") is True

    finding.forceActiveFocus()
    _settle(app)
    assert finding.property("activeFocus") is True

    evidence_feature.advance_to_stale(_evidence_context())
    _settle(app)
    assert "stale" in _interface(evidence_status).text(
        QAccessible.Text.Description
    ).casefold()
    assert "stale" in _accessible_name(evidence_route_status).casefold()

    evidence_feature.advance_to_disconnected(_evidence_context())
    _settle(app)
    assert "disconnected" in _accessible_name(evidence_status).casefold()
    assert (
        "disconnected"
        in _accessible_name(evidence_route_status).casefold()
    )

    evidence_feature.advance_to_failed(_evidence_context())
    _settle(app)
    assert "failed" in _accessible_name(evidence_status).casefold()
    assert "failed" in _interface(evidence_status).text(
        QAccessible.Text.Description
    ).casefold()

    _close(host, run_feature, evidence_feature)


def test_remount_reestablishes_meaningful_keyboard_focus_without_state_mutation():
    app = _app()
    first, run_feature, evidence_feature = _mounted_host()
    setup_features = first._accessibility_feature_owners
    first_root = first.rootObject()
    run_revision = run_feature.snapshot(_run_context()).revision
    evidence_revision = evidence_feature.snapshot(_evidence_context()).revision

    first_root.setProperty("activeRoute", "evidence_and_findings")
    _settle(app)
    first_finding = first_root.property("evidenceFindingFocusItem")
    first_finding.forceActiveFocus()
    _settle(app)
    assert first_finding.property("activeFocus") is True

    _close_host(first)
    _settle(app)
    assert run_feature.snapshot(_run_context()).revision == run_revision
    assert (
        evidence_feature.snapshot(_evidence_context()).revision
        == evidence_revision
    )

    second = JourneyWorkspaceHost(
        run_feature,
        context=_run_context(),
        strategy_library_feature=setup_features[0],
        strategy_library_context=StrategyLibraryContext(),
        scenario_lab_feature=setup_features[1],
        scenario_lab_context=ScenarioLabContext(),
        diagnostic_tasks_feature=setup_features[2],
        diagnostic_tasks_context=DiagnosticTasksContext.workspace(),
        evidence_feature=evidence_feature,
        evidence_context=_evidence_context(),
        system_health_feature=setup_features[3],
        system_health_context=SystemHealthContext(),
        initial_route="run_monitoring",
    )
    second._accessibility_feature_owners = setup_features
    second.resize(1280, 720)
    second.show()
    _settle(app)
    second_root = second.rootObject()
    second_pause = second_root.findChild(QQuickItem, "pauseDiagnosticTask")
    assert second_pause.property("activeFocus") is True
    assert second_pause.property("focusVisible") is True

    second_root.setProperty("activeRoute", "evidence_and_findings")
    _settle(app)
    second_candidate = second_root.property("evidenceInitialFocusItem")
    assert second_candidate.property("activeFocus") is True
    assert second_candidate.property("focusVisible") is True
    assert run_feature.snapshot(_run_context()).revision == run_revision
    assert (
        evidence_feature.snapshot(_evidence_context()).revision
        == evidence_revision
    )

    _close(second, run_feature, evidence_feature)


def test_200_percent_text_scale_scrolls_focused_content_and_reduces_motion():
    app = _app()
    host, run_feature, evidence_feature = _mounted_host(
        preferences=AccessibilityPreferences(
            text_scale=2.0,
            reduced_motion=True,
            high_contrast=True,
        )
    )
    root = host.rootObject()
    tokens = root.findChild(QObject, "designTokens")
    run_scroll = root.findChild(QQuickItem, "runMonitoringFlickable")
    run_grid = root.findChild(QObject, "runMonitoringResearchGrid")
    cancel = root.findChild(QQuickItem, "cancelDiagnosticTask")
    run_route = root.findChild(QQuickItem, "runMonitoringRouteNavigation")
    evidence_route = root.findChild(
        QQuickItem,
        "evidenceAndFindingsRouteNavigation",
    )
    rail_scroll = root.findChild(QQuickItem, "journeyRailFlickable")

    def assert_within_viewport(item: QQuickItem) -> None:
        top_left = item.mapToItem(root, QPointF(0, 0))
        assert top_left.x() >= 0
        assert top_left.x() + item.property("width") <= root.property(
            "width"
        )

    assert tokens.property("textScale") == 2.0
    assert tokens.property("bodySize") == 26
    assert tokens.property("durationForMotion") == 0
    assert rail_scroll is not None
    assert rail_scroll.property("contentHeight") > rail_scroll.property("height")
    assert run_scroll.property("contentHeight") > run_scroll.property("height")
    assert run_grid.property("columns") == 1
    assert cancel.property("scale") == 1.0
    assert_within_viewport(run_route)
    assert_within_viewport(evidence_route)
    for route_name in (
        "strategyLibraryRouteNavigation",
        "scenarioLabRouteNavigation",
        "diagnosticTasksRouteNavigation",
        "runMonitoringRouteNavigation",
        "evidenceAndFindingsRouteNavigation",
        "systemHealthRouteNavigation",
    ):
        route_item = root.findChild(QQuickItem, route_name)
        route_item.forceActiveFocus()
        _settle(app)
        rail_top = route_item.mapToItem(rail_scroll, QPointF(0, 0)).y()
        assert rail_top >= 0
        assert rail_top + route_item.property("height") <= rail_scroll.property(
            "height"
        )
    for object_name in (
        "runMonitoringAccessibleStatus",
        "runMonitoringResearchGrid",
        "diagnosticCommandFeedback",
        "pauseDiagnosticTask",
        "resumeDiagnosticTask",
        "cancelDiagnosticTask",
    ):
        assert_within_viewport(root.findChild(QQuickItem, object_name))

    cancel.forceActiveFocus()
    app.processEvents()
    assert cancel.property("activeFocus") is True
    assert cancel.property("focusVisible") is True
    assert run_scroll.property("contentY") > 0

    root.setProperty("activeRoute", "evidence_and_findings")
    _settle(app)
    evidence_grid = root.findChild(QObject, "evidenceResearchGrid")
    candidate_grid = root.findChild(
        QObject,
        "evidenceCandidateControlsGrid",
    )
    assert evidence_grid.property("columns") == 1
    assert candidate_grid.property("columns") == 1
    first_candidate = root.property("evidenceInitialFocusItem")
    second_candidate = root.property("evidenceSecondCandidateFocusItem")
    for candidate in (first_candidate, second_candidate):
        assert_within_viewport(candidate)
    for object_name in (
        "evidenceAccessibleStatus",
        "evidenceChartSurface",
        "evidenceResearchGrid",
        "evidenceViewportCompound",
    ):
        assert_within_viewport(root.findChild(QQuickItem, object_name))
    assert second_candidate.mapToItem(root, QPointF(0, 0)).y() > (
        first_candidate.mapToItem(root, QPointF(0, 0)).y()
    )

    root.setProperty("activeRoute", "system_health")
    _settle(app)
    health_scroll = root.findChild(QQuickItem, "systemHealthFlickable")
    health_grid = root.findChild(QObject, "systemHealthComponentGrid")
    health_source = root.findChild(QQuickItem, "dataSourceAccessibleStatus")
    assert health_scroll.property("contentHeight") > health_scroll.property(
        "height"
    )
    assert health_grid.property("columns") == 1
    health_source.forceActiveFocus()
    _wait_for(
        lambda: health_scroll.property("contentY") > 0,
        app,
        "System Health did not scroll the focused data-source status into view",
    )
    assert health_source.property("activeFocus") is True
    assert health_scroll.property("contentY") > 0
    health_top = health_source.mapToItem(root, QPointF(0, 0)).y()
    assert health_top >= 0
    assert health_top + health_source.property("height") <= root.property(
        "height"
    )

    root.setProperty("activeRoute", "scenario_lab")
    _settle(app)
    scenario_scroll = root.findChild(QQuickItem, "scenarioLabFlickable")
    scenario_action = root.findChild(
        QQuickItem,
        "scenarioLabCreateRecipeDraftButton",
    )
    assert scenario_scroll.property("contentHeight") > scenario_scroll.property(
        "height"
    )
    scenario_action.forceActiveFocus()
    _settle(app)
    scenario_top = scenario_action.mapToItem(root, QPointF(0, 0)).y()
    assert scenario_scroll.property("contentY") > 0
    assert scenario_top >= 0
    assert scenario_top + scenario_action.property("height") <= root.property(
        "height"
    )

    image = host.grab().toImage()
    assert image.isNull() is False
    assert image.width() > 0
    assert image.height() > 0

    _close(host, run_feature, evidence_feature)


def test_six_live_feature_adapters_drive_the_public_accessible_journey(
    tmp_path,
    monkeypatch,
):
    app = _app()
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    bridge = EventBridge(subscribe_backend=False)
    context = build_app_context(
        settings_path=str(tmp_path / "live-accessible-settings.json"),
        run_monitoring_mode="live",
        event_bridge=bridge,
        runtime_gateway=object(),
    )
    assert isinstance(context.strategy_library_feature, LiveStrategyLibraryAdapter)
    assert isinstance(context.scenario_lab_feature, LiveScenarioLabAdapter)
    assert isinstance(context.diagnostic_tasks_feature, LiveDiagnosticTasksAdapter)
    assert isinstance(context.run_monitoring_feature, LiveRunMonitoringAdapter)
    assert isinstance(
        context.evidence_and_findings_feature,
        LiveEvidenceAndFindingsAdapter,
    )
    assert isinstance(context.system_health_feature, LiveSystemHealthAdapter)

    host = JourneyWorkspaceHost(
        context.run_monitoring_feature,
        context=context.run_monitoring_context,
        strategy_library_feature=context.strategy_library_feature,
        strategy_library_context=context.strategy_library_context,
        scenario_lab_feature=context.scenario_lab_feature,
        scenario_lab_context=context.scenario_lab_context,
        diagnostic_tasks_feature=context.diagnostic_tasks_feature,
        diagnostic_tasks_context=context.diagnostic_tasks_context,
        diagnostic_setup_selection_coordinator=(
            context.diagnostic_setup_selection_coordinator
        ),
        evidence_feature=context.evidence_and_findings_feature,
        evidence_context=context.evidence_and_findings_context,
        system_health_feature=context.system_health_feature,
        system_health_context=context.system_health_context,
        initial_route="strategy_library",
    )
    host.resize(1280, 720)
    host.show()
    _settle(app)
    root = host.rootObject()
    routes = (
        (
            "strategy_library",
            "strategyLibraryRouteNavigation",
            "strategyLibraryInitialFocusItem",
            "strategyLibraryAccessibleStatus",
        ),
        (
            "scenario_lab",
            "scenarioLabRouteNavigation",
            "scenarioLabInitialFocusItem",
            "scenarioLabAccessibleStatus",
        ),
        (
            "diagnostic_tasks",
            "diagnosticTasksRouteNavigation",
            "diagnosticTasksInitialFocusItem",
            "diagnosticTasksAccessibleStatus",
        ),
        (
            "run_monitoring",
            "runMonitoringRouteNavigation",
            "runMonitoringInitialFocusItem",
            "runMonitoringAccessibleStatus",
        ),
        (
            "evidence_and_findings",
            "evidenceAndFindingsRouteNavigation",
            "evidenceInitialFocusItem",
            "evidenceAccessibleStatus",
        ),
        (
            "system_health",
            "systemHealthRouteNavigation",
            "systemHealthInitialFocusItem",
            "systemHealthAccessibleStatus",
        ),
    )
    try:
        for route, navigation_name, focus_property, status_name in routes:
            navigation = root.findChild(QQuickItem, navigation_name)
            navigation.forceActiveFocus()
            QTest.keyClick(host, Qt.Key.Key_Return)
            _wait_for(
                lambda: root.property("activeRoute") == route
                and (
                    (
                        root.property(focus_property) is not None
                        and root.property(focus_property).property("activeFocus")
                    )
                    or (
                        route == "evidence_and_findings"
                        and navigation.property("activeFocus")
                    )
                ),
                app,
                f"live {route} did not restore authoritative focus",
            )
            focus_item = root.property(focus_property)
            if focus_item is None or not focus_item.property("activeFocus"):
                focus_item = navigation
            assert focus_item.property("focusVisible") is True
            status = root.findChild(QObject, status_name)
            status_interface = _interface(status)
            assert status_interface.role() == QAccessible.Role.StatusBar
            assert status_interface.text(QAccessible.Text.Name).strip()
            assert status_interface.text(QAccessible.Text.Description).strip()

        announcement = root.findChild(QQuickItem, "systemHealthAnnouncement")
        assert announcement is not None
        assert _interface(announcement).role() == QAccessible.Role.AlertMessage
        assert "system health update" in _accessible_name(
            announcement
        ).casefold()
    finally:
        _close_host(host)
        context.close()
        bridge.stop()


def test_all_six_routes_restore_meaningful_focus_after_authoritative_return():
    app = _app()
    host, run_feature, evidence_feature = _mounted_host()
    root = host.rootObject()
    routes = (
        (
            JourneyWorkspaceRoute.STRATEGY_LIBRARY,
            "strategyLibraryInitialFocusItem",
        ),
        (JourneyWorkspaceRoute.SCENARIO_LAB, "scenarioLabInitialFocusItem"),
        (
            JourneyWorkspaceRoute.DIAGNOSTIC_TASKS,
            "diagnosticTasksInitialFocusItem",
        ),
        (JourneyWorkspaceRoute.RUN_MONITORING, "runMonitoringInitialFocusItem"),
        (
            JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS,
            "evidenceInitialFocusItem",
        ),
        (JourneyWorkspaceRoute.SYSTEM_HEALTH, "systemHealthInitialFocusItem"),
    )

    for index, (route, focus_property) in enumerate(routes):
        assert host.activate_route(route) is True
        _wait_for(
            lambda: root.property("activeRoute") == route.value
            and root.property(focus_property) is not None
            and root.property(focus_property).property("activeFocus"),
            app,
            f"{route.value} did not receive authoritative entry focus",
        )
        initial_focus = root.property(focus_property)
        initial_object_name = initial_focus.objectName()
        assert initial_object_name
        assert initial_focus.property("focusVisible") is True

        alternate_route = routes[(index + 1) % len(routes)][0]
        assert host.activate_route(alternate_route) is True
        _wait_for(
            lambda: root.property("activeRoute") == alternate_route.value,
            app,
            f"{alternate_route.value} did not activate",
        )
        assert host.activate_route(route) is True
        _wait_for(
            lambda: root.property("activeRoute") == route.value
            and root.property(focus_property) is not None
            and root.property(focus_property).objectName()
            == initial_object_name
            and root.property(focus_property).property("activeFocus"),
            app,
            f"{route.value} did not restore meaningful focus after return",
        )
        restored = root.property(focus_property)
        assert restored.property("focusVisible") is True
        assert restored.property("visible") is True
        assert restored.property("enabled") is True

    _close(host, run_feature, evidence_feature)


def test_initial_evidence_route_loads_asynchronously_with_safe_public_focus():
    app = _app()
    host, run_feature, evidence_feature = _mounted_host(
        initial_route="evidence_and_findings",
    )
    root = host.rootObject()
    loader = root.findChild(QObject, "evidenceAndFindingsPageLoader")
    route = root.findChild(QQuickItem, "evidenceAndFindingsRouteNavigation")

    assert loader is not None
    assert loader.property("asynchronous") is True
    _wait_for(
        lambda: root.property("evidenceInitialFocusItem") is not None
        and root.property("evidenceInitialFocusItem").property("activeFocus"),
        app,
        "Initial Evidence route did not restore public focus after loading",
    )
    assert route.property("visible") is True
    assert root.findChild(QObject, "evidenceAccessibleStatus") is not None
    assert root.findChild(QObject, "runMonitoringFlickable") is None

    assert host.activate_route(JourneyWorkspaceRoute.RUN_MONITORING)
    _wait_for(
        lambda: root.findChild(QObject, "runMonitoringFlickable") is not None
        and root.property("runMonitoringInitialFocusItem") is not None
        and root.property("runMonitoringInitialFocusItem").property("activeFocus"),
        app,
        "Deferred Run Monitoring route did not load and restore public focus",
    )
    assert root.findChild(QObject, "pauseDiagnosticTask") is not None

    _close(host, run_feature, evidence_feature)


def test_initial_evidence_route_restores_page_focus_after_late_state():
    app = _app()
    host, run_feature, evidence_feature = _mounted_host(
        initial_route="evidence_and_findings",
        evidence_ready=False,
    )
    root = host.rootObject()
    route = root.findChild(QQuickItem, "evidenceAndFindingsRouteNavigation")

    _wait_for(
        lambda: route.property("activeFocus"),
        app,
        "Initial Evidence loading did not retain a safe public route focus",
    )
    assert root.property("evidenceInitialFocusItem") is None

    evidence_feature.advance_to_completed(_evidence_context())
    _wait_for(
        lambda: root.property("evidenceInitialFocusItem") is not None
        and root.property("evidenceInitialFocusItem").property("activeFocus")
        and root.property("evidenceInitialFocusItem").property("focusVisible"),
        app,
        "Authoritative Evidence state did not restore visible page focus",
    )

    _close(host, run_feature, evidence_feature)


def test_initial_evidence_route_restores_focus_when_shown_after_async_load():
    app = _app()
    host, run_feature, evidence_feature = _mounted_host(
        initial_route="evidence_and_findings",
        show_host=False,
    )
    root = host.rootObject()
    _wait_for(
        lambda: root.property("evidenceInitialFocusItem") is not None,
        app,
        "Hidden initial Evidence route did not finish loading",
    )
    target = root.property("evidenceInitialFocusItem")
    loader = root.findChild(QObject, "evidenceAndFindingsPageLoader")
    assert loader.property("asynchronous") is True
    target.setFocus(False)
    assert not target.property("activeFocus")

    host.show()
    _wait_for(
        lambda: target.property("activeFocus")
        and target.property("focusVisible"),
        app,
        "Parent window show did not restore visible Evidence page focus",
    )

    _close(host, run_feature, evidence_feature)


def test_show_preserves_meaningful_evidence_page_focus():
    app = _app()
    host, run_feature, evidence_feature = _mounted_host(
        initial_route="evidence_and_findings",
    )
    root = host.rootObject()
    _wait_for(
        lambda: root.property("evidenceSecondCandidateFocusItem") is not None,
        app,
        "Evidence candidate controls did not finish loading",
    )
    target = root.property("evidenceSecondCandidateFocusItem")
    target.forceActiveFocus()
    app.processEvents()
    assert target.property("activeFocus") is True

    host.hide()
    app.processEvents()
    host.show()
    _wait_for(
        lambda: target.property("activeFocus"),
        app,
        "Window show did not preserve the meaningful Evidence page focus",
    )
    _close(host, run_feature, evidence_feature)


def test_initial_evidence_focus_token_preserves_exact_synchronous_restore():
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    evidence_feature = DeterministicFakeEvidenceAndFindingsAdapter()
    run_feature.advance_to_running(_run_context())
    evidence_feature.advance_to_completed(_evidence_context())
    window = MainWindow(
        journey_workspace_bookmark=JourneyWorkspaceBookmark(
            last_route=JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS,
            presentation=JourneyPresentationSelection(
                focus_return_token=JourneyFocusReturnToken(
                    route=JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS,
                    control="evidenceCandidate-MODEL-B17",
                    identity="MODEL-B17",
                ),
            ),
        ),
        run_monitoring_feature=run_feature,
        run_monitoring_context=_run_context(),
        evidence_and_findings_feature=evidence_feature,
        evidence_and_findings_context=_evidence_context(),
        frontend_v2_enabled=True,
    )
    host = window.centralWidget()
    root = host.rootObject()
    loader = root.findChild(QObject, "evidenceAndFindingsPageLoader")

    assert loader.property("asynchronous") is False
    window.show()
    _wait_for(
        lambda: root.property("evidenceInitialFocusItem") is not None
        and root.property("evidenceInitialFocusItem").objectName()
        == "evidenceCandidate-MODEL-B17"
        and root.property("evidenceInitialFocusItem").property("activeFocus"),
        app,
        "Exact persisted Evidence focus token was not restored",
    )

    host.close_adapter()
    window.close()
    run_feature.close()
    evidence_feature.close()


def test_noninitial_evidence_route_preserves_synchronous_route_semantics():
    host, run_feature, evidence_feature = _mounted_host()
    root = host.rootObject()
    loader = root.findChild(QObject, "evidenceAndFindingsPageLoader")

    assert loader is not None
    assert loader.property("asynchronous") is False
    assert host.activate_route(JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS)
    assert root.property("evidenceInitialFocusItem") is not None
    assert root.findChild(QObject, "evidenceAccessibleStatus") is not None

    _close(host, run_feature, evidence_feature)


def test_system_health_announces_semantic_changes_once_with_safe_explanations():
    app = _app()
    health_feature = DeterministicFakeSystemHealthAdapter(
        initially_healthy=True,
    )
    host, run_feature, evidence_feature = _mounted_host(
        system_health_feature=health_feature,
    )
    root = host.rootObject()
    system_route = root.findChild(QQuickItem, "systemHealthRouteNavigation")
    system_route.forceActiveFocus()
    QTest.keyClick(host, Qt.Key.Key_Return)
    _wait_for(
        lambda: root.property("activeRoute") == "system_health",
        app,
        "System Health route did not activate",
    )
    announcement = root.findChild(QQuickItem, "systemHealthAnnouncement")
    assert announcement is not None
    assert _interface(announcement).role() == QAccessible.Role.AlertMessage
    changed = QSignalSpy(announcement.textChanged)

    health_feature.advance_to_degraded()
    _wait_for(
        lambda: "degraded" in _accessible_name(announcement).casefold(),
        app,
        "degraded System Health was not announced",
    )
    degraded_count = changed.count()
    degraded_text = _accessible_name(announcement).casefold()
    for semantic in (
        "system health update",
        "overall degraded",
        "runtime",
        "data source",
        "queue",
        "cache",
        "persistence",
        "version",
    ):
        assert semantic in degraded_text

    health_feature.publish_authoritative_observation()
    _settle(app)
    assert changed.count() == degraded_count

    health_feature.advance_to_disconnected()
    _wait_for(
        lambda: "disconnected" in _accessible_name(announcement).casefold(),
        app,
        "disconnected System Health was not announced",
    )
    disconnected_text = _accessible_name(announcement).casefold()
    assert "structured error" in disconnected_text
    assert "affected" in disconnected_text
    assert "recovery" in disconnected_text
    assert "data-source structured error" in disconnected_text

    health_feature.advance_data_source_to_fallback()
    _wait_for(
        lambda: "fallback active"
        in _accessible_name(announcement).casefold(),
        app,
        "data-source fallback was not announced",
    )

    health_feature.advance_to_reconnected()
    _wait_for(
        lambda: any(
            state in _accessible_name(announcement).casefold()
            for state in ("recovering", "recovered")
        ),
        app,
        "System Health recovery was not announced",
    )

    before_cache_change = changed.count()
    health_feature.advance_cache_to_fallback()
    _wait_for(
        lambda: changed.count() > before_cache_change
        and "cache fallback, fallback active"
        in _accessible_name(announcement).casefold(),
        app,
        "cache fallback semantics were not announced",
    )

    health_feature.advance_to_failed()
    _wait_for(
        lambda: "observation failed"
        in _accessible_name(announcement).casefold(),
        app,
        "failed System Health was not announced with a safe explanation",
    )
    safe_text = _accessible_name(announcement).casefold()
    health_status = root.findChild(QQuickItem, "systemHealthAccessibleStatus")
    assert health_status.property("activeFocus") is True
    assert health_status.property("focusVisible") is True
    for forbidden in (
        "database url",
        "select ",
        "traceback",
        "credential",
        "token=",
        "c:\\",
        "powershell",
        "python.exe",
        "object at 0x",
        "buy",
        "sell",
        "restart",
    ):
        assert forbidden not in safe_text

    _close(host, run_feature, evidence_feature)


@pytest.mark.parametrize(
    "preferences",
    (
        None,
        AccessibilityPreferences(high_contrast=True),
    ),
)
def test_shared_default_and_high_contrast_tokens_meet_wcag_aa_ratios(
    preferences,
):
    host, run_feature, evidence_feature = _mounted_host(
        preferences=preferences,
    )
    tokens = host.rootObject().findChild(QObject, "designTokens")

    def luminance(color) -> float:
        values = []
        for channel in (color.redF(), color.greenF(), color.blueF()):
            values.append(
                channel / 12.92
                if channel <= 0.04045
                else ((channel + 0.055) / 1.055) ** 2.4
            )
        return (
            0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2]
        )

    def contrast(first, second) -> float:
        bright, dark = sorted(
            (luminance(first), luminance(second)),
            reverse=True,
        )
        return (bright + 0.05) / (dark + 0.05)

    surface = tokens.property("surface")
    assert contrast(tokens.property("textPrimary"), surface) >= 4.5
    assert contrast(tokens.property("textMuted"), surface) >= 4.5
    assert contrast(tokens.property("textQuiet"), surface) >= 4.5
    assert contrast(tokens.property("border"), surface) >= 3.0
    assert contrast(tokens.property("focus"), surface) >= 3.0

    _close(host, run_feature, evidence_feature)
