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
from collections import deque
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

_DEFAULT_TIMEFRAME: Timeframe = "1m"
class SymbolDetailPanel:
    def __init__(self, controller: MarketController, service: MarketDataService):
        self._ctl = controller
        self._svc = service
        self._lock = RLock()
        self._symbol: Optional[str] = None
        self._timeframe: Timeframe = _DEFAULT_TIMEFRAME
        self._series_cache: Optional[Any] = None  # BarsSeries
        self._is_stale: bool = False
        self._series_meta: Dict[str, Any] = {}
        self._chart_meta: Dict[str, Any] = {}
        self._last_loaded_ts: float = 0.0
        # 指标缓存 (已转换为 list)
        self._indicators: Dict[str, Any] = {}
        self._pending_jobs: set[str] = set()
        self._ma_window_default = 20
        # 新增: 逐笔成交缓存
        # 这里优先保证前端闭环状态稳定可见；使用简单 deque 作为权威视图源，
        # 避免在 app/runtime 混合导入路径下把最后一层展示状态绑死在优化结构上。
        self._trades: deque[TradeDTO] = deque(maxlen=1000)
        self._seen_trade_keys: deque[tuple[str, float, int, str, int]] = deque(maxlen=256)

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

    def _apply_series_info(self, series_info: Dict[str, Any]) -> None:
        self._series_cache = series_info.get("series")
        self._is_stale = bool(series_info.get("is_stale"))
        self._series_meta = dict(series_info.get("series_meta") or {})
        self._chart_meta = dict(series_info.get("chart_meta") or {})
        self._last_loaded_ts = time.time()

    def _build_snapshot_block(self, snapshot: Optional[SnapshotDTO]) -> tuple[Dict[str, Any] | None, Dict[str, Any]]:
        describe = getattr(self._ctl, "get_detail_snapshot", None)
        if callable(describe):
            detail = describe(self._symbol or "")
            return detail.get("snapshot"), dict(detail.get("snapshot_meta") or {})
        snapshot_status = 'missing'
        snapshot_age_ms: int | None = None
        if snapshot is not None:
            try:
                snapshot_age_ms = max(0, int(time.time() * 1000) - int(snapshot.ts))
            except Exception:
                snapshot_age_ms = None
            snapshot_status = 'available'
        snapshot_meta = {
            'source': 'market-controller-merged-snapshot-cache',
            'authoritative': True,
            'status': snapshot_status,
            'refresh': 'event-batch',
            'freshness_model': 'snapshot-ts-age',
            'timestamp_ms': None if snapshot is None else int(snapshot.ts),
            'age_ms': snapshot_age_ms,
            'stale_after_ms': 15_000,
        }
        return (None if snapshot is None else snapshot.model_dump(), snapshot_meta)

    def _build_order_book_block(
        self,
        snapshot: Optional[SnapshotDTO],
        snapshot_meta: Dict[str, Any],
    ) -> tuple[Dict[str, Any] | None, Dict[str, Any]]:
        describe = getattr(self._ctl, "get_detail_snapshot", None)
        if callable(describe):
            detail = describe(self._symbol or "")
            return detail.get("order_book"), dict(detail.get("order_book_meta") or {})
        order_book = None
        order_book_meta = {
            'source': 'snapshot-derived-order-book-view',
            'authoritative': True,
            'status': 'missing',
            'refresh': 'snapshot-update',
            'freshness_model': 'inherit-snapshot-age',
            'derived_from': 'snapshot',
        }
        if snapshot is not None:
            order_book = {"bids": snapshot.bid_levels, "asks": snapshot.ask_levels}
            order_book_meta['status'] = 'stale' if snapshot_meta.get('status') == 'stale' else 'available'
            order_book_meta['age_ms'] = snapshot_meta.get('age_ms')
            order_book_meta['stale_after_ms'] = snapshot_meta.get('stale_after_ms')
        return order_book, order_book_meta

    def _trade_key(self, trade: Dict[str, Any]) -> tuple[str, int | None, float, int]:
        return (
            str(trade.get('symbol') or ''),
            int(trade.get('ts')) if trade.get('ts') is not None else None,
            float(trade.get('price') or 0.0),
            int(trade.get('qty') or trade.get('quantity') or 0),
        )

    def _merge_trades(
        self,
        runtime_trades: List[Dict[str, Any]],
        local_trades: List[Dict[str, Any]],
        *,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen: set[tuple[str, int | None, float, int]] = set()
        for row in list(local_trades) + list(runtime_trades):
            key = self._trade_key(row)
            if key in seen:
                continue
            seen.add(key)
            merged.append(dict(row))
            if len(merged) >= max(int(limit), 1):
                break
        merged.sort(key=lambda item: int(item.get('ts') or 0), reverse=True)
        return merged[: max(int(limit), 1)]

    def _build_trades_meta(
        self,
        runtime_meta: Dict[str, Any],
        runtime_trades: List[Dict[str, Any]],
        local_trades: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        meta = dict(runtime_meta or {})
        if not local_trades:
            return meta or {
                'source': 'runtime-trade-log',
                'authoritative': True,
                'status': 'empty',
                'refresh': 'runtime-query',
            }
        if meta.get('status') == 'error':
            return {
                'source': 'local-symbol-detail-ring-buffer',
                'authoritative': False,
                'status': 'available',
                'refresh': 'event-append',
            }
        if runtime_trades:
            return {
                'source': 'runtime-trade-log+local-overlay',
                'authoritative': bool(meta.get('authoritative', True)),
                'status': 'available',
                'refresh': 'runtime-query+event-append',
            }
        return {
            'source': 'runtime-trade-log+local-overlay',
            'authoritative': bool(meta.get('authoritative', True)),
            'status': 'available',
            'refresh': 'runtime-query+event-append',
        }

    def _build_indicators_meta(self, indicators_copy: Dict[str, Any], pending_jobs: set[str]) -> Dict[str, Any]:
        return {
            'source': 'indicator-executor-from-series',
            'authoritative': False,
            'status': 'available' if indicators_copy else ('pending' if pending_jobs else 'missing'),
            'refresh': 'load-refresh-recompute',
        }

    def _build_detail_health(
        self,
        *,
        series_meta: Dict[str, Any],
        snapshot_meta: Dict[str, Any],
        order_book_meta: Dict[str, Any],
        trades_meta: Dict[str, Any],
        holdings_meta: Dict[str, Any],
        indicators_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        series_status = str(series_meta.get('status') or 'missing')
        snapshot_status = str(snapshot_meta.get('status') or 'missing')
        order_book_status = str(order_book_meta.get('status') or 'missing')
        trades_status = str(trades_meta.get('status') or 'empty')
        holdings_status = str(holdings_meta.get('status') or 'placeholder')
        indicators_status = str(indicators_meta.get('status') or 'missing')
        core_block_status = {
            'series': series_status,
            'snapshot': snapshot_status,
            'order_book': order_book_status,
        }
        degraded_core_states = {'missing', 'stale', 'error', 'placeholder'}
        overall = 'degraded' if any(v in degraded_core_states for v in core_block_status.values()) else 'ok'
        return {
            'series_status': series_status,
            'snapshot_status': snapshot_status,
            'order_book_status': order_book_status,
            'trades_status': trades_status,
            'holdings_status': holdings_status,
            'indicators_status': indicators_status,
            'overall': overall,
            'core_blocks': core_block_status,
            'auxiliary_blocks': {
                'trades': trades_status,
                'holdings': holdings_status,
                'indicators': indicators_status,
            },
        }

    # ---------- Public API ----------
    def selected_symbol(self) -> Optional[str]:
        with self._lock:
            return self._symbol

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
            self._apply_series_info(series_info)
            # 清空旧指标 (长度可能不同)
            self._indicators.clear()
            self._pending_jobs.clear()
            # 新 symbol 清空逐笔
            self._trades.clear()
            self._seen_trade_keys.clear()
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
            self._apply_series_info(series_info)
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
                raw = dict(trade)
                ts_v = raw.get('ts')
                ts_ms: int
                if isinstance(ts_v, int):
                    ts_ms = ts_v if ts_v >= 10_000_000_000 else ts_v * 1000
                elif isinstance(ts_v, float):
                    ts_ms = int(ts_v if ts_v >= 10_000_000_000 else ts_v * 1000)
                elif isinstance(ts_v, str):
                    try:
                        iv = int(ts_v)
                        ts_ms = iv if iv >= 10_000_000_000 else iv * 1000
                    except Exception:
                        dt = time.strptime(ts_v.split('.')[0], "%Y-%m-%dT%H:%M:%S")
                        ts_ms = int(time.mktime(dt) * 1000)
                else:
                    ts_ms = int(time.time() * 1000)

                side_v = raw.get('side')
                side_s = str(side_v).lower() if side_v is not None else ''
                if side_s not in {'buy', 'sell'}:
                    side_s = 'buy'

                normalized = {
                    'symbol': raw.get('symbol'),
                    'price': raw.get('price'),
                    'qty': raw.get('qty') if raw.get('qty') is not None else raw.get('quantity'),
                    'side': side_s,
                    'ts': ts_ms,
                }
                trade = TradeDTO(**normalized)
            except Exception:  # pragma: no cover
                return
        with self._lock:
            trade_symbol = trade.symbol
            if self._symbol is None or trade_symbol != self._symbol:
                return
            trade_key = (trade.symbol, float(trade.price), int(trade.qty), str(trade.side), int(trade.ts))
            if trade_key in self._seen_trade_keys:
                return
            self._seen_trade_keys.append(trade_key)
            self._trades.append(trade)
        try:
            self._svc.record_runtime_trade(
                trade.symbol,
                price=float(trade.price),
                qty=int(trade.qty),
                ts_ms=int(trade.ts),
            )
        except Exception:
            pass
        try:
            self.refresh()
        except Exception:
            pass

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
            series_meta = dict(self._series_meta)
            chart_meta = dict(self._chart_meta)
            indicators_copy = {k: v if not isinstance(v, list) else list(v) for k, v in self._indicators.items()}
            pending_jobs = set(self._pending_jobs)
            local_trades = [t.model_dump() if hasattr(t, 'model_dump') else t.dict() for t in list(self._trades)]

        snapshot: Optional[SnapshotDTO] = self._ctl.get_snapshot(sym) if sym else None
        snapshot_obj, snapshot_meta = self._build_snapshot_block(snapshot)

        series_obj = None
        series_status = str(series_meta.get('status') or 'missing')
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
                series_status = 'error'
                series_meta['status'] = 'error'
        if bool(series_meta.get('placeholder')):
            series_meta['note'] = 'default synthetic series for non-authoritative fallback only'

        order_book, order_book_meta = self._build_order_book_block(snapshot, snapshot_meta)
        get_trades_detail = getattr(self._svc, "get_trades_detail", None)
        if callable(get_trades_detail) and sym:
            trades_info = get_trades_detail(sym)
        else:
            trades_info = {"trades": [], "trades_meta": {"status": "missing", "source": "unavailable"}}
        runtime_trades = list(trades_info.get("trades") or [])
        trades_list = self._merge_trades(runtime_trades, local_trades, limit=20)
        trades_meta = self._build_trades_meta(
            dict(trades_info.get("trades_meta") or {}),
            runtime_trades,
            local_trades,
        )
        indicators_meta = self._build_indicators_meta(indicators_copy, pending_jobs)
        get_holdings_detail = getattr(self._svc, "get_holdings_detail", None)
        if callable(get_holdings_detail):
            holdings_info = get_holdings_detail(sym or "")
        else:
            holdings_info = {
                "holdings": None,
                "holdings_meta": {
                    "status": "unavailable",
                    "source": "service-missing",
                    "authoritative": False,
                },
            }
        holdings = holdings_info.get("holdings")
        holdings_meta = dict(holdings_info.get("holdings_meta") or {})
        detail_health = self._build_detail_health(
            series_meta=series_meta,
            snapshot_meta=snapshot_meta,
            order_book_meta=order_book_meta,
            trades_meta=trades_meta,
            holdings_meta=holdings_meta,
            indicators_meta=indicators_meta,
        )
        return {
            "symbol": sym,
            "timeframe": tf,
            "series": series_obj,
            "series_meta": series_meta,
            "chart_meta": chart_meta,
            "is_stale": stale,
            "snapshot": snapshot_obj,
            "snapshot_meta": snapshot_meta,
            "order_book": order_book,
            "order_book_meta": order_book_meta,
            "trades": trades_list,
            "trades_meta": trades_meta,
            "indicators": indicators_copy,
            "indicators_meta": indicators_meta,
            "holdings": holdings,
            "holdings_meta": holdings_meta,
            "detail_health": detail_health,
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
            "selected": self._detail.selected_symbol(),
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
