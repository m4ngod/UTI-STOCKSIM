from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import List

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from stock_sim.persistence.models_instrument import Instrument
from stock_sim.services.instrument_runtime_service import (
    ensure_runtime_engine_for_instrument,
    finalize_runtime_instrument_creation,
    sync_runtime_instrument_meta,
)
from stock_sim.services.sim_clock import current_sim_day, virtual_datetime

TRACE_SIMDAY = os.environ.get("DEBUG_TRACE_SIMDAY") == "1"


@dataclass
class InstrumentDTO:
    symbol: str
    name: str
    tick_size: float
    lot_size: int
    min_qty: int
    settlement_cycle: int
    market_cap: float | None
    total_shares: float | None
    free_float_shares: float | None
    initial_price: float | None
    created_at: str | None
    is_active: bool
    ipo_opened: bool

    @staticmethod
    def from_model(m: Instrument) -> "InstrumentDTO":
        return InstrumentDTO(
            symbol=m.symbol,
            name=m.name or m.symbol,
            tick_size=m.tick_size,
            lot_size=m.lot_size,
            min_qty=m.min_qty,
            settlement_cycle=m.settlement_cycle,
            market_cap=m.market_cap,
            total_shares=m.total_shares,
            free_float_shares=m.free_float_shares,
            initial_price=getattr(m, "initial_price", None),
            created_at=m.created_at.isoformat() if getattr(m, "created_at", None) else None,
            is_active=bool(getattr(m, "is_active", True)),
            ipo_opened=bool(getattr(m, "ipo_opened", False)),
        )


class InstrumentService:
    """CRUD for instruments plus explicit runtime synchronization hooks."""

    def __init__(self, session: Session):
        self.s = session

    def _stamp(self, inst_row: Instrument) -> None:
        try:
            sim_day = current_sim_day()
            if TRACE_SIMDAY:
                print(
                    f"[TRACE InstrumentService.stamp] "
                    f"symbol={getattr(inst_row, 'symbol', None)} sim_day={sim_day}"
                )
            if not sim_day:
                return
            if hasattr(inst_row, "sim_day") and not getattr(inst_row, "sim_day", None):
                inst_row.sim_day = sim_day
            if hasattr(inst_row, "sim_dt") and not getattr(inst_row, "sim_dt", None):
                inst_row.sim_dt = virtual_datetime(sim_day)
        except Exception as exc:
            if TRACE_SIMDAY:
                print(f"[TRACE InstrumentService.stamp.error] {exc}")

    def create(
        self,
        *,
        symbol: str,
        name: str = "",
        tick_size: float = 0.01,
        lot_size: int = 1,
        min_qty: int = 1,
        settlement_cycle: int | None = None,
        market_cap: float | None = None,
        total_shares: float | None = None,
        free_float_shares: float | None = None,
        initial_price: float | None = None,
        ipo_opened: bool | None = None,
        overwrite: bool = False,
    ) -> InstrumentDTO:
        sym = symbol.upper().strip()
        if not sym:
            raise ValueError("symbol cannot be empty")

        inst_row = self.s.get(Instrument, sym)
        if inst_row and not overwrite and not inst_row.is_active:
            inst_row.is_active = True
        if inst_row is None:
            inst_row = Instrument(symbol=sym)
            self.s.add(inst_row)

        inst_row.name = name or sym
        inst_row.tick_size = tick_size
        inst_row.lot_size = lot_size
        inst_row.min_qty = min_qty
        if settlement_cycle is not None:
            inst_row.settlement_cycle = settlement_cycle
        if market_cap is not None:
            inst_row.market_cap = market_cap
        if total_shares is not None:
            inst_row.total_shares = total_shares
        if free_float_shares is not None:
            inst_row.free_float_shares = free_float_shares
        if initial_price is not None:
            setattr(inst_row, "initial_price", initial_price)
        if ipo_opened is not None:
            setattr(inst_row, "ipo_opened", bool(ipo_opened))
        inst_row.is_active = True

        self._stamp(inst_row)
        attempts = 0
        while True:
            try:
                self.s.flush()
                break
            except OperationalError as exc:
                message = str(exc).lower()
                if "locked" in message and attempts < 4:
                    attempts += 1
                    time.sleep(0.02 * attempts)
                    continue
                raise

        ensure_runtime_engine_for_instrument(inst_row)
        return InstrumentDTO.from_model(inst_row)

    def update(self, symbol: str, **patch) -> InstrumentDTO:
        sym = symbol.upper()
        inst_row = self.s.get(Instrument, sym)
        if not inst_row:
            raise ValueError(f"instrument not found: {sym}")

        mutable = {"name", "market_cap", "total_shares", "free_float_shares", "initial_price", "ipo_opened"}
        structural = {"tick_size", "lot_size", "min_qty", "settlement_cycle"}
        initial_price_before = getattr(inst_row, "initial_price", None)

        for key, value in patch.items():
            if key in mutable or key in structural:
                setattr(inst_row, key, value)

        self._stamp(inst_row)
        self.s.flush()
        sync_runtime_instrument_meta(
            inst_row,
            initial_price_changed=(
                "initial_price" in patch
                and patch.get("initial_price") is not None
                and patch.get("initial_price") != initial_price_before
            ),
        )
        if TRACE_SIMDAY:
            try:
                print(
                    f"[TRACE InstrumentService.update.after] "
                    f"symbol={sym} initial_price={getattr(inst_row, 'initial_price', None)} "
                    f"ipo_opened={getattr(inst_row, 'ipo_opened', None)}"
                )
            except Exception:
                pass
        return InstrumentDTO.from_model(inst_row)

    def finalize_create(self, symbol: str) -> None:
        finalize_runtime_instrument_creation(symbol)

    def soft_delete(self, symbol: str) -> bool:
        sym = symbol.upper()
        inst_row = self.s.get(Instrument, sym)
        if not inst_row or not inst_row.is_active:
            return False
        inst_row.is_active = False
        self.s.flush()
        return True

    def restore(self, symbol: str) -> bool:
        sym = symbol.upper()
        inst_row = self.s.get(Instrument, sym)
        if not inst_row:
            return False
        if not inst_row.is_active:
            inst_row.is_active = True
            self.s.flush()
        return True

    def get(self, symbol: str) -> InstrumentDTO | None:
        model = self.s.get(Instrument, symbol.upper())
        return InstrumentDTO.from_model(model) if model else None

    def list(self, *, active_only: bool = True) -> List[InstrumentDTO]:
        query = self.s.query(Instrument)
        if active_only:
            query = query.filter(Instrument.is_active.is_(True))
        return [InstrumentDTO.from_model(model) for model in query.order_by(Instrument.symbol.asc()).all()]

    def restore_active_runtime_engines(self) -> List[InstrumentDTO]:
        rows = (
            self.s.query(Instrument)
            .filter(Instrument.is_active.is_(True))
            .order_by(Instrument.symbol.asc())
            .all()
        )
        restored: List[InstrumentDTO] = []
        for inst_row in rows:
            ensure_runtime_engine_for_instrument(inst_row)
            restored.append(InstrumentDTO.from_model(inst_row))
        return restored
