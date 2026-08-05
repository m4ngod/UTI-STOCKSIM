from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError, fields
from typing import get_type_hints

import pytest

from app.features import (
    ACTIVE_FEATURE_INTERFACES,
    SCENARIO_LAB_INTERFACE_VERSION,
    FeatureModuleName,
    ScenarioLabFeature,
)
from app.features.scenario_lab import (
    ScenarioLabCapabilities,
    ScenarioLabContext,
    ScenarioLabViewState,
)
from app.features.scenario_lab_application import (
    ApprovedScenarioRecipeVersionProjection,
    ScenarioLabAdmissionState,
    ScenarioLabQualityState,
    ScenarioRecipeApprovalAuthorityState,
    ScenarioRecipeApprovalProjection,
    ScenarioLabTaskHandle,
    ScenarioLabUnavailabilityCode,
    ScenarioLabUnavailabilityReason,
)


def test_scenario_lab_1_0_activates_complete_five_feature_registry() -> None:
    assert SCENARIO_LAB_INTERFACE_VERSION.render() == "1.0"
    assert tuple(
        (descriptor.name, descriptor.version.render())
        for descriptor in ACTIVE_FEATURE_INTERFACES
    ) == (
        (FeatureModuleName.STRATEGY_LIBRARY, "1.0"),
        (FeatureModuleName.SCENARIO_LAB, "1.0"),
        (FeatureModuleName.DIAGNOSTIC_TASKS, "1.0"),
        (FeatureModuleName.RUN_MONITORING, "1.2"),
        (FeatureModuleName.EVIDENCE_AND_FINDINGS, "1.1"),
    )
    operations = {
        name
        for name, member in inspect.getmembers(
            ScenarioLabFeature, predicate=inspect.isfunction
        )
        if not name.startswith("_")
    }
    assert operations == {
        "approve_recipe",
        "author_recipe_with_ai",
        "close",
        "compose_scenario_set",
        "create_recipe_draft",
        "materialize_reference_path",
        "resolve_execution_assumptions",
        "retry_materialization",
        "revise_recipe_draft",
        "select_formal_scenario_set",
        "snapshot",
        "subscribe",
        "validate_recipe_draft",
    }


def test_scenario_lab_1_0_freezes_typed_read_and_scenario_composition_state() -> None:
    assert {field.name for field in fields(ScenarioLabViewState)} == {
        "interface_version",
        "revision",
        "observed_at",
        "last_reliable_at",
        "freshness",
        "age",
        "freshness_threshold",
        "source",
        "source_revision",
        "context",
        "phase",
        "presentation",
        "completeness",
        "historical_segments",
        "reference_paths",
        "market_scenarios",
        "transformation_catalog",
        "recipe_drafts",
        "recipe_validations",
        "approved_recipe_versions",
        "task_handles",
        "last_reliable_inventory",
        "capabilities",
        "blocking_reasons",
        "focus_restoration_identity",
        "error",
        "scenario_sets",
        "execution_resolutions",
        "selection_contexts",
    }
    capabilities = ScenarioLabCapabilities.read_only()
    assert capabilities.can_browse
    assert capabilities.can_inspect_bounded_preview
    assert not capabilities.can_create_recipe_draft
    assert not capabilities.can_validate_recipe_draft
    assert not capabilities.can_approve_recipe
    assert not capabilities.can_materialize_reference_path
    assert not capabilities.can_compose_scenario_set
    with pytest.raises(FrozenInstanceError):
        capabilities.can_browse = False  # type: ignore[misc]
    typed_operations = (
        "create_recipe_draft",
        "revise_recipe_draft",
        "validate_recipe_draft",
        "approve_recipe",
        "materialize_reference_path",
        "retry_materialization",
        "compose_scenario_set",
        "resolve_execution_assumptions",
        "select_formal_scenario_set",
    )
    annotations = {
        operation: get_type_hints(getattr(ScenarioLabFeature, operation))
        for operation in typed_operations
    }
    assert len({item["command"] for item in annotations.values()}) == 9
    assert len({item["return"] for item in annotations.values()}) == 9
    assert all(item["command"].__name__.endswith("Command") for item in annotations.values())
    assert all(item["return"].__name__.endswith("Result") for item in annotations.values())
    assert {field.name for field in fields(ScenarioLabTaskHandle)} == {
        "identity",
        "attempt_identity",
        "operation",
        "target_identity",
        "phase",
        "progress",
        "result_identity",
        "error",
        "cancelable",
        "retryable",
        "terminal",
        "predecessor_task_handle_id",
    }


def test_scenario_lab_context_rejects_duplicate_filters() -> None:
    with pytest.raises(ValueError, match="filters"):
        ScenarioLabContext(markets=("cn-a", "cn-a"))


def test_scenario_lab_1_0_freezes_exact_approved_recipe_identity_graph() -> None:
    assert {field.name for field in fields(ScenarioRecipeApprovalProjection)} == {
        "approval_id",
        "draft_id",
        "draft_revision",
        "payload_hash",
        "validation_id",
        "recipe_content_hash",
        "actor_id",
        "approved_at",
        "dependencies",
    }
    assert {
        field.name for field in fields(ApprovedScenarioRecipeVersionProjection)
    } == {
        "recipe_version_id",
        "recipe_id",
        "version_number",
        "content_hash",
        "payload",
        "author_id",
        "approval",
        "based_on_recipe_version_id",
        "authority_state",
        "authority_reasons",
        "can_materialize",
    }
    assert {item.value for item in ScenarioRecipeApprovalAuthorityState} == {
        "current",
        "outdated",
        "incompatible",
        "unavailable",
    }
    assert ScenarioRecipeApprovalProjection.__dataclass_params__.frozen
    assert ApprovedScenarioRecipeVersionProjection.__dataclass_params__.frozen
    assert hasattr(ScenarioRecipeApprovalProjection, "__slots__")
    assert hasattr(ApprovedScenarioRecipeVersionProjection, "__slots__")


def test_scenario_lab_1_0_freezes_distinct_typed_inventory_unavailability() -> None:
    assert {item.value for item in ScenarioLabAdmissionState} == {
        "admitted",
        "missing",
        "incomplete",
        "unavailable",
    }
    assert {item.value for item in ScenarioLabQualityState} == {
        "passed",
        "incomplete",
        "failed",
        "unavailable",
    }
    reason = ScenarioLabUnavailabilityReason(
        code=ScenarioLabUnavailabilityCode.SOURCE_INCOMPLETE,
        summary="Source coverage is incomplete.",
        corrective_guidance="Admit a complete immutable source snapshot.",
    )
    with pytest.raises(FrozenInstanceError):
        reason.summary = "mutable"  # type: ignore[misc]


def test_scenario_lab_surface_has_no_generic_trading_or_manifest_operation() -> None:
    operations = {
        name.casefold()
        for name, member in inspect.getmembers(
            ScenarioLabFeature, predicate=inspect.isfunction
        )
        if not name.startswith("_")
    }
    forbidden = (
        "buy",
        "sell",
        "order",
        "broker",
        "transaction",
        "dispatch",
        "query",
        "manifest",
        "register_transformation",
    )
    assert not {
        operation
        for operation in operations
        if any(marker in operation for marker in forbidden)
    }
