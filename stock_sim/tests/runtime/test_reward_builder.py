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
