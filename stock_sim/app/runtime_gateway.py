"""Unified runtime access boundary for the desktop app.

This keeps a stable app-facing interface while delegating backend reads and
mutations to dedicated backend-side services.
"""
from __future__ import annotations

from typing import Any, Dict, List

try:
    from stock_sim.services.runtime_command_service import RuntimeCommandService  # type: ignore
    from stock_sim.services.runtime_query_service import RuntimeQueryService  # type: ignore
except Exception:  # pragma: no cover
    try:
        from services.runtime_command_service import RuntimeCommandService  # type: ignore
        from services.runtime_query_service import RuntimeQueryService  # type: ignore
    except Exception:  # pragma: no cover
        RuntimeCommandService = None  # type: ignore
        RuntimeQueryService = None  # type: ignore


class RuntimeGateway:
    def __init__(self):
        self._queries = RuntimeQueryService() if RuntimeQueryService is not None else None
        self._commands = RuntimeCommandService() if RuntimeCommandService is not None else None

    def list_account_ids(self) -> List[str]:
        if self._queries is None:
            return []
        return self._queries.list_account_ids()

    def get_current_sim_day(self) -> int:
        if self._queries is None:
            return 0
        return self._queries.get_current_sim_day()

    def get_current_run_id(self) -> str | None:
        if self._queries is None:
            return None
        return self._queries.get_current_run_id()

    def get_run_monitoring_snapshot(
        self,
        run_id: str,
    ) -> Dict[str, Any] | None:
        if self._queries is None:
            raise RuntimeError(
                "Run Monitoring query capability is unavailable"
            )
        reader = getattr(self._queries, "get_run_monitoring_snapshot", None)
        if not callable(reader):
            raise RuntimeError(
                "Run Monitoring query capability is unavailable"
            )
        return reader(run_id)

    def ensure_desktop_run(self) -> str | None:
        if self._commands is None:
            return self.get_current_run_id()
        return self._commands.ensure_desktop_run()

    def get_account_snapshot(self, account_id: str) -> Dict[str, Any] | None:
        if self._queries is None:
            return None
        return self._queries.get_account_snapshot(account_id)

    def get_available_sell_qty(self, *, account_id: str, symbol: str) -> int:
        if self._queries is None:
            return 0
        return self._queries.get_available_sell_qty(account_id=account_id, symbol=symbol)

    def bootstrap_agent_account(
        self,
        *,
        account_id: str,
        initial_cash: float,
        agent_type: str | None = None,
        strategy: str | None = None,
    ) -> None:
        if self._commands is None:
            return
        self._commands.bootstrap_agent_account(
            account_id=account_id,
            initial_cash=initial_cash,
            agent_type=agent_type,
            strategy=strategy,
        )

    def list_agent_bindings(self, *, include_all_runs: bool = False) -> List[Dict[str, Any]]:
        if self._queries is None:
            return []
        return self._queries.list_agent_bindings(include_all_runs=include_all_runs)

    def list_instruments(self, *, active_only: bool = True) -> List[Dict[str, Any]]:
        if self._queries is None:
            return []
        return self._queries.list_instruments(active_only=active_only)

    def update_agent_binding_meta(self, agent_id: str, **updates: Any) -> None:
        if self._commands is None:
            return
        self._commands.update_agent_binding_meta(agent_id, **updates)

    def create_instrument(
        self,
        *,
        symbol: str,
        name: str,
        price_step: float,
        initial_price: float,
        float_shares: int,
        market_cap: float,
        total_shares: int,
    ) -> bool:
        if self._commands is None:
            return False
        return self._commands.create_instrument(
            symbol=symbol,
            name=name,
            price_step=price_step,
            initial_price=initial_price,
            float_shares=float_shares,
            market_cap=market_cap,
            total_shares=total_shares,
        )

    def restore_runtime_instruments(self) -> Dict[str, Any]:
        if self._commands is None:
            return {"ok": False, "restored": 0, "symbols": [], "reason": "runtime command service unavailable"}
        return self._commands.restore_runtime_instruments()

    def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        price: float,
        qty: int,
        account_id: str,
    ) -> Dict[str, Any]:
        if self._commands is None:
            raise RuntimeError("runtime trading services unavailable")
        return self._commands.submit_order(
            symbol=symbol,
            side=side,
            price=price,
            qty=qty,
            account_id=account_id,
        )

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        if self._commands is None:
            raise RuntimeError("runtime trading services unavailable")
        return self._commands.cancel_order(order_id)

    def clock_snapshot(self) -> Dict[str, Any]:
        if self._commands is None:
            return {}
        return self._commands.clock_snapshot()

    def start_clock(self, *, sim_day: int | None, day_seconds: float, speed: float, allocate_pending_ipo: bool = False) -> Dict[str, Any]:
        if self._commands is None:
            return {}
        return self._commands.start_clock(
            sim_day=sim_day,
            day_seconds=day_seconds,
            speed=speed,
            allocate_pending_ipo=allocate_pending_ipo,
        )

    def pause_clock(self) -> Dict[str, Any]:
        if self._commands is None:
            return {}
        return self._commands.pause_clock()

    def resume_clock(self, *, day_seconds: float, speed: float) -> Dict[str, Any]:
        if self._commands is None:
            return {}
        return self._commands.resume_clock(day_seconds=day_seconds, speed=speed)

    def stop_clock(self) -> Dict[str, Any]:
        if self._commands is None:
            return {}
        return self._commands.stop_clock()

    def set_clock_speed(self, speed: float) -> Dict[str, Any]:
        if self._commands is None:
            return {}
        return self._commands.set_clock_speed(speed)

    def allocate_pending_ipo_distributions(self, *, sim_day: int) -> None:
        if self._commands is None:
            return
        self._commands.allocate_pending_ipo_distributions(sim_day=sim_day)

    def allocate_pending_ipo_distributions_if_running(self) -> None:
        if self._commands is None:
            return
        self._commands.allocate_pending_ipo_distributions_if_running()

    def ensure_open_instrument_retail_distributions(self, *, sim_day: int | None = None) -> Dict[str, Any]:
        if self._commands is None:
            return {}
        return self._commands.ensure_open_instrument_retail_distributions(sim_day=sim_day)

    def get_retail_holdings(self, symbol: str, *, limit: int = 8) -> Dict[str, Any] | None:
        if self._queries is None:
            return None
        return self._queries.get_retail_holdings(symbol, limit=limit)

    def get_bars(self, symbol: str, timeframe: str, *, limit: int) -> List[Dict[str, Any]]:
        if self._queries is None:
            return []
        return self._queries.get_bars(symbol, timeframe, limit=limit)

    def get_recent_trades(self, symbol: str, *, limit: int = 20) -> List[Dict[str, Any]]:
        if self._queries is None:
            return []
        return self._queries.get_recent_trades(symbol, limit=limit)

    def list_order_events(self, *, limit: int = 500, include_all_runs: bool = True) -> List[Dict[str, Any]]:
        if self._queries is None:
            return []
        return self._queries.list_order_events(limit=limit, include_all_runs=include_all_runs)

    def list_leaderboard_snapshots(self) -> List[Dict[str, Any]]:
        if self._queries is None:
            return []
        return self._queries.list_leaderboard_snapshots()

    def get_leaderboard_history(self, agent_id: str, *, window: str, points: int = 50) -> Dict[str, Any] | None:
        if self._queries is None:
            return None
        return self._queries.get_leaderboard_history(agent_id, window=window, points=points)


__all__ = ["RuntimeGateway"]
