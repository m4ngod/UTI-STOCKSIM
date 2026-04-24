from __future__ import annotations

from infra.event_bus import event_bus

from app.services.trading_service import SubmitOrderRequest, TradingService


class _FakeRuntimeGateway:
    def __init__(self):
        self.submit_calls = []
        self.cancel_calls = []

    def submit_order(self, **kwargs):
        self.submit_calls.append(kwargs)
        return {
            "ok": True,
            "order_id": "ord-1",
            "symbol": kwargs["symbol"],
            "account_id": kwargs["account_id"],
            "side": kwargs["side"],
            "price": kwargs["price"],
            "qty": kwargs["qty"],
            "filled": kwargs["qty"],
            "status": "FILLED",
            "trade_count": 1,
            "trades": [
                {
                    "symbol": kwargs["symbol"],
                    "price": kwargs["price"],
                    "qty": kwargs["qty"],
                    "side": kwargs["side"],
                    "ts": 1,
                }
            ],
        }

    def cancel_order(self, order_id):
        self.cancel_calls.append(order_id)
        return {"ok": True, "order_id": order_id}


def test_trading_service_uses_runtime_gateway_and_publishes_events():
    gateway = _FakeRuntimeGateway()
    seen = []

    def _rec(topic, payload):
        seen.append((topic, payload))

    event_bus.subscribe("frontend.order.submitted", _rec, async_mode=False)
    event_bus.subscribe("order.submitted", _rec, async_mode=False)
    event_bus.subscribe("Trade", _rec, async_mode=False)
    try:
        svc = TradingService(runtime_gateway=gateway)
        result = svc.submit_order(
            SubmitOrderRequest(
                symbol="AAA",
                side="buy",
                price=10.0,
                qty=100,
                account_id="acc-1",
            )
        )
    finally:
        try:
            event_bus.unsubscribe("frontend.order.submitted", _rec)
        except Exception:
            pass
        try:
            event_bus.unsubscribe("order.submitted", _rec)
        except Exception:
            pass
        try:
            event_bus.unsubscribe("Trade", _rec)
        except Exception:
            pass

    assert gateway.submit_calls == [
        {
            "symbol": "AAA",
            "side": "buy",
            "price": 10.0,
            "qty": 100,
            "account_id": "acc-1",
        }
    ]
    assert result["ok"] is True
    assert any(topic == "frontend.order.submitted" for topic, _ in seen)
    assert any(topic == "order.submitted" for topic, _ in seen)
    assert any(topic == "Trade" for topic, _ in seen)


def test_trading_service_cancel_uses_runtime_gateway():
    gateway = _FakeRuntimeGateway()
    svc = TradingService(runtime_gateway=gateway)

    result = svc.cancel_order("ord-x")

    assert gateway.cancel_calls == ["ord-x"]
    assert result["ok"] is True
    assert result["order_id"] == "ord-x"
