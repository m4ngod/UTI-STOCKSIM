"""Diagnostic Tasks Feature Interface contract."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Protocol, runtime_checkable

from .diagnostic_tasks_application import (
    ApproveDiagnosticTaskConfiguration,
    CampaignAttemptId,
    CampaignCaseId,
    CampaignNodeId,
    CancelDiagnosticTarget,
    CreateDiagnosticTask,
    DiagnosticActorId,
    DiagnosticCampaignCaseSelection,
    DiagnosticPolicyIdentity,
    DiagnosticTaskApprovalId,
    DiagnosticTaskConfiguration,
    DiagnosticTaskConfigurationContentId,
    DiagnosticTasksApplicationCommand,
    DiagnosticTasksApplicationCommandRejectionReason,
    DiagnosticTasksApplicationCommandResult,
    DiagnosticTasksInventory,
    DiagnosticTaskValidationId,
    MaterializedMarketScenarioId,
    PauseDiagnosticTarget,
    ResumeDiagnosticTarget,
    RetryFailedCampaignNode,
    ReviseDiagnosticTaskConfiguration,
    StartFormalDiagnosticCampaign,
    ValidateDiagnosticTaskConfiguration,
)
from .evidence_and_findings import DiagnosticEvidencePackageId
from .run_monitoring import (
    Completeness,
    DiagnosticTaskId,
    FormalDiagnosticCampaignId,
    Freshness,
    ReproductionManifestId,
    SourceGenerationId,
    SourceKind,
    StrategyRunId,
    StrategyUnderTestId,
    StructuredFeatureError,
    Subscription,
    TaskHandle,
    TaskHandleId,
    ViewPhase,
)
from .versioning import (
    FeatureInterfaceVersion,
)


class DiagnosticTasksPresentationState(str, Enum):
    LOADING = "loading"
    EMPTY = "empty"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"
    INPUT_UNAVAILABLE = "input_unavailable"


class ReproductionManifestAvailability(str, Enum):
    NOT_YET_AVAILABLE = "not_yet_available"
    PARTIAL = "partial"
    FAILED = "failed"
    AVAILABLE = "available"


class DiagnosticTaskLifecycle(str, Enum):
    CREATING = "creating"
    DRAFT = "draft"
    VALIDATING = "validating"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    RESUMING = "resuming"
    CANCELING = "canceling"
    CANCELED = "canceled"
    FAILED = "failed"
    COMPLETED = "completed"


class DiagnosticTaskValidationState(str, Enum):
    NOT_VALIDATED = "not_validated"
    VALIDATING = "validating"
    VALID = "valid"
    INVALID = "invalid"


class DiagnosticTaskValidationSeverity(str, Enum):
    INFORMATION = "information"
    WARNING = "warning"
    ERROR = "error"


class DiagnosticTasksBlockingCode(str, Enum):
    STRATEGY_LIBRARY_NOT_AVAILABLE = "strategy_library_not_available"
    SCENARIO_LAB_NOT_AVAILABLE = "scenario_lab_not_available"
    APPROVED_RECIPE_NOT_AVAILABLE = "approved_recipe_not_available"
    MATERIALIZED_SCENARIO_NOT_AVAILABLE = "materialized_scenario_not_available"
    COMMAND_NOT_YET_AVAILABLE = "not_yet_available"
    INVENTORY_READ_FAILED = "inventory_read_failed"
    SOURCE_DISCONNECTED = "source_disconnected"
    SOURCE_RECONNECTING = "source_reconnecting"


@dataclass(frozen=True, slots=True)
class DiagnosticTasksBlockingReason:
    code: DiagnosticTasksBlockingCode
    message: str
    dependent_operations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DiagnosticTasksCapabilities:
    can_create: bool
    can_revise: bool
    can_validate: bool
    can_approve: bool
    can_start_campaign: bool
    can_pause: bool
    can_resume: bool
    can_cancel: bool
    can_retry_failed_node: bool


@dataclass(frozen=True, slots=True)
class DiagnosticTaskValidationCode:
    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("Diagnostic Task validation code cannot be empty")


@dataclass(frozen=True, slots=True)
class DiagnosticConfigurationContentReference:
    content_identity: DiagnosticTaskConfigurationContentId


@dataclass(frozen=True, slots=True)
class DiagnosticStrategySelectionReference:
    strategy_id: StrategyUnderTestId


@dataclass(frozen=True, slots=True)
class DiagnosticCampaignCaseSelectionReference:
    campaign_case_id: CampaignCaseId


DiagnosticConfigurationFieldReference = (
    DiagnosticConfigurationContentReference
    | DiagnosticStrategySelectionReference
    | DiagnosticCampaignCaseSelectionReference
)


@dataclass(frozen=True, slots=True)
class DiagnosticTaskValidationFinding:
    reference: DiagnosticConfigurationFieldReference
    severity: DiagnosticTaskValidationSeverity
    code: DiagnosticTaskValidationCode
    safe_explanation: str
    retryable: bool
    requires_different_input: bool

    def __post_init__(self) -> None:
        if not isinstance(self.safe_explanation, str) or not self.safe_explanation.strip():
            raise ValueError("Validation finding explanation cannot be empty")


@dataclass(frozen=True, slots=True)
class DiagnosticTaskValidationSummary:
    state: DiagnosticTaskValidationState
    validation_id: DiagnosticTaskValidationId | None
    task_handle_id: TaskHandleId | None
    validation_revision: int | None
    validated_revision: int | None
    configuration_content_identity: DiagnosticTaskConfigurationContentId | None
    findings: tuple[DiagnosticTaskValidationFinding, ...]
    policy_identities: tuple[DiagnosticPolicyIdentity, ...]


@dataclass(frozen=True, slots=True)
class DiagnosticTaskApprovalSummary:
    approval_id: DiagnosticTaskApprovalId
    approved_revision: int
    configuration_content_identity: DiagnosticTaskConfigurationContentId
    validation_id: DiagnosticTaskValidationId
    validation_revision: int
    actor_identity: DiagnosticActorId
    approved_at: datetime
    policy_identities: tuple[DiagnosticPolicyIdentity, ...]


@dataclass(frozen=True, slots=True)
class DiagnosticCampaignRunHandoff:
    run_id: StrategyRunId
    strategy_id: StrategyUnderTestId
    reproduction_manifest_id: ReproductionManifestId | None = None


@dataclass(frozen=True, slots=True)
class DiagnosticCampaignAttemptHandoff:
    attempt_id: CampaignAttemptId
    runs: tuple[DiagnosticCampaignRunHandoff, ...]
    attempt_number: int = 1
    lifecycle: DiagnosticTaskLifecycle = DiagnosticTaskLifecycle.COMPLETED
    predecessor_attempt_id: CampaignAttemptId | None = None
    task_handle_id: TaskHandleId | None = None
    failure: StructuredFeatureError | None = None

    def __post_init__(self) -> None:
        if self.attempt_number < 1:
            raise ValueError("Campaign attempt number must be positive")
        if self.predecessor_attempt_id == self.attempt_id:
            raise ValueError("Campaign attempt cannot be its own predecessor")
        if (
            self.lifecycle is DiagnosticTaskLifecycle.FAILED
            and self.failure is None
        ):
            raise ValueError("Failed Campaign attempt requires a typed failure")
        if (
            self.lifecycle is not DiagnosticTaskLifecycle.FAILED
            and self.failure is not None
        ):
            raise ValueError("Only failed Campaign attempts expose a failure")
        if len(set(self.run_ids)) != len(self.run_ids):
            raise ValueError("Campaign attempt run identities must be unique")
        strategy_ids = tuple(item.strategy_id for item in self.runs)
        if len(set(strategy_ids)) != len(strategy_ids):
            raise ValueError(
                "Campaign attempt Strategy identities must be unique"
            )

    @property
    def run_ids(self) -> tuple[StrategyRunId, ...]:
        return tuple(item.run_id for item in self.runs)


@dataclass(frozen=True, slots=True)
class DiagnosticCampaignNodeHandoff:
    campaign_node_id: CampaignNodeId
    campaign_case_id: CampaignCaseId
    selected_campaign_case_id: CampaignCaseId
    market_scenario_id: MaterializedMarketScenarioId
    attempts: tuple[DiagnosticCampaignAttemptHandoff, ...]
    active_attempt_id: CampaignAttemptId | None
    revision: int = 1
    lifecycle: DiagnosticTaskLifecycle = DiagnosticTaskLifecycle.QUEUED

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ValueError("Campaign node revision must be positive")
        attempt_ids = tuple(item.attempt_id for item in self.attempts)
        if len(set(attempt_ids)) != len(attempt_ids):
            raise ValueError("Campaign node attempt identities must be unique")
        for index, attempt in enumerate(self.attempts, start=1):
            if attempt.attempt_number != index:
                raise ValueError("Campaign node attempt numbers must be contiguous")
            expected_predecessor = (
                None if index == 1 else self.attempts[index - 2].attempt_id
            )
            if attempt.predecessor_attempt_id != expected_predecessor:
                raise ValueError(
                    "Campaign node attempt predecessor history must be contiguous"
                )
        if (
            self.active_attempt_id is not None
            and self.active_attempt_id not in attempt_ids
        ):
            raise ValueError("Active Campaign attempt must be present in history")


@dataclass(frozen=True, slots=True)
class DiagnosticTaskHandoff:
    campaign_id: FormalDiagnosticCampaignId | None
    selected_cases: tuple[DiagnosticCampaignCaseSelection, ...]
    campaign_nodes: tuple[DiagnosticCampaignNodeHandoff, ...]
    evidence_package_id: DiagnosticEvidencePackageId | None
    reproduction_manifest_id: ReproductionManifestId | None
    campaign_revision: int | None = None
    campaign_lifecycle: DiagnosticTaskLifecycle | None = None
    reproduction_manifest_availability: ReproductionManifestAvailability = (
        ReproductionManifestAvailability.NOT_YET_AVAILABLE
    )
    evidence_error: StructuredFeatureError | None = None

    def __post_init__(self) -> None:
        if self.campaign_revision is not None and self.campaign_revision < 1:
            raise ValueError("Formal Campaign revision must be positive")
        if (
            self.campaign_id is None
            and (
                self.campaign_revision is not None
                or self.campaign_lifecycle is not None
            )
        ):
            raise ValueError(
                "Formal Campaign lifecycle requires a Campaign identity"
            )
        selected_by_case = {
            item.campaign_case_id: item for item in self.selected_cases
        }
        if len(selected_by_case) != len(self.selected_cases):
            raise ValueError("Selected Campaign Case identities must be unique")
        if self.campaign_nodes and self.campaign_id is None:
            raise ValueError("Campaign nodes require a Formal Diagnostic Campaign")
        node_ids = tuple(item.campaign_node_id for item in self.campaign_nodes)
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("Campaign node identities must be unique")
        attempt_ids: list[CampaignAttemptId] = []
        run_ids: list[StrategyRunId] = []
        accepted_manifest_ids: list[ReproductionManifestId | None] = []
        historical_manifest_ids: list[ReproductionManifestId | None] = []
        for node in self.campaign_nodes:
            selection = selected_by_case.get(node.selected_campaign_case_id)
            if (
                selection is None
                or selection.market_scenario_id != node.market_scenario_id
            ):
                raise ValueError(
                    "Campaign node must reference its selected Campaign Case "
                    "and Market Scenario"
                )
            for attempt in node.attempts:
                attempt_ids.append(attempt.attempt_id)
                run_ids.extend(attempt.run_ids)
                target = (
                    accepted_manifest_ids
                    if attempt.attempt_id == node.active_attempt_id
                    else historical_manifest_ids
                )
                target.extend(
                    run.reproduction_manifest_id for run in attempt.runs
                )
        if len(set(attempt_ids)) != len(attempt_ids):
            raise ValueError("Campaign attempt identities must be globally unique")
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("Strategy Run identities must be globally unique")
        evidence_present = self.evidence_package_id is not None
        manifest_present = self.reproduction_manifest_id is not None
        error_present = self.evidence_error is not None
        if not error_present and evidence_present != manifest_present:
            raise ValueError(
                "Evidence Package and Reproduction Manifest identities "
                "must become available together"
            )
        if (
            self.reproduction_manifest_availability
            is ReproductionManifestAvailability.NOT_YET_AVAILABLE
        ):
            inferred_availability = (
                ReproductionManifestAvailability.AVAILABLE
                if evidence_present and manifest_present and not error_present
                else (
                    ReproductionManifestAvailability.PARTIAL
                    if evidence_present and not manifest_present and error_present
                    else (
                        ReproductionManifestAvailability.FAILED
                        if not evidence_present
                        and not manifest_present
                        and error_present
                        else self.reproduction_manifest_availability
                    )
                )
            )
            object.__setattr__(
                self,
                "reproduction_manifest_availability",
                inferred_availability,
            )
        expected = {
            ReproductionManifestAvailability.NOT_YET_AVAILABLE: (
                False,
                False,
                False,
            ),
            ReproductionManifestAvailability.PARTIAL: (True, False, True),
            ReproductionManifestAvailability.FAILED: (False, False, True),
            ReproductionManifestAvailability.AVAILABLE: (True, True, False),
        }[self.reproduction_manifest_availability]
        if (evidence_present, manifest_present, error_present) != expected:
            raise ValueError(
                "Evidence handoff availability does not match its identities "
                "and error"
            )
        if evidence_present and self.campaign_id is None:
            raise ValueError(
                "Evidence handoff requires a Formal Diagnostic Campaign"
            )
        if (
            self.reproduction_manifest_availability
            is ReproductionManifestAvailability.AVAILABLE
            and not run_ids
        ):
            raise ValueError(
                "Evidence handoff requires at least one Strategy Run identity"
            )
        if (
            self.reproduction_manifest_availability
            is ReproductionManifestAvailability.AVAILABLE
            and (
                any(item is None for item in accepted_manifest_ids)
                or len(set(accepted_manifest_ids))
                != len(accepted_manifest_ids)
                or self.reproduction_manifest_id
                not in accepted_manifest_ids
                or any(
                    item is not None for item in historical_manifest_ids
                )
            )
        ):
            raise ValueError(
                "Evidence handoff requires one unique Reproduction Manifest "
                "identity for every Strategy Run"
            )
        if (
            self.reproduction_manifest_availability
            is not ReproductionManifestAvailability.AVAILABLE
            and any(
                item is not None
                for item in (
                    *accepted_manifest_ids,
                    *historical_manifest_ids,
                )
            )
        ):
            raise ValueError(
                "Run Manifest identities require an Evidence Package handoff"
            )

    @property
    def ready_for_run_monitoring(self) -> bool:
        return self.campaign_id is not None and any(
            attempt.run_ids
            for node in self.campaign_nodes
            for attempt in node.attempts
        )

    @property
    def ready_for_evidence_and_findings(self) -> bool:
        return (
            self.ready_for_run_monitoring
            and self.reproduction_manifest_availability
            is ReproductionManifestAvailability.AVAILABLE
            and self.evidence_package_id is not None
            and self.reproduction_manifest_id is not None
        )


@dataclass(frozen=True, slots=True)
class DiagnosticTaskPresentation:
    task_id: DiagnosticTaskId
    revision: int
    lifecycle: DiagnosticTaskLifecycle
    configuration: DiagnosticTaskConfiguration
    validation: DiagnosticTaskValidationSummary
    approval: DiagnosticTaskApprovalSummary | None
    task_handles: tuple[TaskHandle, ...]
    capabilities: DiagnosticTasksCapabilities
    handoff: DiagnosticTaskHandoff
    setup_selection_context_identity: str | None = None
    setup_strategy_source_generation: int | None = None
    setup_scenario_selection_context_identity: str | None = None


@dataclass(frozen=True, slots=True)
class DiagnosticTasksContext:
    """Select the workspace inventory or one durable Diagnostic Task."""

    task_id: DiagnosticTaskId | None = None

    @classmethod
    def workspace(cls) -> DiagnosticTasksContext:
        return cls(task_id=None)


@dataclass(frozen=True, slots=True)
class DiagnosticTasksSource:
    kind: SourceKind
    identity: str
    generation: SourceGenerationId


@dataclass(frozen=True, slots=True)
class DiagnosticTasksViewState:
    interface_version: FeatureInterfaceVersion
    revision: int
    observed_at: datetime
    last_reliable_at: datetime | None
    freshness: Freshness
    age: timedelta
    freshness_threshold: timedelta
    source: DiagnosticTasksSource
    context: DiagnosticTasksContext
    phase: ViewPhase
    presentation: DiagnosticTasksPresentationState
    completeness: Completeness
    last_reliable_inventory: DiagnosticTasksInventory | None
    task: DiagnosticTaskPresentation | None
    capabilities: DiagnosticTasksCapabilities
    blocking_reasons: tuple[DiagnosticTasksBlockingReason, ...]
    reproduction_manifest_availability: ReproductionManifestAvailability
    reproduction_manifest_id: ReproductionManifestId | None
    error: StructuredFeatureError | None


DiagnosticTaskCommand = DiagnosticTasksApplicationCommand
DiagnosticTaskCommandRejectionReason = (
    DiagnosticTasksApplicationCommandRejectionReason
)
DiagnosticTasksCommandResult = DiagnosticTasksApplicationCommandResult
DiagnosticTasksObserver = Callable[[DiagnosticTasksViewState], None]


@runtime_checkable
class DiagnosticTasksFeature(Protocol):
    @property
    def interface_version(self) -> FeatureInterfaceVersion: ...

    def snapshot(
        self,
        context: DiagnosticTasksContext,
    ) -> DiagnosticTasksViewState: ...

    def subscribe(
        self,
        context: DiagnosticTasksContext,
        observer: DiagnosticTasksObserver,
    ) -> Subscription: ...

    def create_diagnostic_task(
        self,
        command: CreateDiagnosticTask,
    ) -> DiagnosticTasksCommandResult: ...

    def revise_configuration(
        self,
        command: ReviseDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksCommandResult: ...

    def validate_configuration(
        self,
        command: ValidateDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksCommandResult: ...

    def approve_configuration(
        self,
        command: ApproveDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksCommandResult: ...

    def start_formal_diagnostic_campaign(
        self,
        command: StartFormalDiagnosticCampaign,
    ) -> DiagnosticTasksCommandResult: ...

    def pause_diagnostic_target(
        self,
        command: PauseDiagnosticTarget,
    ) -> DiagnosticTasksCommandResult: ...

    def resume_diagnostic_target(
        self,
        command: ResumeDiagnosticTarget,
    ) -> DiagnosticTasksCommandResult: ...

    def cancel_diagnostic_target(
        self,
        command: CancelDiagnosticTarget,
    ) -> DiagnosticTasksCommandResult: ...

    def retry_failed_campaign_node(
        self,
        command: RetryFailedCampaignNode,
    ) -> DiagnosticTasksCommandResult: ...

    def close(self) -> None: ...


__all__ = [
    "DiagnosticCampaignAttemptHandoff",
    "DiagnosticCampaignCaseSelectionReference",
    "DiagnosticCampaignNodeHandoff",
    "DiagnosticCampaignRunHandoff",
    "DiagnosticConfigurationContentReference",
    "DiagnosticConfigurationFieldReference",
    "DiagnosticStrategySelectionReference",
    "DiagnosticTaskApprovalSummary",
    "DiagnosticTaskCommand",
    "DiagnosticTaskCommandRejectionReason",
    "DiagnosticTaskHandoff",
    "DiagnosticTaskLifecycle",
    "DiagnosticTaskPresentation",
    "DiagnosticTaskValidationCode",
    "DiagnosticTaskValidationFinding",
    "DiagnosticTaskValidationSeverity",
    "DiagnosticTaskValidationState",
    "DiagnosticTaskValidationSummary",
    "DiagnosticTasksBlockingCode",
    "DiagnosticTasksBlockingReason",
    "DiagnosticTasksCapabilities",
    "DiagnosticTasksCommandResult",
    "DiagnosticTasksContext",
    "DiagnosticTasksFeature",
    "DiagnosticTasksObserver",
    "DiagnosticTasksPresentationState",
    "DiagnosticTasksSource",
    "DiagnosticTasksViewState",
    "ReproductionManifestAvailability",
]
