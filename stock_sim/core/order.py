# python
# file: core/order.py
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any
from stock_sim.core.const import OrderSide, OrderType, OrderStatus, TimeInForce

@dataclass(slots=True, eq=False)
class Order:
    symbol: str
    side: OrderSide
    price: float
    quantity: int
    account_id: Optional[str] = None
    order_type: OrderType = OrderType.LIMIT
    tif: TimeInForce = TimeInForce.GFD
    order_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts_created: datetime = field(default_factory=datetime.utcnow)
    ts_last: datetime = field(default_factory=datetime.utcnow)
    filled: int = 0
    status: OrderStatus = OrderStatus.NEW
    canceled: bool = False
    _orig_price: float = field(init=False)
    _meta: Dict[str, Any] = field(default_factory=dict)
    cost_acc: float = 0.0  # 累计真实成交金额(买单用于释放剩余冻结)

    def __post_init__(self):
        self._orig_price = self.price

    @property
    def remaining(self) -> int:
        return self.quantity - self.filled

    @property
    def is_active(self) -> bool:
        return self.status in (OrderStatus.NEW, OrderStatus.PARTIAL) and not self.canceled and self.remaining > 0

    @property
    def is_filled(self) -> bool:
        return self.remaining == 0 and self.status == OrderStatus.FILLED

    @property
    def is_market(self) -> bool:
        return self.order_type is OrderType.MARKET

    def fill(self, qty: int, trade_price: float | None = None):
        if qty <= 0 or self.remaining <= 0:
            return
        self.filled += qty
        if trade_price is not None:
            # 仅对买单统计真实成本；卖单可视需要扩展
            if self.side is OrderSide.BUY:
                self.cost_acc += trade_price * qty
        self.ts_last = datetime.utcnow()
        self.status = OrderStatus.FILLED if self.remaining == 0 else OrderStatus.PARTIAL

    def cancel(self, reason: str = ""):
        if self.is_active:
            self.canceled = True
            self.status = OrderStatus.CANCELED
            self._meta["cancel_reason"] = reason
            self.ts_last = datetime.utcnow()

    def replace_price(self, new_price: float):
        self.price = new_price
        self.ts_last = datetime.utcnow()

    def attach_meta(self, **kv):
        self._meta.update(kv)

    def to_dict(self):
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.name,
            "type": self.order_type.name,
            "tif": self.tif.name,
            "price": self.price,
            "orig_price": self._orig_price,
            "qty": self.quantity,
            "filled": self.filled,
            "remaining": self.remaining,
            "status": self.status.name,
            "canceled": self.canceled,
            "account_id": self.account_id,
            "ts_created": self.ts_created.isoformat(),
            "ts_last": self.ts_last.isoformat(),
            "meta": self._meta
        }