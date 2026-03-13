"""MarketDataService (Spec Task 8)

职责 (与规范 R2 AC2/3/4/5 对应):
- ensure_symbol: 订阅/跟踪用户添加的自选 symbol (AC2)
- load_initial: 首次拉取指定 timeframe K 线 (detail 首帧 ≤1s 可得) (AC3)
- get / request_detail: 提供图表模块所需的 BarsSeries + stale 检查 (AC3/4)
- append_realtime: 追加实时 bar (由外部事件流驱动) (AC4/5 支撑指标重算、窗口丢弃)
- 指标需求: get_closes / get_ohlcv 返回 numpy 序列给指标线程池 (AC4)
- 逐笔成交/L2: 这里预留接口 (Phase1 仅 K 线 + close) 后续接入 RingBuffer

设计 & 取舍:
- 后端真实 fetch API 尚未接入, 提供可注入 fetcher 回调; 默认使用 _synthetic_fetcher 生成确定性伪数据 (便于测试)
- 不直接耦合 EventBridge; 实时 bar 由控制器收到 snapshot/trade 后聚合再 append_realtime
- Timeframe 采用 bars_cache.Timeframe, 默认支持 1m/5m/15m/60m/1d

扩展点 (TODO 注释):
- TODO 逐笔成交缓存接入 RingBuffer (依赖 Task 5) 用于 AC5 流畅滚动
- TODO L2 深度缓存 (盘口前5/10档)
- TODO 与真实后端 API (MarketDataServiceAdapter) 对接替换 _synthetic_fetcher

"""
from __future__ import annotations
from typing import Callable, Dict, List, Optional, Set
import time
import math
import threading
import numpy as np

from observability.metrics import metrics
from .bars_cache import BarsCache, BarDict, Timeframe, BarsSeries

Fetcher = Callable[[str, Timeframe, int], List[BarDict]]

_TIMEFRAME_MS: Dict[Timeframe, int] = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "60m": 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}

class MarketDataService:
    def __init__(self, bars_cache: Optional[BarsCache] = None, *, fetcher: Optional[Fetcher] = None,
                 default_limit: int = 500):
        self._cache = bars_cache or BarsCache()
        self._fetcher: Fetcher = fetcher or _synthetic_fetcher
        self._subscribed: Set[str] = set()
        self._default_limit = default_limit
        self._lock = threading.RLock()

    # ---------------- Public API ----------------
    def ensure_symbol(self, symbol: str):  # R2 AC2
        with self._lock:
            if symbol in self._subscribed:
                return False
            self._subscribed.add(symbol)
            metrics.inc("market_subscribe")
            return True

    def load_initial(self, symbol: str, timeframe: Timeframe, *, limit: Optional[int] = None) -> BarsSeries:
        """拉取初始 K 线并写入缓存; 返回 BarsSeries. (R2 AC3)"""
        lim = limit or self._default_limit
        start_ms = time.perf_counter()
        bars = self._fetcher(symbol, timeframe, lim)
        self._cache.upsert(symbol, timeframe, bars)
        series = self._cache.get(symbol, timeframe)
        dur = (time.perf_counter() - start_ms) * 1000
        metrics.add_timing("market_load_initial_ms", dur)
        if series is None:  # 理论不应发生
            raise RuntimeError("failed to load initial bars")
        return series

    def append_realtime(self, symbol: str, timeframe: Timeframe, bar: dict[str, object]) -> None:  # R2 AC4/5 支撑
        # 假设 bar.ts >= 现有最后一根 ts
        self._cache.upsert(symbol, timeframe, [bar])  # type: ignore[arg-type]
        metrics.inc("market_realtime_bar")

    def get_closes(self, symbol: str, timeframe: Timeframe) -> Optional[np.ndarray]:
        return self._cache.get_close(symbol, timeframe)

    def get_ohlcv(self, symbol: str, timeframe: Timeframe) -> Optional[BarsSeries]:
        return self._cache.get(symbol, timeframe)

    def request_detail(self, symbol: str, timeframe: Timeframe, *, ensure_loaded: bool = True,
                        limit: Optional[int] = None) -> Dict[str, object]:
        """获取图表详情: 若尚未缓存且 ensure_loaded 则执行初次加载.
        返回: { 'series': BarsSeries|None, 'is_stale': bool, 'symbol': str, 'timeframe': timeframe }
        (R2 AC3/4)
        """
        series = self._cache.get(symbol, timeframe)
        if series is None and ensure_loaded:
            series = self.load_initial(symbol, timeframe, limit=limit)
        stale = self._cache.is_stale(symbol, timeframe)
        return {
            "series": series,
            "is_stale": stale,
            "symbol": symbol,
            "timeframe": timeframe,
        }

    # 方便测试: 暴露订阅列表
    def subscribed_symbols(self) -> List[str]:
        with self._lock:
            return list(self._subscribed)

# ---------------- Synthetic Fetcher (Fallback) ----------------

def _synthetic_fetcher(symbol: str, timeframe: Timeframe, limit: int) -> List[BarDict]:
    """生成确定性伪数据 (不依赖外部 IO). 用于本阶段集成测试.

    生成逻辑:
    - 基于 symbol hash 决定初始价格 base
    - 价格做一个平滑随机游走 (sin 波 + 噪声) 保证可视化
    - ts: 当前时间往前推 (limit-1)*interval 到现在
    """
    interval = _TIMEFRAME_MS[timeframe]
    now = int(time.time() * 1000)
    start = now - (limit - 1) * interval
    h = abs(hash(symbol)) % 10_000
    rng = np.random.default_rng(h)
    base = 50 + (h % 300) / 10.0  # 50 ~ 80
    bars: List[BarDict] = []
    price = base
    for i in range(limit):
        ts = start + i * interval
        # 波动: sin + 随机
        wave = math.sin(i / 20.0) * 0.5
        noise = rng.normal(0, 0.2)
        price = max(0.5, price + wave + noise)
        high = price + abs(rng.normal(0, 0.3))
        low = max(0.1, price - abs(rng.normal(0, 0.3)))
        open_ = price + rng.normal(0, 0.15)
        close = price + rng.normal(0, 0.15)
        vol = max(1.0, abs(rng.normal(100, 20)))
        bars.append({
            "ts": ts,
            "open": float(open_),
            "high": float(max(open_, high, close)),  # 保证 high>=
            "low": float(min(open_, low, close)),    # 保证 low<=
            "close": float(close),
            "volume": float(vol),
        })
    return bars

__all__ = [
    "MarketDataService",
    "_synthetic_fetcher",
]
