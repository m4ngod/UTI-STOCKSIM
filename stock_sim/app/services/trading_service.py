from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Any, Literal

from app.event_bridge import publish_order_submitted, publish_trade_payload
from app.runtime_gateway import RuntimeGateway
from infra.event_bus import event_bus

try:
    from observability.metrics import metrics
except Exception:  # pragma: no cover
    class _Dummy:
        def inc(self, *_, **__):
            pass
    metrics = _Dummy()


TradeSide = Literal["buy", "sell"]


@dataclass
class SubmitOrderRequest:
    symbol: str
    side: TradeSide
    price: float
    qty: int
    account_id: str


class TradingService:
    """Thin app-layer bridge that exposes runtime order placement to the frontend."""

    def __init__(self, *, runtime_gateway: RuntimeGateway | None = None):
        self._runtime_gateway = runtime_gateway or RuntimeGateway()

    def submit_order(self, req: SubmitOrderRequest) -> Dict[str, Any]:
        result = self._runtime_gateway.submit_order(
            symbol=req.symbol,
            side=req.side,
            price=req.price,
            qty=req.qty,
            account_id=req.account_id,
        )
        payload = {key: value for key, value in result.items() if key != "trades"}
        payload["ts"] = int(time.time() * 1000)

        try:
            publish_order_submitted(payload)
        except Exception:
            pass

        for trade in list(result.get("trades") or []):
            if not isinstance(trade, dict):
                continue
            publish_trade_payload({"trade": trade})
        metrics.inc("frontend_order_submit")
        return payload

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        result = self._runtime_gateway.cancel_order(order_id)
        payload = {
            "ok": bool(result.get("ok")),
            "order_id": str(result.get("order_id") or order_id),
            "ts": int(time.time() * 1000),
        }
        try:
            event_bus.publish("frontend.order.cancel_result", payload)
        except Exception:
            pass
        return payload


__all__ = ["TradingService", "SubmitOrderRequest"]
