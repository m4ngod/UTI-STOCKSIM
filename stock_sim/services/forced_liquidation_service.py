# python
"""ForcedLiquidationService (platform-hardening Task7)

功能 (最小可用版本):
  - evaluate_accounts(session) 扫描所有账户计算维持保证金比率 = Equity / GrossExposure
    * Equity = cash + Σ(position.quantity * position.avg_price)
    * GrossExposure = Σ(|position.quantity| * position.avg_price)
  - 若 GrossExposure 为 0 则跳过 (无风险敞口)
  - 若 ratio < settings.MAINTENANCE_MARGIN_RATIO 且 settings.LIQUIDATION_ENABLED:
      * 针对持仓按绝对规模从大到小依次生成强平订单 (多头: SELL, 空头: BUY 回补)
      * 每个持仓下单数量 = ceil(|qty| * LIQUIDATION_ORDER_SLICE_RATIO)，至少 1
      * 每账户不超过 LIQUIDATION_MAX_ORDERS_PER_ACCOUNT
  - 价格选择策略：使用 position.avg_price 作为参考价；卖出多头直接挂 avg_price，买入回补使用 avg_price；后续可接入快照中价。
  - 生成的订单使用 GFD LIMIT (可扩展为 IOC/MARKET)。
  - 发布事件 EventType.LIQUIDATION_TRIGGERED (一次/账户)，包含账户指标与生成订单摘要。
  - 指标: metrics.inc("liquidation_accounts"), metrics.inc("liquidation_orders", n_orders)

扩展留白：
  - 与风险引擎集成可在 evaluate 后立即调用 OrderService.place_order。
  - 策略价格可改为市价或贴近盘口 (需访问 OrderBook)。
  - Equity 可考虑未实现盈亏 / 保证金占用模型。

用法示例:
  from services.forced_liquidation_service import liquidation_service
  orders = liquidation_service.evaluate_and_submit(session, order_service)

"""
from __future__ import annotations
from dataclasses import dataclass
from math import ceil
from typing import List, Tuple

try:
    from stock_sim.settings import settings  # type: ignore
    from stock_sim.persistence.models_account import Account  # type: ignore
    from stock_sim.persistence.models_position import Position  # type: ignore
    from stock_sim.persistence.models_imports import SessionLocal  # type: ignore
    from stock_sim.core.order import Order  # type: ignore
    from stock_sim.core.const import OrderSide, EventType  # type: ignore
    from stock_sim.infra.event_bus import event_bus  # type: ignore
    from stock_sim.observability.metrics import metrics  # type: ignore
except Exception:  # noqa
    from settings import settings  # type: ignore
    from persistence.models_account import Account  # type: ignore
    from persistence.models_position import Position  # type: ignore
    from persistence.models_imports import SessionLocal  # type: ignore
    from core.order import Order  # type: ignore
    from core.const import OrderSide, EventType  # type: ignore
    from infra.event_bus import event_bus  # type: ignore
    from observability.metrics import metrics  # type: ignore

@dataclass
class LiquidationOrderPlan:
    account_id: str
    symbol: str
    side: OrderSide
    qty: int
    price: float

class ForcedLiquidationService:
    def evaluate_accounts(self, session=None) -> Tuple[List[LiquidationOrderPlan], List[dict]]:
        if not settings.LIQUIDATION_ENABLED:
            return [], []
        own = False
        if session is None:
            session = SessionLocal(); own = True
        plans: List[LiquidationOrderPlan] = []
        account_events: List[dict] = []
        try:
            accounts = session.query(Account).all()
            for acc in accounts:
                positions = getattr(acc, 'positions', [])
                if not positions:
                    continue
                equity = acc.cash
                gross = 0.0
                # 计算权益与敞口
                for p in positions:
                    pv = (p.quantity * p.avg_price)
                    equity += pv
                    gross += abs(p.quantity) * p.avg_price
                if gross <= 0:
                    continue
                ratio = (equity / gross) if gross > 0 else 0.0
                if ratio >= settings.MAINTENANCE_MARGIN_RATIO:
                    continue
                # 需要强平
                # 选择按绝对持仓价值排序
                pos_sorted = sorted(positions, key=lambda x: abs(x.quantity) * x.avg_price, reverse=True)
                max_orders = settings.LIQUIDATION_MAX_ORDERS_PER_ACCOUNT
                created = 0
                order_summaries = []
                for p in pos_sorted:
                    if created >= max_orders:
                        break
                    if p.quantity == 0:
                        continue
                    side = OrderSide.SELL if p.quantity > 0 else OrderSide.BUY
                    slice_qty = ceil(abs(p.quantity) * settings.LIQUIDATION_ORDER_SLICE_RATIO)
                    if slice_qty <= 0:
                        slice_qty = 1
                    price = p.avg_price if p.avg_price and p.avg_price > 0 else 1.0
                    plan = LiquidationOrderPlan(acc.id, p.symbol, side, slice_qty, price)
                    plans.append(plan)
                    order_summaries.append({
                        "symbol": p.symbol,
                        "side": side.name,
                        "qty": slice_qty,
                        "ref_price": price,
                    })
                    created += 1
                if order_summaries:
                    account_events.append({
                        "account_id": acc.id,
                        "equity": equity,
                        "gross_exposure": gross,
                        "ratio": ratio,
                        "threshold": settings.MAINTENANCE_MARGIN_RATIO,
                        "orders": order_summaries,
                    })
            return plans, account_events
        finally:
            if own:
                session.close()

    def submit(self, order_service, plans: List[LiquidationOrderPlan]):
        """将强平计划转化为真实订单。返回下单成功数量。"""
        submitted = 0
        for pl in plans:
            try:
                o = Order(symbol=pl.symbol, side=pl.side, price=pl.price, quantity=pl.qty, account_id=pl.account_id)
                order_service.place_order(o)
                submitted += 1
            except Exception:
                metrics.inc("liquidation_submit_fail")
        if submitted:
            metrics.inc("liquidation_orders", submitted)
        return submitted

    def evaluate_and_submit(self, session, order_service):
        plans, events = self.evaluate_accounts(session)
        if events:
            metrics.inc("liquidation_accounts", len(events))
            for ev in events:
                try:
                    event_bus.publish(EventType.LIQUIDATION_TRIGGERED, ev)
                except Exception:
                    pass
        self.submit(order_service, plans)
        return plans

liquidation_service = ForcedLiquidationService()

__all__ = ["liquidation_service", "ForcedLiquidationService", "LiquidationOrderPlan"]

