from __future__ import annotations

from typing import Dict, Any

from app.services.trading_service import TradingService, SubmitOrderRequest

__all__ = ["TradingController"]


class TradingController:
    def __init__(self, service: TradingService):
        self._service = service

    def submit_order(self, *, symbol: str, side: str, price: float, qty: int, account_id: str) -> Dict[str, Any]:
        req = SubmitOrderRequest(
            symbol=symbol,
            side=side.lower(),
            price=float(price),
            qty=int(qty),
            account_id=account_id,
        )
        return self._service.submit_order(req)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return self._service.cancel_order(order_id)
