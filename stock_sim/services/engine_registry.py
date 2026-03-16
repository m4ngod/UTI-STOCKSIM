from __future__ import annotations

"""Global matching engine registry.

This module replaces the legacy FE.engine_registry import path.
It provides a process-wide symbol -> MatchingEngine registry plus
lightweight metadata storage used by services/agents/RL helpers.
"""

from dataclasses import dataclass, field
from threading import RLock
from typing import Any

from stock_sim.core.instruments import Stock
from stock_sim.core.matching_engine import MatchingEngine


@dataclass
class _EngineMeta:
    name: str | None = None
    pe: float | None = None
    market_cap: float | None = None
    initial_price: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class EngineRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._engines: dict[str, MatchingEngine] = {}
        self._meta: dict[str, _EngineMeta] = {}

    def _norm(self, symbol: str) -> str:
        return (symbol or "").upper().strip()

    def get(self, symbol: str) -> MatchingEngine | None:
        sym = self._norm(symbol)
        if not sym:
            return None
        with self._lock:
            return self._engines.get(sym)

    def symbols(self) -> list[str]:
        with self._lock:
            return sorted(self._engines.keys())

    def register(self, symbol: str, engine: MatchingEngine, overwrite: bool = False, **meta: Any) -> MatchingEngine:
        sym = self._norm(symbol)
        if not sym:
            raise ValueError("symbol 不能为空")
        with self._lock:
            if sym in self._engines and not overwrite:
                existing = self._engines[sym]
                if meta:
                    self._merge_meta(sym, meta)
                return existing
            self._engines[sym] = engine
            if meta:
                self._merge_meta(sym, meta)
            else:
                self._meta.setdefault(sym, _EngineMeta())
            return engine

    def get_or_create(self, symbol: str) -> MatchingEngine:
        sym = self._norm(symbol)
        if not sym:
            raise ValueError("symbol 不能为空")
        with self._lock:
            eng = self._engines.get(sym)
            if eng is not None:
                return eng
            meta = self._meta.get(sym)
            initial_price = meta.initial_price if meta else None
            stock = Stock(sym, 0, 0)
            if initial_price is not None:
                try:
                    stock.initial_price = initial_price
                except Exception:
                    pass
            eng = MatchingEngine(sym, instrument=stock)
            self._engines[sym] = eng
            self._meta.setdefault(sym, _EngineMeta())
            return eng

    def update_meta(self, symbol: str, **meta: Any) -> None:
        sym = self._norm(symbol)
        if not sym:
            return
        with self._lock:
            self._merge_meta(sym, meta)

    def remove(self, symbol: str) -> MatchingEngine | None:
        sym = self._norm(symbol)
        if not sym:
            return None
        with self._lock:
            self._meta.pop(sym, None)
            return self._engines.pop(sym, None)

    def _merge_meta(self, symbol: str, meta: dict[str, Any]) -> None:
        cur = self._meta.setdefault(symbol, _EngineMeta())
        for key in ("name", "pe", "market_cap", "initial_price"):
            if key in meta:
                setattr(cur, key, meta[key])
        extra = {k: v for k, v in meta.items() if k not in {"name", "pe", "market_cap", "initial_price"}}
        if extra:
            cur.extra.update(extra)


engine_registry = EngineRegistry()

__all__ = ["EngineRegistry", "engine_registry"]

