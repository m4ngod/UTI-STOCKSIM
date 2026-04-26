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
            ensure = getattr(models_init, "ensure_models", None)
            if callable(ensure):
                ensure()
            else:
                models_init.init_models()
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
            if settlement_cycle >= 1 and TradeORM is not None:
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
                    return []
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
                    return []
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

    def list_leaderboard_snapshots(self) -> List[Dict[str, Any]]:
        if SessionLocal is None or AgentBinding is None or RuntimeAccount is None or RuntimePosition is None:
            return []
        try:
            sess = SessionLocal()
        except Exception:
            return []
        try:
            bindings = sess.query(AgentBinding).order_by(AgentBinding.agent_name.asc()).all()
            out: List[Dict[str, Any]] = []
            for binding in bindings:
                account = sess.get(RuntimeAccount, binding.account_id)
                if account is None:
                    continue
                positions = (
                    sess.query(RuntimePosition)
                    .filter(RuntimePosition.account_id == binding.account_id)
                    .all()
                )
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
                        "account_id": str(getattr(binding, "account_id", "") or ""),
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
