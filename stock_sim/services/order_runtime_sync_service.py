from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from stock_sim.core.const import OrderSide, OrderStatus
from stock_sim.core.order import Order
from stock_sim.core.order_book import OrderBook
from stock_sim.persistence.models_order import OrderORM


class OrderRuntimeSyncService:
    """Own runtime sync between ORM state, in-memory orders, and engine views."""

    def __init__(self, *, mem_orders: Mapping[str, Order]) -> None:
        self._mem_orders = mem_orders

    def locate_order_book(self, engine: Any) -> OrderBook | None:
        candidates = (
            "order_book",
            "book",
            "ob",
            "continuous_book",
            "continuous_order_book",
            "auction_book",
            "auction_order_book",
        )
        for attr in candidates:
            if hasattr(engine, attr):
                book = getattr(engine, attr)
                if isinstance(book, OrderBook):
                    return book
        try:
            for attr in dir(engine):
                if attr.startswith("_"):
                    continue
                try:
                    value = getattr(engine, attr)
                except Exception:
                    continue
                if isinstance(value, OrderBook):
                    return value
        except Exception:
            pass
        return None

    def sync_order_state(
        self,
        order_id: str,
        orm_order: OrderORM | None,
        engine: Any | None,
    ) -> None:
        if orm_order is None:
            return

        mem_order = self._mem_orders.get(order_id)
        if mem_order is not None:
            self._apply_runtime_state(mem_order, orm_order)

        if engine is not None and hasattr(engine, "get_order"):
            try:
                engine_order = engine.get_order(order_id)
            except Exception:
                engine_order = None
            if engine_order is not None and engine_order is not mem_order:
                self._apply_runtime_state(engine_order, orm_order)

        if engine is None:
            return

        order_book = self.locate_order_book(engine)
        if order_book is None:
            return
        for attr in ("orders", "_orders", "order_map"):
            order_map = getattr(order_book, attr, None)
            if not isinstance(order_map, dict) or order_id not in order_map:
                continue
            self._apply_runtime_state(order_map[order_id], orm_order)
            break

    def calc_required_frozen_fee(self) -> dict[str, float]:
        required: dict[str, float] = {}
        for order in self._mem_orders.values():
            if (
                order.side is not OrderSide.BUY
                or order.status not in (OrderStatus.NEW, OrderStatus.PARTIAL)
                or order.quantity <= 0
            ):
                continue
            estimated_fee = order._meta.get("est_fee", 0.0)
            if estimated_fee <= 0:
                continue
            remaining_ratio = order.remaining / order.quantity
            needed_fee = estimated_fee * remaining_ratio
            if needed_fee <= 0:
                continue
            required[order.account_id] = required.get(order.account_id, 0.0) + needed_fee
        return required

    def _apply_runtime_state(self, target: Any, orm_order: OrderORM) -> None:
        try:
            target.filled = orm_order.filled
            target.status = orm_order.status
            target.price = orm_order.price
        except Exception:
            pass


__all__ = ["OrderRuntimeSyncService"]
