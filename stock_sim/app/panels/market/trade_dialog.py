from __future__ import annotations

from threading import RLock
from typing import Any, Dict, Optional, Literal

from app.controllers.trading_controller import TradingController

TradeSide = Literal["buy", "sell"]

__all__ = ["TradeOrderDialog"]


class TradeOrderDialog:
    """Logic-only dialog/controller for submitting a frontend trade order.

    Minimal scope for phase-2 frontend closed loop:
    - bind to a selected symbol
    - validate account_id / price / qty / side
    - call TradingController.submit_order()
    - expose view for UI adapters / headless tests
    """

    def __init__(self, controller: TradingController):
        self._ctl = controller
        self._lock = RLock()
        self._symbol: str = ""
        self._account_id: str = ""
        self._side: TradeSide = "buy"
        self._price: Optional[float] = None
        self._qty: Optional[int] = None
        self._errors: Dict[str, str] = {}
        self._last_result: Optional[Dict[str, Any]] = None
        self._last_error: Optional[str] = None

    def set_context(self, *, symbol: Optional[str] = None, side: Optional[str] = None,
                    price: Optional[float | int | str] = None, qty: Optional[int | str] = None,
                    account_id: Optional[str] = None):
        with self._lock:
            if symbol is not None:
                self._symbol = str(symbol or "").strip().upper()
            if side is not None and str(side).lower() in {"buy", "sell"}:
                self._side = str(side).lower()  # type: ignore[assignment]
            if price is not None:
                try:
                    self._price = float(price)
                except Exception:
                    self._price = None
            if qty is not None:
                try:
                    self._qty = int(qty)
                except Exception:
                    self._qty = None
            if account_id is not None:
                self._account_id = str(account_id or "").strip()
            self._revalidate()

    def _revalidate(self):
        self._errors.clear()
        if not self._symbol:
            self._errors["symbol"] = "EMPTY_SYMBOL"
        if not self._account_id:
            self._errors["account_id"] = "EMPTY_ACCOUNT"
        if self._price is None or self._price <= 0:
            self._errors["price"] = "INVALID_PRICE"
        if self._qty is None or self._qty <= 0:
            self._errors["qty"] = "INVALID_QTY"

    def get_view(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "fields": {
                    "symbol": self._symbol,
                    "account_id": self._account_id,
                    "side": self._side,
                    "price": self._price,
                    "qty": self._qty,
                },
                "errors": dict(self._errors),
                "is_valid": not self._errors,
                "last_result": self._last_result,
                "last_error": self._last_error,
            }

    def submit(self) -> bool:
        with self._lock:
            self._revalidate()
            if self._errors:
                self._last_error = "FORM_INVALID"
                return False
            symbol = self._symbol
            account_id = self._account_id
            side = self._side
            price = float(self._price)
            qty = int(self._qty)
        try:
            result = self._ctl.submit_order(
                symbol=symbol,
                side=side,
                price=price,
                qty=qty,
                account_id=account_id,
            )
            with self._lock:
                self._last_result = result
                self._last_error = None
            return bool(result.get("ok"))
        except Exception as e:  # noqa: BLE001
            with self._lock:
                self._last_result = None
                self._last_error = str(e)
            return False
