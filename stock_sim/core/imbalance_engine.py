# python
# file: core/imbalance_engine.py
from __future__ import annotations
from typing import List
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.order import Order
from stock_sim.core.trade import Trade
from stock_sim.core.const import OrderSide, OrderStatus

class ImbalanceMatchingEngine(MatchingEngine):
    """
    基于订单簿失衡的价格推进撮合引擎：
      - 正常提交订单后先走父类撮合
      - 若无成交且存在买卖价差，并出现买量失衡（买多卖少或买少卖多）
        则自动把价格推进到可成交价位并撮合最优价位的订单
      - 仅撮合一档（best bid vs best ask），可按需要扩展多档循环
    """
    def submit_order(self, order: Order, skip_freeze: bool = False) -> List[Trade]:
        trades = super().submit_order(order, skip_freeze=skip_freeze)
        if trades:
            return trades
        # 无成交，尝试失衡撮合
        extra = self._rebalance_if_imbalanced()
        if extra:
            self.trades.extend(extra)
        return extra

    # ---------------- Internal Helpers ----------------
    def _rebalance_if_imbalanced(self) -> List[Trade]:
        ob = self.order_book
        best_bid = ob.best_bid()
        best_ask = ob.best_ask()
        if not best_bid or not best_ask:
            return []
        # 仍有价差才考虑（若已交叉则父类应已撮合）
        if best_bid.price >= best_ask.price:
            return []
        # 聚合顶部及全簿方向量
        total_bid = sum(o.remaining for o in ob.all_bids() if o.is_active)
        total_ask = sum(o.remaining for o in ob.all_asks() if o.is_active)
        if total_bid == 0 or total_ask == 0:
            return []
        # 判定失衡方向
        if total_bid > total_ask:
            # 买压：以 best_ask 价格撮合
            return self._cross_level(best_price=best_bid.price,
                                     opp_price=best_ask.price,
                                     take_side=OrderSide.BUY,
                                     trade_price=best_ask.price)
        elif total_ask > total_bid:
            # 卖压：以 best_bid 价格撮合
            return self._cross_level(best_price=best_bid.price,
                                     opp_price=best_ask.price,
                                     take_side=OrderSide.SELL,
                                     trade_price=best_bid.price)
        return []

    def _cross_level(self,
                     best_price: float,
                     opp_price: float,
                     take_side: OrderSide,
                     trade_price: float) -> List[Trade]:
        """
        只撮合单档（best bid vs best ask）：
          take_side: 压力方（其希望推进价格）
          trade_price: 生成的成交价（对买压=best_ask，对卖压=best_bid）
        """
        ob = self.order_book
        trades: List[Trade] = []
        # 获取价位队列（复制引用后迭代）
        bid_orders = [o for o in ob.all_bids() if o.price == best_price and o.is_active]
        ask_orders = [o for o in ob.all_asks() if o.price == opp_price and o.is_active]
        if not bid_orders or not ask_orders:
            return trades

        # 双向 FIFO（内部 all_bids/all_asks 已按价+时间顺序）
        bi = 0
        ai = 0
        while bi < len(bid_orders) and ai < len(ask_orders):
            buy = bid_orders[bi]
            sell = ask_orders[ai]
            if not (buy.is_active and sell.is_active):
                if not buy.is_active:
                    bi += 1
                if not sell.is_active:
                    ai += 1
                continue
            qty = min(buy.remaining, sell.remaining)
            if qty <= 0:
                break
            # 更新订单
            buy.fill(qty, trade_price)
            sell.fill(qty, trade_price)
            tr = Trade(
                symbol=buy.symbol,
                price=trade_price,
                quantity=qty,
                buy_order_id=buy.order_id,
                sell_order_id=sell.order_id,
                buy_account_id=buy.account_id or "",
                sell_account_id=sell.account_id or ""
            )
            trades.append(tr)
            # 移除已完成订单出簿
            if buy.is_filled or not buy.is_active:
                ob.remove_order(buy)
                bi += 1
            if sell.is_filled or not sell.is_active:
                ob.remove_order(sell)
                ai += 1

        # 给未完全成交仍活跃的订单调整状态（父类已有逻辑；这里补防）
        for o in bid_orders + ask_orders:
            if o.remaining == 0 and o.status != OrderStatus.FILLED:
                o.status = OrderStatus.FILLED
            elif 0 < o.filled < o.quantity and o.status != OrderStatus.PARTIAL:
                o.status = OrderStatus.PARTIAL
        return trades