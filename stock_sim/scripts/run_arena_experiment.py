from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.app_context import build_app_context
from app.services.arena_experiment_runner import ArenaExperimentConfig, ArenaExperimentRunner
from app.services.training_arena_service import ArenaModelSpec
from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one StockSim Arena experiment episode.")
    parser.add_argument("--arena-id", default=None)
    parser.add_argument("--episode-id", default=None)
    parser.add_argument("--generation", type=int, default=0)
    parser.add_argument("--generations", type=int, default=1, help="Number of sequential Arena generations to run.")
    parser.add_argument("--duration", type=float, default=30.0, help="Real seconds to let the episode run.")
    parser.add_argument("--retail-count", type=int, default=100)
    parser.add_argument("--symbols", default="001,002,003", help="Comma-separated symbol list.")
    parser.add_argument("--clock-speed", type=float, default=240.0)
    parser.add_argument("--clock-start-day", default="1")
    parser.add_argument("--no-clock", action="store_true")
    parser.add_argument("--no-pbt", action="store_true")
    parser.add_argument("--include-baselines-in-pbt", action="store_true")
    parser.add_argument("--apply-inheritance", action="store_true")
    parser.add_argument("--no-liquidity-seed", action="store_true")
    parser.add_argument("--liquidity-order-qty", type=int, default=5000)
    parser.add_argument("--liquidity-spread-ticks", type=int, default=1)
    parser.add_argument("--pbt-min-parent-trades", type=int, default=1)
    parser.add_argument("--report-dir", default="output/arena_experiments")
    parser.add_argument("--checkpoint-dir", default="output/model_checkpoints")
    parser.add_argument(
        "--model",
        action="append",
        default=None,
        help="Model spec as model_id[:agent_id[:mode[:cash]]]. Can be repeated.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    models_init.init_models()
    context = build_app_context()
    config = ArenaExperimentConfig(
        arena_id=args.arena_id,
        episode_id=args.episode_id,
        generation=args.generation,
        symbols=_split_symbols(args.symbols),
        retail_count=max(0, int(args.retail_count)),
        model_specs=_parse_models(args.model),
        duration_seconds=max(0.0, float(args.duration)),
        clock_speed=float(args.clock_speed),
        clock_start_day=str(args.clock_start_day),
        run_clock=not bool(args.no_clock),
        run_pbt=not bool(args.no_pbt),
        apply_inheritance=bool(args.apply_inheritance),
        pbt_excluded_model_ids=[] if args.include_baselines_in_pbt else ["hold_model_v1", "random_weight_v1"],
        pbt_min_parent_trade_count=max(0, int(args.pbt_min_parent_trades)),
        seed_training_liquidity=not bool(args.no_liquidity_seed),
        liquidity_order_qty=max(1, int(args.liquidity_order_qty)),
        liquidity_spread_ticks=max(1, int(args.liquidity_spread_ticks)),
        report_dir=args.report_dir,
        checkpoint_dir=args.checkpoint_dir,
    )
    runner = ArenaExperimentRunner(
        arena_service=context.training_arena_service,
        clock_service=context.clock_service,
        agent_service=context.agent_service,
        runtime_gateway=context.runtime_gateway,
        session_factory=SessionLocal,
    )
    report = runner.run_generations(config, generations=max(1, int(args.generations)))
    print(json.dumps(_console_summary(report), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _split_symbols(raw: str) -> list[str]:
    symbols = [item.strip() for item in str(raw or "").split(",") if item.strip()]
    return symbols or ["001", "002", "003"]


def _parse_models(raw_items: list[str] | None) -> list[ArenaModelSpec]:
    if not raw_items:
        return ArenaExperimentConfig().model_specs
    specs: list[ArenaModelSpec] = []
    for raw in raw_items:
        parts = [part.strip() for part in str(raw or "").split(":")]
        model_id = parts[0] if parts and parts[0] else "hold_model_v1"
        agent_id = parts[1] if len(parts) > 1 and parts[1] else None
        mode = parts[2] if len(parts) > 2 and parts[2] else "collect_only"
        initial_cash = float(parts[3]) if len(parts) > 3 and parts[3] else 200_000.0
        specs.append(ArenaModelSpec(agent_id=agent_id, model_id=model_id, mode=mode, initial_cash=initial_cash))
    return specs


def _console_summary(report: dict[str, Any]) -> dict[str, Any]:
    if report.get("schema") == "stock_sim.arena_generation_series_report.v1":
        return {
            "schema": report.get("schema"),
            "series_id": report.get("series_id"),
            "generation_count": report.get("generation_count"),
            "report_path": report.get("report_path"),
            "aggregate": report.get("aggregate") or {},
            "generations": report.get("generations") or [],
        }
    results = list(((report.get("episode") or {}).get("results") or []))
    return {
        "arena_id": report.get("arena_id"),
        "episode_id": report.get("episode_id"),
        "report_path": report.get("report_path"),
        "transition_count": (report.get("episode") or {}).get("transition_count"),
        "liquidity_seeded": (report.get("states") or {}).get("liquidity_seeded"),
        "execution_health": ((report.get("episode") or {}).get("execution_health") or {}).get("totals") or {},
        "top_results": [
            {
                "rank": row.get("rank"),
                "agent_id": row.get("agent_id"),
                "model_id": row.get("model_id"),
                "score": row.get("score"),
                "equity_return": row.get("equity_return"),
                "trade_count": row.get("trade_count"),
                "fill_ratio": (row.get("execution_health") or {}).get("fill_ratio"),
                "notional_fill_ratio": (row.get("execution_health") or {}).get("notional_fill_ratio"),
            }
            for row in results[:5]
        ],
        "pbt": _compact_pbt(report.get("pbt") or {}),
        "timings_ms": report.get("timings_ms") or {},
    }


def _compact_pbt(pbt: dict[str, Any]) -> dict[str, Any]:
    return {
        "winners": pbt.get("winners") or [],
        "losers": pbt.get("losers") or [],
        "eligible_agents": pbt.get("eligible_agents") or [],
        "parent_eligible_agents": pbt.get("parent_eligible_agents") or [],
        "parent_activity_gate": pbt.get("parent_activity_gate") or {},
        "excluded_model_ids": pbt.get("excluded_model_ids") or [],
        "checkpoint_count": len(pbt.get("checkpoints") or []),
        "lineage_count": len(pbt.get("lineage") or []),
        "applied_count": len(pbt.get("applied_agents") or []),
    }


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
