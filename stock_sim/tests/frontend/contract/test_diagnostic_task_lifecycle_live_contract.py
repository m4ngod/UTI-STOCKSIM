from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError

from app.features import (
    CampaignNodeTarget,
    CancelDiagnosticTarget,
    DeterministicFakeDiagnosticTasksAdapter,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    DiagnosticTaskCommandRejectionReason,
    DiagnosticTaskLifecycle,
    DiagnosticTasksCommandDisposition,
    DiagnosticTasksContext,
    DiagnosticTaskTarget,
    FormalDiagnosticCampaignTarget,
    LiveDiagnosticTasksAdapter,
    LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
    PauseDiagnosticTarget,
    ResumeDiagnosticTarget,
    StartFormalDiagnosticCampaign,
    TaskPhase,
)
from strategy_diagnostics import create_diagnostics_application
from tests.frontend.contract.test_diagnostic_task_campaign_start_live_contract import (
    _approved_formal_task,
    _formal_live_stack,
)
from tests.frontend.contract.test_diagnostic_task_revision_approval_live_contract import (
    _read_task,
)


@pytest.fixture(params=("live", "fake"))
def lifecycle_feature(request, tmp_path):
    (
        _source,
        _artifact_store,
        _engine,
        _application,
        _application_adapter,
        live_feature,
    ) = _formal_live_stack(tmp_path)
    if request.param == "live":
        feature = live_feature
    else:
        workspace = DiagnosticTasksContext.workspace()
        live_feature.snapshot(workspace)
        inventory = live_feature.snapshot(workspace).last_reliable_inventory
        assert inventory is not None
        live_feature.close()
        feature = DeterministicFakeDiagnosticTasksAdapter(
            inventory=inventory,
        )
    approved_task = _approved_formal_task(feature)
    accepted = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-idempotency-60"
            ),
            task_id=approved_task.task_id,
            expected_revision=approved_task.revision,
            approved_revision=approved_task.revision,
        )
    )
    assert accepted.accepted
    running = _read_task(feature, approved_task.task_id)
    assert running.lifecycle is DiagnosticTaskLifecycle.RUNNING
    yield feature, running
    feature.close()


def test_live_and_fake_share_task_pause_resume_cancel_lifecycle(
    lifecycle_feature,
) -> None:
    feature, running = lifecycle_feature
    assert running.capabilities.can_pause
    assert running.capabilities.can_cancel
    assert not running.capabilities.can_resume
    pause = PauseDiagnosticTarget(
        command_id=DiagnosticCommandId("pause-task-command-60"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            "pause-task-idempotency-60"
        ),
        target=DiagnosticTaskTarget(running.task_id),
        expected_revision=running.revision,
    )

    accepted_pause = feature.pause_diagnostic_target(pause)

    assert accepted_pause.disposition is (
        DiagnosticTasksCommandDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    assert accepted_pause.task_handle is not None
    assert accepted_pause.task_handle.phase is TaskPhase.QUEUED
    assert accepted_pause.current_revision == running.revision + 1
    paused = _read_task(feature, running.task_id)
    assert paused.lifecycle is DiagnosticTaskLifecycle.PAUSED
    assert paused.revision == running.revision + 1
    assert paused.capabilities.can_resume
    assert paused.capabilities.can_cancel
    assert not paused.capabilities.can_pause
    pause_handle = next(
        handle
        for handle in paused.task_handles
        if handle.identity == accepted_pause.task_handle.identity
    )
    assert pause_handle.phase is TaskPhase.COMPLETED
    assert pause_handle.result == "diagnostic_task_paused"

    replay = feature.pause_diagnostic_target(
        replace(
            pause,
            command_id=DiagnosticCommandId("pause-task-command-60-replay"),
        )
    )
    assert replay.disposition is (
        DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    )
    assert replay.task_handle is not None
    assert replay.task_handle.identity == pause_handle.identity
    stale = feature.resume_diagnostic_target(
        ResumeDiagnosticTarget(
            command_id=DiagnosticCommandId("resume-task-stale-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "resume-task-stale-idempotency-60"
            ),
            target=DiagnosticTaskTarget(running.task_id),
            expected_revision=running.revision,
        )
    )
    assert stale.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.STALE_EXPECTED_REVISION
    )
    assert stale.task_handle is None

    accepted_resume = feature.resume_diagnostic_target(
        ResumeDiagnosticTarget(
            command_id=DiagnosticCommandId("resume-task-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "resume-task-idempotency-60"
            ),
            target=DiagnosticTaskTarget(running.task_id),
            expected_revision=paused.revision,
        )
    )

    assert accepted_resume.accepted
    resumed = _read_task(feature, running.task_id)
    assert resumed.lifecycle is DiagnosticTaskLifecycle.RUNNING
    assert resumed.revision == paused.revision + 1
    assert resumed.capabilities.can_pause
    assert not resumed.capabilities.can_resume

    accepted_cancel = feature.cancel_diagnostic_target(
        CancelDiagnosticTarget(
            command_id=DiagnosticCommandId("cancel-task-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "cancel-task-idempotency-60"
            ),
            target=DiagnosticTaskTarget(running.task_id),
            expected_revision=resumed.revision,
        )
    )

    assert accepted_cancel.accepted
    canceled = _read_task(feature, running.task_id)
    assert canceled.lifecycle is DiagnosticTaskLifecycle.CANCELED
    assert canceled.revision == resumed.revision + 1
    assert not canceled.capabilities.can_pause
    assert not canceled.capabilities.can_resume
    assert not canceled.capabilities.can_cancel
    terminal_rejection = feature.pause_diagnostic_target(
        replace(
            pause,
            command_id=DiagnosticCommandId("pause-canceled-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "pause-canceled-idempotency-60"
            ),
            expected_revision=canceled.revision,
        )
    )
    assert terminal_rejection.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.INVALID_COMMAND
    )
    assert terminal_rejection.task_handle is None
    assert _read_task(feature, running.task_id) == canceled


def test_live_and_fake_share_campaign_pause_resume_cancel_lifecycle(
    lifecycle_feature,
) -> None:
    feature, running = lifecycle_feature
    campaign_id = running.handoff.campaign_id
    campaign_revision = running.handoff.campaign_revision
    assert campaign_id is not None
    assert campaign_revision is not None

    paused_result = feature.pause_diagnostic_target(
        PauseDiagnosticTarget(
            command_id=DiagnosticCommandId("pause-campaign-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "pause-campaign-idempotency-60"
            ),
            target=FormalDiagnosticCampaignTarget(campaign_id),
            expected_revision=campaign_revision,
        )
    )

    assert paused_result.accepted
    paused = _read_task(feature, running.task_id)
    assert paused.lifecycle is DiagnosticTaskLifecycle.PAUSED
    assert paused.handoff.campaign_lifecycle is DiagnosticTaskLifecycle.PAUSED
    assert paused.handoff.campaign_revision == campaign_revision + 1
    resumed_result = feature.resume_diagnostic_target(
        ResumeDiagnosticTarget(
            command_id=DiagnosticCommandId("resume-campaign-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "resume-campaign-idempotency-60"
            ),
            target=FormalDiagnosticCampaignTarget(campaign_id),
            expected_revision=paused.handoff.campaign_revision,
        )
    )
    assert resumed_result.accepted
    resumed = _read_task(feature, running.task_id)
    assert resumed.lifecycle is DiagnosticTaskLifecycle.RUNNING
    assert resumed.handoff.campaign_lifecycle is DiagnosticTaskLifecycle.RUNNING

    canceled_result = feature.cancel_diagnostic_target(
        CancelDiagnosticTarget(
            command_id=DiagnosticCommandId("cancel-campaign-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "cancel-campaign-idempotency-60"
            ),
            target=FormalDiagnosticCampaignTarget(campaign_id),
            expected_revision=resumed.handoff.campaign_revision,
        )
    )

    assert canceled_result.accepted
    canceled = _read_task(feature, running.task_id)
    assert canceled.lifecycle is DiagnosticTaskLifecycle.CANCELED
    assert (
        canceled.handoff.campaign_lifecycle
        is DiagnosticTaskLifecycle.CANCELED
    )
    assert all(
        node.lifecycle
        in {
            DiagnosticTaskLifecycle.CANCELED,
            DiagnosticTaskLifecycle.COMPLETED,
            DiagnosticTaskLifecycle.FAILED,
        }
        for node in canceled.handoff.campaign_nodes
    )


def test_live_and_fake_share_campaign_node_lifecycle_and_conflicts(
    lifecycle_feature,
) -> None:
    feature, running = lifecycle_feature
    campaign_revision = running.handoff.campaign_revision
    assert campaign_revision is not None
    node = next(
        item
        for item in running.handoff.campaign_nodes
        if item.lifecycle is DiagnosticTaskLifecycle.QUEUED
    )
    target = CampaignNodeTarget(node.campaign_node_id)
    pause = PauseDiagnosticTarget(
        command_id=DiagnosticCommandId("pause-node-command-60"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            "pause-node-idempotency-60"
        ),
        target=target,
        expected_revision=node.revision,
    )

    accepted = feature.pause_diagnostic_target(pause)

    assert accepted.accepted
    paused_task = _read_task(feature, running.task_id)
    paused_node = next(
        item
        for item in paused_task.handoff.campaign_nodes
        if item.campaign_node_id == node.campaign_node_id
    )
    assert paused_task.lifecycle is DiagnosticTaskLifecycle.RUNNING
    assert paused_task.revision == running.revision + 1
    assert paused_node.lifecycle is DiagnosticTaskLifecycle.PAUSED
    assert paused_node.revision == node.revision + 1
    command_conflict = feature.pause_diagnostic_target(
        replace(
            pause,
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "different-pause-node-idempotency-60"
            ),
        )
    )
    assert command_conflict.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.COMMAND_IDENTITY_CONFLICT
    )
    idempotency_conflict = feature.pause_diagnostic_target(
        replace(
            pause,
            command_id=DiagnosticCommandId("different-pause-node-command-60"),
            expected_revision=paused_node.revision,
        )
    )
    assert idempotency_conflict.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.IDEMPOTENCY_CONFLICT
    )

    resumed_result = feature.resume_diagnostic_target(
        ResumeDiagnosticTarget(
            command_id=DiagnosticCommandId("resume-node-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "resume-node-idempotency-60"
            ),
            target=target,
            expected_revision=paused_node.revision,
        )
    )
    assert resumed_result.accepted
    resumed_task = _read_task(feature, running.task_id)
    resumed_node = next(
        item
        for item in resumed_task.handoff.campaign_nodes
        if item.campaign_node_id == node.campaign_node_id
    )
    assert resumed_node.lifecycle is DiagnosticTaskLifecycle.RUNNING

    canceled_result = feature.cancel_diagnostic_target(
        CancelDiagnosticTarget(
            command_id=DiagnosticCommandId("cancel-node-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "cancel-node-idempotency-60"
            ),
            target=target,
            expected_revision=resumed_node.revision,
        )
    )
    assert canceled_result.accepted
    canceled_task = _read_task(feature, running.task_id)
    canceled_node = next(
        item
        for item in canceled_task.handoff.campaign_nodes
        if item.campaign_node_id == node.campaign_node_id
    )
    assert canceled_task.lifecycle is DiagnosticTaskLifecycle.RUNNING
    assert canceled_node.lifecycle is DiagnosticTaskLifecycle.CANCELED
    terminal = feature.resume_diagnostic_target(
        ResumeDiagnosticTarget(
            command_id=DiagnosticCommandId(
                "resume-canceled-node-command-60"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "resume-canceled-node-idempotency-60"
            ),
            target=target,
            expected_revision=canceled_node.revision,
        )
    )
    assert terminal.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.INVALID_COMMAND
    )
    assert _read_task(feature, running.task_id) == canceled_task
    assert (
        canceled_task.handoff.campaign_revision
        == campaign_revision + 3
    )

    parent_pause = feature.pause_diagnostic_target(
        PauseDiagnosticTarget(
            command_id=DiagnosticCommandId(
                "pause-task-after-node-command-60"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "pause-task-after-node-idempotency-60"
            ),
            target=DiagnosticTaskTarget(running.task_id),
            expected_revision=canceled_task.revision,
        )
    )

    assert parent_pause.accepted


def test_live_lifecycle_survives_reopen_and_gates_real_campaign_execution(
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
    approved = _approved_formal_task(feature)
    started = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-reopen-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-reopen-idempotency-60"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert started.accepted
    running = _read_task(feature, approved.task_id)
    campaign_id = running.handoff.campaign_id
    assert campaign_id is not None
    paused_result = feature.pause_diagnostic_target(
        PauseDiagnosticTarget(
            command_id=DiagnosticCommandId("pause-reopen-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "pause-reopen-idempotency-60"
            ),
            target=DiagnosticTaskTarget(running.task_id),
            expected_revision=running.revision,
        )
    )
    assert paused_result.task_handle is not None
    with pytest.raises(ValueError, match="not running"):
        application.advance_diagnostic_campaign(campaign_id.value)
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
    paused = _read_task(reopened_feature, approved.task_id)
    assert paused.lifecycle is DiagnosticTaskLifecycle.PAUSED
    persisted_handle = next(
        item
        for item in paused.task_handles
        if item.identity == paused_result.task_handle.identity
    )
    assert persisted_handle.phase is TaskPhase.COMPLETED
    assert persisted_handle.result == "diagnostic_task_paused"
    resumed = reopened_feature.resume_diagnostic_target(
        ResumeDiagnosticTarget(
            command_id=DiagnosticCommandId("resume-reopen-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "resume-reopen-idempotency-60"
            ),
            target=DiagnosticTaskTarget(paused.task_id),
            expected_revision=paused.revision,
        )
    )
    assert resumed.accepted
    assert (
        reopened.diagnostic_campaign_status(campaign_id.value).campaign_id
        == campaign_id.value
    )
    reopened_feature.close()


def test_application_reopen_completes_durably_accepted_lifecycle_command(
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
    started = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-recover-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-recover-idempotency-60"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert started.accepted
    running = _read_task(feature, approved.task_id)
    failure = {"armed": True}

    def fail_first_lifecycle_completion(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        normalized = " ".join(statement.split())
        if (
            failure["armed"]
            and normalized.startswith(
                "UPDATE diagnostic_task_handles SET phase ="
            )
            and "result_code" in normalized
        ):
            failure["armed"] = False
            raise SQLAlchemyError("synthetic lifecycle completion interruption")

    event.listen(engine, "before_cursor_execute", fail_first_lifecycle_completion)
    try:
        accepted = feature.pause_diagnostic_target(
            PauseDiagnosticTarget(
                command_id=DiagnosticCommandId(
                    "pause-recover-command-60"
                ),
                idempotency_key=DiagnosticCommandIdempotencyKey(
                    "pause-recover-idempotency-60"
                ),
                target=DiagnosticTaskTarget(running.task_id),
                expected_revision=running.revision,
            )
        )
    finally:
        event.remove(
            engine,
            "before_cursor_execute",
            fail_first_lifecycle_completion,
        )
    assert accepted.accepted
    assert accepted.task_handle is not None
    interrupted = _read_task(feature, running.task_id)
    interrupted_handle = next(
        item
        for item in interrupted.task_handles
        if item.identity == accepted.task_handle.identity
    )
    assert interrupted.lifecycle is DiagnosticTaskLifecycle.PAUSED
    assert interrupted_handle.phase is TaskPhase.QUEUED
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
    recovered = _read_task(reopened_feature, running.task_id)
    recovered_handle = next(
        item
        for item in recovered.task_handles
        if item.identity == accepted.task_handle.identity
    )
    assert recovered.lifecycle is DiagnosticTaskLifecycle.PAUSED
    assert recovered_handle.phase is TaskPhase.COMPLETED
    assert recovered_handle.result == "diagnostic_task_paused"
    reopened_feature.close()


def test_later_terminal_command_supersedes_older_queued_lifecycle_handle(
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
    started = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-supersede-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-supersede-idempotency-60"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert started.accepted
    running = _read_task(feature, approved.task_id)
    failure = {"armed": True}

    def fail_first_lifecycle_completion(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        normalized = " ".join(statement.split())
        if (
            failure["armed"]
            and normalized.startswith(
                "UPDATE diagnostic_task_handles SET phase ="
            )
            and "result_code" in normalized
        ):
            failure["armed"] = False
            raise SQLAlchemyError("synthetic superseded completion interruption")

    event.listen(engine, "before_cursor_execute", fail_first_lifecycle_completion)
    try:
        pause = feature.pause_diagnostic_target(
            PauseDiagnosticTarget(
                command_id=DiagnosticCommandId(
                    "pause-superseded-command-60"
                ),
                idempotency_key=DiagnosticCommandIdempotencyKey(
                    "pause-superseded-idempotency-60"
                ),
                target=DiagnosticTaskTarget(running.task_id),
                expected_revision=running.revision,
            )
        )
    finally:
        event.remove(
            engine,
            "before_cursor_execute",
            fail_first_lifecycle_completion,
        )
    assert pause.accepted
    assert pause.task_handle is not None
    paused = _read_task(feature, running.task_id)
    pause_handle = next(
        item
        for item in paused.task_handles
        if item.identity == pause.task_handle.identity
    )
    assert pause_handle.phase is TaskPhase.QUEUED

    cancel = feature.cancel_diagnostic_target(
        CancelDiagnosticTarget(
            command_id=DiagnosticCommandId("cancel-supersede-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "cancel-supersede-idempotency-60"
            ),
            target=DiagnosticTaskTarget(running.task_id),
            expected_revision=paused.revision,
        )
    )

    assert cancel.accepted
    canceled = _read_task(feature, running.task_id)
    superseded = next(
        item
        for item in canceled.task_handles
        if item.identity == pause.task_handle.identity
    )
    assert superseded.phase is TaskPhase.COMPLETED
    assert superseded.result == "diagnostic_task_pause_superseded"
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
    recovered = _read_task(reopened_feature, running.task_id)
    recovered_superseded = next(
        item
        for item in recovered.task_handles
        if item.identity == pause.task_handle.identity
    )
    assert recovered.lifecycle is DiagnosticTaskLifecycle.CANCELED
    assert recovered_superseded.phase is TaskPhase.COMPLETED
    assert recovered_superseded.result == "diagnostic_task_pause_superseded"
    reopened_feature.close()


def test_live_paused_node_blocks_ordered_runner_until_resume(
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
    approved = _approved_formal_task(feature)
    started = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-paused-node-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-paused-node-idempotency-60"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert started.accepted
    running = _read_task(feature, approved.task_id)
    campaign_id = running.handoff.campaign_id
    assert campaign_id is not None
    node = next(
        item
        for item in running.handoff.campaign_nodes
        if item.lifecycle is DiagnosticTaskLifecycle.QUEUED
    )
    paused = feature.pause_diagnostic_target(
        PauseDiagnosticTarget(
            command_id=DiagnosticCommandId("pause-runner-node-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "pause-runner-node-idempotency-60"
            ),
            target=CampaignNodeTarget(node.campaign_node_id),
            expected_revision=node.revision,
        )
    )
    assert paused.accepted

    blocked = application.advance_diagnostic_campaign(
        campaign_id.value,
        max_cases=1,
    )

    blocked_case = next(
        item
        for item in blocked.cases
        if item.case_id == node.campaign_case_id.value
    )
    assert not blocked_case.attempts
    paused_task = _read_task(feature, approved.task_id)
    paused_node = next(
        item
        for item in paused_task.handoff.campaign_nodes
        if item.campaign_node_id == node.campaign_node_id
    )
    assert paused_node.lifecycle is DiagnosticTaskLifecycle.PAUSED
    assert not paused_node.attempts

    resumed = feature.resume_diagnostic_target(
        ResumeDiagnosticTarget(
            command_id=DiagnosticCommandId("resume-runner-node-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "resume-runner-node-idempotency-60"
            ),
            target=CampaignNodeTarget(node.campaign_node_id),
            expected_revision=paused_node.revision,
        )
    )
    assert resumed.accepted
    advanced = application.advance_diagnostic_campaign(
        campaign_id.value,
        max_cases=1,
    )
    advanced_case = next(
        item
        for item in advanced.cases
        if item.case_id == node.campaign_case_id.value
    )
    assert len(advanced_case.attempts) == 1
    refreshed = _read_task(feature, approved.task_id)
    refreshed_node = next(
        item
        for item in refreshed.handoff.campaign_nodes
        if item.campaign_node_id == node.campaign_node_id
    )
    assert refreshed_node.lifecycle in {
        DiagnosticTaskLifecycle.COMPLETED,
        DiagnosticTaskLifecycle.FAILED,
    }
    assert len(refreshed_node.attempts) == 1
    feature.close()


def test_live_canceled_node_never_reaches_ordered_runner(tmp_path) -> None:
    (
        _source,
        _artifact_store,
        _engine,
        application,
        _application_adapter,
        feature,
    ) = _formal_live_stack(tmp_path)
    approved = _approved_formal_task(feature)
    started = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-canceled-node-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-canceled-node-idempotency-60"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert started.accepted
    running = _read_task(feature, approved.task_id)
    campaign_id = running.handoff.campaign_id
    assert campaign_id is not None
    node = next(
        item
        for item in running.handoff.campaign_nodes
        if item.lifecycle is DiagnosticTaskLifecycle.QUEUED
    )
    canceled = feature.cancel_diagnostic_target(
        CancelDiagnosticTarget(
            command_id=DiagnosticCommandId("cancel-runner-node-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "cancel-runner-node-idempotency-60"
            ),
            target=CampaignNodeTarget(node.campaign_node_id),
            expected_revision=node.revision,
        )
    )
    assert canceled.accepted

    blocked = application.advance_diagnostic_campaign(
        campaign_id.value,
        max_cases=1,
    )

    blocked_case = next(
        item
        for item in blocked.cases
        if item.case_id == node.campaign_case_id.value
    )
    assert not blocked_case.attempts
    refreshed = _read_task(feature, approved.task_id)
    refreshed_node = next(
        item
        for item in refreshed.handoff.campaign_nodes
        if item.campaign_node_id == node.campaign_node_id
    )
    assert refreshed_node.lifecycle is DiagnosticTaskLifecycle.CANCELED
    assert not refreshed_node.attempts
    feature.close()


def test_live_completed_campaign_syncs_terminal_diagnostic_lifecycle(
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
    approved = _approved_formal_task(feature)
    started = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-terminal-sync-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-terminal-sync-idempotency-60"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert started.accepted
    running = _read_task(feature, approved.task_id)
    campaign_id = running.handoff.campaign_id
    assert campaign_id is not None

    completed = application.resume_diagnostic_campaign(campaign_id.value)

    assert completed.status == "completed"
    refreshed = _read_task(feature, approved.task_id)
    assert refreshed.lifecycle is DiagnosticTaskLifecycle.COMPLETED
    assert (
        refreshed.handoff.campaign_lifecycle
        is DiagnosticTaskLifecycle.COMPLETED
    )
    assert all(
        node.lifecycle is DiagnosticTaskLifecycle.COMPLETED
        for node in refreshed.handoff.campaign_nodes
    )
    assert not refreshed.capabilities.can_pause
    assert not refreshed.capabilities.can_resume
    assert not refreshed.capabilities.can_cancel
    feature.close()


def test_live_campaign_progress_sync_recovers_after_persistence_interruption(
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
    approved = _approved_formal_task(feature)
    started = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-sync-recovery-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-sync-recovery-idempotency-60"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert started.accepted
    running = _read_task(feature, approved.task_id)
    campaign_id = running.handoff.campaign_id
    assert campaign_id is not None
    failure = {"armed": True}

    def fail_first_campaign_handoff_sync(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        normalized = " ".join(statement.split())
        if (
            failure["armed"]
            and normalized.startswith(
                "UPDATE diagnostic_task_campaign_handoffs"
            )
            and "SET handoff_json =" in normalized
        ):
            failure["armed"] = False
            raise SQLAlchemyError("synthetic Campaign progress sync interruption")

    event.listen(engine, "before_cursor_execute", fail_first_campaign_handoff_sync)
    try:
        with pytest.raises(
            SQLAlchemyError,
            match="synthetic Campaign progress sync interruption",
        ):
            application.resume_diagnostic_campaign(campaign_id.value)
    finally:
        event.remove(
            engine,
            "before_cursor_execute",
            fail_first_campaign_handoff_sync,
        )
    interrupted = _read_task(feature, approved.task_id)
    assert interrupted.lifecycle is DiagnosticTaskLifecycle.RUNNING

    recovered_campaign = application.resume_diagnostic_campaign(
        campaign_id.value
    )

    assert recovered_campaign.status == "completed"
    recovered = _read_task(feature, approved.task_id)
    assert recovered.lifecycle is DiagnosticTaskLifecycle.COMPLETED
    assert all(
        node.lifecycle is DiagnosticTaskLifecycle.COMPLETED
        for node in recovered.handoff.campaign_nodes
    )
    feature.close()


def test_later_campaign_pause_wins_runner_save_to_sidecar_sync_race(
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
    approved = _approved_formal_task(feature)
    started = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-pause-race-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-pause-race-idempotency-60"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert started.accepted
    running = _read_task(feature, approved.task_id)
    campaign_id = running.handoff.campaign_id
    assert campaign_id is not None
    next_node = next(
        node
        for node in running.handoff.campaign_nodes
        if node.lifecycle is DiagnosticTaskLifecycle.QUEUED
    )
    real_sync = application._sync_linked_diagnostic_campaign
    pause_result = None

    def pause_after_runner_save(campaign) -> None:
        nonlocal pause_result
        current = _read_task(feature, approved.task_id)
        assert current.handoff.campaign_revision is not None
        pause_result = feature.pause_diagnostic_target(
            PauseDiagnosticTarget(
                command_id=DiagnosticCommandId(
                    "pause-campaign-race-command-60"
                ),
                idempotency_key=DiagnosticCommandIdempotencyKey(
                    "pause-campaign-race-idempotency-60"
                ),
                target=FormalDiagnosticCampaignTarget(campaign_id),
                expected_revision=current.handoff.campaign_revision,
            )
        )
        assert pause_result.accepted
        real_sync(campaign)

    monkeypatch.setattr(
        application,
        "_sync_linked_diagnostic_campaign",
        pause_after_runner_save,
    )

    application.advance_diagnostic_campaign(campaign_id.value, max_cases=1)

    assert pause_result is not None
    assert pause_result.task_handle is not None
    paused = _read_task(feature, approved.task_id)
    persisted_pause_handle = next(
        handle
        for handle in paused.task_handles
        if handle.identity == pause_result.task_handle.identity
    )
    executed_node = next(
        node
        for node in paused.handoff.campaign_nodes
        if node.campaign_node_id == next_node.campaign_node_id
    )
    assert paused.lifecycle is DiagnosticTaskLifecycle.PAUSED
    assert (
        paused.handoff.campaign_lifecycle
        is DiagnosticTaskLifecycle.PAUSED
    )
    assert persisted_pause_handle.phase is TaskPhase.COMPLETED
    assert (
        persisted_pause_handle.result
        == "formal_diagnostic_campaign_paused"
    )
    assert len(executed_node.attempts) == 1
    with pytest.raises(
        ValueError,
        match="Linked Formal Diagnostic Campaign is not running",
    ):
        application.advance_diagnostic_campaign(
            campaign_id.value,
            max_cases=1,
        )
    feature.close()


def test_final_batch_pause_then_resume_reconciles_completed_campaign(
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
    approved = _approved_formal_task(feature)
    started = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId(
                "start-final-pause-race-command-60"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-final-pause-race-idempotency-60"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert started.accepted
    running = _read_task(feature, approved.task_id)
    campaign_id = running.handoff.campaign_id
    assert campaign_id is not None
    real_sync = application._sync_linked_diagnostic_campaign
    pause_result = None

    def pause_after_final_runner_save(campaign) -> None:
        nonlocal pause_result
        assert campaign.status == "completed"
        current = _read_task(feature, approved.task_id)
        assert current.handoff.campaign_revision is not None
        pause_result = feature.pause_diagnostic_target(
            PauseDiagnosticTarget(
                command_id=DiagnosticCommandId(
                    "pause-final-campaign-race-command-60"
                ),
                idempotency_key=DiagnosticCommandIdempotencyKey(
                    "pause-final-campaign-race-idempotency-60"
                ),
                target=FormalDiagnosticCampaignTarget(campaign_id),
                expected_revision=current.handoff.campaign_revision,
            )
        )
        assert pause_result.accepted
        real_sync(campaign)

    monkeypatch.setattr(
        application,
        "_sync_linked_diagnostic_campaign",
        pause_after_final_runner_save,
    )
    completed_campaign = application.resume_diagnostic_campaign(
        campaign_id.value
    )
    assert completed_campaign.status == "completed"
    paused = _read_task(feature, approved.task_id)
    assert paused.lifecycle is DiagnosticTaskLifecycle.PAUSED
    assert all(
        node.lifecycle
        in {
            DiagnosticTaskLifecycle.COMPLETED,
            DiagnosticTaskLifecycle.FAILED,
        }
        for node in paused.handoff.campaign_nodes
    )
    assert paused.handoff.evidence_package_id is None
    assert paused.handoff.reproduction_manifest_id is None
    monkeypatch.setattr(
        application,
        "_sync_linked_diagnostic_campaign",
        real_sync,
    )
    resumed = feature.resume_diagnostic_target(
        ResumeDiagnosticTarget(
            command_id=DiagnosticCommandId(
                "resume-final-campaign-race-command-60"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "resume-final-campaign-race-idempotency-60"
            ),
            target=FormalDiagnosticCampaignTarget(campaign_id),
            expected_revision=paused.handoff.campaign_revision,
        )
    )
    assert resumed.accepted

    reconciled_campaign = application.resume_diagnostic_campaign(
        campaign_id.value
    )

    assert reconciled_campaign.status == "completed"
    reconciled = _read_task(feature, approved.task_id)
    assert reconciled.lifecycle is DiagnosticTaskLifecycle.COMPLETED
    assert (
        reconciled.handoff.campaign_lifecycle
        is DiagnosticTaskLifecycle.COMPLETED
    )
    assert reconciled.handoff.ready_for_evidence_and_findings
    assert not reconciled.capabilities.can_pause
    assert not reconciled.capabilities.can_resume
    assert not reconciled.capabilities.can_cancel
    feature.close()


def test_live_cancel_target_cannot_reach_order_cancellation(tmp_path) -> None:
    (
        _source,
        _artifact_store,
        engine,
        _application,
        _application_adapter,
        feature,
    ) = _formal_live_stack(tmp_path)
    approved = _approved_formal_task(feature)
    started = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-isolation-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-isolation-idempotency-60"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert started.accepted
    running = _read_task(feature, approved.task_id)
    with engine.connect() as connection:
        orders_before = connection.execute(
            text(
                "SELECT order_id, status, accepted_shares, reason_code "
                "FROM diagnostic_run_orders ORDER BY order_id"
            )
        ).all()

    canceled = feature.cancel_diagnostic_target(
        CancelDiagnosticTarget(
            command_id=DiagnosticCommandId("cancel-isolation-command-60"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "cancel-isolation-idempotency-60"
            ),
            target=DiagnosticTaskTarget(running.task_id),
            expected_revision=running.revision,
        )
    )

    assert canceled.accepted
    with engine.connect() as connection:
        orders_after = connection.execute(
            text(
                "SELECT order_id, status, accepted_shares, reason_code "
                "FROM diagnostic_run_orders ORDER BY order_id"
            )
        ).all()
        command = connection.execute(
            text(
                "SELECT command_type, command_json "
                "FROM diagnostic_task_mutation_commands "
                "WHERE command_id = 'cancel-isolation-command-60'"
            )
        ).one()
    assert orders_after == orders_before
    assert command[0] == "cancel_diagnostic_target"
    assert "order" not in str(command[1]).casefold()
    feature.close()
