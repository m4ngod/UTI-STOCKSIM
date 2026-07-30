from __future__ import annotations

from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.services.engine_registry import engine_registry
from stock_sim.services.order_instrument_resolver import OrderInstrumentResolver


class OrderEngineRouter:
    """Backend symbol -> engine routing owner for OrderService."""

    def __init__(
        self,
        *,
        injected_engine: MatchingEngine | None,
        instrument_resolver: OrderInstrumentResolver,
    ) -> None:
        self._injected_engine = injected_engine
        self._instrument_resolver = instrument_resolver

    def resolve_engine(self, symbol: str) -> MatchingEngine:
        sym = symbol.upper()
        registered = engine_registry.get(sym)
        injected = self._injected_engine
        if injected and getattr(injected, "symbol", "").upper() == sym:
            resolved = self._resolve_injected_engine(sym, registered)
            return resolved or injected
        if injected:
            resolved = self._resolve_injected_engine(sym, registered)
            if resolved is not None:
                return resolved
        if registered is not None:
            return registered
        return engine_registry.get_or_create(sym)

    def get_symbol_params(self, symbol: str):
        sym = symbol.upper()
        engine = self.resolve_engine(sym)
        return self._instrument_resolver.get_symbol_params(engine, sym)

    def _resolve_injected_engine(
        self,
        symbol: str,
        registered: MatchingEngine | None,
    ) -> MatchingEngine | None:
        injected = self._injected_engine
        if injected is None:
            return None
        try:
            fallback_inst = (
                getattr(registered, "instrument", None)
                if registered is not None
                else getattr(injected, "instrument", None)
            )
            source_inst = self._instrument_resolver.ensure_engine_symbol_registered(
                injected,
                symbol,
                fallback_inst=fallback_inst,
            )
            if source_inst is None:
                source_inst = getattr(injected, "instrument", None)
            self._instrument_resolver.sync_engine_phase_from_instrument(
                injected,
                symbol,
                source_inst,
            )
            engine_registry.register(symbol, injected, overwrite=True)
            return injected
        except Exception:
            return None


__all__ = ["OrderEngineRouter"]
