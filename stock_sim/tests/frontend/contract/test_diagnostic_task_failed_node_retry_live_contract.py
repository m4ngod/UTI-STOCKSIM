from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from app.features import (
    CampaignNodeId,
    DeterministicFakeDiagnosticTasksAdapter,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    DiagnosticTaskCommandRejectionReason,
    DiagnosticTaskLifecycle,
    DiagnosticTasksCommandDisposition,
    DiagnosticTasksContext,
    FormalDiagnosticCampaignTarget,
    LiveDiagnosticTasksAdapter,
    LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter,
    PauseDiagnosticTarget,
    RetryFailedCampaignNode,
    StartFormalDiagnosticCampaign,
    TaskPhase,
)
from strategy_diagnostics import (
    PTRADE_SUBPROCESS_HOST_VERSION,
    InProcessPTradeStrategyHost,
    PTradeHostInvocation,
    PTradeHostResult,
    create_diagnostics_application,
)
from tests.frontend.contract.test_diagnostic_task_campaign_start_live_contract import (
    _approved_formal_task,
    _formal_live_stack,
)
from tests.frontend.contract.test_diagnostic_task_revision_approval_live_contract import (
    _read_task,
)


class _FailFirstDecisionPTradeHost:
    adapter_version = PTRADE_SUBPROCESS_HOST_VERSION

    def __init__(self) -> None:
        self._delegate = InProcessPTradeStrategyHost()
        self._failed = False

    def invoke(self, invocation: PTradeHostInvocation) -> PTradeHostResult:
        if invocation.event == "decision" and not self._failed:
            self._failed = True
            raise RuntimeError("deterministic first-attempt strategy failure")
        return replace(
            self._delegate.invoke(invocation),
            host_adapter_version=PTRADE_SUBPROCESS_HOST_VERSION,
        )


class _AlwaysFailDecisionPTradeHost:
    adapter_version = PTRADE_SUBPROCESS_HOST_VERSION

    def __init__(self) -> None:
        self._delegate = InProcessPTradeStrategyHost()

    def invoke(self, invocation: PTradeHostInvocation) -> PTradeHostResult:
        if invocation.event == "decision":
            raise RuntimeError("deterministic repeated strategy failure")
        return replace(
            self._delegate.invoke(invocation),
            host_adapter_version=PTRADE_SUBPROCESS_HOST_VERSION,
        )


@pytest.fixture(params=("live", "fake"))
def failed_node_feature(request, tmp_path):
    if request.param == "live":
        *_, feature = _formal_live_stack(
            tmp_path,
            ptrade_host=_FailFirstDecisionPTradeHost(),
        )
        yield feature
        feature.close()
        return
    *_, live_feature = _formal_live_stack(tmp_path)
    workspace = DiagnosticTasksContext.workspace()
    live_feature.snapshot(workspace)
    inventory = live_feature.snapshot(workspace).last_reliable_inventory
    assert inventory is not None
    live_feature.close()
    fake_feature = DeterministicFakeDiagnosticTasksAdapter(
        inventory=inventory,
        fail_first_campaign_node=True,
    )
    yield fake_feature
    fake_feature.close()


def test_live_and_fake_share_failed_node_retry_conformance(
    failed_node_feature,
) -> None:
    feature = failed_node_feature
    approved = _approved_formal_task(feature)
    feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-conformance-command-61"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-conformance-idempotency-61"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    failed_task = _read_task(feature, approved.task_id)
    failed_node = next(
        node
        for node in failed_task.handoff.campaign_nodes
        if node.lifecycle is DiagnosticTaskLifecycle.FAILED
    )
    failed_attempt = failed_node.attempts[-1]
    assert failed_task.capabilities.can_retry_failed_node
    command = RetryFailedCampaignNode(
        command_id=DiagnosticCommandId("retry-conformance-command-61"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            "retry-conformance-idempotency-61"
        ),
        task_id=approved.task_id,
        campaign_node_id=failed_node.campaign_node_id,
        failed_attempt_id=failed_attempt.attempt_id,
        expected_revision=failed_node.revision,
    )

    accepted = feature.retry_failed_campaign_node(command)
    replay = feature.retry_failed_campaign_node(
        replace(
            command,
            command_id=DiagnosticCommandId(
                "retry-conformance-lost-response-61"
            ),
        )
    )

    assert accepted.disposition is (
        DiagnosticTasksCommandDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    assert accepted.task_handle is not None
    assert accepted.task_handle.phase is TaskPhase.QUEUED
    assert accepted.affected_campaign_attempt_id is not None
    assert replay.disposition is DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    assert replay.task_handle is not None
    assert replay.task_handle.identity == accepted.task_handle.identity
    assert (
        replay.affected_campaign_attempt_id
        == accepted.affected_campaign_attempt_id
    )
    completed = _read_task(feature, approved.task_id)
    completed_node = next(
        node
        for node in completed.handoff.campaign_nodes
        if node.campaign_node_id == failed_node.campaign_node_id
    )
    assert completed_node.attempts[0] == failed_attempt
    assert len(completed_node.attempts) == 2
    retry_attempt = completed_node.attempts[1]
    assert retry_attempt.attempt_number == 2
    assert retry_attempt.predecessor_attempt_id == failed_attempt.attempt_id
    assert retry_attempt.task_handle_id == accepted.task_handle.identity
    assert retry_attempt.lifecycle is DiagnosticTaskLifecycle.COMPLETED
    assert completed_node.active_attempt_id == retry_attempt.attempt_id
    assert not completed.capabilities.can_retry_failed_node
    terminal_handle = next(
        handle
        for handle in completed.task_handles
        if handle.identity == accepted.task_handle.identity
    )
    assert terminal_handle.phase is TaskPhase.COMPLETED
    stale = feature.retry_failed_campaign_node(
        replace(
            command,
            command_id=DiagnosticCommandId("retry-conformance-stale-61"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "retry-conformance-stale-key-61"
            ),
        )
    )
    assert stale.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.STALE_EXPECTED_REVISION
    )
    non_failed = feature.retry_failed_campaign_node(
        replace(
            command,
            command_id=DiagnosticCommandId("retry-conformance-nonfailed-61"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "retry-conformance-nonfailed-key-61"
            ),
            failed_attempt_id=retry_attempt.attempt_id,
            expected_revision=completed_node.revision,
        )
    )
    assert non_failed.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.UNAVAILABLE_INPUT
    )
    assert _read_task(feature, approved.task_id).handoff == completed.handoff


def test_live_and_fake_disable_retry_while_parent_campaign_is_paused(
    failed_node_feature,
) -> None:
    feature = failed_node_feature
    approved = _approved_formal_task(feature)
    feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-paused-parent-command-61"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-paused-parent-idempotency-61"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    failed_task = _read_task(feature, approved.task_id)
    failed_node = next(
        node
        for node in failed_task.handoff.campaign_nodes
        if node.lifecycle is DiagnosticTaskLifecycle.FAILED
    )
    failed_attempt = failed_node.attempts[-1]
    assert failed_task.handoff.campaign_id is not None
    assert failed_task.handoff.campaign_revision is not None
    paused = feature.pause_diagnostic_target(
        PauseDiagnosticTarget(
            command_id=DiagnosticCommandId("pause-parent-command-61"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "pause-parent-idempotency-61"
            ),
            target=FormalDiagnosticCampaignTarget(
                failed_task.handoff.campaign_id
            ),
            expected_revision=failed_task.handoff.campaign_revision,
        )
    )
    assert paused.accepted
    paused_task = _read_task(feature, approved.task_id)
    assert paused_task.lifecycle is DiagnosticTaskLifecycle.PAUSED
    assert (
        paused_task.handoff.campaign_lifecycle
        is DiagnosticTaskLifecycle.PAUSED
    )
    assert not paused_task.capabilities.can_retry_failed_node

    rejected = feature.retry_failed_campaign_node(
        RetryFailedCampaignNode(
            command_id=DiagnosticCommandId(
                "retry-paused-parent-command-61"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "retry-paused-parent-idempotency-61"
            ),
            task_id=approved.task_id,
            campaign_node_id=failed_node.campaign_node_id,
            failed_attempt_id=failed_attempt.attempt_id,
            expected_revision=failed_node.revision,
        )
    )

    assert rejected.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.UNAVAILABLE_INPUT
    )
    assert _read_task(feature, approved.task_id) == paused_task


def test_live_failed_node_retry_is_durably_accepted(tmp_path) -> None:
    (
        _source,
        _artifact_store,
        _engine,
        _application,
        _application_adapter,
        feature,
    ) = _formal_live_stack(
        tmp_path,
        ptrade_host=_FailFirstDecisionPTradeHost(),
    )
    approved = _approved_formal_task(feature)
    started = feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-failed-node-command-61"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-failed-node-idempotency-61"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert started.accepted
    failed_task = _read_task(feature, approved.task_id)
    failed_node = next(
        node
        for node in failed_task.handoff.campaign_nodes
        if node.lifecycle is DiagnosticTaskLifecycle.FAILED
    )
    assert len(failed_node.attempts) == 1
    failed_attempt = failed_node.attempts[0]
    assert failed_attempt.attempt_number == 1
    assert failed_attempt.predecessor_attempt_id is None
    assert failed_attempt.lifecycle is DiagnosticTaskLifecycle.FAILED
    assert failed_attempt.failure is not None
    assert failed_attempt.failure.code
    assert failed_attempt.failure.message
    failed_attempt_id = failed_node.active_attempt_id
    assert failed_attempt_id is not None
    retry_command = RetryFailedCampaignNode(
        command_id=DiagnosticCommandId("retry-failed-node-command-61"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            "retry-failed-node-idempotency-61"
        ),
        task_id=approved.task_id,
        campaign_node_id=failed_node.campaign_node_id,
        failed_attempt_id=failed_attempt_id,
        expected_revision=failed_node.revision,
    )
    wrong_target = feature.retry_failed_campaign_node(
        replace(
            retry_command,
            command_id=DiagnosticCommandId(
                "retry-failed-node-command-61-wrong-target"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "retry-failed-node-idempotency-61-wrong-target"
            ),
            campaign_node_id=CampaignNodeId("not-this-campaign-node"),
        )
    )
    assert wrong_target.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.INVALID_COMMAND
    )
    assert _read_task(feature, approved.task_id).handoff == failed_task.handoff

    retry = feature.retry_failed_campaign_node(retry_command)

    assert retry.disposition is (
        DiagnosticTasksCommandDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    assert retry.task_handle is not None
    assert retry.task_handle.phase is TaskPhase.QUEUED
    assert retry.affected_task_id == approved.task_id
    assert retry.affected_campaign_id == failed_task.handoff.campaign_id
    assert retry.affected_campaign_node_id == failed_node.campaign_node_id
    assert retry.affected_campaign_attempt_id is not None

    retried_task = _read_task(feature, approved.task_id)
    retried_node = next(
        node
        for node in retried_task.handoff.campaign_nodes
        if node.campaign_node_id == failed_node.campaign_node_id
    )
    assert len(retried_node.attempts) == 2
    assert retried_node.attempts[0] == failed_attempt
    new_attempt = retried_node.attempts[1]
    assert new_attempt.attempt_id == retry.affected_campaign_attempt_id
    assert new_attempt.attempt_number == 2
    assert new_attempt.predecessor_attempt_id == failed_attempt.attempt_id
    assert new_attempt.task_handle_id == retry.task_handle.identity
    assert new_attempt.lifecycle is DiagnosticTaskLifecycle.COMPLETED
    assert new_attempt.failure is None
    assert retried_node.active_attempt_id == new_attempt.attempt_id
    assert retried_node.lifecycle is DiagnosticTaskLifecycle.COMPLETED
    persisted_handle = next(
        handle
        for handle in retried_task.task_handles
        if handle.identity == retry.task_handle.identity
    )
    assert persisted_handle.phase is TaskPhase.COMPLETED
    assert persisted_handle.result == "failed_campaign_node_retry_completed"

    replay = feature.retry_failed_campaign_node(
        RetryFailedCampaignNode(
            command_id=DiagnosticCommandId(
                "retry-failed-node-command-61-lost-response"
            ),
            idempotency_key=retry_command.idempotency_key,
            task_id=retry_command.task_id,
            campaign_node_id=retry_command.campaign_node_id,
            failed_attempt_id=retry_command.failed_attempt_id,
            expected_revision=retry_command.expected_revision,
        )
    )
    assert replay.disposition is DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    assert replay.task_handle is not None
    assert replay.task_handle.identity == retry.task_handle.identity
    assert replay.affected_campaign_attempt_id == new_attempt.attempt_id

    command_conflict = feature.retry_failed_campaign_node(
        RetryFailedCampaignNode(
            command_id=retry_command.command_id,
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "retry-failed-node-idempotency-61-command-conflict"
            ),
            task_id=retry_command.task_id,
            campaign_node_id=retry_command.campaign_node_id,
            failed_attempt_id=retry_command.failed_attempt_id,
            expected_revision=retry_command.expected_revision,
        )
    )
    assert command_conflict.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.COMMAND_IDENTITY_CONFLICT
    )
    idempotency_conflict = feature.retry_failed_campaign_node(
        RetryFailedCampaignNode(
            command_id=DiagnosticCommandId(
                "retry-failed-node-command-61-content-conflict"
            ),
            idempotency_key=retry_command.idempotency_key,
            task_id=retry_command.task_id,
            campaign_node_id=retry_command.campaign_node_id,
            failed_attempt_id=retry_command.failed_attempt_id,
            expected_revision=retry_command.expected_revision + 1,
        )
    )
    assert idempotency_conflict.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.IDEMPOTENCY_CONFLICT
    )
    stale = feature.retry_failed_campaign_node(
        RetryFailedCampaignNode(
            command_id=DiagnosticCommandId(
                "retry-failed-node-command-61-stale"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "retry-failed-node-idempotency-61-stale"
            ),
            task_id=retry_command.task_id,
            campaign_node_id=retry_command.campaign_node_id,
            failed_attempt_id=retry_command.failed_attempt_id,
            expected_revision=retry_command.expected_revision,
        )
    )
    assert stale.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.STALE_EXPECTED_REVISION
    )
    assert _read_task(feature, approved.task_id).handoff == retried_task.handoff


def test_live_failed_node_retry_failure_creates_a_new_failed_attempt(
    tmp_path,
) -> None:
    host = _AlwaysFailDecisionPTradeHost()
    (
        source,
        artifact_store,
        engine,
        _application,
        _application_adapter,
        feature,
    ) = _formal_live_stack(
        tmp_path,
        ptrade_host=host,
    )
    approved = _approved_formal_task(feature)
    feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-repeat-failure-command-61"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-repeat-failure-idempotency-61"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    first_failure = _read_task(feature, approved.task_id)
    first_node = next(
        node
        for node in first_failure.handoff.campaign_nodes
        if node.lifecycle is DiagnosticTaskLifecycle.FAILED
    )
    first_attempt = first_node.attempts[-1]

    accepted = feature.retry_failed_campaign_node(
        RetryFailedCampaignNode(
            command_id=DiagnosticCommandId("retry-repeat-failure-command-61"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "retry-repeat-failure-idempotency-61"
            ),
            task_id=approved.task_id,
            campaign_node_id=first_node.campaign_node_id,
            failed_attempt_id=first_attempt.attempt_id,
            expected_revision=first_node.revision,
        )
    )

    assert accepted.accepted
    assert accepted.task_handle is not None
    repeated_failure = _read_task(feature, approved.task_id)
    repeated_node = next(
        node
        for node in repeated_failure.handoff.campaign_nodes
        if node.campaign_node_id == first_node.campaign_node_id
    )
    assert repeated_node.lifecycle is DiagnosticTaskLifecycle.FAILED
    assert repeated_node.attempts[0] == first_attempt
    assert len(repeated_node.attempts) == 2
    second_attempt = repeated_node.attempts[-1]
    assert second_attempt.attempt_id != first_attempt.attempt_id
    assert second_attempt.attempt_number == 2
    assert second_attempt.predecessor_attempt_id == first_attempt.attempt_id
    assert second_attempt.task_handle_id == accepted.task_handle.identity
    assert second_attempt.lifecycle is DiagnosticTaskLifecycle.FAILED
    assert second_attempt.failure is not None
    assert second_attempt.failure.code
    assert second_attempt.failure.message
    assert repeated_node.active_attempt_id == second_attempt.attempt_id
    assert repeated_failure.capabilities.can_retry_failed_node
    terminal_handle = next(
        handle
        for handle in repeated_failure.task_handles
        if handle.identity == accepted.task_handle.identity
    )
    assert terminal_handle.phase is TaskPhase.FAILED
    assert terminal_handle.result is None
    assert terminal_handle.error is not None
    assert terminal_handle.error.code
    assert terminal_handle.error.message

    second_retry = feature.retry_failed_campaign_node(
        RetryFailedCampaignNode(
            command_id=DiagnosticCommandId(
                "retry-repeat-failure-command-61-again"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "retry-repeat-failure-idempotency-61-again"
            ),
            task_id=approved.task_id,
            campaign_node_id=repeated_node.campaign_node_id,
            failed_attempt_id=second_attempt.attempt_id,
            expected_revision=repeated_node.revision,
        )
    )

    assert second_retry.accepted
    assert second_retry.task_handle is not None
    third_failure = _read_task(feature, approved.task_id)
    third_node = next(
        node
        for node in third_failure.handoff.campaign_nodes
        if node.campaign_node_id == first_node.campaign_node_id
    )
    assert len(third_node.attempts) == 3
    assert third_node.attempts[:2] == repeated_node.attempts
    third_attempt = third_node.attempts[-1]
    assert third_attempt.attempt_number == 3
    assert third_attempt.predecessor_attempt_id == second_attempt.attempt_id
    assert third_attempt.lifecycle is DiagnosticTaskLifecycle.FAILED
    assert third_attempt.task_handle_id == second_retry.task_handle.identity
    second_terminal_handle = next(
        handle
        for handle in third_failure.task_handles
        if handle.identity == second_retry.task_handle.identity
    )
    assert second_terminal_handle.phase is TaskPhase.FAILED

    restarted = create_diagnostics_application(
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
        ptrade_host=host,
    )
    restarted.start()
    restarted.initialize_persistence(engine)
    restarted_feature = LiveDiagnosticTasksAdapter(
        application=(
            LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
                restarted
            )
        )
    )
    reopened = _read_task(restarted_feature, approved.task_id)
    assert reopened.handoff == third_failure.handoff
    assert reopened.task_handles == third_failure.task_handles


def test_live_retry_of_a_second_failed_node_preserves_first_retry_history(
    tmp_path,
) -> None:
    host = _AlwaysFailDecisionPTradeHost()
    (
        _source,
        _artifact_store,
        _engine,
        application,
        _application_adapter,
        feature,
    ) = _formal_live_stack(tmp_path, ptrade_host=host)
    approved = _approved_formal_task(feature)
    feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-two-failures-command-61"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-two-failures-idempotency-61"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    after_first = _read_task(feature, approved.task_id)
    assert after_first.handoff.campaign_id is not None
    application.resume_diagnostic_campaign(
        after_first.handoff.campaign_id.value,
        max_cases=1,
    )
    two_failures = _read_task(feature, approved.task_id)
    failed_nodes = tuple(
        node
        for node in two_failures.handoff.campaign_nodes
        if node.lifecycle is DiagnosticTaskLifecycle.FAILED
    )
    assert len(failed_nodes) == 2
    first_node, second_node = failed_nodes
    first_attempt = first_node.attempts[-1]
    first_retry = feature.retry_failed_campaign_node(
        RetryFailedCampaignNode(
            command_id=DiagnosticCommandId(
                "retry-first-of-two-command-61"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "retry-first-of-two-idempotency-61"
            ),
            task_id=approved.task_id,
            campaign_node_id=first_node.campaign_node_id,
            failed_attempt_id=first_attempt.attempt_id,
            expected_revision=first_node.revision,
        )
    )
    assert first_retry.accepted
    after_first_retry = _read_task(feature, approved.task_id)
    first_retried_node = next(
        node
        for node in after_first_retry.handoff.campaign_nodes
        if node.campaign_node_id == first_node.campaign_node_id
    )
    second_still_failed = next(
        node
        for node in after_first_retry.handoff.campaign_nodes
        if node.campaign_node_id == second_node.campaign_node_id
    )
    assert first_retried_node.attempts[-1].task_handle_id is not None
    second_retry = feature.retry_failed_campaign_node(
        RetryFailedCampaignNode(
            command_id=DiagnosticCommandId(
                "retry-second-of-two-command-61"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "retry-second-of-two-idempotency-61"
            ),
            task_id=approved.task_id,
            campaign_node_id=second_still_failed.campaign_node_id,
            failed_attempt_id=second_still_failed.attempts[-1].attempt_id,
            expected_revision=second_still_failed.revision,
        )
    )

    assert second_retry.accepted
    assert second_retry.task_handle is not None
    completed = _read_task(feature, approved.task_id)
    preserved_first = next(
        node
        for node in completed.handoff.campaign_nodes
        if node.campaign_node_id == first_node.campaign_node_id
    )
    retried_second = next(
        node
        for node in completed.handoff.campaign_nodes
        if node.campaign_node_id == second_node.campaign_node_id
    )
    assert preserved_first.attempts == first_retried_node.attempts
    assert len(retried_second.attempts) == 2
    assert (
        retried_second.attempts[-1].predecessor_attempt_id
        == second_still_failed.attempts[-1].attempt_id
    )
    assert retried_second.attempts[-1].lifecycle is (
        DiagnosticTaskLifecycle.FAILED
    )
    second_handle = next(
        handle
        for handle in completed.task_handles
        if handle.identity == second_retry.task_handle.identity
    )
    assert second_handle.phase is TaskPhase.FAILED


def test_live_campaign_progress_after_retry_preserves_task_handle_binding(
    tmp_path,
) -> None:
    host = _FailFirstDecisionPTradeHost()
    (
        _source,
        _artifact_store,
        _engine,
        application,
        _application_adapter,
        feature,
    ) = _formal_live_stack(tmp_path, ptrade_host=host)
    approved = _approved_formal_task(feature)
    feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-progress-command-61"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-progress-idempotency-61"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    failed = _read_task(feature, approved.task_id)
    failed_node = next(
        node
        for node in failed.handoff.campaign_nodes
        if node.lifecycle is DiagnosticTaskLifecycle.FAILED
    )
    retry = feature.retry_failed_campaign_node(
        RetryFailedCampaignNode(
            command_id=DiagnosticCommandId("retry-progress-command-61"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "retry-progress-idempotency-61"
            ),
            task_id=approved.task_id,
            campaign_node_id=failed_node.campaign_node_id,
            failed_attempt_id=failed_node.attempts[-1].attempt_id,
            expected_revision=failed_node.revision,
        )
    )
    assert retry.accepted
    after_retry = _read_task(feature, approved.task_id)
    retried_node = next(
        node
        for node in after_retry.handoff.campaign_nodes
        if node.campaign_node_id == failed_node.campaign_node_id
    )
    assert retried_node.attempts[-1].task_handle_id is not None
    assert after_retry.handoff.campaign_id is not None

    application.advance_diagnostic_campaign(
        after_retry.handoff.campaign_id.value,
        max_cases=1,
    )

    advanced = _read_task(feature, approved.task_id)
    advanced_retried_node = next(
        node
        for node in advanced.handoff.campaign_nodes
        if node.campaign_node_id == failed_node.campaign_node_id
    )
    assert advanced_retried_node.attempts == retried_node.attempts
    assert any(
        node.campaign_node_id != failed_node.campaign_node_id
        and bool(node.attempts)
        for node in advanced.handoff.campaign_nodes
    )


def test_live_retry_completion_preserves_a_newer_public_campaign_pause(
    tmp_path,
) -> None:
    host = _FailFirstDecisionPTradeHost()
    (
        _source,
        _artifact_store,
        _engine,
        _application,
        _application_adapter,
        feature,
    ) = _formal_live_stack(tmp_path, ptrade_host=host)
    approved = _approved_formal_task(feature)
    feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-pause-race-command-61"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-pause-race-idempotency-61"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    failed = _read_task(feature, approved.task_id)
    node = next(
        candidate
        for candidate in failed.handoff.campaign_nodes
        if candidate.lifecycle is DiagnosticTaskLifecycle.FAILED
    )
    assert node.active_attempt_id is not None
    retry_command = RetryFailedCampaignNode(
        command_id=DiagnosticCommandId("retry-pause-race-command-61"),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            "retry-pause-race-idempotency-61"
        ),
        task_id=approved.task_id,
        campaign_node_id=node.campaign_node_id,
        failed_attempt_id=node.active_attempt_id,
        expected_revision=node.revision,
    )
    retry = feature.retry_failed_campaign_node(retry_command)
    assert retry.accepted
    assert retry.task_handle is not None
    retried = _read_task(feature, approved.task_id)
    assert retried.handoff.campaign_id is not None
    assert retried.handoff.campaign_revision is not None
    paused = feature.pause_diagnostic_target(
        PauseDiagnosticTarget(
            command_id=DiagnosticCommandId(
                "pause-after-retry-command-61"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "pause-after-retry-idempotency-61"
            ),
            target=FormalDiagnosticCampaignTarget(
                retried.handoff.campaign_id
            ),
            expected_revision=retried.handoff.campaign_revision,
        )
    )
    assert paused.accepted
    completed = _read_task(feature, approved.task_id)
    completed_node = next(
        candidate
        for candidate in completed.handoff.campaign_nodes
        if candidate.campaign_node_id == node.campaign_node_id
    )
    assert completed.lifecycle is DiagnosticTaskLifecycle.PAUSED
    assert (
        completed.handoff.campaign_lifecycle
        is DiagnosticTaskLifecycle.PAUSED
    )
    assert completed_node.attempts[0] == node.attempts[0]
    assert len(completed_node.attempts) == 2
    assert (
        completed_node.attempts[-1].predecessor_attempt_id
        == node.attempts[0].attempt_id
    )
    assert (
        completed_node.attempts[-1].lifecycle
        is DiagnosticTaskLifecycle.COMPLETED
    )
    assert (
        completed_node.attempts[-1].task_handle_id
        == retry.task_handle.identity
    )
    terminal_handle = next(
        handle
        for handle in completed.task_handles
        if handle.identity == retry.task_handle.identity
    )
    assert terminal_handle.phase is TaskPhase.COMPLETED


def test_live_failed_node_retry_recovers_after_completion_write_interruption(
    tmp_path,
) -> None:
    host = _FailFirstDecisionPTradeHost()
    (
        source,
        artifact_store,
        engine,
        _application,
        _application_adapter,
        feature,
    ) = _formal_live_stack(tmp_path, ptrade_host=host)
    approved = _approved_formal_task(feature)
    feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("start-recovery-command-61"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "start-recovery-idempotency-61"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    failed = _read_task(feature, approved.task_id)
    node = next(
        candidate
        for candidate in failed.handoff.campaign_nodes
        if candidate.lifecycle is DiagnosticTaskLifecycle.FAILED
    )
    assert node.active_attempt_id is not None
    handoff_update_count = 0

    def interrupt_second_handoff_update(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        nonlocal handoff_update_count
        if not statement.startswith(
            "UPDATE diagnostic_task_campaign_handoffs"
        ):
            return
        handoff_update_count += 1
        if handoff_update_count == 2:
            raise SQLAlchemyError("deterministic retry completion interruption")

    event.listen(engine, "before_cursor_execute", interrupt_second_handoff_update)
    try:
        accepted = feature.retry_failed_campaign_node(
            RetryFailedCampaignNode(
                command_id=DiagnosticCommandId(
                    "retry-recovery-command-61"
                ),
                idempotency_key=DiagnosticCommandIdempotencyKey(
                    "retry-recovery-idempotency-61"
                ),
                task_id=approved.task_id,
                campaign_node_id=node.campaign_node_id,
                failed_attempt_id=node.active_attempt_id,
                expected_revision=node.revision,
            )
        )
    finally:
        event.remove(
            engine,
            "before_cursor_execute",
            interrupt_second_handoff_update,
        )
    assert accepted.accepted
    assert accepted.task_handle is not None
    queued = _read_task(feature, approved.task_id)
    queued_handle = next(
        handle
        for handle in queued.task_handles
        if handle.identity == accepted.task_handle.identity
    )
    assert queued_handle.phase is TaskPhase.QUEUED
    assert queued.handoff.campaign_nodes[0].attempts

    restarted = create_diagnostics_application(
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
        ptrade_host=host,
    )
    restarted.start()
    restarted.initialize_persistence(engine)
    restarted_feature = LiveDiagnosticTasksAdapter(
        application=(
            LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
                restarted
            )
        )
    )
    recovered = _read_task(restarted_feature, approved.task_id)
    recovered_node = next(
        candidate
        for candidate in recovered.handoff.campaign_nodes
        if candidate.campaign_node_id == node.campaign_node_id
    )
    assert len(recovered_node.attempts) == 2
    assert recovered_node.attempts[0] == node.attempts[0]
    assert recovered_node.attempts[1].predecessor_attempt_id == (
        node.attempts[0].attempt_id
    )
    recovered_handle = next(
        handle
        for handle in recovered.task_handles
        if handle.identity == accepted.task_handle.identity
    )
    assert recovered_handle.phase is TaskPhase.COMPLETED
    assert recovered_handle.result == "failed_campaign_node_retry_completed"
