from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

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
                    {"transformation_id": "trend-regime.v1", "parameters": {}}
                ]
            },
            "transformation.not-registered",
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


def test_editing_an_approved_recipe_creates_a_new_immutable_version() -> None:
    application, segment_id = _application_with_admitted_segment()
    first_draft = application.create_manual_recipe_draft(
        _baseline_payload(segment_id),
        author="researcher",
    )
    application.validate_recipe_draft(first_draft.draft_id)
    first_version = application.approve_recipe_draft(
        first_draft.draft_id,
        actor="owner",
    )

    with pytest.raises(TypeError, match="immutable"):
        first_version.recipe.name = "Mutated in place"  # type: ignore[misc]

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

    assert migration.current_revision == "0003_scenario_recipe_lifecycle"
    assert restored.to_dict() == approved.to_dict()
    assert {
        "diagnostic_recipe_drafts",
        "diagnostic_recipe_validations",
        "diagnostic_recipe_versions",
    }.issubset(set(inspect(engine).get_table_names()))
