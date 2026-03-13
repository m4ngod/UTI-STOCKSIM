# python
from __future__ import annotations
from typing import List, Optional
from .order import Order
from .order_book import OrderBook
from .trade import Trade
from .const import OrderSide, OrderStatus
from .snapshot import Snapshot
from stock_sim.settings import settings

class AuctionMatchingEngine:
    """
    简化版集合竞价 + 连续竞价撮合引擎：
      - 竞价阶段：仅收集订单
      - finalize_open: 计算撮合，生成成交；未成交残余全部标记为取消（不进入连续）
      - 连续阶段：价/时间优先逐笔撮合
    统一：提供 get_snapshot(levels) 与 snapshot 属性（内部缓存 Snapshot）。
    """
    def __init__(self, symbol: str,
                 instrument=None,
                 enable_auction: bool = True,
                 fast_mode: bool = True):
        self.symbol = symbol
        self.instrument = instrument
        self.enable_auction = enable_auction
        self.fast_mode = fast_mode
        self.order_book = OrderBook(symbol)
        self._auction_phase = enable_auction
        self.trades: List[Trade] = []
        self._orders: dict[str, Order] = {}
        self._snapshot: Snapshot = Snapshot(symbol=symbol)
        self.auction_canceled_order_ids: List[str] = []

    # ------------- Snapshot API -------------
    @property
    def snapshot(self) -> Snapshot:  # 向后兼容
        return self.get_snapshot()

    def get_snapshot(self, levels: int = 10) -> Snapshot:
        self._snapshot = self.order_book.build_snapshot(levels=levels, prev=self._snapshot)
        return self._snapshot

    # ------------- Public API -------------
    def get_order(self, order_id: str) -> Optional[Order]:
        return self._orders.get(order_id)

    @property
    def in_auction(self) -> bool:
        return self._auction_phase

    def submit_order(self, order: Order, skip_freeze: bool = False) -> List[Trade]:
        self._orders[order.order_id] = order
        if self._auction_phase:
            order.status = OrderStatus.NEW
            self.order_book.add_order(order)
            self.get_snapshot()  # 更新盘口
            return []
        self.order_book.add_order(order)
        trades = self._match_continuous(order)
        self.trades.extend(trades)
        if trades:
            snap = self.order_book.last_snapshot() or self._snapshot
            for tr in trades:
                snap.update_trade(tr.price, tr.quantity)
            self._snapshot = snap
        self.get_snapshot()
        return trades

    def cancel_order(self, order_id: str) -> bool:
        o = self._orders.get(order_id)
        if not o or not o.is_active:
            return False
        self.order_book.cancel(order_id)
        self.get_snapshot()
        return True

    def finalize_open(self, prev_close: float) -> List[Trade]:
        if not self._auction_phase:
            return []
        self._auction_phase = False
        buys = sorted([o for o in self.order_book.all_bids() if o.is_active],
                      key=lambda x: (-x.price, x.ts_created))
        sells = sorted([o for o in self.order_book.all_asks() if o.is_active],
                       key=lambda x: (x.price, x.ts_created))
        trades: List[Trade] = []
        bi = si = 0
        while bi < len(buys) and si < len(sells):
            b = buys[bi]; s = sells[si]
            if b.price < s.price:
                break
            px = prev_close
            if not (s.price <= px <= b.price):
                px = round((b.price + s.price) / 2, 6)
            qty = min(b.remaining, s.remaining)
            if qty <= 0:
                break
            b.fill(qty, trade_price=px if b.side is OrderSide.BUY else None)
            s.fill(qty, trade_price=px if s.side is OrderSide.BUY else None)
            tr = Trade(symbol=self.symbol, price=px, quantity=qty,
                       buy_order_id=b.order_id, sell_order_id=s.order_id,
                       buy_account_id=b.account_id or "",
                       sell_account_id=s.account_id or "")
            trades.append(tr)
            if b.remaining <= 0:
                bi += 1
            if s.remaining <= 0:
                si += 1
        remaining_orders = set()
        for idx in range(bi, len(buys)):
            if buys[idx].remaining > 0: remaining_orders.add(buys[idx])
        for idx in range(si, len(sells)):
            if sells[idx].remaining > 0: remaining_orders.add(sells[idx])
        for o in buys[:bi]:
            if o.remaining > 0 and o.is_active: remaining_orders.add(o)
        for o in sells[:si]:
            if o.remaining > 0 and o.is_active: remaining_orders.add(o)
        for o in remaining_orders:
            o.cancel("AUCTION_UNMATCHED")
            self.auction_canceled_order_ids.append(o.order_id)
        self._purge_after_auction()
        self.trades.extend(trades)
        if trades:
            for tr in trades:
                self._snapshot.update_trade(tr.price, tr.quantity)
        # 生成开盘初始盘口快照（此时簿已清空，仅成交信息）
        self.get_snapshot()
        return trades

    # ------------- Internal Continuous Matching -------------
    def _match_continuous(self, incoming: Order) -> List[Trade]:
        trades: List[Trade] = []
        if incoming.side is OrderSide.BUY:
            while incoming.is_active:
                best = self.order_book.best_ask()
                if not best or best.price > incoming.price:
                    break
                qty = min(incoming.remaining, best.remaining)
                px = best.price
                best.fill(qty, trade_price=px if best.side is OrderSide.BUY else None)
                incoming.fill(qty, trade_price=px if incoming.side is OrderSide.BUY else None)
                tr = Trade(symbol=self.symbol, price=px, quantity=qty,
                           buy_order_id=incoming.order_id, sell_order_id=best.order_id,
                           buy_account_id=incoming.account_id or "",
                           sell_account_id=best.account_id or "")
                trades.append(tr)
                if best.remaining <= 0:
                    self.order_book.remove_order(best)
        else:
            while incoming.is_active:
                best = self.order_book.best_bid()
                if not best or best.price < incoming.price:
                    break
                qty = min(incoming.remaining, best.remaining)
                px = best.price
                best.fill(qty, trade_price=px if best.side is OrderSide.BUY else None)
                incoming.fill(qty, trade_price=px if incoming.side is OrderSide.BUY else None)
                tr = Trade(symbol=self.symbol, price=px, quantity=qty,
                           buy_order_id=best.order_id, sell_order_id=incoming.order_id,
                           buy_account_id=best.account_id or "",
                           sell_account_id=incoming.account_id or "")
                trades.append(tr)
                if best.remaining <= 0:
                    self.order_book.remove_order(best)
        # 移除已完全成交的自身
        if incoming.is_filled:
            self.order_book.remove_order(incoming)
        # 快照成交更新
        if trades:
            snap = self.order_book.last_snapshot() or self._snapshot
            for tr in trades:
                snap.update_trade(tr.price, tr.quantity)
            self._snapshot = snap
        return trades

    def _purge_after_auction(self):
        """移除竞价阶段已被标记取消的订单，保持连续阶段干净。"""
        # 简化：重置 order_book 结构（只保留仍 active 的，实际这里全部取消/已成交）
        self.order_book._bids.clear()
        self.order_book._asks.clear()
        self.order_book._index = {oid: o for oid, o in self._orders.items() if o.is_active}