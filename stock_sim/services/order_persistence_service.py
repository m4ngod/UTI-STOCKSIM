from __future__ import annotations

from sqlalchemy.orm import Session

from stock_sim.core.order import Order
from stock_sim.persistence.models_order import OrderORM
from stock_sim.persistence.models_order_event import OrderEvent


class OrderPersistenceService:
    """Persistence collaborator for order/order-event writes."""

    def __init__(self, session: Session):
        self.s = session

    def create_order_record(self, order: Order, *, sim_day: int, sim_dt, run_id: str | None) -> OrderORM:
        orm = OrderORM(
            id=order.order_id,
            account_id=order.account_id,
            symbol=order.symbol,
            side=order.side,
            type=order.order_type,
            tif=order.tif,
            price=order.price,
            orig_price=getattr(order, "_orig_price", order.price),
            quantity=order.quantity,
            filled=order.filled,
            status=order.status,
            sim_day=sim_day,
            sim_dt=sim_dt,
            run_id=run_id,
        )
        self.s.add(orm)
        return orm

    def get_order_record(self, order_id: str) -> OrderORM | None:
        return self.s.get(OrderORM, order_id)

    def update_order_state(self, order: Order, *, sim_day: int, sim_dt) -> OrderORM | None:
        orm = self.s.get(OrderORM, order.order_id)
        if orm is None:
            return None
        orm.price = order.price
        orm.filled = order.filled
        orm.status = order.status
        if not getattr(orm, "sim_day", None):
            orm.sim_day = sim_day
            orm.sim_dt = sim_dt
        return orm

    def create_order_event(self, *, order_id: str, event: str, detail: str, run_id: str | None) -> OrderEvent:
        row = OrderEvent(order_id=order_id, event=event, detail=detail, run_id=run_id)
        self.s.add(row)
        return row
