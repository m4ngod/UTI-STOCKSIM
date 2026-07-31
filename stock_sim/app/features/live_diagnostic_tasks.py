"""Live and deterministic fake Adapters for Diagnostic Tasks 1.0."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import RLock

from .diagnostic_tasks import (
    DiagnosticCampaignCaseSelectionReference,
    DiagnosticConfigurationContentReference,
    DiagnosticConfigurationFieldReference,
    DiagnosticStrategySelectionReference,
    DiagnosticTaskApprovalSummary,
    DiagnosticTaskCommandRejectionReason,
    DiagnosticTaskHandoff,
    DiagnosticTaskLifecycle,
    DiagnosticTaskPresentation,
    DiagnosticTasksBlockingCode,
    DiagnosticTasksBlockingReason,
    DiagnosticTasksCapabilities,
    DiagnosticTasksCommandResult,
    DiagnosticTasksContext,
    DiagnosticTasksObserver,
    DiagnosticTasksPresentationState,
    DiagnosticTasksSource,
    DiagnosticTasksViewState,
    DiagnosticTaskValidationCode,
    DiagnosticTaskValidationFinding,
    DiagnosticTaskValidationSeverity,
    DiagnosticTaskValidationState,
    DiagnosticTaskValidationSummary,
    ReproductionManifestAvailability,
)
from .diagnostic_tasks_application import (
    AppliedScenarioTransformation,
    ApproveDiagnosticTaskConfiguration,
    ApprovedScenarioRecipeInput,
    ApprovedScenarioRecipeVersionId,
    CampaignCaseId,
    CancelDiagnosticTarget,
    CreateDiagnosticTask,
    DiagnosticCampaignLayer,
    DiagnosticComparisonRole,
    DiagnosticPolicyIdentity,
    DiagnosticStrategyInput,
    DiagnosticTaskApprovalId,
    DiagnosticTaskConfiguration,
    DiagnosticTasksApplicationAvailability,
    DiagnosticTasksApplicationCampaignCaseReference,
    DiagnosticTasksApplicationCommand,
    DiagnosticTasksApplicationConfigurationReference,
    DiagnosticTasksApplicationError,
    DiagnosticTasksApplicationInventoryResult,
    DiagnosticTasksApplicationStrategyReference,
    DiagnosticTasksApplicationTask,
    DiagnosticTasksApplicationValidationReference,
    DiagnosticTasksCommandDisposition,
    DiagnosticTasksInventory,
    DiagnosticTaskValidationId,
    ExecutionPolicyValue,
    GuardrailProfileId,
    GuardrailThresholdInput,
    HistoricalMarketSegmentId,
    MarketScenarioInput,
    MarketScenarioMaterializationProvenance,
    MaterializedMarketScenarioId,
    PauseDiagnosticTarget,
    ResumeDiagnosticTarget,
    RetryFailedCampaignNode,
    ReviseDiagnosticTaskConfiguration,
    SourceSnapshotId,
    StartFormalDiagnosticCampaign,
    StrategyDiagnosticsV1DiagnosticTasksApplication,
    TransformationParameterValue,
    ValidateDiagnosticTaskConfiguration,
)
from .run_monitoring import (
    Completeness,
    DiagnosticTaskId,
    Freshness,
    SourceGenerationId,
    SourceKind,
    StrategyUnderTestId,
    StructuredFeatureError,
    Subscription,
    TaskHandle,
    TaskHandleId,
    TaskPhase,
    ViewPhase,
)
from .strategy_diagnostics_v1_read_model import SourceRevisionToken
from .versioning import (
    DIAGNOSTIC_TASKS_INTERFACE_VERSION,
    FeatureInterfaceVersion,
)


class _DiagnosticTasksSubscription:
    def __init__(self, dispose: Callable[[], None]) -> None:
        self._dispose = dispose
        self._disposed = False
        self._lock = RLock()

    @property
    def disposed(self) -> bool:
        with self._lock:
            return self._disposed

    def dispose(self) -> None:
        with self._lock:
            if self._disposed:
                return
            self._disposed = True
        self._dispose()

    def mark_disposed(self) -> None:
        with self._lock:
            self._disposed = True


class _UnavailableDiagnosticTasksCommands:
    def create_diagnostic_task(
        self,
        command: CreateDiagnosticTask,
    ) -> DiagnosticTasksCommandResult:
        return self._not_yet_available(command)

    def revise_configuration(
        self,
        command: ReviseDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksCommandResult:
        return self._not_yet_available(command)

    def validate_configuration(
        self,
        command: ValidateDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksCommandResult:
        return self._not_yet_available(command)

    def approve_configuration(
        self,
        command: ApproveDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksCommandResult:
        return self._not_yet_available(command)

    def start_formal_diagnostic_campaign(
        self,
        command: StartFormalDiagnosticCampaign,
    ) -> DiagnosticTasksCommandResult:
        return self._not_yet_available(command)

    def pause_diagnostic_target(
        self,
        command: PauseDiagnosticTarget,
    ) -> DiagnosticTasksCommandResult:
        return self._not_yet_available(command)

    def resume_diagnostic_target(
        self,
        command: ResumeDiagnosticTarget,
    ) -> DiagnosticTasksCommandResult:
        return self._not_yet_available(command)

    def cancel_diagnostic_target(
        self,
        command: CancelDiagnosticTarget,
    ) -> DiagnosticTasksCommandResult:
        return self._not_yet_available(command)

    def retry_failed_campaign_node(
        self,
        command: RetryFailedCampaignNode,
    ) -> DiagnosticTasksCommandResult:
        return self._not_yet_available(command)

    @staticmethod
    def _not_yet_available(
        command: DiagnosticTasksApplicationCommand,
    ) -> DiagnosticTasksCommandResult:
        return DiagnosticTasksCommandResult(
            disposition=DiagnosticTasksCommandDisposition.REJECTED,
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            message="This Diagnostic Tasks capability is not yet available.",
            rejection_reason=(
                DiagnosticTaskCommandRejectionReason.NOT_YET_AVAILABLE
            ),
            task_handle=None,
            current_revision=None,
            affected_task_id=None,
            affected_campaign_id=None,
            affected_campaign_node_id=None,
            retryable=False,
            correlation_id=None,
        )


class LiveDiagnosticTasksAdapter(_UnavailableDiagnosticTasksCommands):
    """Typed Feature Adapter over the Diagnostic Tasks Application Interface."""

    def __init__(
        self,
        *,
        application: StrategyDiagnosticsV1DiagnosticTasksApplication,
        clock: Callable[[], datetime] | None = None,
        freshness_threshold: timedelta = timedelta(seconds=5),
    ) -> None:
        self._application = application
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._freshness_threshold = freshness_threshold
        self._states: dict[DiagnosticTasksContext, DiagnosticTasksViewState] = {}
        self._source_tokens: dict[
            DiagnosticTasksContext,
            SourceRevisionToken,
        ] = {}
        self._subscriptions: dict[
            int,
            tuple[
                DiagnosticTasksContext,
                DiagnosticTasksObserver,
                _DiagnosticTasksSubscription,
            ],
        ] = {}
        self._next_subscription_id = 1
        self._closed = False
        self._lock = RLock()

    @property
    def interface_version(self) -> FeatureInterfaceVersion:
        return DIAGNOSTIC_TASKS_INTERFACE_VERSION

    def snapshot(
        self,
        context: DiagnosticTasksContext,
    ) -> DiagnosticTasksViewState:
        source = DiagnosticTasksSource(
            kind=SourceKind.LIVE_RUNTIME,
            identity="strategy-diagnostics-v1-diagnostic-tasks",
            generation=SourceGenerationId(1),
        )
        with self._lock:
            self._ensure_open()
            current = self._states.get(context)
            current_token = self._source_tokens.get(context)
            if current is None:
                loading = _loading_view_state(
                    context=context,
                    now=_aware(self._clock()),
                    source=source,
                    freshness_threshold=self._freshness_threshold,
                )
                self._states[context] = loading
                return loading
        result = self._application.read_inventory()
        task_result = self._application.read_diagnostic_task(context.task_id)
        if result.error is None and task_result.error is not None:
            result = replace(
                result,
                availability=DiagnosticTasksApplicationAvailability.FAILED,
                source_token=None,
                error=task_result.error,
            )
        elif result.error is None:
            result = replace(
                result,
                source_token=_combined_source_token(
                    result.source_token,
                    task_result.source_token,
                ),
            )
        now = _aware(self._clock())
        state = _next_view_state(
            context=context,
            result=result,
            previous=current,
            previous_token=current_token,
            now=now,
            source=source,
            freshness_threshold=self._freshness_threshold,
        )
        if result.error is None:
            task = (
                None
                if task_result.task is None
                else _task_presentation(task_result.task)
            )
            state = _with_task_state(
                state,
                task=task,
            )
        with self._lock:
            self._ensure_open()
            if current is state:
                return state
            self._states[context] = state
            if result.source_token is not None and result.error is None:
                self._source_tokens[context] = result.source_token
            observers = tuple(
                observer
                for subscribed_context, observer, subscription in (
                    item for item in self._subscriptions.values()
                )
                if subscribed_context == context and not subscription.disposed
            )
        for observer in observers:
            observer(state)
        return state

    def create_diagnostic_task(
        self,
        command: CreateDiagnosticTask,
    ) -> DiagnosticTasksCommandResult:
        with self._lock:
            self._ensure_open()
        return self._application.create_diagnostic_task(command)

    def revise_configuration(
        self,
        command: ReviseDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksCommandResult:
        with self._lock:
            self._ensure_open()
        return self._application.revise_configuration(command)

    def validate_configuration(
        self,
        command: ValidateDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksCommandResult:
        with self._lock:
            self._ensure_open()
        return self._application.validate_configuration(command)

    def approve_configuration(
        self,
        command: ApproveDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksCommandResult:
        with self._lock:
            self._ensure_open()
        return self._application.approve_configuration(command)

    def subscribe(
        self,
        context: DiagnosticTasksContext,
        observer: DiagnosticTasksObserver,
    ) -> Subscription:
        state = self.snapshot(context)
        with self._lock:
            self._ensure_open()
            subscription_id = self._next_subscription_id
            self._next_subscription_id += 1
            subscription = _DiagnosticTasksSubscription(
                lambda: self._remove_subscription(subscription_id)
            )
            self._subscriptions[subscription_id] = (
                context,
                observer,
                subscription,
            )
        observer(state)
        return subscription

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            subscriptions = tuple(
                item[2] for item in self._subscriptions.values()
            )
            self._subscriptions.clear()
        for subscription in subscriptions:
            subscription.mark_disposed()

    def _remove_subscription(self, subscription_id: int) -> None:
        with self._lock:
            self._subscriptions.pop(subscription_id, None)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Diagnostic Tasks Adapter is closed")


class DeterministicFakeDiagnosticTasksAdapter(
    _UnavailableDiagnosticTasksCommands
):
    """Deterministic Adapter exercising the same formal Feature Interface."""

    def __init__(
        self,
        *,
        inventory: DiagnosticTasksInventory | None = None,
        scripted_results: (
            tuple[DiagnosticTasksApplicationInventoryResult, ...] | None
        ) = None,
        clock: Callable[[], datetime] | None = None,
        freshness_threshold: timedelta = timedelta(seconds=5),
    ) -> None:
        if inventory is not None and scripted_results is not None:
            raise ValueError("inventory and scripted_results are mutually exclusive")
        self._clock = clock or (lambda: datetime(2030, 1, 1, tzinfo=timezone.utc))
        self._freshness_threshold = freshness_threshold
        initial_inventory = inventory or _default_inventory()
        self._scripted_results = list(
            scripted_results
            or (
                DiagnosticTasksApplicationInventoryResult(
                    availability=DiagnosticTasksApplicationAvailability.READY,
                    inventory=initial_inventory,
                    source_token=SourceRevisionToken(
                        "0" * 64
                    ),
                    observed_at=_aware(self._clock()),
                    error=None,
                ),
            )
        )
        self._last_scripted_result = self._scripted_results[-1]
        self._states: dict[
            DiagnosticTasksContext,
            DiagnosticTasksViewState,
        ] = {}
        self._source_tokens: dict[
            DiagnosticTasksContext,
            SourceRevisionToken,
        ] = {}
        self._subscriptions: list[
            tuple[
                DiagnosticTasksContext,
                DiagnosticTasksObserver,
                _DiagnosticTasksSubscription,
            ]
        ] = []
        self._tasks: dict[DiagnosticTaskId, DiagnosticTaskPresentation] = {}
        self._latest_task_id: DiagnosticTaskId | None = None
        self._commands_by_id: dict[
            str,
            tuple[str, DiagnosticTasksCommandResult],
        ] = {}
        self._commands_by_key: dict[
            str,
            tuple[str, DiagnosticTasksCommandResult],
        ] = {}
        self._closed = False
        self._lock = RLock()

    @property
    def interface_version(self) -> FeatureInterfaceVersion:
        return DIAGNOSTIC_TASKS_INTERFACE_VERSION

    def snapshot(
        self,
        context: DiagnosticTasksContext,
    ) -> DiagnosticTasksViewState:
        source = DiagnosticTasksSource(
            kind=SourceKind.DETERMINISTIC_FAKE,
            identity="deterministic-diagnostic-tasks",
            generation=SourceGenerationId(1),
        )
        with self._lock:
            self._ensure_open()
            previous = self._states.get(context)
            previous_token = self._source_tokens.get(context)
            if previous is None:
                loading = _loading_view_state(
                    context=context,
                    now=_aware(self._clock()),
                    source=source,
                    freshness_threshold=self._freshness_threshold,
                )
                self._states[context] = loading
                return loading
            if self._scripted_results:
                self._last_scripted_result = self._scripted_results.pop(0)
            result = self._last_scripted_result
            task = self._task_for_context(context)
            result = replace(
                result,
                source_token=_combined_source_token(
                    result.source_token,
                    _fake_task_token(task),
                ),
            )
        state = _next_view_state(
            context=context,
            result=result,
            previous=previous,
            previous_token=previous_token,
            now=_aware(self._clock()),
            source=source,
            freshness_threshold=self._freshness_threshold,
        )
        state = _with_task_state(
            state,
            task=task,
        )
        with self._lock:
            self._ensure_open()
            if state is previous:
                return state
            self._states[context] = state
            if result.source_token is not None and result.error is None:
                self._source_tokens[context] = result.source_token
            observers = tuple(
                observer
                for subscribed_context, observer, subscription in self._subscriptions
                if subscribed_context == context and not subscription.disposed
            )
        for observer in observers:
            observer(state)
        return state

    def create_diagnostic_task(
        self,
        command: CreateDiagnosticTask,
    ) -> DiagnosticTasksCommandResult:
        with self._lock:
            self._ensure_open()
            content_identity = _fake_command_content_identity(
                command.configuration
            )
            command_binding = self._commands_by_id.get(
                command.command_id.value
            )
            key_binding = self._commands_by_key.get(
                command.idempotency_key.value
            )
            if (
                command_binding is not None
                and key_binding is not None
                and command_binding is not key_binding
            ):
                return _fake_rejection(
                    command,
                    DiagnosticTaskCommandRejectionReason.COMMAND_IDENTITY_CONFLICT,
                )
            if (
                command_binding is not None
                and command_binding[1].idempotency_key
                != command.idempotency_key
            ):
                return _fake_rejection(
                    command,
                    DiagnosticTaskCommandRejectionReason.COMMAND_IDENTITY_CONFLICT,
                )
            existing = command_binding or key_binding
            if existing is not None:
                existing_content, existing_result = existing
                if existing_content != content_identity:
                    reason = (
                        DiagnosticTaskCommandRejectionReason.COMMAND_IDENTITY_CONFLICT
                        if command.command_id.value in self._commands_by_id
                        else DiagnosticTaskCommandRejectionReason.IDEMPOTENCY_CONFLICT
                    )
                    return _fake_rejection(command, reason)
                return replace(
                    existing_result,
                    disposition=(
                        DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY
                    ),
                    command_id=command.command_id,
                    idempotency_key=command.idempotency_key,
                    message="Existing Diagnostic Task acceptance replayed.",
                    task_handle=(
                        None
                        if existing_result.affected_task_id is None
                        else self._tasks[
                            existing_result.affected_task_id
                        ].task_handles[0]
                    ),
                    current_revision=2,
                )
            inventory = self._last_scripted_result.inventory
            if not _configuration_matches_inventory(
                command.configuration,
                inventory,
            ):
                return _fake_rejection(
                    command,
                    DiagnosticTaskCommandRejectionReason.INVALID_COMMAND,
                )
            task_id = DiagnosticTaskId(
                _stable_fake_identity(
                    "diagnostic-task",
                    command.command_id.value,
                )
            )
            handle_id = TaskHandleId(
                _stable_fake_identity(
                    "diagnostic-task-handle",
                    command.command_id.value,
                )
            )
            queued = TaskHandle(
                identity=handle_id,
                target_id=task_id,
                phase=TaskPhase.QUEUED,
                progress=0.0,
                result=None,
                error=None,
                cancelable=False,
            )
            completed = replace(
                queued,
                phase=TaskPhase.COMPLETED,
                progress=1.0,
                result="diagnostic_task_created",
            )
            task = DiagnosticTaskPresentation(
                task_id=task_id,
                revision=2,
                lifecycle=DiagnosticTaskLifecycle.DRAFT,
                configuration=command.configuration,
                validation=DiagnosticTaskValidationSummary(
                    state=DiagnosticTaskValidationState.NOT_VALIDATED,
                    validation_id=None,
                    task_handle_id=None,
                    validation_revision=None,
                    validated_revision=None,
                    configuration_content_identity=None,
                    findings=(),
                    policy_identities=(),
                ),
                approval=None,
                task_handles=(completed,),
                capabilities=_CREATE_ONLY_CAPABILITIES,
                handoff=DiagnosticTaskHandoff(
                    campaign_id=None,
                    selected_cases=(
                        command.configuration.campaign_case_selections
                    ),
                    campaign_nodes=(),
                    evidence_package_id=None,
                    reproduction_manifest_id=None,
                ),
            )
            result = DiagnosticTasksCommandResult(
                disposition=(
                    DiagnosticTasksCommandDisposition.ASYNCHRONOUS_ACCEPTANCE
                ),
                command_id=command.command_id,
                idempotency_key=command.idempotency_key,
                message="Diagnostic Task creation accepted.",
                rejection_reason=None,
                task_handle=queued,
                current_revision=1,
                affected_task_id=task_id,
                affected_campaign_id=None,
                affected_campaign_node_id=None,
                retryable=False,
                correlation_id=None,
            )
            self._tasks[task_id] = task
            self._latest_task_id = task_id
            record = (content_identity, result)
            self._commands_by_id[command.command_id.value] = record
            self._commands_by_key[command.idempotency_key.value] = record
            return result

    def revise_configuration(
        self,
        command: ReviseDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksCommandResult:
        with self._lock:
            self._ensure_open()
            content_identity = _fake_mutation_content_identity(command)
            existing = self._fake_existing_result(
                command,
                content_identity,
            )
            if existing is not None:
                return existing
            task = self._tasks.get(command.task_id)
            if task is None:
                return _fake_rejection(
                    command,
                    DiagnosticTaskCommandRejectionReason.INVALID_COMMAND,
                )
            if task.revision != command.expected_revision:
                return _fake_rejection(
                    command,
                    DiagnosticTaskCommandRejectionReason.STALE_EXPECTED_REVISION,
                    current_revision=task.revision,
                    affected_task_id=task.task_id,
                )
            if (
                command.configuration == task.configuration
                or not _configuration_matches_inventory(
                    command.configuration,
                    self._last_scripted_result.inventory,
                )
            ):
                return _fake_rejection(
                    command,
                    DiagnosticTaskCommandRejectionReason.INVALID_COMMAND,
                    current_revision=task.revision,
                    affected_task_id=task.task_id,
                )
            revised = replace(
                task,
                revision=task.revision + 1,
                lifecycle=DiagnosticTaskLifecycle.DRAFT,
                configuration=command.configuration,
                validation=_not_validated_summary(),
                approval=None,
                handoff=replace(
                    task.handoff,
                    selected_cases=(
                        command.configuration.campaign_case_selections
                    ),
                ),
            )
            self._tasks[task.task_id] = revised
            result = DiagnosticTasksCommandResult(
                disposition=(
                    DiagnosticTasksCommandDisposition.SYNCHRONOUS_COMPLETION
                ),
                command_id=command.command_id,
                idempotency_key=command.idempotency_key,
                message="Diagnostic Task configuration revised.",
                rejection_reason=None,
                task_handle=None,
                current_revision=revised.revision,
                affected_task_id=task.task_id,
                affected_campaign_id=None,
                affected_campaign_node_id=None,
                retryable=False,
                correlation_id=None,
            )
            self._store_fake_command(command, content_identity, result)
            return result

    def validate_configuration(
        self,
        command: ValidateDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksCommandResult:
        with self._lock:
            self._ensure_open()
            content_identity = _fake_mutation_content_identity(command)
            existing = self._fake_existing_result(
                command,
                content_identity,
            )
            if existing is not None:
                return existing
            task = self._tasks.get(command.task_id)
            if task is None:
                return _fake_rejection(
                    command,
                    DiagnosticTaskCommandRejectionReason.INVALID_COMMAND,
                )
            if task.revision != command.expected_revision:
                return _fake_rejection(
                    command,
                    DiagnosticTaskCommandRejectionReason.STALE_EXPECTED_REVISION,
                    current_revision=task.revision,
                    affected_task_id=task.task_id,
                )
            findings = _fake_validation_findings(
                task.configuration,
                self._last_scripted_result.inventory,
            )
            valid = not any(
                item.severity is DiagnosticTaskValidationSeverity.ERROR
                for item in findings
            )
            handle_id = TaskHandleId(
                _stable_fake_identity(
                    "diagnostic-task-validation-handle",
                    command.command_id.value,
                )
            )
            queued = TaskHandle(
                identity=handle_id,
                target_id=task.task_id,
                phase=TaskPhase.QUEUED,
                progress=0.0,
                result=None,
                error=None,
                cancelable=False,
            )
            completed = replace(
                queued,
                phase=TaskPhase.COMPLETED,
                progress=1.0,
                result=(
                    "diagnostic_task_configuration_valid"
                    if valid
                    else "diagnostic_task_configuration_invalid"
                ),
            )
            policies = _fake_policy_identities(
                task.configuration,
                self._last_scripted_result.inventory,
            )
            validated = replace(
                task,
                lifecycle=(
                    DiagnosticTaskLifecycle.AWAITING_APPROVAL
                    if valid
                    else DiagnosticTaskLifecycle.DRAFT
                ),
                validation=DiagnosticTaskValidationSummary(
                    state=(
                        DiagnosticTaskValidationState.VALID
                        if valid
                        else DiagnosticTaskValidationState.INVALID
                    ),
                    validation_id=DiagnosticTaskValidationId(
                        _stable_fake_identity(
                            "diagnostic-task-validation",
                            command.command_id.value,
                        )
                    ),
                    task_handle_id=handle_id,
                    validation_revision=1,
                    validated_revision=task.revision,
                    configuration_content_identity=(
                        task.configuration.content_identity
                    ),
                    findings=findings,
                    policy_identities=policies,
                ),
                approval=None,
                task_handles=(*task.task_handles, completed),
            )
            self._tasks[task.task_id] = validated
            result = DiagnosticTasksCommandResult(
                disposition=(
                    DiagnosticTasksCommandDisposition.ASYNCHRONOUS_ACCEPTANCE
                ),
                command_id=command.command_id,
                idempotency_key=command.idempotency_key,
                message="Diagnostic Task validation accepted.",
                rejection_reason=None,
                task_handle=queued,
                current_revision=task.revision,
                affected_task_id=task.task_id,
                affected_campaign_id=None,
                affected_campaign_node_id=None,
                retryable=False,
                correlation_id=None,
            )
            self._store_fake_command(command, content_identity, result)
            return result

    def approve_configuration(
        self,
        command: ApproveDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksCommandResult:
        with self._lock:
            self._ensure_open()
            content_identity = _fake_mutation_content_identity(command)
            existing = self._fake_existing_result(
                command,
                content_identity,
            )
            if existing is not None:
                return existing
            task = self._tasks.get(command.task_id)
            if task is None:
                return _fake_rejection(
                    command,
                    DiagnosticTaskCommandRejectionReason.INVALID_COMMAND,
                )
            if task.revision != command.expected_revision:
                return _fake_rejection(
                    command,
                    DiagnosticTaskCommandRejectionReason.STALE_EXPECTED_REVISION,
                    current_revision=task.revision,
                    affected_task_id=task.task_id,
                )
            validation = task.validation
            if (
                validation.validation_id is None
                or validation.validation_id != command.validation_id
                or validation.validation_revision
                != command.validation_revision
                or validation.validated_revision
                != command.validated_revision
                or validation.configuration_content_identity
                != command.configuration_content_id
                or command.validated_revision != task.revision
                or command.configuration_content_id
                != task.configuration.content_identity
            ):
                return _fake_rejection(
                    command,
                    DiagnosticTaskCommandRejectionReason.STALE_VALIDATION,
                    current_revision=task.revision,
                    affected_task_id=task.task_id,
                )
            validation_handle = next(
                (
                    handle
                    for handle in task.task_handles
                    if handle.identity == validation.task_handle_id
                ),
                None,
            )
            if (
                validation_handle is not None
                and validation_handle.phase is TaskPhase.QUEUED
            ):
                return _fake_rejection(
                    command,
                    DiagnosticTaskCommandRejectionReason.VALIDATION_PENDING,
                    current_revision=task.revision,
                    affected_task_id=task.task_id,
                    retryable=True,
                )
            if (
                validation_handle is None
                or validation_handle.phase is not TaskPhase.COMPLETED
                or (
                    validation.state is DiagnosticTaskValidationState.VALID
                    and validation_handle.result
                    != "diagnostic_task_configuration_valid"
                )
            ):
                return _fake_rejection(
                    command,
                    DiagnosticTaskCommandRejectionReason.STALE_VALIDATION,
                    current_revision=task.revision,
                    affected_task_id=task.task_id,
                )
            if validation.state is not DiagnosticTaskValidationState.VALID:
                return _fake_rejection(
                    command,
                    DiagnosticTaskCommandRejectionReason.VALIDATION_FAILED,
                    current_revision=task.revision,
                    affected_task_id=task.task_id,
                )
            if task.approval is not None:
                return _fake_rejection(
                    command,
                    DiagnosticTaskCommandRejectionReason.STALE_APPROVAL,
                    current_revision=task.revision,
                    affected_task_id=task.task_id,
                )
            approved = replace(
                task,
                lifecycle=DiagnosticTaskLifecycle.APPROVED,
                approval=DiagnosticTaskApprovalSummary(
                    approval_id=DiagnosticTaskApprovalId(
                        _stable_fake_identity(
                            "diagnostic-task-approval",
                            command.command_id.value,
                        )
                    ),
                    approved_revision=task.revision,
                    configuration_content_identity=(
                        task.configuration.content_identity
                    ),
                    validation_id=validation.validation_id,
                    validation_revision=validation.validation_revision or 1,
                    actor_identity=command.actor_id,
                    approved_at=_aware(self._clock()),
                    policy_identities=validation.policy_identities,
                ),
            )
            self._tasks[task.task_id] = approved
            result = DiagnosticTasksCommandResult(
                disposition=(
                    DiagnosticTasksCommandDisposition.SYNCHRONOUS_COMPLETION
                ),
                command_id=command.command_id,
                idempotency_key=command.idempotency_key,
                message="Diagnostic Task configuration approved.",
                rejection_reason=None,
                task_handle=None,
                current_revision=task.revision,
                affected_task_id=task.task_id,
                affected_campaign_id=None,
                affected_campaign_node_id=None,
                retryable=False,
                correlation_id=None,
            )
            self._store_fake_command(command, content_identity, result)
            return result

    def _fake_existing_result(
        self,
        command: DiagnosticTasksApplicationCommand,
        content_identity: str,
    ) -> DiagnosticTasksCommandResult | None:
        command_binding = self._commands_by_id.get(command.command_id.value)
        key_binding = self._commands_by_key.get(command.idempotency_key.value)
        if (
            command_binding is not None
            and key_binding is not None
            and command_binding is not key_binding
        ):
            return _fake_rejection(
                command,
                DiagnosticTaskCommandRejectionReason.COMMAND_IDENTITY_CONFLICT,
            )
        if (
            command_binding is not None
            and command_binding[1].idempotency_key != command.idempotency_key
        ):
            return _fake_rejection(
                command,
                DiagnosticTaskCommandRejectionReason.COMMAND_IDENTITY_CONFLICT,
            )
        existing = command_binding or key_binding
        if existing is None:
            return None
        existing_content, result = existing
        if existing_content != content_identity:
            return _fake_rejection(
                command,
                (
                    DiagnosticTaskCommandRejectionReason.COMMAND_IDENTITY_CONFLICT
                    if command_binding is not None
                    else DiagnosticTaskCommandRejectionReason.IDEMPOTENCY_CONFLICT
                ),
            )
        task = (
            None
            if result.affected_task_id is None
            else self._tasks.get(result.affected_task_id)
        )
        handle = (
            None
            if task is None or result.task_handle is None
            else next(
                (
                    item
                    for item in task.task_handles
                    if item.identity == result.task_handle.identity
                ),
                result.task_handle,
            )
        )
        return replace(
            result,
            disposition=DiagnosticTasksCommandDisposition.IDEMPOTENT_REPLAY,
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            task_handle=handle,
            current_revision=None if task is None else task.revision,
        )

    def _store_fake_command(
        self,
        command: DiagnosticTasksApplicationCommand,
        content_identity: str,
        result: DiagnosticTasksCommandResult,
    ) -> None:
        record = (content_identity, result)
        self._commands_by_id[command.command_id.value] = record
        self._commands_by_key[command.idempotency_key.value] = record

    def subscribe(
        self,
        context: DiagnosticTasksContext,
        observer: DiagnosticTasksObserver,
    ) -> Subscription:
        state = self.snapshot(context)
        subscription = _DiagnosticTasksSubscription(lambda: None)
        with self._lock:
            self._ensure_open()
            self._subscriptions.append((context, observer, subscription))
        observer(state)
        return subscription

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            subscriptions = tuple(item[2] for item in self._subscriptions)
            self._subscriptions.clear()
        for subscription in subscriptions:
            subscription.mark_disposed()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Diagnostic Tasks Adapter is closed")

    def _task_for_context(
        self,
        context: DiagnosticTasksContext,
    ) -> DiagnosticTaskPresentation | None:
        task_id = context.task_id or self._latest_task_id
        return None if task_id is None else self._tasks.get(task_id)


_UNAVAILABLE_CAPABILITIES = DiagnosticTasksCapabilities(
    can_create=False,
    can_revise=False,
    can_validate=False,
    can_approve=False,
    can_start_campaign=False,
    can_pause=False,
    can_resume=False,
    can_cancel=False,
    can_retry_failed_node=False,
)
_CREATE_ONLY_CAPABILITIES = replace(
    _UNAVAILABLE_CAPABILITIES,
    can_create=True,
)
_COMMANDS_NOT_YET_AVAILABLE = DiagnosticTasksBlockingReason(
    code=DiagnosticTasksBlockingCode.COMMAND_NOT_YET_AVAILABLE,
    message=(
        "Start, lifecycle, and retry commands are not_yet_available after "
        "Issue #58."
    ),
    dependent_operations=(
        "start_formal_diagnostic_campaign",
        "pause_diagnostic_target",
        "resume_diagnostic_target",
        "cancel_diagnostic_target",
        "retry_failed_campaign_node",
    ),
)


def _loading_view_state(
    *,
    context: DiagnosticTasksContext,
    now: datetime,
    source: DiagnosticTasksSource,
    freshness_threshold: timedelta,
) -> DiagnosticTasksViewState:
    return DiagnosticTasksViewState(
        interface_version=DIAGNOSTIC_TASKS_INTERFACE_VERSION,
        revision=1,
        observed_at=now,
        last_reliable_at=None,
        freshness=Freshness.AWAITING_FIRST_STATE,
        age=timedelta(0),
        freshness_threshold=freshness_threshold,
        source=source,
        context=context,
        phase=ViewPhase.LOADING,
        presentation=DiagnosticTasksPresentationState.LOADING,
        completeness=Completeness.UNKNOWN,
        last_reliable_inventory=None,
        task=None,
        capabilities=_UNAVAILABLE_CAPABILITIES,
        blocking_reasons=(_COMMANDS_NOT_YET_AVAILABLE,),
        reproduction_manifest_availability=(
            ReproductionManifestAvailability.NOT_YET_AVAILABLE
        ),
        reproduction_manifest_id=None,
        error=None,
    )


def _next_view_state(
    *,
    context: DiagnosticTasksContext,
    result: DiagnosticTasksApplicationInventoryResult,
    previous: DiagnosticTasksViewState | None,
    previous_token: SourceRevisionToken | None,
    now: datetime,
    source: DiagnosticTasksSource,
    freshness_threshold: timedelta,
) -> DiagnosticTasksViewState:
    if result.error is not None:
        return _failed_or_degraded_state(
            context=context,
            error=result.error,
            previous=previous,
            now=now,
            source=source,
            freshness_threshold=freshness_threshold,
        )
    if (
        previous is None
        or result.source_token is None
        or result.source_token != previous_token
    ):
        return _reliable_view_state(
            context=context,
            availability=result.availability,
            inventory=result.inventory,
            observed_at=now,
            revision=1 if previous is None else previous.revision + 1,
            source=source,
            freshness_threshold=freshness_threshold,
        )
    previous_reliable_at = previous.last_reliable_at or previous.observed_at
    result_observed_at = _aware(result.observed_at)
    last_reliable_at = max(previous_reliable_at, result_observed_at)
    age = max(now - last_reliable_at, timedelta(0))
    stale = age > freshness_threshold
    presentation, completeness = _inventory_presentation(
        result.availability,
        previous.last_reliable_inventory,
    )
    error = (
        StructuredFeatureError(
            code="diagnostic_tasks_inventory_stale",
            message=(
                "Diagnostic Tasks inventory is older than its freshness "
                "threshold; showing the last reliable state."
            ),
            retryable=True,
        )
        if stale
        else None
    )
    candidate = replace(
        previous,
        revision=previous.revision + 1,
        observed_at=now,
        last_reliable_at=last_reliable_at,
        freshness=Freshness.STALE if stale else Freshness.FRESH,
        age=age,
        phase=ViewPhase.DEGRADED if stale else ViewPhase.READY,
        presentation=(
            DiagnosticTasksPresentationState.DEGRADED
            if stale
            else presentation
        ),
        completeness=completeness,
        blocking_reasons=_inventory_blocking_reasons(
            previous.last_reliable_inventory
        ),
        error=error,
    )
    if (
        candidate.observed_at == previous.observed_at
        and candidate.freshness is previous.freshness
        and candidate.age == previous.age
        and candidate.phase is previous.phase
        and candidate.presentation is previous.presentation
        and candidate.completeness is previous.completeness
        and candidate.blocking_reasons == previous.blocking_reasons
        and candidate.error == previous.error
    ):
        return previous
    return candidate


def _failed_or_degraded_state(
    *,
    context: DiagnosticTasksContext,
    error: DiagnosticTasksApplicationError,
    previous: DiagnosticTasksViewState | None,
    now: datetime,
    source: DiagnosticTasksSource,
    freshness_threshold: timedelta,
) -> DiagnosticTasksViewState:
    structured_error = StructuredFeatureError(
        code=error.code.value,
        message=error.message,
        retryable=error.retryable,
        correlation_id=error.correlation_id,
    )
    if previous is None or previous.last_reliable_inventory is None:
        return DiagnosticTasksViewState(
            interface_version=DIAGNOSTIC_TASKS_INTERFACE_VERSION,
            revision=1 if previous is None else previous.revision + 1,
            observed_at=now,
            last_reliable_at=None,
            freshness=Freshness.STALE,
            age=timedelta(0),
            freshness_threshold=freshness_threshold,
            source=source,
            context=context,
            phase=ViewPhase.FAILED,
            presentation=DiagnosticTasksPresentationState.FAILED,
            completeness=Completeness.UNKNOWN,
            last_reliable_inventory=None,
            task=None,
            capabilities=_UNAVAILABLE_CAPABILITIES,
            blocking_reasons=(
                DiagnosticTasksBlockingReason(
                    code=DiagnosticTasksBlockingCode.INVENTORY_READ_FAILED,
                    message=error.message,
                    dependent_operations=("read_inventory",),
                ),
                _COMMANDS_NOT_YET_AVAILABLE,
            ),
            reproduction_manifest_availability=(
                ReproductionManifestAvailability.NOT_YET_AVAILABLE
            ),
            reproduction_manifest_id=None,
            error=structured_error,
        )
    last_reliable_at = previous.last_reliable_at or previous.observed_at
    age = max(now - last_reliable_at, timedelta(0))
    return replace(
        previous,
        revision=previous.revision + 1,
        observed_at=now,
        freshness=Freshness.STALE,
        age=age,
        phase=ViewPhase.DEGRADED,
        presentation=DiagnosticTasksPresentationState.DEGRADED,
        blocking_reasons=(
            DiagnosticTasksBlockingReason(
                code=DiagnosticTasksBlockingCode.INVENTORY_READ_FAILED,
                message=error.message,
                dependent_operations=("read_inventory",),
            ),
            *_inventory_blocking_reasons(
                previous.last_reliable_inventory
            ),
        ),
        error=structured_error,
    )


def _reliable_view_state(
    *,
    context: DiagnosticTasksContext,
    availability: DiagnosticTasksApplicationAvailability,
    inventory: DiagnosticTasksInventory | None,
    observed_at: datetime,
    revision: int,
    source: DiagnosticTasksSource,
    freshness_threshold: timedelta,
) -> DiagnosticTasksViewState:
    resolved = inventory or DiagnosticTasksInventory(
        strategies=(),
        approved_recipes=(),
        market_scenarios=(),
    )
    presentation, completeness = _inventory_presentation(
        availability,
        resolved,
    )
    return DiagnosticTasksViewState(
        interface_version=DIAGNOSTIC_TASKS_INTERFACE_VERSION,
        revision=revision,
        observed_at=observed_at,
        last_reliable_at=observed_at,
        freshness=Freshness.FRESH,
        age=timedelta(0),
        freshness_threshold=freshness_threshold,
        source=source,
        context=context,
        phase=ViewPhase.READY,
        presentation=presentation,
        completeness=completeness,
        last_reliable_inventory=resolved,
        task=None,
        capabilities=_UNAVAILABLE_CAPABILITIES,
        blocking_reasons=_inventory_blocking_reasons(resolved),
        reproduction_manifest_availability=(
            ReproductionManifestAvailability.NOT_YET_AVAILABLE
        ),
        reproduction_manifest_id=None,
        error=None,
    )


def _inventory_presentation(
    availability: DiagnosticTasksApplicationAvailability,
    inventory: DiagnosticTasksInventory | None,
) -> tuple[DiagnosticTasksPresentationState, Completeness]:
    if availability is DiagnosticTasksApplicationAvailability.EMPTY:
        return DiagnosticTasksPresentationState.EMPTY, Completeness.EMPTY
    if availability is DiagnosticTasksApplicationAvailability.INPUT_UNAVAILABLE:
        return (
            DiagnosticTasksPresentationState.INPUT_UNAVAILABLE,
            Completeness.PARTIAL,
        )
    if availability is DiagnosticTasksApplicationAvailability.FAILED:
        return DiagnosticTasksPresentationState.FAILED, Completeness.UNKNOWN
    if inventory is None:
        return DiagnosticTasksPresentationState.EMPTY, Completeness.EMPTY
    return DiagnosticTasksPresentationState.READY, Completeness.COMPLETE


def _inventory_blocking_reasons(
    inventory: DiagnosticTasksInventory | None,
) -> tuple[DiagnosticTasksBlockingReason, ...]:
    reasons: list[DiagnosticTasksBlockingReason] = []
    if inventory is None or not inventory.strategies:
        reasons.append(
            DiagnosticTasksBlockingReason(
                code=(
                    DiagnosticTasksBlockingCode.STRATEGY_LIBRARY_NOT_AVAILABLE
                ),
                message=(
                    "Strategy Library inventory is not available; no strategy "
                    "identity is synthesized."
                ),
                dependent_operations=("create_diagnostic_task",),
            )
        )
    if inventory is None or not inventory.approved_recipes:
        reasons.extend(
            (
                DiagnosticTasksBlockingReason(
                    code=(
                        DiagnosticTasksBlockingCode.APPROVED_RECIPE_NOT_AVAILABLE
                    ),
                    message="No backend-approved Scenario Recipe is available.",
                    dependent_operations=("create_diagnostic_task",),
                ),
                DiagnosticTasksBlockingReason(
                    code=DiagnosticTasksBlockingCode.SCENARIO_LAB_NOT_AVAILABLE,
                    message=(
                        "Scenario Lab authoring is outside Wave 2; no recipe "
                        "placeholder is synthesized."
                    ),
                    dependent_operations=("create_diagnostic_task",),
                ),
            )
        )
    if inventory is None or not inventory.market_scenarios:
        reasons.append(
            DiagnosticTasksBlockingReason(
                code=(
                    DiagnosticTasksBlockingCode.MATERIALIZED_SCENARIO_NOT_AVAILABLE
                ),
                message="No immutable materialized Market Scenario is available.",
                dependent_operations=("create_diagnostic_task",),
            )
        )
    elif (
        sum(
            item.layer is DiagnosticCampaignLayer.BASELINE
            for item in inventory.market_scenarios
        )
        != 1
    ):
        reasons.append(
            DiagnosticTasksBlockingReason(
                code=(
                    DiagnosticTasksBlockingCode.MATERIALIZED_SCENARIO_NOT_AVAILABLE
                ),
                message=(
                    "Diagnostic Task creation requires exactly one "
                    "authoritative baseline Market Scenario."
                ),
                dependent_operations=("create_diagnostic_task",),
            )
        )
    reasons.append(_COMMANDS_NOT_YET_AVAILABLE)
    return tuple(reasons)


def _capabilities(
    inventory: DiagnosticTasksInventory | None,
    task: DiagnosticTaskPresentation | None,
) -> DiagnosticTasksCapabilities:
    baseline_count = (
        0
        if inventory is None
        else sum(
            item.layer is DiagnosticCampaignLayer.BASELINE
            for item in inventory.market_scenarios
        )
    )
    if (
        inventory is not None
        and inventory.strategies
        and inventory.approved_recipes
        and inventory.market_scenarios
        and baseline_count == 1
    ):
        capabilities = _CREATE_ONLY_CAPABILITIES
        if task is None:
            return capabilities
        configuration_mutable = task.lifecycle in {
            DiagnosticTaskLifecycle.DRAFT,
            DiagnosticTaskLifecycle.AWAITING_APPROVAL,
            DiagnosticTaskLifecycle.APPROVED,
        }
        validation_handle = next(
            (
                handle
                for handle in task.task_handles
                if handle.identity == task.validation.task_handle_id
            ),
            None,
        )
        return replace(
            capabilities,
            can_revise=configuration_mutable,
            can_validate=configuration_mutable,
            can_approve=(
                task.lifecycle
                is DiagnosticTaskLifecycle.AWAITING_APPROVAL
                and task.validation.state
                is DiagnosticTaskValidationState.VALID
                and task.validation.validated_revision == task.revision
                and task.validation.configuration_content_identity
                == task.configuration.content_identity
                and validation_handle is not None
                and validation_handle.phase is TaskPhase.COMPLETED
                and validation_handle.result
                == "diagnostic_task_configuration_valid"
            ),
        )
    return _UNAVAILABLE_CAPABILITIES


def _with_task_state(
    state: DiagnosticTasksViewState,
    *,
    task: DiagnosticTaskPresentation | None,
) -> DiagnosticTasksViewState:
    capabilities = _capabilities(state.last_reliable_inventory, task)
    presented_task = (
        None
        if task is None
        else replace(task, capabilities=capabilities)
    )
    blocking_reasons = _inventory_blocking_reasons(
        state.last_reliable_inventory
    )
    if (
        state.task == presented_task
        and state.capabilities == capabilities
        and state.blocking_reasons == blocking_reasons
    ):
        return state
    return replace(
        state,
        task=presented_task,
        capabilities=capabilities,
        blocking_reasons=blocking_reasons,
    )


def _task_presentation(
    task: DiagnosticTasksApplicationTask,
) -> DiagnosticTaskPresentation:
    return DiagnosticTaskPresentation(
        task_id=task.task_id,
        revision=task.revision,
        lifecycle=DiagnosticTaskLifecycle(task.lifecycle.value),
        configuration=task.configuration,
        validation=(
            DiagnosticTaskValidationSummary(
                state=DiagnosticTaskValidationState.NOT_VALIDATED,
                validation_id=None,
                task_handle_id=None,
                validation_revision=None,
                validated_revision=None,
                configuration_content_identity=None,
                findings=(),
                policy_identities=(),
            )
            if task.validation is None
            else DiagnosticTaskValidationSummary(
                state=DiagnosticTaskValidationState(
                    task.validation.state.value
                ),
                validation_id=task.validation.validation_id,
                task_handle_id=task.validation.task_handle_id,
                validation_revision=(
                    task.validation.validation_revision
                ),
                validated_revision=task.validation.validated_revision,
                configuration_content_identity=(
                    task.validation.configuration_content_identity
                ),
                findings=tuple(
                    DiagnosticTaskValidationFinding(
                        reference=_validation_reference(
                            finding.reference,
                        ),
                        severity=DiagnosticTaskValidationSeverity(
                            finding.severity.value
                        ),
                        code=DiagnosticTaskValidationCode(finding.code),
                        safe_explanation=finding.safe_explanation,
                        retryable=finding.retryable,
                        requires_different_input=(
                            finding.requires_different_input
                        ),
                    )
                    for finding in task.validation.findings
                ),
                policy_identities=task.validation.policy_identities,
            )
        ),
        approval=(
            None
            if task.approval is None
            else DiagnosticTaskApprovalSummary(
                approval_id=task.approval.approval_id,
                approved_revision=task.approval.approved_revision,
                configuration_content_identity=(
                    task.approval.configuration_content_identity
                ),
                validation_id=task.approval.validation_id,
                validation_revision=task.approval.validation_revision,
                actor_identity=task.approval.actor_identity,
                approved_at=task.approval.approved_at,
                policy_identities=task.approval.policy_identities,
            )
        ),
        task_handles=task.task_handles,
        capabilities=_CREATE_ONLY_CAPABILITIES,
        handoff=DiagnosticTaskHandoff(
            campaign_id=None,
            selected_cases=task.configuration.campaign_case_selections,
            campaign_nodes=(),
            evidence_package_id=None,
            reproduction_manifest_id=None,
        ),
    )


def _validation_reference(
    reference: DiagnosticTasksApplicationValidationReference,
) -> DiagnosticConfigurationFieldReference:
    if isinstance(
        reference,
        DiagnosticTasksApplicationConfigurationReference,
    ):
        return DiagnosticConfigurationContentReference(
            content_identity=reference.content_identity
        )
    if isinstance(reference, DiagnosticTasksApplicationStrategyReference):
        return DiagnosticStrategySelectionReference(
            strategy_id=reference.strategy_id
        )
    if isinstance(
        reference,
        DiagnosticTasksApplicationCampaignCaseReference,
    ):
        return DiagnosticCampaignCaseSelectionReference(
            campaign_case_id=reference.campaign_case_id
        )
    raise TypeError("Unsupported Diagnostic Task validation reference")


def _combined_source_token(
    inventory_token: SourceRevisionToken | None,
    task_token: SourceRevisionToken | None,
) -> SourceRevisionToken | None:
    if inventory_token is None or task_token is None:
        return None
    return SourceRevisionToken(
        hashlib.sha256(
            f"{inventory_token.value}:{task_token.value}".encode()
        ).hexdigest()
    )


def _fake_task_token(
    task: DiagnosticTaskPresentation | None,
) -> SourceRevisionToken:
    payload: object = (
        "diagnostic-task:none"
        if task is None
        else {
            "approval": (
                None
                if task.approval is None
                else (
                    task.approval.approval_id.value,
                    task.approval.approved_revision,
                    task.approval.validation_id.value,
                )
            ),
            "handle_phases": [
                (
                    item.identity.value,
                    item.phase.value,
                    item.progress,
                    item.result,
                )
                for item in task.task_handles
            ],
            "lifecycle": task.lifecycle.value,
            "revision": task.revision,
            "task_id": task.task_id.value,
            "validation": (
                None
                if task.validation.validation_id is None
                else (
                    task.validation.validation_id.value,
                    task.validation.validation_revision,
                    task.validation.validated_revision,
                    task.validation.state.value,
                    tuple(
                        item.code.value
                        for item in task.validation.findings
                    ),
                )
            ),
        }
    )
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return SourceRevisionToken(hashlib.sha256(encoded).hexdigest())


def _configuration_matches_inventory(
    configuration: DiagnosticTaskConfiguration,
    inventory: DiagnosticTasksInventory | None,
) -> bool:
    if inventory is None:
        return False
    if (
        sum(
            item.layer is DiagnosticCampaignLayer.BASELINE
            for item in inventory.market_scenarios
        )
        != 1
    ):
        return False
    calculated = DiagnosticTaskConfiguration.create(
        strategy_selections=configuration.strategy_selections,
        campaign_case_selections=configuration.campaign_case_selections,
    )
    if calculated.content_identity != configuration.content_identity:
        return False
    strategies = {
        (
            item.strategy_id,
            item.strategy_version,
            item.compatibility_manifest_hash,
            item.guardrail_profile_id,
            item.guardrail_profile_version,
        )
        for item in configuration.strategy_selections
    }
    authoritative_strategies = {
        (
            item.strategy_id,
            item.strategy_version,
            item.compatibility_manifest_hash,
            item.guardrail_profile_id,
            item.guardrail_profile_version,
        )
        for item in inventory.strategies
    }
    if (
        len(strategies) != len(configuration.strategy_selections)
        or strategies != authoritative_strategies
    ):
        return False
    recipes = {
        item.recipe_version_id: item for item in inventory.approved_recipes
    }
    authoritative_cases = {
        item.campaign_case_id: item for item in inventory.market_scenarios
    }
    selected_case_ids = tuple(
        item.campaign_case_id
        for item in configuration.campaign_case_selections
    )
    if (
        not selected_case_ids
        or len(set(selected_case_ids)) != len(selected_case_ids)
    ):
        return False
    baseline_case_ids = {
        item.campaign_case_id
        for item in configuration.campaign_case_selections
        if item.layer is DiagnosticCampaignLayer.BASELINE
    }
    if len(baseline_case_ids) != 1:
        return False
    baseline_case_id = next(iter(baseline_case_ids))
    for selection in configuration.campaign_case_selections:
        authoritative = authoritative_cases.get(selection.campaign_case_id)
        recipe = recipes.get(selection.recipe_version_id)
        if (
            authoritative is None
            or recipe is None
            or selection.layer is not authoritative.layer
            or selection.recipe_version_id
            != authoritative.recipe_version_id
            or selection.recipe_content_hash != recipe.content_hash
            or selection.market_scenario_id
            != authoritative.market_scenario_id
        ):
            return False
        selected_policies = {
            item.name: (item.value, item.version, item.source)
            for item in selection.execution_policy_values
        }
        authoritative_policies = {
            item.name: (item.value, item.version, item.source)
            for item in authoritative.execution_policy_values
        }
        if (
            len(selected_policies)
            != len(selection.execution_policy_values)
            or selected_policies != authoritative_policies
        ):
            return False
        is_baseline = selection.layer is DiagnosticCampaignLayer.BASELINE
        if (
            selection.comparison_role
            is not (
                DiagnosticComparisonRole.CONTROL
                if is_baseline
                else DiagnosticComparisonRole.COMPARE_TO_BASELINE
            )
            or selection.baseline_campaign_case_id
            != (None if is_baseline else baseline_case_id)
        ):
            return False
    return True


def _not_validated_summary() -> DiagnosticTaskValidationSummary:
    return DiagnosticTaskValidationSummary(
        state=DiagnosticTaskValidationState.NOT_VALIDATED,
        validation_id=None,
        task_handle_id=None,
        validation_revision=None,
        validated_revision=None,
        configuration_content_identity=None,
        findings=(),
        policy_identities=(),
    )


def _fake_validation_findings(
    configuration: DiagnosticTaskConfiguration,
    inventory: DiagnosticTasksInventory | None,
) -> tuple[DiagnosticTaskValidationFinding, ...]:
    findings: list[DiagnosticTaskValidationFinding] = []
    layers = tuple(
        item.layer for item in configuration.campaign_case_selections
    )
    for layer, code, explanation in (
        (
            DiagnosticCampaignLayer.BASELINE,
            "campaign.layer.baseline_required",
            "Exactly one Baseline Campaign Case is required.",
        ),
        (
            DiagnosticCampaignLayer.ISOLATED_SENSITIVITY,
            "campaign.layer.isolated_sensitivity_required",
            "At least one Isolated Sensitivity Campaign Case is required.",
        ),
        (
            DiagnosticCampaignLayer.COMPOUND,
            "campaign.layer.compound_required",
            "At least one Compound Campaign Case is required.",
        ),
    ):
        count = layers.count(layer)
        invalid = (
            count != 1
            if layer is DiagnosticCampaignLayer.BASELINE
            else count < 1
        )
        if invalid:
            findings.append(
                DiagnosticTaskValidationFinding(
                    reference=DiagnosticConfigurationContentReference(
                        configuration.content_identity
                    ),
                    severity=DiagnosticTaskValidationSeverity.ERROR,
                    code=DiagnosticTaskValidationCode(code),
                    safe_explanation=explanation,
                    retryable=False,
                    requires_different_input=True,
                )
            )
    findings.extend(
        _fake_authority_findings(configuration, inventory)
    )
    return tuple(findings)


def _fake_authority_findings(
    configuration: DiagnosticTaskConfiguration,
    inventory: DiagnosticTasksInventory | None,
) -> tuple[DiagnosticTaskValidationFinding, ...]:
    findings: list[DiagnosticTaskValidationFinding] = []

    def add(
        reference: DiagnosticConfigurationFieldReference,
        code: str,
        explanation: str,
    ) -> None:
        findings.append(
            DiagnosticTaskValidationFinding(
                reference=reference,
                severity=DiagnosticTaskValidationSeverity.ERROR,
                code=DiagnosticTaskValidationCode(code),
                safe_explanation=explanation,
                retryable=False,
                requires_different_input=True,
            )
        )

    configuration_reference = DiagnosticConfigurationContentReference(
        configuration.content_identity
    )
    calculated = DiagnosticTaskConfiguration.create(
        strategy_selections=configuration.strategy_selections,
        campaign_case_selections=configuration.campaign_case_selections,
    )
    if calculated.content_identity != configuration.content_identity:
        add(
            configuration_reference,
            "configuration.content_identity_mismatch",
            "The configuration content identity is not canonical.",
        )
    if inventory is None:
        add(
            configuration_reference,
            "configuration.authoritative_inventory_unavailable",
            "The authoritative Diagnostic Tasks inventory is unavailable.",
        )
        return tuple(findings)

    authoritative_strategies = {
        item.strategy_id: item for item in inventory.strategies
    }
    selected_strategy_ids = tuple(
        item.strategy_id for item in configuration.strategy_selections
    )
    if len(set(selected_strategy_ids)) != len(selected_strategy_ids):
        add(
            configuration_reference,
            "strategy.selection_duplicate",
            "Each authoritative strategy may be selected only once.",
        )
    if set(selected_strategy_ids) != set(authoritative_strategies):
        add(
            configuration_reference,
            "strategy.selection_set_mismatch",
            "The selected strategy set does not match the authoritative inventory.",
        )
    for strategy_selection in configuration.strategy_selections:
        strategy_reference = DiagnosticStrategySelectionReference(
            strategy_selection.strategy_id
        )
        authoritative_strategy = authoritative_strategies.get(
            strategy_selection.strategy_id
        )
        if authoritative_strategy is None:
            add(
                strategy_reference,
                "strategy.identity_unavailable",
                "The selected strategy identity is not authoritative.",
            )
            continue
        if (
            strategy_selection.strategy_version
            != authoritative_strategy.strategy_version
        ):
            add(
                strategy_reference,
                "strategy.version_mismatch",
                "The selected strategy version is not authoritative.",
            )
        if (
            strategy_selection.compatibility_manifest_hash
            != authoritative_strategy.compatibility_manifest_hash
        ):
            add(
                strategy_reference,
                "strategy.compatibility_manifest_mismatch",
                "The compatibility manifest identity does not match.",
            )
        if (
            strategy_selection.guardrail_profile_id
            != authoritative_strategy.guardrail_profile_id
        ):
            add(
                strategy_reference,
                "strategy.guardrail_profile_id_mismatch",
                "The selected guardrail profile identity does not match.",
            )
        if (
            strategy_selection.guardrail_profile_version
            != authoritative_strategy.guardrail_profile_version
        ):
            add(
                strategy_reference,
                "strategy.guardrail_profile_version_mismatch",
                "The selected guardrail profile version does not match.",
            )

    recipes = {
        item.recipe_version_id: item for item in inventory.approved_recipes
    }
    authoritative_cases = {
        item.campaign_case_id: item for item in inventory.market_scenarios
    }
    if (
        sum(
            item.layer is DiagnosticCampaignLayer.BASELINE
            for item in inventory.market_scenarios
        )
        != 1
    ):
        add(
            configuration_reference,
            "campaign.authoritative_baseline_catalog_invalid",
            "The authoritative Campaign Case inventory must contain one baseline.",
        )
    selected_case_ids = tuple(
        item.campaign_case_id
        for item in configuration.campaign_case_selections
    )
    if not selected_case_ids:
        add(
            configuration_reference,
            "campaign.selection_required",
            "At least one authoritative Campaign Case is required.",
        )
    if len(set(selected_case_ids)) != len(selected_case_ids):
        add(
            configuration_reference,
            "campaign.case_selection_duplicate",
            "Each Campaign Case may be selected only once.",
        )
    baseline_case_ids = {
        item.campaign_case_id
        for item in configuration.campaign_case_selections
        if item.layer is DiagnosticCampaignLayer.BASELINE
    }
    baseline_case_id = (
        next(iter(baseline_case_ids))
        if len(baseline_case_ids) == 1
        else None
    )
    if baseline_case_id is None:
        add(
            configuration_reference,
            "campaign.baseline_selection_invalid",
            "Exactly one selected Campaign Case must be the baseline.",
        )
    for case_selection in configuration.campaign_case_selections:
        case_reference = DiagnosticCampaignCaseSelectionReference(
            case_selection.campaign_case_id
        )
        authoritative_case = authoritative_cases.get(
            case_selection.campaign_case_id
        )
        recipe = recipes.get(case_selection.recipe_version_id)
        if authoritative_case is None:
            add(
                case_reference,
                "campaign.case_identity_unavailable",
                "The selected Campaign Case identity is not authoritative.",
            )
        if recipe is None:
            add(
                case_reference,
                "campaign.recipe_version_unavailable",
                "The approved Scenario Recipe version is unavailable.",
            )
        if authoritative_case is not None:
            if (
                case_selection.recipe_version_id
                != authoritative_case.recipe_version_id
            ):
                add(
                    case_reference,
                    "campaign.case_recipe_mismatch",
                    "The Campaign Case is bound to a different recipe version.",
                )
            if (
                case_selection.market_scenario_id
                != authoritative_case.market_scenario_id
            ):
                add(
                    case_reference,
                    "campaign.case_market_scenario_mismatch",
                    "The Campaign Case is bound to a different market scenario.",
                )
            if case_selection.layer is not authoritative_case.layer:
                add(
                    case_reference,
                    "campaign.layer_mismatch",
                    "The Campaign Case layer does not match its authoritative type.",
                )
        if (
            recipe is not None
            and case_selection.recipe_content_hash != recipe.content_hash
        ):
            add(
                case_reference,
                "campaign.recipe_content_hash_mismatch",
                "The approved Scenario Recipe content identity does not match.",
            )
        is_baseline = (
            case_selection.layer is DiagnosticCampaignLayer.BASELINE
        )
        expected_role = (
            DiagnosticComparisonRole.CONTROL
            if is_baseline
            else DiagnosticComparisonRole.COMPARE_TO_BASELINE
        )
        if (
            case_selection.comparison_role is not expected_role
            or case_selection.baseline_campaign_case_id
            != (None if is_baseline else baseline_case_id)
        ):
            add(
                case_reference,
                "campaign.comparison_binding_mismatch",
                "The comparison role or baseline binding does not match.",
            )
        if authoritative_case is None:
            continue
        selected_policies = {
            item.name: (item.value, item.version, item.source)
            for item in case_selection.execution_policy_values
        }
        authoritative_policies = {
            item.name: (item.value, item.version, item.source)
            for item in authoritative_case.execution_policy_values
        }
        if len(selected_policies) != len(
            case_selection.execution_policy_values
        ):
            add(
                case_reference,
                "campaign.execution_policy_duplicate",
                "Execution policy names must be unique.",
            )
        if selected_policies != authoritative_policies:
            add(
                case_reference,
                "campaign.execution_policy_mismatch",
                "Execution policy values or provenance do not match.",
            )
    return tuple(findings)


def _fake_policy_identities(
    configuration: DiagnosticTaskConfiguration,
    inventory: DiagnosticTasksInventory | None,
) -> tuple[DiagnosticPolicyIdentity, ...]:
    del configuration
    identities = {"diagnostic-task-validation-policy.v1"}
    if inventory is not None:
        identities.update(
            "compatibility-surface:" + item.compatibility_surface_version
            for item in inventory.strategies
        )
        identities.update(
            "guardrail-profile:"
            + item.guardrail_profile_id.value
            + "@"
            + item.guardrail_profile_version
            for item in inventory.strategies
        )
        identities.update(
            "scenario-recipe-schema:" + item.schema_version
            for item in inventory.approved_recipes
        )
        identities.update(
            "transformation-catalog:"
            + item.transformation_catalog_version
            for item in inventory.approved_recipes
        )
        identities.update(
            "market-rule-profile:" + item.market_rule_profile_version
            for item in inventory.market_scenarios
        )
    return tuple(
        DiagnosticPolicyIdentity(item) for item in sorted(identities)
    )


def _fake_rejection(
    command: DiagnosticTasksApplicationCommand,
    reason: DiagnosticTaskCommandRejectionReason,
    *,
    current_revision: int | None = None,
    affected_task_id: DiagnosticTaskId | None = None,
    retryable: bool = False,
) -> DiagnosticTasksCommandResult:
    return DiagnosticTasksCommandResult(
        disposition=DiagnosticTasksCommandDisposition.REJECTED,
        command_id=command.command_id,
        idempotency_key=command.idempotency_key,
        message="Diagnostic Task command rejected.",
        rejection_reason=reason,
        task_handle=None,
        current_revision=current_revision,
        affected_task_id=affected_task_id,
        affected_campaign_id=None,
        affected_campaign_node_id=None,
        retryable=retryable,
        correlation_id=None,
    )


def _stable_fake_identity(prefix: str, seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _fake_command_content_identity(
    configuration: DiagnosticTaskConfiguration,
) -> str:
    calculated = DiagnosticTaskConfiguration.create(
        strategy_selections=configuration.strategy_selections,
        campaign_case_selections=configuration.campaign_case_selections,
    ).content_identity.value
    value = f"{configuration.content_identity.value}:{calculated}"
    return hashlib.sha256(value.encode()).hexdigest()


def _fake_mutation_content_identity(
    command: DiagnosticTasksApplicationCommand,
) -> str:
    return hashlib.sha256(
        f"{type(command).__name__}:{command!r}".encode()
    ).hexdigest()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _default_inventory() -> DiagnosticTasksInventory:
    recipe_version_id = ApprovedScenarioRecipeVersionId(
        "scenario-recipe-baseline-v1@1"
    )
    return DiagnosticTasksInventory(
        strategies=(
            DiagnosticStrategyInput(
                strategy_id=StrategyUnderTestId("quentx-scenario-native"),
                strategy_version="1.0",
                compatibility_surface_version="1.0",
                compatibility_manifest_hash="sha256:fake-strategy-manifest",
                strategy_module="strategies.quentx_scenario_native",
                guardrail_profile_id=GuardrailProfileId(
                    "guardrail-profile-fake-quentx"
                ),
                guardrail_profile_version="1.0",
                guardrail_thresholds=(
                    GuardrailThresholdInput(
                        metric_name="max_drawdown",
                        operator="<=",
                        value="0.20",
                    ),
                ),
                required=True,
            ),
        ),
        approved_recipes=(
            ApprovedScenarioRecipeInput(
                recipe_version_id=recipe_version_id,
                recipe_id="scenario-recipe-baseline-v1",
                version_number=1,
                content_hash="sha256:fake-approved-recipe",
                schema_version="1.0",
                transformation_catalog_version="scenario-transformations.v1",
            ),
        ),
        market_scenarios=(
            MarketScenarioInput(
                market_scenario_id=MaterializedMarketScenarioId(
                    "sha256:fake-materialized-market-scenario"
                ),
                campaign_case_id=CampaignCaseId("campaign-case-baseline-v1"),
                layer=DiagnosticCampaignLayer.BASELINE,
                recipe_version_id=recipe_version_id,
                recipe_content_hash="sha256:fake-approved-recipe",
                historical_segment_id=HistoricalMarketSegmentId(
                    "historical-segment-baseline-v1"
                ),
                historical_segment_content_hash=(
                    "sha256:fake-historical-segment"
                ),
                source_snapshot_id=SourceSnapshotId(
                    "source-snapshot-baseline-v1"
                ),
                materialization_seed=1,
                transformation_catalog_version="scenario-transformations.v1",
                applied_transformations=(
                    AppliedScenarioTransformation(
                        transformation_id="baseline.v1",
                        family="baseline",
                        catalog_version="scenario-transformations.v1",
                        implementation_version="1.0",
                        parameters=(
                            TransformationParameterValue(
                                name="mode",
                                value="control",
                            ),
                        ),
                    ),
                ),
                materialization_provenance=(
                    MarketScenarioMaterializationProvenance(
                        expander_version="five-minute-to-thirty-second.v1",
                        source_resolution="5m",
                        runtime_resolution="30s",
                        reconstructed=True,
                        numeric_tolerance="1e-12",
                        normalization_provenance="fixture-normalization.v1",
                    )
                ),
                market_rule_profile_version="market-rules.v1",
                comparison_requirement="control",
                execution_policy_values=(
                    ExecutionPolicyValue(
                        name="allow_partial_fills",
                        value="true",
                        version="1.0",
                        source="Approved Scenario Recipe",
                    ),
                ),
            ),
        ),
    )


__all__ = [
    "DeterministicFakeDiagnosticTasksAdapter",
    "LiveDiagnosticTasksAdapter",
]
