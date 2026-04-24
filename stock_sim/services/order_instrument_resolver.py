from __future__ import annotations

from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.services.instrument_service import InstrumentService


class OrderInstrumentResolver:
    """Resolve instrument metadata/views needed by OrderService."""

    def __init__(self, instrument_service: InstrumentService):
        self._instrument_service = instrument_service

    def load_instrument_dto(self, symbol: str):
        try:
            return self._instrument_service.get(symbol.upper())
        except Exception:
            return None

    def make_instrument_view(self, dto):
        if dto is None:
            return None

        class _Tmp:
            pass

        tmp = _Tmp()
        tmp.tick_size = dto.tick_size
        tmp.lot_size = dto.lot_size
        tmp.min_qty = dto.min_qty
        tmp.settlement_cycle = dto.settlement_cycle
        tmp.market_cap = dto.market_cap
        tmp.total_shares = dto.total_shares
        tmp.free_float_shares = dto.free_float_shares
        tmp.initial_price = dto.initial_price
        tmp.pe = None
        tmp.ipo_opened = dto.ipo_opened
        return tmp

    def sync_engine_phase_from_instrument(self, engine: MatchingEngine, symbol: str, inst) -> None:
        if inst is None or not getattr(inst, "ipo_opened", False):
            return
        try:
            from stock_sim.core.const import Phase as _Phase  # type: ignore

            book = engine.get_book(symbol)
            book.phase = _Phase.CONTINUOUS
            book.has_continuous_started = True
        except Exception:
            pass

    def ensure_engine_symbol_registered(self, engine: MatchingEngine, symbol: str, fallback_inst=None):
        try:
            books = getattr(engine, "_books", {})
            if symbol in books or not hasattr(engine, "register_symbol"):
                return fallback_inst
            dto = self.load_instrument_dto(symbol)
            inst = fallback_inst or self.make_instrument_view(dto) or getattr(engine, "instrument", None)
            engine.register_symbol(symbol, inst)
            self.sync_engine_phase_from_instrument(engine, symbol, inst)
            return inst
        except Exception:
            return fallback_inst

    def get_symbol_params(self, engine: MatchingEngine, symbol: str):
        sym = symbol.upper()
        view = None
        if hasattr(engine, "get_instrument_view"):
            try:
                view = engine.get_instrument_view(sym)
            except Exception:
                view = None
        dto = None
        if view is None:
            dto = self.load_instrument_dto(sym)
            if dto:
                tmp = self.make_instrument_view(dto)
                try:
                    engine.register_symbol(sym, tmp)
                except Exception:
                    pass
                try:
                    view = engine.get_instrument_view(sym)
                except Exception:
                    view = None
        else:
            dto = self.load_instrument_dto(sym)
        if dto and getattr(dto, "ipo_opened", False):
            self.sync_engine_phase_from_instrument(engine, sym, self.make_instrument_view(dto))
        return view
