from pathlib import Path

from app.services.strict_parent_gate import StrictParentGateV2, collect_evidence_hashes, required_evidence_status


def _identity():
    return {
        "code_identity_hash": "c" * 64,
        "sim_version_identity": {"schema": "stock_sim.sim_version_identity.v1", "sim_version": "0.0.1"},
        "random_seed_ledger_hash": "s" * 64,
        "contract_versions": {"observation": "obs.v1", "action": "act.v1", "reward": "rew.v1"},
        "reward_hash": "r" * 64,
    }


def _artifact(name, passed=True):
    return {
        "artifact_kind": name,
        "source": "live_postgresql_runtime",
        "source_run_ids": [f"run-{name}"],
        "runner_version": "v0",
        "pass_gate": passed,
        "pass_fail": passed,
        "artifact_hash": name[:1] * 64,
    }


def _candidate(**overrides):
    candidate = {
        "id": "MODEL_A",
        "checkpoint_hash": "k" * 64,
        "training_world_hashes": ["t" * 64],
        "evaluation_world_hashes": ["v" * 64],
        "reward_contract_hash": "r" * 64,
        "action_contract_hash": "a" * 64,
        "observation_contract_hash": "o" * 64,
        "code_version": "code-v1",
        "record_completeness": {"critical_pass": True},
        "lineage_evidence": _artifact("lineage_evidence_v1"),
        "baseline_artifact": _artifact("baseline_artifact_v1"),
        "world": {"calibration_artifact": _artifact("calibration_artifact_v1")},
        "hidden_eval_artifact": _artifact("hidden_eval_artifact_v1"),
        "exploit_test_artifact": _artifact("exploit_test_artifact_v1"),
        "paired_sensitivity_artifact": _artifact("paired_sensitivity_artifact_v1"),
        "hidden_rank_ok": True,
        "statistical_confidence_ok": True,
    }
    candidate.update(overrides)
    return candidate


def test_required_evidence_status_reads_all_parent_gate_inputs():
    status = required_evidence_status(_candidate())

    assert status == {
        "experiment_record_completeness": True,
        "checkpoint_hash": True,
        "training_world_hashes": True,
        "evaluation_world_hashes": True,
        "reward_contract_hash": True,
        "action_contract_hash": True,
        "observation_contract_hash": True,
        "code_version_or_runner_version": True,
        "lineage_evidence": True,
        "baseline_artifact": True,
        "calibration_artifact": True,
        "hidden_eval_artifact": True,
        "exploit_test_artifact": True,
        "paired_sensitivity_artifact": True,
    }


def test_collect_evidence_hashes_keeps_required_artifact_hashes():
    hashes = collect_evidence_hashes(_candidate())

    assert hashes["checkpoint_hash"] == "k" * 64
    assert "training_world_hashes" in hashes
    assert "evaluation_world_hashes" in hashes
    assert hashes["reward_contract_hash"] == "r" * 64
    assert hashes["action_contract_hash"] == "a" * 64
    assert hashes["observation_contract_hash"] == "o" * 64
    assert hashes["code_version_or_runner_version"] == "code-v1"
    assert hashes["lineage_evidence"] == "l" * 64
    assert hashes["baseline_artifact"] == "b" * 64
    assert hashes["calibration_artifact"] == "c" * 64
    assert hashes["hidden_eval_artifact"] == "h" * 64
    assert hashes["exploit_test_artifact"] == "e" * 64
    assert hashes["paired_sensitivity_artifact"] == "p" * 64


def test_strict_parent_gate_writes_passed_artifact_with_three_separate_eligibilities(tmp_path):
    artifact = StrictParentGateV2(artifact_root=tmp_path).evaluate(
        candidate=_candidate(hidden_rank_ok=False, statistical_confidence_ok=False),
        **_identity(),
    )

    assert artifact["artifact_kind"] == "parent_gate_artifact_v2"
    assert artifact["artifact_schema_version"] == "2"
    assert artifact["source"] == "live_postgresql_runtime"
    assert artifact["pass_gate"] is True
    assert artifact["pass_fail"] is True
    assert artifact["eligible_for_pbt_parent"] is True
    assert artifact["eligible_for_checkpoint_promotion"] is False
    assert artifact["eligible_for_research_claim"] is False
    assert artifact["failure_reasons"] == []
    assert Path(artifact["artifact_path"]).exists()


def test_strict_parent_gate_blocks_missing_required_evidence_and_identity(tmp_path):
    candidate = _candidate(
        checkpoint_hash=None,
        training_world_hashes=[],
        record_completeness={"critical_pass": False},
        baseline_artifact=_artifact("baseline_artifact_v1", passed=False),
    )

    artifact = StrictParentGateV2(artifact_root=tmp_path).evaluate(
        candidate=candidate,
        code_identity_hash=None,
        sim_version_identity=None,
        random_seed_ledger_hash=None,
        contract_versions=None,
        reward_hash=None,
    )

    assert artifact["pass_fail"] is False
    assert artifact["eligible_for_pbt_parent"] is False
    assert "experiment_record_completeness" in artifact["failure_reasons"]
    assert "checkpoint_hash" in artifact["failure_reasons"]
    assert "training_world_hashes" in artifact["failure_reasons"]
    assert "baseline_artifact" in artifact["failure_reasons"]
    assert "missing_code_identity_hash" in artifact["failure_reasons"]
    assert "missing_random_seed_ledger_hash" in artifact["failure_reasons"]


def test_strict_parent_gate_blocks_manual_or_pass_fail_only_upstream(tmp_path):
    candidate = _candidate(
        baseline_artifact={
            "artifact_kind": "baseline_artifact_v1",
            "source": "manual",
            "pass_gate": True,
            "pass_fail": True,
            "artifact_hash": "b" * 64,
        },
        hidden_eval_artifact={
            "artifact_kind": "hidden_eval_artifact_v1",
            "source": "live_postgresql_runtime",
            "pass_fail": True,
            "artifact_hash": "h" * 64,
        },
    )

    status = required_evidence_status(candidate)

    assert status["baseline_artifact"] is False
    assert status["hidden_eval_artifact"] is False


def test_strict_parent_gate_blocks_missing_lineage_contract_hashes(tmp_path):
    candidate = _candidate(
        training_world_hashes=[],
        evaluation_world_hashes=[],
        reward_contract_hash=None,
        action_contract_hash=None,
        observation_contract_hash=None,
        code_version=None,
    )

    artifact = StrictParentGateV2(artifact_root=tmp_path).evaluate(
        candidate=candidate,
        **_identity(),
    )

    assert artifact["pass_fail"] is False
    assert "training_world_hashes" in artifact["failure_reasons"]
    assert "evaluation_world_hashes" in artifact["failure_reasons"]
    assert "reward_contract_hash" in artifact["failure_reasons"]
    assert "action_contract_hash" in artifact["failure_reasons"]
    assert "observation_contract_hash" in artifact["failure_reasons"]
    assert "code_version_or_runner_version" in artifact["failure_reasons"]
