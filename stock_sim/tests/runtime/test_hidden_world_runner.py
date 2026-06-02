from pathlib import Path

from app.services.evidence_core import build_world_spec_v1, build_world_split_registry
from app.services.hidden_world_runner import (
    REQUIRED_HIDDEN_BASELINES,
    HiddenWorldRunner,
)


class FakePolicy:
    def __init__(self, name):
        self.name = name


def _registry(*hidden_specs):
    return build_world_split_registry(
        [
            build_world_spec_v1(world_name="visible-a", split="visible", symbols=["001"]),
            build_world_spec_v1(world_name="validation-a", split="validation", symbols=["002"]),
            *hidden_specs,
        ]
    )


def _identity():
    return {
        "code_identity_hash": "c" * 64,
        "sim_version_identity": {"schema": "stock_sim.sim_version_identity.v1", "sim_version": "0.0.1"},
        "random_seed_ledger_hash": "s" * 64,
        "contract_versions": {"observation": "obs.v1", "action": "act.v1", "reward": "rew.v1"},
        "reward_hash": "r" * 64,
    }


def test_hidden_world_runner_evaluates_only_hidden_worlds_without_learning(tmp_path):
    calls = []
    hidden_a = build_world_spec_v1(world_name="hidden-a", split="hidden", symbols=["003"])
    hidden_b = build_world_spec_v1(world_name="hidden-b", split="hidden", symbols=["004"])

    def evaluator(spec, policy, *, allow_learning):
        calls.append((spec["world_name"], policy.name, allow_learning))
        if policy.name == "frozen":
            return {"metrics": {"score": 1.0, "max_drawdown": 0.05}}
        return {"metrics": {"score": 0.2, "max_drawdown": 0.03}}

    artifact = HiddenWorldRunner(artifact_root=tmp_path).run_hidden_eval(
        checkpoint={"checkpoint_hash": "k" * 64, "frozen": True},
        world_registry=_registry(hidden_a, hidden_b),
        frozen_policy=FakePolicy("frozen"),
        baseline_policies=[FakePolicy(name) for name in REQUIRED_HIDDEN_BASELINES],
        evaluate_policy_once=evaluator,
        risk_limits={"max_drawdown": 0.10},
        **_identity(),
    )

    assert artifact["artifact_kind"] == "hidden_eval_artifact_v1"
    assert artifact["pass_fail"] is True
    assert artifact["metrics"]["hidden_world_count"] == 2
    assert artifact["metrics"]["hidden_world_hashes"] == sorted([hidden_a["world_spec_hash"], hidden_b["world_spec_hash"]])
    assert artifact["metrics"]["candidate_training_world_hashes"] == []
    assert artifact["metrics"]["baseline_names"] == REQUIRED_HIDDEN_BASELINES
    assert artifact["metrics"]["split_contamination_check"]["status"] == "pass"
    assert "hidden-a" in artifact["metrics"]["metric_summary"]["candidate_metrics"]
    assert artifact["metrics"]["median_win_rate"] == 1.0
    assert artifact["metrics"]["strongest_win_rate"] == 1.0
    assert Path(artifact["artifact_path"]).exists()
    assert all(call[0] in {"hidden-a", "hidden-b"} for call in calls)
    assert all(call[2] is False for call in calls)


def test_hidden_world_runner_blocks_no_signal_positive_alpha(tmp_path):
    no_signal = build_world_spec_v1(
        world_name="hidden-no-signal",
        split="hidden",
        symbols=["003"],
        scenario_family="no_signal",
    )

    def evaluator(spec, policy, *, allow_learning):
        if policy.name == "frozen":
            return {"metrics": {"score": 0.1, "max_drawdown": 0.01}}
        return {"metrics": {"score": -0.1, "max_drawdown": 0.01}}

    artifact = HiddenWorldRunner(artifact_root=tmp_path).run_hidden_eval(
        checkpoint={"checkpoint_hash": "k" * 64, "frozen": True},
        world_registry=_registry(no_signal),
        frozen_policy=FakePolicy("frozen"),
        baseline_policies=[FakePolicy(name) for name in REQUIRED_HIDDEN_BASELINES],
        evaluate_policy_once=evaluator,
        no_signal_tolerance=0.0,
        **_identity(),
    )

    assert artifact["pass_fail"] is False
    assert "no_signal_hidden_positive_alpha" in artifact["failure_reasons"]
    assert artifact["metrics"]["no_signal_failures"] == ["hidden-no-signal"]


def test_hidden_world_runner_blocks_risk_limit_breach_and_missing_identity(tmp_path):
    hidden = build_world_spec_v1(world_name="hidden-risk", split="hidden", symbols=["003"])

    def evaluator(spec, policy, *, allow_learning):
        if policy.name == "frozen":
            return {"metrics": {"score": 1.0, "max_drawdown": 0.15}}
        return {"metrics": {"score": 0.2, "max_drawdown": 0.01}}

    artifact = HiddenWorldRunner(artifact_root=tmp_path).run_hidden_eval(
        checkpoint={},
        world_registry=_registry(hidden),
        frozen_policy=FakePolicy("frozen"),
        baseline_policies=[FakePolicy(name) for name in REQUIRED_HIDDEN_BASELINES],
        evaluate_policy_once=evaluator,
        risk_limits={"max_drawdown": 0.10},
        code_identity_hash=None,
        sim_version_identity=None,
        random_seed_ledger_hash=None,
        contract_versions=None,
        reward_hash=None,
    )

    assert artifact["pass_fail"] is False
    assert "hidden_risk_limit_breached" in artifact["failure_reasons"]
    assert "missing_checkpoint_hash" in artifact["failure_reasons"]
    assert artifact["metrics"]["risk_failures"] == [
        {"world_id": "hidden-risk", "metric": "max_drawdown", "value": 0.15, "limit": 0.1}
    ]


def test_hidden_eval_requires_frozen_candidate_and_hidden_split(tmp_path):
    hidden = build_world_spec_v1(world_name="hidden-contaminated", split="hidden", symbols=["003"])

    def evaluator(spec, policy, *, allow_learning):
        if policy.name == "frozen":
            return {"metrics": {"score": 1.0, "net_return": 0.2, "max_drawdown": 0.01}}
        return {"metrics": {"score": 0.2, "net_return": 0.02, "max_drawdown": 0.01}}

    artifact = HiddenWorldRunner(artifact_root=tmp_path).run_hidden_eval(
        checkpoint={
            "checkpoint_hash": "k" * 64,
            "training_world_hashes": [hidden["world_spec_hash"]],
        },
        world_registry=_registry(hidden),
        frozen_policy=FakePolicy("frozen"),
        baseline_policies=[FakePolicy(name) for name in REQUIRED_HIDDEN_BASELINES],
        evaluate_policy_once=evaluator,
        **_identity(),
    )

    assert artifact["pass_fail"] is False
    assert "candidate_checkpoint_not_frozen" in artifact["failure_reasons"]
    assert "hidden_split_contamination:hidden-contaminated" in artifact["failure_reasons"]
    assert artifact["failure_type"] == "split_contamination"
    assert artifact["metrics"]["split_contamination_worlds"] == ["hidden-contaminated"]
    assert artifact["metrics"]["split_contamination_check"]["status"] == "fail"
    assert artifact["metrics"]["candidate_training_world_hashes"] == [hidden["world_spec_hash"]]


def test_hidden_eval_blocks_missing_required_baseline_and_sample_size(tmp_path):
    hidden = build_world_spec_v1(world_name="hidden-small", split="hidden", symbols=["003"])

    def evaluator(spec, policy, *, allow_learning):
        if policy.name == "frozen":
            return {"metrics": {"score": 1.0, "net_return": 0.2}}
        return {"metrics": {"score": 0.2, "net_return": 0.02}}

    artifact = HiddenWorldRunner(artifact_root=tmp_path).run_hidden_eval(
        checkpoint={"checkpoint_hash": "k" * 64, "frozen": True},
        world_registry=_registry(hidden),
        frozen_policy=FakePolicy("frozen"),
        baseline_policies=[FakePolicy("twap")],
        evaluate_policy_once=evaluator,
        min_hidden_worlds=2,
        **_identity(),
    )

    assert artifact["pass_fail"] is False
    assert "hidden_sample_size_too_small" in artifact["failure_reasons"]
    assert "hidden_missing_required_baseline:vwap" in artifact["failure_reasons"]
    assert "hidden_missing_required_baseline:ac_lite" in artifact["failure_reasons"]
    assert artifact["metrics"]["missing_baseline_names"] == ["vwap", "ac_lite"]
