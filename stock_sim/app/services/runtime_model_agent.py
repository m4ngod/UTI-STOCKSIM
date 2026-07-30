from __future__ import annotations

import threading
import time
import zlib
from typing import Any, Callable

from app.runtime_gateway import RuntimeGateway
from app.services.model_registry_service import ModelRegistryService, ModelPolicy
from rl.action_parser import ActionParser
from rl.reward_builder import RewardBuilder

try:
    from stock_sim.services.engine_registry import engine_registry
except Exception:  # pragma: no cover
    engine_registry = None  # type: ignore

try:
    from stock_sim.persistence.models_imports import SessionLocal
    from stock_sim.services.training_episode_service import EpisodeAgentAccumulator, TrainingEpisodeService
except Exception:  # pragma: no cover
    SessionLocal = None  # type: ignore
    EpisodeAgentAccumulator = None  # type: ignore
    TrainingEpisodeService = None  # type: ignore


RuntimeStateCallback = Callable[[str, str, int | None, int | None], None]
ModelMetricsCallback = Callable[[str, dict[str, Any]], None]


class RuntimeModelAgent:
    """Small lifecycle wrapper for contract-driven model agents.

    This is intentionally modest: it proves the observation -> action -> reward
    loop without embedding PPO training or UI concerns into the app layer.
    """

    def __init__(
        self,
        *,
        agent_id: str,
        model_id: str,
        mode: str = "inference",
        runtime_gateway: RuntimeGateway | None = None,
        state_callback: RuntimeStateCallback | None = None,
        metrics_callback: ModelMetricsCallback | None = None,
        registry: ModelRegistryService | None = None,
        policy: ModelPolicy | None = None,
        decision_interval_s: float = 1.0,
        episode_id: str | None = None,
        arena_id: str | None = None,
        generation: int = 0,
        persist_transitions: bool = True,
    ):
        self.agent_id = agent_id
        self.model_id = model_id or "hold_model_v1"
        self.mode = mode or "inference"
        self.episode_id = episode_id
        self.arena_id = arena_id
        self.generation = int(generation)
        self._runtime_gateway = runtime_gateway or RuntimeGateway()
        self._state_callback = state_callback
        self._metrics_callback = metrics_callback
        self._registry = registry or ModelRegistryService()
        seed = zlib.crc32(f"{self.agent_id}:{self.model_id}".encode("utf-8")) & 0xFFFFFFFF
        self._policy = policy or self._registry.create_policy(self.model_id, seed=seed)
        self._decision_interval_s = max(0.1, float(decision_interval_s))
        self._parser = ActionParser()
        self._reward_builder = RewardBuilder()
        self._lock = threading.RLock()
        self._wake_evt = threading.Event()
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self._paused = True
        self._start_time_ms: int | None = None
        self._step_index = 0
        self.last_action: str | None = None
        self.last_reward: float | None = None
        self.last_execution: dict[str, Any] | None = None
        self._previous_account: dict[str, Any] | None = None
        self._persist_transitions = bool(persist_transitions)
        self._accumulator = (
            EpisodeAgentAccumulator(agent_id=agent_id, model_id=self.model_id)
            if EpisodeAgentAccumulator is not None
            else None
        )

    def start(self, *, emit_state: bool = True) -> None:
        with self._lock:
            self._paused = False
            if self._start_time_ms is None:
                self._start_time_ms = int(time.time() * 1000)
            if self._thread is None or not self._thread.is_alive():
                self._stop_evt.clear()
                self._thread = threading.Thread(
                    target=self._run,
                    name=f"ModelAgent-{self.agent_id}",
                    daemon=True,
                )
                self._thread.start()
        self._wake_evt.set()
        if emit_state:
            self._emit_state("RUNNING", emit_heartbeat=True)

    def pause(self, *, emit_state: bool = True) -> None:
        with self._lock:
            self._paused = True
        self._wake_evt.set()
        if emit_state:
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

    def complete_episode(self, episode_id: str | None = None) -> None:
        with self._lock:
            if episode_id is not None and self.episode_id is not None and str(episode_id) != str(self.episode_id):
                return
            self._persist_transitions = False
            self.episode_id = None

    def _run(self) -> None:
        while not self._stop_evt.is_set():
            if self._paused:
                self._wake_evt.wait(0.5)
                self._wake_evt.clear()
                continue
            self._emit_state("RUNNING", emit_heartbeat=True)
            try:
                self.step_once()
            except Exception:
                pass
            self._wake_evt.wait(self._decision_interval_s)
            self._wake_evt.clear()

    def step_once(self) -> dict[str, Any]:
        observation = self._build_observation()
        action = self._policy.act(observation)
        parsed = self._parser.parse(action)
        execution = self._execute(parsed)
        current_account = self._account_snapshot()
        previous_account = self._previous_account or observation.get("account")
        reward = self._reward_builder.build(
            previous_account=previous_account,
            current_account=current_account,
            action=parsed,
            execution_result=execution,
            benchmark_return=0.0,
        )
        self._previous_account = current_account
        self._step_index += 1
        self.last_action = parsed["action_type"]
        self.last_reward = float(reward["step_reward"])
        self.last_execution = execution
        transition = {
            "observation": observation,
            "action": parsed,
            "execution_result": execution,
            "reward": reward,
        }
        transition["learn_result"] = self._learn_if_enabled(transition)
        self._record_step(transition, account=current_account)
        return transition

    def _build_observation(self) -> dict[str, Any]:
        symbols = [str(row.get("symbol")) for row in self._runtime_gateway.list_instruments(active_only=True) if row.get("symbol")]
        account = self._account_snapshot()
        snapshots: dict[str, Any] = {}
        bars: dict[str, Any] = {}
        order_books: dict[str, Any] = {}
        for symbol in symbols:
            recent = self._runtime_gateway.get_recent_trades(symbol, limit=1)
            snapshots[symbol] = {"recent_trades": recent}
            bars[symbol] = {"1d": self._runtime_gateway.get_bars(symbol, "1d", limit=32)}
            order_books[symbol] = _book_top(symbol)
        return {
            "contract_version": "obs.v1",
            "market": {
                "symbols": symbols,
                "snapshots": snapshots,
                "bars": bars,
                "order_books": order_books,
            },
            "account": account,
            "context": {
                "run_id": self._runtime_gateway.get_current_run_id(),
                "episode_id": self.episode_id,
                "step_index": self._step_index,
                "sim_day": self._runtime_gateway.get_current_sim_day(),
                "clock_running": bool((self._runtime_gateway.clock_snapshot() or {}).get("running", False)),
                "symbol_universe": symbols,
                "agent_id": self.agent_id,
                "opponent_ids": [],
            },
            "features": {},
        }

    def _execute(self, action: dict[str, Any]) -> dict[str, Any]:
        if action["action_type"] == "hold":
            return {
                "accepted": True,
                "status": "NOOP",
                "orders": [],
                "trades": [],
                "execution_health": _execution_health(orders=[], trades=[], status="NOOP"),
            }
        if action["action_type"] == "order":
            return self._execute_order(action)
        if action["action_type"] != "target_weight":
            return {
                "accepted": False,
                "status": "UNSUPPORTED",
                "orders": [],
                "trades": [],
                "execution_health": _execution_health(orders=[], trades=[], status="UNSUPPORTED"),
            }
        account = self._account_snapshot()
        equity = float(account.get("equity") or account.get("cash") or 0.0)
        cash = float(account.get("cash") or 0.0)
        cash_buffer_ratio = _clamp_ratio(action["payload"].get("cash_buffer_ratio", 0.0))
        remaining_cash = max(0.0, cash - (equity * cash_buffer_ratio))
        weights = action["payload"].get("weights") or {}
        orders: list[dict[str, Any]] = []
        trades: list[dict[str, Any]] = []
        for symbol, weight in weights.items():
            symbol_s = str(symbol)
            reference_price = self._last_price(symbol)
            if reference_price <= 0:
                continue
            current_qty = self._current_position_qty(account, symbol_s)
            target_notional = equity * float(weight)
            delta_notional = target_notional - (current_qty * reference_price)
            requested_qty = int(abs(delta_notional) / reference_price)
            if requested_qty <= 0:
                continue
            side = "buy" if delta_notional >= 0 else "sell"
            price = self._marketable_price(symbol_s, side=side, fallback=reference_price)
            qty = requested_qty
            clip_reason: str | None = None
            if side == "buy":
                max_cash_qty = int(remaining_cash / max(price, 0.01))
                if qty > max_cash_qty:
                    qty = max(0, max_cash_qty)
                    clip_reason = "INSUFFICIENT_CASH"
                if qty <= 0:
                    orders.append(
                        _skipped_order(
                            symbol=symbol_s,
                            side=side,
                            requested_qty=requested_qty,
                            price=price,
                            reason="INSUFFICIENT_CASH",
                        )
                    )
                    continue
                remaining_cash = max(0.0, remaining_cash - abs(qty * price))
            else:
                sellable_qty = self._available_position_qty(account, symbol_s)
                if qty > sellable_qty:
                    qty = max(0, sellable_qty)
                    clip_reason = "NO_SELLABLE_QTY"
                if qty <= 0:
                    orders.append(
                        _skipped_order(
                            symbol=symbol_s,
                            side=side,
                            requested_qty=requested_qty,
                            price=price,
                            reason="NO_SELLABLE_QTY",
                        )
                    )
                    continue
            try:
                result = self._runtime_gateway.submit_order(
                    symbol=symbol_s,
                    side=side,
                    price=price,
                    qty=qty,
                    account_id=self.agent_id,
                )
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            order_record = {
                "symbol": symbol_s,
                "side": side,
                "qty": qty,
                "requested_qty": requested_qty,
                "price": price,
                "result": result,
            }
            if clip_reason:
                order_record["clip_reason"] = clip_reason
            orders.append(order_record)
            if isinstance(result, dict):
                for trade in result.get("trades") or []:
                    if isinstance(trade, dict):
                        trades.append(trade)
        return {
            "accepted": True,
            "status": "EXECUTED",
            "orders": orders,
            "trades": trades,
            "execution_health": _execution_health(orders=orders, trades=trades, status="EXECUTED"),
        }

    def _execute_order(self, action: dict[str, Any]) -> dict[str, Any]:
        payload = action.get("payload") or {}
        target = action.get("target") or {}
        symbol = str(payload.get("symbol") or target.get("symbol") or "").strip()
        side = str(payload.get("side") or "").strip().lower()
        price = float(payload.get("price") or 0.0)
        requested_qty = int(payload.get("quantity") or 0)
        orders: list[dict[str, Any]] = []
        trades: list[dict[str, Any]] = []
        if not symbol or side not in {"buy", "sell"} or price <= 0 or requested_qty <= 0:
            orders.append(
                _skipped_order(
                    symbol=symbol,
                    side=side,
                    requested_qty=max(0, requested_qty),
                    price=max(0.0, price),
                    reason="INVALID_ORDER_ACTION",
                )
            )
            return {
                "accepted": True,
                "status": "EXECUTED",
                "orders": orders,
                "trades": trades,
                "execution_health": _execution_health(orders=orders, trades=trades, status="EXECUTED"),
            }
        account = self._account_snapshot()
        qty = requested_qty
        clip_reason: str | None = None
        if side == "buy":
            cash = float(account.get("cash") or 0.0)
            max_cash_qty = int(cash / max(price, 0.01))
            if qty > max_cash_qty:
                qty = max(0, max_cash_qty)
                clip_reason = "INSUFFICIENT_CASH"
            if qty <= 0:
                orders.append(
                    _skipped_order(
                        symbol=symbol,
                        side=side,
                        requested_qty=requested_qty,
                        price=price,
                        reason="INSUFFICIENT_CASH",
                    )
                )
                return {
                    "accepted": True,
                    "status": "EXECUTED",
                    "orders": orders,
                    "trades": trades,
                    "execution_health": _execution_health(orders=orders, trades=trades, status="EXECUTED"),
                }
        else:
            sellable_qty = self._available_position_qty(account, symbol)
            if qty > sellable_qty:
                qty = max(0, sellable_qty)
                clip_reason = "NO_SELLABLE_QTY"
            if qty <= 0:
                orders.append(
                    _skipped_order(
                        symbol=symbol,
                        side=side,
                        requested_qty=requested_qty,
                        price=price,
                        reason="NO_SELLABLE_QTY",
                    )
                )
                return {
                    "accepted": True,
                    "status": "EXECUTED",
                    "orders": orders,
                    "trades": trades,
                    "execution_health": _execution_health(orders=orders, trades=trades, status="EXECUTED"),
                }
        try:
            result = self._runtime_gateway.submit_order(
                symbol=symbol,
                side=side,
                price=price,
                qty=qty,
                account_id=self.agent_id,
            )
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        order_record = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "requested_qty": requested_qty,
            "price": price,
            "result": result,
        }
        if clip_reason:
            order_record["clip_reason"] = clip_reason
        orders.append(order_record)
        if isinstance(result, dict):
            for trade in result.get("trades") or []:
                if isinstance(trade, dict):
                    trades.append(trade)
        return {
            "accepted": True,
            "status": "EXECUTED",
            "orders": orders,
            "trades": trades,
            "execution_health": _execution_health(orders=orders, trades=trades, status="EXECUTED"),
        }

    def _account_snapshot(self) -> dict[str, Any]:
        snapshot = self._runtime_gateway.get_account_snapshot(self.agent_id) or {}
        cash = float(snapshot.get("cash") or 0.0)
        equity = float(snapshot.get("equity") or cash)
        return {**snapshot, "account_id": self.agent_id, "cash": cash, "equity": equity}

    def _last_price(self, symbol: str) -> float:
        bars = self._runtime_gateway.get_bars(symbol, "1d", limit=1)
        if bars:
            try:
                return float(bars[-1].get("close") or bars[-1].get("last") or 0.0)
            except Exception:
                return 0.0
        try:
            for row in self._runtime_gateway.list_instruments(active_only=True):
                if str(row.get("symbol") or "") == str(symbol):
                    return float(row.get("initial_price") or row.get("last_price") or 0.0)
        except Exception:
            return 0.0
        return 0.0

    def _marketable_price(self, symbol: str, *, side: str, fallback: float) -> float:
        book = _book_top(symbol)
        if side == "buy" and book.get("best_ask") is not None:
            return max(float(book["best_ask"]), float(fallback))
        if side == "sell" and book.get("best_bid") is not None:
            return max(0.01, min(float(book["best_bid"]), float(fallback)))
        return float(fallback)

    @staticmethod
    def _current_position_qty(account: dict[str, Any], symbol: str) -> int:
        for position in account.get("positions") or []:
            if str(position.get("symbol") or "") == symbol:
                return int(position.get("quantity") or 0)
        return 0

    @staticmethod
    def _available_position_qty(account: dict[str, Any], symbol: str) -> int:
        for position in account.get("positions") or []:
            if str(position.get("symbol") or "") == symbol:
                quantity = int(position.get("quantity") or 0)
                frozen_qty = int(position.get("frozen_qty") or 0)
                return max(0, quantity - frozen_qty)
        return 0

    def _emit_state(self, status: str, *, emit_heartbeat: bool) -> None:
        if self._state_callback is None:
            return
        heartbeat_ms = int(time.time() * 1000) if emit_heartbeat else None
        try:
            self._state_callback(self.agent_id, status, heartbeat_ms, self._start_time_ms)
        except Exception:
            pass

    def _record_step(self, transition: dict[str, Any], *, account: dict[str, Any]) -> None:
        action = transition.get("action") or {}
        execution = transition.get("execution_result") or {}
        reward = transition.get("reward") or {}
        if self._accumulator is not None:
            self._accumulator.apply_step(
                account=account,
                action=action,
                execution_result=execution,
                reward=reward,
            )
        metrics_payload = {
            "model_id": self.model_id,
            "mode": self.mode,
            "episode_id": self.episode_id,
            "last_reward": float(reward.get("step_reward") or 0.0),
            "last_action": action.get("action_type"),
            "last_execution_health": execution.get("execution_health") if isinstance(execution, dict) else None,
            "equity": float(account.get("equity") or 0.0),
            "pnl": _pnl(account),
            "step_index": self._step_index,
            "reward_total": getattr(self._accumulator, "reward_total", None),
            "learn_result": transition.get("learn_result"),
        }
        if self._metrics_callback is not None:
            try:
                self._metrics_callback(self.agent_id, metrics_payload)
            except Exception:
                pass
        if not self._persist_transitions or not self.episode_id or SessionLocal is None or TrainingEpisodeService is None:
            return
        session = SessionLocal()
        try:
            service = TrainingEpisodeService(session)
            service.create_episode(
                episode_id=self.episode_id,
                arena_id=self.arena_id,
                run_id=self._runtime_gateway.get_current_run_id(),
                generation=self.generation,
                config={"source": "RuntimeModelAgent", "model_id": self.model_id, "mode": self.mode},
                sim_day_start=self._runtime_gateway.get_current_sim_day(),
            )
            service.record_transition(
                run_id=self._runtime_gateway.get_current_run_id(),
                episode_id=self.episode_id,
                arena_id=self.arena_id,
                agent_id=self.agent_id,
                model_id=self.model_id,
                step_index=self._step_index,
                observation=transition.get("observation"),
                action=action,
                execution_result=execution,
                reward=reward,
            )
            if self._accumulator is not None:
                service.upsert_result(self._accumulator, episode_id=self.episode_id, generation=self.generation)
                service.rank_episode(self.episode_id)
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    def _learn_if_enabled(self, transition: dict[str, Any]) -> dict[str, Any] | None:
        if self.mode not in {"online_train", "train"}:
            return None
        learner = getattr(self._policy, "learn", None)
        if not callable(learner):
            return {"ok": False, "reason": "LEARN_NOT_SUPPORTED", "model_id": self.model_id}
        try:
            result = learner(transition)
            return result if isinstance(result, dict) else {"ok": True}
        except Exception as exc:
            return {"ok": False, "reason": "LEARN_FAILED", "error": str(exc), "model_id": self.model_id}


def _pnl(account: dict[str, Any]) -> float:
    if account.get("pnl") is not None:
        return float(account.get("pnl") or 0.0)
    equity = float(account.get("equity") or account.get("cash") or 0.0)
    initial_cash = float(account.get("initial_cash") or account.get("starting_cash") or equity)
    return equity - initial_cash


def _execution_health(
    *,
    orders: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    status: str | None = None,
) -> dict[str, Any]:
    submitted_notional = 0.0
    filled_notional = 0.0
    submitted_order_count = 0
    filled_order_count = 0
    rejected_order_count = 0
    open_order_count = 0
    skipped_order_count = 0
    noop_count = 1 if str(status or "").upper() == "NOOP" else 0
    rejected_reasons: dict[str, int] = {}
    last_rejected_reason: str | None = None
    for order in orders:
        result = order.get("result") if isinstance(order.get("result"), dict) else {}
        status_s = str(result.get("status") or order.get("status") or "").upper()
        if status_s == "SKIPPED":
            skipped_order_count += 1
            reason = _order_reject_reason(order, result)
            if reason:
                rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1
                last_rejected_reason = reason
            continue
        qty = float(order.get("qty") or order.get("quantity") or 0.0)
        price = float(order.get("price") or 0.0)
        submitted_order_count += 1
        submitted_notional += abs(qty * price)
        if not bool(result.get("ok", True)) or status_s == "REJECTED":
            rejected_order_count += 1
            reason = _order_reject_reason(order, result)
            if reason:
                rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1
                last_rejected_reason = reason
            continue
        filled_qty = float(result.get("filled") or order.get("filled") or 0.0)
        nested_trades = result.get("trades") or []
        if filled_qty > 0 or nested_trades:
            filled_order_count += 1
        if status_s not in {"FILLED", "REJECTED", "CANCELED", "CANCELLED"} and filled_qty <= 0 and not nested_trades:
            open_order_count += 1
    for trade in trades:
        qty = float(trade.get("quantity") or trade.get("qty") or 0.0)
        price = float(trade.get("price") or 0.0)
        filled_notional += abs(qty * price)
    return {
        "submitted_order_count": submitted_order_count,
        "filled_order_count": filled_order_count,
        "open_order_count": open_order_count,
        "rejected_order_count": rejected_order_count,
        "skipped_order_count": skipped_order_count,
        "noop_count": noop_count,
        "trade_count": len(trades),
        "submitted_notional": submitted_notional,
        "filled_notional": filled_notional,
        "open_order_notional": max(0.0, submitted_notional - filled_notional),
        "rejected_reasons": rejected_reasons,
        "last_rejected_reason": last_rejected_reason,
    }


def _skipped_order(
    *,
    symbol: str,
    side: str,
    requested_qty: int,
    price: float,
    reason: str,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "side": side,
        "qty": 0,
        "requested_qty": int(requested_qty),
        "price": float(price),
        "skip_reason": reason,
        "status": "SKIPPED",
        "result": {"ok": True, "status": "SKIPPED", "reason": reason},
    }


def _order_reject_reason(order: dict[str, Any], result: dict[str, Any]) -> str | None:
    for value in (
        result.get("reason"),
        result.get("error"),
        order.get("skip_reason"),
        order.get("clip_reason"),
        result.get("status"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return None


def _clamp_ratio(value: Any) -> float:
    try:
        return max(0.0, min(0.95, float(value or 0.0)))
    except Exception:
        return 0.0


def _book_top(symbol: str) -> dict[str, float | None]:
    if engine_registry is None:
        return {"best_bid": None, "best_ask": None}
    try:
        engine = engine_registry.get(str(symbol))
    except Exception:
        engine = None
    if engine is None:
        return {"best_bid": None, "best_ask": None}
    try:
        snap = engine.get_snapshot(5) if hasattr(engine, "get_snapshot") else getattr(engine, "snapshot", None)
    except Exception:
        snap = getattr(engine, "snapshot", None)
    if snap is None:
        return {"best_bid": None, "best_ask": None}
    bid = getattr(snap, "best_bid_price", None)
    ask = getattr(snap, "best_ask_price", None)
    if bid is None or ask is None:
        direct = _book_top_from_live_book(engine, str(symbol))
        bid = bid if bid is not None else direct.get("best_bid")
        ask = ask if ask is not None else direct.get("best_ask")
    return {
        "best_bid": float(bid) if bid is not None else None,
        "best_ask": float(ask) if ask is not None else None,
    }


def _book_top_from_live_book(engine: Any, symbol: str) -> dict[str, float | None]:
    try:
        book = engine.get_book(str(symbol))
    except Exception:
        return {"best_bid": None, "best_ask": None}
    return {
        "best_bid": _best_live_price(getattr(book, "bids", {}) or {}, reverse=True),
        "best_ask": _best_live_price(getattr(book, "asks", {}) or {}, reverse=False),
    }


def _best_live_price(levels: dict[Any, list[Any]], *, reverse: bool) -> float | None:
    try:
        prices = sorted((float(price) for price in levels.keys()), reverse=reverse)
    except Exception:
        return None
    for price in prices:
        orders = levels.get(price) or []
        remaining = 0
        for order in orders:
            if not bool(getattr(order, "is_active", False)):
                continue
            remaining += int(getattr(order, "remaining", 0) or 0)
        if remaining > 0:
            return price
    return None


__all__ = ["ModelMetricsCallback", "RuntimeModelAgent", "RuntimeStateCallback"]
