from __future__ import annotations

from typing import Any

from stock_sim.core.const import OrderSide, OrderType, TimeInForce, OrderStatus
from stock_sim.core.order import Order
from stock_sim.rl.action_parser import ActionParser
from stock_sim.rl.observation_builder import ObservationBuilder


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

    def build_observation_many(self, *, account_id: str, symbols: list[str],
                               run_id: str | None = None, episode_id: str | None = None,
                               step_index: int | None = None) -> dict[str, Any]:
        return self.observation_builder.build_many(
            account_id=account_id,
            symbols=symbols,
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
        if action_type == "target_weight":
            return self._execute_target_weight(parsed)
        if action_type == "target_position":
            return {
                "accepted": False,
                "action_type": "target_position",
                "reject_reason": "TARGET_POSITION_NOT_IMPLEMENTED",
                "trades": [],
                "orders": [],
                "order_id": None,
                "status": "REJECTED",
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

    def _execute_target_weight(self, parsed: dict[str, Any]) -> dict[str, Any]:
        target = parsed["target"]
        payload = parsed["payload"]
        constraints = parsed["constraints"]
        account_id = target.get("account_id")
        symbols = list(target.get("symbols") or payload.get("weights", {}).keys())
        if not account_id or not symbols:
            return {
                "accepted": False,
                "action_type": "target_weight",
                "reject_reason": "MISSING_TARGET",
                "trades": [],
                "orders": [],
                "status": "REJECTED",
            }

        account = self.order_service.accounts.get_or_create(account_id)
        weights = payload.get("weights") or {}
        allow_short = bool(constraints.get("allow_short", False))
        cash_buffer = max(0.0, min(0.95, float(payload.get("cash_buffer_ratio", 0.0) or 0.0)))
        prices = {symbol: self._reference_price(symbol) for symbol in symbols}
        equity = float(getattr(account, "cash", 0.0) or 0.0)
        for symbol in symbols:
            pos = self.order_service.accounts.get_position(account, symbol)
            equity += int(getattr(pos, "quantity", 0) or 0) * prices.get(symbol, 0.0)
        tradable_equity = equity * (1.0 - cash_buffer)

        all_trades: list[dict[str, Any]] = []
        orders: list[dict[str, Any]] = []
        accepted = True
        for symbol in symbols:
            price = prices.get(symbol, 0.0)
            if price <= 0:
                continue
            desired_notional = tradable_equity * float(weights.get(symbol, 0.0))
            pos = self.order_service.accounts.get_position(account, symbol)
            current_qty = int(getattr(pos, "quantity", 0) or 0)
            current_notional = current_qty * price
            delta_notional = desired_notional - current_notional
            params = self.order_service._get_symbol_params(symbol)
            lot_size = int(getattr(params, "lot_size", 1) or 1)
            raw_qty = int(abs(delta_notional) / price)
            qty = (raw_qty // max(lot_size, 1)) * max(lot_size, 1)
            if qty <= 0:
                continue
            side_name = "BUY" if delta_notional > 0 else "SELL"
            if side_name == "SELL" and not allow_short:
                qty = min(qty, max(0, current_qty))
                qty = (qty // max(lot_size, 1)) * max(lot_size, 1)
                if qty <= 0:
                    continue
            order = Order(
                symbol=symbol,
                side=OrderSide[side_name],
                price=price,
                quantity=qty,
                account_id=account_id,
                order_type=OrderType.LIMIT,
                tif=TimeInForce.GFD,
            )
            trades = self.order_service.place_order(order)
            accepted = accepted and order.status != OrderStatus.REJECTED
            all_trades.extend(t.to_dict() for t in trades)
            orders.append({
                "order_id": order.order_id,
                "symbol": symbol,
                "side": side_name,
                "price": price,
                "quantity": qty,
                "status": order.status.name,
                "filled": int(order.filled),
                "remaining": int(order.remaining),
            })
        return {
            "accepted": accepted,
            "action_type": "target_weight",
            "reject_reason": None if accepted else "ORDER_REJECTED",
            "trades": all_trades,
            "orders": orders,
            "order_id": orders[0]["order_id"] if orders else None,
            "status": "EXECUTED" if orders else "NOOP",
        }

    def _reference_price(self, symbol: str) -> float:
        try:
            eng = self.order_service._get_engine(symbol)
            book = eng.get_book(symbol)
            snap = getattr(book, "snapshot", None)
            if snap is not None:
                for attr in ("last_price", "mid_price", "best_ask_price", "best_bid_price"):
                    value = getattr(snap, attr, None)
                    if value:
                        return float(value)
            instrument = getattr(eng, "instrument", None)
            return float(getattr(instrument, "initial_price", 0.0) or 0.0)
        except Exception:
            return 0.0


__all__ = ["ModelBridge"]
