from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Callable, Sequence
import uuid

from app.services.model_checkpoint_service import ModelCheckpointService
from app.services.model_population_service import ModelPopulationService, PopulationEvolutionConfig
from app.services.training_arena_service import ArenaModelSpec, TrainingArenaConfig, TrainingArenaService
from rl.contracts import ACT_CONTRACT_VERSION, OBS_CONTRACT_VERSION, REWARD_CONTRACT_VERSION

try:
    from stock_sim import __version__ as STOCK_SIM_VERSION
    from stock_sim.persistence.models_imports import SessionLocal
    from persistence.models_training import ModelEpisodeResult, ModelTransition, TrainingEpisode
    from stock_sim.services.account_service import AccountService as RuntimeAccountService
except Exception:  # pragma: no cover
    STOCK_SIM_VERSION = None  # type: ignore
    SessionLocal = None  # type: ignore
    ModelEpisodeResult = None  # type: ignore
    ModelTransition = None  # type: ignore
    TrainingEpisode = None  # type: ignore
    RuntimeAccountService = None  # type: ignore


DEFAULT_MODEL_INITIAL_CASH = 50_000_000.0


@dataclass
class ArenaExperimentConfig:
    arena_id: str | None = None
    episode_id: str | None = None
    generation: int = 0
    symbols: list[str] = field(default_factory=lambda: ["001", "002", "003"])
    retail_count: int = 100
    retail_initial_cash: float = 100_000.0
    model_specs: list[ArenaModelSpec] = field(default_factory=lambda: [
        ArenaModelSpec(agent_id="MODEL_PPO_LSTM_A", model_id="ppo_lstm_v1", mode="online_train", initial_cash=DEFAULT_MODEL_INITIAL_CASH),
        ArenaModelSpec(agent_id="MODEL_PPO_LSTM_B", model_id="ppo_lstm_v1", mode="online_train", initial_cash=DEFAULT_MODEL_INITIAL_CASH),
        ArenaModelSpec(agent_id="MODEL_PPO_LSTM_C", model_id="ppo_lstm_v1", mode="online_train", initial_cash=DEFAULT_MODEL_INITIAL_CASH),
        ArenaModelSpec(model_id="hold_model_v1", mode="collect_only", initial_cash=DEFAULT_MODEL_INITIAL_CASH),
        ArenaModelSpec(model_id="random_weight_v1", mode="collect_only", initial_cash=DEFAULT_MODEL_INITIAL_CASH),
        ArenaModelSpec(model_id="target_weight_naive_rebalance_v1", mode="collect_only", initial_cash=DEFAULT_MODEL_INITIAL_CASH),
        ArenaModelSpec(model_id="twap_execution_v1", mode="collect_only", initial_cash=DEFAULT_MODEL_INITIAL_CASH),
        ArenaModelSpec(model_id="vwap_execution_v1", mode="collect_only", initial_cash=DEFAULT_MODEL_INITIAL_CASH),
        ArenaModelSpec(model_id="ac_lite_execution_v1", mode="collect_only", initial_cash=DEFAULT_MODEL_INITIAL_CASH),
    ])
    duration_seconds: float = 30.0
    clock_speed: float = 240.0
    clock_start_day: str = "1"
    run_clock: bool = True
    reward_profile: str = "relative_equity_risk_adjusted_v1"
    task_name: str = "alpha_to_execution.v1"
    run_pbt: bool = True
    apply_inheritance: bool = False
    seed_training_liquidity: bool = True
    persist_market_data: bool = True
    flush_market_bars_on_finish: bool = True
    liquidity_account_id: str = "ARENA_LIQUIDITY"
    liquidity_order_qty: int = 1_000_000_000
    liquidity_spread_ticks: int = 1
    pbt_excluded_model_ids: list[str] = field(default_factory=lambda: [
        "hold_model_v1",
        "random_weight_v1",
        "target_weight_naive_rebalance_v1",
        "twap_execution_v1",
        "vwap_execution_v1",
        "ac_lite_execution_v1",
    ])
    pbt_strict_parent_eligibility: bool = False
    pbt_min_parent_trade_count: int = 1
    pbt_min_parent_notional_fill_ratio: float = 0.0
    no_signal_check: dict[str, Any] | None = None
    no_signal_tolerance: float = 0.0
    no_signal_fee_model: str | None = None
    no_signal_observation_audit_status: str | None = None
    report_dir: str | Path = "output/arena_experiments"
    checkpoint_dir: str | Path = "output/model_checkpoints"


class ArenaExperimentRunner:
    """Run one repeatable Arena episode from orchestration to JSON report."""

    def __init__(
        self,
        *,
        arena_service: TrainingArenaService,
        clock_service: Any | None = None,
        agent_service: Any | None = None,
        runtime_gateway: Any | None = None,
        session_factory: Callable[[], Any] | None = None,
    ):
        self._arena_service = arena_service
        self._clock_service = clock_service
        self._agent_service = agent_service
        self._runtime_gateway = runtime_gateway
        self._session_factory = session_factory or SessionLocal

    def run_generations(
        self,
        config: ArenaExperimentConfig | dict[str, Any] | None = None,
        *,
        generations: int = 1,
    ) -> dict[str, Any]:
        cfg = _coerce_experiment_config(config or ArenaExperimentConfig())
        generation_count = max(1, int(generations or 1))
        if generation_count == 1:
            return self.run(cfg)

        series_id = cfg.arena_id or f"arena-series-{uuid.uuid4().hex[:8]}"
        started_at = _utc_now()
        reports: list[dict[str, Any]] = []
        active_specs = list(cfg.model_specs)
        for offset in range(generation_count):
            generation = int(cfg.generation) + offset
            generation_specs = self._model_specs_for_generation(active_specs)
            generation_cfg = replace(
                cfg,
                arena_id=f"{series_id}-g{generation}",
                episode_id=(
                    f"{cfg.episode_id}-g{generation}"
                    if cfg.episode_id
                    else f"episode-{series_id}-g{generation}-{uuid.uuid4().hex[:6]}"
                ),
                generation=generation,
                apply_inheritance=bool(cfg.apply_inheritance or cfg.run_pbt),
                model_specs=generation_specs,
            )
            report = self.run(generation_cfg)
            reports.append(report)
            active_specs = _model_specs_after_report(generation_specs, report)

        report = {
            "schema": "stock_sim.arena_generation_series_report.v1",
            "generated_at": _utc_now(),
            "started_at": started_at,
            "series_id": series_id,
            "generation_count": generation_count,
            "config": _config_to_dict(cfg),
            "generations": [_generation_summary(item) for item in reports],
            "reports": reports,
            "aggregate": _series_aggregate(reports),
        }
        report_path = self._write_series_report(report, cfg.report_dir, series_id=series_id)
        report["report_path"] = str(report_path)
        return report

    def run(self, config: ArenaExperimentConfig | dict[str, Any] | None = None) -> dict[str, Any]:
        cfg = _coerce_experiment_config(config or ArenaExperimentConfig())
        cfg.symbols = [_normalize_symbol(item) for item in cfg.symbols if _normalize_symbol(item)]
        arena_id = cfg.arena_id or f"arena-exp-{uuid.uuid4().hex[:8]}"
        episode_id = cfg.episode_id or f"episode-{arena_id}-g{int(cfg.generation)}-{uuid.uuid4().hex[:6]}"
        started_at = _utc_now()
        timings: dict[str, float] = {}
        errors: list[dict[str, str]] = []
        states: dict[str, Any] = {}
        clock_started = False
        arena_started = False
        pbt_result: dict[str, Any] | None = None

        try:
            t0 = time.perf_counter()
            states["created"] = self._arena_service.create_arena(
                TrainingArenaConfig(
                    arena_id=arena_id,
                    model_specs=list(cfg.model_specs),
                    retail_count=max(0, int(cfg.retail_count or 0)),
                    retail_initial_cash=float(cfg.retail_initial_cash),
                    symbols=list(cfg.symbols),
                    generation=int(cfg.generation),
                    reward_profile=cfg.reward_profile,
                )
            )
            timings["create_arena_ms"] = _elapsed_ms(t0)

            if cfg.persist_market_data and self._runtime_gateway is not None:
                t0 = time.perf_counter()
                states["market_data_persistence"] = _ensure_market_data_persistence()
                timings["start_market_data_persistence_ms"] = _elapsed_ms(t0)

            if cfg.run_clock and self._clock_service is not None:
                t0 = time.perf_counter()
                _safe_call(self._clock_service, "set_speed", float(cfg.clock_speed))
                _safe_call(self._clock_service, "start", str(cfg.clock_start_day))
                clock_started = True
                timings["start_clock_ms"] = _elapsed_ms(t0)

            if cfg.seed_training_liquidity:
                t0 = time.perf_counter()
                states["liquidity_seeded"] = self._seed_training_liquidity(cfg, episode_id=episode_id)
                timings["seed_liquidity_ms"] = _elapsed_ms(t0)

            t0 = time.perf_counter()
            states["started"] = self._arena_service.start_arena(arena_id, episode_id=episode_id)
            arena_started = True
            timings["start_arena_ms"] = _elapsed_ms(t0)

            if cfg.retail_count > 0 and self._runtime_gateway is not None:
                t0 = time.perf_counter()
                _safe_call(self._runtime_gateway, "allocate_pending_ipo_distributions_if_running")
                states["retail_distribution_after_start"] = _safe_call(
                    self._runtime_gateway,
                    "ensure_open_instrument_retail_distributions",
                    sim_day=_safe_call(self._runtime_gateway, "get_current_sim_day"),
                )
                timings["retail_distribution_after_start_ms"] = _elapsed_ms(t0)

            if cfg.duration_seconds > 0:
                t0 = time.perf_counter()
                time.sleep(float(cfg.duration_seconds))
                timings["runtime_ms"] = _elapsed_ms(t0)

            t0 = time.perf_counter()
            states["stopped"] = self._arena_service.stop_arena(arena_id)
            arena_started = False
            timings["stop_arena_ms"] = _elapsed_ms(t0)

            t0 = time.perf_counter()
            states["evaluated"] = self._arena_service.evaluate_arena(arena_id, complete_episode=True)
            timings["evaluate_arena_ms"] = _elapsed_ms(t0)

            if cfg.run_pbt:
                t0 = time.perf_counter()
                pbt_result = self._run_pbt(episode_id, cfg)
                timings["pbt_ms"] = _elapsed_ms(t0)

            if cfg.flush_market_bars_on_finish and self._runtime_gateway is not None:
                t0 = time.perf_counter()
                run_id = _episode_run_id(episode_id, self._session_factory)
                states["market_data_bar_flush"] = _flush_market_bars(run_id=run_id)
                timings["flush_market_bars_ms"] = _elapsed_ms(t0)
        except Exception as exc:
            errors.append({"stage": "run", "error": str(exc)})
            raise
        finally:
            if arena_started:
                try:
                    states["finally_stopped"] = self._arena_service.stop_arena(arena_id)
                except Exception as exc:
                    errors.append({"stage": "stop_arena", "error": str(exc)})
            if clock_started and self._clock_service is not None:
                try:
                    _safe_call(self._clock_service, "stop")
                except Exception as exc:
                    errors.append({"stage": "stop_clock", "error": str(exc)})

        record_metadata = _experiment_record_metadata(cfg)
        report = {
            "schema": "stock_sim.arena_experiment_report.v1",
            "generated_at": _utc_now(),
            "started_at": started_at,
            "arena_id": arena_id,
            "episode_id": episode_id,
            "code_hash": record_metadata.get("code_hash"),
            "sim_version": record_metadata.get("sim_version"),
            "random_seed": record_metadata.get("random_seed"),
            "record_kind": record_metadata["record_kind"],
            "reward_hash": record_metadata["reward_hash"],
            "world_hash": record_metadata["world_hash"],
            "world_card": record_metadata["world_card"],
            "experiment_record_metadata": record_metadata,
            "config": _config_to_dict(cfg),
            "states": states,
            "episode": self._load_episode_details(episode_id, cfg),
            "pbt": pbt_result,
            "timings_ms": timings,
            "errors": errors,
        }
        report_path = self._write_report(report, cfg.report_dir, episode_id=episode_id)
        report["report_path"] = str(report_path)
        return report

    def _model_specs_for_generation(self, specs: list[ArenaModelSpec]) -> list[ArenaModelSpec]:
        if self._agent_service is None:
            return list(specs)
        result: list[ArenaModelSpec] = []
        for spec in specs:
            spec_model_id = str(spec.model_id or "").strip()
            if _is_lineage_model_id(spec_model_id):
                result.append(spec)
                continue
            current = None
            if spec.agent_id:
                try:
                    current = self._agent_service.get(spec.agent_id)
                except Exception:
                    current = None
            current_type = str(getattr(current, "type", "") or "")
            current_model_id = str(getattr(current, "model_id", "") or "").strip()
            current_mode = str(getattr(current, "mode", "") or "").strip()
            if current_type == "Model" and current_model_id:
                result.append(
                    ArenaModelSpec(
                        agent_id=spec.agent_id,
                        model_id=current_model_id,
                        mode=current_mode or spec.mode,
                        initial_cash=spec.initial_cash,
                    )
                )
            else:
                result.append(spec)
        return result

    def _run_pbt(self, episode_id: str, cfg: ArenaExperimentConfig) -> dict[str, Any]:
        if self._session_factory is None:
            return {"episode_id": episode_id, "skipped": True, "reason": "session_factory_unavailable"}
        session = self._session_factory()
        try:
            population = ModelPopulationService(
                session,
                checkpoint_service=ModelCheckpointService(session, checkpoint_root=cfg.checkpoint_dir),
                agent_service=self._agent_service,
            )
            episode_details = self._load_episode_details(episode_id, cfg)
            result = population.evolve_from_episode(
                episode_id,
                generation=int(cfg.generation),
                config=PopulationEvolutionConfig(
                    apply_to_agents=bool(cfg.apply_inheritance),
                    excluded_model_ids=list(cfg.pbt_excluded_model_ids),
                    min_parent_trade_count=int(cfg.pbt_min_parent_trade_count),
                    min_parent_notional_fill_ratio=float(cfg.pbt_min_parent_notional_fill_ratio),
                    strict_parent_eligibility=bool(cfg.pbt_strict_parent_eligibility),
                    research_acceptance=episode_details.get("research_acceptance"),
                ),
            )
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _seed_training_liquidity(self, cfg: ArenaExperimentConfig, *, episode_id: str) -> dict[str, Any]:
        gateway = self._runtime_gateway
        if gateway is None:
            return {"ok": False, "reason": "runtime_gateway_unavailable", "orders": []}
        bid_account_id = _liquidity_account_id(cfg.liquidity_account_id, episode_id, side="BID")
        ask_account_id = _liquidity_account_id(cfg.liquidity_account_id, episode_id, side="ASK")
        symbols = [_normalize_symbol(item) for item in cfg.symbols if _normalize_symbol(item)]
        if not symbols:
            return {"ok": False, "reason": "no_symbols", "orders": []}

        liquidity_cash = self._liquidity_seed_cash(cfg, symbols=symbols)
        for account_id, strategy in (
            (bid_account_id, "arena_passive_seed_bid"),
            (ask_account_id, "arena_passive_seed_ask"),
        ):
            try:
                gateway.bootstrap_agent_account(
                    account_id=account_id,
                    initial_cash=liquidity_cash,
                    agent_type="LIQUIDITY",
                    strategy=strategy,
                )
            except Exception as exc:
                return {"ok": False, "reason": f"bootstrap_failed: {exc}", "orders": []}

        instruments = _instrument_map(_safe_call(gateway, "list_instruments") or [])
        orders: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        qty = max(1, int(cfg.liquidity_order_qty or 0))
        spread_ticks = max(1, int(cfg.liquidity_spread_ticks or 1))
        for symbol in symbols:
            instrument = instruments.get(symbol, {})
            tick = _positive_float(instrument.get("tick_size"), 0.01)
            reference_price = _reference_price(gateway, symbol, instrument)
            bid = _round_to_tick(max(tick, reference_price - spread_ticks * tick), tick, mode="down")
            ask = _round_to_tick(max(tick, reference_price + spread_ticks * tick), tick, mode="up")
            if ask <= bid:
                ask = _round_to_tick(bid + tick, tick, mode="up")
            self._seed_account_inventory(ask_account_id, symbol=symbol, quantity=qty)
            for side, price, account_id in (
                ("buy", bid, bid_account_id),
                ("sell", ask, ask_account_id),
            ):
                try:
                    result = gateway.submit_order(
                        symbol=symbol,
                        side=side,
                        price=float(price),
                        qty=qty,
                        account_id=account_id,
                    )
                    orders.append(
                        {
                            "symbol": symbol,
                            "side": side,
                            "price": float(price),
                            "qty": qty,
                            "status": result.get("status"),
                            "filled": result.get("filled"),
                            "order_id": result.get("order_id"),
                        }
                    )
                except Exception as exc:
                    errors.append({"symbol": symbol, "side": side, "error": str(exc)})
        return {
            "ok": not errors,
            "bid_account_id": bid_account_id,
            "ask_account_id": ask_account_id,
            "liquidity_cash": liquidity_cash,
            "order_count": len(orders),
            "orders": orders,
            "errors": errors,
        }

    def _liquidity_seed_cash(self, cfg: ArenaExperimentConfig, *, symbols: Sequence[str]) -> float:
        gateway = self._runtime_gateway
        instruments = _instrument_map(_safe_call(gateway, "list_instruments") or []) if gateway is not None else {}
        qty = max(1, int(cfg.liquidity_order_qty or 0))
        notional = 0.0
        for symbol in symbols:
            instrument = instruments.get(symbol, {})
            notional += _reference_price(gateway, symbol, instrument) * qty
        return max(10_000_000.0, notional * 2.0)

    def _seed_account_inventory(self, account_id: str, *, symbol: str, quantity: int) -> bool:
        if self._session_factory is None or RuntimeAccountService is None:
            return False
        session = self._session_factory()
        try:
            accounts = RuntimeAccountService(session)
            account = accounts.get_or_create(account_id, cash=10_000_000.0)
            position = accounts.get_position(account, symbol)
            target = max(int(quantity), int(getattr(position, "quantity", 0) or 0))
            position.quantity = target
            if getattr(position, "avg_price", 0.0) in (None, 0, 0.0):
                position.avg_price = 0.0
            session.commit()
            return True
        except Exception:
            session.rollback()
            return False
        finally:
            session.close()

    def _load_episode_details(self, episode_id: str, cfg: ArenaExperimentConfig) -> dict[str, Any]:
        if self._session_factory is None or TrainingEpisode is None or ModelEpisodeResult is None:
            observation_audit = _runtime_observation_audit([], task_name=cfg.task_name)
            fee_sensitivity = _fee_sensitivity_report()
            fee_accounting_audit = _fee_accounting_audit([], [])
            impact_sensitivity = _impact_sensitivity_report()
            timestamp_audit = _timestamp_audit([])
            mark_to_market_audit = _mark_to_market_audit([], [])
            order_anomaly_audit = _order_anomaly_audit([], [])
            sections = _report_research_sections(
                [],
                cfg,
                episode_id=episode_id,
                runtime_observation_audit=observation_audit,
                fee_sensitivity=fee_sensitivity,
                fee_accounting_audit=fee_accounting_audit,
                impact_sensitivity=impact_sensitivity,
                timestamp_audit=timestamp_audit,
                mark_to_market_audit=mark_to_market_audit,
                order_anomaly_audit=order_anomaly_audit,
            )
            return {
                "episode_id": episode_id,
                "results": [],
                "transition_count": 0,
                "runtime_observation_audit": observation_audit,
                "fee_sensitivity": fee_sensitivity,
                "fee_accounting_audit": fee_accounting_audit,
                "impact_sensitivity": impact_sensitivity,
                "timestamp_audit": timestamp_audit,
                "mark_to_market_audit": mark_to_market_audit,
                "order_anomaly_audit": order_anomaly_audit,
                **sections,
            }
        session = self._session_factory()
        try:
            episode = session.get(TrainingEpisode, episode_id)
            rows = (
                session.query(ModelEpisodeResult)
                .filter(ModelEpisodeResult.episode_id == episode_id)
                .order_by(ModelEpisodeResult.rank.asc().nullslast(), ModelEpisodeResult.score.desc())
                .all()
            )
            transition_rows = []
            if ModelTransition is not None:
                transition_rows = (
                    session.query(ModelTransition)
                    .filter(ModelTransition.episode_id == episode_id)
                    .order_by(ModelTransition.agent_id.asc(), ModelTransition.step_index.asc())
                    .all()
                )
            transition_count = len(transition_rows)
            result_rows = [_result_to_dict(row) for row in rows]
            observation_audit = _runtime_observation_audit(transition_rows, task_name=cfg.task_name)
            fee_sensitivity = _fee_sensitivity_report()
            fee_accounting_audit = _fee_accounting_audit(result_rows, transition_rows)
            impact_sensitivity = _impact_sensitivity_report()
            timestamp_audit = _timestamp_audit(transition_rows)
            mark_to_market_audit = _mark_to_market_audit(result_rows, transition_rows)
            order_anomaly_audit = _order_anomaly_audit(result_rows, transition_rows)
            research_sections = _report_research_sections(
                result_rows,
                cfg,
                episode_id=episode_id,
                runtime_observation_audit=observation_audit,
                fee_sensitivity=fee_sensitivity,
                fee_accounting_audit=fee_accounting_audit,
                impact_sensitivity=impact_sensitivity,
                timestamp_audit=timestamp_audit,
                mark_to_market_audit=mark_to_market_audit,
                order_anomaly_audit=order_anomaly_audit,
            )
            return {
                "episode_id": episode_id,
                "arena_id": getattr(episode, "arena_id", None),
                "run_id": getattr(episode, "run_id", None),
                "generation": getattr(episode, "generation", None),
                "status": getattr(episode, "status", None),
                "started_at": _dt(getattr(episode, "started_at", None)),
                "ended_at": _dt(getattr(episode, "ended_at", None)),
                "transition_count": int(transition_count or 0),
                "runtime_observation_audit": observation_audit,
                "fee_sensitivity": fee_sensitivity,
                "fee_accounting_audit": fee_accounting_audit,
                "impact_sensitivity": impact_sensitivity,
                "timestamp_audit": timestamp_audit,
                "mark_to_market_audit": mark_to_market_audit,
                "order_anomaly_audit": order_anomaly_audit,
                "execution_health": _execution_health_summary(result_rows),
                "results": result_rows,
                **research_sections,
            }
        finally:
            session.close()

    @staticmethod
    def _write_report(report: dict[str, Any], report_dir: str | Path, *, episode_id: str) -> Path:
        root = Path(report_dir)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{episode_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
        return path

    @staticmethod
    def _write_series_report(report: dict[str, Any], report_dir: str | Path, *, series_id: str) -> Path:
        root = Path(report_dir)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{series_id}-series-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
        return path


def _coerce_experiment_config(value: ArenaExperimentConfig | dict[str, Any]) -> ArenaExperimentConfig:
    if isinstance(value, ArenaExperimentConfig):
        return value
    raw_specs = value.get("model_specs")
    specs = [_coerce_spec(item) for item in raw_specs] if raw_specs else ArenaExperimentConfig().model_specs
    return ArenaExperimentConfig(
        arena_id=value.get("arena_id"),
        episode_id=value.get("episode_id"),
        generation=int(value.get("generation", 0) or 0),
        symbols=[_normalize_symbol(item) for item in (value.get("symbols") or ["001", "002", "003"])],
        retail_count=int(value.get("retail_count", 100) or 0),
        retail_initial_cash=float(value.get("retail_initial_cash", 100_000.0) or 100_000.0),
        model_specs=specs,
        duration_seconds=float(value.get("duration_seconds", 30.0) or 0.0),
        clock_speed=float(value.get("clock_speed", 240.0) or 240.0),
        clock_start_day=str(value.get("clock_start_day", "1") or "1"),
        run_clock=bool(value.get("run_clock", True)),
        reward_profile=str(value.get("reward_profile", "relative_equity_risk_adjusted_v1") or "relative_equity_risk_adjusted_v1"),
        run_pbt=bool(value.get("run_pbt", True)),
        apply_inheritance=bool(value.get("apply_inheritance", False)),
        seed_training_liquidity=bool(value.get("seed_training_liquidity", True)),
        persist_market_data=bool(value.get("persist_market_data", True)),
        flush_market_bars_on_finish=bool(value.get("flush_market_bars_on_finish", True)),
        liquidity_account_id=str(value.get("liquidity_account_id", "ARENA_LIQUIDITY") or "ARENA_LIQUIDITY"),
        liquidity_order_qty=int(value.get("liquidity_order_qty", 1_000_000_000) or 1_000_000_000),
        liquidity_spread_ticks=int(value.get("liquidity_spread_ticks", 1) or 1),
        pbt_excluded_model_ids=list(value.get("pbt_excluded_model_ids") or [
            "hold_model_v1",
            "random_weight_v1",
            "target_weight_naive_rebalance_v1",
        ]),
        pbt_strict_parent_eligibility=bool(value.get("pbt_strict_parent_eligibility", False)),
        pbt_min_parent_trade_count=int(value.get("pbt_min_parent_trade_count", 1) or 0),
        pbt_min_parent_notional_fill_ratio=float(value.get("pbt_min_parent_notional_fill_ratio", 0.0) or 0.0),
        no_signal_check=_optional_dict(value.get("no_signal_check")),
        no_signal_tolerance=float(value.get("no_signal_tolerance", 0.0) or 0.0),
        no_signal_fee_model=_optional_str(value.get("no_signal_fee_model")),
        no_signal_observation_audit_status=_optional_str(value.get("no_signal_observation_audit_status")),
        task_name=str(value.get("task_name", "alpha_to_execution.v1") or "alpha_to_execution.v1"),
        report_dir=value.get("report_dir", "output/arena_experiments"),
        checkpoint_dir=value.get("checkpoint_dir", "output/model_checkpoints"),
    )


def _coerce_spec(value: ArenaModelSpec | dict[str, Any]) -> ArenaModelSpec:
    if isinstance(value, ArenaModelSpec):
        return value
    return ArenaModelSpec(
        agent_id=value.get("agent_id"),
        model_id=str(value.get("model_id") or "hold_model_v1"),
        mode=str(value.get("mode") or "collect_only"),
        initial_cash=float(value.get("initial_cash", DEFAULT_MODEL_INITIAL_CASH) or DEFAULT_MODEL_INITIAL_CASH),
    )


def _config_to_dict(cfg: ArenaExperimentConfig) -> dict[str, Any]:
    payload = asdict(cfg)
    payload["report_dir"] = str(cfg.report_dir)
    payload["checkpoint_dir"] = str(cfg.checkpoint_dir)
    return payload


def _experiment_record_metadata(cfg: ArenaExperimentConfig) -> dict[str, Any]:
    code_identity = _git_code_identity()
    sim_version_identity = _sim_version_identity()
    random_seed_identity = _random_seed_identity()
    reward_identity = {
        "schema": "stock_sim.reward_identity.v1",
        "reward_profile": str(cfg.reward_profile),
        "task_name": str(cfg.task_name),
        "reward_contract_version": REWARD_CONTRACT_VERSION,
    }
    world_identity = {
        "schema": "stock_sim.arena_world_identity.v1",
        "symbols": list(cfg.symbols),
        "retail_count": int(cfg.retail_count or 0),
        "retail_initial_cash": float(cfg.retail_initial_cash),
        "clock_start_day": str(cfg.clock_start_day),
        "clock_speed": float(cfg.clock_speed),
        "run_clock": bool(cfg.run_clock),
        "seed_training_liquidity": bool(cfg.seed_training_liquidity),
        "liquidity_account_id": str(cfg.liquidity_account_id),
        "liquidity_order_qty": int(cfg.liquidity_order_qty or 0),
        "liquidity_spread_ticks": int(cfg.liquidity_spread_ticks or 0),
    }
    world_hash = _canonical_sha256(world_identity)
    world_card = _world_card(cfg, world_identity=world_identity, world_hash=world_hash)
    code_hash = code_identity.get("code_hash") if code_identity.get("status") == "available" else None
    sim_version = sim_version_identity.get("sim_version") if sim_version_identity.get("status") == "available" else None
    random_seed = random_seed_identity.get("random_seed") if random_seed_identity.get("status") == "available" else None
    missing_sources = []
    if not code_hash:
        missing_sources.insert(0, "code_hash")
    if not sim_version:
        missing_sources.insert(0, "sim_version")
    if random_seed is None:
        missing_sources.append("random_seed")
    return {
        "schema": "stock_sim.experiment_record_metadata.v1",
        "hash_method": "sha256_json_canonical_v1",
        "code_hash": code_hash,
        "code_identity": code_identity,
        "sim_version": sim_version,
        "sim_version_identity": sim_version_identity,
        "random_seed": random_seed,
        "random_seed_identity": random_seed_identity,
        "record_kind": _experiment_record_kind(cfg),
        "reward_hash": _canonical_sha256(reward_identity),
        "reward_identity": reward_identity,
        "world_hash": world_hash,
        "world_identity": world_identity,
        "world_card": world_card,
        "contract_versions": {
            "observation": OBS_CONTRACT_VERSION,
            "action": ACT_CONTRACT_VERSION,
            "reward": REWARD_CONTRACT_VERSION,
        },
        "missing_sources": missing_sources,
        "not_applicable_sources": ["data_cutoff"],
    }


def _experiment_record_kind(cfg: ArenaExperimentConfig) -> dict[str, Any]:
    return {
        "schema": "stock_sim.experiment_record_kind.v1",
        "kind": "arena_experiment_report",
        "primary_stage": "training",
        "task_name": str(cfg.task_name),
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


def _world_card(cfg: ArenaExperimentConfig, *, world_identity: dict[str, Any], world_hash: str) -> dict[str, Any]:
    return {
        "schema": "stock_sim.arena_world_card.v1",
        "world_hash": world_hash,
        "world_identity_schema": world_identity.get("schema"),
        "split": {
            "status": "training_only",
            "reason": "world_pool_split_not_implemented",
        },
        "universe": {
            "symbols": list(world_identity.get("symbols") or []),
            "symbol_count": len(world_identity.get("symbols") or []),
        },
        "retail_profile": {
            "retail_count": int(world_identity.get("retail_count") or 0),
            "retail_initial_cash": float(world_identity.get("retail_initial_cash") or 0.0),
            "family_mix_status": "not_available",
            "family_mix_reason": "retail_family_mix_not_reported",
        },
        "clock": {
            "clock_start_day": str(world_identity.get("clock_start_day")),
            "clock_speed": float(world_identity.get("clock_speed") or 0.0),
            "run_clock": bool(world_identity.get("run_clock")),
        },
        "liquidity_seed": {
            "seed_training_liquidity": bool(world_identity.get("seed_training_liquidity")),
            "liquidity_account_id": str(world_identity.get("liquidity_account_id")),
            "liquidity_order_qty": int(world_identity.get("liquidity_order_qty") or 0),
            "liquidity_spread_ticks": int(world_identity.get("liquidity_spread_ticks") or 0),
        },
        "calibration": {
            "status": "not_available",
            "reason": "calibration_harness_not_implemented",
            "score": None,
            "score_status": "not_available",
            "score_reason": "calibration_harness_not_implemented",
            "metrics": {},
            "missing_metrics": [
                "return_distribution_shape",
                "volatility_clustering_proxy",
                "bid_ask_spread",
                "depth",
                "volume_turnover",
                "order_arrival_cancel_fill_behavior",
            ],
        },
    }


def _random_seed_identity() -> dict[str, Any]:
    return {
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


def _sim_version_identity() -> dict[str, Any]:
    version = str(STOCK_SIM_VERSION or "").strip()
    if not version:
        return {
            "schema": "stock_sim.sim_version_identity.v1",
            "status": "not_available",
            "reason": "stock_sim_version_unavailable",
        }
    return {
        "schema": "stock_sim.sim_version_identity.v1",
        "status": "available",
        "source": "stock_sim.__version__",
        "sim_version": version,
    }


def _git_code_identity(repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or Path(__file__).resolve().parents[2]
    head = _run_git(root, "rev-parse", "HEAD")
    if not head:
        return {
            "schema": "stock_sim.git_code_identity.v1",
            "status": "not_available",
            "reason": "git_head_unavailable",
        }
    branch = _run_git(root, "rev-parse", "--abbrev-ref", "HEAD") or "unknown"
    status_text = _run_git(root, "status", "--porcelain") or ""
    status_lines = [line for line in status_text.splitlines() if line.strip()]
    hash_source = {
        "schema": "stock_sim.git_code_hash_source.v1",
        "head": head,
        "branch": branch,
        "is_dirty": bool(status_lines),
        "status_entry_count": len(status_lines),
        "status_porcelain_hash": _canonical_sha256(status_lines),
    }
    return {
        "schema": "stock_sim.git_code_identity.v1",
        "status": "available",
        "method": "git_head_plus_status_sha256_v1",
        "head": head,
        "branch": branch,
        "is_dirty": bool(status_lines),
        "status_entry_count": len(status_lines),
        "status_porcelain_hash": hash_source["status_porcelain_hash"],
        "code_hash": _canonical_sha256(hash_source),
    }


def _run_git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _result_to_dict(row: Any) -> dict[str, Any]:
    metrics = _json_loads(row.metrics_json) or {}
    baseline_kind = _baseline_kind(row.model_id)
    return {
        "agent_id": row.agent_id,
        "model_id": row.model_id,
        "result_role": "baseline" if baseline_kind else "candidate",
        "baseline_kind": baseline_kind,
        "generation": row.generation,
        "rank": row.rank,
        "score": row.score,
        "equity_start": row.equity_start,
        "equity_end": row.equity_end,
        "equity_return": row.equity_return,
        "max_drawdown": row.max_drawdown,
        "turnover": row.turnover,
        "fee_total": row.fee_total,
        "trade_count": row.trade_count,
        "reward_total": row.reward_total,
        "execution_health": _execution_health_from_metrics(metrics),
        "metrics": metrics,
    }


def _execution_health_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_agent = {
        str(row.get("agent_id")): row.get("execution_health") or {}
        for row in results
        if row.get("agent_id")
    }
    totals = {
        "submitted_order_count": 0,
        "filled_order_count": 0,
        "open_order_count": 0,
        "rejected_order_count": 0,
        "trade_count": 0,
        "submitted_notional": 0.0,
        "filled_notional": 0.0,
        "open_order_notional": 0.0,
    }
    for health in by_agent.values():
        for key in ("submitted_order_count", "filled_order_count", "open_order_count", "rejected_order_count", "trade_count"):
            totals[key] += int(health.get(key, 0) or 0)
        for key in ("submitted_notional", "filled_notional", "open_order_notional"):
            totals[key] += float(health.get(key, 0.0) or 0.0)
    totals["fill_ratio"] = (
        totals["filled_order_count"] / totals["submitted_order_count"]
        if totals["submitted_order_count"] > 0
        else 0.0
    )
    totals["notional_fill_ratio"] = (
        totals["filled_notional"] / totals["submitted_notional"]
        if totals["submitted_notional"] > 0
        else 0.0
    )
    return {"totals": totals, "by_agent": by_agent}


def _report_research_sections(
    results: list[dict[str, Any]],
    cfg: ArenaExperimentConfig,
    *,
    episode_id: str | None = None,
    runtime_observation_audit: dict[str, Any] | None = None,
    fee_sensitivity: dict[str, Any] | None = None,
    fee_accounting_audit: dict[str, Any] | None = None,
    impact_sensitivity: dict[str, Any] | None = None,
    timestamp_audit: dict[str, Any] | None = None,
    mark_to_market_audit: dict[str, Any] | None = None,
    order_anomaly_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    baseline_suite = _baseline_suite(results, task_name=cfg.task_name)
    benchmark_comparison = _benchmark_comparison(results)
    hidden_evaluation = _hidden_evaluation_placeholder()
    no_signal_check = cfg.no_signal_check
    if no_signal_check is None:
        no_signal_check = _derive_no_signal_check_payload(
            results,
            cfg,
            episode_id=episode_id,
            runtime_observation_audit=runtime_observation_audit,
        )
    exploit_detector = _exploit_detector_report(
        no_signal_check,
        fee_sensitivity=fee_sensitivity,
        fee_accounting_audit=fee_accounting_audit,
        impact_sensitivity=impact_sensitivity,
        timestamp_audit=timestamp_audit,
        mark_to_market_audit=mark_to_market_audit,
        order_anomaly_audit=order_anomaly_audit,
    )
    research_acceptance = _research_acceptance(
        baseline_suite,
        hidden_evaluation=hidden_evaluation,
        exploit_detector=exploit_detector,
    )
    return {
        "baseline_suite": baseline_suite,
        "benchmark_comparison": benchmark_comparison,
        "hidden_evaluation": hidden_evaluation,
        "exploit_detector": exploit_detector,
        "research_acceptance": research_acceptance,
    }


def _baseline_kind(model_id: Any) -> str | None:
    mapping = {
        "hold_model_v1": "no_trade_cash",
        "random_weight_v1": "random_constrained",
        "target_weight_naive_rebalance_v1": "target_weight_naive_rebalance",
        "twap_execution_v1": "twap",
        "vwap_execution_v1": "vwap",
        "ac_lite_execution_v1": "ac_lite",
    }
    return mapping.get(str(model_id or "").strip())


def _baseline_suite(results: list[dict[str, Any]], *, task_name: str) -> dict[str, Any]:
    required = ["no_trade_cash", "random_constrained", "target_weight_naive_rebalance"]
    optional = ["twap", "vwap"]
    present = sorted(
        {
            str(row.get("baseline_kind"))
            for row in results
            if row.get("result_role") == "baseline" and row.get("baseline_kind")
        }
    )
    present_set = set(present)
    missing_required = [item for item in required if item not in present_set]
    return {
        "task_name": str(task_name or "alpha_to_execution.v1"),
        "status": "complete" if not missing_required else "incomplete",
        "present_kinds": present,
        "missing_required": missing_required,
        "required": [
            {
                "kind": item,
                "status": "present" if item in present_set else "missing",
            }
            for item in required
        ],
        "optional": [
            _optional_execution_baseline_slot(item, present=item in present_set)
            for item in optional
        ],
    }


def _optional_execution_baseline_slot(kind: str, *, present: bool) -> dict[str, Any]:
    slot = {
        "kind": kind,
        "status": "present" if present else "not_available",
        "required_inputs": [
            "arrival_price",
            "target_quantity_or_notional",
            "horizon_steps_or_seconds",
            "realized_fill_price",
            "benchmark_fill_price",
        ],
    }
    if not present:
        slot["reason"] = "schedule_execution_not_implemented"
    return slot


def _benchmark_comparison(results: list[dict[str, Any]]) -> dict[str, Any]:
    baselines: dict[str, dict[str, Any]] = {}
    for row in results:
        kind = row.get("baseline_kind")
        if row.get("result_role") == "baseline" and kind and kind not in baselines:
            baselines[str(kind)] = row
    comparisons: dict[str, dict[str, Any]] = {}
    for row in results:
        if row.get("result_role") != "candidate":
            continue
        key = str(row.get("agent_id") or row.get("model_id") or "")
        if not key:
            continue
        comparisons[key] = {
            kind: _excess_metrics(row, baseline)
            for kind, baseline in baselines.items()
        }
    return {
        "status": "available" if baselines else "missing_baselines",
        "baseline_kinds": sorted(baselines),
        "comparisons": comparisons,
    }


def _derive_no_signal_check_payload(
    results: list[dict[str, Any]],
    cfg: ArenaExperimentConfig,
    *,
    episode_id: str | None = None,
    runtime_observation_audit: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if str(cfg.task_name or "").strip() != "alpha_to_execution.no_signal.v1":
        return None
    candidates = [row for row in results if row.get("result_role") == "candidate"]
    if not candidates:
        return None

    candidate = max(candidates, key=lambda row: _optional_float(row.get("score"), default=0.0) or 0.0)
    no_trade = next(
        (
            row
            for row in results
            if row.get("result_role") == "baseline" and row.get("baseline_kind") == "no_trade_cash"
        ),
        None,
    )
    reward_total = _optional_float(candidate.get("reward_total"), default=0.0) or 0.0
    fee_total = _optional_float(candidate.get("fee_total"), default=0.0) or 0.0
    payload: dict[str, Any] = {
        "alpha_signal_source": "no_signal",
        "direction": 0.0,
        "confidence": 0.0,
        "target_weight_hint": None,
        "no_signal_tolerance": float(cfg.no_signal_tolerance or 0.0),
        "fee_model": cfg.no_signal_fee_model or cfg.reward_profile,
        "world_seed_or_hash": str(episode_id or cfg.episode_id or cfg.arena_id or f"generation-{int(cfg.generation)}"),
        "net_reward_after_fees": reward_total - fee_total,
        "payload_source": "episode_result_derived",
        "candidate_agent_id": candidate.get("agent_id"),
        "candidate_model_id": candidate.get("model_id"),
    }
    if no_trade is not None:
        payload["excess_score_vs_no_trade_cash"] = _diff(candidate.get("score"), no_trade.get("score"))
    if cfg.no_signal_observation_audit_status is not None:
        payload["observation_audit_status"] = cfg.no_signal_observation_audit_status
    elif runtime_observation_audit and runtime_observation_audit.get("status") in {"pass", "warn", "fail"}:
        payload["observation_audit_status"] = runtime_observation_audit.get("status")
        payload["runtime_observation_audit"] = runtime_observation_audit
    return payload


def _runtime_observation_audit(transitions: list[Any], *, task_name: str) -> dict[str, Any]:
    task = str(task_name or "alpha_to_execution.v1")
    if not transitions:
        return {
            "status": "not_available",
            "reason": "no_model_transitions",
            "task_name": task,
            "transition_count": 0,
            "checked_transition_count": 0,
            "violations": [],
            "samples": [],
        }

    violations: list[str] = []
    samples: list[dict[str, Any]] = []
    checked = 0
    for row in transitions:
        checked += 1
        observation = _json_loads(getattr(row, "observation_json", None))
        row_violations = _audit_observation_payload(observation)
        if row_violations:
            for violation in row_violations:
                violations.append(violation)
            if len(samples) < 5:
                samples.append(
                    {
                        "agent_id": getattr(row, "agent_id", None),
                        "step_index": getattr(row, "step_index", None),
                        "violations": row_violations,
                    }
                )
    unique_violations = sorted(set(violations))
    if unique_violations:
        status = "fail"
        reason = "runtime_observation_contract_violation"
    else:
        status = "pass"
        reason = "runtime_observation_contract_passed"
    return {
        "status": status,
        "reason": reason,
        "task_name": task,
        "scope": "persisted_model_transition_observation_json",
        "transition_count": len(transitions),
        "checked_transition_count": checked,
        "violations": unique_violations,
        "samples": samples,
    }


def _timestamp_audit(transitions: list[Any]) -> dict[str, Any]:
    if not transitions:
        return {
            "name": "timestamp_audit",
            "status": "not_available",
            "reason": "no_model_transitions",
            "scope": "model_transition_step_index",
            "transition_count": 0,
            "agent_count": 0,
            "violations": [],
            "samples": [],
        }

    by_agent: dict[str, list[Any]] = {}
    for row in transitions:
        agent_id = str(getattr(row, "agent_id", None) or "UNKNOWN")
        by_agent.setdefault(agent_id, []).append(row)

    violations: list[str] = []
    samples: list[dict[str, Any]] = []
    for agent_id, rows in sorted(by_agent.items()):
        seen: set[int] = set()
        previous_step: int | None = None
        ordered = sorted(rows, key=lambda row: (getattr(row, "id", 0) or 0))
        for row in ordered:
            raw_step = getattr(row, "step_index", None)
            try:
                step = int(raw_step)
            except Exception:
                _timestamp_violation(
                    violations,
                    samples,
                    "step_index_not_integer",
                    agent_id=agent_id,
                    row=row,
                    step_index=raw_step,
                )
                continue
            if step < 0:
                _timestamp_violation(
                    violations,
                    samples,
                    "step_index_negative",
                    agent_id=agent_id,
                    row=row,
                    step_index=step,
                )
            if step in seen:
                _timestamp_violation(
                    violations,
                    samples,
                    "step_index_duplicate",
                    agent_id=agent_id,
                    row=row,
                    step_index=step,
                )
            seen.add(step)
            if previous_step is not None and step < previous_step:
                _timestamp_violation(
                    violations,
                    samples,
                    "step_index_regressed",
                    agent_id=agent_id,
                    row=row,
                    step_index=step,
                    previous_step_index=previous_step,
                )
            previous_step = step

    unique_violations = sorted(set(violations))
    if unique_violations:
        status = "fail"
        reason = "transition_step_index_violation"
    else:
        status = "pass"
        reason = "transition_step_index_order_passed"
    return {
        "name": "timestamp_audit",
        "status": status,
        "reason": reason,
        "scope": "model_transition_step_index",
        "transition_count": len(transitions),
        "agent_count": len(by_agent),
        "violations": unique_violations,
        "samples": samples,
    }


def _timestamp_violation(
    violations: list[str],
    samples: list[dict[str, Any]],
    violation: str,
    *,
    agent_id: str,
    row: Any,
    step_index: Any,
    previous_step_index: int | None = None,
) -> None:
    violations.append(violation)
    if len(samples) >= 5:
        return
    sample = {
        "agent_id": agent_id,
        "transition_id": getattr(row, "id", None),
        "step_index": step_index,
        "violation": violation,
    }
    if previous_step_index is not None:
        sample["previous_step_index"] = previous_step_index
    samples.append(sample)


def _mark_to_market_audit(results: list[dict[str, Any]], transitions: list[Any]) -> dict[str, Any]:
    if not results:
        return {
            "name": "mark_to_market_audit",
            "status": "not_available",
            "reason": "no_episode_results",
            "scope": "model_episode_result_accounting",
            "result_count": 0,
            "checked_result_count": 0,
            "violations": [],
            "samples": [],
        }

    transition_rewards = _transition_reward_totals(transitions)
    violations: list[str] = []
    samples: list[dict[str, Any]] = []
    checked = 0
    for row in results:
        checked += 1
        agent_id = str(row.get("agent_id") or "")
        row_violations: list[str] = []
        equity_start = _optional_float(row.get("equity_start"))
        equity_end = _optional_float(row.get("equity_end"))
        equity_return = _optional_float(row.get("equity_return"))
        max_drawdown = _optional_float(row.get("max_drawdown"), default=0.0) or 0.0
        reward_total = _optional_float(row.get("reward_total"))
        fee_total = _optional_float(row.get("fee_total"), default=0.0)
        score = _optional_float(row.get("score"))

        if equity_start is None:
            row_violations.append("missing_equity_start")
        elif equity_start <= 0:
            row_violations.append("equity_start_not_positive")
        if equity_end is None:
            row_violations.append("missing_equity_end")
        if reward_total is None:
            row_violations.append("missing_reward_total")
        if fee_total is None:
            row_violations.append("missing_fee_total")
        elif fee_total < 0:
            row_violations.append("fee_total_negative")
        if max_drawdown < 0:
            row_violations.append("max_drawdown_negative")
        if equity_start and equity_start > 0 and equity_end is not None and equity_return is not None:
            expected_return = (equity_end - equity_start) / equity_start
            if abs(equity_return - expected_return) > 1e-9:
                row_violations.append("equity_return_mismatch")
        if score is not None and reward_total is not None and equity_start and equity_start > 0 and equity_end is not None:
            expected_score = ((equity_end - equity_start) / equity_start) + reward_total - max_drawdown
            if abs(score - expected_score) > 1e-9:
                row_violations.append("score_mismatch")
        if agent_id in transition_rewards and reward_total is not None:
            transition_reward = transition_rewards[agent_id]
            if abs(reward_total - transition_reward) > 1e-9:
                row_violations.append("reward_total_transition_sum_mismatch")

        if row_violations:
            violations.extend(row_violations)
            if len(samples) < 5:
                samples.append(
                    {
                        "agent_id": agent_id,
                        "model_id": row.get("model_id"),
                        "violations": sorted(set(row_violations)),
                    }
                )

    unique_violations = sorted(set(violations))
    if unique_violations:
        status = "fail"
        reason = "episode_result_accounting_violation"
    else:
        status = "pass"
        reason = "episode_result_accounting_passed"
    return {
        "name": "mark_to_market_audit",
        "status": status,
        "reason": reason,
        "scope": "model_episode_result_accounting",
        "result_count": len(results),
        "checked_result_count": checked,
        "transition_reward_agent_count": len(transition_rewards),
        "violations": unique_violations,
        "samples": samples,
    }


def _fee_accounting_audit(results: list[dict[str, Any]], transitions: list[Any]) -> dict[str, Any]:
    if not results:
        return {
            "name": "fee_accounting_audit",
            "status": "not_available",
            "reason": "no_episode_results",
            "scope": "model_episode_result_fee_accounting",
            "result_count": 0,
            "checked_result_count": 0,
            "transition_count": len(transitions),
            "checked_transition_count": 0,
            "fee_ledger_consistent": None,
            "fee_ledger_mismatch_abs": None,
            "violations": [],
            "samples": [],
        }
    if not transitions:
        return {
            "name": "fee_accounting_audit",
            "status": "not_available",
            "reason": "no_model_transitions",
            "scope": "model_episode_result_fee_accounting",
            "result_count": len(results),
            "checked_result_count": 0,
            "transition_count": 0,
            "checked_transition_count": 0,
            "fee_ledger_consistent": None,
            "fee_ledger_mismatch_abs": None,
            "violations": [],
            "samples": [],
        }

    transition_fees = _transition_fee_totals(transitions)
    violations: list[str] = []
    samples: list[dict[str, Any]] = []
    checked = 0
    max_mismatch = 0.0
    for row in results:
        agent_id = str(row.get("agent_id") or "")
        if not agent_id:
            continue
        result_fee = _optional_float(row.get("fee_total"))
        if result_fee is None:
            violations.append("missing_fee_total")
            if len(samples) < 5:
                samples.append({"agent_id": agent_id, "violation": "missing_fee_total"})
            continue
        checked += 1
        transition_fee = float(transition_fees.get(agent_id, 0.0) or 0.0)
        mismatch = abs(float(result_fee) - transition_fee)
        max_mismatch = max(max_mismatch, mismatch)
        if mismatch > 1e-9:
            violations.append("fee_total_transition_sum_mismatch")
            if len(samples) < 5:
                samples.append(
                    {
                        "agent_id": agent_id,
                        "model_id": row.get("model_id"),
                        "result_fee_total": float(result_fee),
                        "transition_fee_total": transition_fee,
                        "mismatch_abs": mismatch,
                        "violation": "fee_total_transition_sum_mismatch",
                    }
                )

    unique_violations = sorted(set(violations))
    status = "fail" if unique_violations else "pass"
    return {
        "name": "fee_accounting_audit",
        "status": status,
        "reason": "fee_accounting_violation" if unique_violations else "fee_accounting_passed",
        "scope": "model_episode_result_fee_accounting",
        "result_count": len(results),
        "checked_result_count": checked,
        "transition_count": len(transitions),
        "checked_transition_count": len(transitions),
        "transition_fee_agent_count": len(transition_fees),
        "fee_ledger_consistent": not unique_violations,
        "fee_ledger_mismatch_abs": max_mismatch,
        "violations": unique_violations,
        "samples": samples,
    }


def _transition_reward_totals(transitions: list[Any]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in transitions:
        agent_id = str(getattr(row, "agent_id", None) or "")
        if not agent_id:
            continue
        reward = _json_loads(getattr(row, "reward_json", None)) or {}
        totals[agent_id] = totals.get(agent_id, 0.0) + float((reward or {}).get("step_reward") or 0.0)
    return totals


def _transition_fee_totals(transitions: list[Any]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in transitions:
        agent_id = str(getattr(row, "agent_id", None) or "")
        if not agent_id:
            continue
        execution = _json_loads(getattr(row, "execution_json", None)) or {}
        totals[agent_id] = totals.get(agent_id, 0.0) + _fee_total_from_execution_payload(execution)
    return totals


def _fee_total_from_execution_payload(execution: Any) -> float:
    if not isinstance(execution, dict):
        return 0.0
    total = _optional_float(execution.get("fee_total"), default=0.0) or 0.0
    for trade in execution.get("trades") or []:
        if isinstance(trade, dict):
            total += _optional_float(trade.get("fee") if trade.get("fee") is not None else trade.get("fees"), default=0.0) or 0.0
    for order in execution.get("orders") or []:
        if not isinstance(order, dict):
            continue
        result = order.get("result") if isinstance(order.get("result"), dict) else {}
        for trade in result.get("trades") or []:
            if isinstance(trade, dict):
                total += _optional_float(trade.get("fee") if trade.get("fee") is not None else trade.get("fees"), default=0.0) or 0.0
    return float(total)


def _order_anomaly_audit(results: list[dict[str, Any]], transitions: list[Any]) -> dict[str, Any]:
    if not transitions:
        return {
            "name": "order_anomaly_audit",
            "status": "not_available",
            "reason": "no_model_transitions",
            "scope": "model_transition_execution_json",
            "transition_count": 0,
            "checked_transition_count": 0,
            "violations": [],
            "samples": [],
        }

    transition_health: dict[str, dict[str, float | int]] = {}
    violations: list[str] = []
    samples: list[dict[str, Any]] = []
    checked = 0
    for row in transitions:
        checked += 1
        agent_id = str(getattr(row, "agent_id", None) or "")
        execution = _json_loads(getattr(row, "execution_json", None)) or {}
        health, row_violations = _execution_health_from_execution_payload(execution)
        if agent_id:
            current = transition_health.setdefault(agent_id, _empty_execution_health())
            _add_execution_health(current, health)
        if row_violations:
            violations.extend(row_violations)
            if len(samples) < 5:
                samples.append(
                    {
                        "agent_id": agent_id,
                        "step_index": getattr(row, "step_index", None),
                        "violations": sorted(set(row_violations)),
                    }
                )

    for result in results:
        agent_id = str(result.get("agent_id") or "")
        if not agent_id or agent_id not in transition_health:
            continue
        expected = transition_health[agent_id]
        actual = result.get("execution_health") or {}
        for key in ("submitted_order_count", "filled_order_count", "open_order_count", "rejected_order_count", "trade_count"):
            if int(actual.get(key, 0) or 0) != int(expected.get(key, 0) or 0):
                violation = f"result_execution_health_mismatch:{key}"
                violations.append(violation)
                if len(samples) < 5:
                    samples.append(
                        {
                            "agent_id": agent_id,
                            "violation": violation,
                            "expected": int(expected.get(key, 0) or 0),
                            "actual": int(actual.get(key, 0) or 0),
                        }
                    )
        for key in ("submitted_notional", "filled_notional", "open_order_notional"):
            if abs(float(actual.get(key, 0.0) or 0.0) - float(expected.get(key, 0.0) or 0.0)) > 1e-9:
                violation = f"result_execution_health_mismatch:{key}"
                violations.append(violation)
                if len(samples) < 5:
                    samples.append(
                        {
                            "agent_id": agent_id,
                            "violation": violation,
                            "expected": float(expected.get(key, 0.0) or 0.0),
                            "actual": float(actual.get(key, 0.0) or 0.0),
                        }
                    )

    unique_violations = sorted(set(violations))
    if unique_violations:
        status = "fail"
        reason = "order_execution_health_violation"
    else:
        status = "pass"
        reason = "order_execution_health_passed"
    return {
        "name": "order_anomaly_audit",
        "status": status,
        "reason": reason,
        "scope": "model_transition_execution_json",
        "transition_count": len(transitions),
        "checked_transition_count": checked,
        "agent_count": len(transition_health),
        "violations": unique_violations,
        "samples": samples,
    }


def _execution_health_from_execution_payload(execution: Any) -> tuple[dict[str, float | int], list[str]]:
    health = _empty_execution_health()
    violations: list[str] = []
    if not isinstance(execution, dict):
        violations.append("execution_not_object")
        return health, violations
    orders = execution.get("orders") or []
    trades = execution.get("trades") or []
    if not isinstance(orders, list):
        violations.append("orders_not_list")
        orders = []
    if not isinstance(trades, list):
        violations.append("trades_not_list")
        trades = []
    health["trade_count"] = len([item for item in trades if isinstance(item, dict)])
    top_level_filled_notional = 0.0
    for trade in trades:
        if isinstance(trade, dict):
            trade_qty = _optional_float(trade.get("qty") if trade.get("qty") is not None else trade.get("quantity"), default=0.0) or 0.0
            trade_price = _optional_float(trade.get("price"), default=0.0) or 0.0
            if trade_qty < 0:
                violations.append("trade_qty_negative")
            if trade_price < 0:
                violations.append("trade_price_negative")
            top_level_filled_notional += abs(trade_qty * trade_price)
    submitted_notional = 0.0
    filled_notional = top_level_filled_notional
    has_top_level_fill = top_level_filled_notional > 0
    for order in orders:
        if not isinstance(order, dict):
            violations.append("order_not_object")
            continue
        health["submitted_order_count"] = int(health["submitted_order_count"]) + 1
        qty = _optional_float(order.get("qty") if order.get("qty") is not None else order.get("quantity"), default=0.0) or 0.0
        price = _optional_float(order.get("price"), default=0.0) or 0.0
        if qty < 0:
            violations.append("order_qty_negative")
        if price < 0:
            violations.append("order_price_negative")
        submitted_notional += abs(qty * price)
        result = order.get("result") if isinstance(order.get("result"), dict) else {}
        status = str(result.get("status") or order.get("status") or "").upper()
        ok = result.get("ok", order.get("ok", True))
        filled_qty = _optional_float(result.get("filled") if result.get("filled") is not None else order.get("filled"), default=0.0) or 0.0
        nested_trades = result.get("trades") if isinstance(result.get("trades"), list) else []
        if filled_qty < 0:
            violations.append("filled_qty_negative")
        order_filled_notional = abs(filled_qty * price)
        for trade in nested_trades:
            if isinstance(trade, dict):
                trade_qty = _optional_float(trade.get("qty") if trade.get("qty") is not None else trade.get("quantity"), default=0.0) or 0.0
                trade_price = _optional_float(trade.get("price"), default=price) or 0.0
                order_filled_notional += abs(trade_qty * trade_price)
        if not has_top_level_fill:
            filled_notional += order_filled_notional
        has_fill = filled_qty > 0 or bool(nested_trades)
        if ok is False or status == "REJECTED":
            health["rejected_order_count"] = int(health["rejected_order_count"]) + 1
        if has_fill:
            health["filled_order_count"] = int(health["filled_order_count"]) + 1
        if ok and status not in {"FILLED", "REJECTED", "CANCELLED"} and not has_fill:
            health["open_order_count"] = int(health["open_order_count"]) + 1
    if int(health["filled_order_count"]) + int(health["open_order_count"]) + int(health["rejected_order_count"]) > int(health["submitted_order_count"]):
        violations.append("order_status_counts_exceed_submitted")
    health["submitted_notional"] = submitted_notional
    health["filled_notional"] = filled_notional
    health["open_order_notional"] = max(0.0, submitted_notional - filled_notional)
    return health, sorted(set(violations))


def _empty_execution_health() -> dict[str, float | int]:
    return {
        "submitted_order_count": 0,
        "filled_order_count": 0,
        "open_order_count": 0,
        "rejected_order_count": 0,
        "trade_count": 0,
        "submitted_notional": 0.0,
        "filled_notional": 0.0,
        "open_order_notional": 0.0,
    }


def _add_execution_health(left: dict[str, float | int], right: dict[str, float | int]) -> None:
    for key in ("submitted_order_count", "filled_order_count", "open_order_count", "rejected_order_count", "trade_count"):
        left[key] = int(left.get(key, 0) or 0) + int(right.get(key, 0) or 0)
    for key in ("submitted_notional", "filled_notional", "open_order_notional"):
        left[key] = float(left.get(key, 0.0) or 0.0) + float(right.get(key, 0.0) or 0.0)


def _fee_sensitivity_report() -> dict[str, Any]:
    return {
        "name": "fee_sensitivity",
        "status": "not_available",
        "reason": "fee_variant_worlds_not_implemented",
        "scope": "scenario_comparison",
        "required_inputs": [
            "base_fee_model",
            "altered_fee_model",
            "same_policy_episode_result",
            "same_seed_or_world_hash",
            "base_net_reward_after_fees",
            "altered_net_reward_after_fees",
            "base_fill_and_turnover_metrics",
            "altered_fill_and_turnover_metrics",
        ],
    }


def _impact_sensitivity_report() -> dict[str, Any]:
    return {
        "name": "impact_sensitivity",
        "status": "not_available",
        "reason": "liquidity_depth_variant_worlds_not_implemented",
        "scope": "scenario_comparison",
        "required_inputs": [
            "base_liquidity_depth_or_impact_model",
            "altered_liquidity_depth_or_impact_model",
            "same_policy_episode_result",
            "same_seed_or_world_hash",
            "base_slippage_or_fill_price_metrics",
            "altered_slippage_or_fill_price_metrics",
            "base_fill_and_turnover_metrics",
            "altered_fill_and_turnover_metrics",
        ],
    }


def _audit_observation_payload(observation: Any) -> list[str]:
    if not isinstance(observation, dict):
        return ["observation_not_object"]

    violations: list[str] = []
    if observation.get("contract_version") != "obs.v1":
        violations.append("contract_version_not_obs_v1")
    required_sections = ["market", "account", "context", "features"]
    for section in required_sections:
        if section not in observation:
            violations.append(f"missing_section:{section}")
        elif not isinstance(observation.get(section), dict):
            violations.append(f"section_not_object:{section}")
    allowed_top = {"contract_version", *required_sections}
    for key in sorted(set(observation) - allowed_top):
        violations.append(f"unexpected_top_level_key:{key}")

    for path in _flatten_observation_paths(observation):
        lowered = path.lower()
        for pattern in _disallowed_observation_key_patterns():
            if pattern in lowered:
                violations.append(f"disallowed_field:{path}")
                break
    return sorted(set(violations))


def _flatten_observation_paths(value: Any, *, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.append(path)
            paths.extend(_flatten_observation_paths(child, prefix=path))
    elif isinstance(value, list):
        for index, child in enumerate(value[:10]):
            path = f"{prefix}[{index}]"
            paths.extend(_flatten_observation_paths(child, prefix=path))
    return paths


def _disallowed_observation_key_patterns() -> list[str]:
    return [
        "panel",
        "widget",
        "selected_row",
        "adapter_render",
        "render_detail",
        "final_rank",
        "final_score",
        "future_bar",
        "future_trade",
        "next_snapshot",
        "post_decision_fill",
        "post_trade",
        "hidden_split",
        "split_label",
        "database_only",
        "db_only",
        "private_future_action",
    ]


def _hidden_evaluation_placeholder() -> dict[str, Any]:
    return {
        "status": "not_available",
        "reason": "hidden_world_runner_not_implemented",
        "split": "hidden",
        "required_inputs": [
            "unseen_seed",
            "unseen_retail_mix",
            "altered_fees",
            "altered_liquidity_depth",
            "altered_tick_or_spread_regime",
        ],
        "checks": [
            {
                "name": "frozen_policy_hidden_seed",
                "status": "not_available",
                "reason": "hidden_world_runner_not_implemented",
                "required_inputs": [
                    "frozen_policy_checkpoint",
                    "unseen_seed",
                    "same_policy_episode_result",
                    "hidden_world_episode_result",
                    "base_world_hash",
                    "hidden_world_hash",
                ],
            },
            {
                "name": "cross_world_transfer",
                "status": "not_available",
                "reason": "paired_world_runner_not_implemented",
                "required_inputs": [
                    "source_world_result",
                    "target_world_result",
                    "same_policy_checkpoint",
                    "source_world_hash",
                    "target_world_hash",
                    "transfer_metric_threshold",
                ],
            },
        ],
    }


def _exploit_detector_placeholder() -> dict[str, Any]:
    return _exploit_detector_report(
        None,
        fee_sensitivity=None,
        fee_accounting_audit=None,
        impact_sensitivity=None,
        timestamp_audit=None,
        mark_to_market_audit=None,
        order_anomaly_audit=None,
    )


def _exploit_detector_report(
    no_signal_check: dict[str, Any] | None,
    *,
    fee_sensitivity: dict[str, Any] | None,
    fee_accounting_audit: dict[str, Any] | None,
    impact_sensitivity: dict[str, Any] | None,
    timestamp_audit: dict[str, Any] | None,
    mark_to_market_audit: dict[str, Any] | None,
    order_anomaly_audit: dict[str, Any] | None,
) -> dict[str, Any]:
    fee_check = fee_sensitivity or _check_placeholder("fee_sensitivity")
    fee_accounting_check = fee_accounting_audit or _check_placeholder("fee_accounting_audit")
    impact_check = impact_sensitivity or _check_placeholder("impact_sensitivity")
    timestamp_check = timestamp_audit or _check_placeholder("timestamp_audit")
    mark_to_market_check = mark_to_market_audit or _check_placeholder("mark_to_market_audit")
    order_anomaly_check = order_anomaly_audit or _check_placeholder("order_anomaly_audit")
    active_audits = [
        item
        for item in (
            fee_accounting_audit,
            fee_sensitivity,
            impact_sensitivity,
            timestamp_audit,
            mark_to_market_audit,
            order_anomaly_audit,
        )
        if item is not None
    ]
    implemented_audit_names = [str(item.get("name")) for item in active_audits if item.get("name")]
    audit_failed = any(item.get("status") == "fail" for item in active_audits)
    if no_signal_check is None:
        status = "not_implemented" if not active_audits else ("failed" if audit_failed else "partial")
        return {
            "status": status,
            "implemented_checks": implemented_audit_names,
            "placeholder_checks": [
                "no_signal_world",
            ] if active_audits else [],
            "checks": [
                _check_placeholder(
                    "no_signal_world",
                    required_inputs=_no_signal_required_inputs(),
                ),
                fee_accounting_check,
                fee_check,
                impact_check,
                timestamp_check,
                mark_to_market_check,
                order_anomaly_check,
            ],
        }

    no_signal = _no_signal_world_check(no_signal_check)
    status = "failed" if no_signal.get("status") == "fail" or audit_failed else "partial"
    implemented_checks = ["no_signal_world"]
    implemented_checks.extend(implemented_audit_names)
    return {
        "status": status,
        "implemented_checks": implemented_checks,
        "placeholder_checks": [
        ],
        "checks": [
            no_signal,
            fee_accounting_check,
            fee_check,
            impact_check,
            timestamp_check,
            mark_to_market_check,
            order_anomaly_check,
        ],
    }


def _no_signal_required_inputs() -> list[str]:
    return [
        "alpha_signal_source",
        "direction",
        "confidence",
        "target_weight_hint",
        "no_signal_tolerance",
        "fee_model",
        "world_seed_or_hash",
        "observation_audit_status",
    ]


def _no_signal_world_check(payload: dict[str, Any]) -> dict[str, Any]:
    payload = _with_no_signal_observation_audit(payload)
    required_inputs = _no_signal_required_inputs()
    metric_inputs = ["net_reward_after_fees", "excess_score_vs_no_trade_cash"]
    missing_required = [key for key in required_inputs if key not in payload]
    missing_metrics = [key for key in metric_inputs if key not in payload]
    tolerance = _optional_float(payload.get("no_signal_tolerance"), default=0.0)
    net_reward = _optional_float(payload.get("net_reward_after_fees"))
    excess_score = _optional_float(payload.get("excess_score_vs_no_trade_cash"))
    failures: list[str] = []

    if "alpha_signal_source" in payload and str(payload.get("alpha_signal_source") or "").strip() != "no_signal":
        failures.append("alpha_signal_source_not_no_signal")
    if "direction" in payload and _optional_float(payload.get("direction")) != 0.0:
        failures.append("direction_not_zero")
    if "confidence" in payload and _optional_float(payload.get("confidence")) != 0.0:
        failures.append("confidence_not_zero")
    if "target_weight_hint" in payload and payload.get("target_weight_hint") is not None:
        failures.append("target_weight_hint_not_null")
    audit_status = str(payload.get("observation_audit_status") or "").strip().lower()
    if "observation_audit_status" in payload and audit_status not in {"pass", "passed", "ok", "warn", "warning"}:
        failures.append("observation_audit_not_passed")
    if net_reward is not None and net_reward > tolerance:
        failures.append("net_reward_after_fees_above_tolerance")
    if excess_score is not None and excess_score > tolerance:
        failures.append("excess_score_vs_no_trade_cash_above_tolerance")

    if failures:
        status = "fail"
        reason = "failed_no_signal_contract"
    elif missing_required or missing_metrics:
        status = "warn"
        reason = "missing_inputs"
    else:
        status = "pass"
        reason = "within_no_signal_tolerance"

    return {
        "name": "no_signal_world",
        "status": status,
        "reason": reason,
        "required_inputs": required_inputs,
        "metric_inputs": metric_inputs,
        "missing_required_inputs": missing_required,
        "missing_metric_inputs": missing_metrics,
        "failures": failures,
        "metrics": {
            "no_signal_tolerance": tolerance,
            "net_reward_after_fees": net_reward,
            "excess_score_vs_no_trade_cash": excess_score,
        },
        "inputs": {
            key: payload.get(key)
            for key in required_inputs
            if key in payload
        },
        "source": payload.get("payload_source"),
        "candidate_agent_id": payload.get("candidate_agent_id"),
        "candidate_model_id": payload.get("candidate_model_id"),
        "observation_audit": payload.get("observation_audit"),
        "runtime_observation_audit": payload.get("runtime_observation_audit"),
    }


def _with_no_signal_observation_audit(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    audit = _audit_no_signal_payload(result)
    result["observation_audit"] = audit
    if "observation_audit_status" not in result:
        result["observation_audit_status"] = audit["status"]
    return result


def _audit_no_signal_payload(payload: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    violations: list[str] = []
    if "alpha_signal_source" not in payload:
        missing.append("alpha_signal_source")
    elif str(payload.get("alpha_signal_source") or "").strip() != "no_signal":
        violations.append("alpha_signal_source_not_no_signal")
    if "direction" not in payload:
        missing.append("direction")
    elif _optional_float(payload.get("direction")) != 0.0:
        violations.append("direction_not_zero")
    if "confidence" not in payload:
        missing.append("confidence")
    elif _optional_float(payload.get("confidence")) != 0.0:
        violations.append("confidence_not_zero")
    if "target_weight_hint" not in payload:
        missing.append("target_weight_hint")
    elif payload.get("target_weight_hint") is not None:
        violations.append("target_weight_hint_not_null")

    if violations:
        status = "fail"
        reason = "no_signal_contract_violation"
    elif missing:
        status = "warn"
        reason = "no_signal_contract_incomplete"
    else:
        status = "pass"
        reason = "no_signal_contract_passed"
    return {
        "status": status,
        "reason": reason,
        "scope": "payload_alpha_signal_contract",
        "missing_fields": missing,
        "violations": violations,
    }


def _check_placeholder(name: str, *, required_inputs: list[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "status": "not_implemented",
        "reason": "placeholder_only",
    }
    if required_inputs is not None:
        result["required_inputs"] = list(required_inputs)
    return result


def _research_acceptance(
    baseline_suite: dict[str, Any],
    *,
    hidden_evaluation: dict[str, Any],
    exploit_detector: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    required_sections = {
        "baseline_suite": baseline_suite.get("status"),
        "hidden_evaluation": hidden_evaluation.get("status"),
        "exploit_detector": exploit_detector.get("status"),
    }
    if baseline_suite.get("status") != "complete":
        missing = ", ".join(str(item) for item in baseline_suite.get("missing_required") or [])
        reasons.append(f"missing required baselines: {missing}" if missing else "missing required baselines")
    if hidden_evaluation.get("status") != "complete":
        reasons.append(f"hidden evaluation {hidden_evaluation.get('status', 'missing')}")
    if exploit_detector.get("status") != "complete":
        reasons.append(f"exploit detector {exploit_detector.get('status', 'missing')}")
    lock = _acceptance_lock(required_sections)
    return {
        "status": "incomplete",
        "reasons": reasons,
        "required_sections": required_sections,
        "acceptance_lock": lock,
        "strict_parent_eligibility_allowed": False,
        "is_research_accepted": False,
    }


def _acceptance_lock(required_sections: dict[str, Any]) -> dict[str, Any]:
    blocking_sections = {
        str(name): status
        for name, status in required_sections.items()
        if status != "complete"
    }
    return {
        "status": "locked" if blocking_sections else "open",
        "required_for": ["research_acceptance", "strict_parent_eligibility"],
        "complete_required_sections": ["baseline_suite", "hidden_evaluation", "exploit_detector"],
        "blocking_sections": blocking_sections,
        "strict_parent_eligibility_default": "opt_in_only",
        "reason": "required_sections_not_complete" if blocking_sections else "required_sections_complete",
    }


def _excess_metrics(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, float]:
    return {
        "excess_score": _diff(candidate.get("score"), baseline.get("score")),
        "excess_equity_return": _diff(candidate.get("equity_return"), baseline.get("equity_return")),
        "excess_reward_total": _diff(candidate.get("reward_total"), baseline.get("reward_total")),
        "excess_filled_notional": _diff(
            (candidate.get("execution_health") or {}).get("filled_notional"),
            (baseline.get("execution_health") or {}).get("filled_notional"),
        ),
    }


def _diff(left: Any, right: Any) -> float:
    return float(left or 0.0) - float(right or 0.0)


def _execution_health_from_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "submitted_order_count": int(metrics.get("submitted_order_count", 0) or 0),
        "filled_order_count": int(metrics.get("filled_order_count", 0) or 0),
        "open_order_count": int(metrics.get("open_order_count", 0) or 0),
        "rejected_order_count": int(metrics.get("rejected_order_count", 0) or 0),
        "trade_count": int(metrics.get("trade_count", 0) or 0),
        "submitted_notional": float(metrics.get("submitted_notional", 0.0) or 0.0),
        "filled_notional": float(metrics.get("filled_notional", 0.0) or 0.0),
        "open_order_notional": float(metrics.get("open_order_notional", 0.0) or 0.0),
        "fill_ratio": float(metrics.get("fill_ratio", 0.0) or 0.0),
        "notional_fill_ratio": float(metrics.get("notional_fill_ratio", 0.0) or 0.0),
    }


def _generation_summary(report: dict[str, Any]) -> dict[str, Any]:
    episode = report.get("episode") or {}
    pbt = report.get("pbt") or {}
    results = list(episode.get("results") or [])
    return {
        "generation": (report.get("config") or {}).get("generation"),
        "arena_id": report.get("arena_id"),
        "episode_id": report.get("episode_id"),
        "report_path": report.get("report_path"),
        "model_specs": (report.get("config") or {}).get("model_specs") or [],
        "transition_count": int(episode.get("transition_count") or 0),
        "execution_health": (episode.get("execution_health") or {}).get("totals") or {},
        "experiment_record_completeness": _experiment_record_completeness_summary(report),
        "experiment_record_identity": _experiment_record_identity_summary(report),
        "record_kind": _record_kind_summary(report),
        "world_card": _world_card_summary(report),
        "transition_evidence": _transition_evidence_summary(episode),
        "model_lineage_evidence": _model_lineage_evidence_summary(report),
        "baseline_suite": _baseline_suite_summary(episode.get("baseline_suite")),
        "benchmark_comparison": _benchmark_comparison_summary(episode.get("benchmark_comparison")),
        "hidden_evaluation": _evaluation_section_summary(episode.get("hidden_evaluation")),
        "exploit_detector": _evaluation_section_summary(episode.get("exploit_detector")),
        "audit_summary": _episode_audit_summary(episode),
        "research_acceptance": _research_acceptance_summary(episode.get("research_acceptance")),
        "top_results": [
            {
                "rank": row.get("rank"),
                "agent_id": row.get("agent_id"),
                "model_id": row.get("model_id"),
                "score": row.get("score"),
                "trade_count": row.get("trade_count"),
                "fill_ratio": (row.get("execution_health") or {}).get("fill_ratio"),
            }
            for row in results[:5]
        ],
        "pbt": {
            "winners": list(pbt.get("winners") or []),
            "losers": list(pbt.get("losers") or []),
            "parent_eligible_agents": list(pbt.get("parent_eligible_agents") or []),
            "strict_parent_gate": _strict_parent_gate_summary(pbt.get("strict_parent_gate")),
            "checkpoint_count": len(pbt.get("checkpoints") or []),
            "lineage_count": len(pbt.get("lineage") or []),
            "applied_count": len(pbt.get("applied_agents") or []),
            "skipped": bool(pbt.get("skipped", False)),
            "reason": pbt.get("reason"),
        },
    }


def _experiment_record_completeness_summary(report: dict[str, Any]) -> dict[str, Any]:
    config = report.get("config") if isinstance(report.get("config"), dict) else {}
    episode = report.get("episode") if isinstance(report.get("episode"), dict) else {}
    pbt = report.get("pbt") if isinstance(report.get("pbt"), dict) else {}
    metadata = report.get("experiment_record_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    raw_record_kind = report.get("record_kind") if isinstance(report.get("record_kind"), dict) else metadata.get("record_kind")
    raw_record_kind = raw_record_kind if isinstance(raw_record_kind, dict) else {}
    raw_code_identity = (
        report.get("code_identity")
        if isinstance(report.get("code_identity"), dict)
        else metadata.get("code_identity")
    )
    raw_code_identity = raw_code_identity if isinstance(raw_code_identity, dict) else {}
    raw_sim_version_identity = (
        report.get("sim_version_identity")
        if isinstance(report.get("sim_version_identity"), dict)
        else metadata.get("sim_version_identity")
    )
    raw_sim_version_identity = raw_sim_version_identity if isinstance(raw_sim_version_identity, dict) else {}
    raw_random_seed_identity = (
        report.get("random_seed_identity")
        if isinstance(report.get("random_seed_identity"), dict)
        else metadata.get("random_seed_identity")
    )
    raw_random_seed_identity = raw_random_seed_identity if isinstance(raw_random_seed_identity, dict) else {}
    raw_reward_identity = (
        report.get("reward_identity")
        if isinstance(report.get("reward_identity"), dict)
        else metadata.get("reward_identity")
    )
    raw_reward_identity = raw_reward_identity if isinstance(raw_reward_identity, dict) else {}
    raw_contract_versions = (
        report.get("contract_versions")
        if isinstance(report.get("contract_versions"), dict)
        else metadata.get("contract_versions")
    )
    raw_contract_versions = raw_contract_versions if isinstance(raw_contract_versions, dict) else {}
    raw_world_identity = (
        report.get("world_identity")
        if isinstance(report.get("world_identity"), dict)
        else metadata.get("world_identity")
    )
    raw_world_identity = raw_world_identity if isinstance(raw_world_identity, dict) else {}
    raw_world_card = report.get("world_card") if isinstance(report.get("world_card"), dict) else metadata.get("world_card")
    raw_world_card = raw_world_card if isinstance(raw_world_card, dict) else {}
    raw_missing_sources = (
        report.get("missing_sources")
        if isinstance(report.get("missing_sources"), list)
        else metadata.get("missing_sources")
    )
    raw_not_applicable_sources = (
        report.get("not_applicable_sources")
        if isinstance(report.get("not_applicable_sources"), list)
        else metadata.get("not_applicable_sources")
    )
    record_kind = _record_kind_summary(report)
    world_card = _world_card_summary(report)
    transition_evidence = _transition_evidence_summary(episode)
    model_lineage_evidence = _model_lineage_evidence_summary(report)
    model_specs = config.get("model_specs") if isinstance(config.get("model_specs"), list) else []
    lineage = pbt.get("lineage") if isinstance(pbt.get("lineage"), list) else []
    field_status = {
        "episode_id": _has_value(report.get("episode_id") or episode.get("episode_id")),
        "arena_id": _has_value(report.get("arena_id") or episode.get("arena_id")),
        "generation": _has_value(
            config.get("generation")
            if config.get("generation") is not None
            else episode.get("generation")
        ),
        "model_specs": bool(model_specs),
        "reward_profile": _has_value(config.get("reward_profile")),
        "task_name": _has_value(config.get("task_name")),
        "symbols": bool(config.get("symbols")),
        "report_path": _has_value(report.get("report_path")),
        "checkpoint_dir": _has_value(config.get("checkpoint_dir")),
        "world_config": bool(config),
        "record_kind": bool(raw_record_kind),
        "record_kind_schema": _has_value(record_kind.get("schema")),
        "record_kind_kind": _has_value(record_kind.get("kind")),
        "record_primary_stage": _has_value(record_kind.get("primary_stage")),
        "record_task_name": _has_value(record_kind.get("task_name")),
        "record_embedded_sections": bool(record_kind.get("embedded_sections")),
        "metadata_schema": _has_value(report.get("metadata_schema") or metadata.get("schema")),
        "hash_method": _has_value(report.get("hash_method") or metadata.get("hash_method")),
        "contract_versions": bool(raw_contract_versions),
        "code_identity": bool(raw_code_identity),
        "sim_version_identity": bool(raw_sim_version_identity),
        "random_seed_identity": bool(raw_random_seed_identity),
        "code_hash": _has_value(report.get("code_hash") or config.get("code_hash")),
        "sim_version": _has_value(report.get("sim_version") or config.get("sim_version")),
        "reward_hash": _has_value(report.get("reward_hash") or config.get("reward_hash")),
        "reward_identity": bool(raw_reward_identity),
        "world_hash": _has_value(report.get("world_hash") or config.get("world_hash") or episode.get("world_hash")),
        "world_identity": bool(raw_world_identity),
        "world_card": bool(raw_world_card),
        "random_seed": _has_value(report.get("random_seed") or config.get("random_seed") or episode.get("random_seed")),
        "missing_sources": isinstance(raw_missing_sources, list),
        "not_applicable_sources": isinstance(raw_not_applicable_sources, list),
    }
    statuses = {
        key: "present" if ok else "missing"
        for key, ok in field_status.items()
    }
    statuses["parent_lineage"] = "present" if lineage else "not_available"
    statuses["data_cutoff"] = (
        "present"
        if _has_value(config.get("data_cutoff") or episode.get("data_cutoff"))
        else "not_applicable"
    )
    statuses["world_universe"] = (
        "present"
        if bool(world_card.get("symbols")) and int(world_card.get("symbol_count") or 0) > 0
        else "missing"
    )
    split_status = str(world_card.get("split_status") or "").strip()
    statuses["world_split"] = (
        "present"
        if split_status in {"train_validation_hidden", "validation", "hidden", "available", "complete"}
        else "not_available"
        if split_status in {"training_only", "not_available"}
        else "missing"
    )
    family_mix_status = str(world_card.get("retail_family_mix_status") or "").strip()
    statuses["world_retail_family_mix"] = (
        "present"
        if family_mix_status in {"pass", "available", "complete", "present"}
        else "not_available"
        if family_mix_status == "not_available"
        else "missing"
    )
    statuses["world_liquidity_seed"] = (
        "present"
        if world_card.get("seed_training_liquidity") is not None
        else "missing"
    )
    statuses["world_clock"] = (
        "present"
        if _has_value(world_card.get("clock_start_day"))
        and _has_value(world_card.get("clock_speed"))
        and world_card.get("run_clock") is not None
        else "missing"
    )
    calibration_status = str(world_card.get("calibration_status") or "").strip()
    statuses["world_calibration"] = (
        "present"
        if calibration_status in {"pass", "available", "complete"}
        else "not_available"
        if calibration_status == "not_available"
        else "missing"
    )
    calibration_score_status = str(world_card.get("calibration_score_status") or "").strip()
    statuses["world_calibration_score"] = (
        "present"
        if calibration_score_status in {"pass", "available", "complete", "present"}
        or _has_value(world_card.get("calibration_score"))
        else "not_available"
        if calibration_score_status == "not_available"
        else "missing"
    )
    statuses["separate_calibration_record"] = _availability_status(
        record_kind.get("separate_calibration_record_status")
    )
    statuses["separate_hidden_evaluation_record"] = _availability_status(
        record_kind.get("separate_hidden_evaluation_record_status")
    )
    statuses["separate_exploit_test_record"] = _availability_status(
        record_kind.get("separate_exploit_test_record_status")
    )
    statuses["transition_evidence"] = (
        "present"
        if transition_evidence.get("status") == "has_summary"
        else "not_available"
        if transition_evidence.get("status") == "no_transitions"
        else "missing"
    )
    statuses["model_lineage_evidence"] = (
        "present"
        if model_lineage_evidence.get("status") == "has_lineage"
        else "not_available"
        if model_lineage_evidence.get("status") == "no_lineage"
        else "missing"
    )
    present = [key for key, status in statuses.items() if status == "present"]
    missing = [key for key, status in statuses.items() if status == "missing"]
    not_available = [key for key, status in statuses.items() if status == "not_available"]
    not_applicable = [key for key, status in statuses.items() if status == "not_applicable"]
    return {
        "status": "complete" if not missing else "incomplete",
        "field_status": statuses,
        "present_fields": present,
        "missing_fields": missing,
        "not_available_fields": not_available,
        "not_applicable_fields": not_applicable,
        "present_count": len(present),
        "missing_count": len(missing),
        "not_available_count": len(not_available),
        "not_applicable_count": len(not_applicable),
        "tracked_fields": list(statuses),
    }


def _availability_status(status: Any) -> str:
    normalized = str(status or "").strip()
    if normalized in {"pass", "available", "complete", "present"}:
        return "present"
    if normalized == "not_available":
        return "not_available"
    if normalized == "not_applicable":
        return "not_applicable"
    return "missing"


def _experiment_record_identity_summary(report: dict[str, Any]) -> dict[str, Any]:
    metadata = report.get("experiment_record_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    code_identity = metadata.get("code_identity") if isinstance(metadata.get("code_identity"), dict) else {}
    sim_identity = (
        metadata.get("sim_version_identity")
        if isinstance(metadata.get("sim_version_identity"), dict)
        else {}
    )
    random_seed_identity = (
        metadata.get("random_seed_identity")
        if isinstance(metadata.get("random_seed_identity"), dict)
        else {}
    )
    random_seed = report.get("random_seed")
    if random_seed is None:
        random_seed = metadata.get("random_seed")
    return {
        "metadata_schema": metadata.get("schema"),
        "code_hash": report.get("code_hash") or metadata.get("code_hash"),
        "code_identity_status": code_identity.get("status"),
        "code_dirty": code_identity.get("is_dirty"),
        "sim_version": report.get("sim_version") or metadata.get("sim_version"),
        "sim_version_status": sim_identity.get("status"),
        "reward_hash": report.get("reward_hash") or metadata.get("reward_hash"),
        "world_hash": report.get("world_hash") or metadata.get("world_hash"),
        "random_seed": random_seed,
        "random_seed_status": random_seed_identity.get("status"),
        "random_seed_reason": random_seed_identity.get("reason"),
        "missing_sources": list(metadata.get("missing_sources") or []),
        "not_applicable_sources": list(metadata.get("not_applicable_sources") or []),
    }


def _record_kind_summary(report: dict[str, Any]) -> dict[str, Any]:
    metadata = report.get("experiment_record_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    record_kind = report.get("record_kind") if isinstance(report.get("record_kind"), dict) else metadata.get("record_kind")
    record_kind = record_kind if isinstance(record_kind, dict) else {}
    return {
        "schema": record_kind.get("schema"),
        "kind": record_kind.get("kind"),
        "primary_stage": record_kind.get("primary_stage"),
        "task_name": record_kind.get("task_name"),
        "embedded_sections": list(record_kind.get("embedded_sections") or []),
        "separate_calibration_record_status": record_kind.get("separate_calibration_record_status"),
        "separate_hidden_evaluation_record_status": record_kind.get("separate_hidden_evaluation_record_status"),
        "separate_exploit_test_record_status": record_kind.get("separate_exploit_test_record_status"),
    }


def _world_card_summary(report: dict[str, Any]) -> dict[str, Any]:
    metadata = report.get("experiment_record_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    card = report.get("world_card") if isinstance(report.get("world_card"), dict) else metadata.get("world_card")
    card = card if isinstance(card, dict) else {}
    universe = card.get("universe") if isinstance(card.get("universe"), dict) else {}
    retail_profile = card.get("retail_profile") if isinstance(card.get("retail_profile"), dict) else {}
    clock = card.get("clock") if isinstance(card.get("clock"), dict) else {}
    liquidity_seed = card.get("liquidity_seed") if isinstance(card.get("liquidity_seed"), dict) else {}
    split = card.get("split") if isinstance(card.get("split"), dict) else {}
    calibration = card.get("calibration") if isinstance(card.get("calibration"), dict) else {}
    symbols = list(universe.get("symbols") or [])
    return {
        "schema": card.get("schema"),
        "world_hash": card.get("world_hash") or report.get("world_hash") or metadata.get("world_hash"),
        "split_status": split.get("status"),
        "split_reason": split.get("reason"),
        "symbols": symbols,
        "symbol_count": int(universe.get("symbol_count") or len(symbols)),
        "retail_count": retail_profile.get("retail_count"),
        "retail_initial_cash": retail_profile.get("retail_initial_cash"),
        "retail_family_mix_status": retail_profile.get("family_mix_status"),
        "clock_start_day": clock.get("clock_start_day"),
        "clock_speed": clock.get("clock_speed"),
        "run_clock": clock.get("run_clock"),
        "seed_training_liquidity": liquidity_seed.get("seed_training_liquidity"),
        "liquidity_order_qty": liquidity_seed.get("liquidity_order_qty"),
        "liquidity_spread_ticks": liquidity_seed.get("liquidity_spread_ticks"),
        "calibration_status": calibration.get("status"),
        "calibration_reason": calibration.get("reason"),
        "calibration_score": calibration.get("score"),
        "calibration_score_status": calibration.get("score_status"),
        "calibration_score_reason": calibration.get("score_reason"),
        "missing_calibration_metrics": list(calibration.get("missing_metrics") or []),
    }


def _transition_evidence_summary(episode: dict[str, Any]) -> dict[str, Any]:
    audit_names = [
        "runtime_observation_audit",
        "timestamp_audit",
        "mark_to_market_audit",
        "order_anomaly_audit",
    ]
    transition_count = int(episode.get("transition_count") or 0)
    sections: dict[str, dict[str, Any]] = {}
    total_sample_count = 0
    total_violation_count = 0
    for name in audit_names:
        section = episode.get(name) if isinstance(episode.get(name), dict) else {}
        samples = section.get("samples") if isinstance(section.get("samples"), list) else []
        violations = section.get("violations") if isinstance(section.get("violations"), list) else []
        sample_count = len(samples)
        violation_count = len(violations)
        total_sample_count += sample_count
        total_violation_count += violation_count
        sections[name] = {
            "status": section.get("status"),
            "reason": section.get("reason"),
            "transition_count": int(section.get("transition_count") or 0),
            "checked_transition_count": int(section.get("checked_transition_count") or 0),
            "sample_count": sample_count,
            "violation_count": violation_count,
        }
    return {
        "status": "has_summary" if transition_count > 0 else "no_transitions",
        "policy": "compact_summary_with_bounded_audit_samples",
        "sample_limit_per_audit": 5,
        "transition_count": transition_count,
        "total_audit_sample_count": total_sample_count,
        "total_audit_violation_count": total_violation_count,
        "sections": sections,
    }


def _model_lineage_evidence_summary(report: dict[str, Any]) -> dict[str, Any]:
    config = report.get("config") if isinstance(report.get("config"), dict) else {}
    pbt = report.get("pbt") if isinstance(report.get("pbt"), dict) else {}
    model_specs = [row for row in (config.get("model_specs") or []) if isinstance(row, dict)]
    lineage = [row for row in (pbt.get("lineage") or []) if isinstance(row, dict)]
    applied_agents = [row for row in (pbt.get("applied_agents") or []) if isinstance(row, dict)]
    model_ids = sorted(
        {str(row.get("model_id")) for row in model_specs if _has_value(row.get("model_id"))}
    )
    agent_ids = sorted(
        {str(row.get("agent_id")) for row in model_specs if _has_value(row.get("agent_id"))}
    )
    applied_model_ids = sorted(
        {str(row.get("model_id")) for row in applied_agents if _has_value(row.get("model_id"))}
    )
    parent_model_ids = sorted(
        {str(row.get("parent_model_id")) for row in lineage if _has_value(row.get("parent_model_id"))}
    )
    child_model_ids = sorted(
        {str(row.get("child_model_id")) for row in lineage if _has_value(row.get("child_model_id"))}
    )
    mutation_keys = sorted(
        {
            str(key)
            for row in lineage
            if isinstance(row.get("mutation"), dict)
            for key in row["mutation"].keys()
        }
    )
    sample_limit = 5
    lineage_samples = []
    for row in lineage[:sample_limit]:
        mutation = row.get("mutation") if isinstance(row.get("mutation"), dict) else {}
        lineage_samples.append(
            {
                "parent_agent_id": row.get("parent_agent_id"),
                "parent_model_id": row.get("parent_model_id"),
                "child_agent_id": row.get("child_agent_id"),
                "child_model_id": row.get("child_model_id"),
                "mutation_keys": sorted(str(key) for key in mutation.keys()),
            }
        )
    return {
        "status": "has_lineage" if lineage else "no_lineage",
        "model_count": len(model_ids),
        "agent_count": len(agent_ids),
        "model_ids": model_ids,
        "agent_ids": agent_ids,
        "lineage_count": len(lineage),
        "applied_count": len(applied_agents),
        "applied_model_ids": applied_model_ids,
        "parent_model_ids": parent_model_ids,
        "child_model_ids": child_model_ids,
        "mutation_keys": mutation_keys,
        "lineage_sample_limit": sample_limit,
        "lineage_samples": lineage_samples,
    }


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _episode_audit_summary(episode: dict[str, Any]) -> dict[str, Any]:
    audit_names = [
        "runtime_observation_audit",
        "fee_accounting_audit",
        "fee_sensitivity",
        "impact_sensitivity",
        "timestamp_audit",
        "mark_to_market_audit",
        "order_anomaly_audit",
    ]
    return {
        name: _audit_section_summary(episode.get(name), default_name=name)
        for name in audit_names
    }


def _audit_section_summary(value: Any, *, default_name: str) -> dict[str, Any]:
    section = value if isinstance(value, dict) else {}
    violations = section.get("violations") if isinstance(section.get("violations"), list) else []
    required_inputs = section.get("required_inputs") if isinstance(section.get("required_inputs"), list) else []
    return {
        "name": section.get("name") or default_name,
        "status": section.get("status"),
        "reason": section.get("reason"),
        "scope": section.get("scope"),
        "transition_count": int(section.get("transition_count") or 0),
        "checked_transition_count": int(section.get("checked_transition_count") or 0),
        "result_count": int(section.get("result_count") or 0),
        "checked_result_count": int(section.get("checked_result_count") or 0),
        "violation_count": len(violations),
        "required_input_count": len(required_inputs),
    }


def _evaluation_section_summary(value: Any) -> dict[str, Any]:
    section = value if isinstance(value, dict) else {}
    checks = [row for row in (section.get("checks") or []) if isinstance(row, dict)]
    return {
        "status": section.get("status"),
        "reason": section.get("reason"),
        "implemented_checks": list(section.get("implemented_checks") or []),
        "placeholder_checks": list(section.get("placeholder_checks") or []),
        "check_count": len(checks),
        "check_status_counts": dict(Counter(str(row.get("status")) for row in checks if row.get("status") is not None)),
        "check_reason_counts": dict(Counter(str(row.get("reason")) for row in checks if row.get("reason") is not None)),
        "required_input_count": len(section.get("required_inputs") or []),
    }


def _benchmark_comparison_summary(value: Any) -> dict[str, Any]:
    comparison = value if isinstance(value, dict) else {}
    comparisons = comparison.get("comparisons") if isinstance(comparison.get("comparisons"), dict) else {}
    candidate_ids = sorted(str(key) for key in comparisons.keys())
    pair_count = 0
    for row in comparisons.values():
        if isinstance(row, dict):
            pair_count += len(row)
    return {
        "status": comparison.get("status"),
        "baseline_kinds": list(comparison.get("baseline_kinds") or []),
        "candidate_count": len(candidate_ids),
        "candidate_ids": candidate_ids,
        "candidate_baseline_pair_count": pair_count,
    }


def _baseline_suite_summary(value: Any) -> dict[str, Any]:
    suite = value if isinstance(value, dict) else {}
    return {
        "task_name": suite.get("task_name"),
        "status": suite.get("status"),
        "present_kinds": list(suite.get("present_kinds") or []),
        "missing_required": list(suite.get("missing_required") or []),
        "required": [
            {
                "kind": row.get("kind"),
                "status": row.get("status"),
            }
            for row in (suite.get("required") or [])
            if isinstance(row, dict)
        ],
        "optional": [
            {
                "kind": row.get("kind"),
                "status": row.get("status"),
                "reason": row.get("reason"),
            }
            for row in (suite.get("optional") or [])
            if isinstance(row, dict)
        ],
    }


def _research_acceptance_summary(value: Any) -> dict[str, Any]:
    report = value if isinstance(value, dict) else {}
    lock = report.get("acceptance_lock") if isinstance(report.get("acceptance_lock"), dict) else {}
    sections = report.get("required_sections") if isinstance(report.get("required_sections"), dict) else {}
    return {
        "status": report.get("status"),
        "is_research_accepted": bool(report.get("is_research_accepted", False)),
        "strict_parent_eligibility_allowed": bool(report.get("strict_parent_eligibility_allowed", False)),
        "reasons": list(report.get("reasons") or []),
        "required_sections": {
            "baseline_suite": sections.get("baseline_suite"),
            "hidden_evaluation": sections.get("hidden_evaluation"),
            "exploit_detector": sections.get("exploit_detector"),
        },
        "acceptance_lock": {
            "status": lock.get("status"),
            "blocking_sections": lock.get("blocking_sections") if isinstance(lock.get("blocking_sections"), dict) else {},
            "reason": lock.get("reason"),
        },
    }


def _strict_parent_gate_summary(value: Any) -> dict[str, Any]:
    gate = value if isinstance(value, dict) else {}
    lock = gate.get("acceptance_lock") if isinstance(gate.get("acceptance_lock"), dict) else {}
    return {
        "enabled": bool(gate.get("enabled", False)),
        "passes": bool(gate.get("passes", False)),
        "reason": gate.get("reason"),
        "blocking_reasons": list(gate.get("blocking_reasons") or []),
        "acceptance_lock": {
            "status": lock.get("status"),
            "blocking_sections": lock.get("blocking_sections") if isinstance(lock.get("blocking_sections"), dict) else {},
            "reason": lock.get("reason"),
        },
    }


def _series_aggregate(reports: list[dict[str, Any]]) -> dict[str, Any]:
    winner_counts: Counter[str] = Counter()
    loser_counts: Counter[str] = Counter()
    record_completeness_status_counts: Counter[str] = Counter()
    record_missing_field_counts: Counter[str] = Counter()
    record_present_field_counts: Counter[str] = Counter()
    record_not_available_field_counts: Counter[str] = Counter()
    record_not_applicable_field_counts: Counter[str] = Counter()
    record_field_status_counts: Counter[str] = Counter()
    identity_code_status_counts: Counter[str] = Counter()
    identity_sim_version_status_counts: Counter[str] = Counter()
    identity_random_seed_status_counts: Counter[str] = Counter()
    identity_missing_source_counts: Counter[str] = Counter()
    identity_not_applicable_source_counts: Counter[str] = Counter()
    record_kind_counts: Counter[str] = Counter()
    record_primary_stage_counts: Counter[str] = Counter()
    record_embedded_section_counts: Counter[str] = Counter()
    separate_calibration_record_status_counts: Counter[str] = Counter()
    separate_hidden_evaluation_record_status_counts: Counter[str] = Counter()
    separate_exploit_test_record_status_counts: Counter[str] = Counter()
    world_card_split_status_counts: Counter[str] = Counter()
    world_card_calibration_status_counts: Counter[str] = Counter()
    world_card_calibration_score_status_counts: Counter[str] = Counter()
    world_card_missing_calibration_metric_counts: Counter[str] = Counter()
    world_card_hash_counts: Counter[str] = Counter()
    transition_evidence_status_counts: Counter[str] = Counter()
    transition_evidence_section_status_counts: Counter[str] = Counter()
    model_lineage_status_counts: Counter[str] = Counter()
    model_lineage_model_id_counts: Counter[str] = Counter()
    model_lineage_agent_id_counts: Counter[str] = Counter()
    model_lineage_parent_model_id_counts: Counter[str] = Counter()
    model_lineage_child_model_id_counts: Counter[str] = Counter()
    model_lineage_applied_model_id_counts: Counter[str] = Counter()
    model_lineage_mutation_key_counts: Counter[str] = Counter()
    audit_status_counts: dict[str, Counter[str]] = defaultdict(Counter)
    audit_reason_counts: dict[str, Counter[str]] = defaultdict(Counter)
    hidden_status_counts: Counter[str] = Counter()
    hidden_check_status_counts: Counter[str] = Counter()
    hidden_check_reason_counts: Counter[str] = Counter()
    exploit_status_counts: Counter[str] = Counter()
    exploit_check_status_counts: Counter[str] = Counter()
    exploit_check_reason_counts: Counter[str] = Counter()
    exploit_implemented_check_counts: Counter[str] = Counter()
    exploit_placeholder_check_counts: Counter[str] = Counter()
    benchmark_status_counts: Counter[str] = Counter()
    benchmark_baseline_kind_counts: Counter[str] = Counter()
    baseline_suite_status_counts: Counter[str] = Counter()
    baseline_present_kind_counts: Counter[str] = Counter()
    baseline_missing_required_counts: Counter[str] = Counter()
    baseline_required_status_counts: Counter[str] = Counter()
    baseline_optional_status_counts: Counter[str] = Counter()
    research_acceptance_status_counts: Counter[str] = Counter()
    research_acceptance_lock_status_counts: Counter[str] = Counter()
    research_acceptance_blocking_section_counts: Counter[str] = Counter()
    research_acceptance_required_section_status_counts: Counter[str] = Counter()
    strict_blocking_reason_counts: Counter[str] = Counter()
    strict_lock_blocking_section_counts: Counter[str] = Counter()
    totals = {
        "transition_count": 0,
        "trade_count": 0,
        "submitted_order_count": 0,
        "filled_order_count": 0,
        "open_order_count": 0,
        "rejected_order_count": 0,
        "submitted_notional": 0.0,
        "filled_notional": 0.0,
        "open_order_notional": 0.0,
        "checkpoint_count": 0,
        "lineage_count": 0,
        "applied_count": 0,
        "strict_gate_observed_count": 0,
        "strict_gate_enabled_count": 0,
        "strict_gate_passed_count": 0,
        "strict_gate_blocked_count": 0,
        "strict_gate_disabled_count": 0,
        "research_acceptance_observed_count": 0,
        "research_accepted_count": 0,
        "research_rejected_count": 0,
        "strict_parent_allowed_count": 0,
        "baseline_suite_observed_count": 0,
        "baseline_suite_complete_count": 0,
        "baseline_suite_incomplete_count": 0,
        "benchmark_comparison_observed_count": 0,
        "benchmark_candidate_count": 0,
        "benchmark_candidate_baseline_pair_count": 0,
        "hidden_evaluation_observed_count": 0,
        "hidden_evaluation_required_input_count": 0,
        "hidden_evaluation_check_count": 0,
        "exploit_detector_observed_count": 0,
        "exploit_detector_check_count": 0,
        "audit_observed_count": 0,
        "audit_transition_count": 0,
        "audit_checked_transition_count": 0,
        "audit_result_count": 0,
        "audit_checked_result_count": 0,
        "audit_violation_count": 0,
        "audit_required_input_count": 0,
        "record_completeness_observed_count": 0,
        "record_completeness_complete_count": 0,
        "record_completeness_incomplete_count": 0,
        "record_identity_observed_count": 0,
        "record_identity_dirty_code_count": 0,
        "record_kind_observed_count": 0,
        "world_card_observed_count": 0,
        "transition_evidence_observed_count": 0,
        "transition_evidence_transition_count": 0,
        "transition_evidence_sample_count": 0,
        "transition_evidence_violation_count": 0,
        "model_lineage_evidence_observed_count": 0,
        "model_lineage_evidence_lineage_count": 0,
        "model_lineage_evidence_applied_count": 0,
    }
    final_models: dict[str, str] = {}
    for report in reports:
        episode = report.get("episode") or {}
        pbt = report.get("pbt") or {}
        record = _experiment_record_completeness_summary(report)
        totals["record_completeness_observed_count"] += 1
        if record.get("status") is not None:
            status = str(record.get("status"))
            record_completeness_status_counts.update([status])
            if status == "complete":
                totals["record_completeness_complete_count"] += 1
            if status == "incomplete":
                totals["record_completeness_incomplete_count"] += 1
        record_present_field_counts.update(str(item) for item in (record.get("present_fields") or []))
        record_missing_field_counts.update(str(item) for item in (record.get("missing_fields") or []))
        record_not_available_field_counts.update(str(item) for item in (record.get("not_available_fields") or []))
        record_not_applicable_field_counts.update(str(item) for item in (record.get("not_applicable_fields") or []))
        field_status = record.get("field_status") if isinstance(record.get("field_status"), dict) else {}
        record_field_status_counts.update(f"{key}:{value}" for key, value in field_status.items())
        identity = _experiment_record_identity_summary(report)
        totals["record_identity_observed_count"] += 1
        if identity.get("code_dirty") is True:
            totals["record_identity_dirty_code_count"] += 1
        if identity.get("code_identity_status") is not None:
            identity_code_status_counts.update([str(identity.get("code_identity_status"))])
        if identity.get("sim_version_status") is not None:
            identity_sim_version_status_counts.update([str(identity.get("sim_version_status"))])
        if identity.get("random_seed_status") is not None:
            identity_random_seed_status_counts.update([str(identity.get("random_seed_status"))])
        identity_missing_source_counts.update(str(item) for item in (identity.get("missing_sources") or []))
        identity_not_applicable_source_counts.update(
            str(item) for item in (identity.get("not_applicable_sources") or [])
        )
        record_kind = _record_kind_summary(report)
        if record_kind.get("kind") is not None:
            totals["record_kind_observed_count"] += 1
            record_kind_counts.update([str(record_kind.get("kind"))])
        if record_kind.get("primary_stage") is not None:
            record_primary_stage_counts.update([str(record_kind.get("primary_stage"))])
        record_embedded_section_counts.update(str(item) for item in (record_kind.get("embedded_sections") or []))
        if record_kind.get("separate_calibration_record_status") is not None:
            separate_calibration_record_status_counts.update([str(record_kind.get("separate_calibration_record_status"))])
        if record_kind.get("separate_hidden_evaluation_record_status") is not None:
            separate_hidden_evaluation_record_status_counts.update(
                [str(record_kind.get("separate_hidden_evaluation_record_status"))]
            )
        if record_kind.get("separate_exploit_test_record_status") is not None:
            separate_exploit_test_record_status_counts.update([str(record_kind.get("separate_exploit_test_record_status"))])
        world_card = _world_card_summary(report)
        if world_card.get("schema") is not None or world_card.get("world_hash") is not None:
            totals["world_card_observed_count"] += 1
        if world_card.get("world_hash") is not None:
            world_card_hash_counts.update([str(world_card.get("world_hash"))])
        if world_card.get("split_status") is not None:
            world_card_split_status_counts.update([str(world_card.get("split_status"))])
        if world_card.get("calibration_status") is not None:
            world_card_calibration_status_counts.update([str(world_card.get("calibration_status"))])
        if world_card.get("calibration_score_status") is not None:
            world_card_calibration_score_status_counts.update([str(world_card.get("calibration_score_status"))])
        world_card_missing_calibration_metric_counts.update(
            str(item) for item in (world_card.get("missing_calibration_metrics") or [])
        )
        transition_evidence = _transition_evidence_summary(episode)
        totals["transition_evidence_observed_count"] += 1
        totals["transition_evidence_transition_count"] += int(transition_evidence.get("transition_count") or 0)
        totals["transition_evidence_sample_count"] += int(transition_evidence.get("total_audit_sample_count") or 0)
        totals["transition_evidence_violation_count"] += int(transition_evidence.get("total_audit_violation_count") or 0)
        if transition_evidence.get("status") is not None:
            transition_evidence_status_counts.update([str(transition_evidence.get("status"))])
        sections = transition_evidence.get("sections") if isinstance(transition_evidence.get("sections"), dict) else {}
        for name, section in sections.items():
            if isinstance(section, dict) and section.get("status") is not None:
                transition_evidence_section_status_counts.update([f"{name}:{section.get('status')}"])
        model_lineage = _model_lineage_evidence_summary(report)
        totals["model_lineage_evidence_observed_count"] += 1
        totals["model_lineage_evidence_lineage_count"] += int(model_lineage.get("lineage_count") or 0)
        totals["model_lineage_evidence_applied_count"] += int(model_lineage.get("applied_count") or 0)
        if model_lineage.get("status") is not None:
            model_lineage_status_counts.update([str(model_lineage.get("status"))])
        model_lineage_model_id_counts.update(str(item) for item in (model_lineage.get("model_ids") or []))
        model_lineage_agent_id_counts.update(str(item) for item in (model_lineage.get("agent_ids") or []))
        model_lineage_parent_model_id_counts.update(str(item) for item in (model_lineage.get("parent_model_ids") or []))
        model_lineage_child_model_id_counts.update(str(item) for item in (model_lineage.get("child_model_ids") or []))
        model_lineage_applied_model_id_counts.update(str(item) for item in (model_lineage.get("applied_model_ids") or []))
        model_lineage_mutation_key_counts.update(str(item) for item in (model_lineage.get("mutation_keys") or []))
        if isinstance(episode.get("baseline_suite"), dict):
            baseline_suite = _baseline_suite_summary(episode.get("baseline_suite"))
            totals["baseline_suite_observed_count"] += 1
            if baseline_suite.get("status") is not None:
                status = str(baseline_suite.get("status"))
                baseline_suite_status_counts.update([status])
                if status == "complete":
                    totals["baseline_suite_complete_count"] += 1
                if status == "incomplete":
                    totals["baseline_suite_incomplete_count"] += 1
            baseline_present_kind_counts.update(str(item) for item in (baseline_suite.get("present_kinds") or []))
            baseline_missing_required_counts.update(str(item) for item in (baseline_suite.get("missing_required") or []))
            for row in baseline_suite.get("required") or []:
                if isinstance(row, dict):
                    baseline_required_status_counts.update([f"{row.get('kind')}:{row.get('status')}"])
            for row in baseline_suite.get("optional") or []:
                if isinstance(row, dict):
                    baseline_optional_status_counts.update([f"{row.get('kind')}:{row.get('status')}"])
        if isinstance(episode.get("benchmark_comparison"), dict):
            benchmark = _benchmark_comparison_summary(episode.get("benchmark_comparison"))
            totals["benchmark_comparison_observed_count"] += 1
            totals["benchmark_candidate_count"] += int(benchmark.get("candidate_count") or 0)
            totals["benchmark_candidate_baseline_pair_count"] += int(benchmark.get("candidate_baseline_pair_count") or 0)
            if benchmark.get("status") is not None:
                benchmark_status_counts.update([str(benchmark.get("status"))])
            benchmark_baseline_kind_counts.update(str(item) for item in (benchmark.get("baseline_kinds") or []))
        if isinstance(episode.get("hidden_evaluation"), dict):
            hidden = _evaluation_section_summary(episode.get("hidden_evaluation"))
            totals["hidden_evaluation_observed_count"] += 1
            totals["hidden_evaluation_required_input_count"] += int(hidden.get("required_input_count") or 0)
            totals["hidden_evaluation_check_count"] += int(hidden.get("check_count") or 0)
            if hidden.get("status") is not None:
                hidden_status_counts.update([str(hidden.get("status"))])
            hidden_check_status_counts.update(hidden.get("check_status_counts") or {})
            hidden_check_reason_counts.update(hidden.get("check_reason_counts") or {})
        if isinstance(episode.get("exploit_detector"), dict):
            exploit = _evaluation_section_summary(episode.get("exploit_detector"))
            totals["exploit_detector_observed_count"] += 1
            totals["exploit_detector_check_count"] += int(exploit.get("check_count") or 0)
            if exploit.get("status") is not None:
                exploit_status_counts.update([str(exploit.get("status"))])
            exploit_check_status_counts.update(exploit.get("check_status_counts") or {})
            exploit_check_reason_counts.update(exploit.get("check_reason_counts") or {})
            exploit_implemented_check_counts.update(str(item) for item in (exploit.get("implemented_checks") or []))
            exploit_placeholder_check_counts.update(str(item) for item in (exploit.get("placeholder_checks") or []))
        audit_summary = _episode_audit_summary(episode)
        for name, audit in audit_summary.items():
            if audit.get("status") is None:
                continue
            totals["audit_observed_count"] += 1
            totals["audit_transition_count"] += int(audit.get("transition_count") or 0)
            totals["audit_checked_transition_count"] += int(audit.get("checked_transition_count") or 0)
            totals["audit_result_count"] += int(audit.get("result_count") or 0)
            totals["audit_checked_result_count"] += int(audit.get("checked_result_count") or 0)
            totals["audit_violation_count"] += int(audit.get("violation_count") or 0)
            totals["audit_required_input_count"] += int(audit.get("required_input_count") or 0)
            audit_status_counts[str(name)].update([str(audit.get("status"))])
            if audit.get("reason") is not None:
                audit_reason_counts[str(name)].update([str(audit.get("reason"))])
        if isinstance(episode.get("research_acceptance"), dict):
            acceptance = _research_acceptance_summary(episode.get("research_acceptance"))
            totals["research_acceptance_observed_count"] += 1
            if acceptance.get("is_research_accepted"):
                totals["research_accepted_count"] += 1
            else:
                totals["research_rejected_count"] += 1
            if acceptance.get("strict_parent_eligibility_allowed"):
                totals["strict_parent_allowed_count"] += 1
            if acceptance.get("status") is not None:
                research_acceptance_status_counts.update([str(acceptance.get("status"))])
            lock = acceptance.get("acceptance_lock") if isinstance(acceptance.get("acceptance_lock"), dict) else {}
            if lock.get("status") is not None:
                research_acceptance_lock_status_counts.update([str(lock.get("status"))])
            blocking_sections = lock.get("blocking_sections") if isinstance(lock.get("blocking_sections"), dict) else {}
            research_acceptance_blocking_section_counts.update(str(key) for key in blocking_sections.keys())
            required_sections = acceptance.get("required_sections") if isinstance(acceptance.get("required_sections"), dict) else {}
            for key, status in required_sections.items():
                research_acceptance_required_section_status_counts.update([f"{key}:{status}"])
        if isinstance(pbt.get("strict_parent_gate"), dict):
            gate = _strict_parent_gate_summary(pbt.get("strict_parent_gate"))
            totals["strict_gate_observed_count"] += 1
            if gate.get("enabled"):
                totals["strict_gate_enabled_count"] += 1
                if gate.get("passes"):
                    totals["strict_gate_passed_count"] += 1
                else:
                    totals["strict_gate_blocked_count"] += 1
            else:
                totals["strict_gate_disabled_count"] += 1
            strict_blocking_reason_counts.update(str(item) for item in (gate.get("blocking_reasons") or []))
            lock = gate.get("acceptance_lock") if isinstance(gate.get("acceptance_lock"), dict) else {}
            blocking_sections = lock.get("blocking_sections") if isinstance(lock.get("blocking_sections"), dict) else {}
            strict_lock_blocking_section_counts.update(str(key) for key in blocking_sections.keys())
        health = ((episode.get("execution_health") or {}).get("totals") or {})
        totals["transition_count"] += int(episode.get("transition_count") or 0)
        for key in (
            "trade_count",
            "submitted_order_count",
            "filled_order_count",
            "open_order_count",
            "rejected_order_count",
        ):
            totals[key] += int(health.get(key, 0) or 0)
        for key in ("submitted_notional", "filled_notional", "open_order_notional"):
            totals[key] += float(health.get(key, 0.0) or 0.0)
        totals["checkpoint_count"] += len(pbt.get("checkpoints") or [])
        totals["lineage_count"] += len(pbt.get("lineage") or [])
        totals["applied_count"] += len(pbt.get("applied_agents") or [])
        winner_counts.update(str(item) for item in (pbt.get("winners") or []))
        loser_counts.update(str(item) for item in (pbt.get("losers") or []))
        for row in episode.get("results") or []:
            agent_id = row.get("agent_id")
            model_id = row.get("model_id")
            if agent_id and model_id:
                final_models[str(agent_id)] = str(model_id)
        for item in pbt.get("applied_agents") or []:
            agent_id = item.get("agent_id")
            model_id = item.get("model_id")
            if agent_id and model_id:
                final_models[str(agent_id)] = str(model_id)
        for item in pbt.get("lineage") or []:
            agent_id = item.get("child_agent_id")
            model_id = item.get("child_model_id")
            if agent_id and model_id:
                final_models[str(agent_id)] = str(model_id)
    totals["fill_ratio"] = (
        totals["filled_order_count"] / totals["submitted_order_count"]
        if totals["submitted_order_count"] > 0
        else 0.0
    )
    totals["notional_fill_ratio"] = (
        totals["filled_notional"] / totals["submitted_notional"]
        if totals["submitted_notional"] > 0
        else 0.0
    )
    return {
        **totals,
        "winner_counts": dict(winner_counts),
        "loser_counts": dict(loser_counts),
        "final_models": final_models,
        "experiment_record_completeness": {
            "observed_count": totals["record_completeness_observed_count"],
            "complete_count": totals["record_completeness_complete_count"],
            "incomplete_count": totals["record_completeness_incomplete_count"],
            "status_counts": dict(record_completeness_status_counts),
            "field_status_counts": dict(record_field_status_counts),
            "present_field_counts": dict(record_present_field_counts),
            "missing_field_counts": dict(record_missing_field_counts),
            "not_available_field_counts": dict(record_not_available_field_counts),
            "not_applicable_field_counts": dict(record_not_applicable_field_counts),
        },
        "experiment_record_identity": {
            "observed_count": totals["record_identity_observed_count"],
            "dirty_code_count": totals["record_identity_dirty_code_count"],
            "code_identity_status_counts": dict(identity_code_status_counts),
            "sim_version_status_counts": dict(identity_sim_version_status_counts),
            "random_seed_status_counts": dict(identity_random_seed_status_counts),
            "missing_source_counts": dict(identity_missing_source_counts),
            "not_applicable_source_counts": dict(identity_not_applicable_source_counts),
        },
        "record_kind": {
            "observed_count": totals["record_kind_observed_count"],
            "kind_counts": dict(record_kind_counts),
            "primary_stage_counts": dict(record_primary_stage_counts),
            "embedded_section_counts": dict(record_embedded_section_counts),
            "separate_calibration_record_status_counts": dict(separate_calibration_record_status_counts),
            "separate_hidden_evaluation_record_status_counts": dict(separate_hidden_evaluation_record_status_counts),
            "separate_exploit_test_record_status_counts": dict(separate_exploit_test_record_status_counts),
        },
        "world_card": {
            "observed_count": totals["world_card_observed_count"],
            "unique_world_hash_count": len(world_card_hash_counts),
            "split_status_counts": dict(world_card_split_status_counts),
            "calibration_status_counts": dict(world_card_calibration_status_counts),
            "calibration_score_status_counts": dict(world_card_calibration_score_status_counts),
            "missing_calibration_metric_counts": dict(world_card_missing_calibration_metric_counts),
        },
        "transition_evidence": {
            "observed_count": totals["transition_evidence_observed_count"],
            "transition_count": totals["transition_evidence_transition_count"],
            "audit_sample_count": totals["transition_evidence_sample_count"],
            "audit_violation_count": totals["transition_evidence_violation_count"],
            "status_counts": dict(transition_evidence_status_counts),
            "section_status_counts": dict(transition_evidence_section_status_counts),
            "policy": "compact_summary_with_bounded_audit_samples",
            "sample_limit_per_audit": 5,
        },
        "model_lineage_evidence": {
            "observed_count": totals["model_lineage_evidence_observed_count"],
            "lineage_count": totals["model_lineage_evidence_lineage_count"],
            "applied_count": totals["model_lineage_evidence_applied_count"],
            "status_counts": dict(model_lineage_status_counts),
            "model_id_counts": dict(model_lineage_model_id_counts),
            "agent_id_counts": dict(model_lineage_agent_id_counts),
            "parent_model_id_counts": dict(model_lineage_parent_model_id_counts),
            "child_model_id_counts": dict(model_lineage_child_model_id_counts),
            "applied_model_id_counts": dict(model_lineage_applied_model_id_counts),
            "mutation_key_counts": dict(model_lineage_mutation_key_counts),
        },
        "baseline_suite": {
            "observed_count": totals["baseline_suite_observed_count"],
            "complete_count": totals["baseline_suite_complete_count"],
            "incomplete_count": totals["baseline_suite_incomplete_count"],
            "status_counts": dict(baseline_suite_status_counts),
            "present_kind_counts": dict(baseline_present_kind_counts),
            "missing_required_counts": dict(baseline_missing_required_counts),
            "required_status_counts": dict(baseline_required_status_counts),
            "optional_status_counts": dict(baseline_optional_status_counts),
        },
        "benchmark_comparison": {
            "observed_count": totals["benchmark_comparison_observed_count"],
            "candidate_count": totals["benchmark_candidate_count"],
            "candidate_baseline_pair_count": totals["benchmark_candidate_baseline_pair_count"],
            "status_counts": dict(benchmark_status_counts),
            "baseline_kind_counts": dict(benchmark_baseline_kind_counts),
        },
        "hidden_evaluation": {
            "observed_count": totals["hidden_evaluation_observed_count"],
            "required_input_count": totals["hidden_evaluation_required_input_count"],
            "check_count": totals["hidden_evaluation_check_count"],
            "status_counts": dict(hidden_status_counts),
            "check_status_counts": dict(hidden_check_status_counts),
            "check_reason_counts": dict(hidden_check_reason_counts),
        },
        "exploit_detector": {
            "observed_count": totals["exploit_detector_observed_count"],
            "check_count": totals["exploit_detector_check_count"],
            "status_counts": dict(exploit_status_counts),
            "check_status_counts": dict(exploit_check_status_counts),
            "check_reason_counts": dict(exploit_check_reason_counts),
            "implemented_check_counts": dict(exploit_implemented_check_counts),
            "placeholder_check_counts": dict(exploit_placeholder_check_counts),
        },
        "audit_summary": {
            "observed_count": totals["audit_observed_count"],
            "transition_count": totals["audit_transition_count"],
            "checked_transition_count": totals["audit_checked_transition_count"],
            "result_count": totals["audit_result_count"],
            "checked_result_count": totals["audit_checked_result_count"],
            "violation_count": totals["audit_violation_count"],
            "required_input_count": totals["audit_required_input_count"],
            "status_counts_by_audit": {name: dict(counter) for name, counter in audit_status_counts.items()},
            "reason_counts_by_audit": {name: dict(counter) for name, counter in audit_reason_counts.items()},
        },
        "research_acceptance": {
            "observed_count": totals["research_acceptance_observed_count"],
            "accepted_count": totals["research_accepted_count"],
            "rejected_count": totals["research_rejected_count"],
            "strict_parent_allowed_count": totals["strict_parent_allowed_count"],
            "status_counts": dict(research_acceptance_status_counts),
            "lock_status_counts": dict(research_acceptance_lock_status_counts),
            "lock_blocking_section_counts": dict(research_acceptance_blocking_section_counts),
            "required_section_status_counts": dict(research_acceptance_required_section_status_counts),
        },
        "strict_parent_gate": {
            "observed_count": totals["strict_gate_observed_count"],
            "enabled_count": totals["strict_gate_enabled_count"],
            "passed_count": totals["strict_gate_passed_count"],
            "blocked_count": totals["strict_gate_blocked_count"],
            "disabled_count": totals["strict_gate_disabled_count"],
            "blocking_reason_counts": dict(strict_blocking_reason_counts),
            "lock_blocking_section_counts": dict(strict_lock_blocking_section_counts),
        },
    }


def _model_specs_after_report(specs: list[ArenaModelSpec], report: dict[str, Any]) -> list[ArenaModelSpec]:
    replacements: dict[str, str] = {}
    pbt = report.get("pbt") or {}
    for item in pbt.get("applied_agents") or []:
        agent_id = str(item.get("agent_id") or "").strip()
        model_id = str(item.get("model_id") or "").strip()
        if agent_id and model_id:
            replacements[agent_id] = model_id
    for item in pbt.get("lineage") or []:
        agent_id = str(item.get("child_agent_id") or "").strip()
        model_id = str(item.get("child_model_id") or "").strip()
        if agent_id and model_id:
            replacements[agent_id] = model_id
    if not replacements:
        return list(specs)
    updated: list[ArenaModelSpec] = []
    for spec in specs:
        if spec.agent_id and spec.agent_id in replacements:
            updated.append(
                ArenaModelSpec(
                    agent_id=spec.agent_id,
                    model_id=replacements[spec.agent_id],
                    mode=spec.mode,
                    initial_cash=spec.initial_cash,
                )
            )
        else:
            updated.append(spec)
    return updated


def _is_lineage_model_id(model_id: str) -> bool:
    return bool(re.search(r"\.gen\d+\.", str(model_id or "")))


def _json_loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def _optional_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _ensure_market_data_persistence() -> dict[str, Any]:
    status: dict[str, Any] = {"ok": True}
    try:
        from stock_sim.services.snapshot_listener import ensure_snapshot_listener_started

        ensure_snapshot_listener_started()
        status["snapshot_listener"] = "started"
    except Exception as exc:
        status["ok"] = False
        status["snapshot_listener"] = "error"
        status["snapshot_listener_error"] = str(exc)
    try:
        from stock_sim.services.bar_aggregator import ensure_bar_aggregator_started

        ensure_bar_aggregator_started()
        status["bar_aggregator"] = "started"
    except Exception as exc:
        status["ok"] = False
        status["bar_aggregator"] = "error"
        status["bar_aggregator_error"] = str(exc)
    return status


def _flush_market_bars(*, run_id: str | None) -> dict[str, Any]:
    if not run_id:
        return {"ok": False, "reason": "run_id_unavailable"}
    try:
        from stock_sim.services.bar_aggregator import ensure_bar_aggregator_started

        aggregator = ensure_bar_aggregator_started()
        result = aggregator.flush_all(run_ids=[run_id])
        return {"ok": True, "run_id": run_id, **result}
    except Exception as exc:
        return {"ok": False, "run_id": run_id, "reason": str(exc)}


def _episode_run_id(episode_id: str, session_factory: Callable[[], Any] | None) -> str | None:
    if not episode_id or session_factory is None or TrainingEpisode is None:
        return None
    session = session_factory()
    try:
        episode = session.get(TrainingEpisode, episode_id)
        run_id = getattr(episode, "run_id", None)
        return str(run_id) if run_id else None
    except Exception:
        return None
    finally:
        session.close()


def _safe_call(target: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    method = getattr(target, method_name, None)
    if not callable(method):
        return None
    return method(*args, **kwargs)


def _liquidity_account_id(base: str, episode_id: str, *, side: str) -> str:
    normalized_base = str(base or "ARENA_LIQUIDITY").strip() or "ARENA_LIQUIDITY"
    suffix = str(episode_id or uuid.uuid4().hex)[-24:]
    return f"{normalized_base}_{side}_{suffix}"[:64]


def _normalize_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if symbol.isdigit() and len(symbol) < 3:
        return symbol.zfill(3)
    return symbol


def _instrument_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol:
            result[symbol] = dict(row)
    return result


def _reference_price(gateway: Any, symbol: str, instrument: dict[str, Any]) -> float:
    recent = _safe_call(gateway, "get_recent_trades", symbol, limit=1) or []
    if recent:
        price = _positive_float(recent[0].get("price"), 0.0)
        if price > 0:
            return price
    return _positive_float(instrument.get("initial_price"), 10.0)


def _positive_float(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        return float(fallback)
    if parsed > 0:
        return parsed
    return float(fallback)


def _optional_float(value: Any, *, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        parsed = float(value)
    except Exception:
        return default
    if math.isnan(parsed) or math.isinf(parsed):
        return default
    return parsed


def _round_to_tick(value: float, tick: float, *, mode: str) -> float:
    tick = max(float(tick or 0.01), 0.000001)
    scaled = float(value) / tick
    if mode == "down":
        rounded = math.floor(scaled + 1e-9) * tick
    elif mode == "up":
        rounded = math.ceil(scaled - 1e-9) * tick
    else:
        rounded = round(scaled) * tick
    decimals = max(0, min(8, len(f"{tick:.8f}".rstrip("0").split(".")[-1])))
    return round(max(tick, rounded), decimals)


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 3)


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _dt(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


__all__ = [
    "ArenaExperimentConfig",
    "ArenaExperimentRunner",
]
