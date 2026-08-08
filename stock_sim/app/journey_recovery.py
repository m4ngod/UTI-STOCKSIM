"""Typed Journey Rail context and durable recovery bookmark.

This module is the navigation boundary.  It composes immutable identities and
presentation intent only; every Feature remains authoritative for mutable data.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import TypeVar

from app.features.diagnostic_tasks_application import (
    ApprovedScenarioRecipeVersionId,
    DiagnosticTaskConfigurationContentId,
)
from app.features.evidence_and_findings import (
    DiagnosticEvidencePackageId,
    EvidenceComparisonId,
    EvidenceRecordId,
    FindingId,
    SensitivityBreakpointId,
)
from app.features.run_monitoring import (
    DiagnosticTaskId,
    FormalDiagnosticCampaignId,
    ReproductionManifestId,
    ScenarioSetId,
    SourceGenerationId,
    StrategyRunId,
    StrategyUnderTestId,
    TaskHandleId,
)
from app.features.scenario_lab import ScenarioLabFocusTarget
from app.features.scenario_lab_application import (
    ReferenceMarketPathId,
    ScenarioRecipeDraftId,
)


_BOOKMARK_SCHEMA_VERSION = "2.0"
_WAVE_3_BOOKMARK_SCHEMA_VERSION = "1.0"
_MAX_BOOKMARK_BYTES = 32_768
_WAVE_3_KEYS = frozenset(
    {
        "schema_version",
        "last_route",
        "diagnostic_task_id",
        "scenario_focus_target",
        "scenario_focus_identity",
    }
)
_BOOKMARK_KEYS = frozenset(
    {
        "schema_version",
        "last_route",
        "diagnostic_task_id",
        "scenario_focus",
        "strategy",
        "scenario",
        "diagnostic",
        "evidence",
        "presentation",
    }
)

_IdentityT = TypeVar("_IdentityT")


class JourneyWorkspaceRoute(str, Enum):
    STRATEGY_LIBRARY = "strategy_library"
    SCENARIO_LAB = "scenario_lab"
    DIAGNOSTIC_TASKS = "diagnostic_tasks"
    RUN_MONITORING = "run_monitoring"
    EVIDENCE_AND_FINDINGS = "evidence_and_findings"
    SYSTEM_HEALTH = "system_health"


@dataclass(frozen=True, slots=True)
class JourneyDestination:
    route: JourneyWorkspaceRoute
    label: str


JOURNEY_DESTINATIONS = (
    JourneyDestination(JourneyWorkspaceRoute.STRATEGY_LIBRARY, "Strategy Library"),
    JourneyDestination(JourneyWorkspaceRoute.SCENARIO_LAB, "Scenario Lab"),
    JourneyDestination(JourneyWorkspaceRoute.DIAGNOSTIC_TASKS, "Diagnostic Tasks"),
    JourneyDestination(JourneyWorkspaceRoute.RUN_MONITORING, "Run Monitoring"),
    JourneyDestination(
        JourneyWorkspaceRoute.EVIDENCE_AND_FINDINGS,
        "Evidence & Findings",
    ),
    JourneyDestination(JourneyWorkspaceRoute.SYSTEM_HEALTH, "System Health"),
)


@dataclass(frozen=True, slots=True)
class JourneyContextVersion:
    major: int
    minor: int

    def __post_init__(self) -> None:
        for value in (self.major, self.minor):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("JourneyContext version is invalid")


JOURNEY_CONTEXT_VERSION = JourneyContextVersion(1, 0)


class JourneyViewMode(str, Enum):
    OVERVIEW = "overview"
    DETAILS = "details"
    COMPARE = "compare"
    FINDINGS = "findings"
    HEALTH = "health"


class JourneyRecoveryReason(str, Enum):
    EXACT = "exact"
    INVALID_BOOKMARK = "invalid_bookmark"
    INVALID_ROUTE = "invalid_route"
    UNAVAILABLE_ROUTE = "unavailable_route"
    MISSING_IDENTITY = "missing_identity"
    SUPERSEDED_IDENTITY = "superseded_identity"
    INCOMPATIBLE_IDENTITY = "incompatible_identity"
    UNAVAILABLE_IDENTITY = "unavailable_identity"
    NO_CURRENT_TASK = "no_current_task"


@dataclass(frozen=True, slots=True)
class JourneyRecoveryState:
    reason: JourneyRecoveryReason
    safe_route: JourneyWorkspaceRoute
    explanation: str

    def __post_init__(self) -> None:
        if not isinstance(self.reason, JourneyRecoveryReason):
            raise TypeError("reason must be a JourneyRecoveryReason")
        if not isinstance(self.safe_route, JourneyWorkspaceRoute):
            raise TypeError("safe_route must be a JourneyWorkspaceRoute")
        _require_safe_text(self.explanation, "recovery explanation")


@dataclass(frozen=True, slots=True)
class JourneyStrategyReference:
    strategy_id: StrategyUnderTestId
    strategy_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.strategy_id, StrategyUnderTestId):
            raise TypeError("strategy_id must be a StrategyUnderTestId")
        _require_safe_identity(self.strategy_version, "strategy version")


@dataclass(frozen=True, slots=True)
class JourneyStrategySelection:
    strategy_under_test: JourneyStrategyReference
    comparison_strategies: tuple[JourneyStrategyReference, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.strategy_under_test, JourneyStrategyReference):
            raise TypeError("strategy_under_test must be typed")
        if not isinstance(self.comparison_strategies, tuple) or any(
            not isinstance(item, JourneyStrategyReference)
            for item in self.comparison_strategies
        ):
            raise TypeError("comparison_strategies must be an immutable typed tuple")
        identities = (
            self.strategy_under_test.strategy_id,
            *(item.strategy_id for item in self.comparison_strategies),
        )
        if len(set(identities)) != len(identities):
            raise ValueError("strategy selections must have unique identities")


@dataclass(frozen=True, slots=True)
class JourneyRecipeDraftReference:
    recipe_draft_id: ScenarioRecipeDraftId
    revision: int

    def __post_init__(self) -> None:
        if not isinstance(self.recipe_draft_id, ScenarioRecipeDraftId):
            raise TypeError("recipe_draft_id must be typed")
        _require_positive_revision(self.revision, "recipe draft revision")


@dataclass(frozen=True, slots=True)
class JourneyApprovedRecipeReference:
    recipe_version_id: ApprovedScenarioRecipeVersionId
    revision: int

    def __post_init__(self) -> None:
        if not isinstance(
            self.recipe_version_id,
            ApprovedScenarioRecipeVersionId,
        ):
            raise TypeError("recipe_version_id must be typed")
        _require_positive_revision(self.revision, "approved recipe revision")


@dataclass(frozen=True, slots=True)
class JourneyScenarioSelection:
    reference_market_path_ids: tuple[ReferenceMarketPathId, ...] = ()
    recipe_drafts: tuple[JourneyRecipeDraftReference, ...] = ()
    approved_recipe_versions: tuple[JourneyApprovedRecipeReference, ...] = ()
    materialized_scenario_set_id: ScenarioSetId | None = None

    def __post_init__(self) -> None:
        for values, value_type, label in (
            (
                self.reference_market_path_ids,
                ReferenceMarketPathId,
                "reference_market_path_ids",
            ),
            (
                self.recipe_drafts,
                JourneyRecipeDraftReference,
                "recipe_drafts",
            ),
            (
                self.approved_recipe_versions,
                JourneyApprovedRecipeReference,
                "approved_recipe_versions",
            ),
        ):
            if not isinstance(values, tuple) or any(
                not isinstance(item, value_type) for item in values
            ):
                raise TypeError(f"{label} must be an immutable typed tuple")
            if len(set(values)) != len(values):
                raise ValueError(f"{label} must be unique")
        _require_optional_type(
            self.materialized_scenario_set_id,
            ScenarioSetId,
            "materialized_scenario_set_id",
        )


@dataclass(frozen=True, slots=True)
class JourneyDiagnosticSelection:
    task_id: DiagnosticTaskId
    task_revision: int
    configuration_content_id: DiagnosticTaskConfigurationContentId
    task_handle_id: TaskHandleId | None = None
    campaign_id: FormalDiagnosticCampaignId | None = None
    campaign_revision: int | None = None
    run_id: StrategyRunId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, DiagnosticTaskId):
            raise TypeError("task_id must be a DiagnosticTaskId")
        if not isinstance(
            self.configuration_content_id,
            DiagnosticTaskConfigurationContentId,
        ):
            raise TypeError("configuration_content_id must be typed")
        _require_positive_revision(self.task_revision, "task_revision")
        _require_optional_type(self.task_handle_id, TaskHandleId, "task_handle_id")
        _require_optional_type(
            self.campaign_id,
            FormalDiagnosticCampaignId,
            "campaign_id",
        )
        _require_optional_type(self.run_id, StrategyRunId, "run_id")
        _require_identity_revision_pair(
            self.campaign_id,
            self.campaign_revision,
            "campaign",
        )
        if self.run_id is not None and self.campaign_id is None:
            raise ValueError("run_id requires campaign_id")


@dataclass(frozen=True, slots=True)
class JourneyEvidenceSelection:
    evidence_package_id: DiagnosticEvidencePackageId
    evidence_id: EvidenceRecordId | None = None
    comparison_id: EvidenceComparisonId | None = None
    finding_id: FindingId | None = None
    sensitivity_breakpoint_id: SensitivityBreakpointId | None = None
    reproduction_manifest_id: ReproductionManifestId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_package_id, DiagnosticEvidencePackageId):
            raise TypeError("evidence_package_id must be typed")
        for value, value_type, label in (
            (self.evidence_id, EvidenceRecordId, "evidence_id"),
            (self.comparison_id, EvidenceComparisonId, "comparison_id"),
            (self.finding_id, FindingId, "finding_id"),
            (
                self.sensitivity_breakpoint_id,
                SensitivityBreakpointId,
                "sensitivity_breakpoint_id",
            ),
            (
                self.reproduction_manifest_id,
                ReproductionManifestId,
                "reproduction_manifest_id",
            ),
        ):
            _require_optional_type(value, value_type, label)
        if self.sensitivity_breakpoint_id is not None and self.finding_id is None:
            raise ValueError("sensitivity breakpoint requires a finding")


@dataclass(frozen=True, slots=True)
class JourneySourceIdentity:
    """Runtime correlation only; deliberately excluded from the bookmark."""

    identity: str
    revision: str
    generation: SourceGenerationId

    def __post_init__(self) -> None:
        _require_safe_identity(self.identity, "source identity")
        _require_safe_identity(self.revision, "source revision")
        if not isinstance(self.generation, SourceGenerationId):
            raise TypeError("generation must be a SourceGenerationId")


@dataclass(frozen=True, slots=True)
class JourneyFocusReturnToken:
    route: JourneyWorkspaceRoute
    control: str
    identity: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.route, JourneyWorkspaceRoute):
            raise TypeError("focus token route must be typed")
        _require_safe_identity(self.control, "focus control")
        if self.identity is not None:
            _require_safe_identity(self.identity, "focus identity")


@dataclass(frozen=True, slots=True)
class JourneyPresentationSelection:
    selected_identity: str | None = None
    view_mode: JourneyViewMode = JourneyViewMode.OVERVIEW
    focus_return_token: JourneyFocusReturnToken | None = None

    def __post_init__(self) -> None:
        if self.selected_identity is not None:
            _require_safe_identity(self.selected_identity, "selected identity")
        if not isinstance(self.view_mode, JourneyViewMode):
            raise TypeError("view_mode must be a JourneyViewMode")
        _require_optional_type(
            self.focus_return_token,
            JourneyFocusReturnToken,
            "focus_return_token",
        )


@dataclass(frozen=True, slots=True)
class JourneyContext:
    context_revision: int
    route: JourneyWorkspaceRoute
    strategy_selection: JourneyStrategySelection | None = None
    scenario_selection: JourneyScenarioSelection | None = None
    diagnostic_selection: JourneyDiagnosticSelection | None = None
    evidence_selection: JourneyEvidenceSelection | None = None
    presentation: JourneyPresentationSelection = field(
        default_factory=JourneyPresentationSelection
    )
    source_identities: tuple[JourneySourceIdentity, ...] = ()
    recovery: JourneyRecoveryState | None = None
    version: JourneyContextVersion = JOURNEY_CONTEXT_VERSION

    def __post_init__(self) -> None:
        _require_positive_revision(self.context_revision, "context_revision")
        if not isinstance(self.route, JourneyWorkspaceRoute):
            raise TypeError("route must be a JourneyWorkspaceRoute")
        for value, value_type, label in (
            (self.strategy_selection, JourneyStrategySelection, "strategy_selection"),
            (self.scenario_selection, JourneyScenarioSelection, "scenario_selection"),
            (
                self.diagnostic_selection,
                JourneyDiagnosticSelection,
                "diagnostic_selection",
            ),
            (self.evidence_selection, JourneyEvidenceSelection, "evidence_selection"),
            (self.presentation, JourneyPresentationSelection, "presentation"),
            (self.recovery, JourneyRecoveryState, "recovery"),
        ):
            _require_optional_type(value, value_type, label)
        if not isinstance(self.source_identities, tuple) or any(
            not isinstance(item, JourneySourceIdentity)
            for item in self.source_identities
        ):
            raise TypeError("source_identities must be an immutable typed tuple")
        if not isinstance(self.version, JourneyContextVersion):
            raise TypeError("version must be a JourneyContextVersion")


@dataclass(frozen=True, slots=True)
class JourneyWorkspaceBookmark:
    """Durable identities and presentation selection; never mutable state."""

    last_route: JourneyWorkspaceRoute = JourneyWorkspaceRoute.STRATEGY_LIBRARY
    diagnostic_task_id: DiagnosticTaskId | None = None
    scenario_focus_target: ScenarioLabFocusTarget = ScenarioLabFocusTarget.SEARCH
    scenario_focus_identity: str | None = None
    strategy_selection: JourneyStrategySelection | None = None
    scenario_selection: JourneyScenarioSelection | None = None
    diagnostic_selection: JourneyDiagnosticSelection | None = None
    evidence_selection: JourneyEvidenceSelection | None = None
    presentation: JourneyPresentationSelection = field(
        default_factory=JourneyPresentationSelection
    )

    def __post_init__(self) -> None:
        if not isinstance(self.last_route, JourneyWorkspaceRoute):
            raise TypeError("last_route must be a JourneyWorkspaceRoute")
        _require_optional_type(
            self.diagnostic_task_id,
            DiagnosticTaskId,
            "diagnostic_task_id",
        )
        if not isinstance(self.scenario_focus_target, ScenarioLabFocusTarget):
            raise TypeError("scenario_focus_target must be typed")
        if self.scenario_focus_identity is not None:
            _require_safe_identity(
                self.scenario_focus_identity,
                "scenario focus identity",
            )
        if self.scenario_focus_target is ScenarioLabFocusTarget.SEARCH:
            if self.scenario_focus_identity is not None:
                raise ValueError("search focus cannot carry an identity")
        elif self.scenario_focus_identity is None:
            raise ValueError("detail focus requires an identity")
        for value, value_type, label in (
            (self.strategy_selection, JourneyStrategySelection, "strategy_selection"),
            (self.scenario_selection, JourneyScenarioSelection, "scenario_selection"),
            (
                self.diagnostic_selection,
                JourneyDiagnosticSelection,
                "diagnostic_selection",
            ),
            (self.evidence_selection, JourneyEvidenceSelection, "evidence_selection"),
            (self.presentation, JourneyPresentationSelection, "presentation"),
        ):
            _require_optional_type(value, value_type, label)
        if (
            self.diagnostic_task_id is not None
            and self.diagnostic_selection is not None
            and self.diagnostic_task_id != self.diagnostic_selection.task_id
        ):
            raise ValueError("diagnostic task identities must match exactly")


@dataclass(frozen=True, slots=True)
class JourneyBookmarkRestore:
    bookmark: JourneyWorkspaceBookmark
    canonical_payload: str
    migrated: bool
    recovery: JourneyRecoveryState


def encode_journey_workspace_bookmark(bookmark: JourneyWorkspaceBookmark) -> str:
    if not isinstance(bookmark, JourneyWorkspaceBookmark):
        raise TypeError("bookmark must be a JourneyWorkspaceBookmark")
    return json.dumps(
        _encode_bookmark(bookmark),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def decode_journey_workspace_bookmark(
    payload: str,
) -> JourneyWorkspaceBookmark | None:
    parsed = _parse_bookmark(payload)
    return None if parsed is None else parsed[0]


def restore_journey_workspace_bookmark(payload: str) -> JourneyBookmarkRestore:
    parsed = _parse_bookmark(payload)
    if parsed is None:
        bookmark = JourneyWorkspaceBookmark()
        return JourneyBookmarkRestore(
            bookmark=bookmark,
            canonical_payload=encode_journey_workspace_bookmark(bookmark),
            migrated=False,
            recovery=JourneyRecoveryState(
                JourneyRecoveryReason.INVALID_BOOKMARK,
                JourneyWorkspaceRoute.STRATEGY_LIBRARY,
                "The bookmark is invalid. Strategy Library was opened safely.",
            ),
        )
    bookmark, migrated = parsed
    return JourneyBookmarkRestore(
        bookmark=bookmark,
        canonical_payload=encode_journey_workspace_bookmark(bookmark),
        migrated=migrated,
        recovery=JourneyRecoveryState(
            JourneyRecoveryReason.EXACT,
            bookmark.last_route,
            (
                "The Wave 3 bookmark was migrated exactly."
                if migrated
                else "The Journey bookmark was restored exactly."
            ),
        ),
    )


def _parse_bookmark(
    payload: str,
) -> tuple[JourneyWorkspaceBookmark, bool] | None:
    if (
        not isinstance(payload, str)
        or not payload
        or len(payload.encode("utf-8")) > _MAX_BOOKMARK_BYTES
    ):
        return None
    try:
        raw = json.loads(payload)
        if not isinstance(raw, dict):
            return None
        version = raw.get("schema_version")
        if version == _WAVE_3_BOOKMARK_SCHEMA_VERSION:
            return _decode_wave_3(raw), True
        if version == _BOOKMARK_SCHEMA_VERSION:
            return _decode_v2(raw), False
        return None
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _decode_wave_3(raw: dict[str, object]) -> JourneyWorkspaceBookmark:
    if frozenset(raw) != _WAVE_3_KEYS:
        raise ValueError("unexpected Wave 3 bookmark fields")
    route = JourneyWorkspaceRoute(_required_str(raw, "last_route"))
    task_value = _optional_str(raw, "diagnostic_task_id")
    focus_target = ScenarioLabFocusTarget(_required_str(raw, "scenario_focus_target"))
    focus_identity = _optional_str(raw, "scenario_focus_identity")
    focus_token = (
        None
        if focus_target is ScenarioLabFocusTarget.SEARCH
        else JourneyFocusReturnToken(
            route=JourneyWorkspaceRoute.SCENARIO_LAB,
            control=_wave_3_focus_control(focus_target, focus_identity),
            identity=(
                focus_identity
                if focus_target
                in {
                    ScenarioLabFocusTarget.HISTORICAL_SEGMENT,
                    ScenarioLabFocusTarget.REFERENCE_PATH,
                    ScenarioLabFocusTarget.MARKET_SCENARIO,
                }
                else None
            ),
        )
    )
    return JourneyWorkspaceBookmark(
        last_route=route,
        diagnostic_task_id=(
            None if task_value is None else DiagnosticTaskId(task_value)
        ),
        scenario_focus_target=focus_target,
        scenario_focus_identity=focus_identity,
        presentation=JourneyPresentationSelection(
            selected_identity=focus_identity,
            focus_return_token=focus_token,
        ),
    )


def _wave_3_focus_control(
    target: ScenarioLabFocusTarget,
    identity: str | None,
) -> str:
    entity_prefixes = {
        ScenarioLabFocusTarget.HISTORICAL_SEGMENT: "scenarioLabSegment-",
        ScenarioLabFocusTarget.REFERENCE_PATH: "scenarioLabPath-",
        ScenarioLabFocusTarget.MARKET_SCENARIO: "scenarioLabScenario-",
    }
    prefix = entity_prefixes.get(target)
    if prefix is not None:
        if identity is None:
            raise ValueError("legacy entity focus requires an exact identity")
        return prefix + identity
    controls = {
        ScenarioLabFocusTarget.TRANSFORMATION_CATALOG: (
            "scenarioLabTransformationFamilyFilter"
        ),
        ScenarioLabFocusTarget.RECIPE_AUTHORING: "scenarioLabRecipeNameInput",
    }
    try:
        return controls[target]
    except KeyError as exc:
        raise ValueError("unsupported legacy focus target") from exc


def _decode_v2(raw: dict[str, object]) -> JourneyWorkspaceBookmark:
    if frozenset(raw) != _BOOKMARK_KEYS:
        raise ValueError("unexpected bookmark fields")
    if raw["schema_version"] != _BOOKMARK_SCHEMA_VERSION:
        raise ValueError("unsupported bookmark version")
    focus = _required_dict(raw, "scenario_focus", {"target", "identity"})
    return JourneyWorkspaceBookmark(
        last_route=JourneyWorkspaceRoute(_required_str(raw, "last_route")),
        diagnostic_task_id=_typed_optional_identity(
            raw,
            "diagnostic_task_id",
            DiagnosticTaskId,
        ),
        scenario_focus_target=ScenarioLabFocusTarget(
            _required_str(focus, "target")
        ),
        scenario_focus_identity=_optional_str(focus, "identity"),
        strategy_selection=_decode_strategy(raw["strategy"]),
        scenario_selection=_decode_scenario(raw["scenario"]),
        diagnostic_selection=_decode_diagnostic(raw["diagnostic"]),
        evidence_selection=_decode_evidence(raw["evidence"]),
        presentation=_decode_presentation(raw["presentation"]),
    )


def _encode_bookmark(bookmark: JourneyWorkspaceBookmark) -> dict[str, object]:
    return {
        "schema_version": _BOOKMARK_SCHEMA_VERSION,
        "last_route": bookmark.last_route.value,
        "diagnostic_task_id": _value(bookmark.diagnostic_task_id),
        "scenario_focus": {
            "target": bookmark.scenario_focus_target.value,
            "identity": bookmark.scenario_focus_identity,
        },
        "strategy": _encode_strategy(bookmark.strategy_selection),
        "scenario": _encode_scenario(bookmark.scenario_selection),
        "diagnostic": _encode_diagnostic(bookmark.diagnostic_selection),
        "evidence": _encode_evidence(bookmark.evidence_selection),
        "presentation": _encode_presentation(bookmark.presentation),
    }


def _encode_strategy(value: JourneyStrategySelection | None) -> object:
    if value is None:
        return None
    return {
        "strategy_under_test": _encode_strategy_reference(value.strategy_under_test),
        "comparison_strategies": [
            _encode_strategy_reference(item) for item in value.comparison_strategies
        ],
    }


def _encode_strategy_reference(value: JourneyStrategyReference) -> dict[str, str]:
    return {
        "strategy_id": value.strategy_id.value,
        "strategy_version": value.strategy_version,
    }


def _decode_strategy(raw: object) -> JourneyStrategySelection | None:
    if raw is None:
        return None
    value = _exact_dict(raw, {"strategy_under_test", "comparison_strategies"})
    comparisons = value["comparison_strategies"]
    if not isinstance(comparisons, list):
        raise TypeError("comparison_strategies must be a list")
    return JourneyStrategySelection(
        strategy_under_test=_decode_strategy_reference(value["strategy_under_test"]),
        comparison_strategies=tuple(
            _decode_strategy_reference(item) for item in comparisons
        ),
    )


def _decode_strategy_reference(raw: object) -> JourneyStrategyReference:
    value = _exact_dict(raw, {"strategy_id", "strategy_version"})
    return JourneyStrategyReference(
        StrategyUnderTestId(_required_str(value, "strategy_id")),
        _required_str(value, "strategy_version"),
    )


def _encode_scenario(value: JourneyScenarioSelection | None) -> object:
    if value is None:
        return None
    return {
        "reference_market_path_ids": [
            item.value for item in value.reference_market_path_ids
        ],
        "recipe_drafts": [
            {"recipe_draft_id": item.recipe_draft_id.value, "revision": item.revision}
            for item in value.recipe_drafts
        ],
        "approved_recipe_versions": [
            {
                "recipe_version_id": item.recipe_version_id.value,
                "revision": item.revision,
            }
            for item in value.approved_recipe_versions
        ],
        "materialized_scenario_set_id": _value(
            value.materialized_scenario_set_id
        ),
    }


def _decode_scenario(raw: object) -> JourneyScenarioSelection | None:
    if raw is None:
        return None
    value = _exact_dict(
        raw,
        {
            "reference_market_path_ids",
            "recipe_drafts",
            "approved_recipe_versions",
            "materialized_scenario_set_id",
        },
    )
    reference_paths = value["reference_market_path_ids"]
    recipe_drafts = value["recipe_drafts"]
    approved_recipes = value["approved_recipe_versions"]
    if (
        not isinstance(reference_paths, list)
        or not isinstance(recipe_drafts, list)
        or not isinstance(approved_recipes, list)
    ):
        raise TypeError("scenario identity collections must be lists")
    return JourneyScenarioSelection(
        reference_market_path_ids=tuple(
            ReferenceMarketPathId(_safe_list_identity(item, "reference path"))
            for item in reference_paths
        ),
        recipe_drafts=tuple(
            _decode_recipe_draft_reference(item) for item in recipe_drafts
        ),
        approved_recipe_versions=tuple(
            _decode_approved_recipe_reference(item) for item in approved_recipes
        ),
        materialized_scenario_set_id=_typed_optional_identity(
            value, "materialized_scenario_set_id", ScenarioSetId
        ),
    )


def _decode_recipe_draft_reference(raw: object) -> JourneyRecipeDraftReference:
    value = _exact_dict(raw, {"recipe_draft_id", "revision"})
    return JourneyRecipeDraftReference(
        ScenarioRecipeDraftId(_required_str(value, "recipe_draft_id")),
        _required_revision(value, "revision"),
    )


def _decode_approved_recipe_reference(
    raw: object,
) -> JourneyApprovedRecipeReference:
    value = _exact_dict(raw, {"recipe_version_id", "revision"})
    return JourneyApprovedRecipeReference(
        ApprovedScenarioRecipeVersionId(
            _required_str(value, "recipe_version_id")
        ),
        _required_revision(value, "revision"),
    )


def _encode_diagnostic(value: JourneyDiagnosticSelection | None) -> object:
    if value is None:
        return None
    return {
        "task_id": value.task_id.value,
        "task_revision": value.task_revision,
        "configuration_content_id": value.configuration_content_id.value,
        "task_handle_id": _value(value.task_handle_id),
        "campaign_id": _value(value.campaign_id),
        "campaign_revision": value.campaign_revision,
        "run_id": _value(value.run_id),
    }


def _decode_diagnostic(raw: object) -> JourneyDiagnosticSelection | None:
    if raw is None:
        return None
    value = _exact_dict(
        raw,
        {
            "task_id",
            "task_revision",
            "configuration_content_id",
            "task_handle_id",
            "campaign_id",
            "campaign_revision",
            "run_id",
        },
    )
    return JourneyDiagnosticSelection(
        task_id=DiagnosticTaskId(_required_str(value, "task_id")),
        task_revision=_required_revision(value, "task_revision"),
        configuration_content_id=DiagnosticTaskConfigurationContentId(
            _required_str(value, "configuration_content_id")
        ),
        task_handle_id=_typed_optional_identity(
            value, "task_handle_id", TaskHandleId
        ),
        campaign_id=_typed_optional_identity(
            value, "campaign_id", FormalDiagnosticCampaignId
        ),
        campaign_revision=_optional_revision(value, "campaign_revision"),
        run_id=_typed_optional_identity(value, "run_id", StrategyRunId),
    )


def _encode_evidence(value: JourneyEvidenceSelection | None) -> object:
    if value is None:
        return None
    return {
        "evidence_package_id": value.evidence_package_id.value,
        "evidence_id": _value(value.evidence_id),
        "comparison_id": _value(value.comparison_id),
        "finding_id": _value(value.finding_id),
        "sensitivity_breakpoint_id": _value(value.sensitivity_breakpoint_id),
        "reproduction_manifest_id": _value(value.reproduction_manifest_id),
    }


def _decode_evidence(raw: object) -> JourneyEvidenceSelection | None:
    if raw is None:
        return None
    value = _exact_dict(
        raw,
        {
            "evidence_package_id",
            "evidence_id",
            "comparison_id",
            "finding_id",
            "sensitivity_breakpoint_id",
            "reproduction_manifest_id",
        },
    )
    return JourneyEvidenceSelection(
        evidence_package_id=DiagnosticEvidencePackageId(
            _required_str(value, "evidence_package_id")
        ),
        evidence_id=_typed_optional_identity(value, "evidence_id", EvidenceRecordId),
        comparison_id=_typed_optional_identity(
            value, "comparison_id", EvidenceComparisonId
        ),
        finding_id=_typed_optional_identity(value, "finding_id", FindingId),
        sensitivity_breakpoint_id=_typed_optional_identity(
            value,
            "sensitivity_breakpoint_id",
            SensitivityBreakpointId,
        ),
        reproduction_manifest_id=_typed_optional_identity(
            value,
            "reproduction_manifest_id",
            ReproductionManifestId,
        ),
    )


def _encode_presentation(value: JourneyPresentationSelection) -> dict[str, object]:
    token = value.focus_return_token
    return {
        "selected_identity": value.selected_identity,
        "view_mode": value.view_mode.value,
        "focus_return_token": (
            None
            if token is None
            else {
                "route": token.route.value,
                "control": token.control,
                "identity": token.identity,
            }
        ),
    }


def _decode_presentation(raw: object) -> JourneyPresentationSelection:
    value = _exact_dict(
        raw,
        {"selected_identity", "view_mode", "focus_return_token"},
    )
    raw_token = value["focus_return_token"]
    token = None
    if raw_token is not None:
        token_value = _exact_dict(raw_token, {"route", "control", "identity"})
        token = JourneyFocusReturnToken(
            route=JourneyWorkspaceRoute(_required_str(token_value, "route")),
            control=_required_str(token_value, "control"),
            identity=_optional_str(token_value, "identity"),
        )
    return JourneyPresentationSelection(
        selected_identity=_optional_str(value, "selected_identity"),
        view_mode=JourneyViewMode(_required_str(value, "view_mode")),
        focus_return_token=token,
    )


def _exact_dict(raw: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(raw, dict) or set(raw) != keys:
        raise ValueError("bookmark object has unexpected fields")
    return raw


def _required_dict(
    raw: dict[str, object],
    key: str,
    keys: set[str],
) -> dict[str, object]:
    return _exact_dict(raw[key], keys)


def _required_str(raw: dict[str, object], key: str) -> str:
    value = raw[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} must be text")
    _require_safe_identity(value, key)
    return value


def _optional_str(raw: dict[str, object], key: str) -> str | None:
    value = raw[key]
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{key} must be text or null")
    _require_safe_identity(value, key)
    return value


def _safe_list_identity(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be text")
    _require_safe_identity(value, label)
    return value


def _typed_optional_identity(
    raw: dict[str, object],
    key: str,
    value_type: Callable[[str], _IdentityT],
) -> _IdentityT | None:
    value = _optional_str(raw, key)
    return None if value is None else value_type(value)


def _required_revision(raw: dict[str, object], key: str) -> int:
    value = raw[key]
    _require_positive_revision(value, key)
    if not isinstance(value, int):
        raise AssertionError("validated revision must be an integer")
    return value


def _optional_revision(raw: dict[str, object], key: str) -> int | None:
    value = raw[key]
    if value is not None:
        _require_positive_revision(value, key)
        if not isinstance(value, int):
            raise AssertionError("validated revision must be an integer")
    return value


def _value(value: object | None) -> str | None:
    return None if value is None else str(getattr(value, "value"))


def _require_optional_type(value: object, value_type: type, label: str) -> None:
    if value is not None and not isinstance(value, value_type):
        raise TypeError(f"{label} must be a {value_type.__name__}")


def _require_identity_revision_pair(
    identity: object | None,
    revision: int | None,
    label: str,
) -> None:
    if (identity is None) != (revision is None):
        raise ValueError(f"{label} identity and revision must be provided together")
    if revision is not None:
        _require_positive_revision(revision, f"{label} revision")


def _require_positive_revision(value: object, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label} must be positive")


def _require_safe_identity(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 512
        or any(
            not (
                character.isalnum()
                or character in "-._:/@"
            )
            for character in value
        )
    ):
        raise ValueError(f"{label} must be an exact safe identity")


def _require_safe_text(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 1_024
        or any(ord(character) < 32 and character not in "\t\n" for character in value)
    ):
        raise ValueError(f"{label} is invalid")


__all__ = [
    "JOURNEY_CONTEXT_VERSION",
    "JOURNEY_DESTINATIONS",
    "JourneyBookmarkRestore",
    "JourneyApprovedRecipeReference",
    "JourneyContext",
    "JourneyContextVersion",
    "JourneyDestination",
    "JourneyDiagnosticSelection",
    "JourneyEvidenceSelection",
    "JourneyFocusReturnToken",
    "JourneyPresentationSelection",
    "JourneyRecoveryReason",
    "JourneyRecoveryState",
    "JourneyRecipeDraftReference",
    "JourneyScenarioSelection",
    "JourneySourceIdentity",
    "JourneyStrategyReference",
    "JourneyStrategySelection",
    "JourneyViewMode",
    "JourneyWorkspaceBookmark",
    "JourneyWorkspaceRoute",
    "decode_journey_workspace_bookmark",
    "encode_journey_workspace_bookmark",
    "restore_journey_workspace_bookmark",
]
