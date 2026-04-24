from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import random
import threading
import time
from typing import Callable, Deque
import zlib

from agents.retail_persona import (
    RetailMarketSnapshot,
    RetailPersonaState,
    RetailPositionSnapshot,
    plan_retail_decision,
    sample_retail_persona,
    update_persona_state,
)
from app.runtime_gateway import RuntimeGateway
from stock_sim.services.engine_registry import engine_registry

from .trading_service import SubmitOrderRequest, TradingService

try:
    from observability.metrics import metrics
except Exception:  # pragma: no cover
    class _Dummy:
        def inc(self, *_a, **_kw):
            pass

    metrics = _Dummy()


RuntimeStateCallback = Callable[[str, str, int | None, int | None], None]


@dataclass
class MarketContext:
    symbol: str
    reference_price: float
    initial_price: float
    tick_size: float
    lot_size: int
    settlement_cycle: int
    best_bid: float | None
    best_ask: float | None
    phase: str
    trade_count: int
    cold_start: bool


@dataclass
class PositionContext:
    quantity: int
    available_qty: int
    avg_price: float
    holding_time_s: float
    unrealized_pnl_norm: float


class RuntimeRetailAgent:
    """Lightweight retail auto-trader owned by AgentService.

    Goals:
    - produce real orders through TradingService instead of synthetic bars
    - keep the lifecycle tiny and service-owned
    - bias early post-IPO/no-trade periods toward bounded micro-noise
    """

    def __init__(
        self,
        *,
        agent_id: str,
        strategy: str,
        trading_service: TradingService | None = None,
        state_callback: RuntimeStateCallback | None = None,
        runtime_gateway: RuntimeGateway | None = None,
        seed: int | None = None,
    ):
        self.agent_id = agent_id
        self.strategy = strategy or "noise"
        self._trading = trading_service
        self._state_callback = state_callback
        self._runtime_gateway = runtime_gateway or RuntimeGateway()
        self._stable_agent_key = _stable_agent_key(agent_id)
        self._rng = random.Random(seed if seed is not None else self._stable_agent_key)
        self._persona = sample_retail_persona(agent_id, self.strategy, seed=seed)
        self._lock = threading.RLock()
        self._wake_evt = threading.Event()
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self._paused = True
        self._start_time_ms: int | None = None
        self._history: dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=24))
        self._persona_state: dict[str, RetailPersonaState] = defaultdict(RetailPersonaState)
        self._holding_started_ms: dict[str, int] = {}
        self._turn = 0
        self._sell_blocked_until_day: dict[str, int] = {}

    def start(self) -> None:
        with self._lock:
            self._paused = False
            if self._start_time_ms is None:
                self._start_time_ms = int(time.time() * 1000)
            if self._thread is None or not self._thread.is_alive():
                self._stop_evt.clear()
                self._thread = threading.Thread(
                    target=self._run,
                    name=f"RetailAgent-{self.agent_id}",
                    daemon=True,
                )
                self._thread.start()
        self._wake_evt.set()
        self._emit_state("RUNNING", emit_heartbeat=True)

    def pause(self) -> None:
        with self._lock:
            self._paused = True
        self._wake_evt.set()
        self._emit_state("PAUSED", emit_heartbeat=True)

    def stop(self) -> None:
        with self._lock:
            self._paused = True
        self._stop_evt.set()
        self._wake_evt.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=1.5)
        self._thread = None
        self._emit_state("STOPPED", emit_heartbeat=False)

    def _run(self) -> None:
        while not self._stop_evt.is_set():
            if self._paused:
                self._wake_evt.wait(0.5)
                self._wake_evt.clear()
                continue
            self._emit_state("RUNNING", emit_heartbeat=True)
            try:
                self._step()
            except Exception:
                metrics.inc("runtime_retail_step_error")
            self._wake_evt.wait(self._decision_interval_s())
            self._wake_evt.clear()

    def _step(self) -> None:
        if not self._market_time_open():
            return
        symbols = engine_registry.symbols()
        if not symbols:
            return
        self._turn += 1
        symbol = symbols[self._turn % len(symbols)]
        ctx = self._build_context(symbol)
        if ctx is None:
            return
        self._history[symbol].append(ctx.reference_price)
        position = self._build_position_context(symbol, current_price=ctx.reference_price)
        decision = self._decide(ctx, position)
        if decision is None:
            return
        side, price, qty = decision
        sim_day = int(self._runtime_gateway.get_current_sim_day())
        if side == "sell" and self._sell_blocked_until_day.get(symbol) == sim_day:
            return
        if side == "sell":
            available_qty = self._available_sell_qty(symbol)
            if available_qty <= 0:
                if ctx.cold_start:
                    fallback = self._cold_start_buy_fallback(ctx)
                    if fallback is None:
                        return
                    side, price, qty = fallback
                else:
                    return
            else:
                max_lot_qty = (available_qty // max(ctx.lot_size, 1)) * max(ctx.lot_size, 1)
                qty = min(qty, max_lot_qty)
                if qty <= 0:
                    return
        trading = self._trading or TradingService()
        self._trading = trading
        result = trading.submit_order(
            SubmitOrderRequest(
                symbol=symbol,
                side=side,
                price=price,
                qty=qty,
                account_id=self.agent_id,
            )
        )
        if ctx.settlement_cycle >= 1 and side == "sell" and not bool((result or {}).get("ok", True)):
            self._sell_blocked_until_day[symbol] = sim_day
        metrics.inc("runtime_retail_orders_submitted")

    def _market_time_open(self) -> bool:
        try:
            snap = self._runtime_gateway.clock_snapshot()
            return bool((snap or {}).get("running", False))
        except Exception:
            pass
        return False

    def _build_context(self, symbol: str) -> MarketContext | None:
        engine = engine_registry.get(symbol)
        if engine is None:
            return None
        try:
            snap = engine.get_snapshot(5) if hasattr(engine, "get_snapshot") else getattr(engine, "snapshot", None)
        except Exception:
            snap = getattr(engine, "snapshot", None)
        if snap is None:
            return None
        instrument = getattr(engine, "instrument", None)
        tick_size = float(getattr(instrument, "tick_size", 0.01) or 0.01)
        lot_size = int(getattr(instrument, "lot_size", 1) or 1)
        settlement_cycle = int(getattr(instrument, "settlement_cycle", 0) or 0)
        initial_price = float(getattr(instrument, "initial_price", 0.0) or 0.0)
        best_bid = getattr(snap, "best_bid_price", None)
        best_ask = getattr(snap, "best_ask_price", None)
        reference_price = (
            getattr(snap, "last_price", None)
            or getattr(snap, "mid_price", None)
            or best_bid
            or best_ask
            or initial_price
        )
        try:
            book = engine.get_book(symbol) if hasattr(engine, "get_book") else None
        except Exception:
            book = None
        phase_obj = getattr(book, "phase", None) or getattr(engine, "phase", None)
        phase = getattr(phase_obj, "name", None) or str(phase_obj or "UNKNOWN")
        trade_count = len(getattr(engine, "trades", []) or [])
        cold_start = trade_count == 0 or (best_bid is None and best_ask is None)
        if reference_price is None or float(reference_price) <= 0:
            return None
        return MarketContext(
            symbol=symbol,
            reference_price=float(reference_price),
            initial_price=initial_price,
            tick_size=tick_size,
            lot_size=max(1, lot_size),
            settlement_cycle=settlement_cycle,
            best_bid=float(best_bid) if best_bid is not None else None,
            best_ask=float(best_ask) if best_ask is not None else None,
            phase=phase,
            trade_count=trade_count,
            cold_start=cold_start,
        )

    def _decide(self, ctx: MarketContext, position: PositionContext) -> tuple[str, float, int] | None:
        if ctx.cold_start:
            return self._decide_cold_start(ctx)
        history = list(self._history[ctx.symbol])
        market = RetailMarketSnapshot(
            symbol=ctx.symbol,
            current_price=ctx.reference_price,
            initial_price=ctx.initial_price if ctx.initial_price > 0 else ctx.reference_price,
            tick_size=ctx.tick_size,
            lot_size=ctx.lot_size,
            best_bid=ctx.best_bid,
            best_ask=ctx.best_ask,
            recent_prices=history,
        )
        position_snapshot = RetailPositionSnapshot(
            quantity=position.quantity,
            available_qty=position.available_qty,
            avg_price=position.avg_price,
            holding_time_s=position.holding_time_s,
            unrealized_pnl_norm=position.unrealized_pnl_norm,
        )
        state = self._persona_state[ctx.symbol]
        plan = plan_retail_decision(self._persona, market, position_snapshot, state, rng=self._rng)
        if plan is not None:
            state.last_expected_price = plan.expected_price
            state.last_action = plan.action
            update_persona_state(
                self._persona,
                state,
                position_snapshot,
                thesis_quality=plan.thesis_quality,
                invalidation_score=plan.invalidation_score,
            )
        if plan is None or plan.action == "hold":
            return None
        side = "buy" if plan.action == "buy" else "sell"
        qty = self._quantity_for_plan(ctx, position, plan)
        if qty <= 0:
            return None
        price = self._price_for_side(
            ctx,
            side,
            aggressive=plan.aggressive,
            expected_price=plan.expected_price,
        )
        return side, price, qty

    def _decide_cold_start(self, ctx: MarketContext) -> tuple[str, float, int] | None:
        """Bootstrap early continuous trading with bounded real orders.

        The parity split makes the started retail population naturally seed both
        sides of the book. Once a few trades exist, normal strategy logic takes over.
        """
        available_qty = self._available_sell_qty(ctx.symbol)
        preferred_buy = self.strategy in {"buy_the_dip", "momentum_chase"}
        parity_buy = self._cold_start_parity(ctx.symbol)
        if available_qty > 0:
            if self.strategy == "profit_taking":
                side = "sell"
            elif self.strategy in {"liquidity_noise", "noise", "mean_revert", "breakout", "vol_scaling"}:
                side = "buy" if parity_buy else "sell"
            else:
                side = "buy" if preferred_buy else ("buy" if parity_buy else "sell")
            if side == "sell":
                qty = min(max(ctx.lot_size, ctx.lot_size), available_qty)
                lot_qty = (qty // max(ctx.lot_size, 1)) * max(ctx.lot_size, 1)
                qty = lot_qty if lot_qty > 0 else min(available_qty, max(ctx.lot_size, 1))
                return side, self._price_for_side(ctx, side, aggressive=True), max(qty, 1)
            return side, self._price_for_side(ctx, side, aggressive=(preferred_buy or parity_buy)), ctx.lot_size
        return self._cold_start_buy_fallback(ctx, preferred_buy=preferred_buy, parity_buy=parity_buy)

    def _cold_start_buy_fallback(
        self,
        ctx: MarketContext,
        *,
        preferred_buy: bool | None = None,
        parity_buy: bool | None = None,
    ) -> tuple[str, float, int] | None:
        if preferred_buy is None:
            preferred_buy = self.strategy in {"buy_the_dip", "momentum_chase"}
        if parity_buy is None:
            parity_buy = self._cold_start_parity(ctx.symbol)
        if self.strategy == "profit_taking":
            return None
        elif self.strategy in {"liquidity_noise", "noise"}:
            if not parity_buy:
                return None
        elif not (preferred_buy or parity_buy):
            return None
        qty = ctx.lot_size
        return "buy", self._price_for_side(ctx, "buy", aggressive=(preferred_buy or parity_buy)), qty

    def _price_for_side(
        self,
        ctx: MarketContext,
        side: str,
        *,
        aggressive: bool,
        expected_price: float | None = None,
    ) -> float:
        tick = ctx.tick_size
        if side == "buy":
            if aggressive and ctx.best_ask is not None:
                return max(ctx.best_ask, ctx.reference_price)
            bid_anchor = ctx.best_bid if ctx.best_bid is not None else ctx.reference_price
            passive = bid_anchor + tick
            if expected_price is not None:
                passive = min(passive, max(tick, expected_price - tick))
            return max(tick, passive)
        if aggressive and ctx.best_bid is not None:
            return max(tick, min(ctx.best_bid, ctx.reference_price))
        ask_anchor = ctx.best_ask if ctx.best_ask is not None else ctx.reference_price
        passive = ask_anchor - tick
        if expected_price is not None:
            passive = max(passive, expected_price + tick)
        return max(tick, passive)

    def _decision_interval_s(self) -> float:
        if self._persona.family in {"liquidity_noise", "noise"}:
            return 0.4 + self._rng.random() * 0.5
        if self._persona.family in {"trend_follow", "buy_the_dip"}:
            return 0.55 + self._rng.random() * 0.55
        if self._persona.family == "slow_fundamental_allocator":
            return 1.0 + self._rng.random() * 0.8
        return 0.8 + self._rng.random() * 0.6

    def _cold_start_parity(self, symbol: str) -> bool:
        return (_stable_agent_key(f"{self.agent_id}:{symbol}") % 2) == 0

    def _available_sell_qty(self, symbol: str) -> int:
        try:
            return int(self._runtime_gateway.get_available_sell_qty(account_id=self.agent_id, symbol=symbol))
        except Exception:
            return 0

    def _build_position_context(self, symbol: str, *, current_price: float) -> PositionContext:
        quantity = 0
        frozen_qty = 0
        avg_price = 0.0
        try:
            snapshot = self._runtime_gateway.get_account_snapshot(self.agent_id) or {}
        except Exception:
            snapshot = {}
        for row in list(snapshot.get("positions") or []):
            if str(row.get("symbol") or "").strip().upper() != symbol:
                continue
            quantity = int(row.get("quantity") or 0)
            frozen_qty = int(row.get("frozen_qty") or 0)
            avg_price = float(row.get("avg_price") or 0.0)
            break
        available_qty = max(0, quantity - frozen_qty)
        now_ms = int(time.time() * 1000)
        if quantity > 0:
            self._holding_started_ms.setdefault(symbol, now_ms)
        else:
            self._holding_started_ms.pop(symbol, None)
        holding_started_ms = self._holding_started_ms.get(symbol, now_ms)
        holding_time_s = max(0.0, (now_ms - holding_started_ms) / 1000.0) if quantity > 0 else 0.0
        unrealized_pnl_norm = 0.0
        if quantity > 0 and avg_price > 0:
            unrealized_pnl_norm = (current_price - avg_price) / avg_price
        return PositionContext(
            quantity=quantity,
            available_qty=available_qty,
            avg_price=avg_price,
            holding_time_s=holding_time_s,
            unrealized_pnl_norm=unrealized_pnl_norm,
        )

    def _quantity_for_plan(self, ctx: MarketContext, position: PositionContext, plan) -> int:
        lots = max(1, int(getattr(plan, "quantity_lots", 1) or 1))
        if plan.action == "buy":
            return max(ctx.lot_size, ctx.lot_size * lots)
        if position.available_qty <= 0:
            return 0
        if plan.action == "reduce":
            qty = max(ctx.lot_size, ctx.lot_size * lots)
            return min(position.available_qty, qty)
        return position.available_qty

    def _emit_state(self, status: str, *, emit_heartbeat: bool) -> None:
        cb = self._state_callback
        if cb is None:
            return
        heartbeat_ms = int(time.time() * 1000) if emit_heartbeat else None
        try:
            cb(self.agent_id, status, heartbeat_ms, self._start_time_ms)
        except Exception:
            pass


__all__ = ["RuntimeRetailAgent", "RuntimeStateCallback"]


def _stable_agent_key(agent_id: str) -> int:
    return zlib.crc32(str(agent_id or "").encode("utf-8")) & 0xFFFFFFFF
