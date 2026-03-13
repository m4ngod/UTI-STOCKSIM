"""MarketPanel & SymbolDetailPanel (Spec Task 25)

职责 (R2):
- MarketPanel: 维护自选(symbol watchlist) + 快照分页/过滤/排序视图
- 支持添加/移除自选、选中某 symbol 打开详情 (调用 SymbolDetailPanel)
- SymbolDetailPanel: 提供指定 symbol 在 timeframe 上的 K 线/最新快照/盘口与占位逐笔数据

设计原则:
- 纯逻辑, 不依赖具体 UI 框架
- 线程安全: 简单 RLock 覆盖写操作与读取视图
- 惰性加载: 首次选中 symbol 时若未订阅/未加载初始 K 线则触发 MarketDataService.ensure_symbol + load_initial

性能/扩展 TODO:
- TODO: 与事件桥接收 snapshot 增量联动刷新 (当前拉取由外部调用 get_view 时即时读取 controller)
- TODO: L2 盘口/逐笔成交 RingBuffer 集成 (Task 5 RingBuffer) 以支撑 5000 行滚动 ≥30FPS
- TODO: 指标叠加支持 (调用 MarketController.request_indicator)
- TODO: watchlist 持久化 (SettingsStore / LayoutPersistence)
"""
from __future__ import annotations
from typing import List, Optional, Dict, Any
from threading import RLock
import time
# 新增: 可选 WatchlistStore 持久化
try:  # pragma: no cover - 运行时若未导入
    from app.services.watchlist_store import WatchlistStore  # type: ignore
except Exception:  # pragma: no cover
    WatchlistStore = None  # type: ignore

from app.controllers.market_controller import MarketController
from app.services.market_data_service import MarketDataService, Timeframe
from app.core_dto.snapshot import SnapshotDTO
from app.core_dto.trade import TradeDTO  # 新增
from app.utils.ring_buffer import RingBuffer  # 新增
# 新增: 指标执行器
try:
    from app.indicators.executor import indicator_executor
except Exception:  # pragma: no cover
    indicator_executor = None  # type: ignore

try:  # 轻量 metrics (可选)
    from observability.metrics import metrics
except Exception:  # pragma: no cover
    class _DummyMetrics:  # noqa: D401
        def inc(self, *_, **__):
            pass
        def add_timing(self, *_, **__):
            pass
    metrics = _DummyMetrics()

__all__ = ["MarketPanel", "SymbolDetailPanel"]

_DEFAULT_TIMEFRAME: Timeframe = "1d"

class SymbolDetailPanel:
    def __init__(self, controller: MarketController, service: MarketDataService):
        self._ctl = controller
        self._svc = service
        self._lock = RLock()
        self._symbol: Optional[str] = None
        self._timeframe: Timeframe = _DEFAULT_TIMEFRAME
        self._series_cache: Optional[Any] = None  # BarsSeries
        self._is_stale: bool = False
        self._last_loaded_ts: float = 0.0
        # 指标缓存 (已转换为 list)
        self._indicators: Dict[str, Any] = {}
        self._pending_jobs: set[str] = set()
        self._ma_window_default = 20
        # 新增: 逐笔成交 ring buffer
        self._trades: RingBuffer[TradeDTO] = RingBuffer(capacity=1000, metrics_prefix="trades_rb")

    # ---------- Internal Helpers ----------
    def _schedule_indicators(self, symbol: str, timeframe: Timeframe):
        if indicator_executor is None:
            return
        closes = self._svc.get_closes(symbol, timeframe)
        if closes is None:
            return
        arr = closes.tolist()  # 转 list 使线程安全复制
        # 构建唯一 job key 以避免重复提交
        key_ma = f"{symbol}:{timeframe}:ma:{self._ma_window_default}:{len(arr)}"
        key_macd = f"{symbol}:{timeframe}:macd:{len(arr)}"
        with self._lock:
            if key_ma in self._pending_jobs or key_macd in self._pending_jobs:
                return
            # 清除旧的 (长度变化说明有新数据, 让缓存失效)
            self._pending_jobs.add(key_ma)
            self._pending_jobs.add(key_macd)
        # 提交 MA
        def _cb_ma(res, *, symbol, name, params, error, duration_ms, cache_key):  # noqa: D401
            indicator_executor.poll_callbacks() if False else None  # 仅保证引用 (避免 lint)
            with self._lock:
                if error is None and res is not None:
                    self._indicators[f"ma{params.get('window')}"] = list(res)
                self._pending_jobs.discard(key_ma)
        indicator_executor.submit('ma', arr, symbol=symbol, window=self._ma_window_default, callback=_cb_ma)
        # 提交 MACD
        def _cb_macd(res, *, symbol, name, params, error, duration_ms, cache_key):  # noqa: D401
            with self._lock:
                if error is None and isinstance(res, dict):
                    self._indicators['macd'] = {k: list(v) for k, v in res.items()}
                self._pending_jobs.discard(key_macd)
        indicator_executor.submit('macd', arr, symbol=symbol, fast=12, slow=26, signal=9, callback=_cb_macd)

    # ---------- Public API ----------
    def load_symbol(self, symbol: str, timeframe: Optional[Timeframe] = None):
        start = time.perf_counter()
        with self._lock:
            current_tf = self._timeframe
        tf: Timeframe = timeframe if timeframe is not None else current_tf
        self._svc.ensure_symbol(symbol)
        series_info = self._svc.request_detail(symbol, tf, ensure_loaded=True)
        with self._lock:
            self._symbol = symbol
            self._timeframe = tf
            self._series_cache = series_info.get("series")
            self._is_stale = bool(series_info.get("is_stale"))
            self._last_loaded_ts = time.time()
            # 清空旧指标 (长度可能不同)
            self._indicators.clear()
            self._pending_jobs.clear()
            # 新 symbol 清空逐笔
            self._trades.clear()
        # 指标缓存失效（同一 symbol 重新加载）
        try:  # pragma: no cover
            if indicator_executor is not None:
                indicator_executor.invalidate_symbol(symbol)
        except Exception:
            pass
        self._schedule_indicators(symbol, tf)
        metrics.inc("symbol_detail_load")
        metrics.add_timing("symbol_detail_load_ms", (time.perf_counter() - start) * 1000)

    def set_timeframe(self, timeframe: Timeframe):
        with self._lock:
            sym = self._symbol
        if sym is None:
            self._timeframe = timeframe
            return
        self.load_symbol(sym, timeframe)

    def refresh(self):  # 主动刷新
        with self._lock:
            sym = self._symbol
            tf = self._timeframe
        if not sym:
            return
        series_info = self._svc.request_detail(sym, tf, ensure_loaded=True)
        with self._lock:
            old_len = len(self._series_cache.ts) if self._series_cache is not None else 0  # type: ignore[arg-type]
            self._series_cache = series_info.get("series")
            self._is_stale = bool(series_info.get("is_stale"))
            self._last_loaded_ts = time.time()
            new_len = len(self._series_cache.ts) if self._series_cache is not None else 0  # type: ignore[arg-type]
        # 若长度变化, 失效对应 symbol 缓存 (避免缓存无限增长 & 及时使用最新数据)
        if new_len != old_len:
            try:  # pragma: no cover
                if indicator_executor is not None:
                    indicator_executor.invalidate_symbol(sym)
            except Exception:
                pass
        # 调度指标 (若新增 bar 则长度变化使用新 key)
        self._schedule_indicators(sym, tf)
        metrics.inc("symbol_detail_refresh")

    # 新增: 接收逐笔 (外部事件驱动调用)
    def add_trade(self, trade: TradeDTO | dict):  # noqa: D401
        if isinstance(trade, dict):
            try:
                trade = TradeDTO(**trade)
            except Exception:  # pragma: no cover
                return
        with self._lock:
            if self._symbol is None or trade.symbol != self._symbol:
                return
            self._trades.append(trade)

    def add_trades(self, trades):  # 批量
        for t in trades:
            self.add_trade(t)

    def get_view(self) -> Dict[str, Any]:
        # 轮询执行器回调 (轻量, 由 UI 周期调用 get_view 即可触发更新)
        try:
            if indicator_executor is not None:
                indicator_executor.poll_callbacks()
        except Exception:  # pragma: no cover
            pass
        with self._lock:
            sym = self._symbol
            tf = self._timeframe
            series = self._series_cache
            stale = self._is_stale
            indicators_copy = {k: v if not isinstance(v, list) else list(v) for k, v in self._indicators.items()}
            trades_list = [t.dict() for t in self._trades.to_list()]
        snapshot: Optional[SnapshotDTO] = self._ctl.get_snapshot(sym) if sym else None
        series_obj = None
        if series is not None:
            try:
                series_obj = {
                    "ts": list(series.ts),
                    "open": list(series.open),
                    "high": list(series.high),
                    "low": list(series.low),
                    "close": list(series.close),
                    "volume": list(series.volume),
                }
            except Exception:  # pragma: no cover
                series_obj = None
        order_book = None
        if snapshot:
            order_book = {"bids": snapshot.bid_levels, "asks": snapshot.ask_levels}
        # holdings：尝试服务提供，否则占位
        holdings = None
        try:
            get_hold = getattr(self._svc, 'get_retail_holdings', None)
            if callable(get_hold) and sym:
                holdings = get_hold(sym)
        except Exception:
            holdings = None
        if holdings is None:
            try:
                holdings = {
                    'labels': ['Retail-MS-1','Retail-MS-2','Retail-MS-3'],
                    'pct': [50.0, 30.0, 20.0],
                }
            except Exception:
                holdings = None
        return {
            "symbol": sym,
            "timeframe": tf,
            "series": series_obj,
            "is_stale": stale,
            "snapshot": None if snapshot is None else snapshot.dict(),
            "order_book": order_book,
            "trades": trades_list,
            "indicators": indicators_copy,
            "holdings": holdings,
        }

class MarketPanel:
    def __init__(self, controller: MarketController, service: MarketDataService, watchlist_store: Optional["WatchlistStore"] = None):
        self._ctl = controller
        self._svc = service
        self._lock = RLock()
        self._watchlist: List[str] = []
        self._filter: Optional[str] = None
        self._page: int = 1
        self._page_size: int = 20
        self._sort_by: str = "symbol"  # or "last"
        self._detail = SymbolDetailPanel(controller, service)
        self._store = watchlist_store
        # 初始加载持久化 watchlist
        if self._store is not None:
            try:
                loaded = self._store.load()
                if loaded:
                    self._watchlist = list(dict.fromkeys(loaded))  # 去重保持顺序
            except Exception:  # pragma: no cover
                pass

    # ---------- Watchlist Ops ----------
    def _persist(self):  # 内部调用; 去抖由 store 处理
        if self._store is not None:
            try:
                self._store.set_symbols(self._watchlist)
            except Exception:  # pragma: no cover
                pass

    def add_symbol(self, symbol: str):
        symbol = symbol.strip()
        if not symbol:
            return
        with self._lock:
            if symbol not in self._watchlist:
                self._watchlist.append(symbol)
                persist_needed = True
            else:
                persist_needed = False
        if persist_needed:
            self._persist()
        self._svc.ensure_symbol(symbol)
        metrics.inc("market_panel_add_symbol")

    def remove_symbol(self, symbol: str):
        changed = False
        with self._lock:
            try:
                self._watchlist.remove(symbol)
                changed = True
            except ValueError:
                return
        if changed:
            self._persist()
        metrics.inc("market_panel_remove_symbol")

    def set_filter(self, substring: Optional[str]):
        with self._lock:
            self._filter = substring.lower() if substring else None

    def set_page(self, page: int, page_size: int):
        with self._lock:
            if page >= 1:
                self._page = page
            if page_size > 0:
                self._page_size = page_size

    def set_sort(self, sort_by: str):
        if sort_by not in ("symbol", "last"):
            return
        with self._lock:
            self._sort_by = sort_by

    def select_symbol(self, symbol: str, timeframe: Optional[Timeframe] = None):
        self._detail.load_symbol(symbol, timeframe)

    def add_trade(self, trade):  # 代理
        self._detail.add_trade(trade)

    def detail_view(self) -> Dict[str, Any]:  # 代理
        return self._detail.get_view()

    # ---------- View ----------
    def get_view(self) -> Dict[str, Any]:
        with self._lock:
            watch = list(self._watchlist)
            filt = self._filter
            page = self._page
            page_size = self._page_size
            sort_by = self._sort_by
        controller_list = self._ctl.list_snapshots(page=1, page_size=5000, symbol_filter=None, sort_by=sort_by)
        items: List[SnapshotDTO] = controller_list["items"]
        items_map = {s.symbol: s for s in items}
        filtered: List[SnapshotDTO] = []
        for sym in watch:
            snap = items_map.get(sym)
            if snap is None:
                filtered.append(SnapshotDTO(symbol=sym, last=0.0, bid_levels=[], ask_levels=[], volume=0, turnover=0.0, ts=0, snapshot_id="-"))
            else:
                filtered.append(snap)
        if filt:
            filtered = [s for s in filtered if filt in s.symbol.lower()]
        if sort_by == "last":
            filtered.sort(key=lambda x: x.last, reverse=True)
        else:
            filtered.sort(key=lambda x: x.symbol)
        total = len(filtered)
        start = (page - 1) * page_size
        paged = filtered[start:start + page_size] if start < total else []
        view_items = [self._snapshot_view(s) for s in paged]
        return {
            "watchlist": {
                "symbols": watch,
                "snapshots": {
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "items": view_items,
                },
            },
            "filter": filt,
            "sort_by": sort_by,
            "selected": self._detail.get_view().get("symbol"),
        }

    @staticmethod
    def _snapshot_view(s: SnapshotDTO) -> Dict[str, Any]:
        return {
            "symbol": s.symbol,
            "last": s.last,
            "volume": s.volume,
            "turnover": s.turnover,
            "ts": s.ts,
            "snapshot_id": s.snapshot_id,
        }
