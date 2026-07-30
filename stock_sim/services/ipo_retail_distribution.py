from __future__ import annotations

import json
import random
from threading import RLock
import time
from typing import Iterable

try:
    from stock_sim.persistence import models_init  # type: ignore
    from stock_sim.persistence.models_imports import SessionLocal  # type: ignore
    from stock_sim.persistence.models_instrument import Instrument  # type: ignore
    from stock_sim.persistence.models_account import Account as RuntimeAccount  # type: ignore
    from stock_sim.persistence.models_position import Position  # type: ignore
    from stock_sim.persistence.models_agent_binding import AgentBinding  # type: ignore
    from stock_sim.persistence.models_order import OrderORM  # type: ignore
    from stock_sim.persistence.models_trade import TradeORM  # type: ignore
    from stock_sim.services.account_service import AccountService  # type: ignore
    from stock_sim.services.sim_clock import ensure_sim_clock_started  # type: ignore
    from stock_sim.core.const import OrderSide, OrderStatus  # type: ignore
except Exception:  # pragma: no cover
    try:
        from persistence import models_init  # type: ignore
        from persistence.models_imports import SessionLocal  # type: ignore
        from persistence.models_instrument import Instrument  # type: ignore
        from persistence.models_account import Account as RuntimeAccount  # type: ignore
        from persistence.models_position import Position  # type: ignore
        from persistence.models_agent_binding import AgentBinding  # type: ignore
        from persistence.models_order import OrderORM  # type: ignore
        from persistence.models_trade import TradeORM  # type: ignore
        from services.account_service import AccountService  # type: ignore
        from services.sim_clock import ensure_sim_clock_started  # type: ignore
        from core.const import OrderSide, OrderStatus  # type: ignore
    except Exception:  # pragma: no cover
        models_init = None  # type: ignore
        SessionLocal = None  # type: ignore
        Instrument = None  # type: ignore
        RuntimeAccount = None  # type: ignore
        Position = None  # type: ignore
        AgentBinding = None  # type: ignore
        OrderORM = None  # type: ignore
        TradeORM = None  # type: ignore
        AccountService = None  # type: ignore
        ensure_sim_clock_started = None  # type: ignore
        OrderSide = None  # type: ignore
        OrderStatus = None  # type: ignore


IPO_RETAIL_ACCOUNT_RATIO = 1.0
ACTIVE_RETAIL_STATUSES = {"RUNNING", "PAUSED"}
ACTIVE_RETAIL_MAX_AGE_MS = 15 * 60 * 1000

_PENDING_SYMBOLS: set[str] = set()
_ALLOCATED_SYMBOLS: set[str] = set()
_LOCK = RLock()

_RETAIL_TYPES = {"RETAIL", "MULTISTRATEGYRETAIL"}
_RETAIL_NAME_PREFIXES = (
    "mean_revert",
    "momentum_chase",
    "buy_the_dip",
    "profit_taking",
    "liquidity_noise",
    "noise",
    "breakout",
    "vol_scaling",
    "msr",
)


def _ensure_models() -> None:
    if models_init is None:
        return
    ensure = getattr(models_init, "ensure_models", None)
    if callable(ensure):
        ensure()
        return
    models_init.init_models()


def register_pending_ipo_distribution(symbol: str) -> None:
    sym = (symbol or "").strip().upper()
    if not sym:
        return
    with _LOCK:
        if sym not in _ALLOCATED_SYMBOLS:
            _PENDING_SYMBOLS.add(sym)


def allocate_pending_ipo_distributions(*, sim_day: int | None = None) -> dict[str, object]:
    with _LOCK:
        symbols = sorted(_PENDING_SYMBOLS)
    applied: list[dict[str, object]] = []
    for symbol in symbols:
        result = allocate_ipo_retail_distribution(symbol, sim_day=sim_day)
        if result.get("applied"):
            applied.append(result)
    return {
        "symbols": symbols,
        "applied": applied,
    }


def allocate_ipo_retail_distribution(
    symbol: str,
    *,
    sim_day: int | None = None,
    account_ratio: float = IPO_RETAIL_ACCOUNT_RATIO,
) -> dict[str, object]:
    sym = (symbol or "").strip().upper()
    if (
        not sym
        or SessionLocal is None
        or Instrument is None
        or RuntimeAccount is None
        or Position is None
        or AccountService is None
    ):
        return {"symbol": sym, "applied": False, "reason": "runtime_unavailable"}
    try:
        _ensure_models()
    except Exception:
        pass
    session = SessionLocal()
    try:
        inst = session.get(Instrument, sym)
        if inst is None:
            return {"symbol": sym, "applied": False, "reason": "instrument_not_found"}
        free_float = int(float(getattr(inst, "free_float_shares", 0) or 0))
        if free_float <= 0:
            _mark_allocated(sym)
            return {"symbol": sym, "applied": False, "reason": "no_free_float"}
        account_ids, cohort_scope = _retail_account_ids(session)
        if not account_ids:
            return {"symbol": sym, "applied": False, "reason": "no_retail_accounts"}
        recipient_count = _resolve_recipient_count(
            account_count=len(account_ids),
            free_float=free_float,
            account_ratio=account_ratio,
            cohort_scope=cohort_scope,
        )
        if recipient_count <= 0:
            return {"symbol": sym, "applied": False, "reason": "no_recipients"}
        existing = _existing_positive_qty(session, sym, account_ids)
        existing_recipient_count = _existing_positive_recipient_count(session, sym, account_ids)
        if existing > 0:
            if not _can_rebalance_existing_distribution(session, sym, existing_recipient_count, recipient_count):
                _mark_allocated(sym)
                return {
                    "symbol": sym,
                    "applied": False,
                    "reason": "already_allocated",
                    "existing_qty": existing,
                    "existing_recipients": existing_recipient_count,
                    "target_recipients": recipient_count,
                    "cohort_scope": cohort_scope,
                }
        rng = random.Random(f"{sym}:{0 if sim_day is None else int(sim_day)}")
        selected_ids = rng.sample(account_ids, recipient_count)
        grants = _split_evenly(free_float, recipient_count)
        account_service = AccountService(session)
        ref_price = float(getattr(inst, "initial_price", 0.0) or 0.0)
        granted_total = 0
        changed_accounts = []
        selected_set = set(selected_ids)
        if existing > 0:
            _clear_unselected_distribution_positions(session, sym, account_ids, selected_set)
        for account_id, grant_qty in zip(selected_ids, grants):
            if grant_qty <= 0:
                continue
            acc = account_service.get_or_create(account_id)
            pos = account_service.get_position(acc, sym)
            old_qty = 0 if existing > 0 else int(getattr(pos, "quantity", 0) or 0)
            old_avg = 0.0 if existing > 0 else float(getattr(pos, "avg_price", 0.0) or 0.0)
            new_qty = (old_qty + int(grant_qty)) if existing <= 0 else int(grant_qty)
            pos.quantity = new_qty
            if existing > 0:
                pos.frozen_qty = 0
            if ref_price > 0:
                if old_qty > 0 and old_avg > 0:
                    pos.avg_price = ((old_qty * old_avg) + (grant_qty * ref_price)) / max(new_qty, 1)
                else:
                    pos.avg_price = ref_price
            granted_total += int(grant_qty)
            changed_accounts.append(acc)
        session.commit()
        for acc in changed_accounts:
            try:
                account_service._publish_account(acc)  # type: ignore[attr-defined]
            except Exception:
                pass
        _mark_allocated(sym)
        return {
            "symbol": sym,
            "applied": granted_total > 0,
            "recipients": len(changed_accounts),
            "granted_qty": granted_total,
            "free_float_shares": free_float,
            "cohort_scope": cohort_scope,
            "existing_recipients": existing_recipient_count,
            "target_recipients": recipient_count,
        }
    except Exception as exc:
        try:
            session.rollback()
        except Exception:
            pass
        return {"symbol": sym, "applied": False, "reason": "error", "error": str(exc)}
    finally:
        session.close()


def _split_evenly(total: int, parts: int) -> list[int]:
    if total <= 0 or parts <= 0:
        return []
    base = total // parts
    remainder = total % parts
    out = [base for _ in range(parts)]
    for idx in range(remainder):
        out[idx] += 1
    return out


def _resolve_recipient_count(
    *,
    account_count: int,
    free_float: int,
    account_ratio: float,
    cohort_scope: str,
) -> int:
    if account_count <= 0 or free_float <= 0:
        return 0
    target = max(1, int(round(account_count * max(0.0, float(account_ratio)))))
    if cohort_scope in {"all-retail-bindings", "recent-active-retail-bindings"}:
        target = account_count
    return min(account_count, target, free_float)


def _retail_account_ids(session) -> tuple[list[str], str]:
    ids: list[str] = []
    if AgentBinding is not None:
        try:
            rows = (
                session.query(AgentBinding)
                .filter(AgentBinding.agent_type.in_(tuple(sorted(_RETAIL_TYPES))))
                .order_by(AgentBinding.updated_at.desc(), AgentBinding.agent_name.asc())
                .all()
            )
            current_run_id = _current_run_id()
            current_run_rows = [
                row
                for row in rows
                if current_run_id and str(getattr(row, "run_id", "") or "").strip() == current_run_id
            ]
            runtime_rows = [
                row for row in rows if _has_runtime_binding_meta(_parse_binding_meta(getattr(row, "meta", None)))
            ]
            latest_runtime_rows = _latest_binding_rows(runtime_rows)
            if latest_runtime_rows:
                rows = latest_runtime_rows
            elif current_run_rows:
                rows = current_run_rows
            elif runtime_rows:
                rows = runtime_rows
            active_ids = []
            for row in rows:
                account_id = str(getattr(row, "account_id", "")).strip()
                if not account_id:
                    continue
                meta = _parse_binding_meta(getattr(row, "meta", None))
                if _is_recently_active_binding(meta):
                    active_ids.append(account_id)
                ids.append(account_id)
        except Exception:
            ids = []
    if ids or RuntimeAccount is None:
        return _dedupe(ids), "all-retail-bindings"
    try:
        rows = session.query(RuntimeAccount).order_by(RuntimeAccount.id.asc()).all()
    except Exception:
        return [], "none"
    for row in rows:
        account_id = str(getattr(row, "id", "")).strip()
        low = account_id.lower()
        if low.startswith(_RETAIL_NAME_PREFIXES):
            ids.append(account_id)
    return _dedupe(ids), "account-prefix-fallback"


def _parse_binding_meta(raw: object) -> dict[str, object]:
    if isinstance(raw, dict):
        return dict(raw)
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _has_runtime_binding_meta(meta: dict[str, object]) -> bool:
    return any(key in meta for key in ("status", "start_time", "last_heartbeat"))


def _latest_binding_rows(rows: list[object], *, window_seconds: float = 10.0) -> list[object]:
    dated_rows = []
    for row in rows:
        updated_at = getattr(row, "updated_at", None)
        try:
            stamp = updated_at.timestamp()
        except Exception:
            continue
        dated_rows.append((stamp, row))
    if not dated_rows:
        return []
    newest = max(stamp for stamp, _row in dated_rows)
    cutoff = newest - max(float(window_seconds), 0.0)
    return [row for stamp, row in dated_rows if stamp >= cutoff]


def _current_run_id() -> str | None:
    if ensure_sim_clock_started is None:
        return None
    try:
        clk = ensure_sim_clock_started()
        snap = clk.snapshot() if hasattr(clk, "snapshot") else {}
        value = str((snap or {}).get("run_id") or "").strip()
        return value or None
    except Exception:
        return None


def _is_recently_active_binding(meta: dict[str, object]) -> bool:
    status = str(meta.get("status") or "").strip().upper()
    if status not in ACTIVE_RETAIL_STATUSES:
        return False
    now_ms = int(time.time() * 1000)
    heartbeat_ms = _coerce_int(meta.get("last_heartbeat"))
    start_time_ms = _coerce_int(meta.get("start_time"))
    freshness_ms = max(x for x in (heartbeat_ms, start_time_ms) if x is not None) if any(
        x is not None for x in (heartbeat_ms, start_time_ms)
    ) else None
    if freshness_ms is None:
        return False
    return (now_ms - freshness_ms) <= ACTIVE_RETAIL_MAX_AGE_MS


def _coerce_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _existing_positive_qty(session, symbol: str, account_ids: Iterable[str]) -> int:
    try:
        rows = (
            session.query(Position)
            .filter(Position.symbol == symbol, Position.quantity > 0)
            .all()
        )
    except Exception:
        return 0
    return sum(max(0, int(getattr(row, "quantity", 0) or 0)) for row in rows)


def _existing_positive_recipient_count(session, symbol: str, account_ids: Iterable[str]) -> int:
    try:
        return int(
            session.query(Position)
            .filter(Position.symbol == symbol, Position.quantity > 0)
            .count()
        )
    except Exception:
        return 0


def _can_rebalance_existing_distribution(session, symbol: str, existing_count: int, target_count: int) -> bool:
    if existing_count <= 0 or existing_count >= target_count:
        return False
    if TradeORM is not None:
        try:
            if session.query(TradeORM).filter(TradeORM.symbol == symbol).first() is not None:
                return False
        except Exception:
            return False
    if OrderORM is not None and OrderStatus is not None and OrderSide is not None:
        try:
            active_sell = (
                session.query(OrderORM)
                .filter(
                    OrderORM.symbol == symbol,
                    OrderORM.side == OrderSide.SELL,
                    OrderORM.status.in_([OrderStatus.NEW, OrderStatus.PARTIAL]),
                )
                .first()
            )
            if active_sell is not None:
                return False
        except Exception:
            return False
    try:
        frozen = (
            session.query(Position)
            .filter(Position.symbol == symbol, Position.frozen_qty > 0)
            .first()
        )
        return frozen is None
    except Exception:
        return False


def _clear_unselected_distribution_positions(
    session,
    symbol: str,
    account_ids: Iterable[str],
    selected_ids: set[str],
) -> None:
    rows = (
        session.query(Position)
        .filter(Position.symbol == symbol, Position.quantity > 0)
        .all()
    )
    for row in rows:
        if str(row.account_id) in selected_ids:
            continue
        row.quantity = 0
        row.frozen_qty = 0
        row.avg_price = 0.0


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = str(item).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _mark_allocated(symbol: str) -> None:
    with _LOCK:
        _PENDING_SYMBOLS.discard(symbol)
        _ALLOCATED_SYMBOLS.add(symbol)


__all__ = [
    "IPO_RETAIL_ACCOUNT_RATIO",
    "register_pending_ipo_distribution",
    "allocate_pending_ipo_distributions",
    "allocate_ipo_retail_distribution",
]
