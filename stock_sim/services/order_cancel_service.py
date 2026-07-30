from __future__ import annotations

from stock_sim.core.const import OrderStatus
from stock_sim.infra.event_bus import event_bus
from stock_sim.observability.struct_logger import logger
from stock_sim.persistence.models_order import OrderORM


class OrderCancelService:
    """Own cancellation lifecycle after the decision to cancel has been made."""

    def __init__(
        self,
        *,
        session,
        accounts,
        pretrade,
        mem_orders,
        engine_lookup,
        run_id_provider,
        persist_state,
        persist_event,
        mem_order_updater,
    ) -> None:
        self._session = session
        self._accounts = accounts
        self._pretrade = pretrade
        self._mem_orders = mem_orders
        self._engine_lookup = engine_lookup
        self._run_id_provider = run_id_provider
        self._persist_state = persist_state
        self._persist_event = persist_event
        self._mem_order_updater = mem_order_updater

    def cancel_user_order(self, order_id: str) -> bool:
        orm = self._session.get(OrderORM, order_id)
        if orm is None:
            return False
        engine = self._engine_lookup(orm.symbol)
        ok = engine.cancel_order(order_id)
        if not ok:
            return False
        self.cancel_persisted_order(
            orm,
            reason="USER",
            engine=engine,
        )
        return True

    def cancel_persisted_order(
        self,
        orm: OrderORM,
        *,
        reason: str,
        engine=None,
    ) -> None:
        acc = self._accounts.get_or_create(orm.account_id)
        mem = self._mem_orders.get(orm.id)
        remaining = orm.quantity - orm.filled
        self._pretrade.release_order_reservations(
            acc=acc,
            symbol=orm.symbol,
            side=orm.side,
            price=orm.price,
            remaining=remaining,
            total_quantity=orm.quantity,
            mem_order=mem,
        )
        orm.status = OrderStatus.CANCELED
        self._persist_event(orm.id, "CANCEL", reason)
        self._publish_canceled(order_id=orm.id, reason=reason, symbol=orm.symbol)
        self._mem_order_updater(orm.id, orm, engine)

    def cancel_runtime_order(self, order, acc, *, reason: str) -> None:
        self._pretrade.release_order_reservations(
            acc=acc,
            symbol=order.symbol,
            side=order.side,
            price=order.price,
            remaining=order.remaining,
            total_quantity=order.quantity,
            mem_order=order,
        )
        order.status = OrderStatus.CANCELED
        self._persist_state(order, "CANCEL", reason)
        self._publish_canceled(
            order_id=order.order_id,
            reason=reason,
            symbol=order.symbol,
        )

    def _publish_canceled(self, *, order_id: str, reason: str, symbol: str) -> None:
        event_bus.publish(
            "OrderCanceled",
            {
                "order_id": order_id,
                "reason": reason,
                "run_id": self._run_id_provider(),
                "symbol": symbol,
            },
        )
        logger.log("order_cancel", order_id=order_id, reason=reason)


__all__ = ["OrderCancelService"]
