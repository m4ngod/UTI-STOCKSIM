from __future__ import annotations

import inspect

from app.features.strategy_library_application import (
    STRATEGY_LIBRARY_APPLICATION_INTERFACE_VERSION,
    LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter,
    StrategyDiagnosticsV1StrategyLibraryApplication,
    StrategyLibraryApplicationAvailability,
)
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
