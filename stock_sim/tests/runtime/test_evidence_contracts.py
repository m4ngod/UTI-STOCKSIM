from app.services.evidence_artifact_writer import EvidenceArtifactWriter, _artifact_hash
from app.services.evidence_core import (
    build_random_seed_ledger,
    build_world_spec_v1,
    build_world_split_registry,
    derive_seed,
    random_seed_ledger_hash,
    world_spec_hash,
)
from app.services.exploit_test_runner import ExploitTestRunner
from app.services.hidden_world_runner import HiddenWorldRunner
from app.services.paired_sensitivity_runner import PairedSensitivityRunner
from app.services.strict_parent_gate import StrictParentGateV2


class FakePolicy:
    def __init__(self, name="frozen"):
        self.name = name


COMMON_ARTIFACT_KEYS = {
    "artifact_id",
    "artifact_kind",
    "artifact_schema_version",
    "created_at",
    "runner_name",
    "runner_version",
    "code_identity_hash",
    "sim_version_identity",
    "world_id",
    "world_hash",
    "reward_hash",
    "reward_not_applicable",
    "contract_versions",
    "random_seed_ledger_hash",
    "dependencies",
    "metrics",
    "pass_fail",
    "failure_reasons",
    "artifact_hash",
}


def _identity():
    return {
        "code_identity_hash": "c" * 64,
        "sim_version_identity": {"schema": "stock_sim.sim_version_identity.v1", "sim_version": "0.0.1"},
        "random_seed_ledger_hash": "s" * 64,
        "contract_versions": {"observation": "obs.v1", "action": "act.v1", "reward": "rew.v1"},
        "reward_hash": "r" * 64,
    }


def _hidden_registry():
    return build_world_split_registry(
        [
            build_world_spec_v1(world_name="visible-a", split="visible", symbols=["001"]),
            build_world_spec_v1(world_name="validation-a", split="validation", symbols=["002"]),
            build_world_spec_v1(world_name="hidden-a", split="hidden", symbols=["003"]),
        ]
    )


def _base_world():
    return build_world_spec_v1(
        world_name="visible-base",
        split="visible",
        symbols=["001"],
        fee_model={"commission_bps": 2.5},
        impact_model={"params": {"temporary": 0.1}},
        fill_model={"latency_ticks": 0},
    )


def _exploit_world():
    return build_world_spec_v1(
        world_name="exploit-no-signal",
        split="exploit",
        symbols=["001"],
        scenario_family="no_signal",
    )


def _safe_exploit_metrics():
    return {
        "score": 0.0,
        "sharpe": 0.0,
        "future_return_action_corr": 0.0,
        "pre_decision_equity_change_abs": 0.0,
        "illegal_action_positive_reward_count": 0,
        "rejected_action_positive_reward_count": 0,
        "fee_ledger_mismatch_abs": 0.0,
        "fee_ledger_consistent": True,
        "tiny_order_fill_reward": 0.0,
        "high_frequency_small_order_ratio": 0.1,
        "cancel_to_order_ratio": 0.2,
        "clock_boundary_return_share": 0.1,
        "boundary_profit_concentration": 0.1,
    }


def test_evidence_contract_hashes_and_seeds_are_reproducible():
    world = build_world_spec_v1(world_name="hash-world", split="hidden", symbols=["001", "002"])
    same_world = {
        **world,
        "universe": {"selection_rule": "explicit_symbols", "symbols": ["001", "002"]},
        "world_spec_hash": "wrong-self-hash",
    }
    changed_world = build_world_spec_v1(world_name="hash-world", split="exploit", symbols=["001", "002"])
    ledger = build_random_seed_ledger(20260504)

    assert world_spec_hash(same_world) == world["world_spec_hash"]
    assert changed_world["world_spec_hash"] != world["world_spec_hash"]
    assert ledger["seeds"]["hidden_world_selection"] == derive_seed(20260504, "hidden_world_selection")
    assert ledger["seeds"]["baselines"] != ledger["seeds"]["hidden_world_selection"]
    assert random_seed_ledger_hash({**ledger, "random_seed_ledger_hash": "bad"}) == ledger["random_seed_ledger_hash"]


def test_artifact_schema_contract_and_hash_are_stable(tmp_path):
    writer = EvidenceArtifactWriter(tmp_path)
    artifact = writer.write_hidden_eval_artifact(
        checkpoint_hash="k" * 64,
        world_id="hidden-registry",
        world_hash="w" * 64,
        results=[{"world_id": "hidden-a", "model": {"score": 1.0}}],
        summary={"schema": "hidden_eval_summary_v1", "pass": True},
        created_at="2026-05-05T00:00:00Z",
        **_identity(),
    )
    repeated = writer.write_hidden_eval_artifact(
        checkpoint_hash="k" * 64,
        world_id="hidden-registry",
        world_hash="w" * 64,
        results=[{"world_id": "hidden-a", "model": {"score": 1.0}}],
        summary={"schema": "hidden_eval_summary_v1", "pass": True},
        created_at="2026-05-05T00:00:00Z",
        **_identity(),
    )
    artifact_payload = {key: value for key, value in artifact.items() if key != "artifact_path"}
    self_hash_changed = {**artifact_payload, "artifact_hash": "wrong-self-hash"}

    assert COMMON_ARTIFACT_KEYS.issubset(artifact.keys())
    assert artifact["artifact_kind"] == "hidden_eval_artifact_v1"
    assert artifact["pass_fail"] is True
    assert repeated["artifact_id"] == artifact["artifact_id"]
    assert repeated["artifact_hash"] == artifact["artifact_hash"]
    assert _artifact_hash(self_hash_changed) == artifact["artifact_hash"]


def test_evidence_runners_enforce_no_learning_contract(tmp_path):
    calls = []

    def hidden_evaluator(spec, policy, *, allow_learning):
        calls.append(("hidden", spec["world_name"], policy.name, allow_learning))
        score = 1.0 if policy.name == "frozen" else 0.1
        return {"metrics": {"score": score, "max_drawdown": 0.01}}

    hidden_artifact = HiddenWorldRunner(artifact_root=tmp_path).run_hidden_eval(
        checkpoint={"checkpoint_hash": "k" * 64},
        world_registry=_hidden_registry(),
        frozen_policy=FakePolicy("frozen"),
        baseline_policies=[FakePolicy("twap")],
        evaluate_policy_once=hidden_evaluator,
        **_identity(),
    )

    def paired_evaluator(spec, policy, *, allow_learning):
        calls.append(("paired", spec.get("world_name"), policy.name, allow_learning))
        return {"metrics": {"score": 1.0, "max_drawdown": 0.01}}

    paired_artifact = PairedSensitivityRunner(artifact_root=tmp_path).run_paired_sensitivity(
        checkpoint={"checkpoint_hash": "k" * 64},
        base_world_spec=_base_world(),
        frozen_policy=FakePolicy("frozen"),
        perturbations=[{"kind": "fee"}, {"kind": "impact"}, {"kind": "latency"}],
        evaluate_policy_once=paired_evaluator,
        **_identity(),
    )

    def exploit_evaluator(spec, policy, *, allow_learning):
        calls.append(("exploit", spec["world_name"], policy.name, allow_learning))
        return {"metrics": _safe_exploit_metrics()}

    exploit_artifact = ExploitTestRunner(artifact_root=tmp_path).run_exploit_tests(
        checkpoint={"checkpoint_hash": "k" * 64},
        exploit_world_specs=[_exploit_world()],
        frozen_policy=FakePolicy("frozen"),
        evaluate_policy_once=exploit_evaluator,
        **_identity(),
    )

    assert hidden_artifact["pass_fail"] is True
    assert paired_artifact["pass_fail"] is True
    assert exploit_artifact["pass_fail"] is True
    assert calls
    assert all(call[3] is False for call in calls)


def test_bad_policy_evidence_is_rejected_by_exploit_runner_and_parent_gate(tmp_path):
    def bad_policy_evaluator(spec, policy, *, allow_learning):
        metrics = _safe_exploit_metrics()
        metrics.update(
            {
                "score": 0.25,
                "future_return_action_corr": 0.9,
                "pre_decision_equity_change_abs": 0.01,
                "illegal_action_positive_reward_count": 1,
                "fee_ledger_mismatch_abs": 0.03,
                "tiny_order_fill_reward": 0.01,
                "clock_boundary_return_share": 0.9,
            }
        )
        return {"metrics": metrics}

    exploit_artifact = ExploitTestRunner(artifact_root=tmp_path).run_exploit_tests(
        checkpoint={"checkpoint_hash": "k" * 64},
        exploit_world_specs=[_exploit_world()],
        frozen_policy=FakePolicy("future-leak-oracle"),
        evaluate_policy_once=bad_policy_evaluator,
        **_identity(),
    )

    candidate = {
        "candidate_id": "bad-policy",
        "checkpoint_hash": "k" * 64,
        "record_completeness": {"critical_pass": True},
        "lineage_evidence": {"pass_fail": True, "artifact_hash": "l" * 64},
        "baseline_artifact": {"pass_fail": True, "artifact_hash": "b" * 64},
        "world": {"calibration_artifact": {"pass_fail": True, "artifact_hash": "c" * 64}},
        "hidden_eval_artifact": {"pass_fail": True, "artifact_hash": "h" * 64},
        "exploit_test_artifact": exploit_artifact,
        "paired_sensitivity_artifact": {"pass_fail": True, "artifact_hash": "p" * 64},
        "hidden_rank_ok": True,
        "statistical_confidence_ok": True,
    }
    gate_artifact = StrictParentGateV2(artifact_root=tmp_path).evaluate(candidate=candidate, **_identity())

    assert exploit_artifact["pass_fail"] is False
    assert "no_signal_world:no_signal_positive_alpha" in exploit_artifact["failure_reasons"]
    assert gate_artifact["pass_fail"] is False
    assert gate_artifact["eligible_for_pbt_parent"] is False
    assert "exploit_test_artifact" in gate_artifact["failure_reasons"]
