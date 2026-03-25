from __future__ import annotations

from typing import Any


class ActionParser:
    """Parse minimal act.v1 actions for the bridge MVP."""

    supported_action_types = {"hold", "order"}
    supported_sides = {"BUY", "SELL"}
    supported_order_types = {"LIMIT", "MARKET"}
    supported_tifs = {"GFD", "IOC", "FOK"}

    def parse(self, action: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(action, dict):
            raise ValueError("ACTION_NOT_DICT")
        if action.get("contract_version") != "act.v1":
            raise ValueError("UNSUPPORTED_ACTION_CONTRACT")

        action_type = action.get("action_type")
        if action_type not in self.supported_action_types:
            raise ValueError("UNSUPPORTED_ACTION_TYPE")

        target = action.get("target") or {}
        payload = action.get("payload") or {}
        constraints = action.get("constraints") or {}
        meta = action.get("meta") or {}

        normalized = {
            "contract_version": "act.v1",
            "action_type": action_type,
            "target": target,
            "payload": payload,
            "constraints": constraints,
            "meta": meta,
        }

        if action_type == "hold":
            return normalized

        side = payload.get("side")
        order_type = payload.get("order_type")
        tif = payload.get("tif", "GFD")
        quantity = payload.get("quantity")
        price = payload.get("price")

        if side not in self.supported_sides:
            raise ValueError("INVALID_SIDE")
        if order_type not in self.supported_order_types:
            raise ValueError("INVALID_ORDER_TYPE")
        if tif not in self.supported_tifs:
            raise ValueError("INVALID_TIF")
        if quantity is None or int(quantity) <= 0:
            raise ValueError("INVALID_QUANTITY")
        if order_type == "LIMIT" and (price is None or float(price) <= 0):
            raise ValueError("INVALID_LIMIT_PRICE")

        normalized["payload"] = {
            **payload,
            "side": side,
            "order_type": order_type,
            "tif": tif,
            "quantity": int(quantity),
            "price": None if price is None else float(price),
        }
        return normalized


__all__ = ["ActionParser"]
