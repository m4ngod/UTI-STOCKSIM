from pathlib import Path

from app.services.evidence_core import build_world_spec_v1
from app.services.paired_sensitivity_runner import (
    REQUIRED_PAIRED_BASELINES,
    REQUIRED_PAIRED_METRICS,
    REQUIRED_PAIRED_SCENARIOS,
    PairedSensitivityRunner,
    apply_perturbation,
    metric_delta,
    scenario_world,
)


class FakePolicy:
    def __init__(self, name="frozen"):
        self.name = name


def _identity():
    return {
        "code_identity_hash": "c" * 64,
        "sim_version_identity": {"schema": "stock_sim.sim_version_identity.v1", "sim_version": "0.0.1"},
        "random_seed_ledger_hash": "s" * 64,
        "contract_versions": {"observation": "obs.v1", "action": "act.v1", "reward": "rew.v1"},
        "reward_hash": "r" * 64,
    }


def _base_world():
    return build_world_spec_v1(
        world_name="visible-base",
        split="visible",
        symbols=["001"],
        fee_model={"commission_bps": 2.5},
        impact_model={"params": {"temporary": 0.1}},
        fill_model={"latency_ticks": 0},
    )


def test_apply_perturbation_updates_fee_impact_and_latency_specs():
    base = _base_world()

    fee = apply_perturbation(base, {"kind": "fee", "factor": 2.0})
    impact = apply_perturbation(base, {"kind": "impact", "factor": 2.0})
    latency = apply_perturbation(base, {"kind": "latency", "ticks": 2})

    assert fee["fee_model"]["commission_bps"] == 5.0
    assert impact["impact_model"]["params"]["temporary"] == 0.2
    assert latency["fill_model"]["latency_ticks"] == 2
    assert fee["world_spec_hash"] != base["world_spec_hash"]


def test_scenario_world_builds_required_paired_scenarios():
    base = _base_world()

    scenarios = {name: scenario_world(base, name) for name in REQUIRED_PAIRED_SCENARIOS}

    assert scenarios["base"]["scenario_family"] == "base"
    assert scenarios["high_fee"]["fee_model"]["commission_bps"] == 5.0
    assert scenarios["high_impact"]["impact_model"]["params"]["temporary"] == 0.2
    assert scenarios["low_liquidity"]["market_rules"]["liquidity_multiplier"] == 0.5
    assert len({item["world_spec_hash"] for item in scenarios.values()}) == 4


def test_metric_delta_outputs_degradation_curve_values():
    delta = metric_delta({"score": 1.0, "max_drawdown": 0.1}, {"score": 0.7, "max_drawdown": 0.2})

    assert delta["base_score"] == 1.0
    assert delta["stressed_score"] == 0.7
    assert round(delta["score_delta"], 6) == -0.3
    assert round(delta["score_degradation"], 6) == 0.3
    assert round(delta["score_degradation_ratio"], 6) == 0.3
    assert round(delta["numeric_metric_delta"]["max_drawdown"], 6) == 0.1


def test_paired_sensitivity_runner_writes_passed_artifact_and_disables_learning(tmp_path):
    calls = []

    def evaluator(spec, policy, *, allow_learning):
        calls.append((spec.get("world_name"), allow_learning, spec))
        fee = spec.get("fee_model", {}).get("commission_bps", 2.5)
        impact = spec.get("impact_model", {}).get("params", {}).get("temporary", 0.1)
        latency = spec.get("fill_model", {}).get("latency_ticks", 0)
        score = 1.0 - (fee - 2.5) * 0.01 - (impact - 0.1) * 0.5 - latency * 0.02
        return {"metrics": {"score": score, "max_drawdown": 0.05}}

    artifact = PairedSensitivityRunner(artifact_root=tmp_path).run_paired_sensitivity(
        checkpoint={"checkpoint_hash": "k" * 64},
        base_world_spec=_base_world(),
        frozen_policy=FakePolicy(),
        perturbations=[
            {"kind": "fee", "factor": 2.0},
            {"kind": "impact", "factor": 2.0},
            {"kind": "latency", "ticks": 2},
        ],
        evaluate_policy_once=evaluator,
        **_identity(),
    )

    assert artifact["artifact_kind"] == "paired_sensitivity_artifact_v1"
    assert artifact["pass_fail"] is True
    assert artifact["metrics"]["present_perturbation_kinds"] == ["fee", "impact", "latency"]
    assert len(artifact["metrics"]["degradation_curve"]) == 3
    assert Path(artifact["artifact_path"]).exists()
    assert all(call[1] is False for call in calls)


def test_paired_sensitivity_runs_base_high_fee_high_impact_low_liquidity_with_baselines(tmp_path):
    calls = []
    baseline_policies = {
        "twap": FakePolicy("twap"),
        "vwap": FakePolicy("vwap"),
        "ac_lite": FakePolicy("ac_lite"),
    }

    def evaluator(spec, policy, *, allow_learning):
        calls.append((spec.get("scenario_family"), getattr(policy, "name", ""), allow_learning))
        scenario = spec.get("scenario_family")
        base_score = {
            "base": 1.0,
            "high_fee": 0.92,
            "high_impact": 0.88,
            "low_liquidity": 0.84,
        }.get(scenario, 0.5)
        policy_penalty = 0.05 if getattr(policy, "name", "") in baseline_policies else 0.0
        return {
            "metrics": {
                "score": base_score - policy_penalty,
                "gross_pnl": base_score * 100.0,
                "net_pnl": base_score * 95.0 - policy_penalty,
                "net_return": base_score - policy_penalty,
                "fee_drag": 0.02 if scenario == "high_fee" else 0.01,
                "impact_cost": 0.03 if scenario == "high_impact" else 0.01,
                "slippage": 0.02,
                "turnover": 0.5,
                "unfilled_ratio": 0.1 if scenario == "low_liquidity" else 0.02,
                "max_drawdown": 0.05,
                "inventory_risk": 0.03,
                "execution_shortfall": 0.04,
            }
        }

    artifact = PairedSensitivityRunner(artifact_root=tmp_path).run_paired_sensitivity(
        checkpoint={"checkpoint_hash": "k" * 64},
        base_world_spec=_base_world(),
        frozen_policy=FakePolicy("candidate"),
        perturbations=[],
        baseline_policies=baseline_policies,
        evaluate_policy_once=evaluator,
        **_identity(),
    )

    assert artifact["pass_gate"] is True
    assert artifact["metrics"]["schema"] == "paired_sensitivity_summary_v2"
    assert artifact["metrics"]["present_scenarios"] == REQUIRED_PAIRED_SCENARIOS
    assert artifact["metrics"]["present_baseline_names"] == REQUIRED_PAIRED_BASELINES
    assert artifact["metrics"]["required_metric_names"] == REQUIRED_PAIRED_METRICS
    assert artifact["metrics"]["missing_required_metrics"] == []
    assert set(artifact["metrics"]["scenario_world_hashes"]) == set(REQUIRED_PAIRED_SCENARIOS)
    assert set(artifact["metrics"]["candidate_metrics"]) == set(REQUIRED_PAIRED_SCENARIOS)
    assert set(artifact["metrics"]["baseline_metrics"]["base"]) == set(REQUIRED_PAIRED_BASELINES)
    assert artifact["metrics"]["scenario_deltas"]["high_fee"]["base_score"] == 1.0
    assert "high_fee:fee_drag_recorded" in artifact["metrics"]["explainability_flags"]
    assert len(artifact["metrics"]["scenario_results"]) == 4
    assert artifact["metrics"]["scenario_results"][0]["baseline_names"] == REQUIRED_PAIRED_BASELINES
    assert all(call[2] is False for call in calls)


def test_paired_sensitivity_runner_blocks_missing_required_perturbation_and_identity(tmp_path):
    def evaluator(spec, policy, *, allow_learning):
        return {"metrics": {"score": 1.0}}

    artifact = PairedSensitivityRunner(artifact_root=tmp_path).run_paired_sensitivity(
        checkpoint={},
        base_world_spec=_base_world(),
        frozen_policy=FakePolicy(),
        perturbations=[{"kind": "fee", "factor": 2.0}],
        evaluate_policy_once=evaluator,
        code_identity_hash=None,
        sim_version_identity=None,
        random_seed_ledger_hash=None,
        contract_versions=None,
        reward_hash=None,
    )

    assert artifact["pass_fail"] is False
    assert "missing_checkpoint_hash" in artifact["failure_reasons"]
    assert "missing_required_perturbation:impact" in artifact["failure_reasons"]
    assert "missing_required_perturbation:latency" in artifact["failure_reasons"]


def test_paired_sensitivity_blocks_missing_required_scenario_and_baseline(tmp_path):
    def evaluator(spec, policy, *, allow_learning):
        return {"metrics": {"score": 1.0, "net_return": 1.0}}

    artifact = PairedSensitivityRunner(artifact_root=tmp_path).run_paired_sensitivity(
        checkpoint={"checkpoint_hash": "k" * 64},
        base_world_spec=_base_world(),
        frozen_policy=FakePolicy("candidate"),
        perturbations=[],
        baseline_policies={"twap": FakePolicy("twap")},
        scenarios=["base", "high_fee"],
        evaluate_policy_once=evaluator,
        **_identity(),
    )

    assert artifact["pass_gate"] is False
    assert artifact["failure_type"] == "missing_metric"
    assert "missing_required_scenario:high_impact" in artifact["failure_reasons"]
    assert "missing_required_scenario:low_liquidity" in artifact["failure_reasons"]
    assert "missing_required_baseline:vwap" in artifact["failure_reasons"]
    assert "missing_required_baseline:ac_lite" in artifact["failure_reasons"]
