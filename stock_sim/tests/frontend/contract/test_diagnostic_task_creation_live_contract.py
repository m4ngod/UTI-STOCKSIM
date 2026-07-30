from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from app.features import (
    CreateDiagnosticTask,
    DeterministicFakeDiagnosticTasksAdapter,
    DiagnosticCampaignCaseSelection,
    DiagnosticCampaignLayer,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    DiagnosticComparisonRole,
    DiagnosticStrategySelection,
    DiagnosticTaskConfiguration,
    DiagnosticTaskConfigurationContentId,
    DiagnosticTaskLifecycle,
    DiagnosticTasksApplicationCommandRejectionReason,
    DiagnosticTasksCommandDisposition,
    DiagnosticTasksContext,
    DiagnosticTasksPresentationState,
    LiveDiagnosticTasksAdapter,
    LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
    StrategyDiagnosticsV1DiagnosticTasksApplication,
    TaskPhase,
)
from strategy_diagnostics import create_diagnostics_application
from strategy_diagnostics.market_paths import InMemoryMarketPathArtifactStore
from tests.strategy_diagnostics.test_recipe_lifecycle import (
    _baseline_payload,
    _RecipeFixtureSource,
)


def _persistent_live_stack(tmp_path):
    source = _RecipeFixtureSource()
    artifact_store = InMemoryMarketPathArtifactStore()
    engine = create_engine(
        f"sqlite:///{tmp_path / 'diagnostic-tasks.db'}",
        future=True,
    )
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=artifact_store,
        recipe_clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        diagnostic_task_clock=lambda: datetime(
            2030,
            1,
            2,
            tzinfo=timezone.utc,
        ),
    )
    application.start()
    application.initialize_persistence(engine)
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    draft = application.create_manual_recipe_draft(
        _baseline_payload(admission.segment.segment_id),
        author="researcher",
    )
    assert application.validate_recipe_draft(draft.draft_id).is_valid
    approved = application.approve_recipe_draft(draft.draft_id, actor="owner")
    application.materialize_baseline_reference_path(approved.version_id)
    application_adapter = (
        LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(application)
    )
    feature = LiveDiagnosticTasksAdapter(application=application_adapter)
    return (
        source,
        artifact_store,
        engine,
        application,
        application_adapter,
        feature,
    )


def _configuration(inventory) -> DiagnosticTaskConfiguration:
    recipe_by_id = {
        item.recipe_version_id: item for item in inventory.approved_recipes
    }
    baseline_case_id = next(
        item.campaign_case_id
        for item in inventory.market_scenarios
        if item.layer is DiagnosticCampaignLayer.BASELINE
    )
    return DiagnosticTaskConfiguration.create(
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
            for item in inventory.market_scenarios
        ),
    )


def _command(
    configuration: DiagnosticTaskConfiguration,
    *,
    command_id: str = "create-command-57",
    idempotency_key: str = "create-idempotency-57",
) -> CreateDiagnosticTask:
    return CreateDiagnosticTask(
        command_id=DiagnosticCommandId(command_id),
        idempotency_key=DiagnosticCommandIdempotencyKey(idempotency_key),
        configuration=configuration,
    )


def test_live_create_is_durable_idempotent_and_reopens_without_a_campaign(
    tmp_path,
) -> None:
    (
        source,
        artifact_store,
        engine,
        _application,
        application_adapter,
        feature,
    ) = _persistent_live_stack(tmp_path)
    assert isinstance(
        application_adapter,
        StrategyDiagnosticsV1DiagnosticTasksApplication,
    )
    assert {
        name
        for name in StrategyDiagnosticsV1DiagnosticTasksApplication.__dict__
        if not name.startswith("_")
    } >= {"read_diagnostic_task", "create_diagnostic_task"}
    context = DiagnosticTasksContext.workspace()
    assert (
        feature.snapshot(context).presentation
        is DiagnosticTasksPresentationState.LOADING
    )
    ready = feature.snapshot(context)
    assert ready.last_reliable_inventory is not None
    configuration = _configuration(ready.last_reliable_inventory)

    accepted = feature.create_diagnostic_task(_command(configuration))

    assert accepted.disposition is (
        DiagnosticTasksCommandDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    assert accepted.task_handle is not None
    assert accepted.task_handle.phase is TaskPhase.QUEUED
    assert accepted.affected_task_id is not None
    task_id = accepted.affected_task_id
    handle_id = accepted.task_handle.identity

    task_context = DiagnosticTasksContext(task_id=task_id)
    assert (
        feature.snapshot(task_context).presentation
        is DiagnosticTasksPresentationState.LOADING
    )
    task_state = feature.snapshot(task_context)
    assert task_state.task is not None
    assert task_state.task.task_id == task_id
    assert task_state.task.revision == 2
    assert task_state.task.lifecycle is DiagnosticTaskLifecycle.DRAFT
    assert task_state.task.configuration == configuration
    assert task_state.task.task_handles[0].identity == handle_id
    assert task_state.task.task_handles[0].phase is TaskPhase.COMPLETED
    assert task_state.task.handoff.campaign_id is None

    replay = feature.create_diagnostic_task(
        _command(
            configuration,
            command_id="create-command-57-retry",
        )
    )
    assert replay.disposition is DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    assert replay.affected_task_id == task_id
    assert replay.task_handle is not None
    assert replay.task_handle.identity == handle_id

    conflicting_configuration = DiagnosticTaskConfiguration.create(
        strategy_selections=configuration.strategy_selections,
        campaign_case_selections=configuration.campaign_case_selections[:-1],
    )
    conflict = feature.create_diagnostic_task(
        _command(
            conflicting_configuration,
            command_id="create-command-57-conflict",
        )
    )
    assert conflict.disposition is DiagnosticTasksCommandDisposition.REJECTED
    assert conflict.rejection_reason is (
        DiagnosticTasksApplicationCommandRejectionReason.IDEMPOTENCY_CONFLICT
    )
    assert conflict.task_handle is None

    feature.close()
    restarted_application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=artifact_store,
        recipe_clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        diagnostic_task_clock=lambda: datetime(
            2030,
            1,
            3,
            tzinfo=timezone.utc,
        ),
    )
    restarted_application.start()
    restarted_application.initialize_persistence(engine)
    restarted = LiveDiagnosticTasksAdapter(
        application=LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
            restarted_application
        )
    )
    task_context = DiagnosticTasksContext(task_id=task_id)
    assert (
        restarted.snapshot(task_context).presentation
        is DiagnosticTasksPresentationState.LOADING
    )
    reopened = restarted.snapshot(task_context)

    assert reopened.task is not None
    assert reopened.task.task_id == task_id
    assert reopened.task.revision == 2
    assert reopened.task.task_handles[0].identity == handle_id
    assert reopened.task.task_handles[0].phase is TaskPhase.COMPLETED
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_tasks")
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_task_commands")
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_task_handles")
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_campaigns")
        ).scalar_one() == 0
    restarted.close()


def test_invalid_create_and_atomic_acceptance_failure_have_no_side_effect(
    tmp_path,
) -> None:
    (
        _source,
        _artifact_store,
        engine,
        _application,
        _application_adapter,
        feature,
    ) = _persistent_live_stack(tmp_path)
    context = DiagnosticTasksContext.workspace()
    feature.snapshot(context)
    inventory = feature.snapshot(context).last_reliable_inventory
    assert inventory is not None
    configuration = _configuration(inventory)
    invalid = replace(
        configuration,
        content_identity=DiagnosticTaskConfigurationContentId(
            "sha256:" + "0" * 64
        ),
    )

    rejected = feature.create_diagnostic_task(
        _command(
            invalid,
            command_id="invalid-create-command-57",
            idempotency_key="invalid-create-idempotency-57",
        )
    )

    assert rejected.disposition is DiagnosticTasksCommandDisposition.REJECTED
    assert rejected.rejection_reason is (
        DiagnosticTasksApplicationCommandRejectionReason.INVALID_COMMAND
    )
    assert rejected.task_handle is None
    with engine.begin() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_tasks")
        ).scalar_one() == 0
        connection.exec_driver_sql(
            "CREATE TRIGGER reject_diagnostic_task_handle "
            "BEFORE INSERT ON diagnostic_task_handles "
            "BEGIN SELECT RAISE(FAIL, 'injected handle persistence failure'); END"
        )

    failed = feature.create_diagnostic_task(
        _command(
            configuration,
            command_id="atomic-create-command-57",
            idempotency_key="atomic-create-idempotency-57",
        )
    )

    assert failed.disposition is DiagnosticTasksCommandDisposition.REJECTED
    assert failed.rejection_reason is (
        DiagnosticTasksApplicationCommandRejectionReason.PERSISTENCE_FAILURE
    )
    assert failed.retryable is True
    assert failed.task_handle is None
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_tasks")
        ).scalar_one() == 0
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_task_commands")
        ).scalar_one() == 0
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_task_handles")
        ).scalar_one() == 0

    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE diagnostic_task_commands")
    preflight_failure = feature.create_diagnostic_task(
        _command(
            configuration,
            command_id="preflight-create-command-57",
            idempotency_key="preflight-create-idempotency-57",
        )
    )
    assert preflight_failure.rejection_reason is (
        DiagnosticTasksApplicationCommandRejectionReason.PERSISTENCE_FAILURE
    )
    assert preflight_failure.retryable is True
    assert preflight_failure.task_handle is None
    feature.close()


def test_unstarted_application_create_is_a_typed_retryable_rejection() -> None:
    fake = DeterministicFakeDiagnosticTasksAdapter()
    context = DiagnosticTasksContext.workspace()
    fake.snapshot(context)
    inventory = fake.snapshot(context).last_reliable_inventory
    assert inventory is not None
    configuration = _configuration(inventory)
    application = create_diagnostics_application()
    adapter = LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
        application
    )

    rejected = adapter.create_diagnostic_task(
        _command(
            configuration,
            command_id="unstarted-command-57",
            idempotency_key="unstarted-idempotency-57",
        )
    )

    assert rejected.disposition is DiagnosticTasksCommandDisposition.REJECTED
    assert rejected.rejection_reason is (
        DiagnosticTasksApplicationCommandRejectionReason.DISCONNECTED_SOURCE
    )
    assert rejected.retryable is True
    assert rejected.task_handle is None
    fake.close()
