"""BarsCache (Spec Task 8)

职责:
- 按 (symbol, timeframe) 缓存 K 线 / 分时数据 (OHLCV + ts)
- 提供快速读取 close/ohlcv 供指标计算与图表渲染
- 控制最大容量 (FIFO 丢弃最旧) 以限制内存
- 简单过期策略: 读取时如最后一根时间戳距离当前 > stale_ms (仅限实时 timeframe) 标记 stale

设计取舍:
- 不做多级索引 (日期 -> 分钟) 以降低复杂度; 后续可加分段文件映射
- 暂不持久化 (Phase1 内存即可)

与 MarketDataService 协作:
- MarketDataService 负责调用后端 fetch_bars 得到 list[BarDict]
- 更新时调用 cache.upsert(symbol, timeframe, bars)

BarDict 结构约定 (最小字段):
{"ts": int, "open": float, "high": float, "low": float, "close": float, "volume": float}

后续扩展: 可添加 turnover / vwap 等; 保持字段存在则缓存.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Literal, Tuple
import time
import threading
import numpy as np

from observability.metrics import metrics

BarDict = Dict[str, float | int]
Timeframe = Literal["1m", "5m", "15m", "60m", "1d"]

@dataclass
class BarsSeries:
    symbol: str
    timeframe: Timeframe
    ts: np.ndarray  # int64 epoch ms
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    last_updated_ms: int

    def tail(self, n: int) -> "BarsSeries":  # 快速截尾
        if n >= len(self.ts):
            return self
        return BarsSeries(
            symbol=self.symbol,
            timeframe=self.timeframe,
            ts=self.ts[-n:],
            open=self.open[-n:],
            high=self.high[-n:],
            low=self.low[-n:],
            close=self.close[-n:],
            volume=self.volume[-n:],
            last_updated_ms=self.last_updated_ms,
        )

class BarsCache:
    __slots__ = ("_data", "_lock", "max_size", "stale_ms")
    def __init__(self, *, max_size: int = 5000, stale_ms: int = 5 * 60 * 1000):
        if max_size <= 0:
            raise ValueError("max_size must >0")
        self.max_size = max_size
        self.stale_ms = stale_ms
        self._data: Dict[Tuple[str, Timeframe], BarsSeries] = {}
        self._lock = threading.RLock()

    # ---------------- Public API ----------------
    def upsert(self, symbol: str, timeframe: Timeframe, bars: Iterable[BarDict]):
        """插入/追加一批 bars (时间升序). 如果超出容量, 丢弃最旧部分.

        要求: bars 中 ts 单调非递减.
        """
        bars_list = list(bars)
        if not bars_list:
            return
        ts_arr = np.asarray([b["ts"] for b in bars_list], dtype=np.int64)
        open_arr = np.asarray([b["open"] for b in bars_list], dtype=np.float64)
        high_arr = np.asarray([b["high"] for b in bars_list], dtype=np.float64)
        low_arr = np.asarray([b["low"] for b in bars_list], dtype=np.float64)
        close_arr = np.asarray([b["close"] for b in bars_list], dtype=np.float64)
        vol_arr = np.asarray([b.get("volume", 0.0) for b in bars_list], dtype=np.float64)
        key = (symbol, timeframe)
        with self._lock:
            cur = self._data.get(key)
            if cur is None:
                # 初次
                series = BarsSeries(symbol, timeframe, ts_arr, open_arr, high_arr, low_arr, close_arr, vol_arr, int(time.time()*1000))
                if len(series.ts) > self.max_size:
                    # 只保留后 max_size 部分
                    series = series.tail(self.max_size)
                    metrics.inc("barscache_truncated_init")
                self._data[key] = series
                metrics.inc("barscache_new_series")
                return
            # 追加: 过滤掉 <= last_ts 的重复
            mask = ts_arr > (cur.ts[-1] if len(cur.ts) else -1)
            if not mask.any():
                return
            ts_arr = ts_arr[mask]
            open_arr = open_arr[mask]
            high_arr = high_arr[mask]
            low_arr = low_arr[mask]
            close_arr = close_arr[mask]
            vol_arr = vol_arr[mask]
            # 连接
            ts_new = np.concatenate([cur.ts, ts_arr])
            open_new = np.concatenate([cur.open, open_arr])
            high_new = np.concatenate([cur.high, high_arr])
            low_new = np.concatenate([cur.low, low_arr])
            close_new = np.concatenate([cur.close, close_arr])
            vol_new = np.concatenate([cur.volume, vol_arr])
            # 容量裁剪
            if len(ts_new) > self.max_size:
                cut = len(ts_new) - self.max_size
                ts_new = ts_new[cut:]
                open_new = open_new[cut:]
                high_new = high_new[cut:]
                low_new = low_new[cut:]
                close_new = close_new[cut:]
                vol_new = vol_new[cut:]
                metrics.inc("barscache_truncated_append")
            self._data[key] = BarsSeries(symbol, timeframe, ts_new, open_new, high_new, low_new, close_new, vol_new, int(time.time()*1000))
            metrics.inc("barscache_append")

    def get(self, symbol: str, timeframe: Timeframe) -> Optional[BarsSeries]:
        with self._lock:
            return self._data.get((symbol, timeframe))

    def get_close(self, symbol: str, timeframe: Timeframe) -> Optional[np.ndarray]:  # noqa: D401
        series = self.get(symbol, timeframe)
        if series is None:
            return None
        return series.close

    def is_stale(self, symbol: str, timeframe: Timeframe) -> bool:
        series = self.get(symbol, timeframe)
        if series is None:
            return True
        age = int(time.time()*1000) - series.last_updated_ms
        return age > self.stale_ms

    def clear_symbol(self, symbol: str):
        with self._lock:
            to_del = [k for k in self._data.keys() if k[0] == symbol]
            for k in to_del:
                self._data.pop(k, None)
            if to_del:
                metrics.inc("barscache_clear_symbol")

__all__ = ["BarsCache", "BarsSeries", "BarDict", "Timeframe"]
