from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from app.app_context import build_app_context
from app.event_bridge import EventBridge
from app.features import (
    ApproveDiagnosticTaskConfiguration,
    CampaignAttemptId,
    CampaignNodeId,
    CancelDiagnosticTarget,
    CreateDiagnosticTask,
    DIAGNOSTIC_TASKS_INTERFACE_VERSION,
    DeterministicFakeDiagnosticTasksAdapter,
    DiagnosticTaskCommandRejectionReason,
    DiagnosticActorId,
    DiagnosticCampaignCaseSelection,
    DiagnosticCampaignLayer,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    DiagnosticComparisonRole,
    DiagnosticStrategySelection,
    DiagnosticTaskTarget,
    DiagnosticTaskConfiguration,
    DiagnosticTaskConfigurationContentId,
    DiagnosticTaskId,
    DiagnosticTasksContext,
    DiagnosticTasksApplicationAvailability,
    DiagnosticTasksApplicationError,
    DiagnosticTasksApplicationErrorCode,
    DiagnosticTasksApplicationInventoryResult,
    DiagnosticTasksFeature,
    DiagnosticTasksPresentationState,
    Freshness,
    LiveDiagnosticTasksAdapter,
    LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
    PauseDiagnosticTarget,
    ReproductionManifestAvailability,
    ResumeDiagnosticTarget,
    RetryFailedCampaignNode,
    ReviseDiagnosticTaskConfiguration,
    SourceRevisionToken,
    StartFormalDiagnosticCampaign,
    StrategyDiagnosticsV1DiagnosticTasksApplication,
    StrategyDiagnosticsV1ApplicationReadModel,
    ValidateDiagnosticTaskConfiguration,
)
from strategy_diagnostics import create_diagnostics_application
from strategy_diagnostics.market_paths import InMemoryMarketPathArtifactStore
from tests.strategy_diagnostics.test_recipe_lifecycle import (
    _RecipeFixtureSource,
    _baseline_payload,
)


def _live_feature() -> DiagnosticTasksFeature:
    source = _RecipeFixtureSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    application.start()
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    draft = application.create_manual_recipe_draft(
        _baseline_payload(admission.segment.segment_id),
        author="researcher",
    )
    assert application.validate_recipe_draft(draft.draft_id).is_valid
    approved = application.approve_recipe_draft(draft.draft_id, actor="owner")
    application.materialize_baseline_reference_path(approved.version_id)
    return LiveDiagnosticTasksAdapter(
        application=LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
            application
        ),
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )


def _fake_feature() -> DiagnosticTasksFeature:
    authoritative = _live_feature()
    context = DiagnosticTasksContext.workspace()
    assert (
        authoritative.snapshot(context).presentation
        is DiagnosticTasksPresentationState.LOADING
    )
    inventory = authoritative.snapshot(context).last_reliable_inventory
    authoritative.close()
    assert inventory is not None
    return DeterministicFakeDiagnosticTasksAdapter(
        inventory=inventory,
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )


@dataclass
class _MutableClock:
    now: datetime
    on_advance: Callable[[], None] | None = None

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta
        if self.on_advance is not None:
            self.on_advance()


class _DisconnectableMarketPathArtifactStore(InMemoryMarketPathArtifactStore):
    def __init__(self) -> None:
        super().__init__()
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def list_paths(self):
        if not self._connected:
            raise RuntimeError("authoritative market-path store is disconnected")
        return super().list_paths()


def _authoritative_inventory():
    feature = _live_feature()
    try:
        context = DiagnosticTasksContext.workspace()
        assert (
            feature.snapshot(context).presentation
            is DiagnosticTasksPresentationState.LOADING
        )
        inventory = feature.snapshot(context).last_reliable_inventory
    finally:
        feature.close()
    assert inventory is not None
    return inventory


def _inventory_result_sequence(
    *,
    failed_second_read: bool,
) -> tuple[DiagnosticTasksApplicationInventoryResult, ...]:
    observed_at = datetime(2030, 1, 1, tzinfo=timezone.utc)
    inventory = _authoritative_inventory()
    first = DiagnosticTasksApplicationInventoryResult(
        availability=DiagnosticTasksApplicationAvailability.READY,
        inventory=inventory,
        source_token=SourceRevisionToken("1" * 64),
        observed_at=observed_at,
        error=None,
    )
    if not failed_second_read:
        return (first, first)
    return (
        first,
        DiagnosticTasksApplicationInventoryResult(
            availability=DiagnosticTasksApplicationAvailability.FAILED,
            inventory=None,
            source_token=None,
            observed_at=observed_at + timedelta(seconds=10),
            error=DiagnosticTasksApplicationError(
                code=DiagnosticTasksApplicationErrorCode.APPLICATION_NOT_READY,
                message="authoritative market-path store is disconnected",
                retryable=True,
                correlation_id="inventory-read-2",
            ),
        ),
    )


def _unavailable_commands(inventory):
    scenarios = inventory.market_scenarios
    recipe_by_id = {
        item.recipe_version_id: item for item in inventory.approved_recipes
    }
    baseline_case_id = next(
        item.campaign_case_id
        for item in scenarios
        if item.layer is DiagnosticCampaignLayer.BASELINE
    )
    configuration = DiagnosticTaskConfiguration(
        content_identity=DiagnosticTaskConfigurationContentId(
            "sha256:configuration-56"
        ),
        strategy_selections=tuple(
            DiagnosticStrategySelection(
                strategy_id=item.strategy_id,
                strategy_version=item.strategy_version,
                compatibility_manifest_hash=item.compatibility_manifest_hash,
                guardrail_profile_id=item.guardrail_profile_id,
                guardrail_profile_version=item.guardrail_profile_version,
            )
            for item in inventory.strategies
        ),
        campaign_case_selections=tuple(
            DiagnosticCampaignCaseSelection(
                layer=item.layer,
                recipe_version_id=item.recipe_version_id,
                recipe_content_hash=recipe_by_id[
                    item.recipe_version_id
                ].content_hash,
                market_scenario_id=item.market_scenario_id,
                campaign_case_id=item.campaign_case_id,
                comparison_role=(
                    DiagnosticComparisonRole.CONTROL
                    if item.layer is DiagnosticCampaignLayer.BASELINE
                    else DiagnosticComparisonRole.COMPARE_TO_BASELINE
                ),
                baseline_campaign_case_id=(
                    None
                    if item.layer is DiagnosticCampaignLayer.BASELINE
                    else baseline_case_id
                ),
                execution_policy_values=item.execution_policy_values,
            )
            for item in scenarios
        ),
    )
    task_id = DiagnosticTaskId("diagnostic-task-56")

    def identity(name: str):
        return (
            DiagnosticCommandId(f"command-56-{name}"),
            DiagnosticCommandIdempotencyKey(f"idempotency-56-{name}"),
        )

    create_id, create_key = identity("create")
    revise_id, revise_key = identity("revise")
    validate_id, validate_key = identity("validate")
    approve_id, approve_key = identity("approve")
    start_id, start_key = identity("start")
    pause_id, pause_key = identity("pause")
    resume_id, resume_key = identity("resume")
    cancel_id, cancel_key = identity("cancel")
    retry_id, retry_key = identity("retry")
    target = DiagnosticTaskTarget(task_id)
    return (
        CreateDiagnosticTask(create_id, create_key, configuration),
        ReviseDiagnosticTaskConfiguration(
            revise_id,
            revise_key,
            task_id,
            1,
            configuration,
        ),
        ValidateDiagnosticTaskConfiguration(
            validate_id,
            validate_key,
            task_id,
            1,
        ),
        ApproveDiagnosticTaskConfiguration(
            approve_id,
            approve_key,
            task_id,
            1,
            1,
            configuration.content_identity,
            DiagnosticActorId("research-owner"),
        ),
        StartFormalDiagnosticCampaign(
            start_id,
            start_key,
            task_id,
            1,
            1,
        ),
        PauseDiagnosticTarget(
            pause_id,
            pause_key,
            target,
            1,
        ),
        ResumeDiagnosticTarget(
            resume_id,
            resume_key,
            target,
            1,
        ),
        CancelDiagnosticTarget(
            cancel_id,
            cancel_key,
            target,
            1,
        ),
        RetryFailedCampaignNode(
            retry_id,
            retry_key,
            task_id,
            CampaignNodeId("campaign-node-56"),
            CampaignAttemptId("campaign-attempt-56"),
            1,
        ),
    )


def _real_live_feature_with_transitions(
    *,
    failed_second_read: bool,
) -> tuple[DiagnosticTasksFeature, _MutableClock]:
    source = _RecipeFixtureSource()
    store = _DisconnectableMarketPathArtifactStore()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=store,
        recipe_clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    application.start()
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    draft = application.create_manual_recipe_draft(
        _baseline_payload(admission.segment.segment_id),
        author="researcher",
    )
    assert application.validate_recipe_draft(draft.draft_id).is_valid
    approved = application.approve_recipe_draft(draft.draft_id, actor="owner")
    application.materialize_baseline_reference_path(approved.version_id)
    clock = _MutableClock(datetime(2030, 1, 1, tzinfo=timezone.utc))
    if failed_second_read:
        clock.on_advance = store.disconnect
    return (
        LiveDiagnosticTasksAdapter(
            application=LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
                application
            ),
            clock=clock,
            freshness_threshold=timedelta(seconds=5),
        ),
        clock,
    )


def _scripted_fake_feature(
    *,
    failed_second_read: bool,
) -> tuple[DiagnosticTasksFeature, _MutableClock]:
    clock = _MutableClock(datetime(2030, 1, 1, tzinfo=timezone.utc))
    return (
        DeterministicFakeDiagnosticTasksAdapter(
            scripted_results=_inventory_result_sequence(
                failed_second_read=failed_second_read
            ),
            clock=clock,
            freshness_threshold=timedelta(seconds=5),
        ),
        clock,
    )


@pytest.mark.parametrize("feature_factory", [_live_feature, _fake_feature])
def test_live_and_fake_share_one_typed_feature_conformance(
    feature_factory: Callable[[], DiagnosticTasksFeature],
) -> None:
    feature = feature_factory()
    context = DiagnosticTasksContext.workspace()

    loading = feature.snapshot(context)
    assert loading.interface_version == DIAGNOSTIC_TASKS_INTERFACE_VERSION
    assert loading.revision == 1
    assert loading.freshness is Freshness.AWAITING_FIRST_STATE
    assert loading.presentation is DiagnosticTasksPresentationState.LOADING
    assert loading.last_reliable_inventory is None

    state = feature.snapshot(context)

    assert state.interface_version == DIAGNOSTIC_TASKS_INTERFACE_VERSION
    assert state.revision == 2
    assert state.freshness is Freshness.FRESH
    assert state.presentation is DiagnosticTasksPresentationState.READY
    assert state.last_reliable_inventory is not None
    assert len(state.last_reliable_inventory.strategies) == 2
    assert len(state.last_reliable_inventory.approved_recipes) == 1
    assert len(state.last_reliable_inventory.market_scenarios) == 1
    assert (
        state.reproduction_manifest_availability
        is ReproductionManifestAvailability.NOT_YET_AVAILABLE
    )
    assert state.reproduction_manifest_id is None
    assert state.error is None
    with pytest.raises(FrozenInstanceError):
        state.revision = 2  # type: ignore[misc]

    observed = []
    subscription = feature.subscribe(context, observed.append)
    assert observed == [state]
    assert not subscription.disposed
    subscription.dispose()
    subscription.dispose()
    assert subscription.disposed

    commands = _unavailable_commands(state.last_reliable_inventory)
    results = (
        feature.create_diagnostic_task(commands[0]),
        feature.revise_configuration(commands[1]),
        feature.validate_configuration(commands[2]),
        feature.approve_configuration(commands[3]),
        feature.start_formal_diagnostic_campaign(commands[4]),
        feature.pause_diagnostic_target(commands[5]),
        feature.resume_diagnostic_target(commands[6]),
        feature.cancel_diagnostic_target(commands[7]),
        feature.retry_failed_campaign_node(commands[8]),
    )
    assert all(not result.accepted for result in results)
    assert all(result.task is None for result in results)
    assert all(
        result.rejection_reason
        is DiagnosticTaskCommandRejectionReason.NOT_YET_AVAILABLE
        for result in results
    )
    feature.close()
    feature.close()


@pytest.mark.parametrize(
    "feature_factory",
    [_real_live_feature_with_transitions, _scripted_fake_feature],
)
@pytest.mark.parametrize("failed_second_read", [False, True])
def test_live_and_fake_share_freshness_and_last_reliable_transitions(
    feature_factory,
    failed_second_read: bool,
) -> None:
    feature, clock = feature_factory(failed_second_read=failed_second_read)
    context = DiagnosticTasksContext.workspace()
    loading = feature.snapshot(context)
    assert loading.presentation is DiagnosticTasksPresentationState.LOADING
    reliable = feature.snapshot(context)
    clock.advance(timedelta(seconds=10))

    degraded = feature.snapshot(context)

    assert reliable.last_reliable_inventory is not None
    assert degraded.revision == reliable.revision + 1
    assert degraded.freshness is Freshness.STALE
    assert degraded.presentation is DiagnosticTasksPresentationState.DEGRADED
    assert degraded.age == timedelta(seconds=10)
    assert degraded.last_reliable_inventory is reliable.last_reliable_inventory
    assert degraded.error is not None
    assert degraded.error.retryable is True
    if failed_second_read:
        assert degraded.error.code == "diagnostic_tasks_application_not_ready"
    else:
        assert degraded.error.code == "diagnostic_tasks_inventory_stale"
    feature.close()


def test_app_context_composes_diagnostic_tasks_as_the_third_feature(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
    )

    assert isinstance(context.diagnostic_tasks_feature, DiagnosticTasksFeature)
    assert (
        context.diagnostic_tasks_feature.interface_version.render() == "1.0"
    )
    assert context.diagnostic_tasks_context == DiagnosticTasksContext.workspace()

    context.diagnostic_tasks_feature.close()
    context.run_monitoring_feature.close()
    context.evidence_and_findings_feature.close()


def test_production_composition_uses_only_the_live_diagnostic_tasks_adapter(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    application = create_diagnostics_application()
    application.start()
    application_adapter = (
        LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(application)
    )

    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="live",
        event_bridge=EventBridge(subscribe_backend=False),
        strategy_diagnostics_read_model=cast(
            StrategyDiagnosticsV1ApplicationReadModel,
            object(),
        ),
        strategy_diagnostics_tasks_application=application_adapter,
    )

    assert isinstance(context.diagnostic_tasks_feature, LiveDiagnosticTasksAdapter)
    assert not isinstance(
        context.diagnostic_tasks_feature,
        DeterministicFakeDiagnosticTasksAdapter,
    )
    assert (
        context.strategy_diagnostics_tasks_application is application_adapter
    )

    context.diagnostic_tasks_feature.close()
    context.run_monitoring_feature.close()
    context.evidence_and_findings_feature.close()
