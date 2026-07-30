from __future__ import annotations

import argparse
import json
import sys
import time
import zlib
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.retail_calibration_report import (
    CalibrationBookSample,
    CalibrationHoldingSample,
    CalibrationOrderSample,
    CalibrationTradeSample,
    RetailCalibrationReportCollector,
)
from agents.retail_strategy import allocate_retail_strategies
from app.runtime_gateway import RuntimeGateway
from app.services.runtime_retail_agent import RuntimeRetailAgent
from app.services.trading_service import SubmitOrderRequest
from stock_sim.core.const import Phase
from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.account_service import AccountService
from stock_sim.services.engine_registry import engine_registry
from stock_sim.services.sim_clock import ensure_sim_clock_started


DEFAULT_SIZES = (6, 20, 100)
DEFAULT_SYMBOLS = ("CAL_A", "CAL_B", "CAL_C")


class RecordingTradingService:
    def __init__(
        self,
        *,
        gateway: RuntimeGateway,
        collector: RetailCalibrationReportCollector,
        agents: dict[str, RuntimeRetailAgent],
        clock: "_EpisodeClock",
    ):
        self._gateway = gateway
        self._collector = collector
        self._agents = agents
        self._clock = clock

    def submit_order(self, req: SubmitOrderRequest) -> dict[str, Any]:
        pre = _book_snapshot(req.symbol)
        agent = self._agents.get(req.account_id)
        family = str(getattr(getattr(agent, "_persona", None), "family", "unknown") or "unknown")
        expected_price = _last_expected_price(agent, req.symbol)
        current_price = _current_price_from_book(pre)
        aggressive = _is_aggressive(req.side, float(req.price), pre)
        result = self._gateway.submit_order(
            symbol=req.symbol,
            side=req.side,
            price=float(req.price),
            qty=int(req.qty),
            account_id=req.account_id,
        )
        self._collector.record_order(
            CalibrationOrderSample(
                ts_ms=self._clock.ts_ms(),
                symbol=req.symbol,
                agent_id=req.account_id,
                family=family,
                side=req.side,
                price=float(req.price),
                current_price=current_price,
                expected_price=expected_price,
                aggressive=aggressive,
                bar_index=self._clock.step,
                post_open=True,
            )
        )
        for trade in list(result.get("trades") or []):
            if not isinstance(trade, dict):
                continue
            price = float(trade.get("price") or req.price)
            self._collector.record_trade(
                CalibrationTradeSample(
                    ts_ms=self._clock.ts_ms(),
                    symbol=str(trade.get("symbol") or req.symbol),
                    price=price,
                    post_open=True,
                )
            )
        return result


class _EpisodeClock:
    def __init__(self, *, bar_ms: int, slots_per_bar: int = 1):
        self.bar_ms = max(1, int(bar_ms))
        self.slot_ms = max(1, self.bar_ms // max(1, int(slots_per_bar)))
        self.step = 0
        self.order_seq = 0

    def ts_ms(self) -> int:
        self.order_seq += 1
        return self.step * self.bar_ms + self.order_seq * self.slot_ms


def run_episode(
    *,
    population: int,
    steps: int,
    symbols: tuple[str, ...],
    seed: int,
    bar_ms: int,
) -> dict[str, object]:
    _reset_runtime(symbols)
    gateway = RuntimeGateway()
    collector = RetailCalibrationReportCollector(bar_ms=bar_ms)
    clock = _EpisodeClock(bar_ms=bar_ms, slots_per_bar=population + 1)

    _create_symbols(gateway, symbols)
    strategies = allocate_retail_strategies(
        population,
        seed=seed + population,
        mode="post_ipo_cold_start",
    )
    agent_ids = [f"cal-{population:03d}-{idx + 1:03d}" for idx in range(population)]
    for agent_id, strategy in zip(agent_ids, strategies):
        gateway.bootstrap_agent_account(
            account_id=agent_id,
            initial_cash=1_000_000.0,
            agent_type="Retail",
            strategy=strategy,
        )
    _seed_inventory(agent_ids, strategies, symbols)

    agents: dict[str, RuntimeRetailAgent] = {}
    trading = RecordingTradingService(
        gateway=gateway,
        collector=collector,
        agents=agents,
        clock=clock,
    )
    for idx, (agent_id, strategy) in enumerate(zip(agent_ids, strategies)):
        agents[agent_id] = RuntimeRetailAgent(
            agent_id=agent_id,
            strategy=strategy,
            trading_service=trading,  # type: ignore[arg-type]
            runtime_gateway=gateway,
            seed=seed + idx,
        )

    gateway.start_clock(sim_day=1, day_seconds=max(steps, 1) * 10.0, speed=1.0)
    first_seen_position: dict[tuple[str, str], int] = {}
    last_seen_position: dict[tuple[str, str], int] = {}
    try:
        for step in range(steps):
            clock.step = step
            clock.order_seq = 0
            for symbol in symbols:
                _record_book(collector, symbol, ts_ms=step * bar_ms)
            for agent in agents.values():
                agent._step()
            for symbol in symbols:
                _record_book(collector, symbol, ts_ms=(step + 1) * bar_ms - 1)
            _record_holding_seen(gateway, agent_ids, symbols, step, first_seen_position, last_seen_position)
    finally:
        for agent in agents.values():
            try:
                agent.stop()
            except Exception:
                pass
        gateway.stop_clock()

    for (agent_id, symbol), first_step in first_seen_position.items():
        last_step = last_seen_position.get((agent_id, symbol), first_step)
        agent = agents.get(agent_id)
        family = str(getattr(getattr(agent, "_persona", None), "family", "unknown") or "unknown")
        collector.record_holding(
            CalibrationHoldingSample(
                agent_id=agent_id,
                family=family,
                symbol=symbol,
                holding_bars=float(max(1, last_step - first_step + 1)),
            )
        )

    report = collector.build()
    out = report.to_dict()
    out["population"] = population
    out["steps"] = steps
    out["seed"] = seed
    out["symbols"] = list(symbols)
    out["strategy_counts"] = dict(sorted(_counts(strategies).items()))
    return out


def run_batch(*, sizes: tuple[int, ...], steps: int, seed: int, output: Path, bar_ms: int) -> dict[str, object]:
    started = int(time.time() * 1000)
    episodes = [
        run_episode(
            population=size,
            steps=steps,
            symbols=DEFAULT_SYMBOLS,
            seed=seed,
            bar_ms=bar_ms,
        )
        for size in sizes
    ]
    payload: dict[str, object] = {
        "generated_at_ms": started,
        "seed": seed,
        "steps": steps,
        "bar_ms": bar_ms,
        "episodes": episodes,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _reset_runtime(symbols: tuple[str, ...]) -> None:
    clk = ensure_sim_clock_started()
    try:
        clk.stop_loop()
    except Exception:
        pass
    for symbol in symbols:
        try:
            engine_registry.remove(symbol)
        except Exception:
            pass
    models_init.init_models()


def _create_symbols(gateway: RuntimeGateway, symbols: tuple[str, ...]) -> None:
    for idx, symbol in enumerate(symbols):
        price = _initial_price_for_symbol(idx)
        gateway.create_instrument(
            symbol=symbol,
            name=symbol,
            price_step=0.01,
            initial_price=price,
            float_shares=1_000_000,
            market_cap=price * 1_000_000,
            total_shares=1_200_000,
        )
        engine = engine_registry.get(symbol)
        if engine is None:
            continue
        try:
            book = engine.get_book(symbol)
            book.phase = Phase.CONTINUOUS
            book.has_continuous_started = True
            book.snapshot.last_price = price
            book.snapshot.open_price = price
            book.snapshot.close_price = price
        except Exception:
            pass


def _seed_inventory(agent_ids: list[str], strategies: list[str], symbols: tuple[str, ...]) -> None:
    session = SessionLocal()
    try:
        svc = AccountService(session)
        anchor_slots = _sell_anchor_slots(agent_ids, strategies, symbols)
        seed_thresholds = {
            "profit_taking": 0.30,
            "liquidity_noise": 0.10,
            "mean_revert": 0.08,
            "momentum_chase": 0.06,
            "buy_the_dip": 0.06,
            "slow_fundamental_allocator": 0.08,
            "noise": 0.06,
        }
        for agent_id, strategy in zip(agent_ids, strategies):
            account = svc.get_or_create(agent_id, cash=1_000_000.0)
            for symbol_idx, symbol in anchor_slots.get(agent_id, []):
                pos = svc.get_position(account, symbol)
                pos.quantity = max(pos.quantity, 36)
                pos.avg_price = _initial_price_for_symbol(symbol_idx)
            key = _stable_key(f"{agent_id}:{strategy}:inventory")
            draw = (key % 10_000) / 10_000.0
            if draw > seed_thresholds.get(strategy, 0.25):
                continue
            symbol_idx = key % len(symbols)
            symbol = symbols[symbol_idx]
            pos = svc.get_position(account, symbol)
            pos.quantity = 80 + ((key // max(1, len(symbols))) % 4) * 40
            pos.avg_price = _initial_price_for_symbol(symbol_idx)
        session.commit()
    finally:
        session.close()


def _sell_anchor_slots(
    agent_ids: list[str],
    strategies: list[str],
    symbols: tuple[str, ...],
) -> dict[str, list[tuple[int, str]]]:
    anchors_per_symbol = 2 if len(agent_ids) <= 30 else 1
    used: set[str] = set()
    slots: dict[str, list[tuple[int, str]]] = {}
    candidates = list(zip(agent_ids, strategies))
    for symbol_idx, symbol in enumerate(symbols):
        chosen = 0
        ranked = sorted(
            (
                (_stable_key(f"{agent_id}:{symbol}:sell-anchor"), agent_id, strategy)
                for agent_id, strategy in candidates
                if _can_seed_cold_start_sell(agent_id, strategy, symbol)
            ),
            key=lambda item: item[0],
        )
        for _key, agent_id, _strategy in ranked:
            if agent_id in used and len(ranked) >= anchors_per_symbol * len(symbols):
                continue
            slots.setdefault(agent_id, []).append((symbol_idx, symbol))
            used.add(agent_id)
            chosen += 1
            if chosen >= anchors_per_symbol:
                break
    return slots


def _can_seed_cold_start_sell(agent_id: str, strategy: str, symbol: str) -> bool:
    if strategy == "profit_taking":
        return True
    if strategy == "noise":
        return False
    if strategy in {"buy_the_dip", "momentum_chase", "mean_revert"}:
        return False
    return (_stable_key(f"{agent_id}:{symbol}") % 2) != 0


def _record_book(collector: RetailCalibrationReportCollector, symbol: str, *, ts_ms: int) -> None:
    snap = _book_snapshot(symbol)
    collector.record_book(
        CalibrationBookSample(
            ts_ms=ts_ms,
            symbol=symbol,
            best_bid=snap.get("best_bid"),
            best_ask=snap.get("best_ask"),
            post_open=True,
        )
    )


def _record_holding_seen(
    gateway: RuntimeGateway,
    agent_ids: list[str],
    symbols: tuple[str, ...],
    step: int,
    first_seen: dict[tuple[str, str], int],
    last_seen: dict[tuple[str, str], int],
) -> None:
    symbol_set = {symbol.upper() for symbol in symbols}
    for agent_id in agent_ids:
        snap = gateway.get_account_snapshot(agent_id) or {}
        for pos in list(snap.get("positions") or []):
            symbol = str(pos.get("symbol") or "").strip().upper()
            if symbol not in symbol_set:
                continue
            if int(pos.get("quantity") or 0) <= 0:
                continue
            key = (agent_id, symbol)
            first_seen.setdefault(key, step)
            last_seen[key] = step


def _book_snapshot(symbol: str) -> dict[str, float | None]:
    engine = engine_registry.get(symbol)
    if engine is None:
        return {"best_bid": None, "best_ask": None, "last": None, "mid": None}
    try:
        snap = engine.get_snapshot(5) if hasattr(engine, "get_snapshot") else getattr(engine, "snapshot", None)
    except Exception:
        snap = getattr(engine, "snapshot", None)
    if snap is None:
        return {"best_bid": None, "best_ask": None, "last": None, "mid": None}
    return {
        "best_bid": _maybe_float(getattr(snap, "best_bid_price", None)),
        "best_ask": _maybe_float(getattr(snap, "best_ask_price", None)),
        "last": _maybe_float(getattr(snap, "last_price", None)),
        "mid": _maybe_float(getattr(snap, "mid_price", None)),
    }


def _current_price_from_book(snapshot: dict[str, float | None]) -> float | None:
    for key in ("last", "mid", "best_bid", "best_ask"):
        value = snapshot.get(key)
        if value is not None and value > 0:
            return float(value)
    return None


def _last_expected_price(agent: RuntimeRetailAgent | None, symbol: str) -> float | None:
    if agent is None:
        return None
    try:
        state = agent._persona_state[symbol]
        value = getattr(state, "last_expected_price", None)
        return float(value) if value is not None else None
    except Exception:
        return None


def _is_aggressive(side: str, price: float, snapshot: dict[str, float | None]) -> bool | None:
    if side == "buy":
        best_ask = snapshot.get("best_ask")
        return bool(best_ask is not None and price >= best_ask)
    if side == "sell":
        best_bid = snapshot.get("best_bid")
        return bool(best_bid is not None and price <= best_bid)
    return None


def _maybe_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _counts(values: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return out


def _initial_price_for_symbol(index: int) -> float:
    return 10.0 + index * 3.0


def _stable_key(value: str) -> int:
    return zlib.crc32(str(value or "").encode("utf-8")) & 0xFFFFFFFF


def _parse_sizes(value: str) -> tuple[int, ...]:
    sizes = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    return sizes or DEFAULT_SIZES


def main() -> None:
    parser = argparse.ArgumentParser(description="Run retail persona calibration episodes.")
    parser.add_argument("--sizes", default=",".join(str(size) for size in DEFAULT_SIZES))
    parser.add_argument("--steps", type=int, default=40)
    parser.add_argument("--seed", type=int, default=20260424)
    parser.add_argument("--bar-ms", type=int, default=30_000)
    parser.add_argument("--output", default="output/retail_calibration/episode_stats.json")
    args = parser.parse_args()

    payload = run_batch(
        sizes=_parse_sizes(args.sizes),
        steps=max(1, int(args.steps)),
        seed=int(args.seed),
        output=Path(args.output),
        bar_ms=max(1, int(args.bar_ms)),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
