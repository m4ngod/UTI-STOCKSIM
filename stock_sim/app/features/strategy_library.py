"""Strategy Library Feature Interface 1.0 contract."""

from __future__ import annotations

import json
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
    StrategyDependencyIdentity,
    StrategyDependencyKind,
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


class StrategyLibraryFocusTarget(str, Enum):
    SEARCH = "search"
    COMPARE_FORMAL_SET = "compare_formal_set"
    SELECT_FORMAL_SET = "select_formal_set"
    STRATEGY_DETAILS = "strategy_details"


@dataclass(frozen=True, slots=True)
class StrategySelectionBookmark:
    selections: tuple[FormalStrategySelectionReference, ...]
    route_identity: str = "strategy_library"
    source_generation: SourceGenerationId | None = None
    focus_target: StrategyLibraryFocusTarget = (
        StrategyLibraryFocusTarget.SELECT_FORMAL_SET
    )
    focus_strategy_id: StrategyUnderTestId | None = None

    def __post_init__(self) -> None:
        if self.route_identity != "strategy_library":
            raise ValueError("Strategy bookmark route must be strategy_library")
        if not self.selections:
            raise ValueError("Strategy bookmark must contain an exact selection")
        if len(self.strategy_ids) != len(set(self.strategy_ids)):
            raise ValueError("Strategy bookmark identities must be unique")
        if (
            self.focus_target is StrategyLibraryFocusTarget.STRATEGY_DETAILS
            and self.focus_strategy_id is None
        ):
            raise ValueError("Strategy details focus requires a Strategy identity")
        if (
            self.focus_strategy_id is not None
            and self.focus_strategy_id not in self.strategy_ids
        ):
            raise ValueError("Strategy bookmark focus must be in the formal set")

    @property
    def strategy_ids(self) -> tuple[StrategyUnderTestId, ...]:
        return tuple(item.strategy_id for item in self.selections)

    @property
    def guardrail_profile_ids(self) -> tuple[GuardrailProfileId, ...]:
        return tuple(item.guardrail_profile_id for item in self.selections)


def encode_strategy_selection_bookmark(
    bookmark: StrategySelectionBookmark,
) -> str:
    """Serialize only immutable backend-owned identities for product reopen."""

    payload = {
        "route_identity": bookmark.route_identity,
        "source_generation": (
            None
            if bookmark.source_generation is None
            else bookmark.source_generation.value
        ),
        "focus_target": bookmark.focus_target.value,
        "focus_strategy_id": (
            None
            if bookmark.focus_strategy_id is None
            else bookmark.focus_strategy_id.value
        ),
        "selections": [
            {
                "strategy_id": selection.strategy_id.value,
                "strategy_version": selection.strategy_version,
                "manifest_content_hash": selection.manifest_content_hash,
                "guardrail_profile_id": selection.guardrail_profile_id.value,
                "guardrail_profile_version": (
                    selection.guardrail_profile_version
                ),
                "dependency_identities": [
                    {
                        "kind": dependency.kind.value,
                        "identity": dependency.identity,
                        "version": dependency.version,
                        "content_hash": dependency.content_hash,
                        "available": dependency.available,
                        "compatible": dependency.compatible,
                    }
                    for dependency in selection.dependency_identities
                ],
            }
            for selection in bookmark.selections
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def decode_strategy_selection_bookmark(
    payload: object,
) -> StrategySelectionBookmark | None:
    """Decode a durable bookmark, rejecting partial or structurally invalid data."""

    if not isinstance(payload, str) or not payload.strip():
        return None
    try:
        raw = json.loads(payload)
        if not isinstance(raw, dict):
            return None
        raw_selections = raw.get("selections")
        if not isinstance(raw_selections, list):
            return None
        selections: list[FormalStrategySelectionReference] = []
        for raw_selection in raw_selections:
            if not isinstance(raw_selection, dict):
                return None
            raw_dependencies = raw_selection.get("dependency_identities")
            if not isinstance(raw_dependencies, list):
                return None
            dependencies: list[StrategyDependencyIdentity] = []
            for raw_dependency in raw_dependencies:
                if not isinstance(raw_dependency, dict):
                    return None
                available = raw_dependency.get("available")
                compatible = raw_dependency.get("compatible")
                if not isinstance(available, bool) or not isinstance(
                    compatible, bool
                ):
                    return None
                dependencies.append(
                    StrategyDependencyIdentity(
                        kind=StrategyDependencyKind(
                            _bookmark_string(raw_dependency, "kind")
                        ),
                        identity=_bookmark_string(raw_dependency, "identity"),
                        version=_bookmark_string(raw_dependency, "version"),
                        content_hash=_bookmark_string(
                            raw_dependency, "content_hash"
                        ),
                        available=available,
                        compatible=compatible,
                    )
                )
            selections.append(
                FormalStrategySelectionReference(
                    strategy_id=StrategyUnderTestId(
                        _bookmark_string(raw_selection, "strategy_id")
                    ),
                    strategy_version=_bookmark_string(
                        raw_selection, "strategy_version"
                    ),
                    manifest_content_hash=_bookmark_string(
                        raw_selection, "manifest_content_hash"
                    ),
                    guardrail_profile_id=GuardrailProfileId(
                        _bookmark_string(
                            raw_selection, "guardrail_profile_id"
                        )
                    ),
                    guardrail_profile_version=_bookmark_string(
                        raw_selection, "guardrail_profile_version"
                    ),
                    dependency_identities=tuple(dependencies),
                )
            )
        raw_focus = raw.get("focus_strategy_id")
        if raw_focus is not None and not isinstance(raw_focus, str):
            return None
        raw_generation = raw.get("source_generation")
        if raw_generation is not None and (
            not isinstance(raw_generation, int) or raw_generation < 1
        ):
            return None
        return StrategySelectionBookmark(
            selections=tuple(selections),
            route_identity=_bookmark_string(raw, "route_identity"),
            source_generation=(
                None
                if raw_generation is None
                else SourceGenerationId(raw_generation)
            ),
            focus_target=StrategyLibraryFocusTarget(
                _bookmark_string(raw, "focus_target")
            ),
            focus_strategy_id=(
                None if raw_focus is None else StrategyUnderTestId(raw_focus)
            ),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _bookmark_string(container: object, key: str) -> str:
    if not isinstance(container, dict):
        raise TypeError("Bookmark container must be an object")
    value = container.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Bookmark field {key} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class StrategyLibraryContext:
    search_text: str = ""
    availability_filter: StrategyLibraryAvailabilityFilter = (
        StrategyLibraryAvailabilityFilter.ALL
    )
    required_capabilities: tuple[str, ...] = ()
    focus_strategy_id: StrategyUnderTestId | None = None
    selection_bookmark: StrategySelectionBookmark | None = None

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
    FORMAL_SELECTION_STALE = "formal_strategy_selection_stale"


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


class StrategySelectionStatus(str, Enum):
    NONE = "none"
    CURRENT = "current"
    STALE = "stale"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"


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
    selection: StrategySelectionContext | None = None
    selection_status: StrategySelectionStatus = StrategySelectionStatus.NONE
    selection_message: str = "No formal Strategy set is selected."


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
    "StrategyLibraryFocusTarget",
    "StrategyLibraryObserver",
    "StrategyLibraryPresentationState",
    "StrategyLibrarySource",
    "StrategyLibraryViewState",
    "StrategySelectionContext",
    "StrategySelectionBookmark",
    "StrategySelectionDisposition",
    "StrategySelectionResult",
    "StrategySelectionStatus",
    "decode_strategy_selection_bookmark",
    "encode_strategy_selection_bookmark",
]
