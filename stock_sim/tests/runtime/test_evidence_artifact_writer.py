import json
from pathlib import Path

from app.services.evidence_artifact_writer import EvidenceArtifactWriter


def test_calibration_artifact_writer_writes_passed_artifact(tmp_path):
    writer = EvidenceArtifactWriter(tmp_path)

    artifact = writer.write_calibration_artifact(
        world_id="world-visible-1",
        world_hash="w" * 64,
        target_profile_id="cn_a_share_microstructure_v0",
        metrics={"return_volatility": 0.02},
        scorecard={
            "target_profile_id": "cn_a_share_microstructure_v0",
            "score": 0.42,
            "parts": {"return_volatility": {"distance": 0.1, "weight": 1.0}},
            "pass": True,
            "critical_failures": [],
            "coverage_failures": [],
            "failure_reasons": [],
        },
        code_identity_hash="c" * 64,
        sim_version_identity={"schema": "stock_sim.sim_version_identity.v1", "sim_version": "0.0.1"},
        random_seed_ledger_hash="s" * 64,
        contract_versions={"observation": "obs.v1", "action": "act.v1", "reward": "rew.v1"},
        reward_hash=None,
        dependencies=[{"kind": "market_metrics_extractor_v0", "hash": "m" * 64}],
        created_at="2026-05-05T00:00:00Z",
    )

    path = Path(artifact["artifact_path"])
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert saved["artifact_kind"] == "calibration_artifact_v1"
    assert saved["artifact_type"] == "calibration_artifact_v1"
    assert saved["artifact_schema_version"] == "1"
    assert saved["world_spec_version"] == "world_spec_v1"
    assert saved["pass_level"] == "engineering"
    assert saved["artifact_id"].startswith("calibration-")
    assert saved["pass_fail"] is True
    assert saved["failure_reasons"] == []
    assert saved["reward_not_applicable"] is True
    assert len(saved["artifact_hash"]) == 64
    without_hash = {key: value for key, value in saved.items() if key != "artifact_hash"}
    assert "artifact_hash" not in without_hash


def test_calibration_artifact_writer_blocks_missing_required_identity(tmp_path):
    writer = EvidenceArtifactWriter(tmp_path)

    artifact = writer.write_calibration_artifact(
        world_id="world-visible-1",
        world_hash=None,
        target_profile_id="cn_a_share_microstructure_v0",
        metrics={},
        scorecard={"pass": True, "failure_reasons": []},
        code_identity_hash=None,
        sim_version_identity=None,
        random_seed_ledger_hash=None,
        contract_versions=None,
        created_at="2026-05-05T00:00:00Z",
    )

    assert artifact["pass_fail"] is False
    assert artifact["failure_reasons"] == [
        "missing_code_identity_hash",
        "missing_sim_version_identity",
        "missing_world_hash",
        "missing_random_seed_ledger_hash",
        "missing_contract_versions",
    ]
    assert Path(artifact["artifact_path"]).exists()


def test_calibration_artifact_hash_excludes_self_hash_and_is_stable(tmp_path):
    writer = EvidenceArtifactWriter(tmp_path)
    kwargs = dict(
        world_id="world-visible-1",
        world_hash="w" * 64,
        target_profile_id="cn_a_share_microstructure_v0",
        metrics={"b": 2, "a": 1},
        scorecard={"pass": False, "failure_reasons": ["critical_metric_out_of_band"]},
        code_identity_hash="c" * 64,
        sim_version_identity="0.0.1",
        random_seed_ledger_hash="s" * 64,
        contract_versions={"reward": "rew.v1", "action": "act.v1", "observation": "obs.v1"},
        created_at="2026-05-05T00:00:00Z",
    )

    first = writer.write_calibration_artifact(**kwargs)
    second = writer.write_calibration_artifact(**kwargs)

    assert first["artifact_id"] == second["artifact_id"]
    assert first["artifact_hash"] == second["artifact_hash"]
    assert first["pass_fail"] is False
    assert first["failure_reasons"] == ["critical_metric_out_of_band"]


def test_baseline_artifact_writer_writes_passed_artifact(tmp_path):
    writer = EvidenceArtifactWriter(tmp_path)
    baseline_results = [
        {"agent_id": "MODEL_HOLD", "model_id": "hold_model_v1", "result_role": "baseline", "baseline_kind": "no_trade_cash", "score": 0.0},
        {"agent_id": "MODEL_RANDOM", "model_id": "random_weight_v1", "result_role": "baseline", "baseline_kind": "random_constrained", "score": 0.1},
        {
            "agent_id": "MODEL_NAIVE",
            "model_id": "target_weight_naive_rebalance_v1",
            "result_role": "baseline",
            "baseline_kind": "target_weight_naive_rebalance",
            "score": 0.2,
        },
        {"agent_id": "MODEL_TWAP", "model_id": "twap_execution_v1", "result_role": "baseline", "baseline_kind": "twap", "score": 0.15},
        {"agent_id": "MODEL_VWAP", "model_id": "vwap_execution_v1", "result_role": "baseline", "baseline_kind": "vwap", "score": 0.16},
        {"agent_id": "MODEL_AC", "model_id": "ac_lite_execution_v1", "result_role": "baseline", "baseline_kind": "ac_lite", "score": 0.17},
    ]

    artifact = writer.write_baseline_artifact(
        world_id="world-visible-1",
        world_hash="w" * 64,
        task_name="alpha_to_execution.v1",
        baseline_suite={
            "status": "complete",
            "present_kinds": ["no_trade_cash", "random_constrained", "target_weight_naive_rebalance", "twap", "vwap", "ac_lite"],
            "missing_required": [],
        },
        baseline_results=baseline_results,
        benchmark_comparison={
            "status": "available",
            "baseline_kinds": ["no_trade_cash", "random_constrained", "target_weight_naive_rebalance", "twap", "vwap", "ac_lite"],
            "comparisons": {
                "MODEL_PPO": {
                    "no_trade_cash": {"excess_score": 0.3},
                    "random_constrained": {"excess_score": 0.2},
                    "target_weight_naive_rebalance": {"excess_score": 0.1},
                    "twap": {"excess_score": 0.15},
                    "vwap": {"excess_score": 0.14},
                    "ac_lite": {"excess_score": 0.13},
                }
            },
        },
        code_identity_hash="c" * 64,
        sim_version_identity={"schema": "stock_sim.sim_version_identity.v1", "sim_version": "0.0.1"},
        random_seed_ledger_hash="s" * 64,
        contract_versions={"observation": "obs.v1", "action": "act.v1", "reward": "rew.v1"},
        reward_hash="r" * 64,
        created_at="2026-05-05T00:00:00Z",
    )

    saved = json.loads(Path(artifact["artifact_path"]).read_text(encoding="utf-8"))

    assert saved["artifact_kind"] == "baseline_artifact_v1"
    assert saved["runner_name"] == "unified_baseline_runner"
    assert saved["pass_fail"] is True
    assert sorted(saved["present_baseline_kinds"]) == sorted([
        "no_trade_cash",
        "random_constrained",
        "target_weight_naive_rebalance",
        "twap",
        "vwap",
        "ac_lite",
        ])
    assert saved["missing_required_baseline_kinds"] == []
    assert saved["metrics"]["baseline_count"] == 6
    assert saved["metrics"]["candidate_baseline_pair_count"] == 6
    assert len(saved["artifact_hash"]) == 64


def test_baseline_artifact_writer_blocks_missing_required_baselines(tmp_path):
    writer = EvidenceArtifactWriter(tmp_path)

    artifact = writer.write_baseline_artifact(
        world_id="world-visible-1",
        world_hash="w" * 64,
        task_name="alpha_to_execution.v1",
        baseline_suite={"status": "incomplete", "present_kinds": ["no_trade_cash"], "missing_required": ["random_constrained"]},
        baseline_results=[
            {"agent_id": "MODEL_HOLD", "model_id": "hold_model_v1", "result_role": "baseline", "baseline_kind": "no_trade_cash"}
        ],
        benchmark_comparison={"status": "available", "comparisons": {}},
        code_identity_hash="c" * 64,
        sim_version_identity="0.0.1",
        random_seed_ledger_hash="s" * 64,
        contract_versions={"observation": "obs.v1"},
        reward_hash="r" * 64,
        created_at="2026-05-05T00:00:00Z",
    )

    assert artifact["pass_fail"] is False
    assert artifact["missing_required_baseline_kinds"] == [
        "random_constrained",
        "target_weight_naive_rebalance",
        "twap",
        "vwap",
        "ac_lite",
    ]
    assert artifact["failure_reasons"] == [
        "missing_required_baseline:random_constrained",
        "missing_required_baseline:target_weight_naive_rebalance",
        "missing_required_baseline:twap",
        "missing_required_baseline:vwap",
        "missing_required_baseline:ac_lite",
    ]
