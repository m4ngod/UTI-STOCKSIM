from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

import pytest
from sqlalchemy import create_engine, inspect, text

from strategy_diagnostics import (
    AdmissionCheck,
    FiveMinuteBar,
    HistoricalSegmentSelection,
    HistoricalSourceInspection,
    InMemoryMarketPathArtifactStore,
    InstrumentState,
    ScenarioDataWorldInput,
    ScenarioRecipeV1,
    SourceArtifact,
    SourceProvenance,
    UnapprovedScenarioRecipeError,
    create_diagnostics_application,
)
from strategy_diagnostics.persistence import SqlScenarioRecipeRepository


_REQUIRED_CHECKS = (
    "bar_continuity",
    "instrument_coverage",
    "eligible_universe",
    "trading_status",
    "st_status",
    "suspension_state",
    "industry_as_of",
    "adjustment_consistency",
    "causal_availability",
    "required_fields",
    "missing_data",
    "duplicates",
    "timestamps",
)


class _RecipeFixtureSource:
    def __init__(self) -> None:
        self.selection = HistoricalSegmentSelection(
            market="mainland-a-share",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 2),
        )

    def inspect(
        self,
        selection: HistoricalSegmentSelection,
    ) -> HistoricalSourceInspection | None:
        if selection != self.selection:
            return None
        return HistoricalSourceInspection(
            selection=selection,
            label="Recipe lifecycle fixture",
            provenance=SourceProvenance(
                provider="Fixture",
                dataset="recipe-lifecycle",
                version="v1",
                observed_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
            ),
            artifacts=(SourceArtifact("bars", "a" * 64, 1),),
            eligible_instrument_count=1,
            trading_day_count=1,
            bar_count=1,
            checks=tuple(
                AdmissionCheck(code, True, f"{code} passed")
                for code in _REQUIRED_CHECKS
            ),
        )

    def load_scenario_data_world(self, segment: object) -> ScenarioDataWorldInput:
        return ScenarioDataWorldInput(
            segment_id=str(getattr(segment, "segment_id")),
            segment_content_hash=str(getattr(segment, "content_hash")),
            source_snapshot_id=str(getattr(segment, "source_snapshot_id")),
            bars=(
                FiveMinuteBar(
                    instrument="sh.600000",
                    end_time=datetime(2024, 1, 2, 9, 35),
                    open=Decimal("10"),
                    high=Decimal("10.2"),
                    low=Decimal("9.9"),
                    close=Decimal("10.1"),
                    volume=100,
                    amount=Decimal("1005"),
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
                    decision_adjustment_provenance="fixture-v1",
                ),
            ),
        )


def _baseline_payload(segment_id: str) -> dict[str, object]:
    return {
        "schema_version": "scenario_recipe.v1",
        "name": "Baseline control",
        "historical_segment_id": segment_id,
        "transformations": [],
        "execution_conditions": {
            "commission_bps": "3",
            "slippage_bps": "0",
            "max_fill_fraction": "1",
            "latency_nodes": 0,
            "allow_partial_fills": True,
        },
        "decision_cadence_minutes": 30,
        "materialization_seed": 17,
        "data_policy": "point-in-time",
        "market_rule_profile": "a-share-cash-equity.v1",
    }


def _application_with_admitted_segment() -> tuple[object, str]:
    source = _RecipeFixtureSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_clock=lambda: datetime(2026, 7, 22, 5, 0, tzinfo=timezone.utc),
    )
    application.start()
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    return application, admission.segment.segment_id


def test_scenario_recipe_v1_has_stable_schema_canonical_json_and_hash() -> None:
    recipe = ScenarioRecipeV1(
        name="Baseline control",
        historical_segment_id="segment_fixture",
        execution_conditions={
            "commission_bps": Decimal("3.000"),
            "slippage_bps": Decimal("0.00"),
            "max_fill_fraction": Decimal("1.0000"),
            "latency_nodes": 0,
            "allow_partial_fills": True,
        },
        decision_cadence_minutes=30,
        materialization_seed=17,
    )

    assert recipe.canonical_json() == (
        '{"data_policy":"point-in-time","decision_cadence_minutes":30,'
        '"execution_conditions":{"allow_partial_fills":true,'
        '"commission_bps":"3","latency_nodes":0,'
        '"max_fill_fraction":"1","slippage_bps":"0"},'
        '"historical_segment_id":"segment_fixture",'
        '"market_rule_profile":"a-share-cash-equity.v1",'
        '"materialization_seed":17,"name":"Baseline control",'
        '"schema_version":"scenario_recipe.v1","transformations":[]}'
    )
    assert recipe.content_hash == (
        "f844c112fe4f08c632ae1e7f0b0aed87c3753678699995ed94d1c115c98f2b52"
    )

    schema = ScenarioRecipeV1.stable_json_schema()
    assert schema == ScenarioRecipeV1.stable_json_schema()
    assert schema["$id"] == "https://uti-stocksim.local/schema/scenario-recipe-v1.json"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["decision_cadence_minutes"]["enum"] == [30, 60]
    canonical_payload = json.loads(recipe.canonical_json())
    execution_schema = schema["definitions"]["ExecutionConditionsV1"][
        "properties"
    ]
    for field in ("commission_bps", "slippage_bps", "max_fill_fraction"):
        wire_value = canonical_payload["execution_conditions"][field]
        field_schema = execution_schema[field]
        assert field_schema["type"] == "string"
        assert isinstance(wire_value, str)
        assert re.fullmatch(field_schema["pattern"], wire_value)
    schema_json = json.dumps(
        schema,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert hashlib.sha256(schema_json.encode("utf-8")).hexdigest() == (
        "d0a87785563d7bef98a90ed77fc307e6b3e0268f0955454034b265ee485b9928"
    )


def test_manual_recipe_requires_validation_and_approval_before_materialization() -> None:
    approved_at = datetime(2026, 7, 22, 5, 0, tzinfo=timezone.utc)
    source = _RecipeFixtureSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_clock=lambda: approved_at,
    )
    application.start()
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None

    draft = application.create_manual_recipe_draft(
        _baseline_payload(admission.segment.segment_id),
        author="researcher",
    )
    assert draft.status == "untrusted"

    with pytest.raises(UnapprovedScenarioRecipeError, match="approved"):
        application.materialize_baseline_reference_path(draft.draft_id)

    validation = application.validate_recipe_draft(draft.draft_id)
    assert validation.is_valid is True
    assert validation.issues == ()

    with pytest.raises(UnapprovedScenarioRecipeError, match="approved"):
        application.materialize_baseline_reference_path(draft.draft_id)

    approved = application.approve_recipe_draft(
        draft.draft_id,
        actor="owner",
    )
    assert approved.version_number == 1
    assert approved.approval_actor == "owner"
    assert approved.approved_at == approved_at
    assert approved.content_hash == validation.recipe_content_hash

    materialized = application.materialize_baseline_reference_path(
        approved.version_id
    )
    assert materialized.segment_id == admission.segment.segment_id


@pytest.mark.parametrize(
    ("change", "expected_rule"),
    (
        ({"unsupported_field": True}, "schema.unknown-field"),
        ({"historical_segment_id": "missing_segment"}, "data.admitted-segment-required"),
        (
            {
                "execution_conditions": {
                    "commission_bps": "101",
                    "slippage_bps": "0",
                    "max_fill_fraction": "1",
                    "latency_nodes": 0,
                    "allow_partial_fills": True,
                }
            },
            "bounds.invalid",
        ),
        ({"data_policy": "future-aware"}, "causality.point-in-time-required"),
        (
            {
                "transformations": [
                    {"transformation_id": "missing-transform.v1", "parameters": {}}
                ]
            },
            "transformation.not-registered",
        ),
        (
            {
                "transformations": [
                    {
                        "transformation_id": "trend-regime.v1",
                        "parameters": {"direction": "bullish", "strength": "1.1"},
                    }
                ]
            },
            "transformation.parameter-bounds",
        ),
        (
            {
                "transformations": [
                    {
                        "transformation_id": "trend-regime.v1",
                        "parameters": {"direction": "bullish", "strength": "0.2"},
                    },
                    {
                        "transformation_id": "trend-regime.v1",
                        "parameters": {"direction": "bearish", "strength": "0.2"},
                    },
                ]
            },
            "transformation.incompatible-combination",
        ),
    ),
)
def test_recipe_validation_fails_closed_with_actionable_rules(
    change: dict[str, object],
    expected_rule: str,
) -> None:
    application, segment_id = _application_with_admitted_segment()
    payload = _baseline_payload(segment_id)
    payload.update(change)

    draft = application.create_manual_recipe_draft(payload, author="researcher")
    result = application.validate_recipe_draft(draft.draft_id)

    assert result.is_valid is False
    assert expected_rule in {issue.rule for issue in result.issues}
    assert all(issue.path and issue.correction for issue in result.issues)
    with pytest.raises(UnapprovedScenarioRecipeError, match="validation"):
        application.approve_recipe_draft(draft.draft_id, actor="owner")


def test_headless_catalog_registers_versioned_transforms_with_typed_bounds() -> None:
    application, segment_id = _application_with_admitted_segment()

    catalog = application.transformation_catalog_view()

    assert catalog == {
        "catalog_version": "scenario-transformation-catalog.v1",
        "transformations": [
            {
                "transformation_id": "execution-stress.v1",
                "family": "execution-stress",
                "implementation_version": "execution-stress.v1",
                "parameters": [
                    {
                        "name": "commission_bps",
                        "value_type": "decimal",
                        "required": False,
                        "minimum": "0",
                        "maximum": "100",
                    },
                    {
                        "name": "slippage_bps",
                        "value_type": "decimal",
                        "required": False,
                        "minimum": "0",
                        "maximum": "1000",
                    },
                    {
                        "name": "latency_nodes",
                        "value_type": "integer",
                        "required": False,
                        "minimum": "0",
                        "maximum": "120",
                    },
                    {
                        "name": "max_fill_fraction",
                        "value_type": "decimal",
                        "required": False,
                        "minimum": "0.01",
                        "maximum": "1",
                    },
                    {
                        "name": "allow_partial_fills",
                        "value_type": "enum",
                        "required": False,
                        "choices": ["false", "true"],
                    },
                    {
                        "name": "rejection_mode",
                        "value_type": "enum",
                        "required": False,
                        "choices": ["none", "reject-all"],
                    },
                ],
                "compatibility_rules": [
                    "a-share-cash-equity.v1",
                    "one-transform-per-family",
                    "execution-only-reference-path-identity",
                ],
                "causality_constraints": [
                    "point-in-time-inputs-only",
                    "deterministic-no-future-reads",
                    "private-portfolio-effects-only",
                ],
            },
            {
                "transformation_id": "liquidity-stress.v1",
                "family": "liquidity",
                "implementation_version": "liquidity-stress.v1",
                "parameters": [
                    {
                        "name": "volume_multiplier",
                        "value_type": "decimal",
                        "required": True,
                        "minimum": "0.25",
                        "maximum": "2",
                    },
                    {
                        "name": "cross_sectional_concentration",
                        "value_type": "decimal",
                        "required": True,
                        "minimum": "0",
                        "maximum": "1",
                    },
                ],
                "compatibility_rules": [
                    "a-share-cash-equity.v1",
                    "one-transform-per-family",
                    "conserve-declared-scaled-volume-per-source-time",
                ],
                "causality_constraints": [
                    "point-in-time-inputs-only",
                    "deterministic-no-future-reads",
                ],
            },
            {
                "transformation_id": "market-structure.v1",
                "family": "market-structure",
                "implementation_version": "market-structure.v1",
                "parameters": [
                    {
                        "name": "breadth_target",
                        "value_type": "decimal",
                        "required": True,
                        "minimum": "0.1",
                        "maximum": "0.9",
                    },
                    {
                        "name": "dispersion_fraction",
                        "value_type": "decimal",
                        "required": True,
                        "minimum": "0.01",
                        "maximum": "0.1",
                    },
                    {
                        "name": "sector_concentration",
                        "value_type": "decimal",
                        "required": True,
                        "minimum": "0",
                        "maximum": "1",
                    },
                ],
                "compatibility_rules": [
                    "a-share-cash-equity.v1",
                    "one-transform-per-family",
                    "cross-sectional-world-with-multiple-industries",
                ],
                "causality_constraints": [
                    "point-in-time-inputs-only",
                    "deterministic-no-future-reads",
                ],
            },
            {
                "transformation_id": "shock-recovery.v1",
                "family": "shock-recovery",
                "implementation_version": "shock-recovery.v1",
                "parameters": [
                    {
                        "name": "direction",
                        "value_type": "enum",
                        "required": True,
                        "choices": ["bearish", "bullish"],
                    },
                    {
                        "name": "gap_fraction",
                        "value_type": "decimal",
                        "required": True,
                        "minimum": "0",
                        "maximum": "0.1",
                    },
                    {
                        "name": "shock_fraction",
                        "value_type": "decimal",
                        "required": True,
                        "minimum": "0.01",
                        "maximum": "0.2",
                    },
                    {
                        "name": "shock_duration_bars",
                        "value_type": "integer",
                        "required": True,
                        "minimum": "1",
                        "maximum": "12",
                    },
                    {
                        "name": "persistence_duration_bars",
                        "value_type": "integer",
                        "required": True,
                        "minimum": "0",
                        "maximum": "24",
                    },
                    {
                        "name": "recovery_duration_bars",
                        "value_type": "integer",
                        "required": True,
                        "minimum": "1",
                        "maximum": "24",
                    },
                ],
                "compatibility_rules": [
                    "a-share-cash-equity.v1",
                    "one-transform-per-family",
                    "ordered-gap-shock-persistence-recovery",
                ],
                "causality_constraints": [
                    "point-in-time-inputs-only",
                    "deterministic-no-future-reads",
                ],
            },
            {
                "transformation_id": "trend-regime.v1",
                "family": "trend-regime",
                "implementation_version": "trend-regime.v1",
                "parameters": [
                    {
                        "name": "direction",
                        "value_type": "enum",
                        "required": True,
                        "choices": ["bearish", "bullish"],
                    },
                    {
                        "name": "strength",
                        "value_type": "decimal",
                        "required": True,
                        "minimum": "0",
                        "maximum": "1",
                    },
                ],
                "compatibility_rules": [
                    "a-share-cash-equity.v1",
                    "one-transform-per-family",
                ],
                "causality_constraints": [
                    "point-in-time-inputs-only",
                    "deterministic-no-future-reads",
                ],
            },
            {
                "transformation_id": "volatility-scaling.v1",
                "family": "volatility",
                "implementation_version": "volatility-scaling.v1",
                "parameters": [
                    {
                        "name": "multiplier",
                        "value_type": "decimal",
                        "required": True,
                        "minimum": "0.5",
                        "maximum": "2",
                    }
                ],
                "compatibility_rules": [
                    "a-share-cash-equity.v1",
                    "one-transform-per-family",
                ],
                "causality_constraints": [
                    "point-in-time-inputs-only",
                    "deterministic-no-future-reads",
                ],
            },
        ],
    }

    payload = _baseline_payload(segment_id)
    payload["transformations"] = [
        {
            "transformation_id": "volatility-scaling.v1",
            "parameters": {"multiplier": "1.5"},
        }
    ]
    draft = application.create_manual_recipe_draft(payload, author="researcher")

    validation = application.validate_recipe_draft(draft.draft_id)

    assert validation.is_valid is True
    assert validation.issues == ()

    payload["transformations"] = [
        {
            "transformation_id": "shock-recovery.v1",
            "parameters": {
                "direction": "bearish",
                "gap_fraction": "0.01",
                "shock_fraction": "0.03",
                "shock_duration_bars": 2,
                "persistence_duration_bars": 1,
                "recovery_duration_bars": 2,
            },
        }
    ]
    shock_draft = application.create_manual_recipe_draft(
        payload,
        author="researcher",
    )

    shock_validation = application.validate_recipe_draft(shock_draft.draft_id)

    assert shock_validation.is_valid is True
    assert shock_validation.issues == ()

    payload["transformations"] = [
        {
            "transformation_id": "market-structure.v1",
            "parameters": {
                "breadth_target": "0.5",
                "dispersion_fraction": "0.04",
                "sector_concentration": "1",
            },
        }
    ]
    structure_draft = application.create_manual_recipe_draft(
        payload,
        author="researcher",
    )

    structure_validation = application.validate_recipe_draft(
        structure_draft.draft_id
    )

    assert structure_validation.is_valid is True
    assert structure_validation.issues == ()

    payload["transformations"] = [
        {
            "transformation_id": "liquidity-stress.v1",
            "parameters": {
                "volume_multiplier": "0.5",
                "cross_sectional_concentration": "0.75",
            },
        }
    ]
    liquidity_draft = application.create_manual_recipe_draft(
        payload,
        author="researcher",
    )

    liquidity_validation = application.validate_recipe_draft(
        liquidity_draft.draft_id
    )

    assert liquidity_validation.is_valid is True
    assert liquidity_validation.issues == ()


@pytest.mark.parametrize("multiplier", ("0.49", "2.01"))
def test_volatility_scaling_rejects_values_outside_published_bounds(
    multiplier: str,
) -> None:
    application, segment_id = _application_with_admitted_segment()
    payload = _baseline_payload(segment_id)
    payload["transformations"] = [
        {
            "transformation_id": "volatility-scaling.v1",
            "parameters": {"multiplier": multiplier},
        }
    ]
    draft = application.create_manual_recipe_draft(payload, author="researcher")

    validation = application.validate_recipe_draft(draft.draft_id)

    assert validation.is_valid is False
    assert {issue.rule for issue in validation.issues} == {
        "transformation.parameter-bounds"
    }
    assert validation.issues[0].path == "transformations.0.parameters.multiplier"
    assert validation.issues[0].correction == "Choose a value from 0.5 through 2."
    with pytest.raises(UnapprovedScenarioRecipeError, match="validation"):
        application.approve_recipe_draft(draft.draft_id, actor="owner")


@pytest.mark.parametrize(
    ("parameter", "value", "expected_rule"),
    (
        ("gap_fraction", "0.11", "transformation.parameter-bounds"),
        ("shock_fraction", "0.201", "transformation.parameter-bounds"),
        ("shock_duration_bars", "1.5", "transformation.parameter-type"),
        ("persistence_duration_bars", "25", "transformation.parameter-bounds"),
        ("recovery_duration_bars", "0", "transformation.parameter-bounds"),
    ),
)
def test_shock_recovery_rejects_invalid_phase_parameters(
    parameter: str,
    value: str,
    expected_rule: str,
) -> None:
    application, segment_id = _application_with_admitted_segment()
    parameters = {
        "direction": "bearish",
        "gap_fraction": "0.01",
        "shock_fraction": "0.03",
        "shock_duration_bars": "2",
        "persistence_duration_bars": "1",
        "recovery_duration_bars": "2",
    }
    parameters[parameter] = value
    payload = _baseline_payload(segment_id)
    payload["transformations"] = [
        {
            "transformation_id": "shock-recovery.v1",
            "parameters": parameters,
        }
    ]
    draft = application.create_manual_recipe_draft(payload, author="researcher")

    validation = application.validate_recipe_draft(draft.draft_id)

    assert validation.is_valid is False
    assert {issue.rule for issue in validation.issues} == {expected_rule}
    assert validation.issues[0].path == f"transformations.0.parameters.{parameter}"
    with pytest.raises(UnapprovedScenarioRecipeError, match="validation"):
        application.approve_recipe_draft(draft.draft_id, actor="owner")


@pytest.mark.parametrize(
    ("parameter", "value"),
    (
        ("breadth_target", "0.09"),
        ("breadth_target", "0.91"),
        ("dispersion_fraction", "0.009"),
        ("dispersion_fraction", "0.101"),
        ("sector_concentration", "-0.01"),
        ("sector_concentration", "1.01"),
    ),
)
def test_market_structure_rejects_values_outside_published_bounds(
    parameter: str,
    value: str,
) -> None:
    application, segment_id = _application_with_admitted_segment()
    parameters = {
        "breadth_target": "0.5",
        "dispersion_fraction": "0.04",
        "sector_concentration": "1",
    }
    parameters[parameter] = value
    payload = _baseline_payload(segment_id)
    payload["transformations"] = [
        {
            "transformation_id": "market-structure.v1",
            "parameters": parameters,
        }
    ]
    draft = application.create_manual_recipe_draft(payload, author="researcher")

    validation = application.validate_recipe_draft(draft.draft_id)

    assert validation.is_valid is False
    assert {issue.rule for issue in validation.issues} == {
        "transformation.parameter-bounds"
    }
    assert validation.issues[0].path == (
        f"transformations.0.parameters.{parameter}"
    )
    with pytest.raises(UnapprovedScenarioRecipeError, match="validation"):
        application.approve_recipe_draft(draft.draft_id, actor="owner")


@pytest.mark.parametrize(
    ("parameter", "value"),
    (
        ("volume_multiplier", "0.249"),
        ("volume_multiplier", "2.001"),
        ("cross_sectional_concentration", "-0.01"),
        ("cross_sectional_concentration", "1.01"),
    ),
)
def test_liquidity_stress_rejects_values_outside_published_bounds(
    parameter: str,
    value: str,
) -> None:
    application, segment_id = _application_with_admitted_segment()
    parameters = {
        "volume_multiplier": "0.5",
        "cross_sectional_concentration": "0.75",
    }
    parameters[parameter] = value
    payload = _baseline_payload(segment_id)
    payload["transformations"] = [
        {
            "transformation_id": "liquidity-stress.v1",
            "parameters": parameters,
        }
    ]
    draft = application.create_manual_recipe_draft(payload, author="researcher")

    validation = application.validate_recipe_draft(draft.draft_id)

    assert validation.is_valid is False
    assert {issue.rule for issue in validation.issues} == {
        "transformation.parameter-bounds"
    }
    assert validation.issues[0].path == (
        f"transformations.0.parameters.{parameter}"
    )


@pytest.mark.parametrize(
    ("forbidden_parameter", "expected_rule"),
    (
        ({"python_code": "prices *= 2"}, "transformation.executable-code-forbidden"),
        ({"expression": "close * 1.1"}, "transformation.expression-forbidden"),
        ({"source_path": "C:\\market\\prices.csv"}, "transformation.path-forbidden"),
        ({"final_prices": {"sh.600000": "99"}}, "transformation.final-price-edit-forbidden"),
    ),
)
def test_recipe_rejects_non_declarative_transformation_payloads(
    forbidden_parameter: dict[str, object],
    expected_rule: str,
) -> None:
    application, segment_id = _application_with_admitted_segment()
    payload = _baseline_payload(segment_id)
    parameters: dict[str, object] = {
        "direction": "bullish",
        "strength": "0.5",
    }
    parameters.update(forbidden_parameter)
    payload["transformations"] = [
        {
            "transformation_id": "trend-regime.v1",
            "parameters": parameters,
        }
    ]
    draft = application.create_manual_recipe_draft(payload, author="researcher")

    validation = application.validate_recipe_draft(draft.draft_id)

    assert validation.is_valid is False
    assert expected_rule in {issue.rule for issue in validation.issues}
    assert all(issue.path and issue.correction for issue in validation.issues)


@pytest.mark.parametrize("strength", ("NaN", "Infinity", "-Infinity"))
def test_catalog_rejects_non_finite_decimal_parameters(strength: str) -> None:
    application, segment_id = _application_with_admitted_segment()
    payload = _baseline_payload(segment_id)
    payload["transformations"] = [
        {
            "transformation_id": "trend-regime.v1",
            "parameters": {"direction": "bullish", "strength": strength},
        }
    ]
    draft = application.create_manual_recipe_draft(payload, author="researcher")

    validation = application.validate_recipe_draft(draft.draft_id)

    assert validation.is_valid is False
    assert {
        (issue.path, issue.rule)
        for issue in validation.issues
    } == {
        (
            "transformations.0.parameters.strength",
            "transformation.parameter-type",
        )
    }


def test_editing_an_approved_recipe_creates_a_new_immutable_version() -> None:
    application, segment_id = _application_with_admitted_segment()
    first_payload = _baseline_payload(segment_id)
    first_payload["transformations"] = [
        {
            "transformation_id": "volatility-scaling.v1",
            "parameters": {"multiplier": "1.2"},
        }
    ]
    first_draft = application.create_manual_recipe_draft(
        first_payload,
        author="researcher",
    )
    application.validate_recipe_draft(first_draft.draft_id)
    first_version = application.approve_recipe_draft(
        first_draft.draft_id,
        actor="owner",
    )

    with pytest.raises(TypeError, match="immutable"):
        first_version.recipe.name = "Mutated in place"  # type: ignore[misc]
    first_hash = first_version.recipe.content_hash
    with pytest.raises(TypeError):
        first_version.recipe.transformations[0].parameters["multiplier"] = (
            "1.8"
        )
    assert first_version.recipe.content_hash == first_hash
    assert first_version.content_hash == first_hash

    revised_payload = _baseline_payload(segment_id)
    revised_payload["name"] = "Hourly baseline"
    revised_payload["decision_cadence_minutes"] = 60
    second_draft = application.revise_recipe_version(
        first_version.version_id,
        revised_payload,
        author="researcher",
    )
    assert second_draft.recipe_id == first_version.recipe_id
    assert second_draft.based_on_version_id == first_version.version_id

    application.validate_recipe_draft(second_draft.draft_id)
    second_version = application.approve_recipe_draft(
        second_draft.draft_id,
        actor="owner",
    )

    assert second_version.version_number == 2
    assert second_version.content_hash != first_version.content_hash
    assert second_version.recipe.name == "Hourly baseline"
    assert first_version.recipe.name == "Baseline control"
    assert application.get_recipe_version(first_version.version_id) == first_version
    with pytest.raises(ValueError, match="approved.*immutable"):
        application.validate_recipe_draft(first_draft.draft_id)


def test_approved_recipe_version_survives_application_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "diagnostics.db"
    engine = create_engine(f"sqlite:///{database_path}", future=True)
    approved_at = datetime(2026, 7, 22, 5, 0, tzinfo=timezone.utc)
    source = _RecipeFixtureSource()
    first = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_clock=lambda: approved_at,
    )
    first.start()
    migration = first.initialize_persistence(engine)
    admission = first.admit_historical_segment(source.selection)
    assert admission.segment is not None
    draft = first.create_manual_recipe_draft(
        _baseline_payload(admission.segment.segment_id),
        author="researcher",
    )
    first.validate_recipe_draft(draft.draft_id)
    approved = first.approve_recipe_draft(draft.draft_id, actor="owner")

    restarted = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
    )
    restarted.start()
    restarted.initialize_persistence(engine)
    restored = restarted.get_recipe_version(approved.version_id)

    assert (
        migration.current_revision
        == "0020_scenario_lab_commands_and_materialization_handles"
    )
    assert restored.to_dict() == approved.to_dict()
    assert {
        "diagnostic_recipe_drafts",
        "diagnostic_recipe_validations",
        "diagnostic_recipe_versions",
    }.issubset(set(inspect(engine).get_table_names()))


@pytest.mark.parametrize("persistent", (False, True))
def test_same_draft_cannot_be_approved_twice(
    tmp_path: Path,
    persistent: bool,
) -> None:
    source = _RecipeFixtureSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_clock=lambda: datetime(2026, 7, 22, 5, 0, tzinfo=timezone.utc),
    )
    application.start()
    if persistent:
        engine = create_engine(
            f"sqlite:///{tmp_path / 'duplicate-approval.db'}",
            future=True,
        )
        application.initialize_persistence(engine)
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    draft = application.create_manual_recipe_draft(
        _baseline_payload(admission.segment.segment_id),
        author="researcher",
    )
    application.validate_recipe_draft(draft.draft_id)
    application.approve_recipe_draft(draft.draft_id, actor="owner")

    with pytest.raises(ValueError, match="already belongs to an approved immutable"):
        application.approve_recipe_draft(draft.draft_id, actor="owner")


def test_approved_version_keeps_its_validation_snapshot(tmp_path: Path) -> None:
    database_path = tmp_path / "diagnostics.db"
    engine = create_engine(f"sqlite:///{database_path}", future=True)
    source = _RecipeFixtureSource()
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=InMemoryMarketPathArtifactStore(),
        recipe_clock=lambda: datetime(2026, 7, 22, 5, 0, tzinfo=timezone.utc),
    )
    application.start()
    application.initialize_persistence(engine)
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    draft = application.create_manual_recipe_draft(
        _baseline_payload(admission.segment.segment_id),
        author="researcher",
    )
    application.validate_recipe_draft(draft.draft_id)
    approved = application.approve_recipe_draft(draft.draft_id, actor="owner")
    repository = SqlScenarioRecipeRepository(engine)

    with pytest.raises(ValueError, match="approved immutable"):
        repository.add_validation(
            replace(
                approved.validation_result,
                validated_at=(
                    approved.validation_result.validated_at + timedelta(seconds=1)
                ),
            )
        )

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_recipe_validations "
                "SET validated_at_utc = :changed_at WHERE draft_id = :draft_id"
            ),
            {
                "changed_at": "2030-01-01T00:00:00+00:00",
                "draft_id": draft.draft_id,
            },
        )

    restored = repository.get_version(approved.version_id)
    assert restored is not None
    assert restored.to_dict() == approved.to_dict()
    assert repository.list_all_versions() == (restored,)
