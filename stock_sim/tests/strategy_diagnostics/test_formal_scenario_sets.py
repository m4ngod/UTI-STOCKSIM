from dataclasses import replace

import pytest

from strategy_diagnostics import (
    CampaignTransformation,
    ISOLATED_SENSITIVITY_FAMILIES,
    compose_formal_scenario_set,
)
from tests.strategy_diagnostics.test_formal_diagnostic_campaigns import (
    _campaign_case,
    _transformation,
)


def _complete_cases():
    baseline = _campaign_case()
    isolated = tuple(
        _campaign_case(_transformation(family, level))
        for family in ISOLATED_SENSITIVITY_FAMILIES
        for level in (1, 2)
    )
    compound = _campaign_case(
        _transformation("trend-regime", 1),
        _transformation("volatility", 2),
    )
    return baseline, isolated, compound


def test_complete_backend_declared_sweep_is_formal_and_round_trips() -> None:
    baseline, isolated, compound = _complete_cases()

    scenario_set = compose_formal_scenario_set(
        baseline_case=baseline,
        isolated_cases=isolated,
        compound_cases=(compound,),
        authoritative_cases=(baseline, *isolated, compound),
    )
    restored = type(scenario_set).from_dict(scenario_set.to_dict())

    assert restored == scenario_set
    assert scenario_set.eligibility == "formal_campaign_eligible"
    assert scenario_set.formal_handoff_eligible
    assert scenario_set.case_ids == (
        baseline.case_id,
        *(item.case_id for item in isolated),
        compound.case_id,
    )
    assert len(scenario_set.comparison_relationships) == 13


def test_selective_sweep_is_typed_quick_experiment_only() -> None:
    baseline, isolated, compound = _complete_cases()

    scenario_set = compose_formal_scenario_set(
        baseline_case=baseline,
        isolated_cases=isolated[:-1],
        compound_cases=(compound,),
        authoritative_cases=(baseline, *isolated, compound),
    )

    assert scenario_set.eligibility == "quick_experiment_only"
    assert not scenario_set.formal_handoff_eligible
    assert scenario_set.missing_requirements == (
        "complete isolated sensitivity sweep",
    )


def test_composition_fails_closed_on_source_seed_or_policy_mismatch() -> None:
    baseline, isolated, compound = _complete_cases()

    for changed in (
        replace(isolated[0], source_snapshot_id="other-source"),
        replace(isolated[0], materialization_seed=999),
        replace(isolated[0], market_rule_profile_version="other-rule.v1"),
    ):
        with pytest.raises(ValueError, match="comparable pinned inputs"):
            compose_formal_scenario_set(
                baseline_case=baseline,
                isolated_cases=(changed, *isolated[1:]),
                compound_cases=(compound,),
                authoritative_cases=(baseline, *isolated, compound),
            )


def test_composition_rejects_transformed_baseline_and_single_family_compound() -> None:
    baseline, isolated, compound = _complete_cases()

    with pytest.raises(ValueError, match="untransformed"):
        compose_formal_scenario_set(
            baseline_case=isolated[0],
            isolated_cases=isolated[1:],
            compound_cases=(compound,),
            authoritative_cases=(baseline, *isolated, compound),
        )
    with pytest.raises(ValueError, match="multiple transformation families"):
        compose_formal_scenario_set(
            baseline_case=baseline,
            isolated_cases=isolated,
            compound_cases=(isolated[0],),
            authoritative_cases=(baseline, *isolated, compound),
        )


def test_authoritative_larger_sweep_cannot_be_selectively_promoted() -> None:
    baseline, isolated, compound = _complete_cases()
    additional = tuple(
        _campaign_case(_transformation(family, 3))
        for family in ISOLATED_SENSITIVITY_FAMILIES
    )

    scenario_set = compose_formal_scenario_set(
        baseline_case=baseline,
        isolated_cases=isolated,
        compound_cases=(compound,),
        authoritative_cases=(baseline, *isolated, *additional, compound),
    )

    assert scenario_set.eligibility == "quick_experiment_only"
    assert scenario_set.missing_requirements == (
        "complete isolated sensitivity sweep",
    )


def test_unknown_isolated_family_fails_closed() -> None:
    baseline, isolated, compound = _complete_cases()
    unknown = _campaign_case(
        CampaignTransformation(
            transformation_id="unregistered-transformation",
            transformation_family="unregistered-family",
            transformation_implementation_version="1.0",
            transformation_parameters=(("level", "1"),),
        )
    )

    with pytest.raises(ValueError, match="unsupported transformation family"):
        compose_formal_scenario_set(
            baseline_case=baseline,
            isolated_cases=(*isolated, unknown),
            compound_cases=(compound,),
            authoritative_cases=(
                baseline,
                *isolated,
                unknown,
                compound,
            ),
        )


def test_immutable_baseline_history_does_not_expand_declared_sweep() -> None:
    baseline, isolated, compound = _complete_cases()
    historical_baseline = replace(
        baseline,
        recipe_version_id="historical-baseline-recipe-version",
        recipe_content_hash="historical-baseline-recipe-hash",
    )

    scenario_set = compose_formal_scenario_set(
        baseline_case=baseline,
        isolated_cases=isolated,
        compound_cases=(compound,),
        authoritative_cases=(
            historical_baseline,
            baseline,
            *isolated,
            compound,
        ),
    )

    assert scenario_set.eligibility == "formal_campaign_eligible"
    assert scenario_set.missing_requirements == ()
