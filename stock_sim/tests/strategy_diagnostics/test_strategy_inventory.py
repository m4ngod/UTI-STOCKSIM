from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from strategy_diagnostics import (
    FormalStrategySelectionCandidate,
    FormalStrategySetValidation,
    FormalStrategySetValidationState,
    StrategyInventoryAvailability,
    StrategyInventoryDependencyKind,
    StrategyInventoryReasonCode,
    create_diagnostics_application,
)
from strategy_diagnostics.strategy_inventory import (
    build_strategy_under_test_inventory,
    validate_formal_strategy_set,
)
from strategy_diagnostics.ptrade_host import (
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
    QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
    REFERENCE_PTRADE_STRATEGY_ID,
)


def test_formal_selection_validation_dtos_are_public_package_types() -> None:
    assert FormalStrategySelectionCandidate.__module__.endswith(
        "strategy_inventory"
    )
    assert FormalStrategySetValidation.__module__.endswith(
        "strategy_inventory"
    )
    assert FormalStrategySetValidationState.VALID.value == "valid"


def test_public_application_inventory_exposes_only_formal_v1_strategies() -> None:
    application = create_diagnostics_application()
    application.start()

    inventory = application.read_strategy_under_test_inventory()

    assert tuple(item.strategy_id for item in inventory.entries) == (
        LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
        QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
    )
    assert REFERENCE_PTRADE_STRATEGY_ID not in {
        item.strategy_id for item in inventory.entries
    }
    assert inventory.formal_campaign_required_strategy_count == 2
    assert inventory.persistence_migration_revision == (
        "0018_diagnostic_campaign_attempt_history"
    )
    for entry in inventory.entries:
        assert entry.formal_campaign_eligible
        assert entry.availability == "formal_campaign_ready"
        assert entry.source.content_sha256
        assert entry.compatibility.content_hash
        assert entry.compatibility.surface_version == "ptrade_surface.v1"
        assert entry.candidate_data_policy == (
            "active-scenario-point-in-time-only"
        )
        assert entry.guardrail_profile.strategy_id == entry.strategy_id
        assert entry.guardrail_profile.strategy_version == entry.strategy_version
        assert len(entry.dependencies) == 6
        assert all(item.available for item in entry.dependencies)
        assert all(item.compatible for item in entry.dependencies)

    surface = application.v1_product_surface_inventory()
    assert "read_strategy_under_test_inventory" in surface.application_commands
    assert "validate_formal_strategy_set" in surface.application_commands
    assert surface.unclassified_commands == ()
    assert surface.status == "verified"


def test_missing_guardrail_profiles_remain_visible_without_fabricated_identity() -> None:
    inventory = build_strategy_under_test_inventory(
        guardrail_profiles=(),
        persistence_migration_revision=(
            "0018_diagnostic_campaign_attempt_history"
        ),
    )

    assert len(inventory.entries) == 2
    for entry in inventory.entries:
        assert entry.guardrail_profile is None
        assert not entry.formal_campaign_eligible
        assert entry.availability is (
            StrategyInventoryAvailability.MISSING_DEPENDENCY
        )
        assert any(
            reason.code is StrategyInventoryReasonCode.GUARDRAIL_PROFILE_MISSING
            for reason in entry.availability_reasons
        )
        guardrail_dependency = next(
            dependency
            for dependency in entry.dependencies
            if dependency.kind is StrategyInventoryDependencyKind.GUARDRAIL_PROFILE
        )
        assert not guardrail_dependency.available
        assert not guardrail_dependency.compatible
        assert guardrail_dependency.identity == ""


def test_unavailable_formal_entry_returns_typed_unavailable_validation() -> None:
    inventory = build_strategy_under_test_inventory(
        guardrail_profiles=(),
        persistence_migration_revision=(
            "0018_diagnostic_campaign_attempt_history"
        ),
    )
    validation = validate_formal_strategy_set(
        inventory=inventory,
        candidates=tuple(
            FormalStrategySelectionCandidate(
                strategy_id=entry.strategy_id,
                strategy_version=entry.strategy_version,
                manifest_content_hash=entry.compatibility.content_hash,
                guardrail_profile_id="",
                guardrail_profile_version="",
                dependencies=entry.dependencies,
            )
            for entry in inventory.entries
        ),
        expected_inventory_content_hash=inventory.content_hash,
    )

    assert validation.state is FormalStrategySetValidationState.UNAVAILABLE
    assert validation.entries == ()
    assert validation.reasons
    assert "Guardrail" in validation.reasons[0].summary


def test_inventory_content_hash_covers_exposed_authoritative_facts() -> None:
    application = create_diagnostics_application()
    application.start()
    inventory = application.read_strategy_under_test_inventory()
    entry = inventory.entries[0]
    profile = entry.guardrail_profile
    assert profile is not None
    threshold = profile.thresholds[0]

    changed_entries = (
        replace(entry, display=replace(entry.display, summary="Changed summary")),
        replace(entry, candidate_data_policy="changed-candidate-data-policy"),
        replace(
            entry,
            guardrail_profile=replace(
                profile,
                thresholds=(
                    replace(
                        threshold,
                        value=threshold.value + Decimal("0.01"),
                    ),
                    *profile.thresholds[1:],
                ),
            ),
        ),
    )
    changed_inventories = (
        replace(
            inventory,
            persistence_migration_revision="changed-migration-revision",
        ),
        replace(
            inventory,
            formal_campaign_required_strategy_count=(
                inventory.formal_campaign_required_strategy_count + 1
            ),
        ),
        *(
            replace(
                inventory,
                entries=(changed_entry, *inventory.entries[1:]),
            )
            for changed_entry in changed_entries
        ),
    )

    assert all(
        changed.content_hash != inventory.content_hash
        for changed in changed_inventories
    )
    guardrail_dependency = next(
        dependency
        for dependency in entry.dependencies
        if dependency.kind is StrategyInventoryDependencyKind.GUARDRAIL_PROFILE
    )
    assert guardrail_dependency.content_hash != profile.profile_id
    assert len(guardrail_dependency.content_hash) == 64
