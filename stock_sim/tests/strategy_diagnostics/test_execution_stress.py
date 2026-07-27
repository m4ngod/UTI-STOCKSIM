from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from strategy_diagnostics.execution_conditions import (
    RequestedExecutionAssumptions,
    resolve_execution_conditions,
)
from strategy_diagnostics.market_paths import (
    FiveMinuteBar,
    InstrumentState,
    ScenarioDataWorldInput,
    SessionPriceLimitReference,
)
from strategy_diagnostics.recipes import ScenarioTransformationRequestV1
from strategy_diagnostics.transformations import (
    apply_registered_transformations,
    create_initial_transformation_catalog,
)


def _world() -> ScenarioDataWorldInput:
    return ScenarioDataWorldInput(
        segment_id="execution-stress-segment",
        segment_content_hash="a" * 64,
        source_snapshot_id="execution-stress-snapshot",
        bars=(
            FiveMinuteBar(
                instrument="sh.600000",
                end_time=datetime(2024, 1, 2, 10, 5),
                open=Decimal("10.00"),
                high=Decimal("10.10"),
                low=Decimal("9.90"),
                close=Decimal("10.05"),
                volume=10_000,
                amount=Decimal("100000"),
            ),
        ),
        instrument_states=(
            InstrumentState(
                instrument="sh.600000",
                effective_at=datetime(2024, 1, 2, 9, 30),
                eligible=True,
                trading_status="trading",
                is_st=False,
                industry="banking",
                decision_adjustment_factor=Decimal("1"),
                decision_adjustment_provenance="fixture",
            ),
        ),
        price_limit_references=(
            SessionPriceLimitReference(
                instrument="sh.600000",
                session_date=date(2024, 1, 2),
                previous_close=Decimal("10"),
                effective_at=datetime(2024, 1, 2, 9, 25),
                provenance="fixture",
                profile_version="a-share-cash-equity.v1",
                board="sh-main",
                is_st=False,
                listing_stage="continuous",
                limit_fraction=Decimal("0.10"),
                rule_code="sh-main.ordinary.10pct.effective-2024-01-02",
            ),
        ),
    )


def test_execution_stress_is_a_registered_identity_transformation() -> None:
    world = _world()
    catalog = create_initial_transformation_catalog()
    entry = catalog.get_entry("execution-stress.v1")

    transformed, applied = apply_registered_transformations(
        world,
        (
            ScenarioTransformationRequestV1(
                transformation_id="execution-stress.v1",
                parameters={
                    "commission_bps": "8",
                    "slippage_bps": "25",
                    "latency_nodes": 2,
                    "max_fill_fraction": "0.25",
                    "allow_partial_fills": "true",
                    "rejection_mode": "none",
                },
            ),
        ),
        catalog=catalog,
    )

    assert entry.family == "execution-stress"
    assert entry.implementation_version == "execution-stress.v1"
    assert transformed == world
    assert transformed.bars == world.bars
    assert transformed.instrument_states == world.instrument_states
    assert transformed.price_limit_references == world.price_limit_references
    assert applied[0].to_dict() == {
        "transformation_id": "execution-stress.v1",
        "family": "execution-stress",
        "catalog_version": "scenario-transformation-catalog.v1",
        "implementation_version": "execution-stress.v1",
        "parameters": {
            "allow_partial_fills": "true",
            "commission_bps": "8",
            "latency_nodes": "2",
            "max_fill_fraction": "0.25",
            "rejection_mode": "none",
            "slippage_bps": "25",
        },
        "statistics": {
            "reference_market_path_changed": "false",
        },
    }


def test_scenario_values_override_requested_assumptions_with_reasons() -> None:
    requested = RequestedExecutionAssumptions(
        commission_bps=Decimal("3"),
        slippage_bps=Decimal("5"),
        max_fill_fraction=Decimal("1"),
        latency_nodes=0,
        allow_partial_fills=False,
    )

    resolved = resolve_execution_conditions(
        requested,
        {
            "commission_bps": "8",
            "slippage_bps": "25",
            "latency_nodes": "2",
            "max_fill_fraction": "0.25",
            "allow_partial_fills": "true",
            "rejection_mode": "reject-all",
        },
    )

    assert resolved.requested == requested
    assert resolved.effective.commission_bps == Decimal("8")
    assert resolved.effective.slippage_bps == Decimal("25")
    assert resolved.effective.latency_nodes == 2
    assert resolved.effective.max_fill_fraction == Decimal("0.25")
    assert resolved.effective.allow_partial_fills is True
    assert resolved.effective.rejection_mode == "reject-all"
    assert {item.name: item.override_reason for item in resolved.resolutions} == {
        "allow_partial_fills": "scenario execution-stress.v1 override",
        "commission_bps": "scenario execution-stress.v1 override",
        "latency_nodes": "scenario execution-stress.v1 override",
        "max_fill_fraction": "scenario execution-stress.v1 override",
        "rejection_mode": "scenario execution-stress.v1 override",
        "slippage_bps": "scenario execution-stress.v1 override",
    }


def test_silent_scenario_uses_requested_values_without_fake_override_reasons() -> None:
    requested = RequestedExecutionAssumptions(
        commission_bps=Decimal("4"),
        slippage_bps=Decimal("7"),
        max_fill_fraction=Decimal("0.8"),
        latency_nodes=1,
        allow_partial_fills=True,
    )

    resolved = resolve_execution_conditions(requested, {})

    assert resolved.effective.commission_bps == Decimal("4")
    assert resolved.effective.slippage_bps == Decimal("7")
    assert resolved.effective.max_fill_fraction == Decimal("0.8")
    assert resolved.effective.latency_nodes == 1
    assert resolved.effective.allow_partial_fills is True
    assert resolved.effective.rejection_mode == "none"
    assert all(item.override_reason is None for item in resolved.resolutions)
