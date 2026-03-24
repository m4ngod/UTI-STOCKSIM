from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, Literal

from infra.event_bus import event_bus

from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.instrument_service import InstrumentService
from stock_sim.services.order_service import OrderService
from stock_sim.services.account_service import AccountService as RuntimeAccountService
from stock_sim.services.engine_registry import engine_registry
from stock_sim.core.matching_engine import MatchingEngine
from stock_sim.core.instruments import create_instrument
from stock_sim.core.order import Order
from stock_sim.core.const import OrderSide, EventType

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
    """Thin app-layer bridge that exposes runtime order placement to the frontend.

    Goals:
    - Give app/panel/adapter layer a stable place to submit an order
    - Reuse the existing runtime matching/settlement path directly
    - Emit a lightweight frontend event after submission so UI can refresh/account for it
    """

    def __init__(self):
        models_init.init_models()

    def submit_order(self, req: SubmitOrderRequest) -> Dict[str, Any]:
        session = SessionLocal()
        try:
            symbol = (req.symbol or "").strip().upper()
            account_id = (req.account_id or "").strip()
            side_s = (req.side or "").strip().lower()
            if not symbol:
                raise ValueError("symbol 不能为空")
            if not account_id:
                raise ValueError("account_id 不能为空")
            if side_s not in {"buy", "sell"}:
                raise ValueError("side 必须是 buy/sell")
            if req.qty <= 0:
                raise ValueError("qty 必须 > 0")
            if req.price <= 0:
                raise ValueError("price 必须 > 0")

            inst_srv = InstrumentService(session)
            dto = inst_srv.get(symbol)
            if dto is None:
                reg = engine_registry.get(symbol)
                reg_inst = getattr(reg, 'instrument', None) if reg is not None else None
                if reg_inst is not None:
                    class _Dto:
                        pass
                    dto = _Dto()
                    dto.tick_size = float(getattr(reg_inst, 'tick_size', 0.01) or 0.01)
                    dto.lot_size = int(getattr(reg_inst, 'lot_size', 100) or 100)
                    dto.min_qty = int(getattr(reg_inst, 'min_qty', dto.lot_size) or dto.lot_size)
                    dto.initial_price = float(getattr(reg_inst, 'initial_price', req.price) or req.price)
                else:
                    raise ValueError(f"instrument not found: {symbol}")

            engine = engine_registry.get(symbol)
            if engine is None:
                engine = MatchingEngine(
                    symbol,
                    create_instrument(
                        symbol,
                        tick_size=dto.tick_size,
                        lot_size=dto.lot_size,
                        min_qty=dto.min_qty,
                        initial_price=dto.initial_price,
                    ),
                )
                engine_registry.register(symbol, engine, overwrite=True)

            runtime_accounts = RuntimeAccountService(session)
            runtime_accounts.get_or_create(account_id)

            order = Order(
                symbol=symbol,
                side=OrderSide.BUY if side_s == "buy" else OrderSide.SELL,
                price=float(req.price),
                quantity=int(req.qty),
                account_id=account_id,
            )
            osrv = OrderService(session, engine=engine, instrument_service=inst_srv)
            trades = osrv.place_order(order)
            session.commit()

            payload = {
                "ok": order.status.name != "REJECTED",
                "order_id": order.order_id,
                "symbol": symbol,
                "account_id": account_id,
                "side": side_s,
                "price": float(order.price),
                "qty": int(order.quantity),
                "filled": int(order.filled),
                "status": order.status.name,
                "trade_count": len(trades),
                "ts": int(time.time() * 1000),
            }

            try:
                event_bus.publish("frontend.order.submitted", payload)
            except Exception:
                pass
            metrics.inc("frontend_order_submit")
            return payload
        finally:
            session.close()

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        session = SessionLocal()
        try:
            models_init.init_models()
            osrv = OrderService(session)
            ok = bool(osrv.cancel(order_id))
            session.commit()
            payload = {"ok": ok, "order_id": order_id, "ts": int(time.time() * 1000)}
            try:
                event_bus.publish("frontend.order.cancel_result", payload)
            except Exception:
                pass
            return payload
        finally:
            session.close()


__all__ = ["TradingService", "SubmitOrderRequest"]
