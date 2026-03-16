from __future__ import annotations
"""UniverseProvider
提供多标的交易宇宙。
默认实现: 从 engine_registry 中列出全部已注册且交易中的标的；可传入过滤回调。
"""
from typing import Callable, List
from stock_sim.services.engine_registry import engine_registry

class UniverseProvider:
    def __init__(self,
                 symbol_filter: Callable[[str], bool] | None = None,
                 min_symbols: int = 1):
        self._filter = symbol_filter
        self._min = min_symbols
    def symbols(self) -> List[str]:
        syms = engine_registry.symbols()
        if self._filter:
            syms = [s for s in syms if self._filter(s)]
        return syms[: ]
    def ensure_min(self) -> bool:
        return len(self.symbols()) >= self._min
