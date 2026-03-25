from __future__ import annotations

from typing import Any

from stock_sim.core.const import OrderSide, OrderType, TimeInForce, OrderStatus
from stock_sim.core.order import Order
from stock_sim.rl.observation_builder import ObservationBuilder
from stock_sim.rl.action_parser import ActionParser


class ModelBridge:
    """Minimal in-process bridge for obs.v1 + act.v1 (hold/order only)."""

    def __init__(self, order_service):
        self.order_service = order_service
        self.observation_builder = ObservationBuilder(order_service)
        self.action_parser = ActionParser()

    def build_observation(self, *, account_id: str, symbol: str,
                          run_id: str | None = None, episode_id: str | None = None,
                          step_index: int | None = None) -> dict[str, Any]:
        return self.observation_builder.build(
            account_id=account_id,
            symbol=symbol,
            run_id=run_id,
            episode_id=episode_id,
            step_index=step_index,
        )

    def step(self, *, action: dict[str, Any]) -> dict[str, Any]:
        try:
            parsed = self.action_parser.parse(action)
        except Exception as exc:
            return {
                "accepted": False,
                "action_type": None,
                "reject_reason": str(exc),
                "trades": [],
                "order_id": None,
                "status": "REJECTED",
            }

        action_type = parsed["action_type"]
        if action_type == "hold":
            return {
                "accepted": True,
                "action_type": "hold",
                "reject_reason": None,
                "trades": [],
                "order_id": None,
                "status": "NOOP",
            }

        target = parsed["target"]
        payload = parsed["payload"]
        symbol = target.get("symbol")
        account_id = target.get("account_id")
        if not symbol or not account_id:
            return {
                "accepted": False,
                "action_type": "order",
                "reject_reason": "MISSING_TARGET",
                "trades": [],
                "order_id": None,
                "status": "REJECTED",
            }

        side = OrderSide[payload["side"]]
        order_type = OrderType[payload["order_type"]]
        tif = TimeInForce[payload["tif"]]
        order = Order(
            symbol=symbol,
            side=side,
            price=float(payload["price"] or 0.0),
            quantity=int(payload["quantity"]),
            account_id=account_id,
            order_type=order_type,
            tif=tif,
        )
        trades = self.order_service.place_order(order)
        return {
            "accepted": order.status != OrderStatus.REJECTED,
            "action_type": "order",
            "reject_reason": None if order.status != OrderStatus.REJECTED else "ORDER_REJECTED",
            "trades": [t.to_dict() for t in trades],
            "order_id": order.order_id,
            "status": order.status.name,
            "filled": int(order.filled),
            "remaining": int(order.remaining),
        }


__all__ = ["ModelBridge"]
