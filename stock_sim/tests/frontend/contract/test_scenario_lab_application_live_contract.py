from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest

from app.features.scenario_lab_application import (
    SCENARIO_LAB_APPLICATION_INTERFACE_VERSION,
    LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter,
    ScenarioLabApplicationAvailability,
    StrategyDiagnosticsV1ScenarioLabApplication,
)
from strategy_diagnostics import create_diagnostics_application


def test_scenario_lab_application_1_0_is_a_separate_exact_surface() -> None:
    assert SCENARIO_LAB_APPLICATION_INTERFACE_VERSION.render() == "1.0"
    operations = {
        name
        for name, member in inspect.getmembers(
            StrategyDiagnosticsV1ScenarioLabApplication,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    assert operations == {
        "approve_recipe",
        "compose_scenario_set",
        "create_recipe_draft",
        "materialize_reference_path",
        "read_inventory",
        "resolve_execution_assumptions",
        "retry_materialization",
        "revise_recipe_draft",
        "select_formal_scenario_set",
        "validate_recipe_draft",
    }


def test_live_scenario_lab_application_reads_only_public_backend_behavior() -> None:
    application = create_diagnostics_application()
    application.start()
    adapter = LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter(application)

    result = adapter.read_inventory()

    assert adapter.interface_version.render() == "1.0"
    assert result.availability is ScenarioLabApplicationAvailability.EMPTY
    assert result.inventory is not None
    assert result.inventory.historical_segments == ()
    assert result.inventory.reference_paths == ()
    assert result.inventory.market_scenarios == ()
    assert result.inventory.transformation_catalog.entries
    source = inspect.getsource(
        LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter
    )
    for forbidden in (
        "Repository",
        "ArtifactStore",
        "Session(",
        "Path(",
        "glob(",
        "rglob(",
        "RuntimeGateway",
        "EventBridge",
    ):
        assert forbidden not in source
    for required in (
        ".read_diagnostic_campaign_case_inventory()",
        ".transformation_catalog_view()",
        ".preview_reference_market_path(",
    ):
        assert required in source


def test_reference_path_preview_rejects_non_boolean_reconstruction_marker() -> None:
    from app.features.scenario_lab_application import _map_preview

    payload = {
        "latest_nodes": {
            "000001.SZ": {
                "instrument": "000001.SZ",
                "simulation_time": "2026-01-02T09:30:00+00:00",
                "open": "10.00",
                "high": "10.10",
                "low": "9.90",
                "close": "10.05",
                "volume": 100,
                "amount": "1005.00",
                "reconstructed": "false",
            }
        },
        "eligible_universe": ["000001.SZ"],
        "path_statistics": {"node_count": 1},
    }

    with pytest.raises(TypeError, match="reconstructed marker"):
        _map_preview(
            payload,
            at_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
            limit=24,
        )
