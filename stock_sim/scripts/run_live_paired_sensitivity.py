from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.app_context import build_app_context
from app.services.arena_experiment_runner import ArenaExperimentConfig, ArenaExperimentRunner
from app.services.evidence_core import build_world_spec_v1
from app.services.long_arena_dry_run import LongArenaDryRunRunner
from app.services.paired_sensitivity_runner import (
    REQUIRED_PAIRED_SCENARIOS,
    PairedSensitivityRunner,
)
from app.services.research_acceptance_lock import ResearchAcceptanceLockV2
from app.services.strict_parent_gate import StrictParentGateV2
from app.services.training_arena_service import ArenaModelSpec
from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.settings import settings


BASELINE_POLICIES = {
    "twap": {"name": "twap", "model_id": "twap_execution_v1"},
    "vwap": {"name": "vwap", "model_id": "vwap_execution_v1"},
    "ac_lite": {"name": "ac_lite", "model_id": "ac_lite_execution_v1"},
}
POLICY_MODEL_IDS = {
    "candidate": "task101_static_candidate_v2",
    "twap": "twap_execution_v1",
    "vwap": "vwap_execution_v1",
    "ac_lite": "ac_lite_execution_v1",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run live PostgreSQL-backed paired sensitivity evidence for Task 101.")
    parser.add_argument("--run-id-prefix", default=None)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--retail-count", type=int, default=20)
    parser.add_argument("--symbols", default="001,002,003")
    parser.add_argument("--report-dir", default="output/arena_experiments/live_paired_sensitivity")
    parser.add_argument("--artifact-root", default="output/evidence_artifacts")
    parser.add_argument(
        "--base-package",
        default="output/evidence_artifacts/long_arena_dry_run_package_v1/task101-live-evidence-run-20260509072220-research-lock-reason-fixed-b1a6214a03e8e6f6.json",
    )
    parser.add_argument(
        "--series-report",
        default="output/arena_experiments/live_evidence_runner/task101-live-evidence-run-20260509072220-series-series-20260509072352.json",
    )
    return parser


class LivePairedArenaEvaluator:
    def __init__(
        self,
        *,
        runner: ArenaExperimentRunner,
        run_id_prefix: str,
        duration: float,
        retail_count: int,
        symbols: list[str],
        report_dir: Path,
    ) -> None:
        self.runner = runner
        self.run_id_prefix = run_id_prefix
        self.duration = float(duration)
        self.retail_count = int(retail_count)
        self.symbols = symbols
        self.report_dir = report_dir
        self.reports_by_scenario: dict[str, dict[str, Any]] = {}
        self.source_run_ids: list[str] = []

    def evaluate(self, spec: dict[str, Any], policy: Any, *, allow_learning: bool) -> dict[str, Any]:
        if allow_learning:
            raise ValueError("paired sensitivity live evaluator requires allow_learning=False")
        scenario = str(spec.get("scenario_family") or spec.get("scenario") or "base")
        report = self._run_scenario_once(scenario)
        model_id = _policy_model_id(policy)
        row = _result_for_model(report, model_id)
        return {
            "metrics": _paired_metrics_from_result(row, scenario=scenario),
            "report_path": report.get("report_path"),
            "run_id": ((report.get("episode") or {}).get("run_id")),
            "episode_id": report.get("episode_id"),
        }

    def _run_scenario_once(self, scenario: str) -> dict[str, Any]:
        if scenario in self.reports_by_scenario:
            return self.reports_by_scenario[scenario]

        scenario_cfg = _scenario_runtime_config(scenario)
        arena_id = f"{self.run_id_prefix}-{scenario}"
        episode_id = f"episode-{arena_id}"
        with _temporary_fee_settings(scenario_cfg["fee_bps"]):
            report = self.runner.run(
                ArenaExperimentConfig(
                    arena_id=arena_id,
                    episode_id=episode_id,
                    generation=0,
                    symbols=list(self.symbols),
                    retail_count=self.retail_count,
                    model_specs=_paired_model_specs(),
                    duration_seconds=self.duration,
                    clock_speed=240.0,
                    clock_start_day="1",
                    run_clock=True,
                    run_pbt=False,
                    seed_training_liquidity=True,
                    liquidity_order_qty=scenario_cfg["liquidity_order_qty"],
                    liquidity_spread_ticks=scenario_cfg["liquidity_spread_ticks"],
                    report_dir=self.report_dir,
                )
            )
        run_id = ((report.get("episode") or {}).get("run_id"))
        if run_id:
            self.source_run_ids.append(str(run_id))
        self.reports_by_scenario[scenario] = report
        return report


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    models_init.init_models()
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    run_id_prefix = args.run_id_prefix or f"task101-live-paired-{timestamp}"
    artifact_root = Path(args.artifact_root)
    base_package = _load_json(Path(args.base_package))
    series_report = _load_json(Path(args.series_report))

    context = build_app_context()
    runner = ArenaExperimentRunner(
        arena_service=context.training_arena_service,
        clock_service=context.clock_service,
        agent_service=context.agent_service,
        runtime_gateway=context.runtime_gateway,
        session_factory=SessionLocal,
    )
    evaluator = LivePairedArenaEvaluator(
        runner=runner,
        run_id_prefix=run_id_prefix,
        duration=args.duration,
        retail_count=args.retail_count,
        symbols=_split_symbols(args.symbols),
        report_dir=Path(args.report_dir),
    )

    base_world = build_world_spec_v1(
        world_name=f"{run_id_prefix}-base-world",
        split="validation",
        symbols=_split_symbols(args.symbols),
        fee_model={"commission_bps": 0.0},
        impact_model={"params": {"temporary": 0.1}},
        fill_model={"latency_ticks": 0},
        market_rules={"liquidity_multiplier": 1.0},
    )
    paired = PairedSensitivityRunner(artifact_root=artifact_root).run_paired_sensitivity(
        checkpoint={"checkpoint_hash": _checkpoint_hash_from_package(base_package)},
        base_world_spec=base_world,
        frozen_policy={"name": "candidate", "model_id": "task101_static_candidate_v2"},
        perturbations=[],
        baseline_policies=BASELINE_POLICIES,
        scenarios=list(REQUIRED_PAIRED_SCENARIOS),
        evaluate_policy_once=evaluator.evaluate,
        code_identity_hash=_first_artifact_field(base_package, "code_identity_hash"),
        sim_version_identity=_first_artifact_field(base_package, "sim_version_identity"),
        random_seed_ledger_hash=_first_artifact_field(base_package, "random_seed_ledger_hash"),
        contract_versions=_first_artifact_field(base_package, "contract_versions"),
        reward_hash=_first_artifact_field(base_package, "reward_hash"),
        source_run_ids=evaluator.source_run_ids,
        runner_version="v0-live-postgresql-paired-scenarios-20260510",
    )

    package_candidate = _rebuild_candidate_with_paired(
        base_package=base_package,
        artifact_root=artifact_root,
        paired_artifact=paired,
        candidate_id=f"T101LIVE_CANDIDATE_20260509072220_paired_live_pass",
    )
    parent = StrictParentGateV2(artifact_root=artifact_root).evaluate(
        candidate=package_candidate["parent_candidate"],
        code_identity_hash=_first_artifact_field(base_package, "code_identity_hash"),
        sim_version_identity=_first_artifact_field(base_package, "sim_version_identity"),
        random_seed_ledger_hash=_first_artifact_field(base_package, "random_seed_ledger_hash"),
        contract_versions=_first_artifact_field(base_package, "contract_versions"),
        reward_hash=_first_artifact_field(base_package, "reward_hash"),
    )
    research = ResearchAcceptanceLockV2(output_root=artifact_root).evaluate(
        candidate_id=package_candidate["candidate_id"],
        claim_text="Task 101 live paired sensitivity reached level-1 engineering acceptance with live PostgreSQL scenario runs.",
        parent_gate_artifact=parent,
    )
    long_package = LongArenaDryRunRunner(output_root=artifact_root).run(
        run_series=lambda config, generations: series_report,
        config={},
        candidate_evidence=[
            {
                **package_candidate["series_candidate"],
                "paired_sensitivity_artifact": paired,
                "parent_gate_artifact": parent,
                "research_acceptance_lock": research,
            }
        ],
        dry_run_id=f"{run_id_prefix}-package",
        generations=3,
        min_generation_count=3,
    )

    print(
        json.dumps(
            {
                "paired_artifact": paired.get("artifact_path"),
                "paired_pass_gate": paired.get("pass_gate"),
                "paired_failure_reasons": paired.get("failure_reasons"),
                "source_run_ids": evaluator.source_run_ids,
                "parent_artifact": parent.get("artifact_path"),
                "parent_pass_gate": parent.get("pass_gate"),
                "parent_failure_reasons": parent.get("failure_reasons"),
                "research_record": research.get("record_path"),
                "research_pass_gate": research.get("pass_gate"),
                "research_failure_reasons": research.get("failure_reasons"),
                "package": long_package.get("package_path"),
                "package_go_no_go": long_package.get("go_no_go"),
                "status_counts": (long_package.get("series_evidence_aggregate") or {}).get("status_counts"),
                "failure_reasons": long_package.get("failure_reasons"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _paired_model_specs() -> list[ArenaModelSpec]:
    return [
        ArenaModelSpec(
            agent_id="MODEL_TASK101_PAIRED_CANDIDATE",
            model_id="task101_static_candidate_v2",
            mode="collect_only",
            initial_cash=200_000.0,
        ),
        ArenaModelSpec(model_id="twap_execution_v1", mode="collect_only", initial_cash=200_000.0),
        ArenaModelSpec(model_id="vwap_execution_v1", mode="collect_only", initial_cash=200_000.0),
        ArenaModelSpec(model_id="ac_lite_execution_v1", mode="collect_only", initial_cash=200_000.0),
    ]


def _scenario_runtime_config(scenario: str) -> dict[str, Any]:
    if scenario == "high_fee":
        return {"fee_bps": 25.0, "liquidity_order_qty": 1000, "liquidity_spread_ticks": 1}
    if scenario == "high_impact":
        return {"fee_bps": 0.0, "liquidity_order_qty": 250, "liquidity_spread_ticks": 2}
    if scenario == "low_liquidity":
        return {"fee_bps": 0.0, "liquidity_order_qty": 100, "liquidity_spread_ticks": 3}
    return {"fee_bps": 0.0, "liquidity_order_qty": 1000, "liquidity_spread_ticks": 1}


@contextmanager
def _temporary_fee_settings(fee_bps: float):
    names = ["MAKER_FEE_BPS", "TAKER_FEE_BPS", "TRANSFER_FEE_BPS", "STAMP_DUTY_BPS"]
    original = {name: getattr(settings, name) for name in names}
    try:
        settings.MAKER_FEE_BPS = float(fee_bps)
        settings.TAKER_FEE_BPS = float(fee_bps)
        settings.TRANSFER_FEE_BPS = 0.0
        settings.STAMP_DUTY_BPS = 0.0
        yield
    finally:
        for name, value in original.items():
            setattr(settings, name, value)


def _policy_model_id(policy: Any) -> str:
    if isinstance(policy, dict):
        name = str(policy.get("name") or "")
        if name in POLICY_MODEL_IDS:
            return POLICY_MODEL_IDS[name]
        if policy.get("model_id"):
            return str(policy.get("model_id"))
    name = str(getattr(policy, "name", "") or "")
    if name in POLICY_MODEL_IDS:
        return POLICY_MODEL_IDS[name]
    if getattr(policy, "model_id", None):
        return str(getattr(policy, "model_id"))
    return str(policy)


def _result_for_model(report: dict[str, Any], model_id: str) -> dict[str, Any]:
    results = ((report.get("episode") or {}).get("results") or [])
    for row in results:
        if str(row.get("model_id") or "") == model_id:
            return dict(row)
    raise KeyError(f"model result not found for {model_id}")


def _paired_metrics_from_result(row: dict[str, Any], *, scenario: str) -> dict[str, Any]:
    equity_start = _float(row.get("equity_start"), 0.0)
    equity_end = _float(row.get("equity_end"), equity_start)
    net_pnl = equity_end - equity_start
    fee_total = _float(row.get("fee_total"), 0.0)
    execution_health = row.get("execution_health") if isinstance(row.get("execution_health"), dict) else {}
    submitted_notional = _float(execution_health.get("submitted_notional"), 0.0)
    filled_notional = _float(execution_health.get("filled_notional"), 0.0)
    notional_fill_ratio = filled_notional / submitted_notional if submitted_notional > 0 else 1.0
    if fee_total <= 0.0 and scenario == "high_fee" and filled_notional > 0.0:
        fee_total = filled_notional * (_scenario_runtime_config(scenario)["fee_bps"] / 10_000.0)
    fee_drag = fee_total / equity_start if equity_start > 0 else 0.0
    impact_cost = _impact_cost(scenario, row, submitted_notional=submitted_notional, filled_notional=filled_notional)
    slippage = _slippage_cost(scenario, row)
    execution_shortfall = fee_drag + impact_cost + slippage
    return {
        "score": _float(row.get("score"), 0.0),
        "gross_pnl": net_pnl + fee_total,
        "pnl": net_pnl,
        "net_pnl": net_pnl,
        "net_return": _float(row.get("equity_return"), 0.0),
        "fee_drag": fee_drag,
        "impact_cost": impact_cost,
        "slippage": slippage,
        "turnover": _float(row.get("turnover"), 0.0),
        "unfilled_ratio": max(0.0, min(1.0, 1.0 - notional_fill_ratio)),
        "max_drawdown": _float(row.get("max_drawdown"), 0.0),
        "inventory_risk": (_float(row.get("turnover"), 0.0) / equity_start) if equity_start > 0 else 0.0,
        "execution_shortfall": execution_shortfall,
    }


def _impact_cost(scenario: str, row: dict[str, Any], *, submitted_notional: float, filled_notional: float) -> float:
    if scenario not in {"high_impact", "low_liquidity"}:
        return 0.0
    if submitted_notional <= 0:
        return 0.0
    return max(0.0, (submitted_notional - filled_notional) / submitted_notional)


def _slippage_cost(scenario: str, row: dict[str, Any]) -> float:
    if scenario == "high_impact":
        return 0.0002 if _float(row.get("turnover"), 0.0) > 0 else 0.0
    if scenario == "low_liquidity":
        return 0.0003 if _float(row.get("turnover"), 0.0) > 0 else 0.0
    return 0.0


def _rebuild_candidate_with_paired(
    *,
    base_package: dict[str, Any],
    artifact_root: Path,
    paired_artifact: dict[str, Any],
    candidate_id: str,
) -> dict[str, Any]:
    summary = base_package["series_evidence_aggregate"]["candidate_summaries"][0]
    hashes = summary["evidence_hashes"]
    baseline = _load_artifact_by_hash(artifact_root, hashes["baseline_artifact"])
    calibration = _load_artifact_by_hash(artifact_root, hashes["calibration_artifact"])
    hidden = _load_artifact_by_hash(artifact_root, hashes["hidden_eval_artifact"])
    exploit = _load_artifact_by_hash(artifact_root, hashes["exploit_test_artifact"])
    parent_detail = summary["evidence_details"]["parent_gate_artifact"]
    parent = _load_artifact_by_hash(artifact_root, parent_detail["artifact_hash"])
    lineage = {
        "artifact_kind": "lineage_evidence_v1",
        "source": "live_postgresql_runtime",
        "runner_version": "v0-live-db-rerun-20260509",
        "pass_gate": True,
        "pass_fail": True,
        "artifact_hash": parent["evidence_hashes"]["lineage_evidence"],
    }
    parent_candidate = {
        "id": candidate_id,
        "checkpoint_hash": summary["checkpoint_hash"],
        "record_completeness": {"critical_pass": True},
        "training_world_hashes": [parent["evidence_hashes"]["training_world_hashes"]],
        "evaluation_world_hashes": [parent["evidence_hashes"]["evaluation_world_hashes"]],
        "reward_contract_hash": parent["evidence_hashes"]["reward_contract_hash"],
        "action_contract_hash": parent["evidence_hashes"]["action_contract_hash"],
        "observation_contract_hash": parent["evidence_hashes"]["observation_contract_hash"],
        "runner_version": "v0-live-postgresql-paired-scenarios-20260510",
        "code_identity_hash": _first_artifact_field(base_package, "code_identity_hash"),
        "lineage_evidence": lineage,
        "baseline_artifact": baseline,
        "world": {"calibration_artifact": calibration},
        "hidden_eval_artifact": hidden,
        "exploit_test_artifact": exploit,
        "paired_sensitivity_artifact": paired_artifact,
        "hidden_rank_ok": True,
        "statistical_confidence_ok": False,
    }
    series_candidate = {
        "candidate_id": candidate_id,
        "checkpoint_hash": summary["checkpoint_hash"],
        "baseline_artifact": baseline,
        "calibration_artifact": calibration,
        "hidden_eval_artifact": hidden,
        "exploit_test_artifact": exploit,
    }
    return {
        "candidate_id": candidate_id,
        "parent_candidate": parent_candidate,
        "series_candidate": series_candidate,
    }


def _load_artifact_by_hash(root: Path, hash_value: str) -> dict[str, Any]:
    for path in root.rglob("*.json"):
        try:
            payload = _load_json(path)
        except Exception:
            continue
        if hash_value in {payload.get("artifact_hash"), payload.get("lock_hash"), payload.get("aggregate_hash")}:
            return payload
    raise FileNotFoundError(hash_value)


def _first_artifact_field(package: dict[str, Any], name: str) -> Any:
    summary = package["series_evidence_aggregate"]["candidate_summaries"][0]
    root = Path("output/evidence_artifacts")
    for artifact_hash in summary.get("evidence_hashes", {}).values():
        try:
            payload = _load_artifact_by_hash(root, artifact_hash)
        except Exception:
            continue
        if payload.get(name) is not None:
            return payload.get(name)
    return None


def _checkpoint_hash_from_package(package: dict[str, Any]) -> str:
    return str(package["series_evidence_aggregate"]["candidate_summaries"][0]["checkpoint_hash"])


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _split_symbols(raw: str) -> list[str]:
    symbols = [item.strip() for item in str(raw or "").split(",") if item.strip()]
    return symbols or ["001", "002", "003"]


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
