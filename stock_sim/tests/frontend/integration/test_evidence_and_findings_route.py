import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from app.features import (
    ApprovedScenarioRecipeId,
    DeterministicFakeEvidenceAndFindingsAdapter,
    DeterministicFakeRunMonitoringAdapter,
    DiagnosticCandidateId,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsSelection,
    FormalDiagnosticCampaignId,
    FindingId,
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


def _visible_text(root: QObject) -> str:
    return " ".join(
        str(item.property("text"))
        for item in root.findChildren(QObject)
        if item.metaObject().indexOfProperty("text") >= 0
        and item.property("visible")
        and item.property("text")
    )


def test_evidence_route_renders_pinned_multidimensional_research_evidence():
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    evidence_feature = DeterministicFakeEvidenceAndFindingsAdapter()
    context = _context()
    evidence_feature.advance_to_completed(context)

    window = MainWindow(
        run_monitoring_feature=run_feature,
        evidence_and_findings_feature=evidence_feature,
        evidence_and_findings_context=context,
        frontend_v2_enabled=True,
    )
    root = window.centralWidget().rootObject()
    root.setProperty("activeRoute", "evidence_and_findings")
    app.processEvents()
    adapter = window.centralWidget()._evidence_and_findings
    finding_text = _visible_text(root)

    assert root.property("activeRoute") == "evidence_and_findings"
    assert root.property("evidenceScreenState") == "ready"
    for expected in (
        "EVIDENCE & FINDINGS",
        "FDC-001",
        "RUN-001",
        "STRATEGY-MOMENTUM-001",
        "SCENARIO-BASELINE",
        "RECIPE-001",
        "RM-001",
        "MODEL-B17",
        "MODEL-A04",
        "Baseline",
        "Isolated sensitivity",
        "Compound scenario",
        "Quick Experiment",
        "CMP-MODEL-B17-FEE",
        "Reference E-MODEL-B17-EXEC-BASE · -1.1",
        "Observed E-MODEL-B17-EXEC-ISO · -3.8",
        "Reference E-MODEL-B17-EXPOSURE-BASE · 41",
        "does not satisfy formal coverage",
        "Fee sensitivity breaks the baseline result",
        "Turnover amplifies effective fees",
        "Sensitivity Breakpoint",
        "1.6x",
    ):
        assert expected.casefold() in finding_text.casefold()

    adapter.setActiveTab("assumptions")
    app.processEvents()
    assumptions_text = _visible_text(root)
    for expected in (
        "requested 1.0x",
        "effective 1.6x",
        "Approved Scenario Recipe override",
    ):
        assert expected.casefold() in assumptions_text.casefold()

    adapter.setActiveTab("provenance")
    app.processEvents()
    provenance_text = _visible_text(root)
    assert "evidence-runner/2.4.0" in provenance_text
    assert "sha256:" in provenance_text

    adapter.setActiveTab("context")
    app.processEvents()
    context_text = _visible_text(root)
    assert "Orders and fills are read-only evidence traces" in context_text

    all_route_text = " ".join(
        (finding_text, assumptions_text, provenance_text, context_text)
    )
    for forbidden in (
        "Buy",
        "Sell",
        "Submit order",
        "Cancel order",
        "Replace order",
        "Bulk order",
        "Start experiment",
        "Launch experiment",
        "universal score",
        "leaderboard",
    ):
        assert forbidden.casefold() not in all_route_text.casefold()

    window.close()
    run_feature.close()
    evidence_feature.close()


def test_local_evidence_exploration_never_mutates_the_feature():
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    evidence_feature = DeterministicFakeEvidenceAndFindingsAdapter()
    context = _context()
    evidence_feature.advance_to_completed(context)
    window = MainWindow(
        run_monitoring_feature=run_feature,
        evidence_and_findings_feature=evidence_feature,
        evidence_and_findings_context=context,
        frontend_v2_enabled=True,
    )
    host = window.centralWidget()
    host.rootObject().setProperty("activeRoute", "evidence_and_findings")
    app.processEvents()
    adapter = host._evidence_and_findings
    revision = evidence_feature.snapshot(context).revision

    adapter.selectCandidate("MODEL-A04")
    adapter.selectFinding("F-MODEL-A04-02")
    adapter.setEvidenceFilter("risk")
    adapter.setSortOrder("coverage")
    adapter.setActiveTab("provenance")
    adapter.setViewportIntent("compound_stress")
    app.processEvents()

    assert adapter.selectedCandidateIdentity == "MODEL-A04"
    assert adapter.selectedFindingIdentity == "F-MODEL-A04-02"
    assert adapter.evidenceFilter == "risk"
    assert adapter.sortOrder == "coverage"
    assert adapter.activeTab == "provenance"
    assert adapter.viewportIntent == "compound_stress"
    assert evidence_feature.snapshot(context).revision == revision
    provenance = host.rootObject().findChild(
        QObject,
        "evidenceProvenancePanel",
    )
    assumptions = host.rootObject().findChild(
        QObject,
        "evidenceAssumptionsPanel",
    )
    flickable = host.rootObject().findChild(
        QObject,
        "evidenceResearchFlickable",
    )
    assert provenance.property("visible") is True
    assert assumptions.property("visible") is False
    assert flickable.property("contentY") > 0

    window.close()
    run_feature.close()
    evidence_feature.close()


def test_route_observes_honest_scripted_states_and_exposes_local_controls():
    app = _app()
    run_feature = DeterministicFakeRunMonitoringAdapter()
    evidence_feature = DeterministicFakeEvidenceAndFindingsAdapter()
    context = _context()
    window = MainWindow(
        run_monitoring_feature=run_feature,
        evidence_and_findings_feature=evidence_feature,
        evidence_and_findings_context=context,
        frontend_v2_enabled=True,
    )
    root = window.centralWidget().rootObject()
    root.setProperty("activeRoute", "evidence_and_findings")
    app.processEvents()

    assert root.property("evidenceScreenState") == "loading"
    assert (
        root.findChild(QObject, "evidenceCandidateRepeater").property("count")
        == 0
    )
    states = (
        (evidence_feature.advance_to_completed, "ready", "complete"),
        (evidence_feature.advance_to_stale, "ready", "stale"),
        (
            evidence_feature.advance_to_disconnected,
            "disconnected",
            "disconnected",
        ),
        (evidence_feature.advance_to_partial, "ready", "partial"),
        (evidence_feature.advance_to_failed, "failed", "failed"),
    )
    for transition, expected_state, expected_text in states:
        transition(context)
        app.processEvents()
        assert root.property("evidenceScreenState") == expected_state
        assert expected_text in _visible_text(root).casefold()
        assert "no research run selected" not in _visible_text(root).casefold()

    for object_name in (
        "evidenceFilterRisk",
        "evidenceSortCoverage",
        "evidenceViewportCompound",
    ):
        assert root.findChild(QObject, object_name) is not None
    assert (
        root.findChild(QObject, "evidenceCandidateRepeater").property("count")
        == 2
    )
    assert root.findChild(QObject, "evidenceTabRepeater").property("count") == 4
    assert (
        root.findChild(QObject, "evidenceFindingRepeater").property("count")
        == 2
    )
    for object_name in (
        "runMonitoringRouteNavigation",
        "evidenceAndFindingsRouteNavigation",
    ):
        navigation = root.findChild(QObject, object_name)
        assert navigation is not None
        assert navigation.property("activeFocusOnTab") is True

    window.close()
    run_feature.close()
    evidence_feature.close()

    empty_feature = DeterministicFakeEvidenceAndFindingsAdapter()
    empty_run_feature = DeterministicFakeRunMonitoringAdapter()
    empty_context = EvidenceAndFindingsContext.no_selection()
    empty_feature.advance_to_empty(empty_context)
    empty_window = MainWindow(
        run_monitoring_feature=empty_run_feature,
        evidence_and_findings_feature=empty_feature,
        evidence_and_findings_context=empty_context,
        frontend_v2_enabled=True,
    )
    empty_root = empty_window.centralWidget().rootObject()
    empty_root.setProperty("activeRoute", "evidence_and_findings")
    app.processEvents()
    assert empty_root.property("evidenceScreenState") == "empty"
    assert "no research run selected" in _visible_text(empty_root).casefold()
    empty_window.close()
    empty_feature.close()
    empty_run_feature.close()


def test_route_candidate_and_finding_controls_follow_typed_fake_data():
    app = _app()
    context = _context()
    seed = DeterministicFakeEvidenceAndFindingsAdapter()
    data = seed.advance_to_completed(context).last_reliable_data
    assert data is not None
    custom_candidate = replace(
        data.candidates[0],
        identity=DiagnosticCandidateId("MODEL-X99"),
        findings=(
            replace(
                data.candidates[0].findings[0],
                identity=FindingId("F-CUSTOM-X99"),
            ),
        ),
    )
    custom_data = replace(data, candidates=(custom_candidate,))
    seed.close()
    feature = DeterministicFakeEvidenceAndFindingsAdapter(
        completed_data=custom_data,
    )
    feature.advance_to_completed(context)
    run_feature = DeterministicFakeRunMonitoringAdapter()
    window = MainWindow(
        run_monitoring_feature=run_feature,
        evidence_and_findings_feature=feature,
        evidence_and_findings_context=context,
        frontend_v2_enabled=True,
    )
    root = window.centralWidget().rootObject()
    root.setProperty("activeRoute", "evidence_and_findings")
    app.processEvents()
    adapter = window.centralWidget()._evidence_and_findings

    assert adapter.candidateIdentities == ["MODEL-X99"]
    assert adapter.findingIdentities == ["F-CUSTOM-X99"]
    assert (
        root.findChild(QObject, "evidenceCandidateRepeater").property("count")
        == 1
    )
    assert (
        root.findChild(QObject, "evidenceFindingRepeater").property("count")
        == 1
    )
    visible_text = _visible_text(root)
    assert "MODEL-X99" in visible_text
    assert "F-CUSTOM-X99" in visible_text

    window.close()
    run_feature.close()
    feature.close()
