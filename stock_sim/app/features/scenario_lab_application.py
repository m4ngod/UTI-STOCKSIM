"""Typed in-process Application Interface for Scenario Lab 1.0."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from datetime import date, datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ._diagnostics_application_access import (
    shared_diagnostics_application_access_gate,
)
from .diagnostic_tasks_application import (
    ApprovedScenarioRecipeVersionId,
    CampaignCaseId,
    HistoricalMarketSegmentId,
    SourceSnapshotId,
)
from .run_monitoring import (
    ScenarioSetId,
    SourceGenerationId,
    StrategyUnderTestId,
    TaskHandleId,
    TaskPhase,
)
from .strategy_diagnostics_v1_read_model import SourceRevisionToken

if TYPE_CHECKING:
    from strategy_diagnostics.application import (
        DiagnosticsApplication,
        ScenarioLabAdmittedSegment,
        ScenarioLabCampaignCaseAssessment,
        ScenarioLabInventoryReason,
        ScenarioLabPathAssessment,
    )
    from strategy_diagnostics.formal_diagnostic_campaigns import (
        DiagnosticCampaignCase,
    )
    from strategy_diagnostics.historical_segments import HistoricalMarketSegment
    from strategy_diagnostics.market_paths import MaterializedMarketPath


@dataclass(frozen=True, slots=True)
class ScenarioLabApplicationVersion:
    major: int
    minor: int

    def render(self) -> str:
        return f"{self.major}.{self.minor}"


SCENARIO_LAB_APPLICATION_INTERFACE_VERSION = ScenarioLabApplicationVersion(
    major=1,
    minor=0,
)


@dataclass(frozen=True, slots=True)
class ReferenceMarketPathId:
    """Content identity of one immutable Reference Market Path."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("Reference Market Path identity cannot be empty")


class ScenarioLabIntegrityState(str, Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class ScenarioCompatibilityState(str, Enum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    NOT_YET_RESOLVED = "not_yet_resolved"
    UNAVAILABLE = "unavailable"


class ScenarioReproducibilityState(str, Enum):
    REPRODUCIBLE = "reproducible"
    NONREPRODUCIBLE = "nonreproducible"
    NOT_YET_RESOLVED = "not_yet_resolved"
    UNAVAILABLE = "unavailable"


class ScenarioExecutionResolutionState(str, Enum):
    RESOLVED = "resolved"
    NOT_YET_RESOLVED = "not_yet_resolved"
    INCOMPATIBLE = "incompatible"
    UNAVAILABLE = "unavailable"


class MarketScenarioLayer(str, Enum):
    BASELINE = "baseline"
    ISOLATED_SENSITIVITY = "isolated_sensitivity"
    COMPOUND = "compound"


class MarketScenarioComparisonRole(str, Enum):
    CONTROL = "control"
    COMPARE_TO_BASELINE = "compare_to_baseline"


class ScenarioLabAdmissionState(str, Enum):
    ADMITTED = "admitted"
    MISSING = "missing"
    INCOMPLETE = "incomplete"
    UNAVAILABLE = "unavailable"


class ScenarioLabQualityState(str, Enum):
    PASSED = "passed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class ScenarioLabUnavailabilityCode(str, Enum):
    SOURCE_INCOMPLETE = "scenario_lab_source_incomplete"
    PATH_INTEGRITY_FAILED = "reference_path_integrity_failed"
    PATH_RECIPE_INCOMPATIBLE = "reference_path_recipe_incompatible"
    PATH_PROVENANCE_INCOMPLETE = "reference_path_provenance_incomplete"
    NONBASELINE_WITHOUT_BASELINE = "nonbaseline_without_baseline"
    PREVIEW_UNAVAILABLE = "reference_path_preview_unavailable"
    EXECUTION_ASSUMPTIONS_UNRESOLVED = "execution_assumptions_unresolved"


@dataclass(frozen=True, slots=True)
class ScenarioLabUnavailabilityReason:
    code: ScenarioLabUnavailabilityCode
    summary: str
    corrective_guidance: str

    def __post_init__(self) -> None:
        _require_identity(self.summary, "Scenario Lab unavailability summary")
        _require_identity(
            self.corrective_guidance,
            "Scenario Lab corrective guidance",
        )


@dataclass(frozen=True, slots=True)
class HistoricalSegmentProvenance:
    provider: str
    dataset: str
    version: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class HistoricalSegmentEntry:
    segment_id: HistoricalMarketSegmentId
    content_hash: str
    source_snapshot_id: SourceSnapshotId
    source_snapshot_content_hash: str
    provenance: HistoricalSegmentProvenance
    market: str
    start_date: date
    end_date: date
    label: str
    eligible_instrument_count: int
    trading_day_count: int
    bar_count: int
    admission_state: ScenarioLabAdmissionState
    quality_state: ScenarioLabQualityState
    recommendation_tags: tuple[str, ...]
    unavailability_reasons: tuple[ScenarioLabUnavailabilityReason, ...]


@dataclass(frozen=True, slots=True)
class TransformationParameterProjection:
    name: str
    value_type: str
    required: bool
    minimum: str | None
    maximum: str | None
    choices: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TransformationCatalogEntryProjection:
    transformation_id: str
    family: str
    implementation_version: str
    parameters: tuple[TransformationParameterProjection, ...]
    compatibility_rules: tuple[str, ...]
    causality_constraints: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TransformationCatalogProjection:
    catalog_version: str
    entries: tuple[TransformationCatalogEntryProjection, ...]


@dataclass(frozen=True, slots=True)
class AppliedTransformationProjection:
    transformation_id: str
    family: str
    catalog_version: str
    implementation_version: str
    parameters: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ReferencePathPreviewNode:
    instrument: str
    simulation_time: datetime
    open: str
    high: str
    low: str
    close: str
    volume: int
    amount: str
    reconstructed: bool


@dataclass(frozen=True, slots=True)
class ReferencePathPreview:
    at_time: datetime
    eligible_universe: tuple[str, ...]
    nodes: tuple[ReferencePathPreviewNode, ...]
    node_count: int
    bounded_node_limit: int


@dataclass(frozen=True, slots=True)
class ReferenceMarketPathEntry:
    path_id: ReferenceMarketPathId
    segment_id: HistoricalMarketSegmentId
    segment_content_hash: str
    source_snapshot_id: SourceSnapshotId
    seed: int
    expander_version: str
    source_resolution: str
    runtime_resolution: str
    reconstructed: bool
    reconstruction_notice: str
    numeric_tolerance: str
    normalization_provenance: str
    market_rule_profile_version: str
    transformation_catalog_version: str
    transformations: tuple[AppliedTransformationProjection, ...]
    start_time: datetime
    end_time: datetime
    integrity: ScenarioLabIntegrityState
    compatibility: ScenarioCompatibilityState
    reproducibility: ScenarioReproducibilityState
    preview: ReferencePathPreview | None
    unavailability_reasons: tuple[ScenarioLabUnavailabilityReason, ...]


@dataclass(frozen=True, slots=True)
class RequestedExecutionAssumptionsProjection:
    commission_bps: str
    slippage_bps: str
    max_fill_fraction: str
    latency_nodes: int
    allow_partial_fills: bool


@dataclass(frozen=True, slots=True)
class MarketScenarioTransformationProjection:
    transformation_id: str
    family: str
    implementation_version: str
    parameters: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class MarketScenarioEntry:
    scenario_id: CampaignCaseId
    layer: MarketScenarioLayer
    comparison_role: MarketScenarioComparisonRole
    baseline_scenario_id: CampaignCaseId | None
    recipe_version_id: ApprovedScenarioRecipeVersionId
    recipe_content_hash: str
    path_id: ReferenceMarketPathId
    segment_id: HistoricalMarketSegmentId
    segment_content_hash: str
    source_snapshot_id: SourceSnapshotId
    seed: int
    transformation_catalog_version: str
    transformations: tuple[MarketScenarioTransformationProjection, ...]
    market_rule_profile_version: str
    decision_cadence_minutes: int
    requested_execution_assumptions: RequestedExecutionAssumptionsProjection
    compatibility: ScenarioCompatibilityState
    reproducibility: ScenarioReproducibilityState
    execution_resolution: ScenarioExecutionResolutionState
    unavailability_reasons: tuple[ScenarioLabUnavailabilityReason, ...]


@dataclass(frozen=True, slots=True)
class ScenarioLabInventory:
    historical_segments: tuple[HistoricalSegmentEntry, ...]
    reference_paths: tuple[ReferenceMarketPathEntry, ...]
    market_scenarios: tuple[MarketScenarioEntry, ...]
    transformation_catalog: TransformationCatalogProjection


class ScenarioLabApplicationAvailability(str, Enum):
    READY = "ready"
    EMPTY = "empty"
    PARTIAL = "partial"
    FAILED = "failed"


class ScenarioLabApplicationErrorCode(str, Enum):
    INVENTORY_READ_FAILED = "scenario_lab_inventory_read_failed"
    APPLICATION_NOT_READY = "scenario_lab_application_not_ready"
    PATH_INTEGRITY_FAILED = "reference_market_path_integrity_failed"


@dataclass(frozen=True, slots=True)
class ScenarioLabApplicationError:
    code: ScenarioLabApplicationErrorCode
    message: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class ScenarioLabApplicationInventoryResult:
    availability: ScenarioLabApplicationAvailability
    inventory: ScenarioLabInventory | None
    source_token: SourceRevisionToken | None
    observed_at: datetime
    error: ScenarioLabApplicationError | None


class ScenarioLabCommandDisposition(str, Enum):
    ACCEPTED = "accepted"
    UNAVAILABLE = "unavailable"
    CONFLICT = "conflict"
    REJECTED = "rejected"


class ScenarioLabTaskOperation(str, Enum):
    CREATE_RECIPE_DRAFT = "create_recipe_draft"
    REVISE_RECIPE_DRAFT = "revise_recipe_draft"
    VALIDATE_RECIPE_DRAFT = "validate_recipe_draft"
    APPROVE_RECIPE = "approve_recipe"
    MATERIALIZE_REFERENCE_PATH = "materialize_reference_path"
    RETRY_MATERIALIZATION = "retry_materialization"
    COMPOSE_SCENARIO_SET = "compose_scenario_set"
    RESOLVE_EXECUTION_ASSUMPTIONS = "resolve_execution_assumptions"
    SELECT_FORMAL_SCENARIO_SET = "select_formal_scenario_set"


def _require_identity(value: str, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} cannot be empty")


@dataclass(frozen=True, slots=True)
class ScenarioLabCommandId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Scenario Lab command identity")


@dataclass(frozen=True, slots=True)
class ScenarioLabIdempotencyIdentity:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Scenario Lab idempotency identity")


@dataclass(frozen=True, slots=True)
class ScenarioLabCommandContentIdentity:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Scenario Lab command content identity")


@dataclass(frozen=True, slots=True)
class ScenarioLabActorId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Scenario Lab actor identity")


@dataclass(frozen=True, slots=True)
class ScenarioRecipeDraftId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Scenario Recipe Draft identity")


@dataclass(frozen=True, slots=True)
class ScenarioRecipeValidationId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Scenario Recipe validation identity")


@dataclass(frozen=True, slots=True)
class ScenarioMaterializationAttemptId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Scenario materialization attempt identity")


@dataclass(frozen=True, slots=True)
class ScenarioExecutionResolutionId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Scenario execution resolution identity")


@dataclass(frozen=True, slots=True)
class ScenarioSelectionContextId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Scenario selection context identity")


@dataclass(frozen=True, slots=True)
class ScenarioLabCommandMetadata:
    command_id: ScenarioLabCommandId
    idempotency_identity: ScenarioLabIdempotencyIdentity
    canonical_content_identity: ScenarioLabCommandContentIdentity
    expected_source_revision: SourceRevisionToken
    expected_source_generation: SourceGenerationId


class ScenarioRecipeAuthoringMode(str, Enum):
    MANUAL = "manual"
    AI_ASSISTED = "ai_assisted"


class ScenarioRecipeDataPolicy(str, Enum):
    POINT_IN_TIME = "point_in_time"


class ScenarioRecipeParameterKind(str, Enum):
    BOOLEAN = "boolean"
    INTEGER = "integer"
    DECIMAL = "decimal"
    CHOICE = "choice"


ScenarioRecipeParameterValue = bool | int | Decimal | str


@dataclass(frozen=True, slots=True)
class ScenarioRecipeParameterInput:
    name: str
    kind: ScenarioRecipeParameterKind
    value: ScenarioRecipeParameterValue

    def __post_init__(self) -> None:
        _require_identity(self.name, "Scenario Recipe parameter name")
        expected = {
            ScenarioRecipeParameterKind.BOOLEAN: bool,
            ScenarioRecipeParameterKind.INTEGER: int,
            ScenarioRecipeParameterKind.DECIMAL: Decimal,
            ScenarioRecipeParameterKind.CHOICE: str,
        }[self.kind]
        if type(self.value) is not expected:
            raise TypeError(f"{self.kind.value} parameter has the wrong value type")
        if isinstance(self.value, str) and not self.value.strip():
            raise ValueError("Choice parameter value cannot be empty")


@dataclass(frozen=True, slots=True)
class ScenarioRecipeTransformationInput:
    transformation_id: str
    parameters: tuple[ScenarioRecipeParameterInput, ...]

    def __post_init__(self) -> None:
        _require_identity(self.transformation_id, "Transformation identity")
        names = tuple(item.name for item in self.parameters)
        if len(names) != len(set(names)):
            raise ValueError("Transformation parameters must be unique")


@dataclass(frozen=True, slots=True)
class ScenarioRecipeDraftPayload:
    name: str
    historical_segment_id: HistoricalMarketSegmentId
    transformations: tuple[ScenarioRecipeTransformationInput, ...]
    requested_execution_assumptions: RequestedExecutionAssumptionsProjection
    decision_cadence_minutes: int
    materialization_seed: int
    data_policy: ScenarioRecipeDataPolicy
    market_rule_profile_version: str

    def __post_init__(self) -> None:
        _require_identity(self.name, "Scenario Recipe Draft name")
        _require_identity(
            self.market_rule_profile_version,
            "Market rule profile version",
        )
        if self.decision_cadence_minutes <= 0:
            raise ValueError("Decision cadence must be positive")
        transformation_ids = tuple(
            item.transformation_id for item in self.transformations
        )
        if len(transformation_ids) != len(set(transformation_ids)):
            raise ValueError("Scenario Recipe transformations must be unique")


@dataclass(frozen=True, slots=True)
class CreateScenarioRecipeDraftCommand:
    metadata: ScenarioLabCommandMetadata
    payload: ScenarioRecipeDraftPayload
    author_id: ScenarioLabActorId
    authoring_mode: ScenarioRecipeAuthoringMode
    assistant_attempt_id: str | None = None

    def __post_init__(self) -> None:
        if self.authoring_mode is ScenarioRecipeAuthoringMode.AI_ASSISTED:
            if self.assistant_attempt_id is None:
                raise ValueError("AI-assisted authoring requires an attempt identity")
            _require_identity(self.assistant_attempt_id, "Assistant attempt identity")
        elif self.assistant_attempt_id is not None:
            raise ValueError("Manual authoring cannot carry an assistant attempt identity")


@dataclass(frozen=True, slots=True)
class ReviseScenarioRecipeDraftCommand:
    metadata: ScenarioLabCommandMetadata
    predecessor_draft_id: ScenarioRecipeDraftId
    expected_draft_revision: int
    payload: ScenarioRecipeDraftPayload
    author_id: ScenarioLabActorId
    based_on_recipe_version_id: ApprovedScenarioRecipeVersionId | None = None

    def __post_init__(self) -> None:
        if self.expected_draft_revision < 1:
            raise ValueError("Expected Recipe Draft revision must be positive")


@dataclass(frozen=True, slots=True)
class ValidateScenarioRecipeDraftCommand:
    metadata: ScenarioLabCommandMetadata
    draft_id: ScenarioRecipeDraftId
    expected_draft_revision: int
    expected_payload_hash: str

    def __post_init__(self) -> None:
        if self.expected_draft_revision < 1:
            raise ValueError("Expected Recipe Draft revision must be positive")
        _require_identity(self.expected_payload_hash, "Expected payload hash")


@dataclass(frozen=True, slots=True)
class ApproveScenarioRecipeCommand:
    metadata: ScenarioLabCommandMetadata
    draft_id: ScenarioRecipeDraftId
    expected_draft_revision: int
    expected_payload_hash: str
    validation_id: ScenarioRecipeValidationId
    actor_id: ScenarioLabActorId

    def __post_init__(self) -> None:
        if self.expected_draft_revision < 1:
            raise ValueError("Expected Recipe Draft revision must be positive")
        _require_identity(self.expected_payload_hash, "Expected payload hash")


@dataclass(frozen=True, slots=True)
class MaterializeApprovedScenarioRecipeCommand:
    metadata: ScenarioLabCommandMetadata
    recipe_version_id: ApprovedScenarioRecipeVersionId
    expected_recipe_content_hash: str

    def __post_init__(self) -> None:
        _require_identity(
            self.expected_recipe_content_hash,
            "Expected approved Recipe content hash",
        )


@dataclass(frozen=True, slots=True)
class RetryScenarioMaterializationCommand:
    metadata: ScenarioLabCommandMetadata
    predecessor_attempt_id: ScenarioMaterializationAttemptId
    predecessor_task_handle_id: TaskHandleId


@dataclass(frozen=True, slots=True)
class ComposeFormalScenarioSetCommand:
    metadata: ScenarioLabCommandMetadata
    baseline_case_id: CampaignCaseId
    isolated_case_ids: tuple[CampaignCaseId, ...]
    compound_case_ids: tuple[CampaignCaseId, ...]

    def __post_init__(self) -> None:
        identities = (
            self.baseline_case_id,
            *self.isolated_case_ids,
            *self.compound_case_ids,
        )
        if len(identities) != len(set(identities)):
            raise ValueError("Formal Scenario Set cases must be unique")


@dataclass(frozen=True, slots=True)
class ScenarioExecutionAssumptionTarget:
    strategy_id: StrategyUnderTestId
    campaign_case_id: CampaignCaseId


@dataclass(frozen=True, slots=True)
class ResolveScenarioExecutionAssumptionsCommand:
    metadata: ScenarioLabCommandMetadata
    targets: tuple[ScenarioExecutionAssumptionTarget, ...]

    def __post_init__(self) -> None:
        if not self.targets:
            raise ValueError("Execution assumption resolution requires targets")
        if len(self.targets) != len(set(self.targets)):
            raise ValueError("Execution assumption targets must be unique")


@dataclass(frozen=True, slots=True)
class SelectFormalScenarioSetCommand:
    metadata: ScenarioLabCommandMetadata
    scenario_set_id: ScenarioSetId
    case_ids: tuple[CampaignCaseId, ...]
    originating_view_revision: int

    def __post_init__(self) -> None:
        if not self.case_ids:
            raise ValueError("Formal Scenario Set selection requires cases")
        if len(self.case_ids) != len(set(self.case_ids)):
            raise ValueError("Formal Scenario Set selection cases must be unique")
        if self.originating_view_revision < 1:
            raise ValueError("Originating view revision must be positive")


class ScenarioLabTaskIdentityKind(str, Enum):
    RECIPE_DRAFT = "recipe_draft"
    RECIPE_VALIDATION = "recipe_validation"
    APPROVED_RECIPE_VERSION = "approved_recipe_version"
    MATERIALIZATION_ATTEMPT = "materialization_attempt"
    REFERENCE_MARKET_PATH = "reference_market_path"
    FORMAL_SCENARIO_SET = "formal_scenario_set"
    EXECUTION_RESOLUTION = "execution_resolution"
    SELECTION_CONTEXT = "selection_context"


@dataclass(frozen=True, slots=True)
class ScenarioLabTaskIdentity:
    kind: ScenarioLabTaskIdentityKind
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Scenario Lab task target/result identity")


@dataclass(frozen=True, slots=True)
class ScenarioLabTaskHandle:
    """Persistent async identity shared with the certified TaskHandle model."""

    identity: TaskHandleId
    attempt_identity: ScenarioMaterializationAttemptId
    operation: ScenarioLabTaskOperation
    target_identity: ScenarioLabTaskIdentity
    phase: TaskPhase
    progress: float
    result_identity: ScenarioLabTaskIdentity | None
    error: ScenarioLabApplicationError | None
    cancelable: bool
    retryable: bool
    terminal: bool
    predecessor_task_handle_id: TaskHandleId | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.progress <= 1.0:
            raise ValueError("Scenario Lab task progress must be between zero and one")
        if self.predecessor_task_handle_id == self.identity:
            raise ValueError("Scenario Lab task cannot be its own predecessor")
        if self.phase is TaskPhase.FAILED and self.error is None:
            raise ValueError("Failed Scenario Lab task requires a typed error")
        if self.phase is not TaskPhase.FAILED and self.error is not None:
            raise ValueError("Only failed Scenario Lab tasks expose an error")
        terminal_phases = {TaskPhase.COMPLETED, TaskPhase.FAILED, TaskPhase.CANCELED}
        if self.terminal != (self.phase in terminal_phases):
            raise ValueError("Scenario Lab task terminal flag must match its phase")
        if self.result_identity is not None and self.phase is not TaskPhase.COMPLETED:
            raise ValueError("Only completed Scenario Lab tasks expose a result identity")


@dataclass(frozen=True, slots=True)
class ScenarioLabCommandReceipt:
    metadata: ScenarioLabCommandMetadata
    operation: ScenarioLabTaskOperation
    disposition: ScenarioLabCommandDisposition
    message: str
    authoritative_revision: SourceRevisionToken | None
    task_handle: ScenarioLabTaskHandle | None


@dataclass(frozen=True, slots=True)
class CreateScenarioRecipeDraftResult:
    receipt: ScenarioLabCommandReceipt
    draft_id: ScenarioRecipeDraftId | None = None
    draft_revision: int | None = None
    payload_hash: str | None = None


@dataclass(frozen=True, slots=True)
class ReviseScenarioRecipeDraftResult:
    receipt: ScenarioLabCommandReceipt
    draft_id: ScenarioRecipeDraftId | None = None
    draft_revision: int | None = None
    payload_hash: str | None = None


@dataclass(frozen=True, slots=True)
class ValidateScenarioRecipeDraftResult:
    receipt: ScenarioLabCommandReceipt
    validation_id: ScenarioRecipeValidationId | None = None
    draft_id: ScenarioRecipeDraftId | None = None
    draft_revision: int | None = None


@dataclass(frozen=True, slots=True)
class ApproveScenarioRecipeResult:
    receipt: ScenarioLabCommandReceipt
    recipe_version_id: ApprovedScenarioRecipeVersionId | None = None
    recipe_content_hash: str | None = None


@dataclass(frozen=True, slots=True)
class MaterializeApprovedScenarioRecipeResult:
    receipt: ScenarioLabCommandReceipt
    path_id: ReferenceMarketPathId | None = None
    attempt_id: ScenarioMaterializationAttemptId | None = None


@dataclass(frozen=True, slots=True)
class RetryScenarioMaterializationResult:
    receipt: ScenarioLabCommandReceipt
    path_id: ReferenceMarketPathId | None = None
    attempt_id: ScenarioMaterializationAttemptId | None = None


@dataclass(frozen=True, slots=True)
class ComposeFormalScenarioSetResult:
    receipt: ScenarioLabCommandReceipt
    scenario_set_id: ScenarioSetId | None = None


@dataclass(frozen=True, slots=True)
class ResolveScenarioExecutionAssumptionsResult:
    receipt: ScenarioLabCommandReceipt
    resolution_id: ScenarioExecutionResolutionId | None = None


@dataclass(frozen=True, slots=True)
class SelectFormalScenarioSetResult:
    receipt: ScenarioLabCommandReceipt
    selection_context_id: ScenarioSelectionContextId | None = None
    scenario_set_id: ScenarioSetId | None = None


ScenarioLabCommandResult = (
    CreateScenarioRecipeDraftResult
    | ReviseScenarioRecipeDraftResult
    | ValidateScenarioRecipeDraftResult
    | ApproveScenarioRecipeResult
    | MaterializeApprovedScenarioRecipeResult
    | RetryScenarioMaterializationResult
    | ComposeFormalScenarioSetResult
    | ResolveScenarioExecutionAssumptionsResult
    | SelectFormalScenarioSetResult
)


@runtime_checkable
class StrategyDiagnosticsV1ScenarioLabApplication(Protocol):
    @property
    def interface_version(self) -> ScenarioLabApplicationVersion: ...

    def read_inventory(self) -> ScenarioLabApplicationInventoryResult: ...

    def create_recipe_draft(
        self, command: CreateScenarioRecipeDraftCommand
    ) -> CreateScenarioRecipeDraftResult: ...

    def revise_recipe_draft(
        self, command: ReviseScenarioRecipeDraftCommand
    ) -> ReviseScenarioRecipeDraftResult: ...

    def validate_recipe_draft(
        self, command: ValidateScenarioRecipeDraftCommand
    ) -> ValidateScenarioRecipeDraftResult: ...

    def approve_recipe(
        self, command: ApproveScenarioRecipeCommand
    ) -> ApproveScenarioRecipeResult: ...

    def materialize_reference_path(
        self, command: MaterializeApprovedScenarioRecipeCommand
    ) -> MaterializeApprovedScenarioRecipeResult: ...

    def retry_materialization(
        self, command: RetryScenarioMaterializationCommand
    ) -> RetryScenarioMaterializationResult: ...

    def compose_scenario_set(
        self, command: ComposeFormalScenarioSetCommand
    ) -> ComposeFormalScenarioSetResult: ...

    def resolve_execution_assumptions(
        self, command: ResolveScenarioExecutionAssumptionsCommand
    ) -> ResolveScenarioExecutionAssumptionsResult: ...

    def select_formal_scenario_set(
        self, command: SelectFormalScenarioSetCommand
    ) -> SelectFormalScenarioSetResult: ...


class LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter:
    """Translate public DiagnosticsApplication behavior into typed values."""

    _PREVIEW_NODE_LIMIT = 24

    def __init__(self, application: DiagnosticsApplication) -> None:
        self._application = application
        self._application_access_gate = (
            shared_diagnostics_application_access_gate(application)
        )

    @property
    def interface_version(self) -> ScenarioLabApplicationVersion:
        return SCENARIO_LAB_APPLICATION_INTERFACE_VERSION

    def read_inventory(self) -> ScenarioLabApplicationInventoryResult:
        observed_at = datetime.now(timezone.utc)
        try:
            with self._application_access_gate:
                case_inventory = (
                    self._application.read_diagnostic_campaign_case_inventory()
                )
                catalog_view = self._application.transformation_catalog_view()
                path_entries = tuple(
                    self._map_path(path, assessment)
                    for path, assessment in zip(
                        case_inventory.materialized_paths,
                        case_inventory.path_assessments,
                        strict=True,
                    )
                )
            mapped_segments = tuple(
                _map_segment(item)
                for item in case_inventory.admitted_segments
            )
            mapped_cases = _map_cases(
                case_inventory.available_cases,
                case_inventory.case_assessments,
            )
            catalog = _map_catalog(catalog_view)
            inventory = ScenarioLabInventory(
                historical_segments=mapped_segments,
                reference_paths=path_entries,
                market_scenarios=mapped_cases,
                transformation_catalog=catalog,
            )
            partial = any(
                item.integrity is not ScenarioLabIntegrityState.VERIFIED
                for item in path_entries
            )
            availability = (
                ScenarioLabApplicationAvailability.PARTIAL
                if partial
                else ScenarioLabApplicationAvailability.READY
                if mapped_segments or path_entries or mapped_cases
                else ScenarioLabApplicationAvailability.EMPTY
            )
        except RuntimeError:
            return _failed_result(
                observed_at,
                ScenarioLabApplicationErrorCode.APPLICATION_NOT_READY,
                "Strategy Diagnostics is not ready.",
                True,
            )
        except (IndexError, KeyError, OSError, TypeError, UnicodeError, ValueError):
            return _failed_result(
                observed_at,
                ScenarioLabApplicationErrorCode.INVENTORY_READ_FAILED,
                "The authoritative Scenario Lab inventory is unavailable.",
                False,
            )
        return ScenarioLabApplicationInventoryResult(
            availability=availability,
            inventory=inventory,
            source_token=_inventory_token(inventory),
            observed_at=observed_at,
            error=None,
        )

    def _map_path(
        self,
        path: MaterializedMarketPath,
        assessment: ScenarioLabPathAssessment,
    ) -> ReferenceMarketPathEntry:
        if path.artifact_hash != assessment.path_identity:
            raise ValueError(
                "Reference Path assessment identity does not match its path"
            )
        integrity = ScenarioLabIntegrityState(assessment.integrity.value)
        compatibility = ScenarioCompatibilityState(
            assessment.compatibility.value
        )
        reproducibility = ScenarioReproducibilityState(
            assessment.reproducibility.value
        )
        reasons = _map_backend_reasons(assessment.reasons)
        try:
            if integrity is not ScenarioLabIntegrityState.VERIFIED:
                raise ValueError("Backend path integrity assessment failed")
            preview_payload = self._application.preview_reference_market_path(
                path.artifact_hash,
                at_time=path.nodes[-1].simulation_time,
            )
            preview = _map_preview(
                preview_payload,
                at_time=path.nodes[-1].simulation_time,
                limit=self._PREVIEW_NODE_LIMIT,
            )
        except (IndexError, KeyError, OSError, TypeError, UnicodeError, ValueError):
            preview = None
            integrity = ScenarioLabIntegrityState.FAILED
            compatibility = ScenarioCompatibilityState.UNAVAILABLE
            reproducibility = ScenarioReproducibilityState.UNAVAILABLE
            preview_reason = ScenarioLabUnavailabilityReason(
                code=ScenarioLabUnavailabilityCode.PREVIEW_UNAVAILABLE,
                summary=(
                    "The immutable Reference Market Path preview failed integrity "
                    "verification."
                ),
                corrective_guidance=(
                    "Verify the persisted path artifact before inspecting its "
                    "bounded preview."
                ),
            )
            if preview_reason not in reasons:
                reasons = (*reasons, preview_reason)
        return ReferenceMarketPathEntry(
            path_id=ReferenceMarketPathId(path.artifact_hash),
            segment_id=HistoricalMarketSegmentId(path.segment_id),
            segment_content_hash=path.segment_content_hash,
            source_snapshot_id=SourceSnapshotId(path.source_snapshot_id),
            seed=path.seed,
            expander_version=path.expander_version,
            source_resolution=path.source_resolution,
            runtime_resolution=path.runtime_resolution,
            reconstructed=path.reconstructed,
            reconstruction_notice=path.reconstruction_notice,
            numeric_tolerance=path.numeric_tolerance,
            normalization_provenance=path.normalization_provenance,
            market_rule_profile_version=path.market_rule_profile_version,
            transformation_catalog_version=path.transformation_catalog_version,
            transformations=tuple(
                AppliedTransformationProjection(
                    transformation_id=item.transformation_id,
                    family=item.family,
                    catalog_version=item.catalog_version,
                    implementation_version=item.implementation_version,
                    parameters=item.parameters,
                )
                for item in path.applied_transformations
            ),
            start_time=path.nodes[0].simulation_time,
            end_time=path.nodes[-1].simulation_time,
            integrity=integrity,
            compatibility=compatibility,
            reproducibility=reproducibility,
            preview=preview,
            unavailability_reasons=reasons,
        )

    def create_recipe_draft(
        self, command: CreateScenarioRecipeDraftCommand
    ) -> CreateScenarioRecipeDraftResult:
        return CreateScenarioRecipeDraftResult(
            receipt=_unavailable_receipt(
                command.metadata,
                ScenarioLabTaskOperation.CREATE_RECIPE_DRAFT,
                "Recipe Draft creation is owned by Issue #80.",
            )
        )

    def revise_recipe_draft(
        self, command: ReviseScenarioRecipeDraftCommand
    ) -> ReviseScenarioRecipeDraftResult:
        return ReviseScenarioRecipeDraftResult(
            receipt=_unavailable_receipt(
                command.metadata,
                ScenarioLabTaskOperation.REVISE_RECIPE_DRAFT,
                "Recipe Draft revision is owned by Issue #80.",
            )
        )

    def validate_recipe_draft(
        self, command: ValidateScenarioRecipeDraftCommand
    ) -> ValidateScenarioRecipeDraftResult:
        return ValidateScenarioRecipeDraftResult(
            receipt=_unavailable_receipt(
                command.metadata,
                ScenarioLabTaskOperation.VALIDATE_RECIPE_DRAFT,
                "Recipe validation is owned by Issue #80.",
            )
        )

    def approve_recipe(
        self, command: ApproveScenarioRecipeCommand
    ) -> ApproveScenarioRecipeResult:
        return ApproveScenarioRecipeResult(
            receipt=_unavailable_receipt(
                command.metadata,
                ScenarioLabTaskOperation.APPROVE_RECIPE,
                "Recipe approval is owned by Issue #81.",
            )
        )

    def materialize_reference_path(
        self, command: MaterializeApprovedScenarioRecipeCommand
    ) -> MaterializeApprovedScenarioRecipeResult:
        return MaterializeApprovedScenarioRecipeResult(
            receipt=_unavailable_receipt(
                command.metadata,
                ScenarioLabTaskOperation.MATERIALIZE_REFERENCE_PATH,
                "Reference Path materialization is owned by Issue #82.",
            )
        )

    def retry_materialization(
        self, command: RetryScenarioMaterializationCommand
    ) -> RetryScenarioMaterializationResult:
        return RetryScenarioMaterializationResult(
            receipt=_unavailable_receipt(
                command.metadata,
                ScenarioLabTaskOperation.RETRY_MATERIALIZATION,
                "Materialization retry is owned by Issue #82.",
            )
        )

    def compose_scenario_set(
        self, command: ComposeFormalScenarioSetCommand
    ) -> ComposeFormalScenarioSetResult:
        return ComposeFormalScenarioSetResult(
            receipt=_unavailable_receipt(
                command.metadata,
                ScenarioLabTaskOperation.COMPOSE_SCENARIO_SET,
                "Scenario-set composition is owned by Issue #83.",
            )
        )

    def resolve_execution_assumptions(
        self, command: ResolveScenarioExecutionAssumptionsCommand
    ) -> ResolveScenarioExecutionAssumptionsResult:
        return ResolveScenarioExecutionAssumptionsResult(
            receipt=_unavailable_receipt(
                command.metadata,
                ScenarioLabTaskOperation.RESOLVE_EXECUTION_ASSUMPTIONS,
                "Execution assumption resolution is owned by Issue #83.",
            )
        )

    def select_formal_scenario_set(
        self, command: SelectFormalScenarioSetCommand
    ) -> SelectFormalScenarioSetResult:
        return SelectFormalScenarioSetResult(
            receipt=_unavailable_receipt(
                command.metadata,
                ScenarioLabTaskOperation.SELECT_FORMAL_SCENARIO_SET,
                "Formal Scenario selection is owned by Issue #83.",
            )
        )


def _map_segment(item: ScenarioLabAdmittedSegment) -> HistoricalSegmentEntry:
    segment = item.segment
    provenance = segment.source_provenance
    return HistoricalSegmentEntry(
        segment_id=HistoricalMarketSegmentId(segment.segment_id),
        content_hash=segment.content_hash,
        source_snapshot_id=SourceSnapshotId(segment.source_snapshot_id),
        source_snapshot_content_hash=item.source_snapshot_content_hash,
        provenance=HistoricalSegmentProvenance(
            provider=provenance.provider,
            dataset=provenance.dataset,
            version=provenance.version,
            observed_at=provenance.observed_at,
        ),
        market=segment.selection.market,
        start_date=segment.selection.start_date,
        end_date=segment.selection.end_date,
        label=segment.label,
        eligible_instrument_count=segment.eligible_instrument_count,
        trading_day_count=segment.trading_day_count,
        bar_count=segment.bar_count,
        admission_state=ScenarioLabAdmissionState(item.admission_state.value),
        quality_state=ScenarioLabQualityState(item.quality_state.value),
        recommendation_tags=segment.recommendation_tags,
        unavailability_reasons=_map_backend_reasons(item.unavailability_reasons),
    )


def _map_backend_reasons(
    reasons: tuple[ScenarioLabInventoryReason, ...],
) -> tuple[ScenarioLabUnavailabilityReason, ...]:
    return tuple(
        ScenarioLabUnavailabilityReason(
            code=ScenarioLabUnavailabilityCode(item.code.value),
            summary=item.summary,
            corrective_guidance=item.corrective_guidance,
        )
        for item in reasons
    )


def _map_catalog(payload: object) -> TransformationCatalogProjection:
    if not isinstance(payload, dict):
        raise TypeError("Transformation catalog must be an object")
    raw_entries = payload.get("transformations")
    if not isinstance(raw_entries, list):
        raise TypeError("Transformation catalog entries must be a list")
    entries: list[TransformationCatalogEntryProjection] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            raise TypeError("Transformation catalog entry must be an object")
        raw_parameters = raw_entry.get("parameters")
        if not isinstance(raw_parameters, list):
            raise TypeError("Transformation parameters must be a list")
        parameters: list[TransformationParameterProjection] = []
        for raw_parameter in raw_parameters:
            if not isinstance(raw_parameter, dict):
                raise TypeError("Transformation parameter must be an object")
            raw_choices = raw_parameter.get("choices", [])
            if not isinstance(raw_choices, list):
                raise TypeError("Transformation choices must be a list")
            required = raw_parameter.get("required")
            if not isinstance(required, bool):
                raise TypeError("Transformation required must be bool")
            parameters.append(
                TransformationParameterProjection(
                    name=_required_text(raw_parameter, "name"),
                    value_type=_required_text(raw_parameter, "value_type"),
                    required=required,
                    minimum=_optional_text(raw_parameter.get("minimum")),
                    maximum=_optional_text(raw_parameter.get("maximum")),
                    choices=tuple(str(value) for value in raw_choices),
                )
            )
        entries.append(
            TransformationCatalogEntryProjection(
                transformation_id=_required_text(raw_entry, "transformation_id"),
                family=_required_text(raw_entry, "family"),
                implementation_version=_required_text(raw_entry, "implementation_version"),
                parameters=tuple(parameters),
                compatibility_rules=_text_tuple(raw_entry, "compatibility_rules"),
                causality_constraints=_text_tuple(raw_entry, "causality_constraints"),
            )
        )
    return TransformationCatalogProjection(
        catalog_version=_required_text(payload, "catalog_version"),
        entries=tuple(entries),
    )


def _map_preview(payload: object, *, at_time: datetime, limit: int) -> ReferencePathPreview:
    if not isinstance(payload, dict):
        raise TypeError("Reference Path preview must be an object")
    raw_nodes = payload.get("latest_nodes")
    raw_universe = payload.get("eligible_universe")
    raw_statistics = payload.get("path_statistics")
    if not isinstance(raw_nodes, dict) or not isinstance(raw_universe, list):
        raise TypeError("Reference Path preview is incomplete")
    if not isinstance(raw_statistics, dict):
        raise TypeError("Reference Path statistics are incomplete")
    nodes: list[ReferencePathPreviewNode] = []
    for instrument in sorted(raw_nodes)[:limit]:
        raw_node = raw_nodes[instrument]
        if not isinstance(raw_node, dict):
            raise TypeError("Reference Path preview node must be an object")
        reconstructed = raw_node.get("reconstructed")
        if not isinstance(reconstructed, bool):
            raise TypeError("Reference Path reconstructed marker must be bool")
        nodes.append(
            ReferencePathPreviewNode(
                instrument=_required_text(raw_node, "instrument"),
                simulation_time=datetime.fromisoformat(_required_text(raw_node, "simulation_time")),
                open=_required_text(raw_node, "open"),
                high=_required_text(raw_node, "high"),
                low=_required_text(raw_node, "low"),
                close=_required_text(raw_node, "close"),
                volume=int(raw_node["volume"]),
                amount=_required_text(raw_node, "amount"),
                reconstructed=reconstructed,
            )
        )
    return ReferencePathPreview(
        at_time=at_time,
        eligible_universe=tuple(str(item) for item in raw_universe[:limit]),
        nodes=tuple(nodes),
        node_count=int(raw_statistics["node_count"]),
        bounded_node_limit=limit,
    )


def _map_cases(
    cases: tuple[DiagnosticCampaignCase, ...],
    assessments: tuple[ScenarioLabCampaignCaseAssessment, ...],
) -> tuple[MarketScenarioEntry, ...]:
    baselines = {
        (
            case.historical_segment_id,
            case.historical_segment_content_hash,
            case.source_snapshot_id,
            case.materialization_seed,
        ): CampaignCaseId(case.case_id)
        for case in cases
        if case.layer == "baseline"
    }
    mapped: list[MarketScenarioEntry] = []
    for case, assessment in zip(cases, assessments, strict=True):
        if case.case_id != assessment.campaign_case_identity:
            raise ValueError(
                "Campaign Case assessment identity does not match its case"
            )
        layer = {
            "baseline": MarketScenarioLayer.BASELINE,
            "isolated": MarketScenarioLayer.ISOLATED_SENSITIVITY,
            "compound": MarketScenarioLayer.COMPOUND,
        }[case.layer]
        baseline_id = baselines.get(
            (
                case.historical_segment_id,
                case.historical_segment_content_hash,
                case.source_snapshot_id,
                case.materialization_seed,
            )
        )
        requested = case.requested_execution_conditions
        reasons = _map_backend_reasons(assessment.reasons)
        mapped.append(
            MarketScenarioEntry(
                scenario_id=CampaignCaseId(case.case_id),
                layer=layer,
                comparison_role=(
                    MarketScenarioComparisonRole.CONTROL
                    if layer is MarketScenarioLayer.BASELINE
                    else MarketScenarioComparisonRole.COMPARE_TO_BASELINE
                ),
                baseline_scenario_id=None if layer is MarketScenarioLayer.BASELINE else baseline_id,
                recipe_version_id=ApprovedScenarioRecipeVersionId(case.recipe_version_id),
                recipe_content_hash=case.recipe_content_hash,
                path_id=ReferenceMarketPathId(case.materialization_hash),
                segment_id=HistoricalMarketSegmentId(case.historical_segment_id),
                segment_content_hash=case.historical_segment_content_hash,
                source_snapshot_id=SourceSnapshotId(case.source_snapshot_id),
                seed=case.materialization_seed,
                transformation_catalog_version=case.transformation_catalog_version,
                transformations=tuple(
                    MarketScenarioTransformationProjection(
                        transformation_id=item.transformation_id,
                        family=item.transformation_family,
                        implementation_version=item.transformation_implementation_version,
                        parameters=item.transformation_parameters,
                    )
                    for item in case.transformations
                ),
                market_rule_profile_version=case.market_rule_profile_version,
                decision_cadence_minutes=case.decision_cadence_minutes,
                requested_execution_assumptions=RequestedExecutionAssumptionsProjection(
                    commission_bps=str(requested.commission_bps),
                    slippage_bps=str(requested.slippage_bps),
                    max_fill_fraction=str(requested.max_fill_fraction),
                    latency_nodes=requested.latency_nodes,
                    allow_partial_fills=requested.allow_partial_fills,
                ),
                compatibility=ScenarioCompatibilityState(
                    assessment.compatibility.value
                ),
                reproducibility=ScenarioReproducibilityState(
                    assessment.reproducibility.value
                ),
                execution_resolution=ScenarioExecutionResolutionState.NOT_YET_RESOLVED,
                unavailability_reasons=reasons,
            )
        )
    return tuple(mapped)


def _inventory_token(inventory: ScenarioLabInventory) -> SourceRevisionToken:
    return SourceRevisionToken(
        hashlib.sha256(repr(inventory).encode("utf-8")).hexdigest()
    )


def _unavailable_receipt(
    metadata: ScenarioLabCommandMetadata,
    operation: ScenarioLabTaskOperation,
    message: str,
) -> ScenarioLabCommandReceipt:
    return ScenarioLabCommandReceipt(
        metadata=metadata,
        operation=operation,
        disposition=ScenarioLabCommandDisposition.UNAVAILABLE,
        message=message,
        authoritative_revision=None,
        task_handle=None,
    )


def _failed_result(
    observed_at: datetime,
    code: ScenarioLabApplicationErrorCode,
    message: str,
    retryable: bool,
) -> ScenarioLabApplicationInventoryResult:
    return ScenarioLabApplicationInventoryResult(
        availability=ScenarioLabApplicationAvailability.FAILED,
        inventory=None,
        source_token=None,
        observed_at=observed_at,
        error=ScenarioLabApplicationError(code, message, retryable),
    )


def _required_text(container: object, key: str) -> str:
    if not isinstance(container, dict):
        raise TypeError("Expected object")
    value = container.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be non-empty text")
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _text_tuple(container: object, key: str) -> tuple[str, ...]:
    if not isinstance(container, dict):
        raise TypeError("Expected object")
    values = container.get(key)
    if not isinstance(values, list):
        raise TypeError(f"{key} must be a list")
    return tuple(str(value) for value in values)


__all__ = [
    "AppliedTransformationProjection",
    "ApproveScenarioRecipeCommand",
    "ApproveScenarioRecipeResult",
    "ComposeFormalScenarioSetCommand",
    "ComposeFormalScenarioSetResult",
    "CreateScenarioRecipeDraftCommand",
    "CreateScenarioRecipeDraftResult",
    "HistoricalSegmentEntry",
    "HistoricalSegmentProvenance",
    "LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter",
    "MaterializeApprovedScenarioRecipeCommand",
    "MaterializeApprovedScenarioRecipeResult",
    "MarketScenarioComparisonRole",
    "MarketScenarioEntry",
    "MarketScenarioLayer",
    "MarketScenarioTransformationProjection",
    "ReferenceMarketPathEntry",
    "ReferenceMarketPathId",
    "ReferencePathPreview",
    "ReferencePathPreviewNode",
    "RequestedExecutionAssumptionsProjection",
    "SCENARIO_LAB_APPLICATION_INTERFACE_VERSION",
    "ScenarioCompatibilityState",
    "ScenarioExecutionResolutionState",
    "ScenarioLabApplicationAvailability",
    "ScenarioLabApplicationError",
    "ScenarioLabApplicationErrorCode",
    "ScenarioLabApplicationInventoryResult",
    "ScenarioLabApplicationVersion",
    "ScenarioLabActorId",
    "ScenarioLabAdmissionState",
    "ScenarioLabCommandContentIdentity",
    "ScenarioLabCommandDisposition",
    "ScenarioLabCommandId",
    "ScenarioLabCommandMetadata",
    "ScenarioLabCommandReceipt",
    "ScenarioLabCommandResult",
    "ScenarioLabIdempotencyIdentity",
    "ScenarioLabIntegrityState",
    "ScenarioLabInventory",
    "ScenarioLabQualityState",
    "ScenarioLabTaskHandle",
    "ScenarioLabTaskIdentity",
    "ScenarioLabTaskIdentityKind",
    "ScenarioLabTaskOperation",
    "ScenarioLabUnavailabilityCode",
    "ScenarioLabUnavailabilityReason",
    "ScenarioReproducibilityState",
    "ScenarioExecutionAssumptionTarget",
    "ScenarioExecutionResolutionId",
    "ScenarioMaterializationAttemptId",
    "ScenarioRecipeAuthoringMode",
    "ScenarioRecipeDataPolicy",
    "ScenarioRecipeDraftId",
    "ScenarioRecipeDraftPayload",
    "ScenarioRecipeParameterInput",
    "ScenarioRecipeParameterKind",
    "ScenarioRecipeParameterValue",
    "ScenarioRecipeTransformationInput",
    "ScenarioRecipeValidationId",
    "ScenarioSelectionContextId",
    "ResolveScenarioExecutionAssumptionsCommand",
    "ResolveScenarioExecutionAssumptionsResult",
    "RetryScenarioMaterializationCommand",
    "RetryScenarioMaterializationResult",
    "ReviseScenarioRecipeDraftCommand",
    "ReviseScenarioRecipeDraftResult",
    "SelectFormalScenarioSetCommand",
    "SelectFormalScenarioSetResult",
    "StrategyDiagnosticsV1ScenarioLabApplication",
    "TransformationCatalogEntryProjection",
    "TransformationCatalogProjection",
    "TransformationParameterProjection",
    "ValidateScenarioRecipeDraftCommand",
    "ValidateScenarioRecipeDraftResult",
]
