# python
# file: services/market_data_service.py
from __future__ import annotations
from typing import Optional, List, Tuple, Any

class MarketDataService:
    """
    统一对外提供快照。
    职责边界改进：
      - 优先调用撮合引擎的 get_snapshot(levels)（若存在），确保撮合内部维护的成交累计/last_price 权威。
      - 若无该方法，退化使用 engine.snapshot （属性）。
      - 始终基于引擎真实订单簿重建盘口（bids/asks 聚合），不在此层新增撮合或状态变更。
      - 保留兜底 last_price / mid 填充与成交补齐逻辑。
    """
    def __init__(self, engine: Any):
        self.engine = engine

    def snapshot(self, levels: int = 5):
        # 1) 获取基础快照对象（权威来源）
        if hasattr(self.engine, "get_snapshot"):
            snap = self.engine.get_snapshot(levels)
        else:
            snap = getattr(self.engine, "snapshot")  # 引擎内部的 snapshot 属性
        # 2) 汇总盘口（两种内部结构适配）
        if hasattr(self.engine, "_bids") and hasattr(self.engine, "_asks"):
            bids = sorted(
                (
                    (px, sum(o.remaining for o in arr if o.is_active))
                    for px, arr in self.engine._bids.items()
                ),
                key=lambda x: x[0],
                reverse=True
            )
            asks = sorted(
                (
                    (px, sum(o.remaining for o in arr if o.is_active))
                    for px, arr in self.engine._asks.items()
                ),
                key=lambda x: x[0]
            )
            snap.update_book(bids, asks, levels)
        elif hasattr(self.engine, "order_book"):
            depth = self.engine.order_book.get_depth(levels)
            bids: List[Tuple[float, int]] = depth.get("bids", [])
            asks: List[Tuple[float, int]] = depth.get("asks", [])
            snap.update_book(bids, asks, levels)

        # 3) 若尚无 last_price 但引擎已有成交，补最后一笔
        if getattr(snap, "last_price", None) is None and getattr(self.engine, "trades", None):
            if self.engine.trades:
                last_tr = self.engine.trades[-1]
                if snap.volume == 0:
                    snap.update_trade(last_tr.price, last_tr.quantity)
                else:
                    snap.last_price = last_tr.price
                    snap.last_quantity = last_tr.quantity
                    snap.close_price = last_tr.price
                    if snap.open_price is None:
                        snap.open_price = last_tr.price
                        snap.high_price = last_tr.price
                        snap.low_price = last_tr.price

        # 4) 兜底填充
        snap.sanity_fill()
        return snap