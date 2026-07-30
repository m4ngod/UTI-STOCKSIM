import json
from pathlib import Path
from types import SimpleNamespace
import uuid

from app.services.arena_experiment_runner import ArenaExperimentConfig, ArenaExperimentRunner
from app.services.arena_experiment_runner import _experiment_record_metadata, _fee_accounting_audit, _generation_summary, _model_specs_after_report, _series_aggregate
from app.services.training_arena_service import ArenaModelSpec
from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.training_episode_service import EpisodeAgentAccumulator, TrainingEpisodeService


class _FakeArenaService:
    def __init__(self, *, on_evaluate=None):
        self.calls = []
        self.on_evaluate = on_evaluate

    def create_arena(self, config):
        self.calls.append(("create_arena", config.arena_id))
        return {
            "arena_id": config.arena_id,
            "status": "READY",
            "model_agent_ids": [],
            "retail_agent_ids": [],
            "current_episode_id": None,
            "generation": config.generation,
            "symbols": list(config.symbols),
        }

    def start_arena(self, arena_id, *, episode_id=None):
        self.calls.append(("start_arena", arena_id, episode_id))
        return {
            "arena_id": arena_id,
            "status": "RUNNING",
            "model_agent_ids": ["MODEL_A", "MODEL_B"],
            "retail_agent_ids": [],
            "current_episode_id": episode_id,
            "generation": 2,
            "symbols": ["001"],
        }

    def stop_arena(self, arena_id):
        self.calls.append(("stop_arena", arena_id))
        return {"arena_id": arena_id, "status": "STOPPED"}

    def evaluate_arena(self, arena_id, *, complete_episode=True):
        self.calls.append(("evaluate_arena", arena_id, complete_episode))
        episode_id = self.calls[1][2]
        if self.on_evaluate is not None:
            self.on_evaluate(episode_id)
        return {
            "arena_id": arena_id,
            "status": "STOPPED",
            "current_episode_id": episode_id,
            "last_summary": {
                "episode": {"episode_id": episode_id, "status": "completed"},
                "results": [],
            },
        }


class _FakeClockService:
    def __init__(self):
        self.calls = []

    def set_speed(self, speed):
        self.calls.append(("set_speed", speed))

    def start(self, sim_day=None):
        self.calls.append(("start", sim_day))

    def stop(self):
        self.calls.append(("stop",))


class _FakeRuntimeGateway:
    def __init__(self):
        self.bootstraps = []
        self.orders = []

    def bootstrap_agent_account(self, **kwargs):
        self.bootstraps.append(dict(kwargs))

    def list_instruments(self, *, active_only=True):
        return [
            {"symbol": "001", "tick_size": 0.01, "initial_price": 10.0},
            {"symbol": "002", "tick_size": 0.05, "initial_price": 25.0},
        ]

    def get_recent_trades(self, symbol, *, limit=1):
        return []

    def submit_order(self, **kwargs):
        self.orders.append(dict(kwargs))
        return {
            "ok": True,
            "order_id": f"ORD-{len(self.orders)}",
            "status": "NEW",
            "filled": 0,
        }


class _FakeAgentService:
    def __init__(self):
        self.models = {}

    def get(self, agent_id):
        model_id = self.models.get(agent_id)
        if not model_id:
            return None
        return SimpleNamespace(agent_id=agent_id, type="Model", model_id=model_id, mode="online_train")


def test_fee_accounting_audit_compares_result_and_transition_fee_totals():
    results = [
        {"agent_id": "MODEL_A", "model_id": "ppo_lstm_v1", "fee_total": 0.2},
        {"agent_id": "MODEL_B", "model_id": "hold_model_v1", "fee_total": 0.0},
    ]
    transitions = [
        SimpleNamespace(agent_id="MODEL_A", execution_json=json.dumps({"fee_total": 0.1, "trades": [{"fee": 0.1}]})),
        SimpleNamespace(agent_id="MODEL_B", execution_json=json.dumps({"orders": [], "trades": []})),
    ]

    audit = _fee_accounting_audit(results, transitions)

    assert audit["status"] == "pass"
    assert audit["reason"] == "fee_accounting_passed"
    assert audit["fee_ledger_consistent"] is True
    assert audit["fee_ledger_mismatch_abs"] == 0.0


def test_fee_accounting_audit_fails_result_transition_fee_mismatch():
    results = [{"agent_id": "MODEL_A", "model_id": "ppo_lstm_v1", "fee_total": 0.3}]
    transitions = [
        SimpleNamespace(agent_id="MODEL_A", execution_json=json.dumps({"fee_total": 0.1, "trades": [{"fee": 0.1}]})),
    ]

    audit = _fee_accounting_audit(results, transitions)

    assert audit["status"] == "fail"
    assert audit["reason"] == "fee_accounting_violation"
    assert audit["fee_ledger_consistent"] is False
    assert audit["violations"] == ["fee_total_transition_sum_mismatch"]
    assert audit["samples"][0]["mismatch_abs"] > 0


def test_runner_orchestrates_arena_clock_and_writes_report(tmp_path):
    arena = _FakeArenaService()
    clock = _FakeClockService()
    runner = ArenaExperimentRunner(arena_service=arena, clock_service=clock, session_factory=None)

    report = runner.run(
        ArenaExperimentConfig(
            arena_id="arena-runner-basic",
            episode_id="episode-runner-basic",
            generation=2,
            symbols=["001"],
            retail_count=0,
            model_specs=[ArenaModelSpec(agent_id="MODEL_A", model_id="hold_model_v1")],
            duration_seconds=0,
            clock_speed=120.0,
            clock_start_day="7",
            run_pbt=False,
            report_dir=tmp_path,
        )
    )

    saved = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
    assert report["schema"] == "stock_sim.arena_experiment_report.v1"
    assert saved["schema"] == "stock_sim.arena_experiment_report.v1"
    assert report["episode_id"] == "episode-runner-basic"
    assert ("start_arena", "arena-runner-basic", "episode-runner-basic") in arena.calls
    assert arena.calls[-1] == ("evaluate_arena", "arena-runner-basic", True)
    assert clock.calls == [("set_speed", 120.0), ("start", "7"), ("stop",)]
    assert "episode-runner-basic" in report["report_path"]
    assert report["reward_hash"] == saved["reward_hash"]
    assert report["world_hash"] == saved["world_hash"]
    assert report["world_card"] == saved["world_card"]
    assert len(report["reward_hash"]) == 64
    assert len(report["world_hash"]) == 64
    metadata = report["experiment_record_metadata"]
    assert metadata["schema"] == "stock_sim.experiment_record_metadata.v1"
    assert metadata["reward_identity"]["reward_contract_version"] == "rew.v1"
    assert metadata["world_identity"]["symbols"] == ["001"]
    assert metadata["world_identity"]["clock_start_day"] == "7"
    assert metadata["world_card"]["schema"] == "stock_sim.arena_world_card.v1"
    assert metadata["world_card"]["world_hash"] == report["world_hash"]
    assert metadata["world_card"]["split"]["status"] == "training_only"
    assert metadata["world_card"]["calibration"]["status"] == "not_available"
    assert metadata["world_card"]["calibration"]["score"] is None
    assert metadata["world_card"]["calibration"]["score_status"] == "not_available"
    assert metadata["world_card"]["calibration"]["score_reason"] == "calibration_harness_not_implemented"
    assert "return_distribution_shape" in metadata["world_card"]["calibration"]["missing_metrics"]
    assert metadata["sim_version_identity"]["source"] == "stock_sim.__version__"
    assert metadata["sim_version"] == "0.0.1"
    assert report["sim_version"] == "0.0.1"
    assert report["random_seed"] is None
    assert report["record_kind"]["kind"] == "arena_experiment_report"
    assert report["record_kind"]["primary_stage"] == "training"
    assert metadata["random_seed_identity"]["status"] == "not_available"
    assert metadata["random_seed_identity"]["reason"] == "random_seed_not_wired_to_stochastic_services"
    assert metadata["missing_sources"][-1:] == ["random_seed"]
    if report["code_hash"]:
        assert len(report["code_hash"]) == 64
        assert "code_hash" not in metadata["missing_sources"]
    else:
        assert "code_hash" in metadata["missing_sources"]


def test_runner_writes_multi_generation_series_report(tmp_path):
    runner = ArenaExperimentRunner(
        arena_service=_FakeArenaService(),
        session_factory=None,
    )

    report = runner.run_generations(
        ArenaExperimentConfig(
            arena_id="arena-series-test",
            generation=2,
            symbols=["001"],
            retail_count=0,
            model_specs=[ArenaModelSpec(agent_id="MODEL_A", model_id="ppo_lstm_v1")],
            duration_seconds=0,
            run_clock=False,
            run_pbt=False,
            report_dir=tmp_path,
        ),
        generations=2,
    )

    saved = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
    assert report["schema"] == "stock_sim.arena_generation_series_report.v1"
    assert saved["generation_count"] == 2
    assert [item["generation"] for item in report["generations"]] == [2, 3]
    assert report["aggregate"]["transition_count"] == 0
    assert "arena-series-test-series" in report["report_path"]


def test_experiment_record_metadata_includes_git_code_identity_when_available():
    metadata = _experiment_record_metadata(
        ArenaExperimentConfig(
            arena_id="arena-code-hash",
            episode_id="episode-code-hash",
            generation=1,
            symbols=["001"],
            retail_count=0,
            model_specs=[ArenaModelSpec(agent_id="MODEL_A", model_id="hold_model_v1")],
        )
    )

    assert metadata["schema"] == "stock_sim.experiment_record_metadata.v1"
    assert metadata["code_identity"]["schema"] == "stock_sim.git_code_identity.v1"
    assert metadata["sim_version_identity"] == {
        "schema": "stock_sim.sim_version_identity.v1",
        "status": "available",
        "source": "stock_sim.__version__",
        "sim_version": "0.0.1",
    }
    assert metadata["random_seed_identity"] == {
        "schema": "stock_sim.random_seed_identity.v1",
        "status": "not_available",
        "reason": "random_seed_not_wired_to_stochastic_services",
        "required_before_present": [
            "arena_config_random_seed",
            "retail_persona_rng_seed",
            "model_training_rng_seed",
            "market_world_rng_seed",
        ],
    }
    assert metadata["record_kind"] == {
        "schema": "stock_sim.experiment_record_kind.v1",
        "kind": "arena_experiment_report",
        "primary_stage": "training",
        "task_name": "alpha_to_execution.v1",
        "embedded_sections": [
            "training_episode",
            "baseline_suite",
            "benchmark_comparison",
            "hidden_evaluation",
            "exploit_detector",
            "research_acceptance",
            "pbt",
        ],
        "separate_calibration_record_status": "not_available",
        "separate_calibration_record_reason": "calibration_harness_not_implemented",
        "separate_hidden_evaluation_record_status": "not_available",
        "separate_hidden_evaluation_record_reason": "hidden_world_runner_not_implemented",
        "separate_exploit_test_record_status": "not_available",
        "separate_exploit_test_record_reason": "separate_exploit_test_artifact_not_implemented",
    }
    assert metadata["missing_sources"][-1:] == ["random_seed"]
    if metadata["code_identity"]["status"] == "available":
        assert len(metadata["code_hash"]) == 64
        assert metadata["code_identity"]["method"] == "git_head_plus_status_sha256_v1"
        assert len(metadata["code_identity"]["head"]) == 40
        assert "code_hash" not in metadata["missing_sources"]
    else:
        assert metadata["code_hash"] is None
        assert "code_hash" in metadata["missing_sources"]


def test_generation_summary_includes_strict_parent_gate_diagnostics():
    summary = _generation_summary(
        {
            "config": {
                "generation": 3,
                "model_specs": [{"agent_id": "MODEL_PPO", "model_id": "ppo_lstm_v1"}],
                "reward_profile": "alpha_to_execution.v1",
                "task_name": "alpha_to_execution.v1",
                "symbols": ["001"],
                "checkpoint_dir": "tmp/checkpoints",
            },
            "arena_id": "arena-summary",
            "episode_id": "episode-summary",
            "report_path": "tmp/reports/arena-summary.json",
            "episode": {
                "results": [],
                "transition_count": 0,
                "baseline_suite": {
                    "task_name": "alpha_to_execution.v1",
                    "status": "incomplete",
                    "present_kinds": ["no_trade_cash"],
                    "missing_required": ["random_constrained", "target_weight_naive_rebalance"],
                    "required": [
                        {"kind": "no_trade_cash", "status": "present"},
                        {"kind": "random_constrained", "status": "missing"},
                        {"kind": "target_weight_naive_rebalance", "status": "missing"},
                    ],
                    "optional": [
                        {"kind": "twap", "status": "not_available", "reason": "schedule_execution_not_implemented"},
                        {"kind": "vwap", "status": "not_available", "reason": "schedule_execution_not_implemented"},
                    ],
                },
                "benchmark_comparison": {
                    "status": "available",
                    "baseline_kinds": ["no_trade_cash"],
                    "comparisons": {
                        "MODEL_PPO": {
                            "no_trade_cash": {
                                "excess_score": 0.1,
                                "excess_equity_return": 0.01,
                                "excess_reward_total": 0.1,
                                "excess_filled_notional": 100.0,
                            }
                        }
                    },
                },
                "hidden_evaluation": {
                    "status": "not_available",
                    "reason": "hidden_world_runner_not_implemented",
                    "required_inputs": ["unseen_seed", "unseen_retail_mix"],
                    "checks": [
                        {
                            "name": "frozen_policy_hidden_seed",
                            "status": "not_available",
                            "reason": "hidden_world_runner_not_implemented",
                        },
                        {
                            "name": "cross_world_transfer",
                            "status": "not_available",
                            "reason": "paired_world_runner_not_implemented",
                        },
                    ],
                },
                "exploit_detector": {
                    "status": "partial",
                    "implemented_checks": ["timestamp_audit"],
                    "placeholder_checks": ["no_signal_world"],
                    "checks": [
                        {"name": "no_signal_world", "status": "not_implemented", "reason": "check_not_implemented"},
                        {"name": "timestamp_audit", "status": "pass", "reason": "step_index_order_valid"},
                    ],
                },
                "runtime_observation_audit": {
                    "status": "pass",
                    "reason": "runtime_observation_contract_passed",
                    "scope": "model_transition_observation_json",
                    "transition_count": 3,
                    "checked_transition_count": 3,
                    "violations": [],
                },
                "timestamp_audit": {
                    "name": "timestamp_audit",
                    "status": "pass",
                    "reason": "transition_step_index_order_passed",
                    "scope": "model_transition_step_index",
                    "transition_count": 3,
                    "violations": [],
                },
                "mark_to_market_audit": {
                    "name": "mark_to_market_audit",
                    "status": "pass",
                    "reason": "episode_result_accounting_passed",
                    "scope": "model_episode_result_accounting",
                    "result_count": 2,
                    "checked_result_count": 2,
                    "violations": [],
                },
                "order_anomaly_audit": {
                    "name": "order_anomaly_audit",
                    "status": "fail",
                    "reason": "order_execution_health_failed",
                    "scope": "model_transition_execution_json",
                    "transition_count": 3,
                    "checked_transition_count": 3,
                    "violations": ["negative_order_qty"],
                },
                "fee_sensitivity": {
                    "name": "fee_sensitivity",
                    "status": "not_available",
                    "reason": "fee_variant_worlds_not_implemented",
                    "scope": "scenario_comparison",
                    "required_inputs": ["base_fee_model", "altered_fee_model"],
                },
                "impact_sensitivity": {
                    "name": "impact_sensitivity",
                    "status": "not_available",
                    "reason": "liquidity_depth_variant_worlds_not_implemented",
                    "scope": "scenario_comparison",
                    "required_inputs": ["base_liquidity_depth_or_impact_model"],
                },
                "research_acceptance": {
                    "status": "incomplete",
                    "is_research_accepted": False,
                    "strict_parent_eligibility_allowed": False,
                    "reasons": ["hidden evaluation not_available"],
                    "required_sections": {
                        "baseline_suite": "complete",
                        "hidden_evaluation": "not_available",
                        "exploit_detector": "partial",
                    },
                    "acceptance_lock": {
                        "status": "locked",
                        "blocking_sections": {
                            "hidden_evaluation": "not_available",
                            "exploit_detector": "partial",
                        },
                        "reason": "required_sections_not_complete",
                    },
                },
            },
            "pbt": {
                "strict_parent_gate": {
                    "enabled": True,
                    "passes": False,
                    "reason": "strict_parent_gate_blocked",
                    "blocking_reasons": [
                        "acceptance_lock_not_open",
                        "hidden_evaluation_not_complete",
                    ],
                    "acceptance_lock": {
                        "status": "locked",
                        "blocking_sections": {"hidden_evaluation": "not_available"},
                        "reason": "required_sections_not_complete",
                    },
                },
                "winners": [],
                "losers": [],
                "parent_eligible_agents": [],
                "lineage": [
                    {
                        "parent_agent_id": "MODEL_A",
                        "parent_model_id": "ppo_lstm_v1",
                        "child_agent_id": "MODEL_B",
                        "child_model_id": "ppo_lstm_v1_child",
                        "mutation": {"learning_rate": 0.0001},
                    }
                ],
            },
        }
    )

    record = summary["experiment_record_completeness"]
    strict_gate = summary["pbt"]["strict_parent_gate"]
    baseline_suite = summary["baseline_suite"]
    benchmark = summary["benchmark_comparison"]
    hidden = summary["hidden_evaluation"]
    exploit = summary["exploit_detector"]
    audits = summary["audit_summary"]
    acceptance = summary["research_acceptance"]
    assert baseline_suite["status"] == "incomplete"
    assert baseline_suite["present_kinds"] == ["no_trade_cash"]
    assert baseline_suite["missing_required"] == ["random_constrained", "target_weight_naive_rebalance"]
    assert baseline_suite["required"][1] == {"kind": "random_constrained", "status": "missing"}
    assert baseline_suite["optional"][0] == {
        "kind": "twap",
        "status": "not_available",
        "reason": "schedule_execution_not_implemented",
    }
    assert benchmark["status"] == "available"
    assert benchmark["baseline_kinds"] == ["no_trade_cash"]
    assert benchmark["candidate_count"] == 1
    assert benchmark["candidate_ids"] == ["MODEL_PPO"]
    assert benchmark["candidate_baseline_pair_count"] == 1
    assert hidden["status"] == "not_available"
    assert hidden["check_count"] == 2
    assert hidden["check_status_counts"] == {"not_available": 2}
    assert hidden["check_reason_counts"] == {
        "hidden_world_runner_not_implemented": 1,
        "paired_world_runner_not_implemented": 1,
    }
    assert exploit["status"] == "partial"
    assert exploit["implemented_checks"] == ["timestamp_audit"]
    assert exploit["placeholder_checks"] == ["no_signal_world"]
    assert exploit["check_status_counts"] == {
        "not_implemented": 1,
        "pass": 1,
    }
    assert audits["runtime_observation_audit"]["status"] == "pass"
    assert audits["runtime_observation_audit"]["checked_transition_count"] == 3
    assert audits["timestamp_audit"]["transition_count"] == 3
    assert audits["mark_to_market_audit"]["checked_result_count"] == 2
    assert audits["order_anomaly_audit"]["violation_count"] == 1
    assert audits["fee_sensitivity"]["required_input_count"] == 2
    assert audits["impact_sensitivity"]["status"] == "not_available"
    assert acceptance["status"] == "incomplete"
    assert acceptance["is_research_accepted"] is False
    assert acceptance["strict_parent_eligibility_allowed"] is False
    assert acceptance["required_sections"]["hidden_evaluation"] == "not_available"
    assert acceptance["acceptance_lock"]["status"] == "locked"
    assert acceptance["acceptance_lock"]["blocking_sections"] == {
        "hidden_evaluation": "not_available",
        "exploit_detector": "partial",
    }
    assert record["status"] == "incomplete"
    assert record["field_status"]["episode_id"] == "present"
    assert record["field_status"]["model_specs"] == "present"
    assert record["field_status"]["parent_lineage"] == "present"
    assert record["field_status"]["data_cutoff"] == "not_applicable"
    assert record["field_status"]["record_kind"] == "missing"
    assert record["field_status"]["record_kind_schema"] == "missing"
    assert record["field_status"]["record_kind_kind"] == "missing"
    assert record["field_status"]["record_primary_stage"] == "missing"
    assert record["field_status"]["record_task_name"] == "missing"
    assert record["field_status"]["record_embedded_sections"] == "missing"
    assert record["field_status"]["metadata_schema"] == "missing"
    assert record["field_status"]["hash_method"] == "missing"
    assert record["field_status"]["contract_versions"] == "missing"
    assert record["field_status"]["code_identity"] == "missing"
    assert record["field_status"]["sim_version_identity"] == "missing"
    assert record["field_status"]["random_seed_identity"] == "missing"
    assert record["field_status"]["reward_identity"] == "missing"
    assert record["field_status"]["world_identity"] == "missing"
    assert record["field_status"]["world_card"] == "missing"
    assert record["field_status"]["world_universe"] == "missing"
    assert record["field_status"]["world_split"] == "missing"
    assert record["field_status"]["world_retail_family_mix"] == "missing"
    assert record["field_status"]["world_liquidity_seed"] == "missing"
    assert record["field_status"]["world_clock"] == "missing"
    assert record["field_status"]["world_calibration"] == "missing"
    assert record["field_status"]["world_calibration_score"] == "missing"
    assert record["field_status"]["separate_calibration_record"] == "missing"
    assert record["field_status"]["separate_hidden_evaluation_record"] == "missing"
    assert record["field_status"]["separate_exploit_test_record"] == "missing"
    assert record["field_status"]["transition_evidence"] == "not_available"
    assert record["field_status"]["model_lineage_evidence"] == "present"
    assert record["field_status"]["missing_sources"] == "missing"
    assert record["field_status"]["not_applicable_sources"] == "missing"
    assert record["missing_fields"] == [
        "record_kind",
        "record_kind_schema",
        "record_kind_kind",
        "record_primary_stage",
        "record_task_name",
        "record_embedded_sections",
        "metadata_schema",
        "hash_method",
        "contract_versions",
        "code_identity",
        "sim_version_identity",
        "random_seed_identity",
        "code_hash",
        "sim_version",
        "reward_hash",
        "reward_identity",
        "world_hash",
        "world_identity",
        "world_card",
        "random_seed",
        "missing_sources",
        "not_applicable_sources",
        "world_universe",
        "world_split",
        "world_retail_family_mix",
        "world_liquidity_seed",
        "world_clock",
        "world_calibration",
        "world_calibration_score",
        "separate_calibration_record",
        "separate_hidden_evaluation_record",
        "separate_exploit_test_record",
    ]
    assert record["not_applicable_fields"] == ["data_cutoff"]
    assert record["not_available_fields"] == ["transition_evidence"]
    assert strict_gate["enabled"] is True
    assert strict_gate["passes"] is False
    assert strict_gate["reason"] == "strict_parent_gate_blocked"
    assert strict_gate["blocking_reasons"] == [
        "acceptance_lock_not_open",
        "hidden_evaluation_not_complete",
    ]
    assert strict_gate["acceptance_lock"]["status"] == "locked"
    assert strict_gate["acceptance_lock"]["blocking_sections"] == {
        "hidden_evaluation": "not_available",
    }


def test_generation_summary_includes_experiment_record_identity():
    summary = _generation_summary(
        {
            "config": {"generation": 1, "model_specs": []},
            "arena_id": "arena-identity",
            "episode_id": "episode-identity",
            "code_hash": "code-hash-1",
            "sim_version": "0.0.1",
            "reward_hash": "reward-hash-1",
            "world_hash": "world-hash-1",
            "random_seed": None,
            "experiment_record_metadata": {
                "schema": "stock_sim.experiment_record_metadata.v1",
                "code_hash": "code-hash-1",
                "code_identity": {"status": "available", "is_dirty": True},
                "sim_version": "0.0.1",
                "sim_version_identity": {"status": "available"},
                "reward_hash": "reward-hash-1",
                "world_hash": "world-hash-1",
                "random_seed": None,
                "random_seed_identity": {
                    "status": "not_available",
                    "reason": "random_seed_not_wired_to_stochastic_services",
                },
                "missing_sources": ["random_seed"],
                "not_applicable_sources": ["data_cutoff"],
            },
            "episode": {"results": [], "transition_count": 0},
            "pbt": {},
        }
    )

    identity = summary["experiment_record_identity"]
    assert identity["metadata_schema"] == "stock_sim.experiment_record_metadata.v1"
    assert identity["code_hash"] == "code-hash-1"
    assert identity["code_identity_status"] == "available"
    assert identity["code_dirty"] is True
    assert identity["sim_version"] == "0.0.1"
    assert identity["sim_version_status"] == "available"
    assert identity["reward_hash"] == "reward-hash-1"
    assert identity["world_hash"] == "world-hash-1"
    assert identity["random_seed"] is None
    assert identity["random_seed_status"] == "not_available"
    assert identity["random_seed_reason"] == "random_seed_not_wired_to_stochastic_services"
    assert identity["missing_sources"] == ["random_seed"]
    assert identity["not_applicable_sources"] == ["data_cutoff"]


def test_generation_summary_includes_world_card():
    summary = _generation_summary(
        {
            "config": {"generation": 1, "model_specs": []},
            "arena_id": "arena-world-card",
            "episode_id": "episode-world-card",
            "world_hash": "world-hash-1",
            "world_card": {
                "schema": "stock_sim.arena_world_card.v1",
                "world_hash": "world-hash-1",
                "split": {"status": "training_only", "reason": "world_pool_split_not_implemented"},
                "universe": {"symbols": ["001", "002"], "symbol_count": 2},
                "retail_profile": {
                    "retail_count": 25,
                    "retail_initial_cash": 100000.0,
                    "family_mix_status": "not_available",
                },
                "clock": {"clock_start_day": "7", "clock_speed": 120.0, "run_clock": True},
                "liquidity_seed": {
                    "seed_training_liquidity": True,
                    "liquidity_order_qty": 5000,
                    "liquidity_spread_ticks": 1,
                },
                "calibration": {
                    "status": "not_available",
                    "reason": "calibration_harness_not_implemented",
                    "score": None,
                    "score_status": "not_available",
                    "score_reason": "calibration_harness_not_implemented",
                    "missing_metrics": ["return_distribution_shape", "depth"],
                },
            },
            "episode": {"results": [], "transition_count": 0},
            "pbt": {},
        }
    )

    world_card = summary["world_card"]
    assert world_card["schema"] == "stock_sim.arena_world_card.v1"
    assert world_card["world_hash"] == "world-hash-1"
    assert world_card["split_status"] == "training_only"
    assert world_card["split_reason"] == "world_pool_split_not_implemented"
    assert world_card["symbols"] == ["001", "002"]
    assert world_card["symbol_count"] == 2
    assert world_card["retail_count"] == 25
    assert world_card["retail_family_mix_status"] == "not_available"
    assert world_card["clock_start_day"] == "7"
    assert world_card["clock_speed"] == 120.0
    assert world_card["seed_training_liquidity"] is True
    assert world_card["liquidity_order_qty"] == 5000
    assert world_card["liquidity_spread_ticks"] == 1
    assert world_card["calibration_status"] == "not_available"
    assert world_card["calibration_reason"] == "calibration_harness_not_implemented"
    assert world_card["calibration_score"] is None
    assert world_card["calibration_score_status"] == "not_available"
    assert world_card["calibration_score_reason"] == "calibration_harness_not_implemented"
    assert world_card["missing_calibration_metrics"] == ["return_distribution_shape", "depth"]


def test_generation_summary_includes_record_kind():
    summary = _generation_summary(
        {
            "config": {"generation": 1, "model_specs": []},
            "arena_id": "arena-record-kind",
            "episode_id": "episode-record-kind",
            "record_kind": {
                "schema": "stock_sim.experiment_record_kind.v1",
                "kind": "arena_experiment_report",
                "primary_stage": "training",
                "task_name": "alpha_to_execution.v1",
                "embedded_sections": ["training_episode", "hidden_evaluation", "exploit_detector"],
                "separate_calibration_record_status": "not_available",
                "separate_hidden_evaluation_record_status": "not_available",
                "separate_exploit_test_record_status": "not_available",
            },
            "episode": {"results": [], "transition_count": 0},
            "pbt": {},
        }
    )

    record_kind = summary["record_kind"]
    assert record_kind["schema"] == "stock_sim.experiment_record_kind.v1"
    assert record_kind["kind"] == "arena_experiment_report"
    assert record_kind["primary_stage"] == "training"
    assert record_kind["task_name"] == "alpha_to_execution.v1"
    assert record_kind["embedded_sections"] == ["training_episode", "hidden_evaluation", "exploit_detector"]
    assert record_kind["separate_calibration_record_status"] == "not_available"
    assert record_kind["separate_hidden_evaluation_record_status"] == "not_available"
    assert record_kind["separate_exploit_test_record_status"] == "not_available"


def test_generation_summary_includes_transition_evidence():
    summary = _generation_summary(
        {
            "config": {"generation": 1, "model_specs": []},
            "arena_id": "arena-transition-evidence",
            "episode_id": "episode-transition-evidence",
            "episode": {
                "results": [],
                "transition_count": 3,
                "runtime_observation_audit": {
                    "status": "fail",
                    "reason": "runtime_observation_contract_failed",
                    "transition_count": 3,
                    "checked_transition_count": 3,
                    "violations": ["missing_action"],
                    "samples": [{"agent_id": "MODEL_A", "step_index": 1}],
                },
                "timestamp_audit": {
                    "status": "pass",
                    "reason": "transition_step_index_order_passed",
                    "transition_count": 3,
                    "violations": [],
                    "samples": [],
                },
            },
            "pbt": {},
        }
    )

    evidence = summary["transition_evidence"]
    assert evidence["status"] == "has_summary"
    assert evidence["policy"] == "compact_summary_with_bounded_audit_samples"
    assert evidence["sample_limit_per_audit"] == 5
    assert evidence["transition_count"] == 3
    assert evidence["total_audit_sample_count"] == 1
    assert evidence["total_audit_violation_count"] == 1
    assert evidence["sections"]["runtime_observation_audit"]["status"] == "fail"
    assert evidence["sections"]["runtime_observation_audit"]["sample_count"] == 1
    assert evidence["sections"]["timestamp_audit"]["status"] == "pass"


def test_generation_summary_includes_model_lineage_evidence():
    summary = _generation_summary(
        {
            "config": {
                "generation": 2,
                "model_specs": [
                    {"agent_id": "MODEL_A", "model_id": "ppo_lstm_v1"},
                    {"agent_id": "MODEL_B", "model_id": "ppo_lstm_v1.gen1.MODEL_B"},
                ],
            },
            "arena_id": "arena-model-lineage",
            "episode_id": "episode-model-lineage",
            "episode": {"results": [], "transition_count": 0},
            "pbt": {
                "lineage": [
                    {
                        "parent_agent_id": "MODEL_A",
                        "parent_model_id": "ppo_lstm_v1",
                        "child_agent_id": "MODEL_B",
                        "child_model_id": "ppo_lstm_v1.gen1.MODEL_B",
                        "mutation": {"learning_rate": 0.0001, "entropy_coef": 0.01},
                    }
                ],
                "applied_agents": [
                    {"agent_id": "MODEL_B", "model_id": "ppo_lstm_v1.gen1.MODEL_B"}
                ],
            },
        }
    )

    evidence = summary["model_lineage_evidence"]
    assert evidence["status"] == "has_lineage"
    assert evidence["model_count"] == 2
    assert evidence["agent_count"] == 2
    assert evidence["model_ids"] == ["ppo_lstm_v1", "ppo_lstm_v1.gen1.MODEL_B"]
    assert evidence["agent_ids"] == ["MODEL_A", "MODEL_B"]
    assert evidence["lineage_count"] == 1
    assert evidence["applied_count"] == 1
    assert evidence["applied_model_ids"] == ["ppo_lstm_v1.gen1.MODEL_B"]
    assert evidence["parent_model_ids"] == ["ppo_lstm_v1"]
    assert evidence["child_model_ids"] == ["ppo_lstm_v1.gen1.MODEL_B"]
    assert evidence["mutation_keys"] == ["entropy_coef", "learning_rate"]
    assert evidence["lineage_sample_limit"] == 5
    assert evidence["lineage_samples"] == [
        {
            "parent_agent_id": "MODEL_A",
            "parent_model_id": "ppo_lstm_v1",
            "child_agent_id": "MODEL_B",
            "child_model_id": "ppo_lstm_v1.gen1.MODEL_B",
            "mutation_keys": ["entropy_coef", "learning_rate"],
        }
    ]


def test_series_aggregate_counts_strict_parent_gate_diagnostics():
    aggregate = _series_aggregate(
        [
            {
                "episode": {"transition_count": 0, "execution_health": {"totals": {}}},
                "pbt": {
                    "strict_parent_gate": {
                        "enabled": True,
                        "passes": False,
                        "reason": "strict_parent_gate_blocked",
                        "blocking_reasons": [
                            "acceptance_lock_not_open",
                            "hidden_evaluation_not_complete",
                        ],
                        "acceptance_lock": {
                            "status": "locked",
                            "blocking_sections": {"hidden_evaluation": "not_available"},
                            "reason": "required_sections_not_complete",
                        },
                    }
                },
            },
            {
                "episode": {"transition_count": 0, "execution_health": {"totals": {}}},
                "pbt": {
                    "strict_parent_gate": {
                        "enabled": True,
                        "passes": True,
                        "reason": "strict_parent_gate_passed",
                        "blocking_reasons": [],
                        "acceptance_lock": {
                            "status": "open",
                            "blocking_sections": {},
                            "reason": "required_sections_complete",
                        },
                    }
                },
            },
        ]
    )

    strict_gate = aggregate["strict_parent_gate"]
    assert strict_gate["observed_count"] == 2
    assert strict_gate["enabled_count"] == 2
    assert strict_gate["passed_count"] == 1
    assert strict_gate["blocked_count"] == 1
    assert strict_gate["blocking_reason_counts"] == {
        "acceptance_lock_not_open": 1,
        "hidden_evaluation_not_complete": 1,
    }
    assert strict_gate["lock_blocking_section_counts"] == {"hidden_evaluation": 1}


def test_series_aggregate_counts_experiment_record_completeness():
    aggregate = _series_aggregate(
        [
            {
                "config": {
                    "generation": 1,
                    "model_specs": [{"agent_id": "MODEL_A", "model_id": "ppo_lstm_v1"}],
                    "reward_profile": "alpha_to_execution.v1",
                    "task_name": "alpha_to_execution.v1",
                    "symbols": ["001"],
                    "checkpoint_dir": "tmp/checkpoints",
                    "world_hash": "world-hash-1",
                    "world_card": "world-card-present",
                    "random_seed": 42,
                },
                "arena_id": "arena-record-1",
                "episode_id": "episode-record-1",
                "report_path": "tmp/reports/arena-record-1.json",
                "code_hash": "code-hash-1",
                "sim_version": "sim.v1",
                "reward_hash": "reward-hash-1",
                "record_kind": {
                    "schema": "stock_sim.experiment_record_kind.v1",
                    "kind": "arena_experiment_report",
                    "primary_stage": "training",
                    "task_name": "alpha_to_execution.v1",
                    "embedded_sections": ["training_episode", "hidden_evaluation"],
                    "separate_calibration_record_status": "not_available",
                    "separate_hidden_evaluation_record_status": "not_available",
                    "separate_exploit_test_record_status": "not_available",
                },
                "experiment_record_metadata": {
                    "schema": "stock_sim.experiment_record_metadata.v1",
                    "hash_method": "sha256_json_canonical_v1",
                    "code_identity": {"status": "available", "is_dirty": False},
                    "sim_version_identity": {"status": "available"},
                    "random_seed_identity": {
                        "status": "not_available",
                        "reason": "random_seed_not_wired_to_stochastic_services",
                    },
                    "contract_versions": {
                        "observation": "obs.v1",
                        "action": "act.v1",
                        "reward": "rew.v1",
                    },
                    "reward_identity": {
                        "schema": "stock_sim.reward_identity.v1",
                        "reward_profile": "alpha_to_execution.v1",
                        "task_name": "alpha_to_execution.v1",
                    },
                    "world_identity": {
                        "schema": "stock_sim.arena_world_identity.v1",
                        "symbols": ["001"],
                    },
                    "missing_sources": ["random_seed"],
                    "not_applicable_sources": ["data_cutoff"],
                },
                "world_card": {
                    "schema": "stock_sim.arena_world_card.v1",
                    "world_hash": "world-hash-1",
                    "universe": {"symbols": ["001"], "symbol_count": 1},
                    "split": {"status": "training_only"},
                    "retail_profile": {"family_mix_status": "not_available"},
                    "liquidity_seed": {"seed_training_liquidity": True},
                    "clock": {"clock_start_day": "7", "clock_speed": 120.0, "run_clock": True},
                    "calibration": {
                        "status": "not_available",
                        "score": None,
                        "score_status": "not_available",
                    },
                },
                "episode": {"transition_count": 2, "execution_health": {"totals": {}}},
                "pbt": {},
            },
            {
                "config": {"generation": 2},
                "arena_id": "arena-record-2",
                "episode_id": "episode-record-2",
                "episode": {"transition_count": 0, "execution_health": {"totals": {}}},
                "pbt": {
                    "lineage": [
                        {
                            "parent_agent_id": "MODEL_A",
                            "parent_model_id": "ppo_lstm_v1",
                            "child_agent_id": "MODEL_B",
                            "child_model_id": "ppo_lstm_v1_child",
                            "mutation": {"learning_rate": 0.0001},
                        }
                    ]
                },
            },
        ]
    )

    record = aggregate["experiment_record_completeness"]
    assert record["observed_count"] == 2
    assert record["complete_count"] == 1
    assert record["incomplete_count"] == 1
    assert record["status_counts"] == {"complete": 1, "incomplete": 1}
    assert record["field_status_counts"]["code_hash:present"] == 1
    assert record["field_status_counts"]["code_hash:missing"] == 1
    assert record["field_status_counts"]["sim_version:present"] == 1
    assert record["field_status_counts"]["sim_version:missing"] == 1
    assert record["field_status_counts"]["parent_lineage:not_available"] == 1
    assert record["field_status_counts"]["parent_lineage:present"] == 1
    assert record["field_status_counts"]["data_cutoff:not_applicable"] == 2
    assert record["field_status_counts"]["record_kind:present"] == 1
    assert record["field_status_counts"]["record_kind:missing"] == 1
    assert record["field_status_counts"]["record_kind_schema:present"] == 1
    assert record["field_status_counts"]["record_kind_schema:missing"] == 1
    assert record["field_status_counts"]["record_kind_kind:present"] == 1
    assert record["field_status_counts"]["record_kind_kind:missing"] == 1
    assert record["field_status_counts"]["record_primary_stage:present"] == 1
    assert record["field_status_counts"]["record_primary_stage:missing"] == 1
    assert record["field_status_counts"]["record_task_name:present"] == 1
    assert record["field_status_counts"]["record_task_name:missing"] == 1
    assert record["field_status_counts"]["record_embedded_sections:present"] == 1
    assert record["field_status_counts"]["record_embedded_sections:missing"] == 1
    assert record["field_status_counts"]["metadata_schema:present"] == 1
    assert record["field_status_counts"]["metadata_schema:missing"] == 1
    assert record["field_status_counts"]["hash_method:present"] == 1
    assert record["field_status_counts"]["hash_method:missing"] == 1
    assert record["field_status_counts"]["contract_versions:present"] == 1
    assert record["field_status_counts"]["contract_versions:missing"] == 1
    assert record["field_status_counts"]["code_identity:present"] == 1
    assert record["field_status_counts"]["code_identity:missing"] == 1
    assert record["field_status_counts"]["sim_version_identity:present"] == 1
    assert record["field_status_counts"]["sim_version_identity:missing"] == 1
    assert record["field_status_counts"]["random_seed_identity:present"] == 1
    assert record["field_status_counts"]["random_seed_identity:missing"] == 1
    assert record["field_status_counts"]["reward_identity:present"] == 1
    assert record["field_status_counts"]["reward_identity:missing"] == 1
    assert record["field_status_counts"]["world_identity:present"] == 1
    assert record["field_status_counts"]["world_identity:missing"] == 1
    assert record["field_status_counts"]["world_card:present"] == 1
    assert record["field_status_counts"]["world_card:missing"] == 1
    assert record["field_status_counts"]["world_universe:present"] == 1
    assert record["field_status_counts"]["world_universe:missing"] == 1
    assert record["field_status_counts"]["world_split:not_available"] == 1
    assert record["field_status_counts"]["world_split:missing"] == 1
    assert record["field_status_counts"]["world_retail_family_mix:not_available"] == 1
    assert record["field_status_counts"]["world_retail_family_mix:missing"] == 1
    assert record["field_status_counts"]["world_liquidity_seed:present"] == 1
    assert record["field_status_counts"]["world_liquidity_seed:missing"] == 1
    assert record["field_status_counts"]["world_clock:present"] == 1
    assert record["field_status_counts"]["world_clock:missing"] == 1
    assert record["field_status_counts"]["world_calibration:not_available"] == 1
    assert record["field_status_counts"]["world_calibration:missing"] == 1
    assert record["field_status_counts"]["world_calibration_score:not_available"] == 1
    assert record["field_status_counts"]["world_calibration_score:missing"] == 1
    assert record["field_status_counts"]["separate_calibration_record:not_available"] == 1
    assert record["field_status_counts"]["separate_calibration_record:missing"] == 1
    assert record["field_status_counts"]["separate_hidden_evaluation_record:not_available"] == 1
    assert record["field_status_counts"]["separate_hidden_evaluation_record:missing"] == 1
    assert record["field_status_counts"]["separate_exploit_test_record:not_available"] == 1
    assert record["field_status_counts"]["separate_exploit_test_record:missing"] == 1
    assert record["field_status_counts"]["transition_evidence:present"] == 1
    assert record["field_status_counts"]["transition_evidence:not_available"] == 1
    assert record["field_status_counts"]["model_lineage_evidence:not_available"] == 1
    assert record["field_status_counts"]["model_lineage_evidence:present"] == 1
    assert record["field_status_counts"]["missing_sources:present"] == 1
    assert record["field_status_counts"]["missing_sources:missing"] == 1
    assert record["field_status_counts"]["not_applicable_sources:present"] == 1
    assert record["field_status_counts"]["not_applicable_sources:missing"] == 1
    assert record["present_field_counts"]["reward_hash"] == 1
    assert record["present_field_counts"]["reward_identity"] == 1
    assert record["present_field_counts"]["contract_versions"] == 1
    assert record["present_field_counts"]["hash_method"] == 1
    assert record["present_field_counts"]["metadata_schema"] == 1
    assert record["present_field_counts"]["code_identity"] == 1
    assert record["present_field_counts"]["sim_version_identity"] == 1
    assert record["present_field_counts"]["random_seed_identity"] == 1
    assert record["present_field_counts"]["record_kind"] == 1
    assert record["present_field_counts"]["record_kind_schema"] == 1
    assert record["present_field_counts"]["record_kind_kind"] == 1
    assert record["present_field_counts"]["record_primary_stage"] == 1
    assert record["present_field_counts"]["record_task_name"] == 1
    assert record["present_field_counts"]["record_embedded_sections"] == 1
    assert record["present_field_counts"]["world_identity"] == 1
    assert record["present_field_counts"]["world_card"] == 1
    assert record["present_field_counts"]["world_universe"] == 1
    assert record["present_field_counts"]["world_liquidity_seed"] == 1
    assert record["present_field_counts"]["world_clock"] == 1
    assert record["present_field_counts"]["missing_sources"] == 1
    assert record["present_field_counts"]["not_applicable_sources"] == 1
    assert record["missing_field_counts"]["reward_hash"] == 1
    assert record["missing_field_counts"]["reward_identity"] == 1
    assert record["missing_field_counts"]["contract_versions"] == 1
    assert record["missing_field_counts"]["hash_method"] == 1
    assert record["missing_field_counts"]["metadata_schema"] == 1
    assert record["missing_field_counts"]["code_identity"] == 1
    assert record["missing_field_counts"]["sim_version_identity"] == 1
    assert record["missing_field_counts"]["random_seed_identity"] == 1
    assert record["missing_field_counts"]["record_kind"] == 1
    assert record["missing_field_counts"]["record_kind_schema"] == 1
    assert record["missing_field_counts"]["record_kind_kind"] == 1
    assert record["missing_field_counts"]["record_primary_stage"] == 1
    assert record["missing_field_counts"]["record_task_name"] == 1
    assert record["missing_field_counts"]["record_embedded_sections"] == 1
    assert record["missing_field_counts"]["world_identity"] == 1
    assert record["missing_field_counts"]["world_card"] == 1
    assert record["missing_field_counts"]["world_universe"] == 1
    assert record["missing_field_counts"]["world_liquidity_seed"] == 1
    assert record["missing_field_counts"]["world_clock"] == 1
    assert record["missing_field_counts"]["missing_sources"] == 1
    assert record["missing_field_counts"]["not_applicable_sources"] == 1
    assert record["not_available_field_counts"]["parent_lineage"] == 1
    assert record["not_available_field_counts"]["world_split"] == 1
    assert record["not_available_field_counts"]["world_retail_family_mix"] == 1
    assert record["not_available_field_counts"]["world_calibration"] == 1
    assert record["not_available_field_counts"]["world_calibration_score"] == 1
    assert record["not_available_field_counts"]["separate_calibration_record"] == 1
    assert record["not_available_field_counts"]["separate_hidden_evaluation_record"] == 1
    assert record["not_available_field_counts"]["separate_exploit_test_record"] == 1
    assert record["not_available_field_counts"]["transition_evidence"] == 1
    assert record["not_available_field_counts"]["model_lineage_evidence"] == 1
    assert record["not_applicable_field_counts"]["data_cutoff"] == 2


def test_series_aggregate_counts_experiment_record_identity():
    aggregate = _series_aggregate(
        [
            {
                "config": {"generation": 1},
                "code_hash": "code-hash-1",
                "sim_version": "0.0.1",
                "reward_hash": "reward-hash-1",
                "world_hash": "world-hash-1",
                "experiment_record_metadata": {
                    "schema": "stock_sim.experiment_record_metadata.v1",
                    "code_identity": {"status": "available", "is_dirty": True},
                    "sim_version_identity": {"status": "available"},
                    "random_seed_identity": {
                        "status": "not_available",
                        "reason": "random_seed_not_wired_to_stochastic_services",
                    },
                    "missing_sources": ["random_seed"],
                    "not_applicable_sources": ["data_cutoff"],
                },
                "episode": {"transition_count": 0, "execution_health": {"totals": {}}},
                "pbt": {},
            },
            {
                "config": {"generation": 2},
                "experiment_record_metadata": {
                    "schema": "stock_sim.experiment_record_metadata.v1",
                    "code_identity": {"status": "unavailable"},
                    "sim_version_identity": {"status": "available"},
                    "random_seed_identity": {
                        "status": "not_available",
                        "reason": "random_seed_not_wired_to_stochastic_services",
                    },
                    "missing_sources": ["code_hash", "random_seed"],
                    "not_applicable_sources": ["data_cutoff"],
                },
                "episode": {"transition_count": 0, "execution_health": {"totals": {}}},
                "pbt": {},
            },
        ]
    )

    identity = aggregate["experiment_record_identity"]
    assert identity["observed_count"] == 2
    assert identity["dirty_code_count"] == 1
    assert identity["code_identity_status_counts"] == {"available": 1, "unavailable": 1}
    assert identity["sim_version_status_counts"] == {"available": 2}
    assert identity["random_seed_status_counts"] == {"not_available": 2}
    assert identity["missing_source_counts"] == {"random_seed": 2, "code_hash": 1}
    assert identity["not_applicable_source_counts"] == {"data_cutoff": 2}


def test_series_aggregate_counts_world_card():
    aggregate = _series_aggregate(
        [
            {
                "world_hash": "world-hash-1",
                "world_card": {
                    "schema": "stock_sim.arena_world_card.v1",
                    "world_hash": "world-hash-1",
                    "split": {"status": "training_only"},
                    "universe": {"symbols": ["001"], "symbol_count": 1},
                    "calibration": {
                        "status": "not_available",
                        "score": None,
                        "score_status": "not_available",
                        "missing_metrics": ["return_distribution_shape", "depth"],
                    },
                },
                "episode": {"transition_count": 0, "execution_health": {"totals": {}}},
                "pbt": {},
            },
            {
                "world_hash": "world-hash-2",
                "experiment_record_metadata": {
                    "world_card": {
                        "schema": "stock_sim.arena_world_card.v1",
                        "world_hash": "world-hash-2",
                        "split": {"status": "training_only"},
                        "universe": {"symbols": ["002"], "symbol_count": 1},
                        "calibration": {
                            "status": "not_available",
                            "score": None,
                            "score_status": "not_available",
                            "missing_metrics": ["return_distribution_shape"],
                        },
                    }
                },
                "episode": {"transition_count": 0, "execution_health": {"totals": {}}},
                "pbt": {},
            },
        ]
    )

    world_card = aggregate["world_card"]
    assert world_card["observed_count"] == 2
    assert world_card["unique_world_hash_count"] == 2
    assert world_card["split_status_counts"] == {"training_only": 2}
    assert world_card["calibration_status_counts"] == {"not_available": 2}
    assert world_card["calibration_score_status_counts"] == {"not_available": 2}
    assert world_card["missing_calibration_metric_counts"] == {
        "return_distribution_shape": 2,
        "depth": 1,
    }


def test_series_aggregate_counts_record_kind():
    aggregate = _series_aggregate(
        [
            {
                "record_kind": {
                    "kind": "arena_experiment_report",
                    "primary_stage": "training",
                    "embedded_sections": ["training_episode", "hidden_evaluation"],
                    "separate_calibration_record_status": "not_available",
                    "separate_hidden_evaluation_record_status": "not_available",
                    "separate_exploit_test_record_status": "not_available",
                },
                "episode": {"transition_count": 0, "execution_health": {"totals": {}}},
                "pbt": {},
            },
            {
                "experiment_record_metadata": {
                    "record_kind": {
                        "kind": "arena_experiment_report",
                        "primary_stage": "training",
                        "embedded_sections": ["training_episode", "exploit_detector"],
                        "separate_calibration_record_status": "not_available",
                        "separate_hidden_evaluation_record_status": "not_available",
                        "separate_exploit_test_record_status": "not_available",
                    }
                },
                "episode": {"transition_count": 0, "execution_health": {"totals": {}}},
                "pbt": {},
            },
        ]
    )

    record_kind = aggregate["record_kind"]
    assert record_kind["observed_count"] == 2
    assert record_kind["kind_counts"] == {"arena_experiment_report": 2}
    assert record_kind["primary_stage_counts"] == {"training": 2}
    assert record_kind["embedded_section_counts"] == {
        "training_episode": 2,
        "hidden_evaluation": 1,
        "exploit_detector": 1,
    }
    assert record_kind["separate_calibration_record_status_counts"] == {"not_available": 2}
    assert record_kind["separate_hidden_evaluation_record_status_counts"] == {"not_available": 2}
    assert record_kind["separate_exploit_test_record_status_counts"] == {"not_available": 2}


def test_series_aggregate_counts_transition_evidence():
    aggregate = _series_aggregate(
        [
            {
                "episode": {
                    "transition_count": 3,
                    "execution_health": {"totals": {}},
                    "runtime_observation_audit": {
                        "status": "fail",
                        "transition_count": 3,
                        "checked_transition_count": 3,
                        "violations": ["missing_action"],
                        "samples": [{"agent_id": "MODEL_A"}],
                    },
                    "timestamp_audit": {
                        "status": "pass",
                        "transition_count": 3,
                        "violations": [],
                        "samples": [],
                    },
                },
                "pbt": {},
            },
            {
                "episode": {
                    "transition_count": 0,
                    "execution_health": {"totals": {}},
                    "runtime_observation_audit": {
                        "status": "not_available",
                        "reason": "no_model_transitions",
                        "transition_count": 0,
                        "violations": [],
                        "samples": [],
                    },
                },
                "pbt": {},
            },
        ]
    )

    evidence = aggregate["transition_evidence"]
    assert evidence["observed_count"] == 2
    assert evidence["transition_count"] == 3
    assert evidence["audit_sample_count"] == 1
    assert evidence["audit_violation_count"] == 1
    assert evidence["status_counts"] == {"has_summary": 1, "no_transitions": 1}
    assert evidence["section_status_counts"]["runtime_observation_audit:fail"] == 1
    assert evidence["section_status_counts"]["runtime_observation_audit:not_available"] == 1
    assert evidence["section_status_counts"]["timestamp_audit:pass"] == 1
    assert evidence["policy"] == "compact_summary_with_bounded_audit_samples"
    assert evidence["sample_limit_per_audit"] == 5


def test_series_aggregate_counts_model_lineage_evidence():
    aggregate = _series_aggregate(
        [
            {
                "config": {
                    "model_specs": [
                        {"agent_id": "MODEL_A", "model_id": "ppo_lstm_v1"},
                        {"agent_id": "MODEL_B", "model_id": "ppo_lstm_v1.gen1.MODEL_B"},
                    ]
                },
                "episode": {"transition_count": 0, "execution_health": {"totals": {}}},
                "pbt": {
                    "lineage": [
                        {
                            "parent_agent_id": "MODEL_A",
                            "parent_model_id": "ppo_lstm_v1",
                            "child_agent_id": "MODEL_B",
                            "child_model_id": "ppo_lstm_v1.gen1.MODEL_B",
                            "mutation": {"learning_rate": 0.0001},
                        }
                    ],
                    "applied_agents": [
                        {"agent_id": "MODEL_B", "model_id": "ppo_lstm_v1.gen1.MODEL_B"}
                    ],
                },
            },
            {
                "config": {
                    "model_specs": [
                        {"agent_id": "MODEL_C", "model_id": "ppo_lstm_v1"},
                    ]
                },
                "episode": {"transition_count": 0, "execution_health": {"totals": {}}},
                "pbt": {},
            },
        ]
    )

    evidence = aggregate["model_lineage_evidence"]
    assert evidence["observed_count"] == 2
    assert evidence["lineage_count"] == 1
    assert evidence["applied_count"] == 1
    assert evidence["status_counts"] == {"has_lineage": 1, "no_lineage": 1}
    assert evidence["model_id_counts"] == {
        "ppo_lstm_v1": 2,
        "ppo_lstm_v1.gen1.MODEL_B": 1,
    }
    assert evidence["agent_id_counts"] == {"MODEL_A": 1, "MODEL_B": 1, "MODEL_C": 1}
    assert evidence["parent_model_id_counts"] == {"ppo_lstm_v1": 1}
    assert evidence["child_model_id_counts"] == {"ppo_lstm_v1.gen1.MODEL_B": 1}
    assert evidence["applied_model_id_counts"] == {"ppo_lstm_v1.gen1.MODEL_B": 1}
    assert evidence["mutation_key_counts"] == {"learning_rate": 1}


def test_series_aggregate_counts_research_acceptance_diagnostics():
    aggregate = _series_aggregate(
        [
            {
                "episode": {
                    "transition_count": 0,
                    "execution_health": {"totals": {}},
                    "research_acceptance": {
                        "status": "incomplete",
                        "is_research_accepted": False,
                        "strict_parent_eligibility_allowed": False,
                        "required_sections": {
                            "baseline_suite": "complete",
                            "hidden_evaluation": "not_available",
                            "exploit_detector": "partial",
                        },
                        "acceptance_lock": {
                            "status": "locked",
                            "blocking_sections": {
                                "hidden_evaluation": "not_available",
                                "exploit_detector": "partial",
                            },
                            "reason": "required_sections_not_complete",
                        },
                    },
                },
                "pbt": {},
            },
            {
                "episode": {
                    "transition_count": 0,
                    "execution_health": {"totals": {}},
                    "research_acceptance": {
                        "status": "incomplete",
                        "is_research_accepted": False,
                        "strict_parent_eligibility_allowed": False,
                        "required_sections": {
                            "baseline_suite": "complete",
                            "hidden_evaluation": "not_available",
                            "exploit_detector": "partial",
                        },
                        "acceptance_lock": {
                            "status": "locked",
                            "blocking_sections": {"hidden_evaluation": "not_available"},
                            "reason": "required_sections_not_complete",
                        },
                    },
                },
                "pbt": {},
            },
        ]
    )

    acceptance = aggregate["research_acceptance"]
    assert acceptance["observed_count"] == 2
    assert acceptance["accepted_count"] == 0
    assert acceptance["rejected_count"] == 2
    assert acceptance["strict_parent_allowed_count"] == 0
    assert acceptance["status_counts"] == {"incomplete": 2}
    assert acceptance["lock_status_counts"] == {"locked": 2}
    assert acceptance["lock_blocking_section_counts"] == {
        "hidden_evaluation": 2,
        "exploit_detector": 1,
    }
    assert acceptance["required_section_status_counts"] == {
        "baseline_suite:complete": 2,
        "hidden_evaluation:not_available": 2,
        "exploit_detector:partial": 2,
    }


def test_series_aggregate_counts_baseline_suite_diagnostics():
    aggregate = _series_aggregate(
        [
            {
                "episode": {
                    "transition_count": 0,
                    "execution_health": {"totals": {}},
                    "baseline_suite": {
                        "task_name": "alpha_to_execution.v1",
                        "status": "complete",
                        "present_kinds": [
                            "no_trade_cash",
                            "random_constrained",
                            "target_weight_naive_rebalance",
                        ],
                        "missing_required": [],
                        "required": [
                            {"kind": "no_trade_cash", "status": "present"},
                            {"kind": "random_constrained", "status": "present"},
                            {"kind": "target_weight_naive_rebalance", "status": "present"},
                        ],
                        "optional": [
                            {"kind": "twap", "status": "not_available"},
                            {"kind": "vwap", "status": "not_available"},
                        ],
                    },
                },
                "pbt": {},
            },
            {
                "episode": {
                    "transition_count": 0,
                    "execution_health": {"totals": {}},
                    "baseline_suite": {
                        "task_name": "alpha_to_execution.v1",
                        "status": "incomplete",
                        "present_kinds": ["no_trade_cash"],
                        "missing_required": [
                            "random_constrained",
                            "target_weight_naive_rebalance",
                        ],
                        "required": [
                            {"kind": "no_trade_cash", "status": "present"},
                            {"kind": "random_constrained", "status": "missing"},
                            {"kind": "target_weight_naive_rebalance", "status": "missing"},
                        ],
                        "optional": [
                            {"kind": "twap", "status": "not_available"},
                            {"kind": "vwap", "status": "not_available"},
                        ],
                    },
                },
                "pbt": {},
            },
        ]
    )

    baseline_suite = aggregate["baseline_suite"]
    assert baseline_suite["observed_count"] == 2
    assert baseline_suite["complete_count"] == 1
    assert baseline_suite["incomplete_count"] == 1
    assert baseline_suite["status_counts"] == {"complete": 1, "incomplete": 1}
    assert baseline_suite["present_kind_counts"] == {
        "no_trade_cash": 2,
        "random_constrained": 1,
        "target_weight_naive_rebalance": 1,
    }
    assert baseline_suite["missing_required_counts"] == {
        "random_constrained": 1,
        "target_weight_naive_rebalance": 1,
    }
    assert baseline_suite["required_status_counts"] == {
        "no_trade_cash:present": 2,
        "random_constrained:present": 1,
        "target_weight_naive_rebalance:present": 1,
        "random_constrained:missing": 1,
        "target_weight_naive_rebalance:missing": 1,
    }
    assert baseline_suite["optional_status_counts"] == {
        "twap:not_available": 2,
        "vwap:not_available": 2,
    }


def test_series_aggregate_counts_benchmark_comparison_diagnostics():
    aggregate = _series_aggregate(
        [
            {
                "episode": {
                    "transition_count": 0,
                    "execution_health": {"totals": {}},
                    "benchmark_comparison": {
                        "status": "available",
                        "baseline_kinds": [
                            "no_trade_cash",
                            "random_constrained",
                        ],
                        "comparisons": {
                            "MODEL_A": {
                                "no_trade_cash": {},
                                "random_constrained": {},
                            },
                            "MODEL_B": {
                                "no_trade_cash": {},
                            },
                        },
                    },
                },
                "pbt": {},
            },
            {
                "episode": {
                    "transition_count": 0,
                    "execution_health": {"totals": {}},
                    "benchmark_comparison": {
                        "status": "missing_baselines",
                        "baseline_kinds": [],
                        "comparisons": {},
                    },
                },
                "pbt": {},
            },
        ]
    )

    benchmark = aggregate["benchmark_comparison"]
    assert benchmark["observed_count"] == 2
    assert benchmark["candidate_count"] == 2
    assert benchmark["candidate_baseline_pair_count"] == 3
    assert benchmark["status_counts"] == {
        "available": 1,
        "missing_baselines": 1,
    }
    assert benchmark["baseline_kind_counts"] == {
        "no_trade_cash": 1,
        "random_constrained": 1,
    }


def test_series_aggregate_counts_hidden_and_exploit_diagnostics():
    aggregate = _series_aggregate(
        [
            {
                "episode": {
                    "transition_count": 0,
                    "execution_health": {"totals": {}},
                    "hidden_evaluation": {
                        "status": "not_available",
                        "reason": "hidden_world_runner_not_implemented",
                        "required_inputs": ["unseen_seed", "unseen_retail_mix"],
                        "checks": [
                            {
                                "name": "frozen_policy_hidden_seed",
                                "status": "not_available",
                                "reason": "hidden_world_runner_not_implemented",
                            },
                            {
                                "name": "cross_world_transfer",
                                "status": "not_available",
                                "reason": "paired_world_runner_not_implemented",
                            },
                        ],
                    },
                    "exploit_detector": {
                        "status": "partial",
                        "implemented_checks": ["timestamp_audit", "mark_to_market_audit"],
                        "placeholder_checks": ["no_signal_world"],
                        "checks": [
                            {"name": "no_signal_world", "status": "not_implemented", "reason": "check_not_implemented"},
                            {"name": "timestamp_audit", "status": "pass", "reason": "step_index_order_valid"},
                            {"name": "mark_to_market_audit", "status": "pass", "reason": "accounting_consistent"},
                        ],
                    },
                },
                "pbt": {},
            },
            {
                "episode": {
                    "transition_count": 0,
                    "execution_health": {"totals": {}},
                    "hidden_evaluation": {
                        "status": "not_available",
                        "reason": "hidden_world_runner_not_implemented",
                        "required_inputs": ["unseen_seed"],
                        "checks": [
                            {
                                "name": "frozen_policy_hidden_seed",
                                "status": "not_available",
                                "reason": "hidden_world_runner_not_implemented",
                            },
                        ],
                    },
                    "exploit_detector": {
                        "status": "failed",
                        "implemented_checks": ["order_anomaly_audit"],
                        "placeholder_checks": [],
                        "checks": [
                            {"name": "order_anomaly_audit", "status": "fail", "reason": "execution_payload_invalid"},
                        ],
                    },
                },
                "pbt": {},
            },
        ]
    )

    hidden = aggregate["hidden_evaluation"]
    exploit = aggregate["exploit_detector"]
    assert hidden["observed_count"] == 2
    assert hidden["required_input_count"] == 3
    assert hidden["check_count"] == 3
    assert hidden["status_counts"] == {"not_available": 2}
    assert hidden["check_status_counts"] == {"not_available": 3}
    assert hidden["check_reason_counts"] == {
        "hidden_world_runner_not_implemented": 2,
        "paired_world_runner_not_implemented": 1,
    }
    assert exploit["observed_count"] == 2
    assert exploit["check_count"] == 4
    assert exploit["status_counts"] == {"partial": 1, "failed": 1}
    assert exploit["check_status_counts"] == {
        "not_implemented": 1,
        "pass": 2,
        "fail": 1,
    }
    assert exploit["implemented_check_counts"] == {
        "timestamp_audit": 1,
        "mark_to_market_audit": 1,
        "order_anomaly_audit": 1,
    }
    assert exploit["placeholder_check_counts"] == {"no_signal_world": 1}


def test_series_aggregate_counts_episode_audit_summaries():
    aggregate = _series_aggregate(
        [
            {
                "episode": {
                    "transition_count": 0,
                    "execution_health": {"totals": {}},
                    "runtime_observation_audit": {
                        "status": "pass",
                        "reason": "runtime_observation_contract_passed",
                        "transition_count": 3,
                        "checked_transition_count": 3,
                        "violations": [],
                    },
                    "timestamp_audit": {
                        "name": "timestamp_audit",
                        "status": "pass",
                        "reason": "transition_step_index_order_passed",
                        "transition_count": 3,
                        "checked_transition_count": 0,
                        "violations": [],
                    },
                    "mark_to_market_audit": {
                        "name": "mark_to_market_audit",
                        "status": "pass",
                        "reason": "episode_result_accounting_passed",
                        "result_count": 2,
                        "checked_result_count": 2,
                        "violations": [],
                    },
                    "order_anomaly_audit": {
                        "name": "order_anomaly_audit",
                        "status": "fail",
                        "reason": "order_execution_health_failed",
                        "transition_count": 3,
                        "checked_transition_count": 3,
                        "violations": ["negative_order_qty"],
                    },
                    "fee_sensitivity": {
                        "name": "fee_sensitivity",
                        "status": "not_available",
                        "reason": "fee_variant_worlds_not_implemented",
                        "required_inputs": ["base_fee_model", "altered_fee_model"],
                    },
                    "impact_sensitivity": {
                        "name": "impact_sensitivity",
                        "status": "not_available",
                        "reason": "liquidity_depth_variant_worlds_not_implemented",
                        "required_inputs": ["base_liquidity_depth_or_impact_model"],
                    },
                },
                "pbt": {},
            },
            {
                "episode": {
                    "transition_count": 0,
                    "execution_health": {"totals": {}},
                    "runtime_observation_audit": {
                        "status": "not_available",
                        "reason": "no_model_transitions",
                        "transition_count": 0,
                        "checked_transition_count": 0,
                        "violations": [],
                    },
                    "timestamp_audit": {
                        "name": "timestamp_audit",
                        "status": "not_available",
                        "reason": "no_model_transitions",
                        "transition_count": 0,
                        "violations": [],
                    },
                },
                "pbt": {},
            },
        ]
    )

    audits = aggregate["audit_summary"]
    assert audits["observed_count"] == 8
    assert audits["transition_count"] == 9
    assert audits["checked_transition_count"] == 6
    assert audits["result_count"] == 2
    assert audits["checked_result_count"] == 2
    assert audits["violation_count"] == 1
    assert audits["required_input_count"] == 3
    assert audits["status_counts_by_audit"]["runtime_observation_audit"] == {
        "pass": 1,
        "not_available": 1,
    }
    assert audits["status_counts_by_audit"]["order_anomaly_audit"] == {"fail": 1}
    assert audits["reason_counts_by_audit"]["fee_sensitivity"] == {
        "fee_variant_worlds_not_implemented": 1,
    }


def test_runner_uses_inherited_model_id_for_next_generation():
    agent_service = _FakeAgentService()
    agent_service.models["MODEL_A"] = "ppo_lstm_v1.gen1.MODEL_A"
    runner = ArenaExperimentRunner(
        arena_service=_FakeArenaService(),
        agent_service=agent_service,
        session_factory=None,
    )

    specs = runner._model_specs_for_generation(
        [ArenaModelSpec(agent_id="MODEL_A", model_id="ppo_lstm_v1", mode="online_train")]
    )

    assert specs[0].model_id == "ppo_lstm_v1.gen1.MODEL_A"
    assert specs[0].mode == "online_train"


def test_runner_keeps_lineage_spec_when_agent_state_is_stale():
    agent_service = _FakeAgentService()
    agent_service.models["MODEL_A"] = "ppo_lstm_v1"
    runner = ArenaExperimentRunner(
        arena_service=_FakeArenaService(),
        agent_service=agent_service,
        session_factory=None,
    )

    specs = runner._model_specs_for_generation(
        [ArenaModelSpec(agent_id="MODEL_A", model_id="ppo_lstm_v1.gen1.MODEL_A", mode="online_train")]
    )

    assert specs[0].model_id == "ppo_lstm_v1.gen1.MODEL_A"


def test_model_specs_after_report_uses_lineage_child_model_id():
    specs = [
        ArenaModelSpec(agent_id="MODEL_A", model_id="ppo_lstm_v1", mode="online_train"),
        ArenaModelSpec(agent_id="MODEL_B", model_id="ppo_lstm_v1", mode="online_train"),
    ]
    report = {
        "pbt": {
            "applied_agents": [{"agent_id": "MODEL_B", "model_id": "ppo_lstm_v1"}],
            "lineage": [{"child_agent_id": "MODEL_B", "child_model_id": "ppo_lstm_v1.gen1.MODEL_B"}],
        }
    }

    updated = _model_specs_after_report(specs, report)

    assert updated[0].model_id == "ppo_lstm_v1"
    assert updated[1].model_id == "ppo_lstm_v1.gen1.MODEL_B"


def test_default_experiment_uses_multiple_trainable_ppo_agents():
    config = ArenaExperimentConfig()

    trainable = [spec for spec in config.model_specs if spec.model_id == "ppo_lstm_v1"]
    baselines = [spec.model_id for spec in config.model_specs if spec.model_id != "ppo_lstm_v1"]

    assert [spec.agent_id for spec in trainable] == [
        "MODEL_PPO_LSTM_A",
        "MODEL_PPO_LSTM_B",
        "MODEL_PPO_LSTM_C",
    ]
    assert all(spec.mode == "online_train" for spec in trainable)
    assert baselines == [
        "hold_model_v1",
        "random_weight_v1",
        "target_weight_naive_rebalance_v1",
        "twap_execution_v1",
        "vwap_execution_v1",
        "ac_lite_execution_v1",
    ]
    assert "target_weight_naive_rebalance_v1" in config.pbt_excluded_model_ids
    assert "twap_execution_v1" in config.pbt_excluded_model_ids
    assert "vwap_execution_v1" in config.pbt_excluded_model_ids
    assert "ac_lite_execution_v1" in config.pbt_excluded_model_ids


def test_runner_seeds_training_liquidity_before_starting_arena(tmp_path):
    arena = _FakeArenaService()
    gateway = _FakeRuntimeGateway()
    runner = ArenaExperimentRunner(
        arena_service=arena,
        runtime_gateway=gateway,
        session_factory=None,
    )

    report = runner.run(
        ArenaExperimentConfig(
            arena_id="arena-liquidity",
            episode_id="episode-liquidity",
            symbols=["001", "002"],
            retail_count=0,
            duration_seconds=0,
            run_clock=False,
            run_pbt=False,
            liquidity_order_qty=250,
            report_dir=tmp_path,
        )
    )

    assert gateway.bootstraps[0]["agent_type"] == "LIQUIDITY"
    assert len(gateway.orders) == 4
    assert [order["side"] for order in gateway.orders] == ["buy", "sell", "buy", "sell"]
    assert gateway.orders[0]["price"] == 9.99
    assert gateway.orders[1]["price"] == 10.01
    assert gateway.orders[2]["price"] == 24.95
    assert gateway.orders[3]["price"] == 25.05
    assert gateway.orders[0]["qty"] == 250
    assert report["states"]["liquidity_seeded"]["order_count"] == 4
    assert arena.calls[0][0] == "create_arena"
    assert arena.calls[1][0] == "start_arena"


def test_runner_can_trigger_pbt_from_episode_results(tmp_path):
    models_init.init_models()
    suffix = uuid.uuid4().hex[:8]
    arena_id = f"arena-runner-pbt-{suffix}"
    episode_id = f"episode-runner-pbt-{suffix}"

    def seed_results(evaluated_episode_id):
        session = SessionLocal()
        try:
            service = TrainingEpisodeService(session)
            service.create_episode(episode_id=evaluated_episode_id, arena_id=arena_id, generation=5)
            for agent_id, model_id, equity, reward in [
                ("MODEL_TOP", "random_weight_v1", 104_000.0, 0.04),
                ("MODEL_MID", "hold_model_v1", 101_000.0, 0.01),
                ("MODEL_LOW", "hold_model_v1", 97_000.0, -0.03),
            ]:
                acc = EpisodeAgentAccumulator(agent_id=agent_id, model_id=model_id)
                execution_result = (
                    {
                        "orders": [
                            {
                                "qty": 100,
                                "price": 10.0,
                                "result": {"ok": True, "status": "NEW", "filled": 0, "trades": []},
                            }
                        ],
                        "trades": [],
                    }
                    if agent_id == "MODEL_LOW"
                    else {}
                )
                acc.apply_step(
                    account={"equity": equity},
                    action={"action_type": "hold"},
                    execution_result=execution_result,
                    reward={"step_reward": reward},
                )
                service.upsert_result(acc, episode_id=evaluated_episode_id, generation=5)
            service.rank_episode(evaluated_episode_id)
            session.commit()
        finally:
            session.close()

    runner = ArenaExperimentRunner(
        arena_service=_FakeArenaService(on_evaluate=seed_results),
        session_factory=SessionLocal,
    )
    report = runner.run(
        ArenaExperimentConfig(
            arena_id=arena_id,
            episode_id=episode_id,
            generation=5,
            retail_count=0,
            duration_seconds=0,
            run_clock=False,
            run_pbt=True,
            pbt_excluded_model_ids=[],
            pbt_min_parent_trade_count=0,
            report_dir=tmp_path / "reports",
            checkpoint_dir=tmp_path / "checkpoints",
        )
    )

    assert report["episode"]["transition_count"] == 0
    assert report["episode"]["execution_health"]["totals"]["submitted_order_count"] == 1
    assert report["episode"]["execution_health"]["by_agent"]["MODEL_LOW"]["fill_ratio"] == 0.0
    assert [row["agent_id"] for row in report["episode"]["results"]] == ["MODEL_TOP", "MODEL_MID", "MODEL_LOW"]
    assert report["pbt"]["winners"] == ["MODEL_TOP"]
    assert report["pbt"]["losers"] == ["MODEL_LOW"]
    assert len(report["pbt"]["checkpoints"]) == 1
    assert len(report["pbt"]["lineage"]) == 1


def test_runner_report_labels_baselines_and_research_acceptance(tmp_path):
    models_init.init_models()
    suffix = uuid.uuid4().hex[:8]
    arena_id = f"arena-baseline-report-{suffix}"
    episode_id = f"episode-baseline-report-{suffix}"

    def seed_results(evaluated_episode_id):
        session = SessionLocal()
        try:
            service = TrainingEpisodeService(session)
            service.create_episode(episode_id=evaluated_episode_id, arena_id=arena_id, generation=1)
            for agent_id, model_id, equity, reward, filled_notional in [
                ("MODEL_PPO", "ppo_lstm_v1", 103_000.0, 0.03, 1200.0),
                ("MODEL_HOLD", "hold_model_v1", 100_000.0, 0.0, 0.0),
                ("MODEL_RANDOM", "random_weight_v1", 101_000.0, 0.01, 800.0),
                ("MODEL_NAIVE", "target_weight_naive_rebalance_v1", 102_000.0, 0.02, 1000.0),
            ]:
                acc = EpisodeAgentAccumulator(agent_id=agent_id, model_id=model_id)
                trade = {"price": 10.0, "qty": int(filled_notional / 10.0)}
                execution_result = {
                    "orders": [
                        {
                            "qty": int(filled_notional / 10.0) or 1,
                            "price": 10.0,
                            "result": {"ok": True, "status": "FILLED", "filled": int(filled_notional / 10.0), "trades": [trade] if filled_notional else []},
                        }
                    ],
                    "trades": [trade] if filled_notional else [],
                }
                acc.apply_step(
                    account={"equity": equity},
                    action={"action_type": "hold"},
                    execution_result=execution_result,
                    reward={"step_reward": reward},
                )
                service.upsert_result(acc, episode_id=evaluated_episode_id, generation=1)
            service.rank_episode(evaluated_episode_id)
            session.commit()
        finally:
            session.close()

    runner = ArenaExperimentRunner(
        arena_service=_FakeArenaService(on_evaluate=seed_results),
        session_factory=SessionLocal,
    )

    report = runner.run(
        ArenaExperimentConfig(
            arena_id=arena_id,
            episode_id=episode_id,
            generation=1,
            retail_count=0,
            duration_seconds=0,
            run_clock=False,
            run_pbt=False,
            report_dir=tmp_path,
        )
    )

    episode = report["episode"]
    by_model = {row["model_id"]: row for row in episode["results"]}
    assert by_model["hold_model_v1"]["result_role"] == "baseline"
    assert by_model["hold_model_v1"]["baseline_kind"] == "no_trade_cash"
    assert by_model["random_weight_v1"]["result_role"] == "baseline"
    assert by_model["random_weight_v1"]["baseline_kind"] == "random_constrained"
    assert by_model["target_weight_naive_rebalance_v1"]["result_role"] == "baseline"
    assert by_model["target_weight_naive_rebalance_v1"]["baseline_kind"] == "target_weight_naive_rebalance"
    assert by_model["ppo_lstm_v1"]["result_role"] == "candidate"
    assert by_model["ppo_lstm_v1"]["baseline_kind"] is None
    assert episode["baseline_suite"]["status"] == "complete"
    assert episode["baseline_suite"]["present_kinds"] == [
        "no_trade_cash",
        "random_constrained",
        "target_weight_naive_rebalance",
    ]
    assert episode["baseline_suite"]["missing_required"] == []
    assert episode["benchmark_comparison"]["baseline_kinds"] == [
        "no_trade_cash",
        "random_constrained",
        "target_weight_naive_rebalance",
    ]
    optional = {row["kind"]: row for row in episode["baseline_suite"]["optional"]}
    assert optional["twap"]["status"] == "not_available"
    assert optional["twap"]["reason"] == "schedule_execution_not_implemented"
    assert optional["vwap"]["status"] == "not_available"
    assert optional["vwap"]["reason"] == "schedule_execution_not_implemented"
    assert optional["twap"]["required_inputs"] == [
        "arrival_price",
        "target_quantity_or_notional",
        "horizon_steps_or_seconds",
        "realized_fill_price",
        "benchmark_fill_price",
    ]
    assert episode["benchmark_comparison"]["comparisons"]["MODEL_PPO"]["no_trade_cash"]["excess_score"] > 0
    assert episode["hidden_evaluation"]["status"] == "not_available"
    assert episode["hidden_evaluation"]["reason"] == "hidden_world_runner_not_implemented"
    hidden_checks = {row["name"]: row for row in episode["hidden_evaluation"]["checks"]}
    assert hidden_checks["frozen_policy_hidden_seed"]["status"] == "not_available"
    assert hidden_checks["frozen_policy_hidden_seed"]["reason"] == "hidden_world_runner_not_implemented"
    assert "frozen_policy_checkpoint" in hidden_checks["frozen_policy_hidden_seed"]["required_inputs"]
    assert hidden_checks["cross_world_transfer"]["status"] == "not_available"
    assert "target_world_hash" in hidden_checks["cross_world_transfer"]["required_inputs"]
    assert "unseen_seed" in episode["hidden_evaluation"]["required_inputs"]
    assert episode["exploit_detector"]["status"] == "partial"
    exploit_checks = {row["name"]: row for row in episode["exploit_detector"]["checks"]}
    assert exploit_checks["no_signal_world"]["status"] == "not_implemented"
    assert exploit_checks["no_signal_world"]["required_inputs"] == [
        "alpha_signal_source",
        "direction",
        "confidence",
        "target_weight_hint",
        "no_signal_tolerance",
        "fee_model",
        "world_seed_or_hash",
        "observation_audit_status",
    ]
    assert exploit_checks["timestamp_audit"]["status"] == "not_available"
    assert exploit_checks["timestamp_audit"]["reason"] == "no_model_transitions"
    assert exploit_checks["mark_to_market_audit"]["status"] == "pass"
    assert exploit_checks["mark_to_market_audit"]["result_count"] == 4
    assert episode["research_acceptance"]["status"] == "incomplete"
    assert episode["research_acceptance"]["required_sections"]["baseline_suite"] == "complete"
    assert episode["research_acceptance"]["required_sections"]["hidden_evaluation"] == "not_available"
    assert episode["research_acceptance"]["required_sections"]["exploit_detector"] == "partial"
    assert episode["research_acceptance"]["acceptance_lock"]["status"] == "locked"
    assert episode["research_acceptance"]["acceptance_lock"]["blocking_sections"] == {
        "hidden_evaluation": "not_available",
        "exploit_detector": "partial",
    }
    assert episode["research_acceptance"]["strict_parent_eligibility_allowed"] is False
    assert episode["research_acceptance"]["is_research_accepted"] is False


def test_runner_report_executes_explicit_no_signal_world_check(tmp_path):
    runner = ArenaExperimentRunner(
        arena_service=_FakeArenaService(),
        session_factory=None,
    )

    report = runner.run(
        ArenaExperimentConfig(
            arena_id="arena-no-signal-check",
            episode_id="episode-no-signal-check",
            symbols=["001"],
            retail_count=0,
            model_specs=[ArenaModelSpec(agent_id="MODEL_A", model_id="hold_model_v1")],
            duration_seconds=0,
            run_clock=False,
            run_pbt=False,
            seed_training_liquidity=False,
            no_signal_check={
                "alpha_signal_source": "no_signal",
                "direction": 0.0,
                "confidence": 0.0,
                "target_weight_hint": None,
                "no_signal_tolerance": 0.0001,
                "fee_model": "test_fee_model",
                "world_seed_or_hash": "seed-1",
                "observation_audit_status": "pass",
                "net_reward_after_fees": 0.0,
                "excess_score_vs_no_trade_cash": 0.0,
            },
            report_dir=tmp_path,
        )
    )

    exploit_detector = report["episode"]["exploit_detector"]
    checks = {row["name"]: row for row in exploit_detector["checks"]}

    assert exploit_detector["status"] == "partial"
    assert exploit_detector["implemented_checks"][0] == "no_signal_world"
    assert "no_signal_world" in exploit_detector["implemented_checks"]
    assert checks["no_signal_world"]["status"] == "pass"
    assert checks["no_signal_world"]["reason"] == "within_no_signal_tolerance"
    assert checks["no_signal_world"]["missing_required_inputs"] == []
    assert checks["no_signal_world"]["missing_metric_inputs"] == []
    assert checks["no_signal_world"]["failures"] == []
    assert checks["no_signal_world"]["metrics"]["net_reward_after_fees"] == 0.0
    assert checks["no_signal_world"]["observation_audit"]["status"] == "pass"
    assert checks["no_signal_world"]["observation_audit"]["scope"] == "payload_alpha_signal_contract"
    assert checks["fee_sensitivity"]["status"] in {"not_available", "not_implemented"}
    assert report["episode"]["research_acceptance"]["required_sections"]["exploit_detector"] == "partial"
    assert report["episode"]["research_acceptance"]["is_research_accepted"] is False


def test_runner_derives_no_signal_world_check_from_episode_results(tmp_path):
    models_init.init_models()
    suffix = uuid.uuid4().hex[:8]
    arena_id = f"arena-no-signal-derived-{suffix}"
    episode_id = f"episode-no-signal-derived-{suffix}"

    def seed_results(evaluated_episode_id):
        session = SessionLocal()
        try:
            service = TrainingEpisodeService(session)
            service.create_episode(episode_id=evaluated_episode_id, arena_id=arena_id, generation=1)
            service.record_transition(
                run_id="run-no-signal-derived",
                episode_id=evaluated_episode_id,
                arena_id=arena_id,
                agent_id="MODEL_PPO",
                model_id="ppo_lstm_v1",
                step_index=1,
                observation={
                    "contract_version": "obs.v1",
                    "market": {},
                    "account": {},
                    "context": {
                        "episode_id": evaluated_episode_id,
                        "agent_id": "MODEL_PPO",
                        "alpha_signal": {
                            "source": "no_signal",
                            "direction": 0.0,
                            "confidence": 0.0,
                            "target_weight_hint": None,
                        },
                    },
                    "features": {},
                },
                action={"action_type": "hold"},
                execution_result={"orders": [], "trades": []},
                reward={"step_reward": 0.0},
            )
            for agent_id, model_id in [
                ("MODEL_PPO", "ppo_lstm_v1"),
                ("MODEL_HOLD", "hold_model_v1"),
            ]:
                acc = EpisodeAgentAccumulator(agent_id=agent_id, model_id=model_id)
                acc.apply_step(
                    account={"equity": 100_000.0},
                    action={"action_type": "hold"},
                    execution_result={"orders": [], "trades": [], "fee_total": 0.0},
                    reward={"step_reward": 0.0},
                )
                service.upsert_result(acc, episode_id=evaluated_episode_id, generation=1)
            service.rank_episode(evaluated_episode_id)
            session.commit()
        finally:
            session.close()

    runner = ArenaExperimentRunner(
        arena_service=_FakeArenaService(on_evaluate=seed_results),
        session_factory=SessionLocal,
    )

    report = runner.run(
        ArenaExperimentConfig(
            arena_id=arena_id,
            episode_id=episode_id,
            task_name="alpha_to_execution.no_signal.v1",
            symbols=["001"],
            retail_count=0,
            duration_seconds=0,
            run_clock=False,
            run_pbt=False,
            seed_training_liquidity=False,
            no_signal_tolerance=0.0001,
            no_signal_fee_model="test_fee_model",
            report_dir=tmp_path,
        )
    )

    exploit_detector = report["episode"]["exploit_detector"]
    no_signal = {row["name"]: row for row in exploit_detector["checks"]}["no_signal_world"]
    timestamp = {row["name"]: row for row in exploit_detector["checks"]}["timestamp_audit"]

    assert exploit_detector["status"] == "partial"
    assert report["episode"]["runtime_observation_audit"]["status"] == "pass"
    assert report["episode"]["runtime_observation_audit"]["transition_count"] == 1
    assert report["episode"]["timestamp_audit"]["status"] == "pass"
    assert report["episode"]["timestamp_audit"]["transition_count"] == 1
    assert report["episode"]["mark_to_market_audit"]["status"] == "pass"
    assert report["episode"]["mark_to_market_audit"]["transition_reward_agent_count"] == 1
    assert timestamp["status"] == "pass"
    assert timestamp["scope"] == "model_transition_step_index"
    assert no_signal["status"] == "pass"
    assert no_signal["source"] == "episode_result_derived"
    assert no_signal["candidate_agent_id"] == "MODEL_PPO"
    assert no_signal["inputs"]["world_seed_or_hash"] == episode_id
    assert no_signal["inputs"]["observation_audit_status"] == "pass"
    assert no_signal["observation_audit"] == {
        "status": "pass",
        "reason": "no_signal_contract_passed",
        "scope": "payload_alpha_signal_contract",
        "missing_fields": [],
        "violations": [],
    }
    assert no_signal["runtime_observation_audit"]["status"] == "pass"
    assert no_signal["metrics"]["net_reward_after_fees"] == 0.0
    assert no_signal["metrics"]["excess_score_vs_no_trade_cash"] == 0.0


def test_runner_report_marks_bad_no_signal_world_check_failed(tmp_path):
    runner = ArenaExperimentRunner(
        arena_service=_FakeArenaService(),
        session_factory=None,
    )

    report = runner.run(
        ArenaExperimentConfig(
            arena_id="arena-no-signal-fail",
            episode_id="episode-no-signal-fail",
            symbols=["001"],
            retail_count=0,
            model_specs=[ArenaModelSpec(agent_id="MODEL_A", model_id="hold_model_v1")],
            duration_seconds=0,
            run_clock=False,
            run_pbt=False,
            seed_training_liquidity=False,
            no_signal_check={
                "alpha_signal_source": "no_signal",
                "direction": 1.0,
                "confidence": 0.0,
                "target_weight_hint": None,
                "no_signal_tolerance": 0.0001,
                "fee_model": "test_fee_model",
                "world_seed_or_hash": "seed-1",
                "observation_audit_status": "pass",
                "net_reward_after_fees": 0.01,
                "excess_score_vs_no_trade_cash": 0.02,
            },
            report_dir=tmp_path,
        )
    )

    exploit_detector = report["episode"]["exploit_detector"]
    no_signal = {row["name"]: row for row in exploit_detector["checks"]}["no_signal_world"]

    assert exploit_detector["status"] == "failed"
    assert no_signal["status"] == "fail"
    assert "direction_not_zero" in no_signal["failures"]
    assert "net_reward_after_fees_above_tolerance" in no_signal["failures"]
    assert "excess_score_vs_no_trade_cash_above_tolerance" in no_signal["failures"]
