"""MarketController (Spec Task 20)

职责 (R2):
- 接收 snapshot 批次 (来自 EventBridge FRONTEND_SNAPSHOT_BATCH_TOPIC) 合并最新行情
- 提供分页/过滤读取最新快照列表
- 提供指标请求接口 (异步) -> 使用 indicator_executor
- 与 MarketDataService 协作: 确保 symbol 订阅 + 初次 bars 加载 + 指标计算数据来源

Done 条件参考规范: 行情 1000 snapshot/s 压测时合并为少量批次 (依赖 EventBridge), 此处合并 O(n) 赋值。

Future Hooks (Task50):
- TODO: Kafka 推送 SNAPSHOT_DELTA (精简字段) 供外部消费
- TODO: L2 深度/逐笔独立增量通道 (拆分性能)
- TODO: 指标缓存命中率指标暴露 (metrics.indicator_cache_hit)
- TODO: 自适应批大小调优 Hook (基于延迟反馈)
"""
from __future__ import annotations
from typing import TYPE_CHECKING, Dict, List, Optional, Any, Callable
from threading import RLock
import time

from app.core_dto.snapshot import SnapshotDTO
from app.event_bridge import publish_instrument_created
from app.services.market_data_service import MarketDataService, Timeframe
from app.indicators.executor import indicator_executor
from observability.metrics import metrics
from app.utils.validators import safe_float, safe_int, derive_third_value, round_to_price_step
from observability.struct_logger import logger  # 新增结构化日志

if TYPE_CHECKING:
    from app.runtime_gateway import RuntimeGateway

__all__ = ["MarketController"]

IndicatorCallback = Callable[[Any, Any], None]  # (result, meta)
_DETAIL_SNAPSHOT_STALE_MS = 15_000

class MarketController:
    def __init__(self, service: MarketDataService, runtime_gateway: RuntimeGateway | None = None):
        self._service = service
        self._runtime_gateway = runtime_gateway
        self._lock = RLock()
        self._snapshots: Dict[str, SnapshotDTO] = {}
        self._batch_count = 0
        self._updated_in_batch = 0

    # ---------------- Snapshot Merge ----------------
    def merge_batch(self, snapshots: List[dict | SnapshotDTO]):
        """合并一批 snapshot. 后写覆盖 (最新)."""
        with self._lock:
            self._batch_count += 1
            updated = 0
            for s in snapshots:
                if isinstance(s, SnapshotDTO):
                    snap = s
                else:
                    snap = SnapshotDTO(**s)
                self._snapshots[snap.symbol] = snap
                updated += 1
            self._updated_in_batch = updated
        metrics.inc("market_controller_merge_batch")

    # ---------------- Read API ----------------
    def get_snapshot(self, symbol: str) -> Optional[SnapshotDTO]:
        with self._lock:
            return self._snapshots.get(symbol)

    def get_detail_snapshot(self, symbol: str, *, stale_after_ms: int = _DETAIL_SNAPSHOT_STALE_MS) -> Dict[str, Any]:
        snapshot = self.get_snapshot(symbol)
        snapshot_status = "missing"
        snapshot_age_ms: int | None = None
        timestamp_ms: int | None = None
        if snapshot is not None:
            try:
                timestamp_ms = int(snapshot.ts)
                snapshot_age_ms = max(0, int(time.time() * 1000) - timestamp_ms)
            except Exception:
                snapshot_age_ms = None
                timestamp_ms = None
            snapshot_status = (
                "stale"
                if snapshot_age_ms is not None and snapshot_age_ms > int(stale_after_ms)
                else "available"
            )
        snapshot_meta = {
            "source": "market-controller-merged-snapshot-cache",
            "authoritative": True,
            "status": snapshot_status,
            "refresh": "event-batch",
            "freshness_model": "snapshot-ts-age",
            "timestamp_ms": timestamp_ms,
            "age_ms": snapshot_age_ms,
            "stale_after_ms": int(stale_after_ms),
        }
        order_book = None
        order_book_meta = {
            "source": "snapshot-derived-order-book-view",
            "authoritative": True,
            "status": "missing",
            "refresh": "snapshot-update",
            "freshness_model": "inherit-snapshot-age",
            "derived_from": "snapshot",
            "age_ms": snapshot_age_ms,
            "stale_after_ms": int(stale_after_ms),
        }
        if snapshot is not None:
            order_book = {
                "bids": snapshot.bid_levels,
                "asks": snapshot.ask_levels,
            }
            order_book_meta["status"] = "stale" if snapshot_status == "stale" else "available"
        return {
            "snapshot": None if snapshot is None else snapshot.model_dump(),
            "snapshot_meta": snapshot_meta,
            "order_book": order_book,
            "order_book_meta": order_book_meta,
        }

    def list_snapshots(self, *, page: int = 1, page_size: int = 50, symbol_filter: Optional[str] = None,
                       sort_by: str = "symbol") -> Dict[str, Any]:
        with self._lock:
            items: List[SnapshotDTO] = list(self._snapshots.values())
        if symbol_filter:
            sf = symbol_filter.lower()
            items = [s for s in items if sf in s.symbol.lower()]
        if sort_by == "last":
            items.sort(key=lambda x: x.last, reverse=True)
        else:
            items.sort(key=lambda x: x.symbol)
        total = len(items)
        if page_size <= 0:
            page_size = 50
        start = (page - 1) * page_size
        if start >= total:
            paged: List[SnapshotDTO] = []
        else:
            paged = items[start:start + page_size]
        return {"total": total, "page": page, "page_size": page_size, "items": paged}

    def load_persisted_instruments(self) -> List[str]:
        gateway = self._runtime_gateway
        if gateway is None or not hasattr(gateway, "list_instruments"):
            return []
        try:
            rows = gateway.list_instruments(active_only=True)
        except Exception:
            return []
        snapshots: List[SnapshotDTO] = []
        symbols: List[str] = []
        now_ms = int(time.time() * 1000)
        for row in rows or []:
            symbol = str((row or {}).get("symbol") or "").strip().upper()
            if not symbol:
                continue
            symbols.append(symbol)
            price_raw = (row or {}).get("initial_price")
            try:
                reference_price = float(price_raw)
            except Exception:
                reference_price = 0.0
            if reference_price <= 0:
                reference_price = 0.0
            step_raw = (row or {}).get("tick_size")
            try:
                price_step = float(step_raw)
            except Exception:
                price_step = 0.01
            try:
                self._service.ensure_symbol(symbol)
                self._service.register_symbol_meta(
                    symbol,
                    reference_price=reference_price if reference_price > 0 else None,
                    price_step=price_step if price_step > 0 else 0.01,
                    limit_pct=0.10,
                )
            except Exception:
                pass
            with self._lock:
                exists = symbol in self._snapshots
            if exists:
                continue
            snapshots.append(
                SnapshotDTO(
                    symbol=symbol,
                    last=reference_price,
                    bid_levels=[],
                    ask_levels=[],
                    volume=0,
                    turnover=0.0,
                    ts=now_ms,
                    snapshot_id=f"{symbol}-instrument-bootstrap-{now_ms}",
                )
            )
        if snapshots:
            self.merge_batch(snapshots)
        return symbols

    # ---------------- Indicator Requests ---------------
    def request_indicator(self, *, symbol: str, timeframe: Timeframe, name: str, callback: Optional[IndicatorCallback] = None, **params):
        """提交指标计算任务。callback 可为两种签名之一:
        1) callback(result, meta_dict)
        2) callback(result, *, symbol=..., name=..., params=..., error=..., duration_ms=..., cache_key=...)
        以兼容历史测试 (旧版直接使用关键字形参)。"""
        # 确保订阅 & 初次加载
        self._service.ensure_symbol(symbol)
        closes = self._service.get_closes(symbol, timeframe)
        if closes is None:
            self._service.load_initial(symbol, timeframe)
            closes = self._service.get_closes(symbol, timeframe)
        if closes is None or len(closes) == 0:  # 仍无数据
            raise RuntimeError("no bars for symbol")

        def _cb(result, *, symbol, name, params, error, duration_ms, cache_key):  # noqa: ANN001
            meta = {
                "symbol": symbol,
                "name": name,
                "params": params,
                "error": error,
                "duration_ms": duration_ms,
                "cache_key": cache_key,
            }
            if callback:
                # 兼容两种调用方式
                try:
                    callback(result, meta)  # 优先新版 (result, meta)
                    return
                except TypeError:
                    try:
                        callback(result, **meta)  # 回退旧版关键字参数形式
                    except Exception:
                        pass
                except Exception:  # 其它异常直接吞掉避免影响执行器
                    pass
        return indicator_executor.submit(name, closes, symbol=symbol, callback=_cb, **params)

    def pending_indicator_jobs(self) -> int:
        return indicator_executor.pending_count()

    def create_instrument(self, *, name: str, symbol: str,
                          initial_price: float | int | str | None = None,
                          float_shares: int | str | None = None,
                          market_cap: float | int | str | None = None,
                          total_shares: int | str | None = None,
                          price_step: float = 0.01) -> dict:
        """
        创建新标的并广播 instrument-created 事件。
        规则：在 {float_shares, market_cap, initial_price} 三者中，必须且仅有一个为 None，由系统推导；
        校验所有数值非负，symbol/name 非空；订阅 symbol 并可选择触发初始数据加载。
        返回：标准化后的 payload 字典。
        """
        name = (name or "").strip()
        symbol = (symbol or "").strip().upper()
        if not name or not symbol:
            logger.log("instrument.create_failed", reason="EMPTY_NAME_OR_SYMBOL", name=name, symbol=symbol)
            raise ValueError("name/symbol 不能为空")
        # 三元推导
        none_count = sum(x is None for x in (float_shares, market_cap, initial_price))
        if none_count != 1:
            logger.log("instrument.create_failed", reason="TRIAD_COUNT_INVALID", name=name, symbol=symbol)
            raise ValueError("float_shares/market_cap/initial_price 必须且仅有一个缺失以供推导")
        try:
            # 执行推导
            derived = derive_third_value(
                float_shares=float_shares,
                market_cap=market_cap,
                price=initial_price,
                price_step=price_step,
            )
            if "float_shares" in derived:
                float_shares = derived["float_shares"]
            elif "market_cap" in derived:
                market_cap = derived["market_cap"]
            elif "price" in derived:
                initial_price = derived["price"]
            # 归一化与边界
            fs = safe_int(float_shares, min_value=0)
            mcap = safe_float(market_cap, min_value=0)
            price = round_to_price_step(initial_price, step=price_step)
            ts = safe_int(total_shares, min_value=fs) if total_shares is not None else fs
        except Exception as e:  # noqa: BLE001
            logger.log("instrument.create_failed", reason="VALIDATION_OR_DERIVE_ERROR", name=name, symbol=symbol, error=str(e))
            raise
        # 订阅并忽略异常
        try:
            self._service.ensure_symbol(symbol)
        except Exception:
            pass
        payload = {
            "name": name,
            "symbol": symbol,
            "initial_price": price,
            "float_shares": fs,
            "market_cap": mcap,
            "total_shares": ts,
            "price_step": price_step,
        }
        try:
            self._service.register_symbol_meta(symbol, reference_price=price, price_step=price_step, limit_pct=0.10)
        except Exception:
            pass
        runtime_registered = False
        if self._runtime_gateway is not None:
            try:
                runtime_registered = bool(
                    self._runtime_gateway.create_instrument(
                        symbol=symbol,
                        name=name,
                        price_step=price_step,
                        initial_price=price,
                        float_shares=fs,
                        market_cap=mcap,
                        total_shares=ts,
                    )
                )
            except Exception:
                runtime_registered = False
        payload["settlement_cycle"] = 1
        payload["ipo_opened"] = True
        payload["runtime_registered"] = runtime_registered
        # Runtime instrument creation and IPO bootstrap now route through RuntimeGateway.
        # 事件广播（统一为 instrument-created）
        try:
            publish_instrument_created(payload)
        except Exception as e:
            # 广播失败不影响创建返回，但记录日志
            logger.log("instrument.broadcast_failed", topic="instrument-created", name=name, symbol=symbol, error=str(e))
        logger.log(
            "instrument.created",
            topic="instrument-created",
            name=name,
            symbol=symbol,
            float_shares=fs,
            market_cap=mcap,
            initial_price=price,
            runtime_registered=runtime_registered,
            ipo_opened=True,
            settlement_cycle=1,
        )
        metrics.inc("instrument_created")
        return payload
