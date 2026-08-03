from dataclasses import replace

from PySide6.QtWidgets import QApplication

from app.features import (
    ApprovedScenarioRecipeId,
    DeterministicFakeEvidenceAndFindingsAdapter,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsSelection,
    FormalDiagnosticCampaignId,
    MarketScenarioId,
    ReproductionManifestId,
    StrategyRunId,
    StrategyUnderTestId,
)
from app.ui.evidence_chart import (
    EvidenceChartFrameGate,
    EvidenceChartRenderFrame,
)
from app.ui.journey_workspace import EvidenceAndFindingsQtAdapter


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


def test_frame_gate_caps_commits_and_never_coalesces_away_terminal_revision():
    frame = EvidenceChartRenderFrame(
        revision=1,
        terminal=False,
        points=((0.0, 0.0), (1.0, 1.0)),
        overlays=(),
    )
    gate = EvidenceChartFrameGate(max_frames_per_second=20)
    assert gate.max_frames_per_second == 20

    first = gate.offer(frame, now_ns=0)
    intermediate = gate.offer(
        replace(frame, revision=2),
        now_ns=10_000_000,
    )
    newest_intermediate = gate.offer(
        replace(frame, revision=3),
        now_ns=20_000_000,
    )
    terminal = gate.offer(
        replace(frame, revision=4, terminal=True),
        now_ns=30_000_000,
    )
    following = gate.offer(
        replace(frame, revision=5),
        now_ns=35_000_000,
    )

    assert tuple(item.revision for item in first.committed) == (1,)
    assert intermediate.committed == ()
    assert newest_intermediate.committed == ()
    assert terminal.committed == ()
    assert terminal.due_in_ns == 20_000_000
    assert following.committed == ()
    assert gate.pendingRevision == 4
    assert gate.queuedAfterTerminalRevision == 5
    assert gate.offer(
        replace(frame, revision=5),
        now_ns=40_000_000,
    ).accepted is False
    assert gate.offer(
        replace(frame, revision=3),
        now_ns=40_000_000,
    ).accepted is False

    before_due = gate.flush(now_ns=49_999_999)
    terminal_commit = gate.flush(now_ns=50_000_000)
    too_soon = gate.flush(now_ns=99_999_999)
    following_commit = gate.flush(now_ns=100_000_000)

    assert before_due.committed == ()
    assert tuple(item.revision for item in terminal_commit.committed) == (4,)
    assert too_soon.committed == ()
    assert tuple(item.revision for item in following_commit.committed) == (5,)
    assert gate.committedRevision == 5


def test_qt_adapter_publishes_semantics_before_capped_chart_frame_deadline():
    _app()
    now = [0]
    feature = DeterministicFakeEvidenceAndFindingsAdapter()
    context = _context()
    feature.advance_to_completed(context)
    adapter = EvidenceAndFindingsQtAdapter(
        feature,
        context=context,
        chart_clock=lambda: now[0],
    )
    initial_sequence = adapter.chartFrameSequence
    assert adapter.chartInteractionEnabled is True

    now[0] = 10_000_000
    adapter.selectCandidate("MODEL-A04")
    now[0] = 20_000_000
    adapter.setViewportIntent("sensitivity")

    assert adapter.selectedCandidateIdentity == "MODEL-A04"
    assert "MODEL-A04" in adapter.chartNarrativeText
    assert "MODEL-A04" in adapter.chartTableText
    assert adapter.chartFrameSequence == initial_sequence
    assert adapter.chartInteractionEnabled is False

    now[0] = 50_000_000
    adapter.flush_chart_frames()

    assert adapter.chartFrameSequence == initial_sequence + 1
    assert adapter.chartInteractionEnabled is True
    for representation in (
        adapter.chartNarrativeText,
        adapter.chartTableText,
    ):
        assert "MODEL-A04" in representation

    now[0] = 60_000_000
    adapter.selectChartOverlay("OV-MODEL-A04-DRAWDOWN")

    assert adapter.chartInteractionEnabled is False
    assert "OV-MODEL-A04-DRAWDOWN" in adapter.chartNarrativeText
    assert "OV-MODEL-A04-DRAWDOWN" in adapter.chartTableText

    now[0] = 100_000_000
    adapter.flush_chart_frames()

    assert adapter.chartInteractionEnabled is True
    assert "OV-MODEL-A04-DRAWDOWN" in adapter.chartNarrativeText
    assert "OV-MODEL-A04-DRAWDOWN" in adapter.chartTableText
    assert adapter.chartAcceptedRevision == feature.snapshot(context).revision

    adapter.close()
    feature.close()


def test_qt_adapter_disables_point_interaction_without_a_chart_sample():
    _app()
    context = _context()
    source_feature = DeterministicFakeEvidenceAndFindingsAdapter()
    completed = source_feature.advance_to_completed(context)
    assert completed.last_reliable_data is not None
    completed_without_charts = replace(
        completed.last_reliable_data,
        candidates=tuple(
            replace(candidate, chart=None, curves=())
            for candidate in completed.last_reliable_data.candidates
        ),
    )
    source_feature.close()
    feature = DeterministicFakeEvidenceAndFindingsAdapter(
        completed_data=completed_without_charts,
    )
    feature.advance_to_completed(context)

    adapter = EvidenceAndFindingsQtAdapter(
        feature,
        context=context,
    )

    assert adapter.chartVisiblePointCount == 0
    assert adapter.chartInteractionEnabled is False
    assert "No full-fidelity diagnostic chart source is available" in (
        adapter.chartAccessibleText
    )

    adapter.close()
    feature.close()


def test_revision_only_commit_does_not_republish_unchanged_chart_geometry():
    _app()
    now = [0]
    feature = DeterministicFakeEvidenceAndFindingsAdapter()
    context = _context()
    completed = feature.advance_to_completed(context)
    adapter = EvidenceAndFindingsQtAdapter(
        feature,
        context=context,
        chart_clock=lambda: now[0],
    )
    geometry_changes = []
    presentation_changes = []
    adapter.chartGeometryChanged.connect(
        lambda: geometry_changes.append(adapter.chartFrameSequence)
    )
    adapter.chartPresentationChanged.connect(
        lambda: presentation_changes.append(adapter.chartFrameSequence)
    )
    initial_points = adapter._chart_presentation.sample.points

    now[0] = 10_000_000
    adapter._accept_state(
        adapter._mount_generation.value,
        replace(completed, revision=completed.revision + 1),
    )

    assert presentation_changes == [adapter.chartFrameSequence]
    assert geometry_changes == []
    assert adapter.chartAcceptedRevision == completed.revision + 1
    assert adapter.chartInteractionEnabled is True
    assert adapter._chart_presentation.sample.points is initial_points
    assert (
        f"Accepted evidence revision · r{completed.revision + 1}"
        in adapter.chartNarrativeText
    )
    assert (
        f"Accepted evidence revision · r{completed.revision + 1}"
        in adapter.chartTableText
    )

    now[0] = 50_000_000
    adapter.flush_chart_frames()
    assert presentation_changes == [adapter.chartFrameSequence]

    adapter.close()
    feature.close()


def test_active_tab_input_does_not_schedule_unrelated_chart_work():
    _app()
    now = [0]
    feature = DeterministicFakeEvidenceAndFindingsAdapter()
    context = _context()
    feature.advance_to_completed(context)
    adapter = EvidenceAndFindingsQtAdapter(
        feature,
        context=context,
        chart_clock=lambda: now[0],
    )
    initial_sequence = adapter.chartFrameSequence
    presentation_changes = []
    adapter.chartPresentationChanged.connect(
        lambda: presentation_changes.append(adapter.chartFrameSequence)
    )

    now[0] = 10_000_000
    adapter.setActiveTab("assumptions")

    assert adapter.activeTab == "assumptions"
    assert adapter.chartFrameSequence == initial_sequence
    assert adapter.chartInteractionEnabled is True
    assert presentation_changes == []

    adapter.close()
    feature.close()
