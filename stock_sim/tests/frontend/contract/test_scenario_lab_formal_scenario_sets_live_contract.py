from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from sqlalchemy import create_engine

from app.features import LiveScenarioLabAdapter, ScenarioLabContext
from app.features.run_monitoring import SourceGenerationId, StrategyUnderTestId
from app.features.scenario_lab_application import (
    ComposeFormalScenarioSetCommand,
    FormalScenarioSetEligibility,
    LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter,
    ResolveScenarioExecutionAssumptionsCommand,
    ScenarioExecutionAssumptionTarget,
    ScenarioExecutionResolutionState,
    ScenarioLabCommandContentIdentity,
    ScenarioLabCommandDisposition,
    ScenarioLabCommandId,
    ScenarioLabCommandMetadata,
    ScenarioLabIdempotencyIdentity,
    ScenarioSelectionContextStatus,
    SelectFormalScenarioSetCommand,
    canonical_scenario_lab_command_content_identity,
)
from tests.frontend.contract.test_diagnostic_task_campaign_start_live_contract import (
    _formal_live_stack,
)
from strategy_diagnostics import create_diagnostics_application


def _metadata(state, identity: str) -> ScenarioLabCommandMetadata:
    assert state.source_revision is not None
    return ScenarioLabCommandMetadata(
        command_id=ScenarioLabCommandId(f"{identity}-command"),
        idempotency_identity=ScenarioLabIdempotencyIdentity(
            f"{identity}-idempotency"
        ),
        canonical_content_identity=ScenarioLabCommandContentIdentity(
            "pending-canonical-content"
        ),
        expected_source_revision=state.source_revision,
        expected_source_generation=SourceGenerationId(
            state.source.generation.value
        ),
    )


def _canonical(command):
    return replace(
        command,
        metadata=replace(
            command.metadata,
            canonical_content_identity=(
                canonical_scenario_lab_command_content_identity(command)
            ),
        ),
    )


def _formal_cases(state):
    baseline = next(
        item for item in state.market_scenarios if item.layer.value == "baseline"
    )
    isolated = tuple(
        item
        for item in state.market_scenarios
        if item.layer.value == "isolated_sensitivity"
    )
    compound = tuple(
        item for item in state.market_scenarios if item.layer.value == "compound"
    )
    assert len(isolated) == 12
    assert len(compound) == 1
    return baseline, isolated, compound


def _live_feature(tmp_path):
    source, artifact_store, engine, application, _, _ = _formal_live_stack(
        tmp_path
    )
    feature = LiveScenarioLabAdapter(
        application=LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
            application
        )
    )
    return source, artifact_store, engine, application, feature


def test_live_composition_classifies_complete_formal_and_selective_quick_sets(
    tmp_path,
) -> None:
    _, _, engine, _, feature = _live_feature(tmp_path)
    context = ScenarioLabContext()
    feature.snapshot(context)
    ready = feature.snapshot(context)
    baseline, isolated, compound = _formal_cases(ready)

    complete = feature.compose_scenario_set(
        _canonical(
            ComposeFormalScenarioSetCommand(
                metadata=_metadata(ready, "compose-complete-83"),
                baseline_case_id=baseline.scenario_id,
                isolated_case_ids=tuple(item.scenario_id for item in isolated),
                compound_case_ids=tuple(item.scenario_id for item in compound),
            )
        )
    )

    assert complete.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert complete.scenario_set is not None
    assert complete.scenario_set.eligibility is (
        FormalScenarioSetEligibility.FORMAL_CAMPAIGN_ELIGIBLE
    )
    assert complete.scenario_set.formal_handoff_eligible
    assert complete.scenario_set.missing_requirements == ()
    assert complete.scenario_set.baseline_case_id == baseline.scenario_id
    assert complete.scenario_set.isolated_case_ids == tuple(
        item.scenario_id for item in isolated
    )
    assert complete.scenario_set.compound_case_ids == tuple(
        item.scenario_id for item in compound
    )
    assert len(complete.scenario_set.comparison_relationships) == 13

    after_complete = feature.snapshot(context)
    assert after_complete.source_revision is not None
    selective = feature.compose_scenario_set(
        _canonical(
            ComposeFormalScenarioSetCommand(
                metadata=_metadata(after_complete, "compose-selective-83"),
                baseline_case_id=baseline.scenario_id,
                isolated_case_ids=tuple(
                    item.scenario_id for item in isolated[:-1]
                ),
                compound_case_ids=tuple(item.scenario_id for item in compound),
            )
        )
    )

    assert selective.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert selective.scenario_set is not None
    assert selective.scenario_set.eligibility is (
        FormalScenarioSetEligibility.QUICK_EXPERIMENT_ONLY
    )
    assert not selective.scenario_set.formal_handoff_eligible
    assert "complete isolated sensitivity sweep" in (
        selective.scenario_set.missing_requirements
    )
    snapshot = feature.snapshot(context)
    assert tuple(item.scenario_set_id for item in snapshot.scenario_sets) == (
        complete.scenario_set.scenario_set_id,
        selective.scenario_set.scenario_set_id,
    )
    assert snapshot.capabilities.can_compose_scenario_set
    feature.close()
    engine.dispose()


def test_live_recipe_successor_history_keeps_one_active_semantic_sweep(
    tmp_path,
) -> None:
    _, _, engine, application, feature = _live_feature(tmp_path)
    baseline_version = next(
        item
        for item in application.list_approved_scenario_recipes()
        if not item.recipe.transformations
    )
    successor_payload = baseline_version.recipe.dict()
    successor_payload["name"] = "Formal baseline successor"
    successor_draft = application.revise_recipe_version(
        baseline_version.version_id,
        successor_payload,
        author="researcher",
    )
    assert application.validate_recipe_draft(successor_draft.draft_id).is_valid
    successor = application.approve_recipe_draft(
        successor_draft.draft_id,
        actor="owner",
    )
    application.materialize_baseline_reference_path(successor.version_id)

    context = ScenarioLabContext()
    feature.snapshot(context)
    ready = feature.snapshot(context)
    baseline = next(
        item
        for item in ready.market_scenarios
        if item.recipe_version_id.value == successor.version_id
    )
    isolated = tuple(
        item
        for item in ready.market_scenarios
        if item.layer.value == "isolated_sensitivity"
    )
    compound = tuple(
        item
        for item in ready.market_scenarios
        if item.layer.value == "compound"
    )
    composed = feature.compose_scenario_set(
        _canonical(
            ComposeFormalScenarioSetCommand(
                metadata=_metadata(ready, "compose-successor-history-83"),
                baseline_case_id=baseline.scenario_id,
                isolated_case_ids=tuple(
                    item.scenario_id for item in isolated
                ),
                compound_case_ids=tuple(
                    item.scenario_id for item in compound
                ),
            )
        )
    )

    assert composed.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert composed.scenario_set is not None
    assert composed.scenario_set.eligibility is (
        FormalScenarioSetEligibility.FORMAL_CAMPAIGN_ELIGIBLE
    )
    feature.close()
    engine.dispose()


def test_live_resolution_and_selection_bind_exact_assumptions_and_activation(
    tmp_path,
    monkeypatch,
) -> None:
    source, artifact_store, engine, application, feature = _live_feature(
        tmp_path
    )
    context = ScenarioLabContext()
    feature.snapshot(context)
    ready = feature.snapshot(context)
    baseline, isolated, compound = _formal_cases(ready)
    composed = feature.compose_scenario_set(
        _canonical(
            ComposeFormalScenarioSetCommand(
                metadata=_metadata(ready, "compose-resolution-83"),
                baseline_case_id=baseline.scenario_id,
                isolated_case_ids=tuple(item.scenario_id for item in isolated),
                compound_case_ids=tuple(item.scenario_id for item in compound),
            )
        )
    )
    assert composed.scenario_set is not None

    after_compose = feature.snapshot(context)
    strategy_ids = tuple(
        StrategyUnderTestId(item.strategy_id)
        for item in application.read_strategy_under_test_inventory().entries
    )
    decision_time = baseline_path_start = next(
        item.start_time
        for item in after_compose.reference_paths
        if item.path_id == baseline.path_id
    )
    targets = tuple(
        ScenarioExecutionAssumptionTarget(
            strategy_id=strategy_id,
            campaign_case_id=case_id,
            decision_time=decision_time,
        )
        for strategy_id in strategy_ids
        for case_id in composed.scenario_set.case_ids
    )
    resolved = feature.resolve_execution_assumptions(
        _canonical(
            ResolveScenarioExecutionAssumptionsCommand(
                metadata=_metadata(after_compose, "resolve-formal-83"),
                scenario_set_id=composed.scenario_set.scenario_set_id,
                targets=targets,
            )
        )
    )

    assert resolved.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert resolved.resolution is not None
    assert resolved.resolution.formal_handoff_eligible
    assert len(resolved.resolution.targets) == len(targets)
    assert all(
        item.state is ScenarioExecutionResolutionState.RESOLVED
        for item in resolved.resolution.targets
    )
    assert all(
        item.after_decision_time > item.decision_time
        and item.activation_time >= item.after_decision_time
        for item in resolved.resolution.targets
        if item.decision_time is not None
        and item.after_decision_time is not None
        and item.activation_time is not None
    )
    execution_stress = tuple(
        item
        for item in resolved.resolution.targets
        if any(
            transform.family == "execution-stress"
            for transform in next(
                case
                for case in after_compose.market_scenarios
                if case.scenario_id == item.campaign_case_id
            ).transformations
        )
    )
    assert execution_stress
    assert all(
        any(
            condition.name == "slippage_bps"
            and condition.requested_value != condition.effective_value
            and condition.override_reason is not None
            for condition in item.conditions
        )
        for item in execution_stress
    )
    parity_target = execution_stress[0]
    parity_case = next(
        item
        for item in after_compose.market_scenarios
        if item.scenario_id == parity_target.campaign_case_id
    )
    production_run = application.start_baseline_strategy_run(
        parity_case.recipe_version_id.value,
        parity_case.path_id.value,
        initial_cash=Decimal("100000"),
        order_shares=1000,
        replica_id="issue-83-resolution-parity",
        strategy_id=parity_target.strategy_id.value,
        strategy_version=parity_target.strategy_version,
    )
    assert production_run.specification.resolved_execution_conditions is not None
    assert tuple(
        (
            item.name,
            item.requested_value,
            item.effective_value,
            item.override_reason,
        )
        for item in parity_target.conditions
    ) == tuple(
        (
            item.name,
            item.requested_value,
            item.effective_value,
            item.override_reason,
        )
        for item in (
            production_run.specification.resolved_execution_conditions.resolutions
        )
    )

    after_resolution = feature.snapshot(context)
    selected = feature.select_formal_scenario_set(
        _canonical(
            SelectFormalScenarioSetCommand(
                metadata=_metadata(after_resolution, "select-formal-83"),
                scenario_set_id=composed.scenario_set.scenario_set_id,
                case_ids=composed.scenario_set.case_ids,
                originating_view_revision=after_resolution.revision,
                execution_resolution_id=resolved.resolution.resolution_id,
            )
        )
    )
    assert selected.receipt.disposition is ScenarioLabCommandDisposition.ACCEPTED
    assert selected.selection_context is not None
    assert selected.selection_context.status is ScenarioSelectionContextStatus.CURRENT
    assert selected.selection_context.formal_handoff_eligible
    assert selected.selection_context.case_ids == composed.scenario_set.case_ids
    assert (
        selected.selection_context.execution_resolution_id
        == resolved.resolution.resolution_id
    )
    assert selected.selection_context.originating_view_revision == (
        after_resolution.revision
    )
    assert selected.selection_context.source_generation == (
        after_resolution.source.generation
    )

    remounted = LiveScenarioLabAdapter(
        application=LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
            application
        )
    )
    remounted.snapshot(context)
    reopened_state = remounted.snapshot(context)
    assert reopened_state.selection_contexts[-1] == selected.selection_context
    assert reopened_state.selection_contexts[-1].status is (
        ScenarioSelectionContextStatus.CURRENT
    )
    remounted.close()
    feature.close()
    engine.dispose()

    reopened_engine = create_engine(
        f"sqlite:///{tmp_path / 'diagnostic-task-campaign.db'}",
        future=True,
    )
    reopened_application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=artifact_store,
        recipe_clock=lambda: datetime(2030, 1, 1),
    )
    reopened_application.start()
    reopened_application.initialize_persistence(reopened_engine)
    reopened_feature = LiveScenarioLabAdapter(
        application=LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(
            reopened_application
        )
    )
    reopened_feature.snapshot(context)
    persisted = reopened_feature.snapshot(context)
    assert persisted.scenario_sets[-1] == composed.scenario_set
    assert persisted.execution_resolutions[-1] == resolved.resolution
    assert persisted.selection_contexts[-1] == selected.selection_context
    assert persisted.selection_contexts[-1].status is (
        ScenarioSelectionContextStatus.CURRENT
    )
    monkeypatch.setattr(
        reopened_application,
        "list_available_diagnostic_campaign_cases",
        lambda: (),
    )
    authority_lost = reopened_feature.snapshot(context)
    assert authority_lost.selection_contexts[-1].status is (
        ScenarioSelectionContextStatus.STALE
    )
    assert not authority_lost.selection_contexts[-1].formal_handoff_eligible
    reopened_feature.close()
    reopened_engine.dispose()
