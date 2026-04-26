from __future__ import annotations

import threading
import time
import zlib
from typing import Any, Callable

from app.runtime_gateway import RuntimeGateway
from app.services.model_registry_service import ModelRegistryService, ModelPolicy
from rl.action_parser import ActionParser
from rl.reward_builder import RewardBuilder


RuntimeStateCallback = Callable[[str, str, int | None, int | None], None]


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
        registry: ModelRegistryService | None = None,
        policy: ModelPolicy | None = None,
        decision_interval_s: float = 1.0,
    ):
        self.agent_id = agent_id
        self.model_id = model_id or "hold_model_v1"
        self.mode = mode or "inference"
        self._runtime_gateway = runtime_gateway or RuntimeGateway()
        self._state_callback = state_callback
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

    def start(self) -> None:
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
        reward = self._reward_builder.build(
            previous_account=self._previous_account,
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
        return {
            "observation": observation,
            "action": parsed,
            "execution_result": execution,
            "reward": reward,
        }

    def _build_observation(self) -> dict[str, Any]:
        symbols = [str(row.get("symbol")) for row in self._runtime_gateway.list_instruments(active_only=True) if row.get("symbol")]
        account = self._account_snapshot()
        snapshots: dict[str, Any] = {}
        bars: dict[str, Any] = {}
        for symbol in symbols:
            recent = self._runtime_gateway.get_recent_trades(symbol, limit=1)
            snapshots[symbol] = {"recent_trades": recent}
            bars[symbol] = {"1d": self._runtime_gateway.get_bars(symbol, "1d", limit=32)}
        return {
            "contract_version": "obs.v1",
            "market": {
                "symbols": symbols,
                "snapshots": snapshots,
                "bars": bars,
                "order_books": {},
            },
            "account": account,
            "context": {
                "run_id": self._runtime_gateway.get_current_run_id(),
                "episode_id": None,
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
            return {"accepted": True, "status": "NOOP", "orders": [], "trades": []}
        if action["action_type"] != "target_weight":
            return {"accepted": False, "status": "UNSUPPORTED", "orders": [], "trades": []}
        account = self._account_snapshot()
        equity = float(account.get("equity") or account.get("cash") or 0.0)
        weights = action["payload"].get("weights") or {}
        orders: list[dict[str, Any]] = []
        for symbol, weight in weights.items():
            price = self._last_price(symbol)
            if price <= 0:
                continue
            current_qty = self._current_position_qty(account, str(symbol))
            target_notional = equity * float(weight)
            delta_notional = target_notional - (current_qty * price)
            qty = int(abs(delta_notional) / price)
            if qty <= 0:
                continue
            side = "buy" if delta_notional >= 0 else "sell"
            try:
                result = self._runtime_gateway.submit_order(
                    symbol=str(symbol),
                    side=side,
                    price=price,
                    qty=qty,
                    account_id=self.agent_id,
                )
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            orders.append({"symbol": symbol, "side": side, "qty": qty, "price": price, "result": result})
        return {"accepted": True, "status": "EXECUTED", "orders": orders, "trades": []}

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

    @staticmethod
    def _current_position_qty(account: dict[str, Any], symbol: str) -> int:
        for position in account.get("positions") or []:
            if str(position.get("symbol") or "") == symbol:
                return int(position.get("quantity") or 0)
        return 0

    def _emit_state(self, status: str, *, emit_heartbeat: bool) -> None:
        if self._state_callback is None:
            return
        heartbeat_ms = int(time.time() * 1000) if emit_heartbeat else None
        try:
            self._state_callback(self.agent_id, status, heartbeat_ms, self._start_time_ms)
        except Exception:
            pass


__all__ = ["RuntimeModelAgent", "RuntimeStateCallback"]
