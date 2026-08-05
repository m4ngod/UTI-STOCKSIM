"""Typed cross-Feature selection handoff into Diagnostic Tasks 1.0."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
from threading import RLock

from .diagnostic_tasks_application import (
    ApproveDiagnosticTaskConfiguration,
    CreateDiagnosticTask,
    DiagnosticCampaignCaseSelection,
    DiagnosticCampaignLayer,
    DiagnosticComparisonRole,
    DiagnosticStrategySelection,
    DiagnosticTaskConfiguration,
    ExecutionPolicyValue,
    GuardrailProfileId,
    MaterializedMarketScenarioId,
    ReviseDiagnosticTaskConfiguration,
    StartFormalDiagnosticCampaign,
    ValidateDiagnosticTaskConfiguration,
)
from .scenario_lab_application import (
    FormalScenarioSetEligibility,
    FormalScenarioSetProjection,
    MarketScenarioComparisonRole,
    MarketScenarioEntry,
    MarketScenarioLayer,
    ScenarioExecutionResolutionProjection,
    ScenarioExecutionResolutionState,
    ScenarioExecutionTargetProjection,
    ScenarioCompatibilityState,
    ScenarioReproducibilityState,
    ScenarioSelectionContextProjection,
    ScenarioSelectionContextStatus,
)
from .strategy_library import StrategySelectionContext


@dataclass(frozen=True, slots=True)
class ScenarioDiagnosticSelection:
    """Exact Scenario Lab projections required by the existing task config."""

    context: ScenarioSelectionContextProjection
    scenario_set: FormalScenarioSetProjection
    market_scenarios: tuple[MarketScenarioEntry, ...]
    execution_resolution: ScenarioExecutionResolutionProjection


@dataclass(frozen=True, slots=True)
class DiagnosticSetupSelectionContext:
    """Immutable typed navigation intent; never a new source of truth."""

    context_identity: str
    canonical_payload_json: str
    strategy_selection: StrategySelectionContext
    scenario_selection: ScenarioDiagnosticSelection
    configuration: DiagnosticTaskConfiguration


class DiagnosticSetupSelectionCoordinator:
    """Composition-owned current immutable setup for command/read handoff."""

    def __init__(self) -> None:
        self._selection: DiagnosticSetupSelectionContext | None = None
        self._lock = RLock()

    def observe(
        self,
        selection: DiagnosticSetupSelectionContext | None,
    ) -> None:
        with self._lock:
            self._selection = selection

    def current(self) -> DiagnosticSetupSelectionContext | None:
        with self._lock:
            return self._selection


@dataclass(frozen=True, slots=True)
class CreateDiagnosticTaskFromSetup(CreateDiagnosticTask):
    """Existing 1.0 create command carrying its typed navigation input."""

    setup_selection: DiagnosticSetupSelectionContext

    def __post_init__(self) -> None:
        _require_matching_setup_configuration(
            self.setup_selection,
            self.configuration,
        )


@dataclass(frozen=True, slots=True)
class ReviseDiagnosticTaskConfigurationFromSetup(
    ReviseDiagnosticTaskConfiguration
):
    """Existing 1.0 correction command carrying its replacement setup."""

    setup_selection: DiagnosticSetupSelectionContext

    def __post_init__(self) -> None:
        ReviseDiagnosticTaskConfiguration.__post_init__(self)
        _require_matching_setup_configuration(
            self.setup_selection,
            self.configuration,
        )


@dataclass(frozen=True, slots=True)
class ValidateDiagnosticTaskConfigurationFromSetup(
    ValidateDiagnosticTaskConfiguration
):
    """Existing 1.0 validation command with the current typed setup."""

    setup_selection: DiagnosticSetupSelectionContext

    def __post_init__(self) -> None:
        ValidateDiagnosticTaskConfiguration.__post_init__(self)


@dataclass(frozen=True, slots=True)
class ApproveDiagnosticTaskConfigurationFromSetup(
    ApproveDiagnosticTaskConfiguration
):
    """Existing 1.0 approval command with the current typed setup."""

    setup_selection: DiagnosticSetupSelectionContext

    def __post_init__(self) -> None:
        ApproveDiagnosticTaskConfiguration.__post_init__(self)


@dataclass(frozen=True, slots=True)
class StartFormalDiagnosticCampaignFromSetup(
    StartFormalDiagnosticCampaign
):
    """Existing 1.0 start command with the current typed setup."""

    setup_selection: DiagnosticSetupSelectionContext

    def __post_init__(self) -> None:
        StartFormalDiagnosticCampaign.__post_init__(self)


def _require_matching_setup_configuration(
    setup: DiagnosticSetupSelectionContext,
    configuration: DiagnosticTaskConfiguration,
) -> None:
    if setup.configuration != configuration:
        raise ValueError(
            "Diagnostic setup must supply the exact task configuration"
        )


def compose_diagnostic_setup_selection_context(
    strategy_selection: StrategySelectionContext,
    scenario_selection: ScenarioDiagnosticSelection,
) -> DiagnosticSetupSelectionContext:
    """Combine two independent current selections into the 1.0 task config."""

    _validate_strategy_selection(strategy_selection)
    _validate_scenario_selection(scenario_selection)
    _validate_cross_feature_binding(strategy_selection, scenario_selection)
    configuration = DiagnosticTaskConfiguration.create(
        strategy_selections=tuple(
            DiagnosticStrategySelection(
                strategy_id=item.strategy_id,
                strategy_version=item.strategy_version,
                compatibility_manifest_hash=item.manifest_content_hash,
                guardrail_profile_id=item.guardrail_profile_id,
                guardrail_profile_version=item.guardrail_profile_version,
            )
            for item in strategy_selection.selections
        ),
        campaign_case_selections=tuple(
            _configuration_case(item, scenario_selection)
            for item in scenario_selection.market_scenarios
        ),
    )
    identity_payload = {
        "schema_version": "diagnostic-setup-selection-context.v1",
        "strategy_selection": _canonical_value(strategy_selection),
        "scenario_selection": _canonical_value(scenario_selection),
        "configuration_content_identity": configuration.content_identity.value,
    }
    canonical_payload_json = json.dumps(
        identity_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return DiagnosticSetupSelectionContext(
        context_identity=(
            "sha256:"
            + hashlib.sha256(canonical_payload_json.encode("utf-8")).hexdigest()
        ),
        canonical_payload_json=canonical_payload_json,
        strategy_selection=strategy_selection,
        scenario_selection=scenario_selection,
        configuration=configuration,
    )


def _validate_strategy_selection(selection: StrategySelectionContext) -> None:
    if not selection.context_identity.strip() or not selection.selections:
        raise ValueError("Strategy selection context is unavailable")
    strategy_ids = tuple(item.strategy_id for item in selection.selections)
    if len(strategy_ids) != len(set(strategy_ids)):
        raise ValueError("Strategy selection identities must be unique")
    if selection.originating_view_revision < 1:
        raise ValueError("Strategy originating View revision must be positive")
    if any(
        not dependency.available or not dependency.compatible
        for item in selection.selections
        for dependency in item.dependency_identities
    ):
        raise ValueError("Strategy dependency binding is not authoritative")


def _validate_scenario_selection(selection: ScenarioDiagnosticSelection) -> None:
    context = selection.context
    scenario_set = selection.scenario_set
    resolution = selection.execution_resolution
    if context.status is not ScenarioSelectionContextStatus.CURRENT:
        raise ValueError("Scenario selection context is not current")
    if not context.formal_handoff_eligible:
        raise ValueError("Scenario selection context is not eligible for handoff")
    if (
        scenario_set.eligibility
        is not FormalScenarioSetEligibility.FORMAL_CAMPAIGN_ELIGIBLE
        or not scenario_set.formal_handoff_eligible
        or scenario_set.missing_requirements
    ):
        raise ValueError("Quick Experiment is ineligible for formal handoff")
    if not resolution.formal_handoff_eligible:
        raise ValueError("Execution assumptions are not fully resolved")
    if (
        context.scenario_set_id != scenario_set.scenario_set_id
        or context.scenario_set_projection_revision
        != scenario_set.projection_revision
        or resolution.scenario_set_id != scenario_set.scenario_set_id
        or resolution.scenario_set_projection_revision
        != scenario_set.projection_revision
        or context.execution_resolution_id != resolution.resolution_id
        or context.execution_resolution_projection_revision
        != resolution.projection_revision
    ):
        raise ValueError("Scenario selection dependency projection is stale")
    scenario_ids = tuple(item.scenario_id for item in selection.market_scenarios)
    if (
        not scenario_ids
        or scenario_ids != scenario_set.case_ids
        or scenario_ids != context.case_ids
        or len(scenario_ids) != len(set(scenario_ids))
    ):
        raise ValueError("Scenario selection must bind every exact Campaign Case")
    expected_layers = (
        (scenario_set.baseline_case_id, MarketScenarioLayer.BASELINE),
        *(
            (identity, MarketScenarioLayer.ISOLATED_SENSITIVITY)
            for identity in scenario_set.isolated_case_ids
        ),
        *(
            (identity, MarketScenarioLayer.COMPOUND)
            for identity in scenario_set.compound_case_ids
        ),
    )
    if tuple((item.scenario_id, item.layer) for item in selection.market_scenarios) != (
        expected_layers
    ):
        raise ValueError("Scenario Set layers do not match exact Campaign Cases")
    binding_by_case = {
        item.campaign_case_id: item for item in context.case_bindings
    }
    if len(binding_by_case) != len(context.case_bindings):
        raise ValueError("Scenario dependency bindings must be unique")
    for item in selection.market_scenarios:
        binding = binding_by_case.get(item.scenario_id)
        if binding is None or (
            binding.recipe_version_id != item.recipe_version_id
            or binding.recipe_content_hash != item.recipe_content_hash
            or binding.reference_path_id != item.path_id
            or binding.segment_id != item.segment_id
            or binding.segment_content_hash != item.segment_content_hash
            or binding.source_snapshot_id != item.source_snapshot_id
            or binding.seed != item.seed
            or binding.transformation_catalog_version
            != item.transformation_catalog_version
            or binding.transformations != item.transformations
            or binding.market_rule_profile_version
            != item.market_rule_profile_version
            or binding.decision_cadence_minutes != item.decision_cadence_minutes
        ):
            raise ValueError("Campaign Case dependency binding is not exact")
        if (
            item.compatibility is not ScenarioCompatibilityState.COMPATIBLE
            or item.reproducibility
            is not ScenarioReproducibilityState.REPRODUCIBLE
            or item.unavailability_reasons
        ):
            raise ValueError("Campaign Case is not authoritative for handoff")
    _validate_execution_targets(selection)


def _validate_cross_feature_binding(
    strategy: StrategySelectionContext,
    scenario: ScenarioDiagnosticSelection,
) -> None:
    expected = tuple(
        (
            item.strategy_id,
            item.strategy_version,
            item.manifest_content_hash,
            item.guardrail_profile_id.value,
            item.guardrail_profile_version,
        )
        for item in strategy.selections
    )
    actual = tuple(
        (
            item.strategy_id,
            item.strategy_version,
            item.compatibility_manifest_hash,
            item.guardrail_profile_id,
            item.guardrail_profile_version,
        )
        for item in scenario.context.strategy_bindings
    )
    if actual != expected:
        raise ValueError("Strategy and Scenario selection bindings do not match")


def _validate_execution_targets(selection: ScenarioDiagnosticSelection) -> None:
    resolution = selection.execution_resolution
    target_keys = tuple(
        (item.strategy_id, item.campaign_case_id) for item in resolution.targets
    )
    expected_keys = tuple(
        (strategy.strategy_id, case.scenario_id)
        for strategy in selection.context.strategy_bindings
        for case in selection.market_scenarios
    )
    if (
        len(target_keys) != len(set(target_keys))
        or set(target_keys) != set(expected_keys)
    ):
        raise ValueError("Execution resolution must bind every Strategy/Case target")
    strategy_by_id = {
        item.strategy_id: item for item in selection.context.strategy_bindings
    }
    case_by_id = {item.scenario_id: item for item in selection.market_scenarios}
    for target in resolution.targets:
        strategy = strategy_by_id[target.strategy_id]
        case = case_by_id[target.campaign_case_id]
        if (
            target.state is not ScenarioExecutionResolutionState.RESOLVED
            or target.unavailability_reasons
            or target.strategy_version != strategy.strategy_version
            or target.compatibility_manifest_hash
            != strategy.compatibility_manifest_hash
            or target.guardrail_profile_id != strategy.guardrail_profile_id
            or target.guardrail_profile_version
            != strategy.guardrail_profile_version
            or target.execution_policy_version
            != strategy.execution_policy_version
            or target.decision_cadence_minutes != case.decision_cadence_minutes
            or target.after_decision_time is None
            or target.activation_time is None
            or target.activation_time < target.after_decision_time
        ):
            raise ValueError("Execution assumption target is not authoritative")


def _configuration_case(
    item: MarketScenarioEntry,
    selection: ScenarioDiagnosticSelection,
) -> DiagnosticCampaignCaseSelection:
    targets = tuple(
        target
        for target in selection.execution_resolution.targets
        if target.campaign_case_id == item.scenario_id
    )
    policies = tuple(_execution_policy_values(targets[0]))
    if any(tuple(_execution_policy_values(target)) != policies for target in targets[1:]):
        raise ValueError(
            "DiagnosticTasksFeature 1.0 requires one effective policy per Case"
        )
    layer = {
        MarketScenarioLayer.BASELINE: DiagnosticCampaignLayer.BASELINE,
        MarketScenarioLayer.ISOLATED_SENSITIVITY: (
            DiagnosticCampaignLayer.ISOLATED_SENSITIVITY
        ),
        MarketScenarioLayer.COMPOUND: DiagnosticCampaignLayer.COMPOUND,
    }[item.layer]
    comparison = {
        MarketScenarioComparisonRole.CONTROL: DiagnosticComparisonRole.CONTROL,
        MarketScenarioComparisonRole.COMPARE_TO_BASELINE: (
            DiagnosticComparisonRole.COMPARE_TO_BASELINE
        ),
    }[item.comparison_role]
    return DiagnosticCampaignCaseSelection(
        layer=layer,
        recipe_version_id=item.recipe_version_id,
        recipe_content_hash=item.recipe_content_hash,
        market_scenario_id=MaterializedMarketScenarioId(item.path_id.value),
        campaign_case_id=item.scenario_id,
        comparison_role=comparison,
        baseline_campaign_case_id=item.baseline_scenario_id,
        execution_policy_values=policies,
    )


def _execution_policy_values(
    target: ScenarioExecutionTargetProjection,
) -> tuple[ExecutionPolicyValue, ...]:
    return tuple(
        ExecutionPolicyValue(
            name=condition.name,
            value=condition.effective_value,
            version=target.execution_policy_version,
            source=(
                "backend-resolved:requested=" + condition.requested_value
                if condition.override_reason is None
                else (
                    "backend-resolved:"
                    + condition.override_reason
                    + ";requested="
                    + condition.requested_value
                )
            ),
        )
        for condition in sorted(target.conditions, key=lambda value: value.name)
    )


def _canonical_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _canonical_value(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, tuple):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"Unsupported canonical Diagnostic setup value: {type(value)!r}")


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "ApproveDiagnosticTaskConfigurationFromSetup",
    "CreateDiagnosticTaskFromSetup",
    "DiagnosticSetupSelectionContext",
    "DiagnosticSetupSelectionCoordinator",
    "ReviseDiagnosticTaskConfigurationFromSetup",
    "ScenarioDiagnosticSelection",
    "StartFormalDiagnosticCampaignFromSetup",
    "ValidateDiagnosticTaskConfigurationFromSetup",
    "compose_diagnostic_setup_selection_context",
]
