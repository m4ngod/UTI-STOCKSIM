from __future__ import annotations

import json
from typing import Any, Dict, List

try:
    from stock_sim.persistence import models_init  # type: ignore
    from stock_sim.persistence.models_imports import SessionLocal  # type: ignore
    from stock_sim.persistence.models_account import Account as RuntimeAccount  # type: ignore
    from stock_sim.persistence.models_account_equity_snapshot import AccountEquitySnapshot  # type: ignore
    from stock_sim.persistence.models_agent_binding import AgentBinding  # type: ignore
    from stock_sim.persistence.models_position import Position as RuntimePosition  # type: ignore
    from stock_sim.persistence.models_bars import Bar1m, Bar1h, Bar1d  # type: ignore
    from stock_sim.persistence.models_order import OrderORM  # type: ignore
    from stock_sim.persistence.models_simulation_run import SimulationRun  # type: ignore
    from stock_sim.persistence.models_trade import TradeORM  # type: ignore
    from stock_sim.persistence.models_instrument import Instrument  # type: ignore
    from stock_sim.services.account_service import AccountService as RuntimeAccountService  # type: ignore
    from stock_sim.services.sim_clock import current_sim_day, ensure_sim_clock_started  # type: ignore
except Exception:  # pragma: no cover
    try:
        from persistence import models_init  # type: ignore
        from persistence.models_imports import SessionLocal  # type: ignore
        from persistence.models_account import Account as RuntimeAccount  # type: ignore
        from persistence.models_account_equity_snapshot import AccountEquitySnapshot  # type: ignore
        from persistence.models_agent_binding import AgentBinding  # type: ignore
        from persistence.models_position import Position as RuntimePosition  # type: ignore
        from persistence.models_bars import Bar1m, Bar1h, Bar1d  # type: ignore
        from persistence.models_order import OrderORM  # type: ignore
        from persistence.models_simulation_run import SimulationRun  # type: ignore
        from persistence.models_trade import TradeORM  # type: ignore
        from persistence.models_instrument import Instrument  # type: ignore
        from services.account_service import AccountService as RuntimeAccountService  # type: ignore
        from services.sim_clock import current_sim_day, ensure_sim_clock_started  # type: ignore
    except Exception:  # pragma: no cover
        models_init = None  # type: ignore
        SessionLocal = None  # type: ignore
        RuntimeAccount = None  # type: ignore
        AccountEquitySnapshot = None  # type: ignore
        AgentBinding = None  # type: ignore
        RuntimePosition = None  # type: ignore
        Bar1m = None  # type: ignore
        Bar1h = None  # type: ignore
        Bar1d = None  # type: ignore
        OrderORM = None  # type: ignore
        SimulationRun = None  # type: ignore
        TradeORM = None  # type: ignore
        Instrument = None  # type: ignore
        RuntimeAccountService = None  # type: ignore
        current_sim_day = None  # type: ignore
        ensure_sim_clock_started = None  # type: ignore


class RuntimeQueryService:
    def __init__(self) -> None:
        try:
            if models_init is not None:
                ensure = getattr(models_init, "ensure_models", None)
                if callable(ensure):
                    ensure()
                else:
                    models_init.init_models()
        except Exception:
            pass

    def list_account_ids(self) -> List[str]:
        if SessionLocal is None or RuntimeAccount is None:
            return []
        try:
            sess = SessionLocal()
        except Exception:
            return []
        try:
            ordered: List[str] = []
            if AgentBinding is not None:
                bindings = (
                    sess.query(AgentBinding)
                    .order_by(AgentBinding.updated_at.desc(), AgentBinding.created_at.desc(), AgentBinding.agent_name.asc())
                    .all()
                )
                for row in bindings:
                    account_id = str(getattr(row, "account_id", "") or "").strip()
                    if account_id and account_id not in ordered:
                        ordered.append(account_id)
            rows = sess.query(RuntimeAccount).order_by(RuntimeAccount.id.asc()).all()
            for row in rows:
                account_id = str(getattr(row, "id", "")).strip()
                if account_id and account_id not in ordered:
                    ordered.append(account_id)
            return ordered
        except Exception:
            return []
        finally:
            sess.close()

    def get_current_sim_day(self) -> int:
        if current_sim_day is None:
            return 0
        try:
            return int(current_sim_day() or 0)
        except Exception:
            return 0

    def get_current_run_id(self) -> str | None:
        if ensure_sim_clock_started is None:
            return None
        try:
            clk = ensure_sim_clock_started()
            snap = clk.snapshot() if hasattr(clk, "snapshot") else {}
            run_id = str((snap or {}).get("run_id") or "").strip()
            return run_id or None
        except Exception:
            return None

    def get_run_monitoring_snapshot(
        self,
        run_id: str,
    ) -> Dict[str, Any] | None:
        """Return one internal, read-only aggregate for the V2 live Adapter."""

        normalized_run_id = str(run_id or "").strip()
        if (
            not normalized_run_id
            or SessionLocal is None
            or SimulationRun is None
        ):
            raise RuntimeError("Run Monitoring persistence is unavailable")
        try:
            sess = SessionLocal()
        except Exception as error:
            raise RuntimeError(
                "Run Monitoring persistence session is unavailable"
            ) from error
        try:
            run = sess.get(SimulationRun, normalized_run_id)
            if run is None:
                return None
            bindings = []
            if AgentBinding is not None:
                bindings = (
                    sess.query(AgentBinding)
                    .filter(AgentBinding.run_id == normalized_run_id)
                    .order_by(
                        AgentBinding.updated_at.desc(),
                        AgentBinding.agent_name.asc(),
                    )
                    .all()
                )
            binding_context = []
            merged_meta: Dict[str, Any] = {}
            account_ids = []
            for binding in bindings:
                meta = _safe_parse_meta(getattr(binding, "meta", None))
                if not merged_meta and meta:
                    merged_meta = meta
                account_id = str(
                    getattr(binding, "account_id", "") or ""
                ).strip()
                if account_id:
                    account_ids.append(account_id)
                binding_context.append(
                    " · ".join(
                        value
                        for value in (
                            str(getattr(binding, "agent_name", "") or ""),
                            str(meta.get("strategy") or meta.get("model_id") or ""),
                            account_id,
                        )
                        if value
                    )
                )

            positions = []
            if RuntimePosition is not None and account_ids:
                for position in (
                    sess.query(RuntimePosition)
                    .filter(RuntimePosition.account_id.in_(account_ids))
                    .order_by(
                        RuntimePosition.account_id.asc(),
                        RuntimePosition.symbol.asc(),
                    )
                    .all()
                ):
                    positions.append(
                        f"{getattr(position, 'account_id', '')} · "
                        f"{getattr(position, 'symbol', '')} · "
                        f"{int(getattr(position, 'quantity', 0) or 0)}"
                    )

            orders = []
            if OrderORM is not None:
                for order in (
                    sess.query(OrderORM)
                    .filter(OrderORM.run_id == normalized_run_id)
                    .order_by(OrderORM.ts_last.desc(), OrderORM.id.desc())
                    .limit(20)
                    .all()
                ):
                    orders.append(
                        f"{getattr(order, 'id', '')} · "
                        f"{getattr(order, 'symbol', '')} · "
                        f"{_enum_value(getattr(order, 'status', ''))}"
                    )

            fills = []
            market_symbols = set()
            if TradeORM is not None:
                for trade in (
                    sess.query(TradeORM)
                    .filter(TradeORM.run_id == normalized_run_id)
                    .order_by(TradeORM.ts.desc(), TradeORM.id.desc())
                    .limit(20)
                    .all()
                ):
                    symbol = str(getattr(trade, "symbol", "") or "")
                    if symbol:
                        market_symbols.add(symbol)
                    fills.append(
                        f"{getattr(trade, 'id', '')} · {symbol} · "
                        f"{int(getattr(trade, 'quantity', 0) or 0)} @ "
                        f"{float(getattr(trade, 'price', 0.0) or 0.0):.4f}"
                    )
            if OrderORM is not None and not market_symbols:
                market_symbols.update(
                    str(row[0])
                    for row in (
                        sess.query(OrderORM.symbol)
                        .filter(OrderORM.run_id == normalized_run_id)
                        .distinct()
                        .all()
                    )
                    if row[0]
                )

            requested_execution = merged_meta.get("requested_execution")
            effective_execution = merged_meta.get("effective_execution")
            override_reasons = merged_meta.get("execution_override_reasons")
            if not isinstance(requested_execution, dict):
                requested_execution = {
                    "speed_profile": str(
                        getattr(run, "speed_profile", None) or "default"
                    )
                }
            if not isinstance(effective_execution, dict):
                effective_execution = dict(requested_execution)
            if not isinstance(override_reasons, dict):
                override_reasons = {}

            last_sim_day = int(getattr(run, "last_sim_day", 0) or 0)
            sim_end_day = getattr(run, "sim_end_day", None)
            total_nodes = int(
                merged_meta.get("total_nodes")
                or sim_end_day
                or max(last_sim_day, 1)
            )
            completed_nodes = min(
                int(merged_meta.get("completed_nodes") or last_sim_day),
                total_nodes,
            )
            failure_reason = str(
                getattr(run, "failure_reason", "") or ""
            ).strip()
            alerts = []
            if failure_reason:
                alerts.append(
                    {
                        "code": "runtime_run_failure",
                        "severity": "error",
                        "message": failure_reason,
                    }
                )
            strategy_id = str(
                merged_meta.get("strategy")
                or merged_meta.get("model_id")
                or ""
            ).strip() or None
            return {
                "run_id": normalized_run_id,
                "name": str(
                    getattr(run, "name", "") or normalized_run_id
                ),
                "scenario_name": (
                    str(
                        getattr(run, "scenario_name", "")
                        or ""
                    ).strip()
                    or None
                ),
                "scenario_set_id": (
                    str(
                        merged_meta.get("scenario_set_id")
                        or getattr(run, "environment_tag", None)
                        or ""
                    ).strip()
                    or None
                ),
                "strategy_id": strategy_id,
                "reproduction_manifest_id": (
                    str(
                        merged_meta.get("reproduction_manifest_id")
                        or ""
                    ).strip()
                    or None
                ),
                "status": str(getattr(run, "status", "") or "created"),
                "failure_reason": failure_reason or None,
                "started_at": getattr(run, "started_at", None),
                "updated_at": getattr(run, "updated_at", None),
                "ended_at": getattr(run, "ended_at", None),
                "sim_start_day": getattr(run, "sim_start_day", None),
                "last_sim_day": last_sim_day,
                "sim_end_day": sim_end_day,
                "last_sim_dt": getattr(run, "last_sim_dt", None),
                "current_node_id": str(
                    merged_meta.get("current_node_id")
                    or f"RUN-{str(getattr(run, 'status', 'created')).upper()}"
                ),
                "current_node_label": str(
                    merged_meta.get("current_node_label")
                    or str(getattr(run, "status", "created")).replace("_", " ").title()
                ),
                "completed_nodes": completed_nodes,
                "total_nodes": total_nodes,
                "task_id": (
                    str(
                        merged_meta.get("diagnostic_task_id")
                        or merged_meta.get("arena_id")
                        or ""
                    ).strip()
                    or None
                ),
                "requested_execution": requested_execution,
                "effective_execution": effective_execution,
                "execution_override_reasons": override_reasons,
                "alerts": alerts,
                "market_context": sorted(market_symbols),
                "account_context": binding_context,
                "position_context": positions,
                "order_context": orders,
                "fill_context": fills,
            }
        except Exception:
            try:
                sess.rollback()
            except Exception:
                pass
            raise
        finally:
            sess.close()

    def list_agent_bindings(self, *, include_all_runs: bool = False) -> List[Dict[str, Any]]:
        if SessionLocal is None or AgentBinding is None:
            return []
        try:
            sess = SessionLocal()
        except Exception:
            return []
        try:
            active_run_id = self.get_current_run_id()
            if active_run_id is None and not include_all_runs:
                return []
            query = sess.query(AgentBinding)
            if not include_all_runs:
                query = query.filter(AgentBinding.run_id == active_run_id)
            rows = query.order_by(AgentBinding.updated_at.desc(), AgentBinding.agent_name.asc()).all()
            out: List[Dict[str, Any]] = []
            for row in rows:
                meta_raw = getattr(row, "meta", None)
                try:
                    meta = json.loads(meta_raw) if meta_raw else None
                except Exception:
                    meta = None
                out.append(
                    {
                        "agent_name": str(getattr(row, "agent_name", "") or ""),
                        "agent_type": str(getattr(row, "agent_type", "") or ""),
                        "account_id": str(getattr(row, "account_id", "") or ""),
                        "run_id": str(getattr(row, "run_id", "") or ""),
                        "meta": meta if isinstance(meta, dict) else None,
                    }
                )
            return out
        except Exception:
            return []
        finally:
            sess.close()

    def list_instruments(self, *, active_only: bool = True) -> List[Dict[str, Any]]:
        if SessionLocal is None or Instrument is None:
            return []
        try:
            sess = SessionLocal()
        except Exception:
            return []
        try:
            query = sess.query(Instrument)
            if active_only:
                query = query.filter(Instrument.is_active.is_(True))
            rows = query.order_by(Instrument.symbol.asc()).all()
            out: List[Dict[str, Any]] = []
            for row in rows:
                created_at = getattr(row, "created_at", None)
                out.append(
                    {
                        "symbol": str(getattr(row, "symbol", "") or ""),
                        "name": str(getattr(row, "name", "") or getattr(row, "symbol", "") or ""),
                        "tick_size": float(getattr(row, "tick_size", 0.01) or 0.01),
                        "lot_size": int(getattr(row, "lot_size", 1) or 1),
                        "min_qty": int(getattr(row, "min_qty", 1) or 1),
                        "settlement_cycle": int(getattr(row, "settlement_cycle", 1) or 1),
                        "market_cap": getattr(row, "market_cap", None),
                        "total_shares": getattr(row, "total_shares", None),
                        "free_float_shares": getattr(row, "free_float_shares", None),
                        "initial_price": getattr(row, "initial_price", None),
                        "is_active": bool(getattr(row, "is_active", True)),
                        "ipo_opened": bool(getattr(row, "ipo_opened", False)),
                        "created_at": created_at.isoformat() if created_at is not None else None,
                    }
                )
            return out
        except Exception:
            return []
        finally:
            sess.close()

    def get_account_snapshot(self, account_id: str) -> Dict[str, Any] | None:
        if SessionLocal is None or RuntimeAccount is None or RuntimePosition is None:
            return None
        try:
            sess = SessionLocal()
        except Exception:
            return None
        try:
            acc = sess.get(RuntimeAccount, account_id)
            if acc is None:
                return None
            positions = (
                sess.query(RuntimePosition)
                .filter(RuntimePosition.account_id == account_id)
                .order_by(RuntimePosition.symbol.asc())
                .all()
            )
            pos_out: List[Dict[str, Any]] = []
            market_value = 0.0
            for pos in positions:
                qty = int(getattr(pos, "quantity", 0) or 0)
                avg_price = float(getattr(pos, "avg_price", 0.0) or 0.0)
                frozen_qty = int(getattr(pos, "frozen_qty", 0) or 0)
                borrowed_qty = int(getattr(pos, "borrowed_qty", 0) or 0)
                market_value += qty * avg_price
                pos_out.append(
                    {
                        "symbol": str(getattr(pos, "symbol", "") or ""),
                        "quantity": qty,
                        "frozen_qty": frozen_qty,
                        "avg_price": avg_price,
                        "borrowed_qty": borrowed_qty,
                        "pnl_unreal": 0.0,
                    }
                )
            cash = float(getattr(acc, "cash", 0.0) or 0.0)
            frozen_cash = float(getattr(acc, "frozen_cash", 0.0) or 0.0)
            frozen_fee = float(getattr(acc, "frozen_fee", 0.0) or 0.0)
            equity = max(0.0, cash + frozen_cash + market_value)
            utilization = 0.0
            if equity > 0:
                utilization = min(max((frozen_cash + frozen_fee) / equity, 0.0), 1.0)
            sim_day = getattr(acc, "sim_day", None)
            return {
                "account_id": str(account_id),
                "cash": cash,
                "frozen_cash": frozen_cash,
                "frozen_fee": frozen_fee,
                "positions": pos_out,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "equity": equity,
                "utilization": utilization,
                "sim_day": str(sim_day) if sim_day is not None else str(self.get_current_sim_day()),
            }
        except Exception:
            return None
        finally:
            sess.close()

    def get_available_sell_qty(self, *, account_id: str, symbol: str) -> int:
        if SessionLocal is None or RuntimeAccountService is None or models_init is None:
            return 0
        normalized_account_id = str(account_id or "").strip()
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_account_id or not normalized_symbol:
            return 0
        try:
            sess = SessionLocal()
        except Exception:
            return 0
        try:
            accounts = RuntimeAccountService(sess)
            account = accounts.get_or_create(normalized_account_id)
            position = accounts.get_position(account, normalized_symbol)
            quantity = int(getattr(position, "quantity", 0) or 0)
            frozen_qty = int(getattr(position, "frozen_qty", 0) or 0)
            available = max(0, quantity - frozen_qty)
            instrument = sess.get(Instrument, normalized_symbol) if Instrument is not None else None
            settlement_cycle = int(getattr(instrument, "settlement_cycle", 0) or 0) if instrument is not None else 0
            if (
                settlement_cycle >= 1
                and TradeORM is not None
                and self._agent_type_for_account(sess, normalized_account_id) == "RETAIL"
            ):
                trade_query = sess.query(TradeORM.quantity).filter(
                    TradeORM.buy_account_id == normalized_account_id,
                    TradeORM.symbol == normalized_symbol,
                    TradeORM.sim_day == self.get_current_sim_day(),
                )
                active_run_id = self.get_current_run_id()
                if active_run_id:
                    trade_query = trade_query.filter(TradeORM.run_id == active_run_id)
                same_day_buy_qty = sum(max(0, int(qty or 0)) for (qty,) in trade_query.all())
                available = max(0, available - same_day_buy_qty)
            return available
        except Exception:
            try:
                sess.rollback()
            except Exception:
                pass
            return 0
        finally:
            sess.close()

    def _agent_type_for_account(self, sess, account_id: str) -> str:
        normalized = str(account_id or "").strip()
        if not normalized:
            return "RETAIL"
        upper = normalized.upper()
        if "MODEL" in upper:
            return "MODEL"
        if "LIQUIDITY" in upper:
            return "LIQUIDITY"
        if AgentBinding is not None:
            try:
                row = (
                    sess.query(AgentBinding.agent_type)
                    .filter(AgentBinding.account_id == normalized)
                    .one_or_none()
                )
                if row is not None:
                    return str(row[0] or "RETAIL").strip().upper() or "RETAIL"
            except Exception:
                pass
        return "RETAIL"

    def get_retail_holdings(self, symbol: str, *, limit: int = 8) -> Dict[str, Any] | None:
        if SessionLocal is None or RuntimePosition is None:
            return None
        sym = str(symbol or "").strip().upper()
        if not sym:
            return None
        try:
            sess = SessionLocal()
        except Exception:
            return None
        try:
            positions = (
                sess.query(RuntimePosition)
                .filter(RuntimePosition.symbol == sym, RuntimePosition.quantity > 0)
                .order_by(RuntimePosition.quantity.desc())
                .limit(max(int(limit), 1))
                .all()
            )
            if not positions:
                return {
                    "labels": [],
                    "pct": [],
                    "authoritative": True,
                    "source": "runtime-position-book",
                    "placeholder": False,
                }
            name_map: Dict[str, str] = {}
            if AgentBinding is not None:
                bindings = (
                    sess.query(AgentBinding)
                    .filter(AgentBinding.account_id.in_([p.account_id for p in positions]))
                    .all()
                )
                name_map = {str(b.account_id): str(b.agent_name) for b in bindings}
            total_qty = sum(max(int(getattr(p, "quantity", 0) or 0), 0) for p in positions)
            if total_qty <= 0:
                return {
                    "labels": [],
                    "pct": [],
                    "authoritative": True,
                    "source": "runtime-position-book",
                    "placeholder": False,
                }
            labels: List[str] = []
            pct: List[float] = []
            for pos in positions:
                qty = max(int(getattr(pos, "quantity", 0) or 0), 0)
                if qty <= 0:
                    continue
                labels.append(name_map.get(str(pos.account_id), str(pos.account_id)))
                pct.append(round(qty * 100.0 / total_qty, 2))
            return {
                "labels": labels,
                "pct": pct,
                "authoritative": True,
                "source": "runtime-position-book",
                "placeholder": False,
            }
        except Exception:
            return None
        finally:
            sess.close()

    def get_bars(self, symbol: str, timeframe: str, *, limit: int) -> List[Dict[str, Any]]:
        if SessionLocal is None:
            return []
        sym = str(symbol or "").strip().upper()
        if not sym or int(limit) <= 0:
            return []
        model = {
            "1m": Bar1m,
            "5m": None,
            "15m": None,
            "60m": Bar1h,
            "1d": Bar1d,
        }.get(str(timeframe))
        if model is None:
            return []
        try:
            sess = SessionLocal()
        except Exception:
            return []
        try:
            active_run_id = self.get_current_run_id()
            query = sess.query(model).filter(model.symbol == sym)
            rows = []
            resolved_scope = "unscoped"
            if active_run_id is not None:
                rows = (
                    query.filter(model.run_id == active_run_id)
                    .order_by(model.ts.desc())
                    .limit(int(limit))
                    .all()
                )
                if rows:
                    resolved_scope = "active-run"
                else:
                    latest_run_id = self._latest_history_run_id(sess, model, sym)
                    if latest_run_id is not None:
                        rows = (
                            query.filter(model.run_id == latest_run_id)
                            .order_by(model.ts.desc())
                            .limit(int(limit))
                            .all()
                        )
                        resolved_scope = "latest-persisted-run"
            if not rows:
                rows = (
                    query.order_by(model.ts.desc())
                    .limit(int(limit))
                    .all()
                )
                resolved_scope = "unscoped"
            if not rows:
                return []
            rows.reverse()
            out: List[Dict[str, Any]] = []
            for row in rows:
                ts_ms = self._bar_ts_ms(row, str(timeframe))
                if ts_ms is None:
                    continue
                out.append(
                    {
                        "ts": ts_ms,
                        "open": float(getattr(row, "open", 0.0) or 0.0),
                        "high": float(getattr(row, "high", 0.0) or 0.0),
                        "low": float(getattr(row, "low", 0.0) or 0.0),
                        "close": float(getattr(row, "close", 0.0) or 0.0),
                        "volume": float(getattr(row, "volume", 0.0) or 0.0),
                        "run_id": str(getattr(row, "run_id", "") or "") or None,
                        "_history_scope": resolved_scope,
                    }
                )
            return out
        except Exception:
            return []
        finally:
            sess.close()

    @staticmethod
    def _latest_history_run_id(sess, model, symbol: str) -> str | None:
        try:
            row = (
                sess.query(model.run_id)
                .filter(model.symbol == symbol, model.run_id.isnot(None))
                .order_by(model.ts.desc())
                .first()
            )
            value = str(row[0] or "").strip() if row else ""
            return value or None
        except Exception:
            return None

    @staticmethod
    def _bar_ts_ms(row: object, timeframe: str) -> int | None:
        if timeframe == "1d":
            try:
                sim_day = int(getattr(row, "sim_day", 0) or 0)
                return sim_day * 24 * 60 * 60 * 1000
            except Exception:
                pass
        ts = getattr(row, "ts", None)
        try:
            return int(ts.timestamp() * 1000)
        except Exception:
            return None

    def get_recent_trades(self, symbol: str, *, limit: int = 20) -> List[Dict[str, Any]]:
        if SessionLocal is None or TradeORM is None:
            return []
        sym = str(symbol or "").strip().upper()
        if not sym or int(limit) <= 0:
            return []
        try:
            sess = SessionLocal()
        except Exception:
            return []
        try:
            active_run_id = self.get_current_run_id()
            base_query = sess.query(TradeORM).filter(TradeORM.symbol == sym)
            rows = []
            resolved_scope = "unscoped"
            if active_run_id is not None:
                rows = (
                    base_query.filter(TradeORM.run_id == active_run_id)
                    .order_by(TradeORM.ts.desc())
                    .limit(int(limit))
                    .all()
                )
                if rows:
                    resolved_scope = "active-run"
                else:
                    latest_run_id = self._latest_trade_run_id(sess, sym)
                    if latest_run_id is not None:
                        rows = (
                            base_query.filter(TradeORM.run_id == latest_run_id)
                            .order_by(TradeORM.ts.desc())
                            .limit(int(limit))
                            .all()
                        )
                        resolved_scope = "latest-persisted-run"
            if not rows:
                rows = (
                    base_query.order_by(TradeORM.ts.desc())
                    .limit(int(limit))
                    .all()
                )
            out: List[Dict[str, Any]] = []
            for row in rows:
                ts_value = getattr(row, "ts", None)
                ts_ms = None
                try:
                    if ts_value is not None and hasattr(ts_value, "timestamp"):
                        ts_ms = int(float(ts_value.timestamp()) * 1000)
                except Exception:
                    ts_ms = None
                out.append(
                    {
                        "trade_id": str(getattr(row, "id", "") or ""),
                        "symbol": str(getattr(row, "symbol", "") or ""),
                        "price": float(getattr(row, "price", 0.0) or 0.0),
                        "qty": int(getattr(row, "quantity", 0) or 0),
                        "buy_account_id": str(getattr(row, "buy_account_id", "") or ""),
                        "sell_account_id": str(getattr(row, "sell_account_id", "") or ""),
                        "buy_order_id": str(getattr(row, "buy_order_id", "") or ""),
                        "sell_order_id": str(getattr(row, "sell_order_id", "") or ""),
                        "ts": ts_ms,
                        "history_scope": resolved_scope,
                        "run_id": str(getattr(row, "run_id", "") or "") or None,
                    }
                )
            return out
        except Exception:
            return []
        finally:
            sess.close()

    def list_order_events(self, *, limit: int = 500, include_all_runs: bool = True) -> List[Dict[str, Any]]:
        if SessionLocal is None:
            return []
        max_rows = max(1, min(int(limit or 500), 5000))
        try:
            sess = SessionLocal()
        except Exception:
            return []
        try:
            active_run_id = self.get_current_run_id()
            events: List[Dict[str, Any]] = []
            if OrderORM is not None:
                order_query = sess.query(OrderORM)
                if active_run_id and not include_all_runs:
                    order_query = order_query.filter(OrderORM.run_id == active_run_id)
                for row in order_query.order_by(OrderORM.ts_last.desc()).limit(max_rows).all():
                    status = _enum_value(getattr(row, "status", None))
                    events.append(
                        {
                            "ts": _datetime_ms(getattr(row, "ts_last", None)) or _datetime_ms(getattr(row, "ts_created", None)),
                            "type": "OrderSubmitted",
                            "order_id": str(getattr(row, "id", "") or ""),
                            "symbol": str(getattr(row, "symbol", "") or ""),
                            "side": _enum_value(getattr(row, "side", None)).lower() or None,
                            "price": float(getattr(row, "price", 0.0) or 0.0),
                            "qty": int(getattr(row, "quantity", 0) or 0),
                            "status": status,
                            "reason": None,
                            "account_id": str(getattr(row, "account_id", "") or ""),
                            "run_id": str(getattr(row, "run_id", "") or "") or None,
                            "source": "runtime-order-table",
                        }
                    )
            if TradeORM is not None:
                trade_query = sess.query(TradeORM)
                if active_run_id and not include_all_runs:
                    trade_query = trade_query.filter(TradeORM.run_id == active_run_id)
                for row in trade_query.order_by(TradeORM.ts.desc()).limit(max_rows).all():
                    ts_ms = _datetime_ms(getattr(row, "ts", None))
                    base = {
                        "ts": ts_ms,
                        "type": "Trade",
                        "symbol": str(getattr(row, "symbol", "") or ""),
                        "price": float(getattr(row, "price", 0.0) or 0.0),
                        "qty": int(getattr(row, "quantity", 0) or 0),
                        "status": "TRADE",
                        "reason": None,
                        "run_id": str(getattr(row, "run_id", "") or "") or None,
                        "source": "runtime-trade-table",
                    }
                    buy_account = str(getattr(row, "buy_account_id", "") or "")
                    sell_account = str(getattr(row, "sell_account_id", "") or "")
                    events.append(
                        {
                            **base,
                            "order_id": str(getattr(row, "buy_order_id", "") or ""),
                            "side": "buy",
                            "account_id": buy_account,
                        }
                    )
                    if sell_account:
                        events.append(
                            {
                                **base,
                                "order_id": str(getattr(row, "sell_order_id", "") or ""),
                                "side": "sell",
                                "account_id": sell_account,
                            }
                        )
            events.sort(key=lambda item: int(item.get("ts") or 0), reverse=True)
            return list(reversed(events[:max_rows]))
        except Exception:
            return []
        finally:
            sess.close()

    @staticmethod
    def _latest_trade_run_id(sess, symbol: str) -> str | None:
        try:
            row = (
                sess.query(TradeORM.run_id)
                .filter(TradeORM.symbol == symbol, TradeORM.run_id.isnot(None))
                .order_by(TradeORM.ts.desc())
                .first()
            )
            value = str(row[0] or "").strip() if row else ""
            return value or None
        except Exception:
            return None

    def list_leaderboard_snapshots(self) -> List[Dict[str, Any]]:
        if SessionLocal is None or AgentBinding is None or RuntimeAccount is None or RuntimePosition is None:
            return []
        try:
            sess = SessionLocal()
        except Exception:
            return []
        try:
            bindings = sess.query(AgentBinding).order_by(AgentBinding.agent_name.asc()).all()
            account_ids = [
                str(getattr(binding, "account_id", "") or "").strip()
                for binding in bindings
                if str(getattr(binding, "account_id", "") or "").strip()
            ]
            if not account_ids:
                return []
            accounts = {
                str(getattr(account, "id", "") or ""): account
                for account in sess.query(RuntimeAccount).filter(RuntimeAccount.id.in_(account_ids)).all()
            }
            positions_by_account: Dict[str, List[Any]] = {}
            for pos in sess.query(RuntimePosition).filter(RuntimePosition.account_id.in_(account_ids)).all():
                positions_by_account.setdefault(str(getattr(pos, "account_id", "") or ""), []).append(pos)
            out: List[Dict[str, Any]] = []
            for binding in bindings:
                account_id = str(getattr(binding, "account_id", "") or "").strip()
                account = accounts.get(account_id)
                if account is None:
                    continue
                positions = positions_by_account.get(account_id, [])
                cash = float(getattr(account, "cash", 0.0) or 0.0)
                frozen_cash = float(getattr(account, "frozen_cash", 0.0) or 0.0)
                equity = cash + frozen_cash
                gross_exposure = 0.0
                long_count = 0
                short_count = 0
                for pos in positions:
                    qty = int(getattr(pos, "quantity", 0) or 0)
                    avg_price = float(getattr(pos, "avg_price", 0.0) or 0.0)
                    equity += qty * avg_price
                    gross_exposure += abs(qty * avg_price)
                    if qty > 0:
                        long_count += 1
                    elif qty < 0:
                        short_count += 1
                meta = _safe_parse_meta(getattr(binding, "meta", None))
                out.append(
                    {
                        "agent_id": str(getattr(binding, "agent_name", "") or ""),
                        "account_id": account_id,
                        "initial_cash": float(meta.get("initial_cash") or 100_000.0),
                        "equity": equity,
                        "gross_exposure": gross_exposure,
                        "long_count": long_count,
                        "short_count": short_count,
                    }
                )
            return out
        except Exception:
            return []
        finally:
            sess.close()

    def get_leaderboard_history(self, agent_id: str, *, window: str, points: int = 50) -> Dict[str, Any] | None:
        if SessionLocal is None or AgentBinding is None or AccountEquitySnapshot is None:
            return None
        normalized_agent_id = str(agent_id or "").strip()
        if not normalized_agent_id:
            return None
        window_days = {
            "1d": 1,
            "7d": 7,
            "30d": 30,
            "90d": 90,
            "ytd": 200,
            "all": 365,
        }.get(str(window), 365)
        try:
            sess = SessionLocal()
        except Exception:
            return None
        try:
            binding = sess.get(AgentBinding, normalized_agent_id)
            if binding is None:
                return None
            account_id = str(getattr(binding, "account_id", "") or "").strip()
            if not account_id:
                return None
            active_run_id = self.get_current_run_id()
            current_day = self.get_current_sim_day()
            min_sim_day = max(0, int(current_day) - int(window_days) + 1)
            base_query = (
                sess.query(AccountEquitySnapshot)
                .filter(AccountEquitySnapshot.account_id == account_id)
            )
            rows = []
            if active_run_id:
                rows = (
                    base_query
                    .filter(AccountEquitySnapshot.run_id == active_run_id)
                    .filter(AccountEquitySnapshot.sim_day >= min_sim_day)
                    .order_by(AccountEquitySnapshot.sim_day.asc(), AccountEquitySnapshot.created_at.asc())
                    .all()
                )
            if not rows:
                rows = (
                    base_query
                    .order_by(AccountEquitySnapshot.created_at.desc(), AccountEquitySnapshot.id.desc())
                    .limit(max(int(points), 1) * 4)
                    .all()
                )
                rows.reverse()
            if not rows:
                return {
                    "agent_id": normalized_agent_id,
                    "account_id": account_id,
                    "equity_curve": [],
                    "drawdown_curve": [],
                    "source": "runtime-account-equity-snapshots",
                    "authoritative": True,
                    "active_run_id": active_run_id,
                }
            sampled = _sample_rows(rows, max(int(points), 1))
            equity_curve = [float(getattr(row, "equity", 0.0) or 0.0) for row in sampled]
            drawdown_curve = [float(getattr(row, "drawdown", 0.0) or 0.0) for row in sampled]
            if not any(abs(v) > 1e-12 for v in drawdown_curve):
                drawdown_curve = _compute_drawdown_curve(equity_curve)
            return {
                "agent_id": normalized_agent_id,
                "account_id": account_id,
                "equity_curve": equity_curve,
                "drawdown_curve": drawdown_curve,
                "source": "runtime-account-equity-snapshots",
                "authoritative": True,
                "active_run_id": active_run_id,
            }
        except Exception:
            return None
        finally:
            sess.close()


def _safe_parse_meta(raw: str | None) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _enum_value(value: Any) -> str:
    raw = getattr(value, "name", None) or getattr(value, "value", value)
    return str(raw or "")


def _datetime_ms(value: Any) -> int | None:
    try:
        if value is not None and hasattr(value, "timestamp"):
            return int(float(value.timestamp()) * 1000)
    except Exception:
        return None
    return None


def _sample_rows(rows: List[Any], points: int) -> List[Any]:
    if points <= 0 or len(rows) <= points:
        return list(rows)
    if points == 1:
        return [rows[-1]]
    out = []
    max_index = len(rows) - 1
    for idx in range(points):
        pos = round((idx / (points - 1)) * max_index)
        out.append(rows[int(pos)])
    return out


def _compute_drawdown_curve(equity_curve: List[float]) -> List[float]:
    if not equity_curve:
        return []
    peak = float(equity_curve[0] or 0.0)
    out: List[float] = []
    for value in equity_curve:
        eq = float(value or 0.0)
        peak = max(peak, eq)
        if peak <= 0:
            out.append(0.0)
        else:
            out.append(min(0.0, (eq - peak) / peak))
    return out


__all__ = ["RuntimeQueryService"]
