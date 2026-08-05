"""Scenario Lab Feature Interface 1.0 contract."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Protocol, runtime_checkable

from .run_monitoring import (
    Completeness,
    Freshness,
    SourceGenerationId,
    SourceKind,
    StructuredFeatureError,
    Subscription,
    ViewPhase,
)
from .scenario_lab_application import (
    ApprovedScenarioRecipeVersionProjection,
    ApproveScenarioRecipeCommand,
    ApproveScenarioRecipeResult,
    ComposeFormalScenarioSetCommand,
    ComposeFormalScenarioSetResult,
    CreateAiAssistedScenarioRecipeDraftCommand,
    CreateScenarioRecipeDraftCommand,
    CreateScenarioRecipeDraftResult,
    HistoricalSegmentEntry,
    MaterializeApprovedScenarioRecipeCommand,
    MaterializeApprovedScenarioRecipeResult,
    MarketScenarioEntry,
    ReferenceMarketPathEntry,
    ScenarioLabInventory,
    FormalScenarioSetProjection,
    ScenarioExecutionResolutionProjection,
    ScenarioSelectionContextProjection,
    ScenarioLabTaskHandle,
    ScenarioRecipeDraftProjection,
    ScenarioRecipeValidationProjection,
    ResolveScenarioExecutionAssumptionsCommand,
    ResolveScenarioExecutionAssumptionsResult,
    RetryScenarioMaterializationCommand,
    RetryScenarioMaterializationResult,
    ReviseScenarioRecipeDraftCommand,
    ReviseScenarioRecipeDraftResult,
    SelectFormalScenarioSetCommand,
    SelectFormalScenarioSetResult,
    TransformationCatalogProjection,
    ValidateScenarioRecipeDraftCommand,
    ValidateScenarioRecipeDraftResult,
)
from .strategy_diagnostics_v1_read_model import SourceRevisionToken
from .versioning import FeatureInterfaceVersion


class ScenarioLabPresentationState(str, Enum):
    LOADING = "loading"
    EMPTY = "empty"
    READY = "ready"
    PARTIAL = "partial"
    STALE = "stale"
    DISCONNECTED = "disconnected"
    FAILED = "failed"


class ScenarioLabFocusTarget(str, Enum):
    SEARCH = "search"
    HISTORICAL_SEGMENT = "historical_segment"
    REFERENCE_PATH = "reference_path"
    MARKET_SCENARIO = "market_scenario"
    TRANSFORMATION_CATALOG = "transformation_catalog"
    RECIPE_AUTHORING = "recipe_authoring"


@dataclass(frozen=True, slots=True)
class ScenarioLabContext:
    search_text: str = ""
    markets: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    recipe_versions: tuple[str, ...] = ()
    layers: tuple[str, ...] = ()
    transformation_families: tuple[str, ...] = ()
    compatibilities: tuple[str, ...] = ()
    reproducibilities: tuple[str, ...] = ()
    reconstructed: bool | None = None
    focus_target: ScenarioLabFocusTarget = ScenarioLabFocusTarget.SEARCH
    focus_identity: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "search_text", " ".join(self.search_text.split()))
        dimensions = (
            self.markets,
            self.sources,
            self.recipe_versions,
            self.layers,
            self.transformation_families,
            self.compatibilities,
            self.reproducibilities,
        )
        if any(len(values) != len(set(values)) for values in dimensions):
            raise ValueError("Scenario Lab filters must be unique")
        if any(not value.strip() for values in dimensions for value in values):
            raise ValueError("Scenario Lab filters cannot be empty")
        if self.focus_target is not ScenarioLabFocusTarget.SEARCH and not self.focus_identity:
            raise ValueError("Scenario Lab detail focus requires an identity")


@dataclass(frozen=True, slots=True)
class ScenarioLabCapabilities:
    can_browse: bool
    can_search: bool
    can_filter: bool
    can_inspect_bounded_preview: bool
    can_create_recipe_draft: bool
    can_create_ai_assisted_recipe_draft: bool
    can_revise_recipe_draft: bool
    can_validate_recipe_draft: bool
    can_approve_recipe: bool
    can_materialize_reference_path: bool
    can_retry_materialization: bool
    can_compose_scenario_set: bool
    can_resolve_execution_assumptions: bool
    can_select_formal_scenario_set: bool

    @classmethod
    def read_only(cls) -> "ScenarioLabCapabilities":
        return cls(
            can_browse=True,
            can_search=True,
            can_filter=True,
            can_inspect_bounded_preview=True,
            can_create_recipe_draft=False,
            can_create_ai_assisted_recipe_draft=False,
            can_revise_recipe_draft=False,
            can_validate_recipe_draft=False,
            can_approve_recipe=False,
            can_materialize_reference_path=False,
            can_retry_materialization=False,
            can_compose_scenario_set=False,
            can_resolve_execution_assumptions=False,
            can_select_formal_scenario_set=False,
        )


class ScenarioLabBlockingCode(str, Enum):
    INVENTORY_PARTIAL = "scenario_lab_inventory_partial"
    INVENTORY_READ_FAILED = "scenario_lab_inventory_read_failed"
    SOURCE_DISCONNECTED = "scenario_lab_source_disconnected"
    SOURCE_RECONNECTING = "scenario_lab_source_reconnecting"
    RECIPE_DRAFT_NOT_YET_AVAILABLE = "recipe_draft_not_yet_available"
    RECIPE_APPROVAL_NOT_YET_AVAILABLE = "recipe_approval_not_yet_available"
    MATERIALIZATION_NOT_YET_AVAILABLE = "materialization_not_yet_available"
    SCENARIO_COMPOSITION_NOT_YET_AVAILABLE = "scenario_composition_not_yet_available"


@dataclass(frozen=True, slots=True)
class ScenarioLabBlockingReason:
    code: ScenarioLabBlockingCode
    message: str
    dependent_operations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScenarioLabSource:
    kind: SourceKind
    identity: str
    generation: SourceGenerationId


@dataclass(frozen=True, slots=True)
class ScenarioLabViewState:
    interface_version: FeatureInterfaceVersion
    revision: int
    observed_at: datetime
    last_reliable_at: datetime | None
    freshness: Freshness
    age: timedelta
    freshness_threshold: timedelta
    source: ScenarioLabSource
    source_revision: SourceRevisionToken | None
    context: ScenarioLabContext
    phase: ViewPhase
    presentation: ScenarioLabPresentationState
    completeness: Completeness
    historical_segments: tuple[HistoricalSegmentEntry, ...]
    reference_paths: tuple[ReferenceMarketPathEntry, ...]
    market_scenarios: tuple[MarketScenarioEntry, ...]
    transformation_catalog: TransformationCatalogProjection | None
    recipe_drafts: tuple[ScenarioRecipeDraftProjection, ...]
    recipe_validations: tuple[ScenarioRecipeValidationProjection, ...]
    approved_recipe_versions: tuple[
        ApprovedScenarioRecipeVersionProjection, ...
    ]
    task_handles: tuple[ScenarioLabTaskHandle, ...]
    last_reliable_inventory: ScenarioLabInventory | None
    capabilities: ScenarioLabCapabilities
    blocking_reasons: tuple[ScenarioLabBlockingReason, ...]
    focus_restoration_identity: str | None
    error: StructuredFeatureError | None
    scenario_sets: tuple[FormalScenarioSetProjection, ...] = ()
    execution_resolutions: tuple[
        ScenarioExecutionResolutionProjection, ...
    ] = ()
    selection_contexts: tuple[ScenarioSelectionContextProjection, ...] = ()


ScenarioLabObserver = Callable[[ScenarioLabViewState], None]


@runtime_checkable
class ScenarioLabFeature(Protocol):
    @property
    def interface_version(self) -> FeatureInterfaceVersion: ...

    def snapshot(self, context: ScenarioLabContext) -> ScenarioLabViewState: ...

    def subscribe(
        self,
        context: ScenarioLabContext,
        observer: ScenarioLabObserver,
    ) -> Subscription: ...

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

    def close(self) -> None: ...


__all__ = [
    "ScenarioLabBlockingCode",
    "ScenarioLabBlockingReason",
    "ScenarioLabCapabilities",
    "ScenarioLabContext",
    "ScenarioLabFeature",
    "ScenarioLabFocusTarget",
    "ScenarioLabObserver",
    "ScenarioLabPresentationState",
    "ScenarioLabSource",
    "ScenarioLabViewState",
]
