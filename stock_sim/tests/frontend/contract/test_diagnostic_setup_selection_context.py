from __future__ import annotations

from dataclasses import fields, replace
from datetime import datetime, timezone
from typing import get_type_hints

import pytest

from app.features.diagnostic_setup import (
    DiagnosticSetupSelectionContext,
    ScenarioDiagnosticSelection,
    compose_diagnostic_setup_selection_context,
)
from app.features.diagnostic_tasks_application import (
    CampaignCaseId,
    DiagnosticCampaignLayer,
    DiagnosticComparisonRole,
    MaterializedMarketScenarioId,
    StrategyUnderTestId,
)
from app.features.run_monitoring import SourceGenerationId
from app.features.scenario_lab_application import (
    ApprovedScenarioRecipeVersionId,
    FormalScenarioComparisonProjection,
    FormalScenarioSetEligibility,
    FormalScenarioSetProjection,
    HistoricalMarketSegmentId,
    MarketScenarioComparisonRole,
    MarketScenarioEntry,
    MarketScenarioLayer,
    MarketScenarioTransformationProjection,
    ReferenceMarketPathId,
    RequestedExecutionAssumptionsProjection,
    ScenarioCompatibilityState,
    ScenarioExecutionConditionProjection,
    ScenarioExecutionResolutionId,
    ScenarioExecutionResolutionProjection,
    ScenarioExecutionResolutionState,
    ScenarioExecutionTargetProjection,
    ScenarioReproducibilityState,
    ScenarioSelectionCaseBindingProjection,
    ScenarioSelectionContextId,
    ScenarioSelectionContextProjection,
    ScenarioSelectionContextStatus,
    ScenarioSelectionStrategyBindingProjection,
    ScenarioSetId,
    SourceSnapshotId,
)
from app.features.strategy_diagnostics_v1_read_model import SourceRevisionToken
from app.features.strategy_library import StrategySelectionContext
from app.features.strategy_library_application import (
    FormalStrategySelectionReference,
    GuardrailProfileId,
    StrategyDependencyIdentity,
    StrategyDependencyKind,
)


def _strategy_context() -> StrategySelectionContext:
    selections = tuple(
        FormalStrategySelectionReference(
            strategy_id=StrategyUnderTestId(identity),
            strategy_version="1.0",
            manifest_content_hash=f"sha256:{identity}-manifest",
            guardrail_profile_id=GuardrailProfileId(f"{identity}-guardrail"),
            guardrail_profile_version="1.0",
            dependency_identities=(
                StrategyDependencyIdentity(
                    kind=StrategyDependencyKind.COMPATIBILITY_MANIFEST,
                    identity=f"{identity}-manifest",
                    version="1.0",
                    content_hash=f"sha256:{identity}-manifest",
                    available=True,
                    compatible=True,
                ),
            ),
        )
        for identity in ("baseline_equal_weight", "momentum_rank_top_n")
    )
    return StrategySelectionContext(
        context_identity="strategy-selection-context-001",
        selections=selections,
        source_revision=SourceRevisionToken("1" * 64),
        originating_view_revision=17,
        source_generation=SourceGenerationId(3),
    )


def _case(
    identity: str,
    layer: MarketScenarioLayer,
    *,
    baseline: CampaignCaseId | None,
) -> MarketScenarioEntry:
    transformation = (
        ()
        if layer is MarketScenarioLayer.BASELINE
        else (
            MarketScenarioTransformationProjection(
                transformation_id=f"{identity}.v1",
                family=(
                    "execution-stress"
                    if layer is MarketScenarioLayer.ISOLATED_SENSITIVITY
                    else "compound-stress"
                ),
                implementation_version="1.0",
                parameters=(("severity", "bounded"),),
            ),
        )
    )
    return MarketScenarioEntry(
        scenario_id=CampaignCaseId(identity),
        layer=layer,
        comparison_role=(
            MarketScenarioComparisonRole.CONTROL
            if baseline is None
            else MarketScenarioComparisonRole.COMPARE_TO_BASELINE
        ),
        baseline_scenario_id=baseline,
        recipe_version_id=ApprovedScenarioRecipeVersionId("recipe-version-001"),
        recipe_content_hash="sha256:recipe-001",
        path_id=ReferenceMarketPathId("path-001"),
        segment_id=HistoricalMarketSegmentId("segment-001"),
        segment_content_hash="sha256:segment-001",
        source_snapshot_id=SourceSnapshotId("snapshot-001"),
        seed=41,
        transformation_catalog_version="transformations.v1",
        transformations=transformation,
        market_rule_profile_version="cn-a-share.v1",
        decision_cadence_minutes=5,
        requested_execution_assumptions=RequestedExecutionAssumptionsProjection(
            commission_bps="3",
            slippage_bps="4",
            max_fill_fraction="0.20",
            latency_nodes=1,
            allow_partial_fills=True,
        ),
        compatibility=ScenarioCompatibilityState.COMPATIBLE,
        reproducibility=ScenarioReproducibilityState.REPRODUCIBLE,
        execution_resolution=ScenarioExecutionResolutionState.RESOLVED,
        unavailability_reasons=(),
    )


def _scenario_selection() -> ScenarioDiagnosticSelection:
    baseline_id = CampaignCaseId("case-baseline")
    cases = (
        _case("case-baseline", MarketScenarioLayer.BASELINE, baseline=None),
        _case(
            "case-isolated",
            MarketScenarioLayer.ISOLATED_SENSITIVITY,
            baseline=baseline_id,
        ),
        _case("case-compound", MarketScenarioLayer.COMPOUND, baseline=baseline_id),
    )
    scenario_set = FormalScenarioSetProjection(
        scenario_set_id=ScenarioSetId("scenario-set-001"),
        projection_revision=4,
        eligibility=FormalScenarioSetEligibility.FORMAL_CAMPAIGN_ELIGIBLE,
        baseline_case_id=baseline_id,
        isolated_case_ids=(CampaignCaseId("case-isolated"),),
        compound_case_ids=(CampaignCaseId("case-compound"),),
        case_ids=tuple(item.scenario_id for item in cases),
        comparison_relationships=(
            FormalScenarioComparisonProjection(
                kind="isolated-vs-baseline",
                subject_case_id=CampaignCaseId("case-isolated"),
                control_case_ids=(baseline_id,),
            ),
            FormalScenarioComparisonProjection(
                kind="compound-vs-baseline-and-isolated",
                subject_case_id=CampaignCaseId("case-compound"),
                control_case_ids=(baseline_id, CampaignCaseId("case-isolated")),
            ),
        ),
        missing_requirements=(),
        formal_handoff_eligible=True,
    )
    strategy_bindings = tuple(
        ScenarioSelectionStrategyBindingProjection(
            strategy_id=item.strategy_id,
            strategy_version=item.strategy_version,
            compatibility_manifest_hash=item.manifest_content_hash,
            guardrail_profile_id=item.guardrail_profile_id.value,
            guardrail_profile_version=item.guardrail_profile_version,
            execution_policy_version="diagnostic-execution.v1",
        )
        for item in _strategy_context().selections
    )
    case_bindings = tuple(
        ScenarioSelectionCaseBindingProjection(
            campaign_case_id=item.scenario_id,
            recipe_version_id=item.recipe_version_id,
            recipe_content_hash=item.recipe_content_hash,
            reference_path_id=item.path_id,
            reference_path_content_hash="sha256:path-001",
            segment_id=item.segment_id,
            segment_content_hash=item.segment_content_hash,
            source_snapshot_id=item.source_snapshot_id,
            seed=item.seed,
            expander_version="market-path-expander.v1",
            source_resolution="1m",
            runtime_resolution="5m",
            numeric_tolerance="1e-9",
            normalization_provenance="ohlcv-normalization.v1",
            transformation_catalog_version=item.transformation_catalog_version,
            transformations=item.transformations,
            market_rule_profile_version=item.market_rule_profile_version,
            decision_cadence_minutes=item.decision_cadence_minutes,
        )
        for item in cases
    )
    selection = ScenarioSelectionContextProjection(
        selection_context_id=ScenarioSelectionContextId(
            "scenario-selection-context-001"
        ),
        scenario_set_id=scenario_set.scenario_set_id,
        scenario_set_projection_revision=scenario_set.projection_revision,
        case_ids=scenario_set.case_ids,
        case_bindings=case_bindings,
        strategy_bindings=strategy_bindings,
        execution_resolution_id=ScenarioExecutionResolutionId(
            "execution-resolution-001"
        ),
        execution_resolution_projection_revision=2,
        status=ScenarioSelectionContextStatus.CURRENT,
        selection_revision=9,
        originating_view_revision=23,
        source_revision=SourceRevisionToken("8" * 64),
        source_generation=SourceGenerationId(6),
        formal_handoff_eligible=True,
    )
    targets = tuple(
        ScenarioExecutionTargetProjection(
            strategy_id=strategy.strategy_id,
            strategy_version=strategy.strategy_version,
            compatibility_manifest_hash=strategy.compatibility_manifest_hash,
            guardrail_profile_id=strategy.guardrail_profile_id,
            guardrail_profile_version=strategy.guardrail_profile_version,
            campaign_case_id=case.scenario_id,
            state=ScenarioExecutionResolutionState.RESOLVED,
            decision_time=datetime(2026, 1, 5, 9, 30, tzinfo=timezone.utc),
            after_decision_time=datetime(2026, 1, 5, 9, 35, tzinfo=timezone.utc),
            activation_time=datetime(2026, 1, 5, 9, 40, tzinfo=timezone.utc),
            decision_cadence_minutes=case.decision_cadence_minutes,
            decision_grid="first-node-strictly-after-decision-time",
            activation_policy="after-decision-time.v1",
            execution_policy_version=strategy.execution_policy_version,
            conditions=(
                ScenarioExecutionConditionProjection(
                    name="commission_bps",
                    requested_value="3",
                    effective_value="3",
                    override_reason=None,
                ),
                ScenarioExecutionConditionProjection(
                    name="slippage_bps",
                    requested_value="4",
                    effective_value="5",
                    override_reason="scenario-execution-stress",
                ),
            ),
            unavailability_reasons=(),
        )
        for strategy in strategy_bindings
        for case in cases
    )
    resolution = ScenarioExecutionResolutionProjection(
        resolution_id=selection.execution_resolution_id,
        projection_revision=selection.execution_resolution_projection_revision,
        scenario_set_id=scenario_set.scenario_set_id,
        scenario_set_projection_revision=scenario_set.projection_revision,
        targets=targets,
        formal_handoff_eligible=True,
    )
    return ScenarioDiagnosticSelection(
        context=selection,
        scenario_set=scenario_set,
        market_scenarios=cases,
        execution_resolution=resolution,
    )


def test_compose_exact_setup_selection_context_into_existing_configuration() -> None:
    result = compose_diagnostic_setup_selection_context(
        _strategy_context(),
        _scenario_selection(),
    )

    assert isinstance(result, DiagnosticSetupSelectionContext)
    assert result.context_identity.startswith("sha256:")
    assert result.strategy_selection.context_identity == (
        "strategy-selection-context-001"
    )
    assert result.scenario_selection.context.selection_context_id.value == (
        "scenario-selection-context-001"
    )
    assert tuple(
        item.strategy_id.value for item in result.configuration.strategy_selections
    ) == ("baseline_equal_weight", "momentum_rank_top_n")
    assert tuple(
        item.layer for item in result.configuration.campaign_case_selections
    ) == (
        DiagnosticCampaignLayer.BASELINE,
        DiagnosticCampaignLayer.ISOLATED_SENSITIVITY,
        DiagnosticCampaignLayer.COMPOUND,
    )
    assert result.configuration.campaign_case_selections[0].market_scenario_id == (
        MaterializedMarketScenarioId("path-001")
    )
    assert result.configuration.campaign_case_selections[0].comparison_role is (
        DiagnosticComparisonRole.CONTROL
    )
    assert result.configuration.campaign_case_selections[1].comparison_role is (
        DiagnosticComparisonRole.COMPARE_TO_BASELINE
    )
    assert result.configuration.campaign_case_selections[1].baseline_campaign_case_id == (
        CampaignCaseId("case-baseline")
    )
    assert result.configuration.campaign_case_selections[1].execution_policy_values[1].source == (
        "backend-resolved:scenario-execution-stress;requested=4"
    )


def test_setup_identity_binds_separate_source_view_selection_and_projection_revisions() -> None:
    strategy = _strategy_context()
    scenario = _scenario_selection()
    original = compose_diagnostic_setup_selection_context(strategy, scenario)

    assert compose_diagnostic_setup_selection_context(strategy, scenario) == original
    assert compose_diagnostic_setup_selection_context(
        replace(strategy, originating_view_revision=18), scenario
    ).context_identity != original.context_identity
    assert compose_diagnostic_setup_selection_context(
        strategy,
        replace(
            scenario,
            context=replace(scenario.context, selection_revision=10),
        ),
    ).context_identity != original.context_identity
    assert compose_diagnostic_setup_selection_context(
        strategy,
        replace(
            scenario,
            scenario_set=replace(scenario.scenario_set, projection_revision=5),
            context=replace(
                scenario.context,
                scenario_set_projection_revision=5,
            ),
            execution_resolution=replace(
                scenario.execution_resolution,
                scenario_set_projection_revision=5,
            ),
        ),
    ).context_identity != original.context_identity


@pytest.mark.parametrize(
    "scenario",
    (
        replace(
            _scenario_selection(),
            context=replace(
                _scenario_selection().context,
                status=ScenarioSelectionContextStatus.STALE,
            ),
        ),
        replace(
            _scenario_selection(),
            scenario_set=replace(
                _scenario_selection().scenario_set,
                eligibility=FormalScenarioSetEligibility.QUICK_EXPERIMENT_ONLY,
                formal_handoff_eligible=False,
            ),
        ),
        replace(
            _scenario_selection(),
            execution_resolution=replace(
                _scenario_selection().execution_resolution,
                formal_handoff_eligible=False,
            ),
        ),
    ),
)
def test_setup_composition_fails_closed_for_stale_quick_or_unresolved_scenario(
    scenario: ScenarioDiagnosticSelection,
) -> None:
    with pytest.raises(ValueError):
        compose_diagnostic_setup_selection_context(_strategy_context(), scenario)


def test_setup_composition_fails_closed_on_strategy_binding_mismatch() -> None:
    scenario = _scenario_selection()
    mismatched = replace(
        scenario,
        context=replace(
            scenario.context,
            strategy_bindings=(scenario.context.strategy_bindings[0],),
        ),
    )

    with pytest.raises(ValueError, match="Strategy"):
        compose_diagnostic_setup_selection_context(_strategy_context(), mismatched)


def test_setup_context_public_type_graph_is_immutable_and_safe() -> None:
    hints = get_type_hints(DiagnosticSetupSelectionContext)

    assert DiagnosticSetupSelectionContext.__dataclass_params__.frozen
    assert {item.name for item in fields(DiagnosticSetupSelectionContext)} == {
        "context_identity",
        "canonical_payload_json",
        "strategy_selection",
        "scenario_selection",
        "configuration",
    }
    rendered = " ".join(str(value) for value in hints.values())
    for forbidden in (
        "dict",
        "Mapping",
        "Any",
        "Repository",
        "RuntimeGateway",
        "EventBridge",
        "QObject",
        "Future",
        "Lock",
    ):
        assert forbidden not in rendered
