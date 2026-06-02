from stock_sim.rl.reward_builder import RewardBuilder


def test_reward_builder_emits_rew_v1_components():
    reward = RewardBuilder().build(
        previous_account={"equity": 100_000.0},
        current_account={
            "equity": 101_000.0,
            "gross_exposure": 50_000.0,
            "realized_pnl": 200.0,
            "unrealized_pnl": 800.0,
        },
        action={"action_type": "target_weight"},
        execution_result={
            "orders": [{"qty": 100, "price": 10.0}],
            "trades": [{"quantity": 100, "price": 10.0, "fee": 1.0}],
        },
        benchmark_return=0.002,
    )

    assert reward["reward_version"] == "rew.v1"
    assert reward["components"]["delta_equity"] == 0.01
    assert reward["components"]["relative_alpha"] == 0.008
    assert reward["components"]["fee_penalty"] < 0
    assert reward["components"]["turnover_penalty"] < 0
    assert reward["meta"]["action_type"] == "target_weight"


def test_reward_builder_lightly_penalizes_unfilled_order_intent():
    reward = RewardBuilder().build(
        previous_account={"equity": 100_000.0},
        current_account={"equity": 100_000.0},
        action={"action_type": "target_weight"},
        execution_result={
            "orders": [
                {
                    "qty": 5000,
                    "price": 10.0,
                    "result": {"ok": True, "status": "NEW", "filled": 0, "trades": []},
                }
            ],
            "trades": [],
        },
    )

    assert reward["components"]["filled_turnover"] == 0.0
    assert reward["components"]["open_order_pressure"] == 0.5
    assert reward["components"]["turnover_penalty"] == 0.0
    assert reward["components"]["open_order_pressure_penalty"] == -0.0005
    assert reward["step_reward"] == -0.0005


def test_reward_builder_uses_filled_notional_for_turnover_penalty():
    reward = RewardBuilder().build(
        previous_account={"equity": 100_000.0},
        current_account={"equity": 100_000.0},
        action={"action_type": "target_weight"},
        execution_result={
            "orders": [
                {
                    "qty": 5000,
                    "price": 10.0,
                    "result": {"ok": True, "status": "PARTIAL", "filled": 1000, "trades": []},
                }
            ],
            "trades": [],
        },
    )

    assert reward["components"]["filled_turnover"] == 0.1
    assert reward["components"]["open_order_pressure"] == 0.4
    assert reward["components"]["turnover_penalty"] == -0.002
    assert reward["components"]["open_order_pressure_penalty"] == -0.0004
