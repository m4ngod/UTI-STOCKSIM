# python
from __future__ import annotations
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple
from threading import RLock
from .order import Order
from .const import OrderSide
from .snapshot import Snapshot

class OrderBook:
    """
    价/时间优先订单簿（同价位 FIFO）。
    新增：
      - 线程锁
      - snapshot 缓存
      - 自动复用上一快照以保持 last_price/成交累积
    """
    def __init__(self, symbol: Optional[str] = None):
        self.symbol = symbol
        self._bids: Dict[float, Deque[Order]] = {}
        self._asks: Dict[float, Deque[Order]] = {}
        self._index: Dict[str, Order] = {}
        self._lock = RLock()
        self._last_snapshot: Optional[Snapshot] = None

    # ---------------- ORDER MUTATIONS ----------------
    def add_order(self, order: Order):
        with self._lock:
            if self.symbol and order.symbol != self.symbol:
                raise ValueError("symbol mismatch")
            book = self._bids if order.side is OrderSide.BUY else self._asks
            dq = book.setdefault(order.price, deque())
            dq.append(order)
            self._index[order.order_id] = order

    def remove_order(self, order: Order):
        with self._lock:
            book = self._bids if order.side is OrderSide.BUY else self._asks
            dq = book.get(order.price)
            if not dq:
                return
            try:
                dq.remove(order)
            except ValueError:
                pass
            if not dq:
                del book[order.price]
            self._index.pop(order.order_id, None)

    def cancel(self, order_id: str) -> bool:
        with self._lock:
            o = self._index.get(order_id)
            if not o or not o.is_active:
                return False
            self.remove_order(o)
            o.cancel("user_cancel")
            return True

    def modify_price(self, order_id: str, new_price: float) -> bool:
        with self._lock:
            o = self._index.get(order_id)
            if not o or not o.is_active:
                return False
            self.remove_order(o)
            o.replace_price(new_price)
            self.add_order(o)
            return True

    # ---------------- QUERIES ----------------
    def get(self, order_id: str) -> Optional[Order]:
        with self._lock:
            return self._index.get(order_id)

    def best_bid(self) -> Optional[Order]:
        with self._lock:
            if not self._bids:
                return None
            px = max(self._bids)
            return self._bids[px][0]

    def best_ask(self) -> Optional[Order]:
        with self._lock:
            if not self._asks:
                return None
            px = min(self._asks)
            return self._asks[px][0]

    def all_bids(self) -> List[Order]:
        with self._lock:
            return [o for _, dq in sorted(self._bids.items(), reverse=True) for o in dq]

    def all_asks(self) -> List[Order]:
        with self._lock:
            return [o for _, dq in sorted(self._asks.items()) for o in dq]

    # ---------------- DEPTH / SNAPSHOT ----------------
    def get_depth(self, levels: int = 10) -> dict:
        bids, asks = self._aggregate(levels)
        return {"bids": bids, "asks": asks}

    def build_snapshot(self, levels: int = 10,
                       prev: Optional[Snapshot] = None) -> Snapshot:
        """
        复用上一快照（若 prev 未显式传入）以维持 last_price / volume / turnover 延续。
        """
        if prev is None:
            prev = self._last_snapshot
        bids, asks = self._aggregate(levels)
        snap = prev if (prev and prev.symbol == (self.symbol or "")) else Snapshot(symbol=self.symbol or "")
        snap.update_book(bids, asks, levels)
        snap.sanity_fill()
        self._last_snapshot = snap
        return snap

    def last_snapshot(self) -> Optional[Snapshot]:
        return self._last_snapshot

    # ---------------- INTERNAL ----------------
    def _aggregate(self, levels: int) -> Tuple[List[Tuple[float, int]], List[Tuple[float, int]]]:
        with self._lock:
            bid_rows: List[Tuple[float, int]] = []
            for px in sorted(self._bids.keys(), reverse=True):
                total = sum(o.remaining for o in self._bids[px] if o.is_active)
                if total > 0:
                    bid_rows.append((px, total))
                if len(bid_rows) >= levels:
                    break
            ask_rows: List[Tuple[float, int]] = []
            for px in sorted(self._asks.keys()):
                total = sum(o.remaining for o in self._asks[px] if o.is_active)
                if total > 0:
                    ask_rows.append((px, total))
                if len(ask_rows) >= levels:
                    break
            return bid_rows, ask_rows