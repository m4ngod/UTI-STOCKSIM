import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QObject, Qt
from PySide6.QtQuick import QQuickItem, QQuickPaintedItem
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
    StrategyRunId,
    StrategyUnderTestId,
)
from app.ui.main_window import MainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _context() -> EvidenceAndFindingsContext:
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


def test_qml_route_mounts_production_chart_with_one_synchronized_revision():
    app = _app()
    context = _context()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    evidence_feature = DeterministicFakeEvidenceAndFindingsAdapter()
    evidence_state = evidence_feature.advance_to_completed(context)
    window = MainWindow(
        run_monitoring_feature=run_feature,
        evidence_and_findings_feature=evidence_feature,
        evidence_and_findings_context=context,
        frontend_v2_enabled=True,
    )
    host = window.centralWidget()
    root = host.rootObject()
    root.setProperty("activeRoute", "evidence_and_findings")
    app.processEvents()
    adapter = host._evidence_and_findings
    renderer = root.findChild(QQuickItem, "productionEvidenceChart")
    mount = root.findChild(QObject, "evidenceChartMount")

    assert mount is not None
    assert isinstance(renderer, QQuickItem)
    assert not isinstance(renderer, QQuickPaintedItem)
    assert renderer.parentItem() is mount
    assert renderer.property("acceptedRevision") == evidence_state.revision
    assert adapter.chartAcceptedRevision == evidence_state.revision
    assert adapter.chartSourcePointCount == 100_000
    assert adapter.chartVisiblePointCount == 4_000
    assert adapter.chartOverlayCount == 3
    for identity in (
        "frontend-v2-evidence-and-findings-fake",
        "FDC-001",
        "RUN-001",
        "MODEL-B17",
        "MODEL-B17-diagnostic-series",
    ):
        assert identity in adapter.chartSourceIdentity
    revision_marker = f"Accepted evidence revision · r{evidence_state.revision}"
    assert revision_marker in adapter.chartNarrativeText
    assert revision_marker in adapter.chartTableText
    assert (
        renderer.property("samplePointCount")
        == adapter.chartVisiblePointCount
    )
    assert renderer.property("overlayCount") == adapter.chartOverlayCount
    assert "sha256:" in adapter.provenanceText

    window.close()
    run_feature.close()
    evidence_feature.close()


def test_research_selections_update_chart_narrative_and_table_without_mutation():
    app = _app()
    context = _context()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    evidence_feature = DeterministicFakeEvidenceAndFindingsAdapter()
    evidence_feature.advance_to_completed(context)
    window = MainWindow(
        run_monitoring_feature=run_feature,
        evidence_and_findings_feature=evidence_feature,
        evidence_and_findings_context=context,
        frontend_v2_enabled=True,
    )
    host = window.centralWidget()
    root = host.rootObject()
    root.setProperty("activeRoute", "evidence_and_findings")
    app.processEvents()
    adapter = host._evidence_and_findings
    renderer = root.findChild(QQuickItem, "productionEvidenceChart")
    stored_revision = evidence_feature.snapshot(context).revision
    initial_frame_sequence = renderer.property("frameSequence")

    adapter.selectCandidate("MODEL-A04")
    adapter.selectFinding("F-MODEL-A04-02")
    adapter.setViewportIntent("sensitivity")
    QTest.qWait(60)
    app.processEvents()

    adapter.selectChartPointAtRatio(0.25)
    QTest.qWait(60)
    app.processEvents()

    adapter.selectChartOverlay("OV-MODEL-A04-DRAWDOWN")
    QTest.qWait(60)
    app.processEvents()

    adapter.selectChartBreakpoint("BP-MODEL-A04-FEE")

    assert adapter.chartInteractionEnabled is True
    assert evidence_feature.snapshot(context).revision == stored_revision
    assert adapter.chartAcceptedRevision == stored_revision
    assert renderer.property("acceptedRevision") == stored_revision
    assert renderer.property("frameSequence") > initial_frame_sequence
    assert (
        renderer.property("selectedPointSourceIndex")
        == adapter.selectedChartPointIndex
    )
    assert 25_000 <= adapter.selectedChartPointIndex <= 70_000
    assert (
        renderer.property("selectedOverlayIdentity")
        == adapter.selectedChartOverlayIdentity
        == "OV-MODEL-A04-DRAWDOWN"
    )
    assert (
        renderer.property("selectedFindingIdentity")
        == "F-MODEL-A04-02"
    )
    assert (
        renderer.property("selectedBreakpointIdentity")
        == "BP-MODEL-A04-FEE"
    )
    for representation in (
        adapter.chartNarrativeText,
        adapter.chartTableText,
    ):
        assert f"Accepted evidence revision · r{stored_revision}" in representation
        assert "MODEL-A04" in representation
        assert "F-MODEL-A04-02" in representation
        assert f"#{adapter.selectedChartPointIndex}" in representation
        assert "OV-MODEL-A04-DRAWDOWN" in representation
        assert "BP-MODEL-A04-FEE" in representation
        assert "Limit-up rules block the assumed entry path" in representation

    point_control = root.findChild(QQuickItem, "evidenceChartPointSelection")
    focus_indicator = root.findChild(
        QQuickItem,
        "evidenceChartFocusIndicator",
    )
    overlay_repeater = root.findChild(QObject, "evidenceChartOverlayRepeater")
    breakpoint_repeater = root.findChild(
        QObject,
        "evidenceChartBreakpointRepeater",
    )
    assert point_control is not None
    assert overlay_repeater.property("count") == 3
    assert breakpoint_repeater.property("count") == 1

    point_control.forceActiveFocus()
    app.processEvents()
    assert focus_indicator is not None
    assert focus_indicator.property("visible") is True
    selected_before_keyboard = adapter.selectedChartPointIndex
    QTest.keyClick(host, Qt.Key.Key_Right)
    QTest.qWait(60)
    app.processEvents()

    assert adapter.selectedChartPointIndex > selected_before_keyboard
    assert (
        renderer.property("selectedPointSourceIndex")
        == adapter.selectedChartPointIndex
    )
    assert focus_indicator.property("visible") is True
    for representation in (
        adapter.chartNarrativeText,
        adapter.chartTableText,
    ):
        assert f"#{adapter.selectedChartPointIndex}" in representation

    window.close()
    run_feature.close()
    evidence_feature.close()
