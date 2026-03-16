# python
"""RL AccountAdapter

用于将真实 AccountService / OrderService 状态注入 RL 环境。
实现目标 (Req7 部分):
  - get_account_state(account_id, symbols) -> AccountState
  - rebalance_to_weights(...) 根据目标权重下单 (简化同步实现)
  - 捕获下单被拒绝 (风险/资金/卖空) 并返回 reject 摘要

最小侵入: 仅依赖 OrderService 公共 API; 不修改其内部。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple, Any
import math

try:  # 兼容不同 import 根
    from stock_sim.services.order_service import OrderService  # type: ignore
    from stock_sim.core.order import Order  # type: ignore
    from stock_sim.core.const import OrderSide, OrderType, TimeInForce  # type: ignore
    from stock_sim.settings import settings  # type: ignore
except Exception:  # noqa
    from services.order_service import OrderService  # type: ignore
    from core.order import Order  # type: ignore
    from core.const import OrderSide, OrderType, TimeInForce  # type: ignore
    from settings import settings  # type: ignore

@dataclass
class AccountState:
    cash: float
    positions: Dict[str, Dict[str, float]]  # symbol -> {qty, avg_price, borrowed_qty}
    equity: float

class AccountAdapter:
    def __init__(self, order_service: OrderService, account_id: str):
        self.order_service = order_service
        self.account_id = account_id
        # 确保账户存在
        self.order_service.accounts.get_or_create(account_id)

    # ---- 基础状态 ----
    def get_account_state(self, symbols: List[str]) -> AccountState:
        acc = self.order_service.accounts.get_or_create(self.account_id)
        pos_map: Dict[str, Dict[str, float]] = {}
        cash = float(getattr(acc, 'cash', 0.0))
        for p in getattr(acc, 'positions', []) or []:
            if p.symbol not in symbols:
                continue
            borrowed = float(getattr(p, 'borrowed_qty', 0.0) or 0.0)
            pos_map[p.symbol] = {
                'qty': float(p.quantity),
                'avg_price': float(p.avg_price or 0.0),
                'borrowed_qty': borrowed
            }
        # 未持仓 symbol 设为 0
        for s in symbols:
            if s not in pos_map:
                pos_map[s] = {'qty': 0.0, 'avg_price': 0.0, 'borrowed_qty': 0.0}
        # 估算 equity (忽略冻结/费用，权重环境中足够)
        prices = self._latest_prices(symbols)
        equity = cash + sum(pos_map[s]['qty'] * prices.get(s, 0.0) for s in symbols)
        return AccountState(cash=cash, positions=pos_map, equity=equity)

    # ---- 权重调仓 ----
    def rebalance_to_weights(self,
                             target_w: List[float] | Any,
                             symbols: List[str],
                             slip: float,
                             max_leverage: float,
                             short_allowed: List[bool] | None = None) -> Tuple[float, float, List[str]]:
        """根据目标权重粗略生成订单。(同步阻塞)
        返回: (total_cost, traded_notional, rejects)
        简化策略:
          1. 读取最新账户状态 & 价格
          2. 按 equity * target_w 计算目标价值, 与当前价值差 -> 需要调仓价值
          3. 将价值差转换为数量 (price * qty)
          4. 对每个 symbol 下单 (LIMIT, 轻微价格偏移=slip)
          5. 统计失败的 symbol -> rejects
        注意: 这里不做一次性最优拆分 / 费用估计; 仅作为集成 MVP。
        """
        state = self.get_account_state(symbols)
        prices = self._latest_prices(symbols)
        equity = max(1e-9, state.equity)
        # 杠杆限制 (目标 gross > max 则整体缩放)
        gross_target = sum(abs(w) for w in target_w) * equity
        max_gross = max_leverage * equity
        scale = 1.0
        if gross_target > max_gross and gross_target > 0:
            scale = max_gross / gross_target
        rejects: List[str] = []
        traded_value = 0.0
        total_cost = 0.0  # (预估: 包含手续费/滑点, 此处仅记滑点价值)
        for i, sym in enumerate(symbols):
            w = float(target_w[i]) * scale
            price = prices.get(sym)
            if price is None or price <= 0:
                continue
            cur_qty = state.positions[sym]['qty']
            cur_val = cur_qty * price
            tgt_val = w * equity
            delta_val = tgt_val - cur_val
            if abs(delta_val) < 1e-6:
                continue
            side = OrderSide.BUY if delta_val > 0 else OrderSide.SELL
            if side is OrderSide.SELL and not self._is_short_sell_ok(cur_qty, delta_val, short_allowed, i):
                # 若尝试扩大空头且禁止 卖空, 直接跳过; 记录 reject
                rejects.append(f"SHORT_DISABLED:{sym}")
                continue
            qty = int(abs(delta_val) / price)
            if qty <= 0:
                continue
            # 简单滑点偏移 (买抬价, 卖压价)
            px = price * (1 + slip if side is OrderSide.BUY else 1 - slip)
            # 下单
            order = Order(symbol=sym, side=side, price=px, quantity=qty,
                          account_id=self.account_id, order_type=OrderType.LIMIT, tif=TimeInForce.GFD)
            before_cash = state.cash
            trades = self.order_service.place_order(order)
            # 若被拒 | 无成交 (可能进入簿) 均不追踪真实细节，这里仅做一次调仓尝试
            if order.status.name == 'REJECTED':
                rejects.append(f"REJECT:{sym}")
                continue
            # 估算成交名义金额: 已成交数量 * price (忽略多次不同成交价)
            filled_notional = order.filled * price
            traded_value += abs(filled_notional)
            # 滑点/费用近似: notional * slip
            total_cost += abs(filled_notional) * slip
        return float(total_cost), float(traded_value), rejects

    # ---- 内部 ----
    def _latest_prices(self, symbols: List[str]) -> Dict[str, float]:
        prices: Dict[str, float] = {}
        # 尝试从匹配引擎获取 snapshot
        try:
            from stock_sim.services.engine_registry import engine_registry  # type: ignore
            for s in symbols:
                eng = engine_registry.get(s.upper())
                if not eng:  # 尝试创建 (惰性)
                    eng = engine_registry.get_or_create(s.upper())
                snap = getattr(eng, 'snapshot', None)
                last_px = None
                if snap:
                    last_px = getattr(snap, 'last_price', None)
                    if not last_px and getattr(snap, 'ask_levels', None):
                        try:
                            last_px = snap.ask_levels[0][0]
                        except Exception:
                            pass
                    if not last_px and getattr(snap, 'bid_levels', None):
                        try:
                            last_px = snap.bid_levels[0][0]
                        except Exception:
                            pass
                if last_px:
                    prices[s] = float(last_px)
        except Exception:  # noqa
            pass
        return prices

    def _is_short_sell_ok(self, cur_qty: float, delta_val: float, short_allowed: List[bool] | None, idx: int) -> bool:
        # delta_val <0 表示卖出; 若卖出后可能形成或扩大空头 -> 检查
        if settings.RISK_DISABLE_SHORT:
            return False
        if short_allowed is not None and idx < len(short_allowed) and not short_allowed[idx]:
            return False
        return True

__all__ = ["AccountAdapter", "AccountState"]
