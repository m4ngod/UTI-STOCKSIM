# python
# file: core/call_auction.py
from __future__ import annotations
from typing import List, Tuple
from stock_sim.core.order import Order
from stock_sim.core.const import OrderSide
from stock_sim.core.trade import Trade

class CallAuction:
    """
    简化集合竞价：
      - 输入所有限价单
      - 计算各价位累积买卖量，选取最大可成交量、最小剩余差、若多价并列取中间价
    """
    def __init__(self, symbol: str):
        self.symbol = symbol
        self._orders: List[Order] = []

    def add(self, order: Order):
        self._orders.append(order)

    def _price_points(self) -> List[float]:
        return sorted({o.price for o in self._orders})

    def run(self) -> Tuple[float | None, List[Trade]]:
        if not self._orders:
            return None, []
        price_points = self._price_points()
        best_price = None
        best_exec = -1
        best_imbalance = 10**18
        # 预聚合
        bids = [o for o in self._orders if o.side is OrderSide.BUY]
        asks = [o for o in self._orders if o.side is OrderSide.SELL]
        for p in price_points:
            buy_vol = sum(o.remaining for o in bids if o.price >= p)
            sell_vol = sum(o.remaining for o in asks if o.price <= p)
            exec_vol = min(buy_vol, sell_vol)
            imbalance = abs(buy_vol - sell_vol)
            if exec_vol > best_exec or (exec_vol == best_exec and imbalance < best_imbalance):
                best_exec = exec_vol
                best_price = p
                best_imbalance = imbalance
        if best_price is None or best_exec <= 0:
            return None, []
        # 按价格优先 / 时间优先撮合到 best_exec
        trades: List[Trade] = []
        remaining = best_exec
        buy_queue = sorted([o for o in bids if o.price >= best_price], key=lambda x: ( -x.price, x.ts_created ))
        sell_queue = sorted([o for o in asks if o.price <= best_price], key=lambda x: ( x.price, x.ts_created ))
        bi = si = 0
        while remaining > 0 and bi < len(buy_queue) and si < len(sell_queue):
            b = buy_queue[bi]
            s = sell_queue[si]
            qty = min(b.remaining, s.remaining, remaining)
            if qty <= 0:
                break
            b.fill(qty)
            s.fill(qty)
            trades.append(Trade(
                symbol=self.symbol,
                price=best_price,
                quantity=qty,
                buy_order_id=b.order_id,
                sell_order_id=s.order_id,
                buy_account_id=b.account_id or "",
                sell_account_id=s.account_id or ""
            ))
            remaining -= qty
            if b.remaining == 0: bi += 1
            if s.remaining == 0: si += 1
        return best_price, trades

    def remaining_orders(self) -> List[Order]:
        return [o for o in self._orders if o.is_active and o.remaining > 0]