from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from app.event_bridge import EventBridge
from app.features import (
    ApproveDiagnosticTaskConfiguration,
    CancelDiagnosticTarget,
    DiagnosticActorId,
    DiagnosticCampaignLayer,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    DiagnosticTaskConfiguration,
    DiagnosticTaskLifecycle,
    DiagnosticTasksCommandDisposition,
    DiagnosticTasksContext,
    DiagnosticTaskTarget,
    LiveDiagnosticTasksAdapter,
    LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
    PauseDiagnosticTarget,
    ResumeDiagnosticTarget,
    ReviseDiagnosticTaskConfiguration,
    StartFormalDiagnosticCampaign,
    TaskPhase,
    ValidateDiagnosticTaskConfiguration,
)
from strategy_diagnostics import create_diagnostics_application
from tests.frontend.contract.test_diagnostic_task_campaign_start_live_contract import (
    _approved_formal_task,
    _formal_live_stack,
)
from tests.frontend.contract.test_diagnostic_task_creation_live_contract import (
    _command,
    _configuration,
)
from tests.frontend.contract.test_diagnostic_task_revision_approval_live_contract import (
    _persistent_three_layer_stack,
    _read_task,
)


def test_pre_campaign_commands_replay_after_application_restart(
    tmp_path,
) -> None:
    (
        source,
        artifact_store,
        engine,
        _application,
        _application_adapter,
        feature,
    ) = _persistent_three_layer_stack(tmp_path)
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    inventory = feature.snapshot(workspace).last_reliable_inventory
    assert inventory is not None
    full_configuration = _configuration(inventory)
    baseline_configuration = DiagnosticTaskConfiguration.create(
        strategy_selections=full_configuration.strategy_selections,
        campaign_case_selections=tuple(
            item
            for item in full_configuration.campaign_case_selections
            if item.layer is DiagnosticCampaignLayer.BASELINE
        ),
    )
    create = _command(
        baseline_configuration,
        command_id="create-command-62",
        idempotency_key="create-idempotency-62",
    )
    created = feature.create_diagnostic_task(create)
    assert created.affected_task_id is not None
    assert created.task_handle is not None
    task_id = created.affected_task_id
    revise = ReviseDiagnosticTaskConfiguration(
        command_id=DiagnosticCommandId("revise-command-62"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            "revise-idempotency-62"
        ),
        task_id=task_id,
        expected_revision=2,
        configuration=full_configuration,
    )
    revised = feature.revise_configuration(revise)
    assert revised.current_revision == 3
    validate = ValidateDiagnosticTaskConfiguration(
        command_id=DiagnosticCommandId("validate-command-62"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            "validate-idempotency-62"
        ),
        task_id=task_id,
        expected_revision=3,
    )
    validated = feature.validate_configuration(validate)
    assert validated.task_handle is not None
    validated_task = _read_task(feature, task_id)
    assert validated_task.validation.validation_id is not None
    assert validated_task.validation.validation_revision is not None
    assert validated_task.validation.validated_revision is not None
    assert (
        validated_task.validation.configuration_content_identity
        is not None
    )
    approve = ApproveDiagnosticTaskConfiguration(
        command_id=DiagnosticCommandId("approve-command-62"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            "approve-idempotency-62"
        ),
        task_id=task_id,
        expected_revision=3,
        validation_id=validated_task.validation.validation_id,
        validation_revision=validated_task.validation.validation_revision,
        validated_revision=validated_task.validation.validated_revision,
        configuration_content_id=(
            validated_task.validation.configuration_content_identity
        ),
        actor_id=DiagnosticActorId("wave2-recovery-owner"),
    )
    approved = feature.approve_configuration(approve)
    assert approved.accepted
    accepted_task = _read_task(feature, task_id)
    feature.close()
    feature.close()

    restarted_application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=artifact_store,
        recipe_clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        diagnostic_task_clock=lambda: datetime(
            2030,
            1,
            4,
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
    restored = _read_task(restarted, task_id)

    assert restored.configuration == accepted_task.configuration
    assert restored.validation == accepted_task.validation
    assert restored.approval == accepted_task.approval
    assert restored.task_handles == accepted_task.task_handles
    create_replay = restarted.create_diagnostic_task(
        replace(
            create,
            command_id=DiagnosticCommandId("create-replay-command-62"),
        )
    )
    revise_replay = restarted.revise_configuration(
        replace(
            revise,
            command_id=DiagnosticCommandId("revise-replay-command-62"),
        )
    )
    validate_replay = restarted.validate_configuration(
        replace(
            validate,
            command_id=DiagnosticCommandId("validate-replay-command-62"),
        )
    )
    approve_replay = restarted.approve_configuration(
        replace(
            approve,
            command_id=DiagnosticCommandId("approve-replay-command-62"),
        )
    )

    assert create_replay.disposition is (
        DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    )
    assert create_replay.task_handle is not None
    assert create_replay.task_handle.identity == created.task_handle.identity
    assert create_replay.task_handle.phase is TaskPhase.COMPLETED
    assert revise_replay.disposition is (
        DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    )
    assert validate_replay.disposition is (
        DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    )
    assert validate_replay.task_handle is not None
    assert validate_replay.task_handle.identity == validated.task_handle.identity
    assert validate_replay.task_handle.phase is TaskPhase.COMPLETED
    assert approve_replay.disposition is (
        DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    )

    restarted.close()


def test_campaign_lifecycle_replays_after_application_restart_without_regression(
    tmp_path,
) -> None:
    (
        source,
        artifact_store,
        engine,
        _application,
        _application_adapter,
        feature,
    ) = _formal_live_stack(tmp_path)
    approved = _approved_formal_task(feature)
    start = StartFormalDiagnosticCampaign(
        command_id=DiagnosticCommandId("start-command-62"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            "start-idempotency-62"
        ),
        task_id=approved.task_id,
        expected_revision=approved.revision,
        approved_revision=approved.revision,
    )
    started = feature.start_formal_diagnostic_campaign(start)
    assert started.task_handle is not None
    running = _read_task(feature, approved.task_id)
    pause = PauseDiagnosticTarget(
        command_id=DiagnosticCommandId("pause-command-62"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            "pause-idempotency-62"
        ),
        target=DiagnosticTaskTarget(running.task_id),
        expected_revision=running.revision,
    )
    paused_result = feature.pause_diagnostic_target(pause)
    assert paused_result.task_handle is not None
    paused = _read_task(feature, approved.task_id)
    assert paused.lifecycle is DiagnosticTaskLifecycle.PAUSED
    resume = ResumeDiagnosticTarget(
        command_id=DiagnosticCommandId("resume-command-62"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            "resume-idempotency-62"
        ),
        target=DiagnosticTaskTarget(paused.task_id),
        expected_revision=paused.revision,
    )
    resumed_result = feature.resume_diagnostic_target(resume)
    assert resumed_result.task_handle is not None
    resumed = _read_task(feature, approved.task_id)
    assert resumed.lifecycle is DiagnosticTaskLifecycle.RUNNING
    cancel = CancelDiagnosticTarget(
        command_id=DiagnosticCommandId("cancel-command-62"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            "cancel-idempotency-62"
        ),
        target=DiagnosticTaskTarget(resumed.task_id),
        expected_revision=resumed.revision,
    )
    canceled_result = feature.cancel_diagnostic_target(cancel)
    assert canceled_result.task_handle is not None
    canceled = _read_task(feature, approved.task_id)
    assert canceled.lifecycle is DiagnosticTaskLifecycle.CANCELED
    terminal_handles = canceled.task_handles
    feature.close()

    restarted_application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=artifact_store,
        recipe_clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        diagnostic_task_clock=lambda: datetime(
            2030,
            1,
            5,
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
    restored = _read_task(restarted, approved.task_id)

    assert restored.lifecycle is DiagnosticTaskLifecycle.CANCELED
    assert restored.task_handles == terminal_handles
    replays = (
        restarted.start_formal_diagnostic_campaign(
            replace(
                start,
                command_id=DiagnosticCommandId("start-replay-command-62"),
            )
        ),
        restarted.pause_diagnostic_target(
            replace(
                pause,
                command_id=DiagnosticCommandId("pause-replay-command-62"),
            )
        ),
        restarted.resume_diagnostic_target(
            replace(
                resume,
                command_id=DiagnosticCommandId("resume-replay-command-62"),
            )
        ),
        restarted.cancel_diagnostic_target(
            replace(
                cancel,
                command_id=DiagnosticCommandId("cancel-replay-command-62"),
            )
        ),
    )

    assert all(
        result.disposition
        is DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
        for result in replays
    )
    assert tuple(
        result.task_handle.identity
        for result in replays
        if result.task_handle is not None
    ) == (
        started.task_handle.identity,
        paused_result.task_handle.identity,
        resumed_result.task_handle.identity,
        canceled_result.task_handle.identity,
    )
    after_replay = _read_task(restarted, approved.task_id)
    assert after_replay.lifecycle is DiagnosticTaskLifecycle.CANCELED
    assert after_replay.task_handles == terminal_handles

    restarted.close()


def test_current_generation_campaign_run_batch_refreshes_its_diagnostic_task(
    tmp_path,
) -> None:
    (
        _source,
        _artifact_store,
        _engine,
        application,
        application_adapter,
        initial_feature,
    ) = _formal_live_stack(tmp_path)
    initial_feature.close()
    bridge = EventBridge(subscribe_backend=False)
    feature = LiveDiagnosticTasksAdapter(
        application=application_adapter,
        event_bridge=bridge,
    )
    approved = _approved_formal_task(feature)
    started = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-batch-command-62"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-batch-idempotency-62"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert started.accepted
    task_context = DiagnosticTasksContext(approved.task_id)
    before = _read_task(feature, approved.task_id)
    assert before.handoff.campaign_id is not None
    run_id = next(
        run.run_id.value
        for node in before.handoff.campaign_nodes
        for attempt in node.attempts
        for run in attempt.runs
    )
    observed = []
    subscription = feature.subscribe(task_context, observed.append)

    application.advance_diagnostic_campaign(
        before.handoff.campaign_id.value,
        max_cases=1,
    )
    delivered_before_unrelated = len(observed)
    bridge.on_snapshot({"run_id": "unrelated-run"}, generation=1)
    bridge.flush(force=True)

    assert len(observed) == delivered_before_unrelated

    bridge.on_snapshot({"run_id": run_id}, generation=1)
    bridge.flush(force=True)

    assert observed[-1].task is not None
    assert observed[-1].task.revision > before.revision
    subscription.dispose()
    feature.close()
