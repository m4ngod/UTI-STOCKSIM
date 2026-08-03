"""Strategy Library Feature Interface 1.0 contract."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Protocol, runtime_checkable

from .diagnostic_tasks_application import GuardrailProfileId
from .run_monitoring import (
    Completeness,
    Freshness,
    SourceGenerationId,
    SourceKind,
    StrategyUnderTestId,
    StructuredFeatureError,
    Subscription,
    ViewPhase,
)
from .strategy_diagnostics_v1_read_model import SourceRevisionToken
from .strategy_library_application import (
    FormalStrategySelectionReference,
    StrategyAvailability,
    StrategyLibraryEntry,
    StrategyLibraryInventory,
)
from .versioning import FeatureInterfaceVersion


class StrategyLibraryAvailabilityFilter(str, Enum):
    ALL = "all"
    FORMAL_CAMPAIGN_READY = "formal_campaign_ready"
    UNAVAILABLE = "unavailable"
    OUTDATED = "outdated"
    INCOMPATIBLE = "incompatible"
    MISSING_DEPENDENCY = "missing_dependency"


@dataclass(frozen=True, slots=True)
class StrategyLibraryContext:
    search_text: str = ""
    availability_filter: StrategyLibraryAvailabilityFilter = (
        StrategyLibraryAvailabilityFilter.ALL
    )
    required_capabilities: tuple[str, ...] = ()
    focus_strategy_id: StrategyUnderTestId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.search_text, str):
            raise TypeError("Strategy Library search text must be a string")
        normalized = " ".join(self.search_text.split())
        object.__setattr__(self, "search_text", normalized)
        if any(
            not isinstance(item, str) or not item.strip()
            for item in self.required_capabilities
        ):
            raise ValueError("Strategy capability filters cannot be empty")
        if len(self.required_capabilities) != len(
            set(self.required_capabilities)
        ):
            raise ValueError("Strategy capability filters must be unique")


class StrategyLibraryPresentationState(str, Enum):
    LOADING = "loading"
    EMPTY = "empty"
    READY = "ready"
    PARTIAL = "partial"
    STALE = "stale"
    DISCONNECTED = "disconnected"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StrategyLibraryCapabilities:
    can_search: bool
    can_filter: bool
    can_inspect_details: bool
    can_compare: bool
    can_select_formal_strategy_set: bool


class StrategyLibraryBlockingCode(str, Enum):
    INVENTORY_PARTIAL = "strategy_library_inventory_partial"
    INVENTORY_READ_FAILED = "strategy_library_inventory_read_failed"
    SOURCE_DISCONNECTED = "strategy_library_source_disconnected"
    SOURCE_RECONNECTING = "strategy_library_source_reconnecting"
    FORMAL_SELECTION_NOT_YET_AVAILABLE = (
        "formal_strategy_selection_not_yet_available"
    )


@dataclass(frozen=True, slots=True)
class StrategyLibraryBlockingReason:
    code: StrategyLibraryBlockingCode
    message: str
    dependent_operations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrategyLibrarySource:
    kind: SourceKind
    identity: str
    generation: SourceGenerationId


@dataclass(frozen=True, slots=True)
class StrategyLibraryViewState:
    interface_version: FeatureInterfaceVersion
    revision: int
    observed_at: datetime
    last_reliable_at: datetime | None
    freshness: Freshness
    age: timedelta
    freshness_threshold: timedelta
    source: StrategyLibrarySource
    source_revision: SourceRevisionToken | None
    context: StrategyLibraryContext
    phase: ViewPhase
    presentation: StrategyLibraryPresentationState
    completeness: Completeness
    entries: tuple[StrategyLibraryEntry, ...]
    last_reliable_inventory: StrategyLibraryInventory | None
    capabilities: StrategyLibraryCapabilities
    blocking_reasons: tuple[StrategyLibraryBlockingReason, ...]
    focus_restoration_id: StrategyUnderTestId | None
    error: StructuredFeatureError | None


@dataclass(frozen=True, slots=True)
class CompareStrategies:
    strategy_ids: tuple[StrategyUnderTestId, ...]
    expected_source_revision: SourceRevisionToken
    expected_source_generation: SourceGenerationId


class StrategyComparisonDisposition(str, Enum):
    AVAILABLE = "available"
    INVALID_SELECTION = "invalid_selection"
    SOURCE_CONFLICT = "source_conflict"
    NOT_YET_AVAILABLE = "not_yet_available"


@dataclass(frozen=True, slots=True)
class StrategyComparisonResult:
    disposition: StrategyComparisonDisposition
    entries: tuple[StrategyLibraryEntry, ...]
    message: str


@dataclass(frozen=True, slots=True)
class SelectFormalStrategySet:
    strategy_ids: tuple[StrategyUnderTestId, ...]
    guardrail_profile_ids: tuple[GuardrailProfileId, ...]
    expected_source_revision: SourceRevisionToken
    expected_source_generation: SourceGenerationId
    originating_view_revision: int


class StrategySelectionDisposition(str, Enum):
    SELECTED = "selected"
    INVALID_SELECTION = "invalid_selection"
    SOURCE_CONFLICT = "source_conflict"
    UNAVAILABLE = "unavailable"
    NOT_YET_AVAILABLE = "not_yet_available"


@dataclass(frozen=True, slots=True)
class StrategySelectionContext:
    context_identity: str
    selections: tuple[FormalStrategySelectionReference, ...]
    source_revision: SourceRevisionToken
    originating_view_revision: int
    source_generation: SourceGenerationId


@dataclass(frozen=True, slots=True)
class StrategySelectionResult:
    disposition: StrategySelectionDisposition
    selection: StrategySelectionContext | None
    message: str


StrategyLibraryObserver = Callable[[StrategyLibraryViewState], None]


@runtime_checkable
class StrategyLibraryFeature(Protocol):
    @property
    def interface_version(self) -> FeatureInterfaceVersion: ...

    def snapshot(
        self,
        context: StrategyLibraryContext,
    ) -> StrategyLibraryViewState: ...

    def subscribe(
        self,
        context: StrategyLibraryContext,
        observer: StrategyLibraryObserver,
    ) -> Subscription: ...

    def compare_strategies(
        self,
        command: CompareStrategies,
    ) -> StrategyComparisonResult: ...

    def select_formal_strategy_set(
        self,
        command: SelectFormalStrategySet,
    ) -> StrategySelectionResult: ...

    def close(self) -> None: ...


__all__ = [
    "CompareStrategies",
    "SelectFormalStrategySet",
    "StrategyComparisonDisposition",
    "StrategyComparisonResult",
    "StrategyLibraryAvailabilityFilter",
    "StrategyLibraryBlockingCode",
    "StrategyLibraryBlockingReason",
    "StrategyLibraryCapabilities",
    "StrategyLibraryContext",
    "StrategyLibraryFeature",
    "StrategyLibraryObserver",
    "StrategyLibraryPresentationState",
    "StrategyLibrarySource",
    "StrategyLibraryViewState",
    "StrategySelectionContext",
    "StrategySelectionDisposition",
    "StrategySelectionResult",
]
