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
from typing import Dict, List, Optional, Any, Callable
from threading import RLock

from app.core_dto.snapshot import SnapshotDTO
from app.services.market_data_service import MarketDataService, Timeframe
from app.indicators.executor import indicator_executor
from observability.metrics import metrics
from infra.event_bus import event_bus
from app.utils.validators import safe_float, safe_int, derive_third_value, round_to_price_step
from observability.struct_logger import logger  # 新增结构化日志

__all__ = ["MarketController"]

IndicatorCallback = Callable[[Any, Any], None]  # (result, meta)

class MarketController:
    def __init__(self, service: MarketDataService):
        self._service = service
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
        # 事件广播（统一为 instrument-created）
        try:
            event_bus.publish("instrument-created", payload)
        except Exception as e:
            # 广播失败不影响创建返回，但记录日志
            logger.log("instrument.broadcast_failed", topic="instrument-created", name=name, symbol=symbol, error=str(e))
        logger.log("instrument.created", topic="instrument-created", name=name, symbol=symbol, float_shares=fs, market_cap=mcap, initial_price=price)
        metrics.inc("instrument_created")
        return payload
