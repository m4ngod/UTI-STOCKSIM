from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import datetime, timedelta, timezone
from threading import Event, Thread, current_thread
from typing import cast

import pytest

from app.app_context import build_app_context
from app.event_bridge import EventBridge
from app.features import (
    DIAGNOSTIC_TASKS_INTERFACE_VERSION,
    ApproveDiagnosticTaskConfiguration,
    CampaignAttemptId,
    CampaignNodeId,
    CancelDiagnosticTarget,
    CreateDiagnosticTask,
    DeterministicFakeDiagnosticTasksAdapter,
    DiagnosticActorId,
    DiagnosticCampaignCaseSelection,
    DiagnosticCampaignLayer,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    DiagnosticComparisonRole,
    DiagnosticStrategySelection,
    DiagnosticTaskCommandRejectionReason,
    DiagnosticTaskConfiguration,
    DiagnosticTaskConfigurationContentId,
    DiagnosticTaskId,
    DiagnosticTaskLifecycle,
    DiagnosticTasksApplicationAvailability,
    DiagnosticTasksApplicationError,
    DiagnosticTasksApplicationErrorCode,
    DiagnosticTasksApplicationInventoryResult,
    DiagnosticTasksBlockingCode,
    DiagnosticTasksCommandDisposition,
    DiagnosticTasksContext,
    DiagnosticTasksFeature,
    DiagnosticTasksPresentationState,
    DiagnosticTaskTarget,
    DiagnosticTaskValidationId,
    DiagnosticTaskValidationState,
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
    StrategyDiagnosticsV1ApplicationReadModel,
    StrategyDiagnosticsV1DiagnosticTasksApplication,
    TaskPhase,
    ValidateDiagnosticTaskConfiguration,
)
from strategy_diagnostics import create_diagnostics_application
from strategy_diagnostics.market_paths import InMemoryMarketPathArtifactStore
from tests.frontend.contract.test_diagnostic_task_revision_approval_live_contract import (
    _persistent_three_layer_stack,
)
from tests.strategy_diagnostics.test_recipe_lifecycle import (
    _baseline_payload,
    _RecipeFixtureSource,
)


def _live_diagnostics_application():
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
    return application


def _live_application_adapter() -> (
    StrategyDiagnosticsV1DiagnosticTasksApplication
):
    return LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
        _live_diagnostics_application()
    )


def _live_feature(
    *,
    event_bridge: EventBridge | None = None,
) -> DiagnosticTasksFeature:
    return LiveDiagnosticTasksAdapter(
        application=_live_application_adapter(),
        event_bridge=event_bridge,
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


@dataclass(frozen=True)
class _DiagnosticTasksRecoveryHarness:
    feature: DiagnosticTasksFeature
    disconnect: Callable[[], None]
    reconnect: Callable[[], None]


@dataclass(frozen=True)
class _DelayedSnapshotRecoveryHarness:
    feature: DiagnosticTasksFeature
    disconnect: Callable[[], None]
    reconnect: Callable[[], None]
    block_next_read: Callable[[], None]
    wait_until_blocked: Callable[[], bool]
    release_read: Callable[[], None]


class _BlockingInventoryApplication:
    def __init__(
        self,
        delegate: StrategyDiagnosticsV1DiagnosticTasksApplication,
        entered: Event,
        release: Event,
    ) -> None:
        self._delegate = delegate
        self._entered = entered
        self._release = release
        self._block_next = False

    def block_next_read(self) -> None:
        self._block_next = True

    def read_inventory(self):
        if self._block_next:
            self._block_next = False
            self._entered.set()
            assert self._release.wait(2)
        return self._delegate.read_inventory()

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)


class _BlockingTaskReadApplication:
    def __init__(
        self,
        delegate: StrategyDiagnosticsV1DiagnosticTasksApplication,
        entered: Event,
        release: Event,
    ) -> None:
        self._delegate = delegate
        self._entered = entered
        self._release = release
        self._block_next = False

    def block_next_read(self) -> None:
        self._block_next = True

    def read_diagnostic_task(self, task_id):
        result = self._delegate.read_diagnostic_task(task_id)
        if self._block_next:
            self._block_next = False
            self._entered.set()
            assert self._release.wait(2)
        return result

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)


class _BlockingClock:
    def __init__(self) -> None:
        self._entered = Event()
        self._release = Event()
        self._block_named_thread = False

    def block_next_named_thread(self) -> None:
        self._block_named_thread = True

    def wait_until_blocked(self) -> bool:
        return self._entered.wait(2)

    def release(self) -> None:
        self._release.set()

    def __call__(self) -> datetime:
        if (
            self._block_named_thread
            and current_thread().name == "older-snapshot"
        ):
            self._block_named_thread = False
            self._entered.set()
            assert self._release.wait(2)
        return datetime(2030, 1, 1, tzinfo=timezone.utc)


class _DisconnectAfterAcceptedCreateApplication:
    def __init__(
        self,
        delegate: StrategyDiagnosticsV1DiagnosticTasksApplication,
        bridge: EventBridge,
    ) -> None:
        self._delegate = delegate
        self._bridge = bridge
        self._did_disconnect = False

    def create_diagnostic_task(self, command):
        accepted = self._delegate.create_diagnostic_task(command)
        if not self._did_disconnect:
            self._did_disconnect = True
            self._bridge.mark_disconnected()
        return accepted

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)


class _ReconnectBeforeAcceptedCreateReturnsApplication:
    def __init__(
        self,
        delegate: StrategyDiagnosticsV1DiagnosticTasksApplication,
        bridge: EventBridge,
    ) -> None:
        self._delegate = delegate
        self._bridge = bridge
        self._did_reconnect = False

    def create_diagnostic_task(self, command):
        accepted = self._delegate.create_diagnostic_task(command)
        if not self._did_reconnect:
            self._did_reconnect = True
            self._bridge.mark_disconnected()
            self._bridge.mark_reconnected()
        return accepted

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)


class _LoseFirstCreateResponseDiagnosticsApplication:
    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self._lost = False

    def create_diagnostic_task(self, request):
        result = self._delegate.create_diagnostic_task(request)
        if not self._lost:
            self._lost = True
            raise RuntimeError("response lost after durable acceptance")
        return result

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)


def _live_recovery_harness() -> _DiagnosticTasksRecoveryHarness:
    bridge = EventBridge(subscribe_backend=False)
    return _DiagnosticTasksRecoveryHarness(
        feature=_live_feature(event_bridge=bridge),
        disconnect=bridge.mark_disconnected,
        reconnect=bridge.mark_reconnected,
    )


def _fake_recovery_harness() -> _DiagnosticTasksRecoveryHarness:
    feature = _fake_feature()
    assert isinstance(feature, DeterministicFakeDiagnosticTasksAdapter)
    return _DiagnosticTasksRecoveryHarness(
        feature=feature,
        disconnect=feature.advance_to_disconnected,
        reconnect=feature.advance_to_reconnected,
    )


def _live_delayed_snapshot_recovery_harness() -> (
    _DelayedSnapshotRecoveryHarness
):
    bridge = EventBridge(subscribe_backend=False)
    entered = Event()
    release = Event()
    application = _BlockingTaskReadApplication(
        _live_application_adapter(),
        entered,
        release,
    )
    feature = LiveDiagnosticTasksAdapter(
        application=cast(
            StrategyDiagnosticsV1DiagnosticTasksApplication,
            application,
        ),
        event_bridge=bridge,
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    return _DelayedSnapshotRecoveryHarness(
        feature=feature,
        disconnect=bridge.mark_disconnected,
        reconnect=bridge.mark_reconnected,
        block_next_read=application.block_next_read,
        wait_until_blocked=lambda: entered.wait(2),
        release_read=release.set,
    )


def _fake_delayed_snapshot_recovery_harness() -> (
    _DelayedSnapshotRecoveryHarness
):
    clock = _BlockingClock()
    feature = DeterministicFakeDiagnosticTasksAdapter(
        inventory=_authoritative_inventory(),
        clock=clock,
    )
    return _DelayedSnapshotRecoveryHarness(
        feature=feature,
        disconnect=feature.advance_to_disconnected,
        reconnect=feature.advance_to_reconnected,
        block_next_read=clock.block_next_named_thread,
        wait_until_blocked=clock.wait_until_blocked,
        release_read=clock.release,
    )


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
    configuration = DiagnosticTaskConfiguration.create(
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
            DiagnosticTaskValidationId("diagnostic-task-validation-58"),
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


def _live_revision_feature(tmp_path) -> DiagnosticTasksFeature:
    return _persistent_three_layer_stack(tmp_path)[-1]


def _fake_revision_feature(tmp_path) -> DiagnosticTasksFeature:
    live = _persistent_three_layer_stack(tmp_path)[-1]
    context = DiagnosticTasksContext.workspace()
    live.snapshot(context)
    inventory = live.snapshot(context).last_reliable_inventory
    live.close()
    assert inventory is not None
    return DeterministicFakeDiagnosticTasksAdapter(inventory=inventory)


def _current_task(feature: DiagnosticTasksFeature, task_id: DiagnosticTaskId):
    context = DiagnosticTasksContext(task_id)
    feature.snapshot(context)
    state = feature.snapshot(context)
    assert state.task is not None
    return state.task


@pytest.mark.parametrize(
    "feature_factory",
    [_live_revision_feature, _fake_revision_feature],
)
def test_live_and_fake_share_revision_validation_approval_conformance(
    feature_factory,
    tmp_path,
) -> None:
    feature = feature_factory(tmp_path)
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    inventory = feature.snapshot(workspace).last_reliable_inventory
    assert inventory is not None
    commands = _unavailable_commands(inventory)
    full_configuration = commands[0].configuration
    baseline_configuration = DiagnosticTaskConfiguration.create(
        strategy_selections=full_configuration.strategy_selections,
        campaign_case_selections=tuple(
            item
            for item in full_configuration.campaign_case_selections
            if item.layer is DiagnosticCampaignLayer.BASELINE
        ),
    )
    created = feature.create_diagnostic_task(
        replace(commands[0], configuration=baseline_configuration)
    )
    assert created.affected_task_id is not None
    task_id = created.affected_task_id
    revised_command = replace(
        commands[1],
        task_id=task_id,
        expected_revision=2,
        configuration=full_configuration,
    )
    creation_identity_conflict = feature.revise_configuration(
        replace(
            revised_command,
            command_id=commands[0].command_id,
        )
    )
    assert creation_identity_conflict.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.COMMAND_IDENTITY_CONFLICT
    )
    creation_key_conflict = feature.revise_configuration(
        replace(
            revised_command,
            idempotency_key=commands[0].idempotency_key,
        )
    )
    assert creation_key_conflict.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.IDEMPOTENCY_CONFLICT
    )
    assert _current_task(feature, task_id).revision == 2

    revised = feature.revise_configuration(revised_command)
    replayed_revision = feature.revise_configuration(revised_command)

    assert revised.disposition is (
        DiagnosticTasksCommandDisposition.SYNCHRONOUS_COMPLETION
    )
    assert revised.current_revision == 3
    assert revised.task_handle is None
    assert replayed_revision.disposition is (
        DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    )
    assert _current_task(feature, task_id).configuration == full_configuration

    stale = feature.revise_configuration(
        replace(
            revised_command,
            command_id=DiagnosticCommandId("command-58-stale"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "idempotency-58-stale"
            ),
            expected_revision=2,
            configuration=baseline_configuration,
        )
    )
    assert stale.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.STALE_EXPECTED_REVISION
    )
    assert stale.current_revision == 3
    assert stale.task_handle is None

    validate_command = replace(
        commands[2],
        task_id=task_id,
        expected_revision=3,
    )
    validated = feature.validate_configuration(validate_command)
    replayed_validation = feature.validate_configuration(validate_command)

    assert validated.disposition is (
        DiagnosticTasksCommandDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    assert validated.task_handle is not None
    assert validated.task_handle.phase is TaskPhase.QUEUED
    assert replayed_validation.disposition is (
        DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    )
    assert replayed_validation.task_handle is not None
    assert replayed_validation.task_handle.phase is TaskPhase.COMPLETED
    task = _current_task(feature, task_id)
    assert task.lifecycle is DiagnosticTaskLifecycle.AWAITING_APPROVAL
    assert task.validation.state is DiagnosticTaskValidationState.VALID
    assert task.validation.validation_id is not None
    assert task.validation.task_handle_id is not None
    assert task.validation.validation_revision == 1
    assert task.validation.validated_revision == 3
    assert task.validation.policy_identities
    assert task.validation.findings == ()
    validation_handle = next(
        handle
        for handle in task.task_handles
        if handle.identity == task.validation.task_handle_id
    )
    assert validation_handle.phase is TaskPhase.COMPLETED
    assert (
        validation_handle.result
        == "diagnostic_task_configuration_valid"
    )
    assert task.capabilities.can_approve
    validated_view_revision = feature.snapshot(
        DiagnosticTasksContext(task_id=task_id)
    ).revision

    stale_validation_approval = feature.approve_configuration(
        replace(
            commands[3],
            task_id=task_id,
            expected_revision=3,
            validation_id=DiagnosticTaskValidationId(
                "diagnostic-task-validation-stale"
            ),
            validation_revision=task.validation.validation_revision,
            validated_revision=3,
            configuration_content_id=full_configuration.content_identity,
        )
    )
    assert stale_validation_approval.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.STALE_VALIDATION
    )
    assert stale_validation_approval.current_revision == 3
    assert stale_validation_approval.task_handle is None
    assert _current_task(feature, task_id).approval is None

    approval_command = replace(
        commands[3],
        task_id=task_id,
        expected_revision=3,
        validation_id=task.validation.validation_id,
        validation_revision=task.validation.validation_revision,
        validated_revision=3,
        configuration_content_id=full_configuration.content_identity,
    )
    approved = feature.approve_configuration(approval_command)
    replayed_approval = feature.approve_configuration(approval_command)

    assert approved.disposition is (
        DiagnosticTasksCommandDisposition.SYNCHRONOUS_COMPLETION
    )
    assert approved.task_handle is None
    assert replayed_approval.disposition is (
        DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    )
    task = _current_task(feature, task_id)
    approved_view_revision = feature.snapshot(
        DiagnosticTasksContext(task_id=task_id)
    ).revision
    assert approved_view_revision > validated_view_revision
    assert task.lifecycle is DiagnosticTaskLifecycle.APPROVED
    assert task.approval is not None
    assert task.approval.validation_id == task.validation.validation_id
    assert task.approval.validation_revision == 1
    assert task.approval.policy_identities == task.validation.policy_identities
    original_approval = task.approval
    stale_approval = feature.approve_configuration(
        replace(
            approval_command,
            command_id=DiagnosticCommandId("command-58-stale-approval"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "idempotency-58-stale-approval"
            ),
        )
    )
    assert stale_approval.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.STALE_APPROVAL
    )
    assert stale_approval.current_revision == 3
    assert stale_approval.task_handle is None
    assert _current_task(feature, task_id).approval == original_approval

    corrected = feature.revise_configuration(
        replace(
            revised_command,
            command_id=DiagnosticCommandId("command-58-invalidate"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "idempotency-58-invalidate"
            ),
            expected_revision=3,
            configuration=baseline_configuration,
        )
    )
    assert corrected.current_revision == 4
    task = _current_task(feature, task_id)
    assert task.lifecycle is DiagnosticTaskLifecycle.DRAFT
    assert task.validation.state is DiagnosticTaskValidationState.NOT_VALIDATED
    assert task.approval is None

    invalid_validation = feature.validate_configuration(
        replace(
            validate_command,
            command_id=DiagnosticCommandId("command-58-invalid-validate"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "idempotency-58-invalid-validate"
            ),
            expected_revision=4,
        )
    )
    assert invalid_validation.accepted
    task = _current_task(feature, task_id)
    assert task.validation.state is DiagnosticTaskValidationState.INVALID
    assert {
        item.code.value for item in task.validation.findings
    } >= {
        "campaign.layer.isolated_sensitivity_required",
        "campaign.layer.compound_required",
    }
    rejected_approval = feature.approve_configuration(
        replace(
            approval_command,
            command_id=DiagnosticCommandId("command-58-invalid-approve"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "idempotency-58-invalid-approve"
            ),
            expected_revision=4,
            validation_id=task.validation.validation_id,
            validation_revision=task.validation.validation_revision,
            validated_revision=4,
            configuration_content_id=baseline_configuration.content_identity,
        )
    )
    assert rejected_approval.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.VALIDATION_FAILED
    )
    assert rejected_approval.task_handle is None
    assert feature.start_formal_diagnostic_campaign(
        replace(
            commands[4],
            task_id=task_id,
            expected_revision=4,
            approved_revision=4,
        )
    ).rejection_reason is DiagnosticTaskCommandRejectionReason.STALE_APPROVAL
    feature.close()


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
    created = feature.create_diagnostic_task(commands[0])
    assert (
        created.disposition
        is DiagnosticTasksCommandDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    assert created.task is not None
    assert created.task.phase is TaskPhase.QUEUED
    assert created.affected_task_id is not None
    task_context = DiagnosticTasksContext(created.affected_task_id)
    assert (
        feature.snapshot(task_context).presentation
        is DiagnosticTasksPresentationState.LOADING
    )
    created_state = feature.snapshot(task_context)
    assert created_state.task is not None
    assert created_state.task.revision == 2
    assert created_state.task.lifecycle is DiagnosticTaskLifecycle.DRAFT
    assert created_state.task.task_handles[0].phase is TaskPhase.COMPLETED
    assert created_state.task.handoff.campaign_id is None
    replay = feature.create_diagnostic_task(
        replace(
            commands[0],
            command_id=DiagnosticCommandId("command-57-replay"),
        )
    )
    assert (
        replay.disposition is DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    )
    assert replay.affected_task_id == created.affected_task_id
    conflict = feature.create_diagnostic_task(
        replace(
            commands[0],
            command_id=DiagnosticCommandId("command-57-conflict"),
            configuration=replace(
                commands[0].configuration,
                content_identity=DiagnosticTaskConfigurationContentId(
                    "sha256:" + "f" * 64
                ),
            ),
        )
    )
    assert conflict.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.IDEMPOTENCY_CONFLICT
    )
    second = feature.create_diagnostic_task(
        replace(
            commands[0],
            command_id=DiagnosticCommandId("command-57-second"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "idempotency-57-second"
            ),
        )
    )
    assert second.disposition is (
        DiagnosticTasksCommandDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    cross_bound = feature.create_diagnostic_task(
        replace(
            commands[0],
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "idempotency-57-second"
            ),
        )
    )
    assert cross_bound.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.COMMAND_IDENTITY_CONFLICT
    )
    authoritative_case = commands[0].configuration.campaign_case_selections[0]
    non_authoritative = DiagnosticTaskConfiguration.create(
        strategy_selections=commands[0].configuration.strategy_selections,
        campaign_case_selections=(
            replace(
                authoritative_case,
                recipe_content_hash="sha256:non-authoritative-recipe",
            ),
        ),
    )
    invalid = feature.create_diagnostic_task(
        replace(
            commands[0],
            command_id=DiagnosticCommandId("command-57-invalid-authority"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "idempotency-57-invalid-authority"
            ),
            configuration=non_authoritative,
        )
    )
    assert invalid.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.INVALID_COMMAND
    )
    reordered_case = replace(
        authoritative_case,
        execution_policy_values=tuple(
            reversed(authoritative_case.execution_policy_values)
        ),
    )
    reordered_configuration = DiagnosticTaskConfiguration.create(
        strategy_selections=commands[0].configuration.strategy_selections,
        campaign_case_selections=(reordered_case,),
    )
    reordered = feature.create_diagnostic_task(
        replace(
            commands[0],
            command_id=DiagnosticCommandId("command-57-reordered-policies"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "idempotency-57-reordered-policies"
            ),
            configuration=reordered_configuration,
        )
    )
    assert reordered.disposition is (
        DiagnosticTasksCommandDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    results = (
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
        is DiagnosticTaskCommandRejectionReason.INVALID_COMMAND
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


@pytest.mark.parametrize("baseline_count", [0, 2])
def test_create_capability_requires_exactly_one_authoritative_baseline(
    baseline_count: int,
) -> None:
    inventory = _authoritative_inventory()
    baseline = inventory.market_scenarios[0]
    scenarios = () if baseline_count == 0 else (baseline, baseline)
    feature = DeterministicFakeDiagnosticTasksAdapter(
        inventory=replace(inventory, market_scenarios=scenarios)
    )
    context = DiagnosticTasksContext.workspace()
    feature.snapshot(context)

    state = feature.snapshot(context)

    assert state.capabilities.can_create is False
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


def test_live_diagnostic_tasks_reconnects_with_a_new_generation_only_after_reread(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    application = create_diagnostics_application()
    application.start()
    application_adapter = (
        LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(application)
    )
    bridge = EventBridge(subscribe_backend=False)
    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="live",
        event_bridge=bridge,
        strategy_diagnostics_read_model=cast(
            StrategyDiagnosticsV1ApplicationReadModel,
            object(),
        ),
        strategy_diagnostics_tasks_application=application_adapter,
    )
    feature = context.diagnostic_tasks_feature
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    reliable = feature.snapshot(workspace)
    observed = []
    subscription = feature.subscribe(workspace, observed.append)

    bridge.mark_disconnected()
    disconnected = feature.snapshot(workspace)

    assert disconnected.revision > reliable.revision
    assert disconnected.freshness is Freshness.DISCONNECTED
    assert disconnected.last_reliable_inventory is reliable.last_reliable_inventory
    assert disconnected.source.generation.value == 1
    assert disconnected.error is not None
    assert disconnected.error.code == "diagnostic_tasks_source_disconnected"
    assert disconnected.blocking_reasons[0].code is (
        DiagnosticTasksBlockingCode.SOURCE_DISCONNECTED
    )

    bridge.mark_reconnected()
    recovered = feature.snapshot(workspace)

    assert recovered.revision > disconnected.revision
    assert recovered.freshness is Freshness.FRESH
    assert recovered.source.generation.value == 2
    assert recovered.last_reliable_inventory is not None
    assert any(
        state.source.generation.value == 2
        and state.freshness is not Freshness.FRESH
        and state.error is not None
        and state.error.code == "diagnostic_tasks_source_reconnecting"
        for state in observed
    )

    subscription.dispose()
    delivered_before_close = len(observed)
    feature.close()
    feature.close()
    bridge.mark_disconnected()
    bridge.mark_reconnected()
    assert len(observed) == delivered_before_close

    context.run_monitoring_feature.close()
    context.evidence_and_findings_feature.close()


@pytest.mark.parametrize(
    "harness_factory",
    [_live_recovery_harness, _fake_recovery_harness],
)
def test_live_and_fake_opened_disconnected_never_claim_fresh_or_empty(
    harness_factory: Callable[[], _DiagnosticTasksRecoveryHarness],
) -> None:
    harness = harness_factory()
    feature = harness.feature
    workspace = DiagnosticTasksContext.workspace()
    harness.disconnect()

    disconnected = feature.snapshot(workspace)

    assert disconnected.revision == 1
    assert disconnected.freshness is Freshness.DISCONNECTED
    assert disconnected.presentation is DiagnosticTasksPresentationState.FAILED
    assert disconnected.last_reliable_inventory is None
    assert disconnected.task is None
    assert disconnected.source.generation.value == 1
    assert disconnected.error is not None
    assert disconnected.error.code == "diagnostic_tasks_source_disconnected"
    assert disconnected.blocking_reasons[0].code is (
        DiagnosticTasksBlockingCode.SOURCE_DISCONNECTED
    )

    harness.reconnect()
    recovered = feature.snapshot(workspace)

    assert recovered.revision > disconnected.revision
    assert recovered.freshness is Freshness.FRESH
    assert recovered.source.generation.value == 2
    feature.close()


@pytest.mark.parametrize(
    "harness_factory",
    [_live_recovery_harness, _fake_recovery_harness],
)
def test_live_and_fake_share_navigation_disconnect_and_reconnect_state(
    harness_factory: Callable[[], _DiagnosticTasksRecoveryHarness],
) -> None:
    harness = harness_factory()
    feature = harness.feature
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    reliable = feature.snapshot(workspace)
    observed = []
    page_subscription = feature.subscribe(workspace, observed.append)

    harness.disconnect()
    disconnected = feature.snapshot(workspace)

    assert disconnected.revision > reliable.revision
    assert disconnected.freshness is Freshness.DISCONNECTED
    assert disconnected.last_reliable_inventory is reliable.last_reliable_inventory
    assert disconnected.source.generation.value == 1
    assert disconnected.error is not None
    assert disconnected.error.code == "diagnostic_tasks_source_disconnected"
    assert disconnected.blocking_reasons[0].code is (
        DiagnosticTasksBlockingCode.SOURCE_DISCONNECTED
    )

    harness.reconnect()
    recovered = feature.snapshot(workspace)

    assert recovered.revision > disconnected.revision
    assert recovered.freshness is Freshness.FRESH
    assert recovered.source.generation.value == 2
    assert any(
        state.source.generation.value == 2
        and state.freshness is not Freshness.FRESH
        and state.error is not None
        and state.error.code == "diagnostic_tasks_source_reconnecting"
        for state in observed
    )

    page_subscription.dispose()
    observed_before_route_leave = len(observed)
    harness.disconnect()
    harness.reconnect()
    remounted = feature.snapshot(workspace)

    assert len(observed) == observed_before_route_leave
    assert remounted.freshness is Freshness.FRESH
    assert remounted.source.generation.value == 3
    remount_observed = []
    remount_subscription = feature.subscribe(
        workspace,
        remount_observed.append,
    )
    assert remount_observed[-1] == remounted
    remount_subscription.dispose()
    feature.close()


@pytest.mark.parametrize(
    "harness_factory",
    [_live_recovery_harness, _fake_recovery_harness],
)
def test_live_and_fake_reject_before_acceptance_while_disconnected(
    harness_factory: Callable[[], _DiagnosticTasksRecoveryHarness],
) -> None:
    harness = harness_factory()
    feature = harness.feature
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    reliable = feature.snapshot(workspace)
    assert reliable.last_reliable_inventory is not None
    commands = _unavailable_commands(reliable.last_reliable_inventory)
    command = commands[0]

    harness.disconnect()
    rejected_results = (
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

    assert all(not result.accepted for result in rejected_results)
    assert all(
        result.rejection_reason
        is DiagnosticTaskCommandRejectionReason.DISCONNECTED_SOURCE
        for result in rejected_results
    )
    assert all(result.task_handle is None for result in rejected_results)
    assert all(result.retryable for result in rejected_results)
    assert all(
        "authoritative command lookup" in result.message
        for result in rejected_results
    )

    harness.reconnect()
    accepted = feature.create_diagnostic_task(command)
    replay = feature.create_diagnostic_task(
        replace(
            command,
            command_id=DiagnosticCommandId("command-62-create-replay"),
        )
    )

    assert accepted.accepted
    assert accepted.task_handle is not None
    assert (
        replay.disposition
        is DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    )
    assert replay.task_handle is not None
    assert replay.task_handle.identity == accepted.task_handle.identity
    assert replay.task_handle.phase is TaskPhase.COMPLETED
    assert replay.affected_task_id == accepted.affected_task_id
    feature.close()


def test_live_adapter_quarantines_an_authoritative_read_from_old_generation() -> (
    None
):
    bridge = EventBridge(subscribe_backend=False)
    entered = Event()
    release = Event()
    application = _BlockingInventoryApplication(
        _live_application_adapter(),
        entered,
        release,
    )
    feature = LiveDiagnosticTasksAdapter(
        application=cast(
            StrategyDiagnosticsV1DiagnosticTasksApplication,
            application,
        ),
        event_bridge=bridge,
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    application.block_next_read()
    completed = []
    reader = Thread(target=lambda: completed.append(feature.snapshot(workspace)))
    reader.start()
    assert entered.wait(2)

    bridge.mark_disconnected()
    disconnected = feature.snapshot(workspace)
    release.set()
    reader.join(timeout=2)

    assert not reader.is_alive()
    assert completed == [disconnected]
    assert feature.snapshot(workspace) == disconnected
    assert disconnected.freshness is Freshness.DISCONNECTED
    feature.close()


@pytest.mark.parametrize(
    "harness_factory",
    [
        _live_delayed_snapshot_recovery_harness,
        _fake_delayed_snapshot_recovery_harness,
    ],
)
def test_live_and_fake_quarantine_a_delayed_old_generation_snapshot(
    harness_factory: Callable[[], _DelayedSnapshotRecoveryHarness],
) -> None:
    harness = harness_factory()
    feature = harness.feature
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    reliable = feature.snapshot(workspace)
    assert reliable.last_reliable_inventory is not None
    commands = _unavailable_commands(reliable.last_reliable_inventory)
    first = feature.create_diagnostic_task(commands[0])
    assert first.affected_task_id is not None

    harness.block_next_read()
    completed = []
    reader = Thread(
        name="older-snapshot",
        target=lambda: completed.append(feature.snapshot(workspace)),
    )
    reader.start()
    assert harness.wait_until_blocked()

    harness.disconnect()
    harness.reconnect()
    second = feature.create_diagnostic_task(
        replace(
            commands[0],
            command_id=DiagnosticCommandId(
                "command-62-new-generation-task"
            ),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "idempotency-62-new-generation-task"
            ),
        )
    )
    assert second.affected_task_id is not None
    newest = feature.snapshot(workspace)
    assert newest.task is not None
    assert newest.task.task_id == second.affected_task_id
    assert newest.source.generation.value == 2

    harness.release_read()
    reader.join(timeout=2)

    assert not reader.is_alive()
    assert completed == [newest]
    assert feature.snapshot(workspace) == newest
    feature.close()


def test_live_adapter_quarantines_an_older_same_generation_snapshot() -> None:
    entered = Event()
    release = Event()
    application = _BlockingTaskReadApplication(
        _live_application_adapter(),
        entered,
        release,
    )
    feature = LiveDiagnosticTasksAdapter(
        application=cast(
            StrategyDiagnosticsV1DiagnosticTasksApplication,
            application,
        ),
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    reliable = feature.snapshot(workspace)
    assert reliable.last_reliable_inventory is not None
    commands = _unavailable_commands(reliable.last_reliable_inventory)
    first = feature.create_diagnostic_task(commands[0])
    assert first.affected_task_id is not None

    application.block_next_read()
    completed = []
    reader = Thread(
        name="older-snapshot",
        target=lambda: completed.append(feature.snapshot(workspace)),
    )
    reader.start()
    assert entered.wait(2)

    second = feature.create_diagnostic_task(
        replace(
            commands[0],
            command_id=DiagnosticCommandId("command-62-newer-task"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "idempotency-62-newer-task"
            ),
        )
    )
    assert second.affected_task_id is not None
    newest = feature.snapshot(workspace)
    assert newest.task is not None
    assert newest.task.task_id == second.affected_task_id

    release.set()
    reader.join(timeout=2)

    assert not reader.is_alive()
    assert completed == [newest]
    assert feature.snapshot(workspace) == newest
    feature.close()


def test_fake_adapter_quarantines_an_older_same_generation_snapshot() -> None:
    clock = _BlockingClock()
    feature = DeterministicFakeDiagnosticTasksAdapter(
        inventory=_authoritative_inventory(),
        clock=clock,
    )
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    reliable = feature.snapshot(workspace)
    assert reliable.last_reliable_inventory is not None
    commands = _unavailable_commands(reliable.last_reliable_inventory)
    first = feature.create_diagnostic_task(commands[0])
    assert first.affected_task_id is not None

    clock.block_next_named_thread()
    completed = []
    reader = Thread(
        name="older-snapshot",
        target=lambda: completed.append(feature.snapshot(workspace)),
    )
    reader.start()
    assert clock.wait_until_blocked()

    second = feature.create_diagnostic_task(
        replace(
            commands[0],
            command_id=DiagnosticCommandId("command-62-newer-fake-task"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "idempotency-62-newer-fake-task"
            ),
        )
    )
    assert second.affected_task_id is not None
    newest = feature.snapshot(workspace)
    assert newest.task is not None
    assert newest.task.task_id == second.affected_task_id

    clock.release()
    reader.join(timeout=2)

    assert not reader.is_alive()
    assert completed == [newest]
    assert feature.snapshot(workspace) == newest
    feature.close()


@pytest.mark.parametrize("feature_factory", [_live_feature, _fake_feature])
def test_subscribe_registers_against_the_latest_state(
    feature_factory: Callable[[], DiagnosticTasksFeature],
    monkeypatch,
) -> None:
    feature = feature_factory()
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    reliable = feature.snapshot(workspace)
    assert reliable.last_reliable_inventory is not None
    command = _unavailable_commands(reliable.last_reliable_inventory)[0]
    original_snapshot = feature.snapshot
    entered = Event()
    release = Event()

    def delayed_subscribe_snapshot(context):
        state = original_snapshot(context)
        if current_thread().name == "subscriber":
            entered.set()
            assert release.wait(2)
        return state

    monkeypatch.setattr(feature, "snapshot", delayed_subscribe_snapshot)
    observed = []
    subscriptions = []
    subscriber = Thread(
        name="subscriber",
        target=lambda: subscriptions.append(
            feature.subscribe(workspace, observed.append)
        ),
    )
    subscriber.start()
    assert entered.wait(2)

    accepted = feature.create_diagnostic_task(command)
    assert accepted.affected_task_id is not None
    newest = original_snapshot(workspace)
    assert newest.task is not None
    assert newest.task.task_id == accepted.affected_task_id

    release.set()
    subscriber.join(timeout=2)

    assert not subscriber.is_alive()
    assert observed[-1] == newest
    assert subscriptions
    subscriptions[0].dispose()
    feature.close()


def test_live_adapter_close_drops_an_inflight_read_without_late_callback() -> None:
    entered = Event()
    release = Event()
    application = _BlockingInventoryApplication(
        _live_application_adapter(),
        entered,
        release,
    )
    feature = LiveDiagnosticTasksAdapter(
        application=cast(
            StrategyDiagnosticsV1DiagnosticTasksApplication,
            application,
        ),
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    feature.snapshot(workspace)
    observed = []
    subscription = feature.subscribe(workspace, observed.append)
    delivered_before_close = len(observed)
    application.block_next_read()
    completed = []
    reader = Thread(target=lambda: completed.append(feature.snapshot(workspace)))
    reader.start()
    assert entered.wait(2)

    feature.close()
    feature.close()
    release.set()
    reader.join(timeout=2)

    assert not reader.is_alive()
    assert subscription.disposed
    assert len(observed) == delivered_before_close
    assert len(completed) == 1


def test_live_adapter_ignores_old_generation_batches_but_rereads_current() -> (
    None
):
    bridge = EventBridge(subscribe_backend=False)
    feature = _live_feature(event_bridge=bridge)
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    reliable = feature.snapshot(workspace)
    assert reliable.last_reliable_inventory is not None
    observed = []
    subscription = feature.subscribe(workspace, observed.append)
    bridge.mark_disconnected()
    bridge.mark_reconnected()
    accepted = feature.create_diagnostic_task(
        _unavailable_commands(reliable.last_reliable_inventory)[0]
    )
    assert accepted.accepted
    assert observed[-1].task is None

    delivered_before_old_batch = len(observed)
    bridge.on_snapshot({"kind": "diagnostic-task"}, generation=1)
    bridge.flush(force=True)

    assert len(observed) == delivered_before_old_batch
    assert observed[-1].task is None

    bridge.on_snapshot({"run_id": "market-run"}, generation=2)
    bridge.flush(force=True)

    assert len(observed) == delivered_before_old_batch
    assert observed[-1].task is None

    bridge.on_snapshot({"kind": "diagnostic-task"}, generation=2)
    bridge.flush(force=True)

    assert observed[-1].task is not None
    assert observed[-1].task.task_id == accepted.affected_task_id
    subscription.dispose()
    feature.close()


def test_disconnect_after_durable_acceptance_preserves_the_original_handle() -> (
    None
):
    bridge = EventBridge(subscribe_backend=False)
    wrapped = _DisconnectAfterAcceptedCreateApplication(
        _live_application_adapter(),
        bridge,
    )
    feature = LiveDiagnosticTasksAdapter(
        application=cast(
            StrategyDiagnosticsV1DiagnosticTasksApplication,
            wrapped,
        ),
        event_bridge=bridge,
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    reliable = feature.snapshot(workspace)
    assert reliable.last_reliable_inventory is not None
    command = _unavailable_commands(reliable.last_reliable_inventory)[0]

    accepted = feature.create_diagnostic_task(command)

    assert accepted.accepted
    assert accepted.task_handle is not None
    assert feature.snapshot(workspace).freshness is Freshness.DISCONNECTED

    bridge.mark_reconnected()
    replay = feature.create_diagnostic_task(
        replace(
            command,
            command_id=DiagnosticCommandId("command-62-post-accept-replay"),
        )
    )

    assert (
        replay.disposition
        is DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    )
    assert replay.task_handle is not None
    assert replay.task_handle.identity == accepted.task_handle.identity
    assert replay.affected_task_id == accepted.affected_task_id
    feature.close()


def test_old_generation_accepted_response_requires_authoritative_recovery() -> (
    None
):
    bridge = EventBridge(subscribe_backend=False)
    wrapped = _ReconnectBeforeAcceptedCreateReturnsApplication(
        _live_application_adapter(),
        bridge,
    )
    feature = LiveDiagnosticTasksAdapter(
        application=cast(
            StrategyDiagnosticsV1DiagnosticTasksApplication,
            wrapped,
        ),
        event_bridge=bridge,
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    reliable = feature.snapshot(workspace)
    assert reliable.last_reliable_inventory is not None
    command = _unavailable_commands(reliable.last_reliable_inventory)[0]

    quarantined = feature.create_diagnostic_task(command)

    assert not quarantined.accepted
    assert quarantined.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.DISCONNECTED_SOURCE
    )
    assert quarantined.task_handle is None
    authoritative = feature.snapshot(workspace)
    assert authoritative.task is not None
    replay = feature.create_diagnostic_task(
        replace(
            command,
            command_id=DiagnosticCommandId(
                "command-62-old-generation-replay"
            ),
        )
    )
    assert (
        replay.disposition
        is DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    )
    assert replay.task_handle is not None
    assert replay.affected_task_id == authoritative.task.task_id
    feature.close()


def test_lost_response_requires_lookup_and_same_key_recovers_acceptance() -> None:
    backend = _LoseFirstCreateResponseDiagnosticsApplication(
        _live_diagnostics_application()
    )
    feature = LiveDiagnosticTasksAdapter(
        application=LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter(
            backend
        ),
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    workspace = DiagnosticTasksContext.workspace()
    feature.snapshot(workspace)
    reliable = feature.snapshot(workspace)
    assert reliable.last_reliable_inventory is not None
    command = _unavailable_commands(reliable.last_reliable_inventory)[0]

    indeterminate = feature.create_diagnostic_task(command)

    assert not indeterminate.accepted
    assert indeterminate.rejection_reason is (
        DiagnosticTaskCommandRejectionReason.DISCONNECTED_SOURCE
    )
    assert indeterminate.task_handle is None
    assert "authoritative task lookup" in indeterminate.message
    assert "same idempotency key" in indeterminate.message

    authoritative = feature.snapshot(workspace)
    assert authoritative.task is not None
    replay = feature.create_diagnostic_task(
        replace(
            command,
            command_id=DiagnosticCommandId(
                "command-62-lost-response-replay"
            ),
        )
    )

    assert (
        replay.disposition
        is DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
    )
    assert replay.task_handle is not None
    assert replay.task_handle.phase is TaskPhase.COMPLETED
    assert replay.affected_task_id == authoritative.task.task_id
    feature.close()
