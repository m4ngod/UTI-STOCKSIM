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
    DeterministicEvidenceChartSampler,
    EvidenceChartSamplingPolicy,
    EvidenceChartViewport,
)


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


def test_reference_evidence_source_is_sampled_deterministically_without_mutation():
    feature = DeterministicFakeEvidenceAndFindingsAdapter()
    state = feature.advance_to_completed(_context())
    data = state.last_reliable_data
    assert data is not None
    source = data.candidates[0].chart
    assert source is not None
    original_values = source.values
    original_overlays = source.overlays
    sampler = DeterministicEvidenceChartSampler()
    viewport = EvidenceChartViewport(start=0.0, end=1.0)

    first = sampler.sample(
        source,
        source_identity=f"{state.source.identity}:{source.identity}",
        revision=state.revision,
        viewport=viewport,
        resolution=4_000,
        policy=EvidenceChartSamplingPolicy.UNIFORM_ENDPOINTS_V1,
    )
    second = sampler.sample(
        source,
        source_identity=f"{state.source.identity}:{source.identity}",
        revision=state.revision,
        viewport=viewport,
        resolution=4_000,
        policy=EvidenceChartSamplingPolicy.UNIFORM_ENDPOINTS_V1,
    )

    assert len(source.values) == 100_000
    assert len(source.overlays) == 3
    assert len(first.points) == 4_000
    assert first == second
    assert first.key.source_identity == (
        "frontend-v2-evidence-and-findings-fake:"
        "MODEL-B17-diagnostic-series"
    )
    assert first.key.revision == state.revision
    assert first.key.viewport == viewport
    assert first.key.resolution == 4_000
    assert first.key.policy is EvidenceChartSamplingPolicy.UNIFORM_ENDPOINTS_V1
    assert first.points[0].source_index == 0
    assert first.points[-1].source_index == 99_999
    assert source.values is original_values
    assert source.overlays is original_overlays

    feature.close()
