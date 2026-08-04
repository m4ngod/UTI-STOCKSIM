from __future__ import annotations

import inspect

from app.features.strategy_library_application import (
    STRATEGY_LIBRARY_APPLICATION_INTERFACE_VERSION,
    FormalStrategySelectionReference,
    FormalStrategySetValidationState,
    LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter,
    StrategyDiagnosticsV1StrategyLibraryApplication,
    StrategyLibraryApplicationAvailability,
    ValidateFormalStrategySet,
)
from app.features.diagnostic_tasks_application import GuardrailProfileId
from app.features.strategy_diagnostics_v1_read_model import SourceRevisionToken
from strategy_diagnostics import create_diagnostics_application


def test_strategy_library_application_1_0_is_a_separate_exact_surface() -> None:
    assert STRATEGY_LIBRARY_APPLICATION_INTERFACE_VERSION.render() == "1.0"
    operations = {
        name
        for name, member in inspect.getmembers(
            StrategyDiagnosticsV1StrategyLibraryApplication,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    assert operations == {"read_inventory", "validate_formal_strategy_set"}


def test_live_application_adapter_reads_the_public_backend_inventory() -> None:
    application = create_diagnostics_application()
    application.start()
    adapter = LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
        application
    )

    result = adapter.read_inventory()

    assert adapter.interface_version.render() == "1.0"
    assert result.availability is StrategyLibraryApplicationAvailability.READY
    assert result.error is None
    assert result.source_token is not None
    assert result.inventory is not None
    assert len(result.inventory.entries) == 2
    assert all(
        entry.formal_campaign_eligible for entry in result.inventory.entries
    )
    assert all(
        entry.guardrail_profile.thresholds
        for entry in result.inventory.entries
    )


def test_live_application_adapter_does_not_discover_strategy_sources() -> None:
    source = inspect.getsource(
        LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter
    )

    for forbidden in (
        "FORMAL_STRATEGY_SOURCE_BINDINGS",
        "PTRADE_COMPATIBILITY_MANIFESTS",
        "Path(",
        "glob(",
        "rglob(",
        "iterdir(",
        "find_spec(",
        "import_module(",
        "Repository",
        "ArtifactStore",
        "_persistence",
    ):
        assert forbidden not in source
    assert ".read_strategy_under_test_inventory()" in source


def _formal_references(
    adapter: LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter,
) -> tuple[FormalStrategySelectionReference, ...]:
    result = adapter.read_inventory()
    assert result.inventory is not None
    return tuple(
        FormalStrategySelectionReference(
            strategy_id=entry.strategy_id,
            strategy_version=entry.strategy_version,
            manifest_content_hash=entry.compatibility.content_hash,
            guardrail_profile_id=entry.guardrail_profile.profile_id,
            guardrail_profile_version=entry.guardrail_profile.profile_version,
            dependency_identities=entry.dependencies,
        )
        for entry in result.inventory.entries
    )


def test_live_application_validates_the_exact_backend_declared_formal_set() -> None:
    application = create_diagnostics_application()
    application.start()
    adapter = LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
        application
    )
    inventory = adapter.read_inventory()
    assert inventory.source_token is not None

    validation = adapter.validate_formal_strategy_set(
        ValidateFormalStrategySet(
            selections=_formal_references(adapter),
            expected_source_revision=inventory.source_token,
        )
    )

    assert validation.state is FormalStrategySetValidationState.VALID
    assert len(validation.selections) == 2
    assert validation.source_revision == inventory.source_token
    assert validation.reasons == ()


def test_live_application_rejects_conflict_duplicate_and_guardrail_mismatch() -> None:
    application = create_diagnostics_application()
    application.start()
    adapter = LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter(
        application
    )
    inventory = adapter.read_inventory()
    assert inventory.source_token is not None
    references = _formal_references(adapter)

    conflict = adapter.validate_formal_strategy_set(
        ValidateFormalStrategySet(
            selections=references,
            expected_source_revision=SourceRevisionToken("0" * 64),
        )
    )
    duplicate = adapter.validate_formal_strategy_set(
        ValidateFormalStrategySet(
            selections=(references[0], references[0]),
            expected_source_revision=inventory.source_token,
        )
    )
    mismatched = adapter.validate_formal_strategy_set(
        ValidateFormalStrategySet(
            selections=(
                references[0],
                FormalStrategySelectionReference(
                    strategy_id=references[1].strategy_id,
                    strategy_version=references[1].strategy_version,
                    manifest_content_hash=(
                        references[1].manifest_content_hash
                    ),
                    guardrail_profile_id=GuardrailProfileId(
                        "guardrail-profile-mismatched"
                    ),
                    guardrail_profile_version=(
                        references[1].guardrail_profile_version
                    ),
                    dependency_identities=(
                        references[1].dependency_identities
                    ),
                ),
            ),
            expected_source_revision=inventory.source_token,
        )
    )

    assert conflict.state is FormalStrategySetValidationState.SOURCE_CONFLICT
    assert conflict.source_revision == inventory.source_token
    assert duplicate.state is FormalStrategySetValidationState.INVALID
    assert duplicate.selections == ()
    assert mismatched.state is FormalStrategySetValidationState.INVALID
    assert mismatched.selections == ()
    assert any("Guardrail" in reason.summary for reason in mismatched.reasons)
