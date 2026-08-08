from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError, fields

import pytest

from app.features import (
    ACTIVE_FEATURE_INTERFACES,
    STRATEGY_LIBRARY_INTERFACE_VERSION,
    FeatureModuleName,
    StrategyLibraryFeature,
)
from app.features.strategy_library import (
    StrategyLibraryContext,
    StrategyLibraryViewState,
)
from app.features.strategy_library_application import (
    LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter,
    StrategyAvailability,
    StrategyAvailabilityReasonCode,
    StrategyDependencyKind,
)
from strategy_diagnostics import create_diagnostics_application


def test_strategy_library_1_0_activates_its_complete_operation_surface() -> None:
    assert STRATEGY_LIBRARY_INTERFACE_VERSION.render() == "1.0"
    assert tuple(
        (descriptor.name, descriptor.version.render())
        for descriptor in ACTIVE_FEATURE_INTERFACES
    ) == (
        (FeatureModuleName.STRATEGY_LIBRARY, "1.0"),
        (FeatureModuleName.SCENARIO_LAB, "1.0"),
        (FeatureModuleName.DIAGNOSTIC_TASKS, "1.0"),
        (FeatureModuleName.RUN_MONITORING, "1.2"),
        (FeatureModuleName.EVIDENCE_AND_FINDINGS, "1.1"),
        (FeatureModuleName.SYSTEM_HEALTH, "1.0"),
    )

    operations = {
        name
        for name, member in inspect.getmembers(
            StrategyLibraryFeature,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    assert operations == {
        "close",
        "compare_strategies",
        "select_formal_strategy_set",
        "snapshot",
        "subscribe",
    }


def test_strategy_library_1_0_freezes_complete_typed_state_shapes() -> None:
    assert {item.value for item in StrategyAvailability} == {
        "formal_campaign_ready",
        "unavailable",
        "outdated",
        "incompatible",
        "missing_dependency",
    }
    assert {item.value for item in StrategyDependencyKind} == {
        "retained_source",
        "packaged_source",
        "compatibility_manifest",
        "ptrade_surface",
        "candidate_data_policy",
        "guardrail_profile",
    }
    assert {field.name for field in fields(StrategyLibraryViewState)} == {
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
        "entries",
        "last_reliable_inventory",
        "capabilities",
        "blocking_reasons",
        "focus_restoration_id",
        "error",
        "selection",
        "selection_status",
        "selection_message",
    }

    application = create_diagnostics_application()
    application.start()
    result = LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
        application
    ).read_inventory()
    assert result.inventory is not None
    entry = result.inventory.entries[0]
    assert isinstance(entry.source.lineage, tuple)
    assert isinstance(entry.dependencies, tuple)
    assert isinstance(entry.availability_reasons, tuple)
    assert len(entry.dependencies) == len(StrategyDependencyKind)
    assert entry.availability_reasons[0].code is (
        StrategyAvailabilityReasonCode.FORMAL_CAMPAIGN_READY
    )
    assert entry.guardrail_profile is not None
    assert entry.guardrail_profile.strategy_id == entry.strategy_id
    assert entry.guardrail_profile.strategy_version == entry.strategy_version
    with pytest.raises(FrozenInstanceError):
        entry.strategy_version = "mutated"  # type: ignore[misc]


def test_strategy_library_context_rejects_duplicate_capability_filters() -> None:
    with pytest.raises(ValueError, match="capability filters"):
        StrategyLibraryContext(
            required_capabilities=("get_history", "get_history"),
        )


def test_strategy_library_surface_contains_no_admin_trading_or_dispatch_action() -> None:
    operations = {
        name.casefold()
        for name, member in inspect.getmembers(
            StrategyLibraryFeature,
            predicate=inspect.isfunction,
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
        "register",
        "import",
        "retire",
        "source_edit",
        "execute",
    )
    assert not {
        operation
        for operation in operations
        if any(marker in operation for marker in forbidden)
    }
