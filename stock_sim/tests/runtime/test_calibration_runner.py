from pathlib import Path

from app.services.calibration_runner import CalibrationRunner, _aggregate_observed_metrics
from app.services.evidence_core import build_world_spec_v1


def _identity():
    return {
        "code_identity_hash": "c" * 64,
        "sim_version_identity": {"schema": "stock_sim.sim_version_identity.v1", "sim_version": "0.0.1"},
        "random_seed_ledger_hash": "s" * 64,
        "contract_versions": {"observation": "obs.v1", "action": "act.v1", "reward": "rew.v1"},
        "reward_hash": None,
    }


def _world():
    return build_world_spec_v1(
        world_name="validation-calibration",
        split="validation",
        symbols=["001"],
    )


def _facts():
    return {
        "orders": [
            {"agent_id": "A", "side": "buy", "order_type": "limit", "status": "filled", "filled": 10, "retail_family": "mean_revert", "lifespan_bars": 2},
            {"agent_id": "B", "side": "sell", "order_type": "limit", "status": "cancelled", "filled": 0, "retail_family": "momentum", "lifespan_bars": 3},
            {"agent_id": "C", "side": "buy", "order_type": "market", "status": "filled", "filled": 5, "retail_family": "liquidity_noise", "lifespan_bars": 1},
        ],
        "trades": [
            {"price": 10.0, "qty": 10},
            {"price": 10.1, "qty": 5},
        ],
        "snapshots_1s": [
            {"best_bid": 9.99, "best_ask": 10.01, "bid_depth": 100, "ask_depth": 120},
            {"best_bid": 10.00, "best_ask": 10.03, "bid_depth": 90, "ask_depth": 130},
        ],
        "bars": [
            {"close": 10.0},
            {"close": 10.1},
            {"close": 10.05},
            {"close": 10.2},
        ],
        "holdings": [{"holding_bars": 3}, {"holding_bars": 4}],
    }


def test_calibration_runner_writes_live_runtime_artifact_with_p0_metrics(tmp_path):
    run_calls = []

    def run_world_once(*, world_spec, seed, backend):
        run_calls.append((world_spec["world_name"], seed, backend))
        return {"run_id": f"run-{seed}"}

    def fetch_runtime_facts(run_id):
        assert run_id in {"run-101", "run-202"}
        return _facts()

    artifacts = CalibrationRunner(artifact_root=tmp_path).run_calibration(
        world_specs=[_world()],
        seeds=[101, 202],
        run_world_once=run_world_once,
        fetch_runtime_facts=fetch_runtime_facts,
        **_identity(),
    )

    artifact = artifacts[0]
    scorecard = artifact["scorecard"]
    assert artifact["artifact_kind"] == "calibration_artifact_v1"
    assert artifact["artifact_type"] == "calibration_artifact_v1"
    assert artifact["source"] == "live_postgresql_runtime"
    assert artifact["source_run_ids"] == ["run-101", "run-202"]
    assert len(artifact["seed_hashes"]) == 2
    assert artifact["world_spec_version"] == "world_spec_v1"
    assert artifact["pass_level"] == "engineering"
    assert artifact["pass_gate"] is True
    assert artifact["engineering_pass"] is True
    assert artifact["research_pass"] is False
    assert artifact["metric_coverage"]["spread_mean"] == "present"
    assert round(artifact["observed_values"]["spread"], 6) == 0.025
    assert artifact["distance_by_metric"]["spread"] == 0.0
    assert artifact["severity_by_metric"]["spread"] == "none"
    assert artifact["failed_metrics"] == []
    assert artifact["missing_metrics"] == []
    assert artifact["calibration_score"] == 0.0
    assert artifact["metrics"]["runtime_fact_counts"]["orders"] == 6
    assert artifact["metrics"]["runtime_fact_counts"]["bars_1m"] == 8
    assert "agent_bindings" in artifact["metrics"]["source_fact_tables"]
    assert scorecard["target_source"] == "engineering_default_v0"
    assert set(scorecard["metric_results"]) == {
        "spread",
        "depth",
        "turnover",
        "volatility",
        "return_autocorrelation",
        "fill_rate",
        "cancel_rate",
        "buy_sell_ratio",
        "holding_period",
        "retail_family_mix",
        "order_lifespan",
    }
    assert Path(artifact["artifact_path"]).exists()
    assert run_calls == [
        ("validation-calibration", 101, "postgresql_runtime"),
        ("validation-calibration", 202, "postgresql_runtime"),
    ]


def test_calibration_runner_missing_metric_fails_gate(tmp_path):
    def run_world_once(*, world_spec, seed, backend):
        return f"run-{seed}"

    def fetch_runtime_facts(run_id):
        facts = _facts()
        facts["orders"] = []
        facts["snapshots_1s"] = []
        return facts

    artifact = CalibrationRunner(artifact_root=tmp_path).run_calibration(
        world_specs=[_world()],
        seeds=[101],
        run_world_once=run_world_once,
        fetch_runtime_facts=fetch_runtime_facts,
        **_identity(),
    )[0]

    assert artifact["pass_gate"] is False
    assert artifact["failure_type"] == "missing_metric"
    assert "missing_metric:spread" in artifact["failure_reasons"]
    assert "spread" in artifact["blocking_metrics"]


def test_aggregate_observed_metrics_recomputes_buy_sell_ratio_from_counts():
    observed = _aggregate_observed_metrics(
        [
            {"buy_sell_ratio": 11.5, "buy_order_count": 46, "sell_order_count": 4},
            {"buy_sell_ratio": 9.4, "buy_order_count": 47, "sell_order_count": 5},
            {"buy_sell_ratio": 9.2, "buy_order_count": 46, "sell_order_count": 5},
        ]
    )

    assert round(observed["buy_sell_ratio"], 6) == round(139 / 14, 6)
