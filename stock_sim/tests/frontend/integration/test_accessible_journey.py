import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtGui import QAccessible, QAccessibleActionInterface
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.features import (
    ApprovedScenarioRecipeId,
    DeterministicFakeEvidenceAndFindingsAdapter,
    DeterministicFakeRunMonitoringAdapter,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsSelection,
    FormalDiagnosticCampaignId,
    MarketScenarioId,
    ReproductionManifestId,
    RunMonitoringContext,
    RunMonitoringSelection,
    StrategyRunId,
    StrategyUnderTestId,
)
from app.ui.accessibility import AccessibilityPreferences
from app.ui.journey_workspace import JourneyWorkspaceHost


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
) -> tuple[
    JourneyWorkspaceHost,
    DeterministicFakeRunMonitoringAdapter,
    DeterministicFakeEvidenceAndFindingsAdapter,
]:
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    evidence_feature = DeterministicFakeEvidenceAndFindingsAdapter()
    run_feature.advance_to_running(_run_context())
    evidence_feature.advance_to_completed(_evidence_context())
    host = JourneyWorkspaceHost(
        run_feature,
        context=_run_context(),
        evidence_feature=evidence_feature,
        evidence_context=_evidence_context(),
        accessibility_preferences=preferences,
    )
    host.resize(1280, 720)
    host.show()
    app.processEvents()
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


def _close(
    host: JourneyWorkspaceHost,
    run_feature: DeterministicFakeRunMonitoringAdapter,
    evidence_feature: DeterministicFakeEvidenceAndFindingsAdapter,
) -> None:
    host.close_adapter()
    host.close()
    run_feature.close()
    evidence_feature.close()


def test_narrator_sees_named_state_progress_commands_and_no_trading_actions():
    host, run_feature, evidence_feature = _mounted_host()
    root = host.rootObject()

    status = root.findChild(QObject, "runMonitoringAccessibleStatus")
    progress = root.findChild(QObject, "runMonitoringAccessibleProgress")
    pause = root.findChild(QObject, "pauseDiagnosticTask")
    route = root.findChild(QObject, "runMonitoringRouteNavigation")

    status_interface = _interface(status)
    progress_interface = _interface(progress)
    pause_interface = _interface(pause)
    route_interface = _interface(route)

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
    assert finding.property("activeFocus") is True

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
    QTest.qWait(60)
    app.processEvents()
    assert adapter.selectedChartPointIndex < before
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

    evidence_feature.advance_to_disconnected(_evidence_context())
    _settle(app)
    assert "disconnected" in _accessible_name(evidence_status).casefold()

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
    first_root = first.rootObject()
    run_revision = run_feature.snapshot(_run_context()).revision
    evidence_revision = evidence_feature.snapshot(_evidence_context()).revision

    first_root.setProperty("activeRoute", "evidence_and_findings")
    _settle(app)
    first_finding = first_root.property("evidenceFindingFocusItem")
    first_finding.forceActiveFocus()
    _settle(app)
    assert first_finding.property("activeFocus") is True

    first.close_adapter()
    first.close()
    _settle(app)
    assert run_feature.snapshot(_run_context()).revision == run_revision
    assert (
        evidence_feature.snapshot(_evidence_context()).revision
        == evidence_revision
    )

    second = JourneyWorkspaceHost(
        run_feature,
        context=_run_context(),
        evidence_feature=evidence_feature,
        evidence_context=_evidence_context(),
    )
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

    second.close_adapter()
    second.close()
    run_feature.close()
    evidence_feature.close()


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
    evidence_grid = root.findChild(QObject, "evidenceResearchGrid")
    candidate_grid = root.findChild(
        QObject,
        "evidenceCandidateControlsGrid",
    )
    cancel = root.findChild(QQuickItem, "cancelDiagnosticTask")
    run_route = root.findChild(QQuickItem, "runMonitoringRouteNavigation")
    evidence_route = root.findChild(
        QQuickItem,
        "evidenceAndFindingsRouteNavigation",
    )

    def assert_within_viewport(item: QQuickItem) -> None:
        top_left = item.mapToItem(root, QPointF(0, 0))
        assert top_left.x() >= 0
        assert top_left.x() + item.property("width") <= root.property(
            "width"
        )

    assert tokens.property("textScale") == 2.0
    assert tokens.property("bodySize") == 26
    assert tokens.property("durationForMotion") == 0
    assert run_scroll.property("contentHeight") > run_scroll.property("height")
    assert run_grid.property("columns") == 1
    assert evidence_grid.property("columns") == 1
    assert candidate_grid.property("columns") == 1
    assert cancel.property("scale") == 1.0
    assert_within_viewport(run_route)
    assert_within_viewport(evidence_route)
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

    image = host.grab().toImage()
    assert image.isNull() is False
    assert image.width() > 0
    assert image.height() > 0

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
