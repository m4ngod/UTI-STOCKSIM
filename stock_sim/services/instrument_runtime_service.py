from __future__ import annotations

import os
import time

from stock_sim.core.instruments import Stock, create_instrument
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.persistence.models_instrument import Instrument
from stock_sim.services.engine_registry import engine_registry
from stock_sim.settings import settings


TRACE_SIMDAY = os.environ.get("DEBUG_TRACE_SIMDAY") == "1"


def _get_active_run_id() -> str | None:
    try:
        from stock_sim.services.sim_clock import ensure_sim_clock_started
    except Exception:
        try:
            from services.sim_clock import ensure_sim_clock_started  # type: ignore
        except Exception:
            return None
    try:
        clk = ensure_sim_clock_started()
        snap = clk.snapshot() if hasattr(clk, "snapshot") else {}
        run_id = str((snap or {}).get("run_id") or "").strip()
        return run_id or None
    except Exception:
        return None


def _stamp_engine_run_id(eng: MatchingEngine, symbol: str, run_id: str | None) -> None:
    if not run_id:
        return
    try:
        book = eng.get_book(symbol) if hasattr(eng, "get_book") else None
    except Exception:
        book = None
    if book is not None:
        try:
            meta = getattr(book, "instrument_meta", None)
            if not isinstance(meta, dict):
                meta = {}
                setattr(book, "instrument_meta", meta)
            meta["run_id"] = run_id
        except Exception:
            pass
        try:
            setattr(book.snapshot, "run_id", run_id)
        except Exception:
            pass


def _build_stock_from_row(inst_row: Instrument) -> Stock:
    stock_obj: Stock = create_instrument(
        inst_row.symbol,
        tick_size=inst_row.tick_size,
        lot_size=inst_row.lot_size,
        min_qty=inst_row.min_qty,
        initial_price=getattr(inst_row, "initial_price", None),
        settlement_cycle=inst_row.settlement_cycle,
    )
    try:
        stock_obj.total_shares = inst_row.total_shares or 0
        stock_obj.free_float_shares = inst_row.free_float_shares or 0
        stock_obj.initial_price = getattr(inst_row, "initial_price", None)
        stock_obj.ipo_opened = bool(getattr(inst_row, "ipo_opened", False))
    except Exception:
        pass
    return stock_obj


def _sync_phase(eng: MatchingEngine, inst_row: Instrument) -> None:
    from stock_sim.core.const import Phase

    if bool(getattr(inst_row, "ipo_opened", False)):
        eng.phase = Phase.CONTINUOUS
        try:
            book = eng._books[inst_row.symbol]
            book.phase = Phase.CONTINUOUS
            book.has_continuous_started = True
        except Exception:
            pass
    else:
        eng.phase = Phase.CALL_AUCTION


def _seed_reference_snapshot(eng: MatchingEngine, initial_price: float | None) -> None:
    if initial_price is None or initial_price <= 0:
        return
    try:
        snap = eng.snapshot
        snap.open_price = snap.high_price = snap.low_price = snap.close_price = snap.last_price = float(initial_price)
    except Exception:
        pass


def _ensure_ipo_timer(eng: MatchingEngine, symbol: str) -> None:
    try:
        from stock_sim.services.sim_clock import ensure_sim_clock_started

        ensure_sim_clock_started()
        duration = float(getattr(settings, "IPO_CALL_AUCTION_SECONDS", 3.75))
        eng._ipo_end_ts = time.time() + duration
        if TRACE_SIMDAY:
            print(f"[TRACE InstrumentRuntime.timer] symbol={symbol} real_secs={duration:.3f} end_ts={eng._ipo_end_ts:.3f}")
    except Exception as exc:
        if TRACE_SIMDAY:
            print(f"[TRACE InstrumentRuntime.timer.error] symbol={symbol} err={exc}")


def ensure_runtime_engine_for_instrument(inst_row: Instrument) -> MatchingEngine:
    symbol = str(inst_row.symbol or "").upper()
    eng = engine_registry.get(symbol)
    if eng is not None:
        _stamp_engine_run_id(eng, symbol, _get_active_run_id())
        return eng
    if TRACE_SIMDAY:
        print(
            f"[TRACE InstrumentRuntime.ensure] symbol={symbol} "
            f"ipo_opened={bool(getattr(inst_row, 'ipo_opened', False))} "
            f"initial_price={getattr(inst_row, 'initial_price', None)}"
        )
    stock_obj = _build_stock_from_row(inst_row)
    eng = MatchingEngine(symbol, instrument=stock_obj)
    _sync_phase(eng, inst_row)
    if TRACE_SIMDAY:
        try:
            print(f"[TRACE InstrumentRuntime.phase] symbol={symbol} phase={eng.phase.name}")
        except Exception:
            pass
    engine_registry.register(
        symbol,
        eng,
        name=getattr(inst_row, "name", None),
        pe=getattr(inst_row, "pe", None),
        market_cap=getattr(inst_row, "market_cap", None),
        initial_price=getattr(inst_row, "initial_price", None),
        settlement_cycle=getattr(inst_row, "settlement_cycle", None),
    )
    _stamp_engine_run_id(eng, symbol, _get_active_run_id())
    _seed_reference_snapshot(eng, getattr(inst_row, "initial_price", None))
    _ensure_ipo_timer(eng, symbol)
    return eng


def sync_runtime_instrument_meta(inst_row: Instrument, *, initial_price_changed: bool = False) -> None:
    symbol = str(inst_row.symbol or "").upper()
    engine_registry.update_meta(
        symbol,
        name=getattr(inst_row, "name", None),
        pe=getattr(inst_row, "pe", None),
        market_cap=getattr(inst_row, "market_cap", None),
        initial_price=getattr(inst_row, "initial_price", None),
        settlement_cycle=getattr(inst_row, "settlement_cycle", None),
    )
    eng = engine_registry.get(symbol)
    if eng is None:
        return
    try:
        inst = getattr(eng, "instrument", None)
        if inst is not None:
            inst.tick_size = inst_row.tick_size
            inst.lot_size = inst_row.lot_size
            inst.min_qty = inst_row.min_qty
            inst.settlement_cycle = inst_row.settlement_cycle
            inst.market_cap = inst_row.market_cap
            inst.total_shares = inst_row.total_shares
            inst.free_float_shares = inst_row.free_float_shares
            inst.initial_price = getattr(inst_row, "initial_price", None)
            inst.ipo_opened = bool(getattr(inst_row, "ipo_opened", False))
    except Exception:
        pass
    _sync_phase(eng, inst_row)
    _stamp_engine_run_id(eng, symbol, _get_active_run_id())
    if initial_price_changed:
        try:
            snap = getattr(eng, "snapshot", None)
            if snap and (snap.last_price is None or snap.last_price <= 0):
                _seed_reference_snapshot(eng, getattr(inst_row, "initial_price", None))
        except Exception:
            pass


def finalize_runtime_instrument_creation(symbol: str) -> None:
    normalized_symbol = str(symbol or "").strip().upper()
    if not normalized_symbol:
        return
    try:
        from stock_sim.services.ipo_retail_distribution import (
            allocate_ipo_retail_distribution,
            register_pending_ipo_distribution,
        )
        from stock_sim.services.sim_clock import ensure_sim_clock_started
    except Exception:
        return
    try:
        register_pending_ipo_distribution(normalized_symbol)
    except Exception:
        pass
    try:
        clk = ensure_sim_clock_started()
        snap = clk.snapshot() if hasattr(clk, "snapshot") else {}
        if bool((snap or {}).get("running", False)):
            allocate_ipo_retail_distribution(
                normalized_symbol,
                sim_day=int((snap or {}).get("sim_day", 0) or 0),
            )
    except Exception:
        pass


__all__ = [
    "ensure_runtime_engine_for_instrument",
    "sync_runtime_instrument_meta",
    "finalize_runtime_instrument_creation",
]
