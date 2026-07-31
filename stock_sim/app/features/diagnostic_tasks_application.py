"""Typed in-process Application Interface for Frontend V2 Diagnostic Tasks."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

from .run_monitoring import (
    DiagnosticTaskId,
    FormalDiagnosticCampaignId,
    StrategyUnderTestId,
    StructuredFeatureError,
    TaskHandle,
    TaskHandleId,
    TaskPhase,
)
from .strategy_diagnostics_v1_read_model import SourceRevisionToken

if TYPE_CHECKING:
    from strategy_diagnostics.application import DiagnosticsApplication
    from strategy_diagnostics.diagnostic_tasks import (
        DiagnosticTaskConfiguration as BackendDiagnosticTaskConfiguration,
    )
    from strategy_diagnostics.diagnostic_tasks import (
        DiagnosticTaskCreationResult as BackendDiagnosticTaskCreationResult,
    )
    from strategy_diagnostics.diagnostic_tasks import (
        DiagnosticTaskSnapshot as BackendDiagnosticTaskSnapshot,
    )
    from strategy_diagnostics.diagnostic_tasks import (
        DiagnosticTaskValidationFinding as BackendDiagnosticTaskValidationFinding,
    )
    from strategy_diagnostics.formal_diagnostic_campaigns import (
        DiagnosticCampaignCase,
    )
    from strategy_diagnostics.market_paths import MaterializedMarketPath
    from strategy_diagnostics.recipes import ApprovedScenarioRecipeVersion


@dataclass(frozen=True, slots=True)
class DiagnosticTasksApplicationVersion:
    major: int
    minor: int

    def render(self) -> str:
        return f"{self.major}.{self.minor}"


DIAGNOSTIC_TASKS_APPLICATION_INTERFACE_VERSION = (
    DiagnosticTasksApplicationVersion(major=1, minor=0)
)


def _require_identity(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} identity cannot be empty")


def _require_positive_revision(value: int, label: str) -> None:
    if not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be positive")


@dataclass(frozen=True, slots=True)
class GuardrailProfileId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Strategy Guardrail Profile")


@dataclass(frozen=True, slots=True)
class ApprovedScenarioRecipeVersionId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Approved Scenario Recipe Version")


@dataclass(frozen=True, slots=True)
class HistoricalMarketSegmentId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Historical Market Segment")


@dataclass(frozen=True, slots=True)
class SourceSnapshotId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Source snapshot")


@dataclass(frozen=True, slots=True)
class MaterializedMarketScenarioId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Materialized Market Scenario")


@dataclass(frozen=True, slots=True)
class CampaignCaseId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Campaign Case")


class DiagnosticCampaignLayer(str, Enum):
    BASELINE = "baseline"
    ISOLATED_SENSITIVITY = "isolated_sensitivity"
    COMPOUND = "compound"


class DiagnosticComparisonRole(str, Enum):
    CONTROL = "control"
    COMPARE_TO_BASELINE = "compare_to_baseline"


class DiagnosticTasksApplicationAvailability(str, Enum):
    READY = "ready"
    EMPTY = "empty"
    INPUT_UNAVAILABLE = "input_unavailable"
    FAILED = "failed"


class DiagnosticTasksApplicationErrorCode(str, Enum):
    INVENTORY_READ_FAILED = "diagnostic_tasks_inventory_read_failed"
    TASK_READ_FAILED = "diagnostic_task_read_failed"
    APPLICATION_NOT_READY = "diagnostic_tasks_application_not_ready"


class DiagnosticTasksApplicationCommandRejectionReason(str, Enum):
    NOT_YET_AVAILABLE = "not_yet_available"
    INVALID_COMMAND = "invalid_command"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    COMMAND_IDENTITY_CONFLICT = "command_identity_conflict"
    PERSISTENCE_FAILURE = "persistence_failure"
    STALE_EXPECTED_REVISION = "stale_expected_revision"
    STALE_VALIDATION = "stale_validation"
    STALE_APPROVAL = "stale_approval"
    VALIDATION_PENDING = "validation_pending"
    VALIDATION_FAILED = "validation_failed"
    UNAVAILABLE_INPUT = "unavailable_input"
    DISCONNECTED_SOURCE = "disconnected_source"
    UNAVAILABLE_CAPABILITY = "unavailable_capability"


class DiagnosticTasksCommandDisposition(str, Enum):
    REJECTED = "rejected"
    SYNCHRONOUS_COMPLETION = "synchronous_completion"
    ASYNCHRONOUS_ACCEPTANCE = "asynchronous_acceptance"
    IDEMPOTENT_REPLAY = "idempotent_replay"


@dataclass(frozen=True, slots=True)
class DiagnosticTasksApplicationError:
    code: DiagnosticTasksApplicationErrorCode
    message: str
    retryable: bool
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class GuardrailThresholdInput:
    metric_name: str
    operator: str
    value: str


@dataclass(frozen=True, slots=True)
class DiagnosticStrategyInput:
    strategy_id: StrategyUnderTestId
    strategy_version: str
    compatibility_surface_version: str
    compatibility_manifest_hash: str
    strategy_module: str
    guardrail_profile_id: GuardrailProfileId
    guardrail_profile_version: str
    guardrail_thresholds: tuple[GuardrailThresholdInput, ...]
    required: bool


@dataclass(frozen=True, slots=True)
class ApprovedScenarioRecipeInput:
    recipe_version_id: ApprovedScenarioRecipeVersionId
    recipe_id: str
    version_number: int
    content_hash: str
    schema_version: str
    transformation_catalog_version: str


@dataclass(frozen=True, slots=True)
class ExecutionPolicyValue:
    name: str
    value: str
    version: str
    source: str


@dataclass(frozen=True, slots=True)
class TransformationParameterValue:
    name: str
    value: str


@dataclass(frozen=True, slots=True)
class AppliedScenarioTransformation:
    transformation_id: str
    family: str
    catalog_version: str
    implementation_version: str
    parameters: tuple[TransformationParameterValue, ...]


@dataclass(frozen=True, slots=True)
class MarketScenarioMaterializationProvenance:
    expander_version: str
    source_resolution: str
    runtime_resolution: str
    reconstructed: bool
    numeric_tolerance: str
    normalization_provenance: str


@dataclass(frozen=True, slots=True)
class DiagnosticCampaignCaseSelection:
    layer: DiagnosticCampaignLayer
    recipe_version_id: ApprovedScenarioRecipeVersionId
    recipe_content_hash: str
    market_scenario_id: MaterializedMarketScenarioId
    campaign_case_id: CampaignCaseId
    comparison_role: DiagnosticComparisonRole
    baseline_campaign_case_id: CampaignCaseId | None
    execution_policy_values: tuple[ExecutionPolicyValue, ...]

    def __post_init__(self) -> None:
        is_control = self.comparison_role is DiagnosticComparisonRole.CONTROL
        if is_control != (self.baseline_campaign_case_id is None):
            raise ValueError(
                "Only a control Campaign Case may omit its baseline comparison"
            )
        if is_control and self.layer is not DiagnosticCampaignLayer.BASELINE:
            raise ValueError("Only a baseline Campaign Case may be the control")
        if (
            not is_control
            and self.baseline_campaign_case_id == self.campaign_case_id
        ):
            raise ValueError("A Campaign Case cannot compare to itself")


@dataclass(frozen=True, slots=True)
class MarketScenarioInput:
    market_scenario_id: MaterializedMarketScenarioId
    campaign_case_id: CampaignCaseId
    layer: DiagnosticCampaignLayer
    recipe_version_id: ApprovedScenarioRecipeVersionId
    recipe_content_hash: str
    historical_segment_id: HistoricalMarketSegmentId
    historical_segment_content_hash: str
    source_snapshot_id: SourceSnapshotId
    materialization_seed: int
    transformation_catalog_version: str
    applied_transformations: tuple[AppliedScenarioTransformation, ...]
    materialization_provenance: MarketScenarioMaterializationProvenance
    market_rule_profile_version: str
    comparison_requirement: str
    execution_policy_values: tuple[ExecutionPolicyValue, ...]


@dataclass(frozen=True, slots=True)
class DiagnosticTasksInventory:
    strategies: tuple[DiagnosticStrategyInput, ...]
    approved_recipes: tuple[ApprovedScenarioRecipeInput, ...]
    market_scenarios: tuple[MarketScenarioInput, ...]


@dataclass(frozen=True, slots=True)
class DiagnosticCommandId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Command")


@dataclass(frozen=True, slots=True)
class DiagnosticCommandIdempotencyKey:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Command idempotency key")


@dataclass(frozen=True, slots=True)
class DiagnosticTaskConfigurationContentId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Diagnostic Task configuration content")


@dataclass(frozen=True, slots=True)
class DiagnosticActorId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Diagnostic actor")


@dataclass(frozen=True, slots=True)
class DiagnosticTaskValidationId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Diagnostic Task validation")


@dataclass(frozen=True, slots=True)
class DiagnosticTaskApprovalId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Diagnostic Task approval")


@dataclass(frozen=True, slots=True)
class DiagnosticPolicyIdentity:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Diagnostic policy")


@dataclass(frozen=True, slots=True)
class CampaignNodeId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Campaign node")


@dataclass(frozen=True, slots=True)
class CampaignAttemptId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Campaign attempt")


@dataclass(frozen=True, slots=True)
class DiagnosticTaskTarget:
    task_id: DiagnosticTaskId


@dataclass(frozen=True, slots=True)
class FormalDiagnosticCampaignTarget:
    campaign_id: FormalDiagnosticCampaignId


@dataclass(frozen=True, slots=True)
class CampaignNodeTarget:
    campaign_node_id: CampaignNodeId


DiagnosticLifecycleTarget = (
    DiagnosticTaskTarget
    | FormalDiagnosticCampaignTarget
    | CampaignNodeTarget
)


@dataclass(frozen=True, slots=True)
class DiagnosticStrategySelection:
    strategy_id: StrategyUnderTestId
    strategy_version: str
    compatibility_manifest_hash: str
    guardrail_profile_id: GuardrailProfileId
    guardrail_profile_version: str


@dataclass(frozen=True, slots=True)
class DiagnosticTaskConfiguration:
    content_identity: DiagnosticTaskConfigurationContentId
    strategy_selections: tuple[DiagnosticStrategySelection, ...]
    campaign_case_selections: tuple[DiagnosticCampaignCaseSelection, ...]

    @classmethod
    def create(
        cls,
        *,
        strategy_selections: tuple[DiagnosticStrategySelection, ...],
        campaign_case_selections: tuple[
            DiagnosticCampaignCaseSelection,
            ...,
        ],
    ) -> DiagnosticTaskConfiguration:
        payload = _diagnostic_task_configuration_payload(
            strategy_selections,
            campaign_case_selections,
        )
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return cls(
            content_identity=DiagnosticTaskConfigurationContentId(
                "sha256:" + hashlib.sha256(encoded).hexdigest()
            ),
            strategy_selections=strategy_selections,
            campaign_case_selections=campaign_case_selections,
        )


@dataclass(frozen=True, slots=True)
class CreateDiagnosticTask:
    command_id: DiagnosticCommandId
    idempotency_key: DiagnosticCommandIdempotencyKey
    configuration: DiagnosticTaskConfiguration


@dataclass(frozen=True, slots=True)
class ReviseDiagnosticTaskConfiguration:
    command_id: DiagnosticCommandId
    idempotency_key: DiagnosticCommandIdempotencyKey
    task_id: DiagnosticTaskId
    expected_revision: int
    configuration: DiagnosticTaskConfiguration

    def __post_init__(self) -> None:
        _require_positive_revision(self.expected_revision, "expected_revision")


@dataclass(frozen=True, slots=True)
class ValidateDiagnosticTaskConfiguration:
    command_id: DiagnosticCommandId
    idempotency_key: DiagnosticCommandIdempotencyKey
    task_id: DiagnosticTaskId
    expected_revision: int

    def __post_init__(self) -> None:
        _require_positive_revision(self.expected_revision, "expected_revision")


@dataclass(frozen=True, slots=True)
class ApproveDiagnosticTaskConfiguration:
    command_id: DiagnosticCommandId
    idempotency_key: DiagnosticCommandIdempotencyKey
    task_id: DiagnosticTaskId
    expected_revision: int
    validation_id: DiagnosticTaskValidationId
    validation_revision: int
    validated_revision: int
    configuration_content_id: DiagnosticTaskConfigurationContentId
    actor_id: DiagnosticActorId

    def __post_init__(self) -> None:
        _require_positive_revision(self.expected_revision, "expected_revision")
        _require_positive_revision(
            self.validation_revision,
            "validation_revision",
        )
        _require_positive_revision(self.validated_revision, "validated_revision")


@dataclass(frozen=True, slots=True)
class StartFormalDiagnosticCampaign:
    command_id: DiagnosticCommandId
    idempotency_key: DiagnosticCommandIdempotencyKey
    task_id: DiagnosticTaskId
    expected_revision: int
    approved_revision: int

    def __post_init__(self) -> None:
        _require_positive_revision(self.expected_revision, "expected_revision")
        _require_positive_revision(self.approved_revision, "approved_revision")


@dataclass(frozen=True, slots=True)
class PauseDiagnosticTarget:
    command_id: DiagnosticCommandId
    idempotency_key: DiagnosticCommandIdempotencyKey
    target: DiagnosticLifecycleTarget
    expected_revision: int

    def __post_init__(self) -> None:
        _require_positive_revision(self.expected_revision, "expected_revision")


@dataclass(frozen=True, slots=True)
class ResumeDiagnosticTarget:
    command_id: DiagnosticCommandId
    idempotency_key: DiagnosticCommandIdempotencyKey
    target: DiagnosticLifecycleTarget
    expected_revision: int

    def __post_init__(self) -> None:
        _require_positive_revision(self.expected_revision, "expected_revision")


@dataclass(frozen=True, slots=True)
class CancelDiagnosticTarget:
    command_id: DiagnosticCommandId
    idempotency_key: DiagnosticCommandIdempotencyKey
    target: DiagnosticLifecycleTarget
    expected_revision: int

    def __post_init__(self) -> None:
        _require_positive_revision(self.expected_revision, "expected_revision")


@dataclass(frozen=True, slots=True)
class RetryFailedCampaignNode:
    command_id: DiagnosticCommandId
    idempotency_key: DiagnosticCommandIdempotencyKey
    task_id: DiagnosticTaskId
    campaign_node_id: CampaignNodeId
    failed_attempt_id: CampaignAttemptId
    expected_revision: int

    def __post_init__(self) -> None:
        _require_positive_revision(self.expected_revision, "expected_revision")


DiagnosticTasksApplicationCommand = (
    CreateDiagnosticTask
    | ReviseDiagnosticTaskConfiguration
    | ValidateDiagnosticTaskConfiguration
    | ApproveDiagnosticTaskConfiguration
    | StartFormalDiagnosticCampaign
    | PauseDiagnosticTarget
    | ResumeDiagnosticTarget
    | CancelDiagnosticTarget
    | RetryFailedCampaignNode
)


@dataclass(frozen=True, slots=True)
class DiagnosticTasksApplicationCommandResult:
    disposition: DiagnosticTasksCommandDisposition
    command_id: DiagnosticCommandId
    idempotency_key: DiagnosticCommandIdempotencyKey
    message: str
    rejection_reason: DiagnosticTasksApplicationCommandRejectionReason | None
    task_handle: TaskHandle | None
    current_revision: int | None
    affected_task_id: DiagnosticTaskId | None
    affected_campaign_id: FormalDiagnosticCampaignId | None
    affected_campaign_node_id: CampaignNodeId | None
    retryable: bool
    correlation_id: str | None

    @property
    def accepted(self) -> bool:
        return self.disposition is not DiagnosticTasksCommandDisposition.REJECTED

    @property
    def task(self) -> TaskHandle | None:
        return self.task_handle


@dataclass(frozen=True, slots=True)
class DiagnosticTasksApplicationInventoryResult:
    availability: DiagnosticTasksApplicationAvailability
    inventory: DiagnosticTasksInventory | None
    source_token: SourceRevisionToken | None
    observed_at: datetime
    error: DiagnosticTasksApplicationError | None


class DiagnosticTasksApplicationTaskLifecycle(str, Enum):
    CREATING = "creating"
    DRAFT = "draft"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"


class DiagnosticTasksApplicationValidationState(str, Enum):
    VALID = "valid"
    INVALID = "invalid"


class DiagnosticTasksApplicationValidationSeverity(str, Enum):
    INFORMATION = "information"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class DiagnosticTasksApplicationConfigurationReference:
    content_identity: DiagnosticTaskConfigurationContentId


@dataclass(frozen=True, slots=True)
class DiagnosticTasksApplicationStrategyReference:
    strategy_id: StrategyUnderTestId


@dataclass(frozen=True, slots=True)
class DiagnosticTasksApplicationCampaignCaseReference:
    campaign_case_id: CampaignCaseId


DiagnosticTasksApplicationValidationReference = (
    DiagnosticTasksApplicationConfigurationReference
    | DiagnosticTasksApplicationStrategyReference
    | DiagnosticTasksApplicationCampaignCaseReference
)


@dataclass(frozen=True, slots=True)
class DiagnosticTasksApplicationValidationFinding:
    reference: DiagnosticTasksApplicationValidationReference
    severity: DiagnosticTasksApplicationValidationSeverity
    code: str
    safe_explanation: str
    retryable: bool
    requires_different_input: bool


@dataclass(frozen=True, slots=True)
class DiagnosticTasksApplicationValidation:
    validation_id: DiagnosticTaskValidationId
    task_handle_id: TaskHandleId
    validation_revision: int
    validated_revision: int
    configuration_content_identity: DiagnosticTaskConfigurationContentId
    state: DiagnosticTasksApplicationValidationState
    findings: tuple[DiagnosticTasksApplicationValidationFinding, ...]
    policy_identities: tuple[DiagnosticPolicyIdentity, ...]


@dataclass(frozen=True, slots=True)
class DiagnosticTasksApplicationApproval:
    approval_id: DiagnosticTaskApprovalId
    approved_revision: int
    configuration_content_identity: DiagnosticTaskConfigurationContentId
    validation_id: DiagnosticTaskValidationId
    validation_revision: int
    actor_identity: DiagnosticActorId
    approved_at: datetime
    policy_identities: tuple[DiagnosticPolicyIdentity, ...]


@dataclass(frozen=True, slots=True)
class DiagnosticTasksApplicationTask:
    task_id: DiagnosticTaskId
    revision: int
    lifecycle: DiagnosticTasksApplicationTaskLifecycle
    configuration: DiagnosticTaskConfiguration
    validation: DiagnosticTasksApplicationValidation | None
    approval: DiagnosticTasksApplicationApproval | None
    task_handles: tuple[TaskHandle, ...]


@dataclass(frozen=True, slots=True)
class DiagnosticTasksApplicationTaskResult:
    availability: DiagnosticTasksApplicationAvailability
    task: DiagnosticTasksApplicationTask | None
    source_token: SourceRevisionToken | None
    observed_at: datetime
    error: DiagnosticTasksApplicationError | None


@runtime_checkable
class StrategyDiagnosticsV1DiagnosticTasksApplication(Protocol):
    @property
    def interface_version(self) -> DiagnosticTasksApplicationVersion: ...

    def read_inventory(self) -> DiagnosticTasksApplicationInventoryResult: ...

    def read_diagnostic_task(
        self,
        task_id: DiagnosticTaskId | None,
    ) -> DiagnosticTasksApplicationTaskResult: ...

    def create_diagnostic_task(
        self,
        command: CreateDiagnosticTask,
    ) -> DiagnosticTasksApplicationCommandResult: ...

    def revise_configuration(
        self,
        command: ReviseDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksApplicationCommandResult: ...

    def validate_configuration(
        self,
        command: ValidateDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksApplicationCommandResult: ...

    def approve_configuration(
        self,
        command: ApproveDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksApplicationCommandResult: ...

    def start_formal_diagnostic_campaign(
        self,
        command: StartFormalDiagnosticCampaign,
    ) -> DiagnosticTasksApplicationCommandResult: ...

    def pause_diagnostic_target(
        self,
        command: PauseDiagnosticTarget,
    ) -> DiagnosticTasksApplicationCommandResult: ...

    def resume_diagnostic_target(
        self,
        command: ResumeDiagnosticTarget,
    ) -> DiagnosticTasksApplicationCommandResult: ...

    def cancel_diagnostic_target(
        self,
        command: CancelDiagnosticTarget,
    ) -> DiagnosticTasksApplicationCommandResult: ...

    def retry_failed_campaign_node(
        self,
        command: RetryFailedCampaignNode,
    ) -> DiagnosticTasksApplicationCommandResult: ...


class LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter:
    """Translate only public DiagnosticsApplication behavior to typed inputs."""

    def __init__(self, application: DiagnosticsApplication) -> None:
        self._application = application

    @property
    def interface_version(self) -> DiagnosticTasksApplicationVersion:
        return DIAGNOSTIC_TASKS_APPLICATION_INTERFACE_VERSION

    def read_inventory(self) -> DiagnosticTasksApplicationInventoryResult:
        observed_at = datetime.now(timezone.utc)
        try:
            inventory = self._read_inventory()
        except RuntimeError:
            return DiagnosticTasksApplicationInventoryResult(
                availability=DiagnosticTasksApplicationAvailability.FAILED,
                inventory=None,
                source_token=None,
                observed_at=observed_at,
                error=DiagnosticTasksApplicationError(
                    code=(
                        DiagnosticTasksApplicationErrorCode.APPLICATION_NOT_READY
                    ),
                    message="Strategy Diagnostics is not ready.",
                    retryable=True,
                ),
            )
        except (KeyError, TypeError, ValueError):
            return DiagnosticTasksApplicationInventoryResult(
                availability=DiagnosticTasksApplicationAvailability.FAILED,
                inventory=None,
                source_token=None,
                observed_at=observed_at,
                error=DiagnosticTasksApplicationError(
                    code=(
                        DiagnosticTasksApplicationErrorCode.INVENTORY_READ_FAILED
                    ),
                    message="Authoritative Diagnostic Tasks inputs are unavailable.",
                    retryable=False,
                ),
            )
        observed_at = datetime.now(timezone.utc)
        return DiagnosticTasksApplicationInventoryResult(
            availability=(
                DiagnosticTasksApplicationAvailability.READY
                if inventory.market_scenarios
                else DiagnosticTasksApplicationAvailability.INPUT_UNAVAILABLE
                if inventory.approved_recipes
                else DiagnosticTasksApplicationAvailability.EMPTY
            ),
            inventory=inventory,
            source_token=_inventory_token(inventory),
            observed_at=observed_at,
            error=None,
        )

    def read_diagnostic_task(
        self,
        task_id: DiagnosticTaskId | None,
    ) -> DiagnosticTasksApplicationTaskResult:
        observed_at = datetime.now(timezone.utc)
        try:
            snapshot = self._application.get_diagnostic_task(
                None if task_id is None else task_id.value
            )
        except RuntimeError:
            return DiagnosticTasksApplicationTaskResult(
                availability=DiagnosticTasksApplicationAvailability.FAILED,
                task=None,
                source_token=None,
                observed_at=observed_at,
                error=DiagnosticTasksApplicationError(
                    code=DiagnosticTasksApplicationErrorCode.APPLICATION_NOT_READY,
                    message="Strategy Diagnostics is not ready.",
                    retryable=True,
                ),
            )
        except (KeyError, TypeError, ValueError):
            return DiagnosticTasksApplicationTaskResult(
                availability=DiagnosticTasksApplicationAvailability.FAILED,
                task=None,
                source_token=None,
                observed_at=observed_at,
                error=DiagnosticTasksApplicationError(
                    code=DiagnosticTasksApplicationErrorCode.TASK_READ_FAILED,
                    message="The authoritative Diagnostic Task could not be read.",
                    retryable=False,
                ),
            )
        if snapshot is None:
            return DiagnosticTasksApplicationTaskResult(
                availability=DiagnosticTasksApplicationAvailability.EMPTY,
                task=None,
                source_token=SourceRevisionToken(
                    hashlib.sha256(b"diagnostic-task:none").hexdigest()
                ),
                observed_at=observed_at,
                error=None,
            )
        task = _map_diagnostic_task(snapshot)
        return DiagnosticTasksApplicationTaskResult(
            availability=DiagnosticTasksApplicationAvailability.READY,
            task=task,
            source_token=_diagnostic_task_token(task),
            observed_at=observed_at,
            error=None,
        )

    def create_diagnostic_task(
        self,
        command: CreateDiagnosticTask,
    ) -> DiagnosticTasksApplicationCommandResult:
        from strategy_diagnostics.diagnostic_tasks import (
            CreateDiagnosticTaskRequest as BackendCreateDiagnosticTaskRequest,
        )
        from strategy_diagnostics.diagnostic_tasks import (
            DiagnosticCampaignCaseSelection as BackendCampaignCaseSelection,
        )
        from strategy_diagnostics.diagnostic_tasks import (
            DiagnosticStrategySelection as BackendStrategySelection,
        )
        from strategy_diagnostics.diagnostic_tasks import (
            DiagnosticTaskConfiguration as BackendTaskConfiguration,
        )

        try:
            result = self._application.create_diagnostic_task(
                BackendCreateDiagnosticTaskRequest(
                    command_id=command.command_id.value,
                    idempotency_key=command.idempotency_key.value,
                    configuration=BackendTaskConfiguration(
                        content_identity=(
                            command.configuration.content_identity.value
                        ),
                        strategy_selections=tuple(
                            BackendStrategySelection(
                                strategy_id=item.strategy_id.value,
                                strategy_version=item.strategy_version,
                                compatibility_manifest_hash=(
                                    item.compatibility_manifest_hash
                                ),
                                guardrail_profile_id=(
                                    item.guardrail_profile_id.value
                                ),
                                guardrail_profile_version=(
                                    item.guardrail_profile_version
                                ),
                            )
                            for item in (
                                command.configuration.strategy_selections
                            )
                        ),
                        campaign_case_selections=tuple(
                            BackendCampaignCaseSelection(
                                layer=item.layer.value,
                                recipe_version_id=(
                                    item.recipe_version_id.value
                                ),
                                recipe_content_hash=item.recipe_content_hash,
                                market_scenario_id=(
                                    item.market_scenario_id.value
                                ),
                                campaign_case_id=(
                                    item.campaign_case_id.value
                                ),
                                comparison_role=item.comparison_role.value,
                                baseline_campaign_case_id=(
                                    None
                                    if item.baseline_campaign_case_id is None
                                    else item.baseline_campaign_case_id.value
                                ),
                                execution_policy_values=tuple(
                                    (
                                        value.name,
                                        value.value,
                                        value.version,
                                        value.source,
                                    )
                                    for value in item.execution_policy_values
                                ),
                            )
                            for item in (
                                command.configuration.campaign_case_selections
                            )
                        ),
                    ),
                )
            )
        except RuntimeError:
            return DiagnosticTasksApplicationCommandResult(
                disposition=DiagnosticTasksCommandDisposition.REJECTED,
                command_id=command.command_id,
                idempotency_key=command.idempotency_key,
                message="Strategy Diagnostics is not ready.",
                rejection_reason=(
                    DiagnosticTasksApplicationCommandRejectionReason.DISCONNECTED_SOURCE
                ),
                task_handle=None,
                current_revision=None,
                affected_task_id=None,
                affected_campaign_id=None,
                affected_campaign_node_id=None,
                retryable=True,
                correlation_id=None,
            )
        return _map_creation_result(result)

    def revise_configuration(
        self,
        command: ReviseDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksApplicationCommandResult:
        from strategy_diagnostics.diagnostic_tasks import (
            ReviseDiagnosticTaskConfigurationRequest,
        )

        try:
            result = self._application.revise_diagnostic_task_configuration(
                ReviseDiagnosticTaskConfigurationRequest(
                    command_id=command.command_id.value,
                    idempotency_key=command.idempotency_key.value,
                    task_id=command.task_id.value,
                    expected_revision=command.expected_revision,
                    configuration=_backend_configuration(
                        command.configuration
                    ),
                )
            )
        except RuntimeError:
            return self._disconnected(command)
        return _map_creation_result(result)

    def validate_configuration(
        self,
        command: ValidateDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksApplicationCommandResult:
        from strategy_diagnostics.diagnostic_tasks import (
            ValidateDiagnosticTaskConfigurationRequest,
        )

        try:
            result = self._application.validate_diagnostic_task_configuration(
                ValidateDiagnosticTaskConfigurationRequest(
                    command_id=command.command_id.value,
                    idempotency_key=command.idempotency_key.value,
                    task_id=command.task_id.value,
                    expected_revision=command.expected_revision,
                )
            )
        except RuntimeError:
            return self._disconnected(command)
        return _map_creation_result(result)

    def approve_configuration(
        self,
        command: ApproveDiagnosticTaskConfiguration,
    ) -> DiagnosticTasksApplicationCommandResult:
        from strategy_diagnostics.diagnostic_tasks import (
            ApproveDiagnosticTaskConfigurationRequest,
        )

        try:
            result = self._application.approve_diagnostic_task_configuration(
                ApproveDiagnosticTaskConfigurationRequest(
                    command_id=command.command_id.value,
                    idempotency_key=command.idempotency_key.value,
                    task_id=command.task_id.value,
                    expected_revision=command.expected_revision,
                    validation_id=command.validation_id.value,
                    validation_revision=command.validation_revision,
                    validated_revision=command.validated_revision,
                    configuration_content_id=(
                        command.configuration_content_id.value
                    ),
                    actor_id=command.actor_id.value,
                )
            )
        except RuntimeError:
            return self._disconnected(command)
        return _map_creation_result(result)

    def start_formal_diagnostic_campaign(
        self,
        command: StartFormalDiagnosticCampaign,
    ) -> DiagnosticTasksApplicationCommandResult:
        return self._not_yet_available(command)

    def pause_diagnostic_target(
        self,
        command: PauseDiagnosticTarget,
    ) -> DiagnosticTasksApplicationCommandResult:
        return self._not_yet_available(command)

    def resume_diagnostic_target(
        self,
        command: ResumeDiagnosticTarget,
    ) -> DiagnosticTasksApplicationCommandResult:
        return self._not_yet_available(command)

    def cancel_diagnostic_target(
        self,
        command: CancelDiagnosticTarget,
    ) -> DiagnosticTasksApplicationCommandResult:
        return self._not_yet_available(command)

    def retry_failed_campaign_node(
        self,
        command: RetryFailedCampaignNode,
    ) -> DiagnosticTasksApplicationCommandResult:
        return self._not_yet_available(command)

    @staticmethod
    def _not_yet_available(
        command: DiagnosticTasksApplicationCommand,
    ) -> DiagnosticTasksApplicationCommandResult:
        return DiagnosticTasksApplicationCommandResult(
            disposition=DiagnosticTasksCommandDisposition.REJECTED,
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            message="This Diagnostic Tasks capability is not yet available.",
            rejection_reason=(
                DiagnosticTasksApplicationCommandRejectionReason.NOT_YET_AVAILABLE
            ),
            task_handle=None,
            current_revision=None,
            affected_task_id=None,
            affected_campaign_id=None,
            affected_campaign_node_id=None,
            retryable=False,
            correlation_id=None,
        )

    @staticmethod
    def _disconnected(
        command: DiagnosticTasksApplicationCommand,
    ) -> DiagnosticTasksApplicationCommandResult:
        return DiagnosticTasksApplicationCommandResult(
            disposition=DiagnosticTasksCommandDisposition.REJECTED,
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            message="Strategy Diagnostics is not ready.",
            rejection_reason=(
                DiagnosticTasksApplicationCommandRejectionReason.DISCONNECTED_SOURCE
            ),
            task_handle=None,
            current_revision=None,
            affected_task_id=None,
            affected_campaign_id=None,
            affected_campaign_node_id=None,
            retryable=True,
            correlation_id=None,
        )

    def _read_inventory(self) -> DiagnosticTasksInventory:
        configuration = self._application.v1_diagnostic_configuration()
        configured_profiles = cast(
            list[Mapping[str, object]],
            configuration["supported_guardrail_profiles"],
        )
        configured_strategies = cast(
            list[Mapping[str, object]],
            configuration["supported_strategies"],
        )
        profiles = {
            str(item["strategy_id"]): item
            for item in configured_profiles
        }
        strategies = tuple(
            _map_strategy(item, profiles[str(item["strategy_id"])])
            for item in configured_strategies
        )
        transformation_catalog_version = str(
            self._application.transformation_catalog_view()["catalog_version"]
        )
        approved = self._application.list_approved_scenario_recipes()
        recipes = tuple(
            _map_recipe(item, transformation_catalog_version)
            for item in approved
        )
        paths = self._application.list_materialized_market_paths()
        approved_by_id = {item.version_id: item for item in approved}
        paths_by_hash = {item.artifact_hash: item for item in paths}
        scenarios = tuple(
            _map_scenario(
                approved_by_id[case.recipe_version_id],
                paths_by_hash[case.materialization_hash],
                case,
            )
            for case in self._application.list_available_diagnostic_campaign_cases()
        )
        return DiagnosticTasksInventory(
            strategies=tuple(
                sorted(strategies, key=lambda item: item.strategy_id.value)
            ),
            approved_recipes=tuple(
                sorted(
                    recipes,
                    key=lambda item: item.recipe_version_id.value,
                )
            ),
            market_scenarios=tuple(
                sorted(
                    scenarios,
                    key=lambda item: (
                        item.layer.value,
                        item.campaign_case_id.value,
                    ),
                )
            ),
        )


def _map_strategy(
    manifest: Mapping[str, object],
    profile: Mapping[str, object],
) -> DiagnosticStrategyInput:
    thresholds = cast(
        tuple[Mapping[str, object], ...],
        profile["thresholds"],
    )
    return DiagnosticStrategyInput(
        strategy_id=StrategyUnderTestId(str(manifest["strategy_id"])),
        strategy_version=str(manifest["strategy_version"]),
        compatibility_surface_version=str(manifest["surface_version"]),
        compatibility_manifest_hash=str(manifest["manifest_content_hash"]),
        strategy_module=str(manifest["strategy_module"]),
        guardrail_profile_id=GuardrailProfileId(str(profile["profile_id"])),
        guardrail_profile_version=str(profile["profile_version"]),
        guardrail_thresholds=tuple(
            GuardrailThresholdInput(
                metric_name=str(threshold["metric_name"]),
                operator=str(threshold["operator"]),
                value=str(threshold["value"]),
            )
            for threshold in thresholds
        ),
        required=True,
    )


def _map_recipe(
    recipe: ApprovedScenarioRecipeVersion,
    transformation_catalog_version: str,
) -> ApprovedScenarioRecipeInput:
    return ApprovedScenarioRecipeInput(
        recipe_version_id=ApprovedScenarioRecipeVersionId(recipe.version_id),
        recipe_id=recipe.recipe_id,
        version_number=recipe.version_number,
        content_hash=recipe.content_hash,
        schema_version=recipe.recipe.schema_version,
        transformation_catalog_version=transformation_catalog_version,
    )


def _map_scenario(
    recipe: ApprovedScenarioRecipeVersion,
    materialized: MaterializedMarketPath,
    case: DiagnosticCampaignCase,
) -> MarketScenarioInput:
    layer = {
        "baseline": DiagnosticCampaignLayer.BASELINE,
        "isolated": DiagnosticCampaignLayer.ISOLATED_SENSITIVITY,
        "compound": DiagnosticCampaignLayer.COMPOUND,
    }[case.layer]
    execution = recipe.recipe.execution_conditions
    values = {
        "allow_partial_fills": str(execution.allow_partial_fills).lower(),
        "commission_bps": str(execution.commission_bps),
        "decision_cadence_minutes": str(
            recipe.recipe.decision_cadence_minutes
        ),
        "latency_nodes": str(execution.latency_nodes),
        "max_fill_fraction": str(execution.max_fill_fraction),
        "slippage_bps": str(execution.slippage_bps),
    }
    return MarketScenarioInput(
        market_scenario_id=MaterializedMarketScenarioId(
            materialized.artifact_hash
        ),
        campaign_case_id=CampaignCaseId(case.case_id),
        layer=layer,
        recipe_version_id=ApprovedScenarioRecipeVersionId(recipe.version_id),
        recipe_content_hash=recipe.content_hash,
        historical_segment_id=HistoricalMarketSegmentId(
            materialized.segment_id
        ),
        historical_segment_content_hash=materialized.segment_content_hash,
        source_snapshot_id=SourceSnapshotId(materialized.source_snapshot_id),
        materialization_seed=materialized.seed,
        transformation_catalog_version=(
            materialized.transformation_catalog_version
        ),
        applied_transformations=tuple(
            AppliedScenarioTransformation(
                transformation_id=item.transformation_id,
                family=item.family,
                catalog_version=item.catalog_version,
                implementation_version=item.implementation_version,
                parameters=tuple(
                    TransformationParameterValue(name=name, value=value)
                    for name, value in item.parameters
                ),
            )
            for item in materialized.applied_transformations
        ),
        materialization_provenance=MarketScenarioMaterializationProvenance(
            expander_version=materialized.expander_version,
            source_resolution=materialized.source_resolution,
            runtime_resolution=materialized.runtime_resolution,
            reconstructed=materialized.reconstructed,
            numeric_tolerance=materialized.numeric_tolerance,
            normalization_provenance=materialized.normalization_provenance,
        ),
        market_rule_profile_version=(
            materialized.market_rule_profile_version
        ),
        comparison_requirement=(
            "control"
            if layer is DiagnosticCampaignLayer.BASELINE
            else "compare_to_baseline"
        ),
        execution_policy_values=tuple(
            ExecutionPolicyValue(
                name=name,
                value=value,
                version=recipe.recipe.schema_version,
                source="Approved Scenario Recipe",
            )
            for name, value in sorted(values.items())
        ),
    )


def _inventory_token(inventory: DiagnosticTasksInventory) -> SourceRevisionToken:
    payload = {
        "strategies": [
            (
                item.strategy_id.value,
                item.strategy_version,
                item.compatibility_manifest_hash,
                item.guardrail_profile_id.value,
            )
            for item in inventory.strategies
        ],
        "recipes": [
            (
                item.recipe_version_id.value,
                item.content_hash,
            )
            for item in inventory.approved_recipes
        ],
        "scenarios": [
            (
                item.campaign_case_id.value,
                item.market_scenario_id.value,
                item.layer.value,
            )
            for item in inventory.market_scenarios
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return SourceRevisionToken(hashlib.sha256(encoded).hexdigest())


def _diagnostic_task_configuration_payload(
    strategy_selections: tuple[DiagnosticStrategySelection, ...],
    campaign_case_selections: tuple[
        DiagnosticCampaignCaseSelection,
        ...,
    ],
) -> dict[str, object]:
    return {
        "campaign_case_selections": [
            {
                "baseline_campaign_case_id": (
                    None
                    if item.baseline_campaign_case_id is None
                    else item.baseline_campaign_case_id.value
                ),
                "campaign_case_id": item.campaign_case_id.value,
                "comparison_role": item.comparison_role.value,
                "execution_policy_values": [
                    {
                        "name": value.name,
                        "source": value.source,
                        "value": value.value,
                        "version": value.version,
                    }
                    for value in sorted(
                        item.execution_policy_values,
                        key=lambda candidate: (
                            candidate.name,
                            candidate.value,
                            candidate.version,
                            candidate.source,
                        ),
                    )
                ],
                "layer": item.layer.value,
                "market_scenario_id": item.market_scenario_id.value,
                "recipe_content_hash": item.recipe_content_hash,
                "recipe_version_id": item.recipe_version_id.value,
            }
            for item in sorted(
                campaign_case_selections,
                key=lambda candidate: (
                    candidate.layer.value,
                    candidate.campaign_case_id.value,
                ),
            )
        ],
        "strategy_selections": [
            {
                "compatibility_manifest_hash": (
                    item.compatibility_manifest_hash
                ),
                "guardrail_profile_id": item.guardrail_profile_id.value,
                "guardrail_profile_version": item.guardrail_profile_version,
                "strategy_id": item.strategy_id.value,
                "strategy_version": item.strategy_version,
            }
            for item in sorted(
                strategy_selections,
                key=lambda candidate: candidate.strategy_id.value,
            )
        ],
    }


def _backend_configuration(
    configuration: DiagnosticTaskConfiguration,
) -> BackendDiagnosticTaskConfiguration:
    from strategy_diagnostics.diagnostic_tasks import (
        DiagnosticCampaignCaseSelection as BackendCampaignCaseSelection,
    )
    from strategy_diagnostics.diagnostic_tasks import (
        DiagnosticStrategySelection as BackendStrategySelection,
    )
    from strategy_diagnostics.diagnostic_tasks import (
        DiagnosticTaskConfiguration as BackendTaskConfiguration,
    )

    return BackendTaskConfiguration(
        content_identity=configuration.content_identity.value,
        strategy_selections=tuple(
            BackendStrategySelection(
                strategy_id=item.strategy_id.value,
                strategy_version=item.strategy_version,
                compatibility_manifest_hash=(
                    item.compatibility_manifest_hash
                ),
                guardrail_profile_id=item.guardrail_profile_id.value,
                guardrail_profile_version=item.guardrail_profile_version,
            )
            for item in configuration.strategy_selections
        ),
        campaign_case_selections=tuple(
            BackendCampaignCaseSelection(
                layer=item.layer.value,
                recipe_version_id=item.recipe_version_id.value,
                recipe_content_hash=item.recipe_content_hash,
                market_scenario_id=item.market_scenario_id.value,
                campaign_case_id=item.campaign_case_id.value,
                comparison_role=item.comparison_role.value,
                baseline_campaign_case_id=(
                    None
                    if item.baseline_campaign_case_id is None
                    else item.baseline_campaign_case_id.value
                ),
                execution_policy_values=tuple(
                    (
                        value.name,
                        value.value,
                        value.version,
                        value.source,
                    )
                    for value in item.execution_policy_values
                ),
            )
            for item in configuration.campaign_case_selections
        ),
    )


def _application_validation_reference(
    finding: BackendDiagnosticTaskValidationFinding,
) -> DiagnosticTasksApplicationValidationReference:
    reference_kind = finding.reference_kind.value
    if reference_kind == "configuration":
        return DiagnosticTasksApplicationConfigurationReference(
            content_identity=DiagnosticTaskConfigurationContentId(
                finding.reference_identity
            )
        )
    if reference_kind == "strategy":
        return DiagnosticTasksApplicationStrategyReference(
            strategy_id=StrategyUnderTestId(finding.reference_identity)
        )
    if reference_kind == "campaign_case":
        return DiagnosticTasksApplicationCampaignCaseReference(
            campaign_case_id=CampaignCaseId(finding.reference_identity)
        )
    raise ValueError("Unsupported Diagnostic Task validation reference")


def _map_diagnostic_task(
    snapshot: BackendDiagnosticTaskSnapshot,
) -> DiagnosticTasksApplicationTask:
    configuration = snapshot.configuration
    task_id = DiagnosticTaskId(snapshot.task_id)
    return DiagnosticTasksApplicationTask(
        task_id=task_id,
        revision=snapshot.revision,
        lifecycle=DiagnosticTasksApplicationTaskLifecycle(
            snapshot.lifecycle.value
        ),
        configuration=DiagnosticTaskConfiguration(
            content_identity=DiagnosticTaskConfigurationContentId(
                configuration.content_identity
            ),
            strategy_selections=tuple(
                DiagnosticStrategySelection(
                    strategy_id=StrategyUnderTestId(item.strategy_id),
                    strategy_version=item.strategy_version,
                    compatibility_manifest_hash=(
                        item.compatibility_manifest_hash
                    ),
                    guardrail_profile_id=GuardrailProfileId(
                        item.guardrail_profile_id
                    ),
                    guardrail_profile_version=item.guardrail_profile_version,
                )
                for item in configuration.strategy_selections
            ),
            campaign_case_selections=tuple(
                DiagnosticCampaignCaseSelection(
                    layer=DiagnosticCampaignLayer(item.layer),
                    recipe_version_id=ApprovedScenarioRecipeVersionId(
                        item.recipe_version_id
                    ),
                    recipe_content_hash=item.recipe_content_hash,
                    market_scenario_id=MaterializedMarketScenarioId(
                        item.market_scenario_id
                    ),
                    campaign_case_id=CampaignCaseId(item.campaign_case_id),
                    comparison_role=DiagnosticComparisonRole(
                        item.comparison_role
                    ),
                    baseline_campaign_case_id=(
                        None
                        if item.baseline_campaign_case_id is None
                        else CampaignCaseId(item.baseline_campaign_case_id)
                    ),
                    execution_policy_values=tuple(
                        ExecutionPolicyValue(
                            name=name,
                            value=value,
                            version=version,
                            source=source,
                        )
                        for name, value, version, source in (
                            item.execution_policy_values
                        )
                    ),
                )
                for item in configuration.campaign_case_selections
            ),
        ),
        validation=(
            None
            if snapshot.validation is None
            else DiagnosticTasksApplicationValidation(
                validation_id=DiagnosticTaskValidationId(
                    snapshot.validation.validation_id
                ),
                task_handle_id=TaskHandleId(
                    snapshot.validation.task_handle_id
                ),
                validation_revision=(
                    snapshot.validation.validation_revision
                ),
                validated_revision=snapshot.validation.task_revision,
                configuration_content_identity=(
                    DiagnosticTaskConfigurationContentId(
                        snapshot.validation.configuration_content_id
                    )
                ),
                state=DiagnosticTasksApplicationValidationState(
                    snapshot.validation.state.value
                ),
                findings=tuple(
                    DiagnosticTasksApplicationValidationFinding(
                        reference=_application_validation_reference(item),
                        severity=(
                            DiagnosticTasksApplicationValidationSeverity(
                                item.severity.value
                            )
                        ),
                        code=item.code,
                        safe_explanation=item.safe_explanation,
                        retryable=item.retryable,
                        requires_different_input=(
                            item.requires_different_input
                        ),
                    )
                    for item in snapshot.validation.findings
                ),
                policy_identities=tuple(
                    DiagnosticPolicyIdentity(item)
                    for item in snapshot.validation.policy_identities
                ),
            )
        ),
        approval=(
            None
            if snapshot.approval is None
            else DiagnosticTasksApplicationApproval(
                approval_id=DiagnosticTaskApprovalId(
                    snapshot.approval.approval_id
                ),
                approved_revision=snapshot.approval.task_revision,
                configuration_content_identity=(
                    DiagnosticTaskConfigurationContentId(
                        snapshot.approval.configuration_content_id
                    )
                ),
                validation_id=DiagnosticTaskValidationId(
                    snapshot.approval.validation_id
                ),
                validation_revision=(
                    snapshot.approval.validation_revision
                ),
                actor_identity=DiagnosticActorId(
                    snapshot.approval.actor_id
                ),
                approved_at=snapshot.approval.approved_at,
                policy_identities=tuple(
                    DiagnosticPolicyIdentity(item)
                    for item in snapshot.approval.policy_identities
                ),
            )
        ),
        task_handles=tuple(
            TaskHandle(
                identity=TaskHandleId(item.task_handle_id),
                target_id=task_id,
                phase=TaskPhase(item.phase.value),
                progress=item.progress,
                result=item.result_code,
                error=(
                    None
                    if item.error_code is None
                    else StructuredFeatureError(
                        code=item.error_code,
                        message=item.error_message or item.error_code,
                        retryable=item.error_retryable,
                    )
                ),
                cancelable=item.cancelable,
            )
            for item in snapshot.task_handles
        ),
    )


def _map_creation_result(
    result: BackendDiagnosticTaskCreationResult,
) -> DiagnosticTasksApplicationCommandResult:
    task_id = (
        None
        if result.affected_task_id is None
        else DiagnosticTaskId(result.affected_task_id)
    )
    handle = result.task_handle
    return DiagnosticTasksApplicationCommandResult(
        disposition=DiagnosticTasksCommandDisposition(
            result.disposition.value
        ),
        command_id=DiagnosticCommandId(result.command_id),
        idempotency_key=DiagnosticCommandIdempotencyKey(
            result.idempotency_key
        ),
        message=result.message,
        rejection_reason=(
            None
            if result.rejection_reason is None
            else DiagnosticTasksApplicationCommandRejectionReason(
                result.rejection_reason.value
            )
        ),
        task_handle=(
            None
            if handle is None or task_id is None
            else TaskHandle(
                identity=TaskHandleId(handle.task_handle_id),
                target_id=task_id,
                phase=TaskPhase(handle.phase.value),
                progress=handle.progress,
                result=handle.result_code,
                error=(
                    None
                    if handle.error_code is None
                    else StructuredFeatureError(
                        code=handle.error_code,
                        message=handle.error_message or handle.error_code,
                        retryable=handle.error_retryable,
                    )
                ),
                cancelable=handle.cancelable,
            )
        ),
        current_revision=result.current_revision,
        affected_task_id=task_id,
        affected_campaign_id=None,
        affected_campaign_node_id=None,
        retryable=result.retryable,
        correlation_id=None,
    )


def _diagnostic_task_token(
    task: DiagnosticTasksApplicationTask,
) -> SourceRevisionToken:
    payload = {
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
            (item.identity.value, item.phase.value, item.progress, item.result)
            for item in task.task_handles
        ],
        "lifecycle": task.lifecycle.value,
        "revision": task.revision,
        "task_id": task.task_id.value,
        "validation": (
            None
            if task.validation is None
            else (
                task.validation.validation_id.value,
                task.validation.validation_revision,
                task.validation.validated_revision,
                task.validation.state.value,
                tuple(item.code for item in task.validation.findings),
            )
        ),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return SourceRevisionToken(hashlib.sha256(encoded).hexdigest())


__all__ = [
    "DIAGNOSTIC_TASKS_APPLICATION_INTERFACE_VERSION",
    "AppliedScenarioTransformation",
    "ApproveDiagnosticTaskConfiguration",
    "ApprovedScenarioRecipeInput",
    "ApprovedScenarioRecipeVersionId",
    "CampaignAttemptId",
    "CampaignCaseId",
    "CampaignNodeId",
    "CampaignNodeTarget",
    "CancelDiagnosticTarget",
    "CreateDiagnosticTask",
    "DiagnosticActorId",
    "DiagnosticCampaignCaseSelection",
    "DiagnosticCampaignLayer",
    "DiagnosticCommandId",
    "DiagnosticCommandIdempotencyKey",
    "DiagnosticComparisonRole",
    "DiagnosticLifecycleTarget",
    "DiagnosticPolicyIdentity",
    "DiagnosticStrategyInput",
    "DiagnosticStrategySelection",
    "DiagnosticTaskApprovalId",
    "DiagnosticTaskConfiguration",
    "DiagnosticTaskConfigurationContentId",
    "DiagnosticTaskTarget",
    "DiagnosticTaskValidationId",
    "DiagnosticTasksApplicationApproval",
    "DiagnosticTasksApplicationAvailability",
    "DiagnosticTasksApplicationCampaignCaseReference",
    "DiagnosticTasksApplicationCommand",
    "DiagnosticTasksApplicationCommandRejectionReason",
    "DiagnosticTasksApplicationCommandResult",
    "DiagnosticTasksApplicationConfigurationReference",
    "DiagnosticTasksApplicationError",
    "DiagnosticTasksApplicationErrorCode",
    "DiagnosticTasksApplicationInventoryResult",
    "DiagnosticTasksApplicationStrategyReference",
    "DiagnosticTasksApplicationTask",
    "DiagnosticTasksApplicationTaskLifecycle",
    "DiagnosticTasksApplicationTaskResult",
    "DiagnosticTasksApplicationValidation",
    "DiagnosticTasksApplicationValidationFinding",
    "DiagnosticTasksApplicationValidationReference",
    "DiagnosticTasksApplicationValidationSeverity",
    "DiagnosticTasksApplicationValidationState",
    "DiagnosticTasksApplicationVersion",
    "DiagnosticTasksCommandDisposition",
    "DiagnosticTasksInventory",
    "ExecutionPolicyValue",
    "FormalDiagnosticCampaignTarget",
    "GuardrailProfileId",
    "GuardrailThresholdInput",
    "HistoricalMarketSegmentId",
    "LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter",
    "MarketScenarioInput",
    "MarketScenarioMaterializationProvenance",
    "MaterializedMarketScenarioId",
    "PauseDiagnosticTarget",
    "ResumeDiagnosticTarget",
    "RetryFailedCampaignNode",
    "ReviseDiagnosticTaskConfiguration",
    "SourceSnapshotId",
    "StartFormalDiagnosticCampaign",
    "StrategyDiagnosticsV1DiagnosticTasksApplication",
    "TransformationParameterValue",
    "ValidateDiagnosticTaskConfiguration",
]
