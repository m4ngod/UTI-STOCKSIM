from __future__ import annotations

import math
import random

from agents.retail_persona import (
    RetailMarketSnapshot,
    RetailPersona,
    RetailPersonaState,
    RetailPositionSnapshot,
    courage_effective,
    hold_probability,
    plan_retail_decision,
    sample_retail_persona,
    transform_loss_aversion,
    utility,
)


def test_sample_retail_persona_is_stable_for_same_agent_and_seed():
    left = sample_retail_persona("retail-001", "mean_revert", seed=42)
    right = sample_retail_persona("retail-001", "mean_revert", seed=42)

    assert left == right
    assert left.family == "mean_revert"


def test_loss_aversion_transform_and_utility_are_monotonic():
    low = transform_loss_aversion(0.1)
    high = transform_loss_aversion(0.9)

    assert high > low
    assert utility(-0.02, 0.9) < utility(-0.02, 0.1)
    assert math.isclose(utility(0.02, 0.9), 0.02)


def test_courage_effective_and_hold_probability_increase_with_courage():
    timid = courage_effective(0.2)
    brave = courage_effective(0.8)
    assert brave > timid

    timid_hold = hold_probability(
        courage_raw=0.2,
        courage_delta=0.0,
        q_thesis=0.7,
        i_invalid=0.1,
        m_adv=0.4,
        v_adv=0.3,
        tau_u=3.0,
        k_stop=0.35,
    )
    brave_hold = hold_probability(
        courage_raw=0.8,
        courage_delta=0.0,
        q_thesis=0.7,
        i_invalid=0.1,
        m_adv=0.4,
        v_adv=0.3,
        tau_u=3.0,
        k_stop=0.35,
    )
    assert brave_hold > timid_hold


def test_mean_revert_plan_uses_partial_expected_price_not_full_reversion():
    persona = RetailPersona(
        agent_id="mr-001",
        strategy="mean_revert",
        family="mean_revert",
        loss_aversion_raw=0.45,
        courage_raw=0.55,
        thesis_horizon_bars=10,
        entry_selectiveness=1.0,
        target_conservatism=0.5,
        execution_patience=0.4,
        position_budget=1.0,
        profit_realization_bias=1.0,
        crowd_susceptibility=0.2,
    )
    market = RetailMarketSnapshot(
        symbol="AAA",
        current_price=88.0,
        initial_price=100.0,
        tick_size=0.01,
        lot_size=1,
        best_bid=87.9,
        best_ask=88.1,
        recent_prices=[100.0, 99.4, 98.8, 97.9, 96.2, 94.1, 92.5, 90.4, 89.1, 88.0],
    )
    position = RetailPositionSnapshot(quantity=0, available_qty=0, avg_price=0.0, holding_time_s=0.0, unrealized_pnl_norm=0.0)
    plan = plan_retail_decision(persona, market, position, RetailPersonaState(), rng=random.Random(1))

    assert plan is not None
    assert plan.action == "buy"
    ma_10 = sum(market.recent_prices[-10:]) / 10.0
    assert market.current_price < plan.expected_price < ma_10


def test_slow_fundamental_allocator_builds_buy_plan_when_price_is_below_anchor():
    persona = RetailPersona(
        agent_id="fa-001",
        strategy="slow_fundamental_allocator",
        family="slow_fundamental_allocator",
        loss_aversion_raw=0.35,
        courage_raw=0.62,
        thesis_horizon_bars=18,
        entry_selectiveness=1.1,
        target_conservatism=0.72,
        execution_patience=0.8,
        position_budget=1.25,
        profit_realization_bias=0.9,
        crowd_susceptibility=0.12,
    )
    market = RetailMarketSnapshot(
        symbol="BBB",
        current_price=82.0,
        initial_price=100.0,
        tick_size=0.01,
        lot_size=1,
        best_bid=81.9,
        best_ask=82.1,
        recent_prices=[100.0, 99.8, 99.5, 99.1, 98.7, 98.2, 97.9, 97.3, 96.8, 96.2, 95.5, 94.9, 93.8, 92.6, 90.8, 88.9, 85.4, 82.0],
    )
    position = RetailPositionSnapshot(quantity=0, available_qty=0, avg_price=0.0, holding_time_s=0.0, unrealized_pnl_norm=0.0)
    plan = plan_retail_decision(persona, market, position, RetailPersonaState(), rng=random.Random(7))

    assert plan is not None
    assert plan.action == "buy"
    assert plan.expected_price > market.current_price
    assert plan.quantity_lots >= 1
