# python
# file: core/matching_engine.py
from __future__ import annotations
from typing import List, Optional
from threading import RLock
from stock_sim.core.order import Order
from stock_sim.core.trade import Trade
from stock_sim.core.snapshot import Snapshot
from stock_sim.core.const import (
    OrderSide, OrderType, OrderStatus, TimeInForce, Phase, EventType
)
from stock_sim.core.validators import validate_tick, normalize_price, validate_lot
from stock_sim.core.call_auction import CallAuction
from stock_sim.infra.event_bus import event_bus
from dataclasses import dataclass, field  # 新增
from types import SimpleNamespace  # 新增
from stock_sim.settings import settings  # 新增: 使用每标的节流阈值
# 自适应快照策略可选导入
try:
    from stock_sim.services.adaptive_snapshot_service import AdaptiveSnapshotPolicyManager
except Exception:  # noqa
    AdaptiveSnapshotPolicyManager = None  # 占位

import os  # 调试
TRACE_ME = os.environ.get('DEBUG_TRACE_ME') == '1'

class MatchingEngine:
    """
    只负责撮合（无资金冻结/风险/持久化），支持：
      - 集合竞价阶段 (Phase.CALL_AUCTION)
      - 连续竞价
      - 限价 / 市价
      - TIF: GFD/IOC/FOK
      - 市价多档吃单（直至数量满足 / 订阅的深度耗尽）
    增强: 支持可插拔 AdaptiveSnapshotPolicyManager 动态阈值。
    """
    @dataclass
    class BookState:
        symbol: str
        tick_size: float
        lot_size: int
        min_qty: int
        settlement_cycle: int
        instrument_meta: dict = field(default_factory=dict)  # 保存市值/股本/IPO 等信息
        bids: dict = field(default_factory=dict)
        asks: dict = field(default_factory=dict)
        index: dict = field(default_factory=dict)
        trades: list[Trade] = field(default_factory=list)
        phase: Phase = Phase.CALL_AUCTION
        call_auction: CallAuction | None = None
        snapshot: Snapshot | None = None
        has_continuous_started: bool = False
        ops_since_snapshot: int = 0  # 新增: 节流计数

    def __init__(self, symbol: str, instrument):
        # NOTE: self.symbol 仅作为当前实例默认标识，事件发布改用 self.snapshot.symbol 以便未来共享线程池使用多标的簿时可替换/扩展。
        self.symbol = symbol
        self.instrument = instrument
        # 新增多簿容器
        self._books: dict[str, MatchingEngine.BookState] = {}
        # 注册初始 symbol
        self.register_symbol(symbol, instrument)
        # 将默认 book 关键引用指向旧属性以保持兼容
        b = self._books[symbol]
        self.call_auction = b.call_auction
        self.snapshot = b.snapshot
        self.phase = b.phase
        self._lock = RLock()  # 补回锁
        # 自适应策略管理器（可选）
        self._adaptive_mgr: AdaptiveSnapshotPolicyManager | None = None

    def set_adaptive_snapshot_manager(self, mgr: 'AdaptiveSnapshotPolicyManager'):
        """注入自适应快照策略管理器。"""
        self._adaptive_mgr = mgr

    @property
    def symbols(self) -> list[str]:
        return list(self._books.keys())

    def get_trades(self, symbol: str) -> list[Trade]:
        b = self._books.get(symbol.upper())
        return list(b.trades) if b else []

    # 删除旧的 trades 属性引用 self._trades，保留向后兼容返回默认 symbol 交易
    @property
    def trades(self) -> List[Trade]:
        return self.get_trades(self.symbol)

    # ---- 多标的接口 ----
    def register_symbol(self, symbol: str, instrument) -> None:
        sym = symbol.upper()
        if sym in self._books:
            return
        # 提取必要参数 (实现 C: 引擎仅持有参数非完整 instrument)
        tick = getattr(instrument, 'tick_size', 0.01)
        lot = getattr(instrument, 'lot_size', 1)
        min_qty = getattr(instrument, 'min_qty', 1)
        settle = getattr(instrument, 'settlement_cycle', 0)
        meta = {}
        for k in ('market_cap','total_shares','free_float_shares','initial_price','pe','ipo_opened'):
            if hasattr(instrument, k):
                meta[k] = getattr(instrument, k)
        bs = MatchingEngine.BookState(
            symbol=sym,
            tick_size=tick,
            lot_size=lot,
            min_qty=min_qty,
            settlement_cycle=settle,
            instrument_meta=meta,
            call_auction=CallAuction(sym),
            snapshot=Snapshot(symbol=sym)
        )
        self._books[sym] = bs

    def ensure_symbol(self, symbol: str, instrument_factory=None):
        sym = symbol.upper()
        if sym not in self._books:
            if instrument_factory:
                inst = instrument_factory(sym)
            else:
                from stock_sim.core.instruments import create_instrument
                inst = create_instrument(sym)
            self.register_symbol(sym, inst)
        return self._books[sym]

    def get_book(self, symbol: str) -> 'MatchingEngine.BookState':
        return self._books[symbol.upper()]

    def get_instrument_view(self, symbol: str):
        b = self.get_book(symbol)
        # 返回一个只读视图供外部获取撮合所需参数
        return SimpleNamespace(tick_size=b.tick_size, lot_size=b.lot_size, min_qty=b.min_qty, settlement_cycle=b.settlement_cycle,
                                **b.instrument_meta)

    # ----------------------------- PUBLIC API -----------------------------
    # 重载 submit_order 走多簿
    def submit_order(self, order: Order, *, skip_freeze: bool = False) -> List[Trade]:
        with self._lock:
            sym = order.symbol.upper()
            if sym not in self._books:
                self.ensure_symbol(sym)
            book = self._books[sym]
            snapshot = book.snapshot
            if TRACE_ME:
                print(f"[TRACE ME.submit.in] sym={sym} phase={book.phase.name} side={order.side.name} type={order.order_type.name} qty={order.quantity} price={order.price}", flush=True)
            # 规范化
            if order.order_type is OrderType.LIMIT:
                if not validate_tick(order.price, book.tick_size):
                    order.price = normalize_price(order.price, book.tick_size)
            if not validate_lot(order.quantity, book.lot_size, book.min_qty):
                order.status = OrderStatus.REJECTED
                event_bus.publish(EventType.ORDER_REJECTED, {"order": order.to_dict(), "reason": "LOT_INVALID"})
                return []
            if book.phase is Phase.CALL_AUCTION and order.order_type is OrderType.MARKET:
                order.attach_meta(converted_from="MARKET")
                order.price = float("inf") if order.side is OrderSide.BUY else 0.0
            if book.phase is Phase.CONTINUOUS and order.order_type is OrderType.MARKET:
                order.price = float("inf") if order.side is OrderSide.BUY else 0.0
            if book.phase is Phase.CALL_AUCTION:
                if TRACE_ME:
                    ca_orders = len(getattr(book.call_auction, '_orders', [])) if book.call_auction else 0
                    print(f"[TRACE ME.call_auction.add] sym={sym} before_orders={ca_orders}", flush=True)
                book.call_auction.add(order)
                book.index[order.order_id] = order
                event_bus.publish(EventType.ORDER_ACCEPTED, {"order": order.to_dict(), "phase": "CALL_AUCTION"})
                # 外部 IPO 服务尝试自动开盘 (受设置开关控制)
                if getattr(settings, 'IPO_INTERNAL_AUTO_OPEN_ENABLED', False):
                    try:
                        from stock_sim.services.ipo_service import maybe_auto_open_ipo
                        before_phase = book.phase
                        opened = maybe_auto_open_ipo(self, book)
                        if TRACE_ME:
                            ca_orders2 = len(getattr(book.call_auction, '_orders', [])) if book.call_auction else 0
                            print(f"[TRACE ME.ipo_check] sym={sym} opened={opened} phase_before={before_phase.name} phase_after={book.phase.name} orders_now={ca_orders2} has_cont={book.has_continuous_started}", flush=True)
                    except Exception as e:
                        if TRACE_ME:
                            print(f"[TRACE ME.ipo_check.error] sym={sym} err={e}", flush=True)
                return []
            trades = self._match_continuous(order, book)
            if order.tif is TimeInForce.IOC and order.remaining > 0 and order.is_active:
                order.cancel("IOC_REMAINING_CANCEL")
            if order.tif is TimeInForce.FOK and order.remaining > 0 and order.filled == 0:
                order.cancel("FOK_UNFILLABLE")
            if order.is_active and order.remaining > 0 and order.order_type is OrderType.LIMIT:
                self._add_to_book(order, book)
            self._post_trade_events(trades, order)
            self._conditional_refresh_snapshot(book, force=bool(trades))
            return trades

    # 集合竞价结束并切换到连续竞价（可选指定标的，否则默认 self.symbol）
    def run_call_auction_and_open(self, symbol: str | None = None):
        with self._lock:
            sym = symbol.upper() if symbol else self.symbol.upper()
            if sym not in self._books:
                return
            book = self._books[sym]
            if book.phase is not Phase.CALL_AUCTION:
                return
            # 记录竞价前订单数量 (用于判断是否应产生初始快照)
            pre_orders = len(getattr(book.call_auction, '_orders', [])) if book.call_auction else 0
            price, trades = book.call_auction.run()
            effective_trades = trades if pre_orders > 0 else []  # 无订单则忽略合成成交
            for tr in effective_trades:
                book.snapshot.update_trade(tr.price, tr.quantity)
            for o in book.call_auction.remaining_orders():
                self._add_to_book(o, book)
            if price is not None and pre_orders > 0:
                book.snapshot.open_price = price
                book.snapshot.close_price = price
            book.phase = Phase.CONTINUOUS
            # 仍记录真实 trades 以便后续调试, 但不触发首次快照
            book.trades.extend(effective_trades)
            for tr in effective_trades:
                event_bus.publish(EventType.TRADE, {"trade": tr.to_dict(), "phase": "CALL_AUCTION"})
            if effective_trades and (effective_trades or getattr(settings, 'SNAPSHOT_INITIAL_ON_OPEN', False)):
                self._conditional_refresh_snapshot(book, force=True)
            book.has_continuous_started = True

    def cancel_order(self, order_id: str) -> bool:
        with self._lock:
            for book in self._books.values():
                o = book.index.get(order_id)
                if not o or not o.is_active:
                    continue
                o.cancel("USER")
                coll = book.bids if o.side is OrderSide.BUY else book.asks
                arr = coll.get(o.price)
                if arr and o in arr:
                    arr.remove(o)
                    if not arr: del coll[o.price]
                event_bus.publish(EventType.ORDER_CANCELED, {"order_id": order_id})
                self._conditional_refresh_snapshot(book, force=False)
                return True
            return False

    def modify_order_price(self, order_id: str, new_price: float) -> bool:
        with self._lock:
            for book in self._books.values():
                o = book.index.get(order_id)
                if not o or not o.is_active or o.order_type is OrderType.MARKET:
                    continue
                if not validate_tick(new_price, book.tick_size):
                    new_price = normalize_price(new_price, book.tick_size)
                coll = book.bids if o.side is OrderSide.BUY else book.asks
                arr = coll.get(o.price)
                if arr and o in arr:
                    arr.remove(o)
                    if not arr: del coll[o.price]
                o.replace_price(new_price)
                self._add_to_book(o, book)
                self._conditional_refresh_snapshot(book, force=False)
                return True
            return False

    # ---------------------------- CONTINUOUS MATCH -------------------------
    def _match_continuous(self, taker: Order, book: 'MatchingEngine.BookState') -> List[Trade]:
        trades: List[Trade] = []
        if taker.tif is TimeInForce.FOK and not self._can_fok_fulfill(taker, book):
            taker.cancel("FOK_UNFILLABLE")
            return trades
        while taker.remaining > 0:
            best = self._best_opposite(taker, book)
            if not best:
                break
            if not self._price_crossable(taker, best):
                break
            qty = min(taker.remaining, best.remaining)
            price = best.price
            taker.fill(qty)
            best.fill(qty)
            tr = self._record_trade(taker, best, price, qty)
            trades.append(tr)
            book.snapshot.update_trade(price, qty)
            if best.is_filled:
                self._remove_from_book(best, book)
        book.trades.extend(trades)
        return trades

    def _best_opposite(self, taker: Order, book: 'MatchingEngine.BookState') -> Optional[Order]:
        coll = book.asks if taker.side is OrderSide.BUY else book.bids
        if not coll: return None
        price = min(coll) if taker.side is OrderSide.BUY else max(coll)
        arr = coll[price]
        while arr and not arr[0].is_active:
            arr.pop(0)
        if not arr:
            del coll[price]
            return self._best_opposite(taker, book)
        return arr[0]

    def _price_crossable(self, taker: Order, maker: Order) -> bool:
        if taker.side is OrderSide.BUY:
            return maker.price <= taker.price
        return maker.price >= taker.price

    def _can_fok_fulfill(self, order: Order, book: 'MatchingEngine.BookState') -> bool:
        need = order.remaining; total = 0
        if order.side is OrderSide.BUY:
            for px in sorted(book.asks):
                if px > order.price: break
                total += sum(o.remaining for o in book.asks[px] if o.is_active)
                if total >= need: return True
            return False
        else:
            for px in sorted(book.bids, reverse=True):
                if px < order.price: break
                total += sum(o.remaining for o in book.bids[px] if o.is_active)
                if total >= need: return True
            return False

    # ---------------------------- BOOK OPS -------------------------
    def _add_to_book(self, order: Order, book: 'MatchingEngine.BookState'):
        coll = book.bids if order.side is OrderSide.BUY else book.asks
        arr = coll.setdefault(order.price, [])
        arr.append(order)
        book.index[order.order_id] = order

    def _remove_from_book(self, order: Order, book: 'MatchingEngine.BookState'):
        coll = book.bids if order.side is OrderSide.BUY else book.asks
        arr = coll.get(order.price)
        if not arr: return
        if order in arr: arr.remove(order)
        if not arr: del coll[order.price]

    # ---------------------------- UTIL -------------------------
    def _record_trade(self, taker: Order, maker: Order, price: float, qty: int) -> Trade:
        # 事件中 symbol 取订单 symbol，避免与 engine.self.symbol 强绑定
        sym = taker.symbol
        if taker.side is OrderSide.BUY:
            buy, sell = taker, maker
        else:
            buy, sell = maker, taker
        tr = Trade(
            symbol=sym,
            price=price,
            quantity=qty,
            buy_order_id=buy.order_id,
            sell_order_id=sell.order_id,
            buy_account_id=buy.account_id or "",
            sell_account_id=sell.account_id or "",
        )
        return tr

    def _post_trade_events(self, trades: List[Trade], taker: Order):
        for tr in trades:
            event_bus.publish(EventType.TRADE, {"trade": tr.to_dict()})
        if taker.status is OrderStatus.FILLED:
            event_bus.publish(EventType.ORDER_FILLED, {"order_id": taker.order_id})
        elif taker.status is OrderStatus.PARTIAL:
            event_bus.publish(EventType.ORDER_PARTIALLY_FILLED, {"order_id": taker.order_id})
        else:
            event_bus.publish(EventType.ORDER_ACCEPTED, {"order": taker.to_dict()})

    def _conditional_refresh_snapshot(self, book: 'MatchingEngine.BookState', *, force: bool):
        # 若启用自适应策略，记录一次操作并尝试调整阈值
        if self._adaptive_mgr is not None:
            try:
                self._adaptive_mgr.on_book_op(book.symbol)
                self._adaptive_mgr.maybe_adjust(book.symbol)
            except Exception:
                pass
        if force:
            self._refresh_snapshot_book(book)
            book.ops_since_snapshot = 0
            return
        book.ops_since_snapshot += 1
        # 动态阈值: 优先取自适应策略 -> 配置 -> 回退默认 5
        if self._adaptive_mgr is not None:
            try:
                threshold = self._adaptive_mgr.get_threshold(book.symbol)
            except Exception:
                threshold = getattr(settings, 'SNAPSHOT_THROTTLE_N_PER_SYMBOL', getattr(settings, 'SNAPSHOT_THROTTLE_N', 5))
        else:
            threshold = getattr(settings, 'SNAPSHOT_THROTTLE_N_PER_SYMBOL', getattr(settings, 'SNAPSHOT_THROTTLE_N', 5))
        if book.ops_since_snapshot >= threshold:
            self._refresh_snapshot_book(book)
            book.ops_since_snapshot = 0

    def _refresh_snapshot_book(self, book: 'MatchingEngine.BookState', levels: int = 5):
        bids = sorted(((px, sum(o.remaining for o in arr if o.is_active)) for px, arr in book.bids.items()), key=lambda x: x[0], reverse=True)
        asks = sorted(((px, sum(o.remaining for o in arr if o.is_active)) for px, arr in book.asks.items()), key=lambda x: x[0])
        book.snapshot.update_book(bids, asks, levels)
        bid1_px, bid1_qty = (book.snapshot.best_bid_price, book.snapshot.best_bid_qty)
        ask1_px, ask1_qty = (book.snapshot.best_ask_price, book.snapshot.best_ask_qty)
        event_bus.publish(EventType.SNAPSHOT_UPDATED, {
            'symbol': book.symbol,
            'snapshot': {
                'bids': book.snapshot.bid_levels,
                'asks': book.snapshot.ask_levels,
                'last': book.snapshot.last_price,
                'vol': book.snapshot.volume,
                'turnover': book.snapshot.turnover,
                'bid1': bid1_px,
                'ask1': ask1_px,
                'bid1_qty': bid1_qty,
                'ask1_qty': ask1_qty,
            }
        })

    def _auto_open_ipo_if_ready(self, book: 'MatchingEngine.BookState'):
        # 已迁移到 ipo_service.maybe_auto_open_ipo; 保留占位以兼容旧调用（不执行）
        return

    # 向后兼容属性访问 (phase/snapshot) 指向初始 symbol
    def __getattr__(self, item):
        if item in ('phase','snapshot','call_auction'):
            if self.symbol.upper() in self._books:
                b = self._books[self.symbol.upper()]
                if item == 'phase': return b.phase
                if item == 'snapshot': return b.snapshot
                if item == 'call_auction': return b.call_auction
        raise AttributeError(item)
