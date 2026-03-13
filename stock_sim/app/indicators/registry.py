"""Indicator Registry (Task 6)

职责:
- 注册/发现指标计算函数
- 统一 compute 接口
- 生成缓存 key (后续可扩展加数据哈希)

返回约定:
- 单序列指标: numpy.ndarray 与输入等长
- 多序列指标(MACD): dict[str, ndarray] 各数组等长
"""
from __future__ import annotations
from typing import Callable, Any, Dict, Iterable, Optional
import numpy as np

IndicatorFunc = Callable[[np.ndarray, Dict[str, Any]], Any]

class IndicatorRegistry:
    def __init__(self):
        self._indicators: Dict[str, IndicatorFunc] = {}

    def register(self, name: str, func: IndicatorFunc):
        if name in self._indicators:
            raise ValueError(f"indicator already registered: {name}")
        self._indicators[name] = func

    def compute(self, name: str, data: Iterable[float], **params: Any):
        if name not in self._indicators:
            raise KeyError(name)
        arr = _to_ndarray(data)
        return self._indicators[name](arr, params)

    def generate_cache_key(self, name: str, *, data_len: int, params: Optional[Dict[str, Any]] = None) -> str:
        params = params or {}
        parts = [f"{k}={params[k]}" for k in sorted(params.keys())]
        return f"{name}|len={data_len}|params={'&'.join(parts)}"

def _to_ndarray(data: Iterable[float]) -> np.ndarray:
    if isinstance(data, np.ndarray):
        return data.astype(np.float64)
    return np.asarray(list(data), dtype=np.float64)

indicator_registry = IndicatorRegistry()

# 引入具体指标并注册
from .ma import indicator_ma  # noqa: E402
from .rsi import indicator_rsi  # noqa: E402
from .macd import indicator_macd  # noqa: E402

indicator_registry.register("ma", indicator_ma)
indicator_registry.register("rsi", indicator_rsi)
indicator_registry.register("macd", indicator_macd)

__all__ = [
    "indicator_registry",
    "IndicatorRegistry",
    "indicator_ma",
    "indicator_rsi",
    "indicator_macd",
]
