"""Typed in-process Application Interface for Scenario Lab 1.0."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from datetime import date, datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

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
    from strategy_diagnostics.scenario_lab_authoring import (
        ScenarioLabAuthoringResult,
        ScenarioRecipeApprovalRecord,
        ScenarioRecipeDraftRevisionRecord,
        ScenarioRecipeValidationDependencyRecord,
        ScenarioRecipeValidationRecord,
    )


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
    RECIPE_APPROVAL_OUTDATED = "scenario_recipe_approval_outdated"
    RECIPE_APPROVAL_INCOMPATIBLE = "scenario_recipe_approval_incompatible"
    RECIPE_APPROVAL_DEPENDENCY_UNAVAILABLE = (
        "scenario_recipe_approval_dependency_unavailable"
    )


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
    authoring_capabilities: ScenarioRecipeAuthoringCapabilitiesProjection
    recipe_drafts: tuple[ScenarioRecipeDraftProjection, ...] = ()
    recipe_validations: tuple[ScenarioRecipeValidationProjection, ...] = ()
    approved_recipe_versions: tuple[
        ApprovedScenarioRecipeVersionProjection, ...
    ] = ()
    task_handles: tuple[ScenarioLabTaskHandle, ...] = ()


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


@dataclass(frozen=True, slots=True)
class ScenarioRecipeAuthoringCapabilitiesProjection:
    manual_authoring_available: bool
    ai_authoring_available: bool
    ai_provider: str | None
    ai_model: str | None

    def __post_init__(self) -> None:
        if not self.manual_authoring_available:
            raise ValueError("Scenario Lab manual authoring must remain available")
        if self.ai_authoring_available:
            if self.ai_provider is None or self.ai_model is None:
                raise ValueError(
                    "Configured AI authoring requires provider and model identities"
                )
            _require_identity(self.ai_provider, "AI authoring provider")
            _require_identity(self.ai_model, "AI authoring model")
        elif self.ai_provider is not None or self.ai_model is not None:
            raise ValueError(
                "Unavailable AI authoring cannot advertise provider or model"
            )

    @classmethod
    def manual_only(cls) -> "ScenarioRecipeAuthoringCapabilitiesProjection":
        return cls(
            manual_authoring_available=True,
            ai_authoring_available=False,
            ai_provider=None,
            ai_model=None,
        )


@dataclass(frozen=True, slots=True)
class CreateAiAssistedScenarioRecipeDraftCommand:
    metadata: ScenarioLabCommandMetadata
    intent: str
    author_id: ScenarioLabActorId

    def __post_init__(self) -> None:
        normalized = " ".join(self.intent.split())
        _require_identity(normalized, "AI Recipe authoring intent")
        object.__setattr__(self, "intent", normalized)


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


class ScenarioRecipeValidationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class ScenarioRecipeCompatibilityState(str, Enum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True, slots=True)
class ScenarioRecipeCompatibilityObservation:
    subject: str
    state: ScenarioRecipeCompatibilityState
    explanation: str

    def __post_init__(self) -> None:
        _require_identity(self.subject, "Recipe compatibility subject")
        _require_identity(self.explanation, "Recipe compatibility explanation")


@dataclass(frozen=True, slots=True)
class ScenarioRecipeValidationFindingProjection:
    path: tuple[str, ...]
    rule_code: str
    severity: ScenarioRecipeValidationSeverity
    explanation: str
    correction: str
    retryable: bool
    different_input_required: bool

    def __post_init__(self) -> None:
        if not self.path or any(not item.strip() for item in self.path):
            raise ValueError("Recipe validation finding path cannot be empty")
        _require_identity(self.rule_code, "Recipe validation rule code")
        _require_identity(self.explanation, "Recipe validation explanation")
        _require_identity(self.correction, "Recipe validation correction")


@dataclass(frozen=True, slots=True)
class ScenarioRecipeValidationDependenciesProjection:
    historical_segment_id: HistoricalMarketSegmentId
    historical_segment_content_hash: str
    source_snapshot_id: SourceSnapshotId
    source_snapshot_content_hash: str
    recipe_schema_identity: str
    recipe_schema_hash: str
    transformation_catalog_version: str
    transformation_catalog_hash: str
    transformation_implementation_identities: tuple[str, ...]
    data_policy: ScenarioRecipeDataPolicy
    causality_rule_identities: tuple[str, ...]
    market_rule_profile_version: str
    market_rule_profile_hash: str
    compatibility_observations: tuple[
        ScenarioRecipeCompatibilityObservation, ...
    ]


@dataclass(frozen=True, slots=True)
class ScenarioRecipeDraftProjection:
    draft_id: ScenarioRecipeDraftId
    recipe_id: str
    revision: int
    payload: ScenarioRecipeDraftPayload
    payload_hash: str
    author_id: ScenarioLabActorId
    created_at: datetime
    predecessor_draft_id: ScenarioRecipeDraftId | None
    based_on_recipe_version_id: ApprovedScenarioRecipeVersionId | None
    authoring_mode: ScenarioRecipeAuthoringMode
    assistant_attempt_id: str | None

    def __post_init__(self) -> None:
        _require_identity(self.recipe_id, "Scenario Recipe identity")
        _require_identity(self.payload_hash, "Scenario Recipe Draft payload hash")
        if self.revision < 1:
            raise ValueError("Scenario Recipe Draft revision must be positive")
        if self.predecessor_draft_id == self.draft_id:
            raise ValueError("Scenario Recipe Draft cannot be its own predecessor")


@dataclass(frozen=True, slots=True)
class ScenarioRecipeValidationProjection:
    validation_id: ScenarioRecipeValidationId
    draft_id: ScenarioRecipeDraftId
    draft_revision: int
    payload_hash: str
    is_valid: bool
    findings: tuple[ScenarioRecipeValidationFindingProjection, ...]
    dependencies: ScenarioRecipeValidationDependenciesProjection
    recipe_content_hash: str | None
    validated_at: datetime

    def __post_init__(self) -> None:
        if self.draft_revision < 1:
            raise ValueError("Validated Recipe Draft revision must be positive")
        _require_identity(self.payload_hash, "Validated Recipe payload hash")
        if self.is_valid == bool(self.findings):
            raise ValueError(
                "Recipe validation validity must agree with its findings"
            )
        if self.is_valid != (self.recipe_content_hash is not None):
            raise ValueError(
                "Only valid Recipe validation exposes a content hash"
            )


@dataclass(frozen=True, slots=True)
class ScenarioRecipeApprovalId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Scenario Recipe approval identity")


class ScenarioRecipeApprovalAuthorityState(str, Enum):
    CURRENT = "current"
    OUTDATED = "outdated"
    INCOMPATIBLE = "incompatible"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ScenarioRecipeApprovalProjection:
    approval_id: ScenarioRecipeApprovalId
    draft_id: ScenarioRecipeDraftId
    draft_revision: int | None
    payload_hash: str
    validation_id: ScenarioRecipeValidationId | None
    recipe_content_hash: str
    actor_id: ScenarioLabActorId
    approved_at: datetime
    dependencies: ScenarioRecipeValidationDependenciesProjection | None

    def __post_init__(self) -> None:
        if self.draft_revision is not None and self.draft_revision < 1:
            raise ValueError("Approved Recipe Draft revision must be positive")
        exact_bindings = (
            self.draft_revision is not None,
            self.validation_id is not None,
            self.dependencies is not None,
        )
        if any(exact_bindings) and not all(exact_bindings):
            raise ValueError(
                "Approved Recipe validation bindings must be present together"
            )
        _require_identity(self.payload_hash, "Approved Recipe payload hash")
        _require_identity(
            self.recipe_content_hash,
            "Approved Recipe content hash",
        )


@dataclass(frozen=True, slots=True)
class ApprovedScenarioRecipeVersionProjection:
    recipe_version_id: ApprovedScenarioRecipeVersionId
    recipe_id: str
    version_number: int
    content_hash: str
    payload: ScenarioRecipeDraftPayload
    author_id: ScenarioLabActorId
    approval: ScenarioRecipeApprovalProjection
    based_on_recipe_version_id: ApprovedScenarioRecipeVersionId | None
    authority_state: ScenarioRecipeApprovalAuthorityState
    authority_reasons: tuple[ScenarioLabUnavailabilityReason, ...]
    can_materialize: bool

    def __post_init__(self) -> None:
        _require_identity(self.recipe_id, "Approved Scenario Recipe identity")
        _require_identity(self.content_hash, "Approved Scenario Recipe hash")
        if self.version_number < 1:
            raise ValueError("Approved Scenario Recipe version must be positive")
        if self.can_materialize != (
            self.authority_state is ScenarioRecipeApprovalAuthorityState.CURRENT
        ):
            raise ValueError(
                "Approved Recipe materialization capability must match authority"
            )
        if self.can_materialize == bool(self.authority_reasons):
            raise ValueError(
                "Only non-current Approved Recipes expose authority reasons"
            )


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
    draft: ScenarioRecipeDraftProjection | None = None


@dataclass(frozen=True, slots=True)
class ReviseScenarioRecipeDraftResult:
    receipt: ScenarioLabCommandReceipt
    draft_id: ScenarioRecipeDraftId | None = None
    draft_revision: int | None = None
    payload_hash: str | None = None
    draft: ScenarioRecipeDraftProjection | None = None
    authoritative_draft_revision: int | None = None


@dataclass(frozen=True, slots=True)
class ValidateScenarioRecipeDraftResult:
    receipt: ScenarioLabCommandReceipt
    validation_id: ScenarioRecipeValidationId | None = None
    draft_id: ScenarioRecipeDraftId | None = None
    draft_revision: int | None = None
    validation: ScenarioRecipeValidationProjection | None = None
    authoritative_draft_revision: int | None = None


@dataclass(frozen=True, slots=True)
class ApproveScenarioRecipeResult:
    receipt: ScenarioLabCommandReceipt
    recipe_version_id: ApprovedScenarioRecipeVersionId | None = None
    recipe_content_hash: str | None = None
    approved_version: ApprovedScenarioRecipeVersionProjection | None = None
    authoritative_draft_revision: int | None = None


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


def canonical_scenario_lab_command_content_identity(
    command: (
        CreateAiAssistedScenarioRecipeDraftCommand
        | CreateScenarioRecipeDraftCommand
        | ReviseScenarioRecipeDraftCommand
        | ValidateScenarioRecipeDraftCommand
        | ApproveScenarioRecipeCommand
    ),
) -> ScenarioLabCommandContentIdentity:
    """Calculate one durable Scenario Lab authoring/approval body identity."""

    if isinstance(command, CreateAiAssistedScenarioRecipeDraftCommand):
        value: object = {
            "operation": ScenarioLabTaskOperation.CREATE_RECIPE_DRAFT.value,
            "authoring_mode": ScenarioRecipeAuthoringMode.AI_ASSISTED.value,
            "intent": command.intent,
            "author_id": command.author_id.value,
        }
    elif isinstance(command, CreateScenarioRecipeDraftCommand):
        value = {
            "operation": ScenarioLabTaskOperation.CREATE_RECIPE_DRAFT.value,
            "payload": _canonical_recipe_payload(command.payload),
            "author_id": command.author_id.value,
            "authoring_mode": command.authoring_mode.value,
            "assistant_attempt_id": command.assistant_attempt_id,
        }
    elif isinstance(command, ReviseScenarioRecipeDraftCommand):
        value = {
            "operation": ScenarioLabTaskOperation.REVISE_RECIPE_DRAFT.value,
            "predecessor_draft_id": command.predecessor_draft_id.value,
            "expected_draft_revision": command.expected_draft_revision,
            "payload": _canonical_recipe_payload(command.payload),
            "author_id": command.author_id.value,
            "based_on_recipe_version_id": (
                None
                if command.based_on_recipe_version_id is None
                else command.based_on_recipe_version_id.value
            ),
        }
    elif isinstance(command, ValidateScenarioRecipeDraftCommand):
        value = {
            "operation": ScenarioLabTaskOperation.VALIDATE_RECIPE_DRAFT.value,
            "draft_id": command.draft_id.value,
            "expected_draft_revision": command.expected_draft_revision,
            "expected_payload_hash": command.expected_payload_hash,
        }
    else:
        value = {
            "operation": ScenarioLabTaskOperation.APPROVE_RECIPE.value,
            "draft_id": command.draft_id.value,
            "expected_draft_revision": command.expected_draft_revision,
            "expected_payload_hash": command.expected_payload_hash,
            "validation_id": command.validation_id.value,
            "actor_id": command.actor_id.value,
        }
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return ScenarioLabCommandContentIdentity(hashlib.sha256(encoded).hexdigest())


@runtime_checkable
class StrategyDiagnosticsV1ScenarioLabApplication(Protocol):
    @property
    def interface_version(self) -> ScenarioLabApplicationVersion: ...

    def read_inventory(self) -> ScenarioLabApplicationInventoryResult: ...

    def create_recipe_draft(
        self, command: CreateScenarioRecipeDraftCommand
    ) -> CreateScenarioRecipeDraftResult: ...

    def author_recipe_with_ai(
        self, command: CreateAiAssistedScenarioRecipeDraftCommand
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
                recipe_drafts = (
                    self._application.scenario_recipe_draft_revisions()
                )
                recipe_validations = (
                    self._application.scenario_recipe_validation_history()
                )
                recipe_approvals = (
                    self._application.scenario_recipe_approval_history()
                )
                authoring_capabilities = (
                    self._application.recipe_authoring_capabilities()
                )
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
                authoring_capabilities=_map_recipe_authoring_capabilities(
                    authoring_capabilities
                ),
                recipe_drafts=tuple(
                    _map_recipe_draft(item, catalog)
                    for item in recipe_drafts
                ),
                recipe_validations=tuple(
                    _map_recipe_validation(item)
                    for item in recipe_validations
                ),
                approved_recipe_versions=tuple(
                    _map_recipe_approval(item, catalog)
                    for item in recipe_approvals
                ),
            )
            partial = any(
                item.integrity is not ScenarioLabIntegrityState.VERIFIED
                for item in path_entries
            )
            availability = (
                ScenarioLabApplicationAvailability.PARTIAL
                if partial
                else ScenarioLabApplicationAvailability.READY
                if (
                    mapped_segments
                    or path_entries
                    or mapped_cases
                    or recipe_drafts
                    or recipe_approvals
                )
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
        operation = ScenarioLabTaskOperation.CREATE_RECIPE_DRAFT
        rejection = self._content_identity_rejection(command, operation)
        if rejection is not None:
            return CreateScenarioRecipeDraftResult(receipt=rejection)
        result = self._authoring_replay(command.metadata, operation)
        if result is None:
            conflict = self._source_conflict(command.metadata, operation)
            if conflict is not None:
                return CreateScenarioRecipeDraftResult(receipt=conflict)
            with self._application_access_gate:
                result = self._application.create_scenario_recipe_draft_command(
                    command_id=command.metadata.command_id.value,
                    idempotency_identity=(
                        command.metadata.idempotency_identity.value
                    ),
                    canonical_content_identity=(
                        command.metadata.canonical_content_identity.value
                    ),
                    expected_source_revision=(
                        command.metadata.expected_source_revision.value
                    ),
                    expected_source_generation=(
                        command.metadata.expected_source_generation.value
                    ),
                    payload=_recipe_payload_to_backend(command.payload),
                    author=command.author_id.value,
                    authoring_mode=command.authoring_mode.value,
                    assistant_attempt_id=command.assistant_attempt_id,
                )
        with self._application_access_gate:
            catalog = _map_catalog(
                self._application.transformation_catalog_view()
            )
        draft = (
            None
            if result.draft is None
            else _map_recipe_draft(result.draft, catalog)
        )
        return CreateScenarioRecipeDraftResult(
            receipt=_map_authoring_receipt(
                result,
                command.metadata,
                ScenarioLabTaskOperation.CREATE_RECIPE_DRAFT,
            ),
            draft_id=None if draft is None else draft.draft_id,
            draft_revision=None if draft is None else draft.revision,
            payload_hash=None if draft is None else draft.payload_hash,
            draft=draft,
        )

    def author_recipe_with_ai(
        self,
        command: CreateAiAssistedScenarioRecipeDraftCommand,
    ) -> CreateScenarioRecipeDraftResult:
        operation = ScenarioLabTaskOperation.CREATE_RECIPE_DRAFT
        rejection = self._content_identity_rejection(command, operation)
        if rejection is not None:
            return CreateScenarioRecipeDraftResult(receipt=rejection)
        result = self._authoring_replay(command.metadata, operation)
        if result is None:
            conflict = self._source_conflict(command.metadata, operation)
            if conflict is not None:
                return CreateScenarioRecipeDraftResult(receipt=conflict)
            with self._application_access_gate:
                capabilities = self._application.recipe_authoring_capabilities()
                if capabilities.get("ai_authoring_available") is not True:
                    return CreateScenarioRecipeDraftResult(
                        receipt=_unavailable_receipt(
                            command.metadata,
                            operation,
                            "No audited AI Recipe Assistant provider is configured.",
                        )
                    )
                result = self._application.author_scenario_recipe_draft_command(
                    command_id=command.metadata.command_id.value,
                    idempotency_identity=(
                        command.metadata.idempotency_identity.value
                    ),
                    canonical_content_identity=(
                        command.metadata.canonical_content_identity.value
                    ),
                    expected_source_revision=(
                        command.metadata.expected_source_revision.value
                    ),
                    expected_source_generation=(
                        command.metadata.expected_source_generation.value
                    ),
                    intent=command.intent,
                    author=command.author_id.value,
                )
        with self._application_access_gate:
            catalog = _map_catalog(
                self._application.transformation_catalog_view()
            )
        draft = (
            None
            if result.draft is None
            else _map_recipe_draft(result.draft, catalog)
        )
        return CreateScenarioRecipeDraftResult(
            receipt=_map_authoring_receipt(result, command.metadata, operation),
            draft_id=None if draft is None else draft.draft_id,
            draft_revision=None if draft is None else draft.revision,
            payload_hash=None if draft is None else draft.payload_hash,
            draft=draft,
        )

    def revise_recipe_draft(
        self, command: ReviseScenarioRecipeDraftCommand
    ) -> ReviseScenarioRecipeDraftResult:
        operation = ScenarioLabTaskOperation.REVISE_RECIPE_DRAFT
        rejection = self._content_identity_rejection(command, operation)
        if rejection is not None:
            return ReviseScenarioRecipeDraftResult(receipt=rejection)
        result = self._authoring_replay(command.metadata, operation)
        if result is None:
            conflict = self._source_conflict(command.metadata, operation)
            if conflict is not None:
                return ReviseScenarioRecipeDraftResult(receipt=conflict)
            with self._application_access_gate:
                result = self._application.revise_scenario_recipe_draft_command(
                    command_id=command.metadata.command_id.value,
                    idempotency_identity=(
                        command.metadata.idempotency_identity.value
                    ),
                    canonical_content_identity=(
                        command.metadata.canonical_content_identity.value
                    ),
                    expected_source_revision=(
                        command.metadata.expected_source_revision.value
                    ),
                    expected_source_generation=(
                        command.metadata.expected_source_generation.value
                    ),
                    predecessor_draft_id=command.predecessor_draft_id.value,
                    expected_draft_revision=command.expected_draft_revision,
                    payload=_recipe_payload_to_backend(command.payload),
                    author=command.author_id.value,
                    based_on_version_id=(
                        None
                        if command.based_on_recipe_version_id is None
                        else command.based_on_recipe_version_id.value
                    ),
                )
        with self._application_access_gate:
            catalog = _map_catalog(
                self._application.transformation_catalog_view()
            )
        draft = (
            None
            if result.draft is None
            else _map_recipe_draft(result.draft, catalog)
        )
        return ReviseScenarioRecipeDraftResult(
            receipt=_map_authoring_receipt(
                result,
                command.metadata,
                ScenarioLabTaskOperation.REVISE_RECIPE_DRAFT,
            ),
            draft_id=None if draft is None else draft.draft_id,
            draft_revision=None if draft is None else draft.revision,
            payload_hash=None if draft is None else draft.payload_hash,
            draft=draft,
            authoritative_draft_revision=(
                result.authoritative_draft_revision
            ),
        )

    def validate_recipe_draft(
        self, command: ValidateScenarioRecipeDraftCommand
    ) -> ValidateScenarioRecipeDraftResult:
        operation = ScenarioLabTaskOperation.VALIDATE_RECIPE_DRAFT
        rejection = self._content_identity_rejection(command, operation)
        if rejection is not None:
            return ValidateScenarioRecipeDraftResult(receipt=rejection)
        result = self._authoring_replay(command.metadata, operation)
        if result is None:
            conflict = self._source_conflict(command.metadata, operation)
            if conflict is not None:
                return ValidateScenarioRecipeDraftResult(receipt=conflict)
            with self._application_access_gate:
                result = (
                    self._application.validate_scenario_recipe_draft_command(
                        command_id=command.metadata.command_id.value,
                        idempotency_identity=(
                            command.metadata.idempotency_identity.value
                        ),
                        canonical_content_identity=(
                            command.metadata.canonical_content_identity.value
                        ),
                        expected_source_revision=(
                            command.metadata.expected_source_revision.value
                        ),
                        expected_source_generation=(
                            command.metadata.expected_source_generation.value
                        ),
                        draft_id=command.draft_id.value,
                        expected_draft_revision=command.expected_draft_revision,
                        expected_payload_hash=command.expected_payload_hash,
                    )
                )
        validation = (
            None
            if result.validation is None
            else _map_recipe_validation(result.validation)
        )
        return ValidateScenarioRecipeDraftResult(
            receipt=_map_authoring_receipt(
                result,
                command.metadata,
                ScenarioLabTaskOperation.VALIDATE_RECIPE_DRAFT,
            ),
            validation_id=(
                None if validation is None else validation.validation_id
            ),
            draft_id=None if validation is None else validation.draft_id,
            draft_revision=(
                None if validation is None else validation.draft_revision
            ),
            validation=validation,
            authoritative_draft_revision=(
                result.authoritative_draft_revision
            ),
        )

    def _authoring_replay(
        self,
        metadata: ScenarioLabCommandMetadata,
        operation: ScenarioLabTaskOperation,
    ) -> ScenarioLabAuthoringResult | None:
        with self._application_access_gate:
            return cast(
                "ScenarioLabAuthoringResult | None",
                self._application.replay_scenario_lab_authoring_command(
                    command_id=metadata.command_id.value,
                    idempotency_identity=(
                        metadata.idempotency_identity.value
                    ),
                    canonical_content_identity=(
                        metadata.canonical_content_identity.value
                    ),
                    operation=operation.value,
                ),
            )

    def _content_identity_rejection(
        self,
        command: (
            CreateAiAssistedScenarioRecipeDraftCommand
            | CreateScenarioRecipeDraftCommand
            | ReviseScenarioRecipeDraftCommand
            | ValidateScenarioRecipeDraftCommand
            | ApproveScenarioRecipeCommand
        ),
        operation: ScenarioLabTaskOperation,
    ) -> ScenarioLabCommandReceipt | None:
        calculated = canonical_scenario_lab_command_content_identity(command)
        if calculated == command.metadata.canonical_content_identity:
            return None
        current = self.read_inventory()
        return ScenarioLabCommandReceipt(
            metadata=command.metadata,
            operation=operation,
            disposition=ScenarioLabCommandDisposition.REJECTED,
            message=(
                "The canonical command content identity does not match the "
                "typed Scenario Lab command body."
            ),
            authoritative_revision=current.source_token,
            task_handle=None,
        )

    def _source_conflict(
        self,
        metadata: ScenarioLabCommandMetadata,
        operation: ScenarioLabTaskOperation,
    ) -> ScenarioLabCommandReceipt | None:
        current = self.read_inventory()
        if current.source_token == metadata.expected_source_revision:
            return None
        return ScenarioLabCommandReceipt(
            metadata=metadata,
            operation=operation,
            disposition=ScenarioLabCommandDisposition.CONFLICT,
            message="The expected Scenario Lab source revision is stale.",
            authoritative_revision=current.source_token,
            task_handle=None,
        )

    def approve_recipe(
        self, command: ApproveScenarioRecipeCommand
    ) -> ApproveScenarioRecipeResult:
        operation = ScenarioLabTaskOperation.APPROVE_RECIPE
        rejection = self._content_identity_rejection(command, operation)
        if rejection is not None:
            return ApproveScenarioRecipeResult(receipt=rejection)
        result = self._authoring_replay(command.metadata, operation)
        if result is None:
            conflict = self._source_conflict(command.metadata, operation)
            if conflict is not None:
                return ApproveScenarioRecipeResult(receipt=conflict)
            with self._application_access_gate:
                result = self._application.approve_scenario_recipe_command(
                    command_id=command.metadata.command_id.value,
                    idempotency_identity=(
                        command.metadata.idempotency_identity.value
                    ),
                    canonical_content_identity=(
                        command.metadata.canonical_content_identity.value
                    ),
                    expected_source_revision=(
                        command.metadata.expected_source_revision.value
                    ),
                    expected_source_generation=(
                        command.metadata.expected_source_generation.value
                    ),
                    draft_id=command.draft_id.value,
                    expected_draft_revision=command.expected_draft_revision,
                    expected_payload_hash=command.expected_payload_hash,
                    validation_id=command.validation_id.value,
                    actor=command.actor_id.value,
                )
        with self._application_access_gate:
            catalog = _map_catalog(
                self._application.transformation_catalog_view()
            )
        approved = (
            None
            if result.approval is None
            else _map_recipe_approval(result.approval, catalog)
        )
        return ApproveScenarioRecipeResult(
            receipt=_map_authoring_receipt(result, command.metadata, operation),
            recipe_version_id=(
                None if approved is None else approved.recipe_version_id
            ),
            recipe_content_hash=(
                None if approved is None else approved.content_hash
            ),
            approved_version=approved,
            authoritative_draft_revision=(
                result.authoritative_draft_revision
            ),
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


def _map_recipe_authoring_capabilities(
    payload: object,
) -> ScenarioRecipeAuthoringCapabilitiesProjection:
    if not isinstance(payload, dict):
        raise TypeError("Recipe authoring capabilities must be an object")
    manual = payload.get("manual_authoring_available")
    ai = payload.get("ai_authoring_available")
    if not isinstance(manual, bool) or not isinstance(ai, bool):
        raise TypeError("Recipe authoring capability flags must be boolean")
    provider = payload.get("ai_provider")
    model = payload.get("ai_model")
    if provider is not None and not isinstance(provider, str):
        raise TypeError("AI authoring provider must be text")
    if model is not None and not isinstance(model, str):
        raise TypeError("AI authoring model must be text")
    return ScenarioRecipeAuthoringCapabilitiesProjection(
        manual_authoring_available=manual,
        ai_authoring_available=ai,
        ai_provider=provider,
        ai_model=model,
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


def _recipe_payload_to_backend(
    payload: ScenarioRecipeDraftPayload,
) -> dict[str, object]:
    return {
        "schema_version": "scenario_recipe.v1",
        "name": payload.name,
        "historical_segment_id": payload.historical_segment_id.value,
        "transformations": [
            {
                "transformation_id": item.transformation_id,
                "parameters": {
                    parameter.name: parameter.value
                    for parameter in item.parameters
                },
            }
            for item in payload.transformations
        ],
        "execution_conditions": {
            "commission_bps": (
                payload.requested_execution_assumptions.commission_bps
            ),
            "slippage_bps": (
                payload.requested_execution_assumptions.slippage_bps
            ),
            "max_fill_fraction": (
                payload.requested_execution_assumptions.max_fill_fraction
            ),
            "latency_nodes": (
                payload.requested_execution_assumptions.latency_nodes
            ),
            "allow_partial_fills": (
                payload.requested_execution_assumptions.allow_partial_fills
            ),
        },
        "decision_cadence_minutes": payload.decision_cadence_minutes,
        "materialization_seed": payload.materialization_seed,
        "data_policy": "point-in-time",
        "market_rule_profile": payload.market_rule_profile_version,
    }


def _canonical_recipe_payload(
    payload: ScenarioRecipeDraftPayload,
) -> dict[str, object]:
    return {
        "name": payload.name,
        "historical_segment_id": payload.historical_segment_id.value,
        "transformations": [
            {
                "transformation_id": item.transformation_id,
                "parameters": [
                    {
                        "name": parameter.name,
                        "kind": parameter.kind.value,
                        "value": (
                            str(parameter.value)
                            if isinstance(parameter.value, Decimal)
                            else parameter.value
                        ),
                    }
                    for parameter in item.parameters
                ],
            }
            for item in payload.transformations
        ],
        "requested_execution_assumptions": {
            "commission_bps": (
                payload.requested_execution_assumptions.commission_bps
            ),
            "slippage_bps": (
                payload.requested_execution_assumptions.slippage_bps
            ),
            "max_fill_fraction": (
                payload.requested_execution_assumptions.max_fill_fraction
            ),
            "latency_nodes": (
                payload.requested_execution_assumptions.latency_nodes
            ),
            "allow_partial_fills": (
                payload.requested_execution_assumptions.allow_partial_fills
            ),
        },
        "decision_cadence_minutes": payload.decision_cadence_minutes,
        "materialization_seed": payload.materialization_seed,
        "data_policy": payload.data_policy.value,
        "market_rule_profile_version": payload.market_rule_profile_version,
    }


def _map_recipe_draft(
    record: ScenarioRecipeDraftRevisionRecord,
    catalog: TransformationCatalogProjection,
) -> ScenarioRecipeDraftProjection:
    payload = record.draft.payload
    raw_transformations = payload.get("transformations", ())
    if not isinstance(raw_transformations, list):
        raise TypeError("Stored Recipe Draft transformations must be a list")
    catalog_entries = {
        item.transformation_id: item for item in catalog.entries
    }
    transformations: list[ScenarioRecipeTransformationInput] = []
    for raw in raw_transformations:
        if not isinstance(raw, dict):
            raise TypeError("Stored Recipe Draft transformation must be an object")
        transformation_id = str(raw.get("transformation_id") or "")
        parameters = raw.get("parameters", {})
        if not isinstance(parameters, dict):
            raise TypeError("Stored Recipe Draft parameters must be an object")
        entry = catalog_entries.get(transformation_id)
        definitions = (
            {} if entry is None else {item.name: item for item in entry.parameters}
        )
        mapped_parameters: list[ScenarioRecipeParameterInput] = []
        for name, value in sorted(parameters.items()):
            definition = definitions.get(str(name))
            value_type = "enum" if definition is None else definition.value_type
            if value_type == "decimal":
                kind = ScenarioRecipeParameterKind.DECIMAL
                mapped_value: ScenarioRecipeParameterValue = Decimal(str(value))
            elif value_type == "integer":
                kind = ScenarioRecipeParameterKind.INTEGER
                mapped_value = int(str(value))
            elif value_type == "boolean":
                kind = ScenarioRecipeParameterKind.BOOLEAN
                if not isinstance(value, bool):
                    raise TypeError(
                        "Stored Recipe Draft boolean parameter must be boolean"
                    )
                mapped_value = value
            else:
                kind = ScenarioRecipeParameterKind.CHOICE
                mapped_value = str(value)
            mapped_parameters.append(
                ScenarioRecipeParameterInput(
                    name=str(name),
                    kind=kind,
                    value=mapped_value,
                )
            )
        transformations.append(
            ScenarioRecipeTransformationInput(
                transformation_id=transformation_id,
                parameters=tuple(mapped_parameters),
            )
        )
    execution = payload.get("execution_conditions")
    if not isinstance(execution, dict):
        raise TypeError("Stored Recipe execution conditions must be an object")
    return ScenarioRecipeDraftProjection(
        draft_id=ScenarioRecipeDraftId(record.draft.draft_id),
        recipe_id=record.draft.recipe_id,
        revision=record.revision,
        payload=ScenarioRecipeDraftPayload(
            name=str(payload.get("name") or ""),
            historical_segment_id=HistoricalMarketSegmentId(
                str(payload.get("historical_segment_id") or "")
            ),
            transformations=tuple(transformations),
            requested_execution_assumptions=(
                RequestedExecutionAssumptionsProjection(
                    commission_bps=str(execution.get("commission_bps", "3")),
                    slippage_bps=str(execution.get("slippage_bps", "0")),
                    max_fill_fraction=str(
                        execution.get("max_fill_fraction", "1")
                    ),
                    latency_nodes=int(
                        str(execution.get("latency_nodes", 0))
                    ),
                    allow_partial_fills=(
                        True
                        if "allow_partial_fills" not in execution
                        else _required_bool(
                            execution,
                            "allow_partial_fills",
                        )
                    ),
                )
            ),
            decision_cadence_minutes=int(
                str(payload.get("decision_cadence_minutes"))
            ),
            materialization_seed=int(
                str(payload.get("materialization_seed"))
            ),
            data_policy=ScenarioRecipeDataPolicy.POINT_IN_TIME,
            market_rule_profile_version=str(
                payload.get("market_rule_profile") or ""
            ),
        ),
        payload_hash=record.draft.payload_hash,
        author_id=ScenarioLabActorId(record.draft.author),
        created_at=record.draft.created_at,
        predecessor_draft_id=(
            None
            if record.predecessor_draft_id is None
            else ScenarioRecipeDraftId(record.predecessor_draft_id)
        ),
        based_on_recipe_version_id=(
            None
            if record.draft.based_on_version_id is None
            else ApprovedScenarioRecipeVersionId(
                record.draft.based_on_version_id
            )
        ),
        authoring_mode=ScenarioRecipeAuthoringMode(record.authoring_mode),
        assistant_attempt_id=record.assistant_attempt_id,
    )


def _map_recipe_validation(
    record: ScenarioRecipeValidationRecord,
) -> ScenarioRecipeValidationProjection:
    return ScenarioRecipeValidationProjection(
        validation_id=ScenarioRecipeValidationId(record.validation_id),
        draft_id=ScenarioRecipeDraftId(record.result.draft_id),
        draft_revision=record.draft_revision,
        payload_hash=record.result.payload_hash,
        is_valid=record.result.is_valid,
        findings=tuple(
            ScenarioRecipeValidationFindingProjection(
                path=tuple(item.path.split(".")),
                rule_code=item.rule,
                severity=ScenarioRecipeValidationSeverity.ERROR,
                explanation=item.message,
                correction=item.correction,
                retryable=(
                    item.rule == "data.admitted-segment-required"
                ),
                different_input_required=(
                    item.rule != "data.admitted-segment-required"
                ),
            )
            for item in record.result.issues
        ),
        dependencies=_map_recipe_dependencies(record.dependencies),
        recipe_content_hash=record.result.recipe_content_hash,
        validated_at=record.result.validated_at,
    )


def _map_recipe_approval(
    record: ScenarioRecipeApprovalRecord,
    catalog: TransformationCatalogProjection,
) -> ApprovedScenarioRecipeVersionProjection:
    version = record.version
    draft = _map_recipe_draft(record.draft, catalog)
    validation = (
        None
        if record.validation is None
        else _map_recipe_validation(record.validation)
    )
    if validation is None:
        if (
            version.validation_identity is not None
            or version.validation_result.draft_id != draft.draft_id.value
            or version.validation_result.payload_hash != draft.payload_hash
            or version.content_hash
            != version.validation_result.recipe_content_hash
        ):
            raise ValueError(
                "Historical Approved Recipe projection evidence is inconsistent"
            )
    elif (
        version.validation_identity != validation.validation_id.value
        or version.validation_result.draft_id != draft.draft_id.value
        or version.validation_result.payload_hash != draft.payload_hash
        or version.content_hash != validation.recipe_content_hash
    ):
        raise ValueError(
            "Approved Scenario Recipe projection evidence is inconsistent"
        )
    authority_state = ScenarioRecipeApprovalAuthorityState(
        record.authority_state
    )
    reasons: tuple[ScenarioLabUnavailabilityReason, ...] = ()
    if authority_state is not ScenarioRecipeApprovalAuthorityState.CURRENT:
        code = {
            ScenarioRecipeApprovalAuthorityState.OUTDATED: (
                ScenarioLabUnavailabilityCode.RECIPE_APPROVAL_OUTDATED
            ),
            ScenarioRecipeApprovalAuthorityState.INCOMPATIBLE: (
                ScenarioLabUnavailabilityCode.RECIPE_APPROVAL_INCOMPATIBLE
            ),
            ScenarioRecipeApprovalAuthorityState.UNAVAILABLE: (
                ScenarioLabUnavailabilityCode.RECIPE_APPROVAL_DEPENDENCY_UNAVAILABLE
            ),
        }[authority_state]
        reasons = (
            ScenarioLabUnavailabilityReason(
                code=code,
                summary=record.authority_message,
                corrective_guidance=(
                    "Reread authoritative dependencies, create a successor Draft, "
                    "then validate and approve the exact corrected revision."
                ),
            ),
        )
    return ApprovedScenarioRecipeVersionProjection(
        recipe_version_id=ApprovedScenarioRecipeVersionId(version.version_id),
        recipe_id=version.recipe_id,
        version_number=version.version_number,
        content_hash=version.content_hash,
        payload=draft.payload,
        author_id=ScenarioLabActorId(version.author),
        approval=ScenarioRecipeApprovalProjection(
            approval_id=ScenarioRecipeApprovalId(record.approval_id),
            draft_id=draft.draft_id,
            draft_revision=(
                None if record.validation is None else record.validation.draft_revision
            ),
            payload_hash=draft.payload_hash,
            validation_id=(
                None if validation is None else validation.validation_id
            ),
            recipe_content_hash=version.content_hash,
            actor_id=ScenarioLabActorId(version.approval_actor),
            approved_at=version.approved_at,
            dependencies=(
                None if validation is None else validation.dependencies
            ),
        ),
        based_on_recipe_version_id=(
            None
            if version.based_on_version_id is None
            else ApprovedScenarioRecipeVersionId(version.based_on_version_id)
        ),
        authority_state=authority_state,
        authority_reasons=reasons,
        can_materialize=record.can_materialize,
    )


def _map_recipe_dependencies(
    value: ScenarioRecipeValidationDependencyRecord,
) -> ScenarioRecipeValidationDependenciesProjection:
    return ScenarioRecipeValidationDependenciesProjection(
        historical_segment_id=HistoricalMarketSegmentId(
            value.historical_segment_id
        ),
        historical_segment_content_hash=(
            value.historical_segment_content_hash
        ),
        source_snapshot_id=SourceSnapshotId(value.source_snapshot_id),
        source_snapshot_content_hash=value.source_snapshot_content_hash,
        recipe_schema_identity=value.recipe_schema_identity,
        recipe_schema_hash=value.recipe_schema_hash,
        transformation_catalog_version=(
            value.transformation_catalog_version
        ),
        transformation_catalog_hash=value.transformation_catalog_hash,
        transformation_implementation_identities=(
            value.transformation_implementation_identities
        ),
        data_policy=ScenarioRecipeDataPolicy.POINT_IN_TIME,
        causality_rule_identities=value.causality_rule_identities,
        market_rule_profile_version=value.market_rule_profile_version,
        market_rule_profile_hash=value.market_rule_profile_hash,
        compatibility_observations=tuple(
            ScenarioRecipeCompatibilityObservation(
                subject=subject,
                state=ScenarioRecipeCompatibilityState(state),
                explanation=explanation,
            )
            for subject, state, explanation in value.compatibility_observations
        ),
    )


def _map_authoring_receipt(
    result: ScenarioLabAuthoringResult,
    fallback_metadata: ScenarioLabCommandMetadata,
    operation: ScenarioLabTaskOperation,
) -> ScenarioLabCommandReceipt:
    command = result.command
    metadata = (
        fallback_metadata
        if command is None
        else ScenarioLabCommandMetadata(
            command_id=ScenarioLabCommandId(command.command_id),
            idempotency_identity=ScenarioLabIdempotencyIdentity(
                command.idempotency_identity
            ),
            canonical_content_identity=ScenarioLabCommandContentIdentity(
                command.canonical_content_identity
            ),
            expected_source_revision=SourceRevisionToken(
                command.expected_source_revision
            ),
            expected_source_generation=SourceGenerationId(
                command.expected_source_generation
            ),
        )
    )
    return ScenarioLabCommandReceipt(
        metadata=metadata,
        operation=operation,
        disposition=ScenarioLabCommandDisposition(result.disposition),
        message=result.message,
        authoritative_revision=(
            None
            if command is None
            else SourceRevisionToken(command.expected_source_revision)
        ),
        task_handle=None,
    )


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


def _required_bool(container: object, key: str) -> bool:
    if not isinstance(container, dict):
        raise TypeError("Expected object")
    value = container.get(key)
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be boolean")
    return value


def _text_tuple(container: object, key: str) -> tuple[str, ...]:
    if not isinstance(container, dict):
        raise TypeError("Expected object")
    values = container.get(key)
    if not isinstance(values, list):
        raise TypeError(f"{key} must be a list")
    return tuple(str(value) for value in values)


__all__ = [
    "AppliedTransformationProjection",
    "ApprovedScenarioRecipeVersionProjection",
    "ApproveScenarioRecipeCommand",
    "ApproveScenarioRecipeResult",
    "ComposeFormalScenarioSetCommand",
    "ComposeFormalScenarioSetResult",
    "CreateAiAssistedScenarioRecipeDraftCommand",
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
    "ScenarioRecipeAuthoringCapabilitiesProjection",
    "ScenarioRecipeAuthoringMode",
    "ScenarioRecipeApprovalAuthorityState",
    "ScenarioRecipeApprovalId",
    "ScenarioRecipeApprovalProjection",
    "ScenarioRecipeDataPolicy",
    "ScenarioRecipeCompatibilityObservation",
    "ScenarioRecipeCompatibilityState",
    "ScenarioRecipeDraftId",
    "ScenarioRecipeDraftPayload",
    "ScenarioRecipeDraftProjection",
    "ScenarioRecipeParameterInput",
    "ScenarioRecipeParameterKind",
    "ScenarioRecipeParameterValue",
    "ScenarioRecipeTransformationInput",
    "ScenarioRecipeValidationDependenciesProjection",
    "ScenarioRecipeValidationFindingProjection",
    "ScenarioRecipeValidationId",
    "ScenarioRecipeValidationProjection",
    "ScenarioRecipeValidationSeverity",
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
    "canonical_scenario_lab_command_content_identity",
]
