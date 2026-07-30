from __future__ import annotations

from typing import Any


class ActionParser:
    """Parse minimal act.v1 actions for the bridge MVP."""

    supported_action_types = {"hold", "order", "target_position", "target_weight"}
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
        if action_type == "target_weight":
            return self._parse_target_weight(normalized)
        if action_type == "target_position":
            return self._parse_target_position(normalized)

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

    def _parse_target_weight(self, normalized: dict[str, Any]) -> dict[str, Any]:
        target = normalized["target"]
        payload = normalized["payload"]
        constraints = normalized["constraints"]
        account_id = target.get("account_id")
        symbols = list(target.get("symbols") or [])
        weights = payload.get("weights")
        if not account_id:
            raise ValueError("MISSING_ACCOUNT_ID")
        if not isinstance(weights, dict) or not weights:
            raise ValueError("INVALID_TARGET_WEIGHTS")
        if not symbols:
            symbols = list(weights.keys())
        parsed_weights: dict[str, float] = {}
        gross = 0.0
        for symbol, value in weights.items():
            sym = str(symbol).strip()
            if not sym:
                raise ValueError("INVALID_SYMBOL")
            weight = float(value)
            parsed_weights[sym] = weight
            gross += abs(weight)
        max_gross = float(constraints.get("max_gross_leverage", 1.0) or 1.0)
        if gross > max_gross and not bool(constraints.get("clip_to_limits", False)):
            raise ValueError("MAX_GROSS_LEVERAGE_EXCEEDED")
        if gross > max_gross and gross > 0:
            scale = max_gross / gross
            parsed_weights = {sym: weight * scale for sym, weight in parsed_weights.items()}
        normalized["target"] = {**target, "account_id": account_id, "symbols": symbols}
        normalized["payload"] = {
            **payload,
            "weights": parsed_weights,
            "cash_buffer_ratio": float(payload.get("cash_buffer_ratio", 0.0) or 0.0),
            "rebalance_mode": str(payload.get("rebalance_mode") or "market"),
        }
        normalized["constraints"] = {
            **constraints,
            "allow_short": bool(constraints.get("allow_short", False)),
            "max_gross_leverage": max_gross,
            "clip_to_limits": bool(constraints.get("clip_to_limits", False)),
        }
        return normalized

    def _parse_target_position(self, normalized: dict[str, Any]) -> dict[str, Any]:
        target = normalized["target"]
        payload = normalized["payload"]
        account_id = target.get("account_id")
        positions = payload.get("positions")
        if not account_id:
            raise ValueError("MISSING_ACCOUNT_ID")
        if positions is None and target.get("symbol") and payload.get("target_quantity") is not None:
            positions = {target["symbol"]: payload["target_quantity"]}
        if not isinstance(positions, dict) or not positions:
            raise ValueError("INVALID_TARGET_POSITIONS")
        parsed_positions: dict[str, int] = {}
        for symbol, value in positions.items():
            sym = str(symbol).strip()
            if not sym:
                raise ValueError("INVALID_SYMBOL")
            parsed_positions[sym] = int(value)
        normalized["payload"] = {**payload, "positions": parsed_positions}
        return normalized


__all__ = ["ActionParser"]
