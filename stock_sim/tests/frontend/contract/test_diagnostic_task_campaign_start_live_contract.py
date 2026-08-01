from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from threading import Barrier, Lock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import SQLAlchemyError

from app.event_bridge import EventBridge
from app.features import (
    ApplicationReadAvailability,
    ApproveDiagnosticTaskConfiguration,
    DeterministicFakeDiagnosticTasksAdapter,
    DiagnosticActorId,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    DiagnosticTaskCommandRejectionReason,
    DiagnosticTaskConfiguration,
    DiagnosticTaskLifecycle,
    DiagnosticTasksCommandDisposition,
    DiagnosticTasksContext,
    LiveDiagnosticTasksAdapter,
    LiveRunMonitoringAdapter,
    LiveStrategyDiagnosticsV1ApplicationAdapter,
    LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
    ReviseDiagnosticTaskConfiguration,
    RunMonitoringContext,
    RunMonitoringPresentationState,
    RunMonitoringSelection,
    StartFormalDiagnosticCampaign,
    TaskPhase,
    V1JourneySelector,
    ValidateDiagnosticTaskConfiguration,
)
from strategy_diagnostics import (
    PTRADE_EMBEDDED_PRODUCTION_HOST_VERSION,
    create_diagnostics_application,
)
from strategy_diagnostics.market_paths import InMemoryMarketPathArtifactStore
from tests.frontend.contract.test_diagnostic_task_creation_live_contract import (
    _command,
    _configuration,
)
from tests.frontend.contract.test_diagnostic_task_revision_approval_live_contract import (
    _persistent_three_layer_stack,
    _read_task,
)
from tests.frontend.contract.test_strategy_diagnostics_v1_run_monitoring_live_contract import (
    _DirectExecutor,
)
from tests.strategy_diagnostics.test_market_path_materialization import (
    _AdmittedShockFixtureSource,
    _segment,
)
from tests.strategy_diagnostics.test_recipe_lifecycle import _baseline_payload

_FORMAL_ISOLATED_LEVELS: dict[str, tuple[dict[str, object], ...]] = {
    "trend-regime.v1": (
        {"direction": "bullish", "strength": "0.25"},
        {"direction": "bearish", "strength": "0.75"},
    ),
    "volatility-scaling.v1": (
        {"multiplier": "0.75"},
        {"multiplier": "1.5"},
    ),
    "shock-recovery.v1": (
        {
            "direction": "bearish",
            "gap_fraction": "0.01",
            "shock_fraction": "0.03",
            "shock_duration_bars": 2,
            "persistence_duration_bars": 1,
            "recovery_duration_bars": 2,
        },
        {
            "direction": "bearish",
            "gap_fraction": "0.02",
            "shock_fraction": "0.05",
            "shock_duration_bars": 2,
            "persistence_duration_bars": 1,
            "recovery_duration_bars": 2,
        },
    ),
    "market-structure.v1": (
        {
            "breadth_target": "0.3",
            "dispersion_fraction": "0.03",
            "sector_concentration": "0.3",
        },
        {
            "breadth_target": "0.7",
            "dispersion_fraction": "0.06",
            "sector_concentration": "0.8",
        },
    ),
    "liquidity-stress.v1": (
        {
            "volume_multiplier": "0.5",
            "cross_sectional_concentration": "0.2",
        },
        {
            "volume_multiplier": "1.5",
            "cross_sectional_concentration": "0.8",
        },
    ),
    "execution-stress.v1": (
        {"slippage_bps": "25"},
        {"slippage_bps": "100"},
    ),
}


class _FormalCampaignFixtureSource(_AdmittedShockFixtureSource):
    def load_scenario_data_world(self, segment):
        world = super().load_scenario_data_world(segment)
        return replace(
            world,
            instrument_states=tuple(
                replace(
                    state,
                    industry=(
                        "technology"
                        if state.instrument == "sz.000001"
                        else state.industry
                    ),
                )
                for state in world.instrument_states
            ),
        )


def _formal_live_stack(
    tmp_path,
    *,
    ptrade_host=None,
    evidence_artifact_store=None,
):
    source = _FormalCampaignFixtureSource()
    artifact_store = InMemoryMarketPathArtifactStore()
    engine = create_engine(
        f"sqlite:///{tmp_path / 'diagnostic-task-campaign.db'}",
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
        ptrade_host=ptrade_host,
        evidence_artifact_store=evidence_artifact_store,
    )
    application.start()
    application.initialize_persistence(engine)
    admission = application.admit_historical_segment(_segment().selection)
    assert admission.segment is not None
    baseline_payload = _formal_recipe_payload(
        admission.segment.segment_id,
        name="Formal baseline control",
        transformations=[],
    )
    baseline_draft = application.create_manual_recipe_draft(
        baseline_payload,
        author="researcher",
    )
    assert application.validate_recipe_draft(baseline_draft.draft_id).is_valid
    baseline = application.approve_recipe_draft(
        baseline_draft.draft_id,
        actor="owner",
    )
    application.materialize_baseline_reference_path(baseline.version_id)
    _add_formal_campaign_inputs(application)
    application_adapter = (
        LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(application)
    )
    feature = LiveDiagnosticTasksAdapter(application=application_adapter)
    return source, artifact_store, engine, application, application_adapter, feature


def _formal_recipe_payload(
    segment_id: str,
    *,
    name: str,
    transformations: list[dict[str, object]],
) -> dict[str, object]:
    payload = deepcopy(_baseline_payload(segment_id))
    payload["name"] = name
    payload["transformations"] = transformations
    execution_conditions = dict(payload["execution_conditions"])
    execution_conditions["slippage_bps"] = "5"
    payload["execution_conditions"] = execution_conditions
    return payload


def _add_formal_campaign_inputs(application: object) -> None:
    segment_id = application.list_historical_segments()[0].segment_id
    for transformation_id, levels in _FORMAL_ISOLATED_LEVELS.items():
        for level_number, parameters in enumerate(levels, start=1):
            payload = _formal_recipe_payload(
                segment_id,
                name=f"{transformation_id} formal sensitivity {level_number}",
                transformations=[
                    {
                        "transformation_id": transformation_id,
                        "parameters": parameters,
                    }
                ],
            )
            draft = application.create_manual_recipe_draft(
                payload,
                author="researcher",
            )
            assert application.validate_recipe_draft(draft.draft_id).is_valid
            approved = application.approve_recipe_draft(
                draft.draft_id,
                actor="owner",
            )
            application.materialize_reference_path(approved.version_id)
    compound_payload = _formal_recipe_payload(
        segment_id,
        name="Trend and volatility formal compound",
        transformations=[
            {
                "transformation_id": "trend-regime.v1",
                "parameters": {
                    "direction": "bullish",
                    "strength": "0.25",
                },
            },
            {
                "transformation_id": "volatility-scaling.v1",
                "parameters": {"multiplier": "1.5"},
            },
        ],
    )
    compound_draft = application.create_manual_recipe_draft(
        compound_payload,
        author="researcher",
    )
    assert application.validate_recipe_draft(compound_draft.draft_id).is_valid
    compound = application.approve_recipe_draft(
        compound_draft.draft_id,
        actor="owner",
    )
    application.materialize_reference_path(compound.version_id)


def _approved_formal_task(feature):
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    inventory = feature.snapshot(workspace).last_reliable_inventory
    assert inventory is not None
    configuration = _configuration(inventory)
    created = feature.create_diagnostic_task(
        _command(
            configuration,
            command_id="create-command-59",
            idempotency_key="create-idempotency-59",
        )
    )
    assert created.affected_task_id is not None
    task_id = created.affected_task_id
    task = _read_task(feature, task_id)

    validated = feature.validate_configuration(
        ValidateDiagnosticTaskConfiguration(
            command_id=DiagnosticCommandId("validate-command-59"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "validate-idempotency-59"
            ),
            task_id=task_id,
            expected_revision=task.revision,
        )
    )
    assert validated.disposition is (
        DiagnosticTasksCommandDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    task = _read_task(feature, task_id)
    assert task.validation.validation_id is not None
    assert task.validation.validation_revision is not None
    assert task.validation.validated_revision is not None
    assert task.validation.configuration_content_identity is not None

    approved = feature.approve_configuration(
        ApproveDiagnosticTaskConfiguration(
            command_id=DiagnosticCommandId("approve-command-59"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "approve-idempotency-59"
            ),
            task_id=task_id,
            expected_revision=task.revision,
            validation_id=task.validation.validation_id,
            validation_revision=task.validation.validation_revision,
            validated_revision=task.validation.validated_revision,
            configuration_content_id=(
                task.validation.configuration_content_identity
            ),
            actor_id=DiagnosticActorId("wave2-release-owner"),
        )
    )
    assert approved.disposition is (
        DiagnosticTasksCommandDisposition.SYNCHRONOUS_COMPLETION
    )
    approved_task = _read_task(feature, task_id)
    assert approved_task.lifecycle is DiagnosticTaskLifecycle.APPROVED
    return approved_task


@pytest.fixture(params=("live", "fake"))
def formal_feature(request, tmp_path):
    (
        _source,
        _artifact_store,
        _engine,
        _application,
        _application_adapter,
        live_feature,
    ) = _formal_live_stack(tmp_path)
    if request.param == "live":
        yield live_feature
        live_feature.close()
        return
    workspace = DiagnosticTasksContext.workspace()
    live_feature.snapshot(workspace)
    inventory = live_feature.snapshot(workspace).last_reliable_inventory
    assert inventory is not None
    live_feature.close()
    fake_feature = DeterministicFakeDiagnosticTasksAdapter(
        inventory=inventory,
    )
    yield fake_feature
    fake_feature.close()


def test_live_and_fake_share_formal_campaign_start_conformance(
    formal_feature,
) -> None:
    approved_task = _approved_formal_task(formal_feature)
    command = StartFormalDiagnosticCampaign(
        command_id=DiagnosticCommandId("start-command-59"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            "start-idempotency-59"
        ),
        task_id=approved_task.task_id,
        expected_revision=approved_task.revision,
        approved_revision=approved_task.revision,
    )

    accepted = formal_feature.start_formal_diagnostic_campaign(command)

    assert accepted.disposition is (
        DiagnosticTasksCommandDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    assert accepted.task_handle is not None
    assert accepted.task_handle.phase is TaskPhase.QUEUED
    assert accepted.affected_campaign_id is not None
    running_task = _read_task(formal_feature, approved_task.task_id)
    assert running_task.lifecycle is DiagnosticTaskLifecycle.RUNNING
    assert running_task.handoff.campaign_id == accepted.affected_campaign_id
    assert running_task.handoff.ready_for_run_monitoring
    persisted_handle = next(
        item
        for item in running_task.task_handles
        if item.identity == accepted.task_handle.identity
    )
    assert persisted_handle.phase is TaskPhase.COMPLETED
    assert persisted_handle.result == "formal_diagnostic_campaign_started"

    replay = formal_feature.start_formal_diagnostic_campaign(
        replace(
            command,
            command_id=DiagnosticCommandId("start-command-59-replay"),
        )
    )
    assert replay.disposition is (
        DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    )
    assert replay.affected_campaign_id == accepted.affected_campaign_id
    assert replay.task_handle is not None
    assert replay.task_handle.identity == accepted.task_handle.identity
    validation_rejected = formal_feature.validate_configuration(
        ValidateDiagnosticTaskConfiguration(
            command_id=DiagnosticCommandId(
                "validate-command-59-after-start"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "validate-idempotency-59-after-start"
            ),
            task_id=approved_task.task_id,
            expected_revision=approved_task.revision,
        )
    )
    assert validation_rejected.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.INVALID_COMMAND
    )
    assert (
        _read_task(formal_feature, approved_task.task_id).lifecycle
        is DiagnosticTaskLifecycle.RUNNING
    )


def test_start_exact_approved_revision_persists_one_formal_campaign_and_handoff(
    tmp_path,
) -> None:
    (
        _source,
        artifact_store,
        engine,
        application,
        _application_adapter,
        feature,
    ) = _formal_live_stack(tmp_path)
    approved_task = _approved_formal_task(feature)
    command = StartFormalDiagnosticCampaign(
        command_id=DiagnosticCommandId("start-command-59"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            "start-idempotency-59"
        ),
        task_id=approved_task.task_id,
        expected_revision=approved_task.revision,
        approved_revision=approved_task.revision,
    )

    accepted = feature.start_formal_diagnostic_campaign(command)

    assert accepted.disposition is (
        DiagnosticTasksCommandDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    assert accepted.task_handle is not None
    assert accepted.task_handle.phase is TaskPhase.QUEUED
    assert accepted.affected_campaign_id is not None
    campaign_id = accepted.affected_campaign_id
    task_handle_id = accepted.task_handle.identity

    running_task = _read_task(feature, approved_task.task_id)
    assert running_task.lifecycle is DiagnosticTaskLifecycle.RUNNING
    assert running_task.handoff.campaign_id == campaign_id
    assert running_task.handoff.ready_for_run_monitoring
    assert (
        running_task.handoff.selected_cases
        == approved_task.configuration.campaign_case_selections
    )
    assert (
        running_task.configuration.strategy_selections
        == approved_task.configuration.strategy_selections
    )
    assert running_task.handoff.evidence_package_id is None
    assert running_task.handoff.reproduction_manifest_id is None
    persisted_handle = next(
        item
        for item in running_task.task_handles
        if item.identity == task_handle_id
    )
    assert persisted_handle.phase is TaskPhase.COMPLETED
    assert persisted_handle.result == "formal_diagnostic_campaign_started"

    campaign = application.diagnostic_campaign_status(campaign_id.value)
    assert campaign.specification.campaign_type == "formal_diagnostic_campaign"
    isolated = campaign.specification.isolated_sensitivity_set
    assert isolated is not None
    assert {
        sweep.transformation_id: len(sweep.levels)
        for sweep in isolated.sweeps
    } == {family: 2 for family in _FORMAL_ISOLATED_LEVELS}
    assert {
        (
            selection.strategy_id,
            selection.strategy_version,
            selection.guardrail_profile_id,
            selection.guardrail_profile_version,
        )
        for selection in campaign.specification.approved_strategies
    } == {
        (
            selection.strategy_id.value,
            selection.strategy_version,
            selection.guardrail_profile_id.value,
            selection.guardrail_profile_version,
        )
        for selection in approved_task.configuration.strategy_selections
    }
    assert {
        case.case_id for case in campaign.cases
    } == {
        node.campaign_case_id.value
        for node in running_task.handoff.campaign_nodes
    }
    assert {
        node.selected_campaign_case_id.value
        for node in running_task.handoff.campaign_nodes
    } == {
        selection.campaign_case_id.value
        for selection in running_task.handoff.selected_cases
    }
    assert campaign.completed_count == 1
    assert campaign.pending_count > 0
    attempt = next(
        attempt
        for node in running_task.handoff.campaign_nodes
        for attempt in node.attempts
    )
    assert len(attempt.run_ids) == 2
    run_snapshots = tuple(
        application.strategy_run_status(run_id.value)
        for run_id in attempt.run_ids
    )
    assert {run.run_id for run in run_snapshots} == {
        run_id.value for run_id in attempt.run_ids
    }
    assert {run.specification.strategy_id for run in run_snapshots} == {
        strategy.strategy_id.value
        for strategy in approved_task.configuration.strategy_selections
    }
    assert {
        (member.run_id.value, member.strategy_id.value)
        for member in attempt.runs
    } == {
        (run.run_id, run.specification.strategy_id)
        for run in run_snapshots
    }
    selected_by_materialization = {
        selection.market_scenario_id.value: selection
        for selection in running_task.handoff.selected_cases
    }
    for run in run_snapshots:
        selection = selected_by_materialization[
            run.specification.materialization_hash
        ]
        assert run.specification.recipe_version_id == (
            selection.recipe_version_id.value
        )
        assert run.specification.recipe_content_hash == (
            selection.recipe_content_hash
        )

    replay = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-command-59-retry"),
            idempotency_key=command.idempotency_key,
            task_id=command.task_id,
            expected_revision=command.expected_revision,
            approved_revision=command.approved_revision,
        )
    )
    assert replay.disposition is (
        DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    )
    assert replay.affected_campaign_id == campaign_id
    assert replay.task_handle is not None
    assert replay.task_handle.identity == task_handle_id
    command_identity_conflict = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=command.command_id,
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-idempotency-59-conflict"
            ),
            task_id=command.task_id,
            expected_revision=command.expected_revision,
            approved_revision=command.approved_revision,
        )
    )
    assert command_identity_conflict.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.COMMAND_IDENTITY_CONFLICT
    )
    idempotency_conflict = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId(
                "start-command-59-content-conflict"
            ),
            idempotency_key=command.idempotency_key,
            task_id=command.task_id,
            expected_revision=command.expected_revision,
            approved_revision=command.approved_revision + 1,
        )
    )
    assert idempotency_conflict.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.IDEMPOTENCY_CONFLICT
    )

    application_read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
    )
    run_id = attempt.run_ids[0]
    selection = RunMonitoringSelection(
        campaign_id=campaign_id,
        run_id=run_id,
    )
    resolved = application_read_model.resolve_journey(
        V1JourneySelector(
            campaign_id=campaign_id,
            run_id=run_id,
        )
    )
    assert resolved.availability is ApplicationReadAvailability.PENDING
    assert resolved.value is not None
    run_monitoring = LiveRunMonitoringAdapter(
        application_read_model=application_read_model,
        event_bridge=EventBridge(subscribe_backend=False),
        executor=_DirectExecutor(),
    )
    run_state = run_monitoring.snapshot(
        RunMonitoringContext.for_run(selection)
    )
    assert run_state.presentation in {
        RunMonitoringPresentationState.ACTIVE,
        RunMonitoringPresentationState.TERMINAL,
    }
    assert run_state.last_reliable_data is not None
    assert run_state.last_reliable_data.selection == selection
    run_monitoring.close()

    with engine.connect() as connection:
        campaign_count = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM diagnostic_campaigns"
        ).scalar_one()
        start_command_count = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM diagnostic_task_mutation_commands "
            "WHERE command_type = 'start_formal_diagnostic_campaign'"
        ).scalar_one()
        handoff_count = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM diagnostic_task_campaign_handoffs"
        ).scalar_one()
    assert campaign_count == 1
    assert start_command_count == 1
    assert handoff_count == 1

    reopened = create_diagnostics_application(
        historical_source=_source,
        market_data_source=_source,
        artifact_store=artifact_store,
        recipe_clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        diagnostic_task_clock=lambda: datetime(
            2030,
            1,
            2,
            tzinfo=timezone.utc,
        ),
    )
    reopened.start()
    reopened.initialize_persistence(engine)
    reopened_feature = LiveDiagnosticTasksAdapter(
        application=(
            LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
                reopened
            )
        )
    )
    reopened_task = _read_task(reopened_feature, approved_task.task_id)
    assert reopened_task.lifecycle is DiagnosticTaskLifecycle.RUNNING
    assert reopened_task.handoff == running_task.handoff
    assert next(
        item
        for item in reopened_task.task_handles
        if item.identity == task_handle_id
    ).phase is TaskPhase.COMPLETED
    assert (
        reopened.diagnostic_campaign_status(campaign_id.value).campaign_id
        == campaign_id.value
    )
    assert reopened.strategy_run_status(run_id.value).run_id == run_id.value
    reopened_feature.close()


def test_default_start_uses_the_single_process_production_host(
    tmp_path,
) -> None:
    (
        _source,
        _artifact_store,
        _engine,
        application,
        _application_adapter,
        feature,
    ) = _formal_live_stack(tmp_path)
    approved_task = _approved_formal_task(feature)

    accepted = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId(
                "start-command-59-embedded-production"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-idempotency-59-embedded-production"
            ),
            task_id=approved_task.task_id,
            expected_revision=approved_task.revision,
            approved_revision=approved_task.revision,
        )
    )

    assert accepted.disposition is (
        DiagnosticTasksCommandDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    assert accepted.affected_campaign_id is not None
    campaign = application.diagnostic_campaign_status(
        accepted.affected_campaign_id.value
    )
    assert campaign.completed_count == 1
    completed_case = next(
        case for case in campaign.cases if case.status == "completed"
    )
    completed_attempt = completed_case.attempts[-1]
    completed_runs = tuple(
        application.strategy_run_status(str(member["run_id"]))
        for member in completed_attempt.to_dict()["members"]
    )
    assert {
        run.specification.ptrade_host_adapter_version
        for run in completed_runs
    } == {PTRADE_EMBEDDED_PRODUCTION_HOST_VERSION}
    assert all(
        run.ptrade_audit is not None
        and run.ptrade_audit.host_adapter_versions
        == (PTRADE_EMBEDDED_PRODUCTION_HOST_VERSION,)
        for run in completed_runs
    )
    feature.close()


def test_retry_after_handoff_persistence_failure_does_not_advance_another_case(
    tmp_path,
) -> None:
    (
        _source,
        _artifact_store,
        engine,
        application,
        _application_adapter,
        feature,
    ) = _formal_live_stack(tmp_path)
    approved_task = _approved_formal_task(feature)
    command = StartFormalDiagnosticCampaign(
        command_id=DiagnosticCommandId("start-command-59-fault"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            "start-idempotency-59-fault"
        ),
        task_id=approved_task.task_id,
        expected_revision=approved_task.revision,
        approved_revision=approved_task.revision,
    )
    failed_once = False

    def fail_first_handoff_insert(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        nonlocal failed_once
        if (
            not failed_once
            and "INSERT INTO diagnostic_task_campaign_handoffs" in statement
        ):
            failed_once = True
            raise SQLAlchemyError("synthetic handoff persistence failure")

    event.listen(engine, "before_cursor_execute", fail_first_handoff_insert)
    try:
        accepted = feature.start_formal_diagnostic_campaign(command)
    finally:
        event.remove(
            engine,
            "before_cursor_execute",
            fail_first_handoff_insert,
        )

    assert accepted.disposition is (
        DiagnosticTasksCommandDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    assert accepted.affected_campaign_id is not None
    campaign_id = accepted.affected_campaign_id
    after_fault = application.diagnostic_campaign_status(campaign_id.value)
    attempts_after_fault = tuple(
        (case.case_id, len(case.attempts)) for case in after_fault.cases
    )
    assert after_fault.completed_count == 1
    assert sum(count for _case_id, count in attempts_after_fault) == 1

    replay = feature.start_formal_diagnostic_campaign(
        replace(
            command,
            command_id=DiagnosticCommandId("start-command-59-fault-retry"),
        )
    )

    assert replay.disposition is (
        DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    )
    assert replay.affected_campaign_id == campaign_id
    after_retry = application.diagnostic_campaign_status(campaign_id.value)
    assert tuple(
        (case.case_id, len(case.attempts)) for case in after_retry.cases
    ) == attempts_after_fault
    running_task = _read_task(feature, approved_task.task_id)
    assert running_task.lifecycle is DiagnosticTaskLifecycle.RUNNING
    assert running_task.handoff.campaign_id == campaign_id


def test_concurrent_same_idempotency_claims_one_durable_start_continuation(
    tmp_path,
    monkeypatch,
) -> None:
    (
        _source,
        _artifact_store,
        _engine,
        application,
        _application_adapter,
        feature,
    ) = _formal_live_stack(tmp_path)
    approved_task = _approved_formal_task(feature)
    command = StartFormalDiagnosticCampaign(
        command_id=DiagnosticCommandId("start-command-59-concurrent"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            "start-idempotency-59-concurrent"
        ),
        task_id=approved_task.task_id,
        expected_revision=approved_task.revision,
        approved_revision=approved_task.revision,
    )
    both_claiming = Barrier(2)
    original_claim = application._diagnostic_tasks.claim_start_continuation
    original_executor = application._diagnostic_campaigns._executor
    executor_invocations = 0
    executor_invocations_lock = Lock()

    def synchronized_claim(task_handle_id, continuation_claim_id):
        both_claiming.wait(timeout=10)
        return original_claim(task_handle_id, continuation_claim_id)

    def counted_executor(*args, **kwargs):
        nonlocal executor_invocations
        with executor_invocations_lock:
            executor_invocations += 1
        return original_executor(*args, **kwargs)

    monkeypatch.setattr(
        application._diagnostic_tasks,
        "claim_start_continuation",
        synchronized_claim,
    )
    monkeypatch.setattr(
        application._diagnostic_campaigns,
        "_executor",
        counted_executor,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            executor.map(
                feature.start_formal_diagnostic_campaign,
                (
                    command,
                    replace(
                        command,
                        command_id=DiagnosticCommandId(
                            "start-command-59-concurrent-replay"
                        ),
                    ),
                ),
            )
        )

    task = _read_task(feature, approved_task.task_id)
    assert task.handoff.ready_for_run_monitoring
    assert {result.affected_campaign_id for result in results} == {
        task.handoff.campaign_id
    }
    assert len(
        {
            result.task_handle.identity
            for result in results
            if result.task_handle is not None
        }
    ) == 1
    attempts = tuple(
        attempt
        for node in task.handoff.campaign_nodes
        for attempt in node.attempts
    )
    assert executor_invocations == 1
    assert len(attempts) == 1
    assert len(attempts[0].run_ids) == 2
    assert len(set(attempts[0].run_ids)) == 2


def test_application_reopen_resumes_a_durably_accepted_queued_start(
    tmp_path,
) -> None:
    (
        source,
        artifact_store,
        engine,
        application,
        _application_adapter,
        feature,
    ) = _formal_live_stack(tmp_path)
    approved_task = _approved_formal_task(feature)
    command = StartFormalDiagnosticCampaign(
        command_id=DiagnosticCommandId("start-command-59-reopen"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            "start-idempotency-59-reopen"
        ),
        task_id=approved_task.task_id,
        expected_revision=approved_task.revision,
        approved_revision=approved_task.revision,
    )
    failed_once = False

    def fail_first_handoff_insert(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        nonlocal failed_once
        if (
            not failed_once
            and "INSERT INTO diagnostic_task_campaign_handoffs" in statement
        ):
            failed_once = True
            raise SQLAlchemyError("synthetic pre-reopen interruption")

    event.listen(engine, "before_cursor_execute", fail_first_handoff_insert)
    try:
        accepted = feature.start_formal_diagnostic_campaign(command)
    finally:
        event.remove(
            engine,
            "before_cursor_execute",
            fail_first_handoff_insert,
        )
    assert accepted.affected_campaign_id is not None
    campaign_id = accepted.affected_campaign_id
    before_reopen = application.diagnostic_campaign_status(campaign_id.value)
    attempts_before_reopen = tuple(
        (case.case_id, len(case.attempts)) for case in before_reopen.cases
    )
    assert (
        _read_task(feature, approved_task.task_id).lifecycle
        is DiagnosticTaskLifecycle.QUEUED
    )
    assert accepted.task_handle is not None
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE diagnostic_task_handles "
            "SET start_continuation_claim_id = 'crashed-owner-59', "
            "start_continuation_claimed_at_utc = "
            "'2030-01-02T00:00:00+00:00' "
            "WHERE task_handle_id = ?",
            (accepted.task_handle.identity.value,),
        )
    feature.close()

    reopened = create_diagnostics_application(
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
    reopened.start()
    reopened.initialize_persistence(engine)
    reopened_feature = LiveDiagnosticTasksAdapter(
        application=(
            LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
                reopened
            )
        )
    )

    recovered_task = _read_task(reopened_feature, approved_task.task_id)
    assert recovered_task.lifecycle is DiagnosticTaskLifecycle.RUNNING
    assert recovered_task.handoff.campaign_id == campaign_id
    assert tuple(
        (case.case_id, len(case.attempts))
        for case in reopened.diagnostic_campaign_status(campaign_id.value).cases
    ) == attempts_before_reopen
    assert next(
        handle
        for handle in recovered_task.task_handles
        if handle.identity == accepted.task_handle.identity
    ).phase is TaskPhase.COMPLETED
    reopened_feature.close()


def test_running_task_rejects_configuration_mutations_in_backend(
    tmp_path,
) -> None:
    (
        _source,
        _artifact_store,
        engine,
        _application,
        _application_adapter,
        feature,
    ) = _formal_live_stack(tmp_path)
    approved_task = _approved_formal_task(feature)
    command = StartFormalDiagnosticCampaign(
        command_id=DiagnosticCommandId("start-command-59-immutable"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            "start-idempotency-59-immutable"
        ),
        task_id=approved_task.task_id,
        expected_revision=approved_task.revision,
        approved_revision=approved_task.revision,
    )
    accepted = feature.start_formal_diagnostic_campaign(command)
    assert accepted.affected_campaign_id is not None
    running_task = _read_task(feature, approved_task.task_id)
    corrected = DiagnosticTaskConfiguration.create(
        strategy_selections=running_task.configuration.strategy_selections,
        campaign_case_selections=(
            running_task.configuration.campaign_case_selections[:-1]
        ),
    )

    revise_rejected = feature.revise_configuration(
        ReviseDiagnosticTaskConfiguration(
            command_id=DiagnosticCommandId("revise-command-59-running"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "revise-idempotency-59-running"
            ),
            task_id=running_task.task_id,
            expected_revision=running_task.revision,
            configuration=corrected,
        )
    )
    validate_rejected = feature.validate_configuration(
        ValidateDiagnosticTaskConfiguration(
            command_id=DiagnosticCommandId("validate-command-59-running"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "validate-idempotency-59-running"
            ),
            task_id=running_task.task_id,
            expected_revision=running_task.revision,
        )
    )

    assert revise_rejected.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.INVALID_COMMAND
    )
    assert validate_rejected.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.INVALID_COMMAND
    )
    assert _read_task(feature, running_task.task_id) == running_task
    with engine.connect() as connection:
        mutation_count = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM diagnostic_task_mutation_commands "
            "WHERE command_id IN ("
            "'revise-command-59-running', "
            "'validate-command-59-running')"
        ).scalar_one()
    assert mutation_count == 0


def test_incomplete_formal_input_is_rejected_before_start_side_effects(
    tmp_path,
) -> None:
    (
        _source,
        _artifact_store,
        engine,
        _application,
        _application_adapter,
        feature,
    ) = _persistent_three_layer_stack(tmp_path)
    approved_task = _approved_formal_task(feature)

    rejected = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId(
                "start-command-59-incomplete"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-idempotency-59-incomplete"
            ),
            task_id=approved_task.task_id,
            expected_revision=approved_task.revision,
            approved_revision=approved_task.revision,
        )
    )

    assert rejected.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.UNAVAILABLE_INPUT
    )
    assert rejected.task_handle is None
    assert rejected.affected_campaign_id is None
    assert (
        _read_task(feature, approved_task.task_id).lifecycle
        is DiagnosticTaskLifecycle.APPROVED
    )
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM diagnostic_campaigns"
        ).scalar_one() == 0
        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM diagnostic_task_mutation_commands "
            "WHERE command_type = 'start_formal_diagnostic_campaign'"
        ).scalar_one() == 0
        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM diagnostic_task_campaign_handoffs"
        ).scalar_one() == 0
