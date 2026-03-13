# python
# file: core/trade.py
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
import uuid

@dataclass(slots=True)
class Trade:
    symbol: str
    price: float
    quantity: int
    buy_order_id: str
    sell_order_id: str
    buy_account_id: str
    sell_account_id: str
    trade_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self):
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "price": self.price,
            "qty": self.quantity,
            "buy_order_id": self.buy_order_id,
            "sell_order_id": self.sell_order_id,
            "buy_account_id": self.buy_account_id,
            "sell_account_id": self.sell_account_id,
            "ts": self.ts.isoformat()
        }