from app.controllers.trading_controller import TradingController
from app.panels.market.trade_dialog import TradeOrderDialog


class _StubTradingService:
    def __init__(self):
        self.calls = []

    def submit_order(self, req):
        self.calls.append(req)
        return {
            "ok": True,
            "order_id": "ord-1",
            "symbol": req.symbol,
            "account_id": req.account_id,
            "side": req.side,
            "price": req.price,
            "qty": req.qty,
            "filled": 0,
            "status": "NEW",
            "trade_count": 0,
            "ts": 1,
        }

    def cancel_order(self, order_id: str):
        return {"ok": True, "order_id": order_id, "ts": 1}


def test_trade_order_dialog_validates_and_submits():
    svc = _StubTradingService()
    ctl = TradingController(svc)
    dlg = TradeOrderDialog(ctl)

    dlg.set_context(symbol="T1", side="buy", price=10.5, qty=100, account_id="ACC-1")
    view = dlg.get_view()
    assert view["is_valid"] is True
    assert view["errors"] == {}

    ok = dlg.submit()
    assert ok is True
    assert len(svc.calls) == 1
    req = svc.calls[0]
    assert req.symbol == "T1"
    assert req.side == "buy"
    assert req.price == 10.5
    assert req.qty == 100
    assert req.account_id == "ACC-1"


def test_trade_order_dialog_rejects_invalid_form():
    svc = _StubTradingService()
    ctl = TradingController(svc)
    dlg = TradeOrderDialog(ctl)

    dlg.set_context(symbol="", side="sell", price=0, qty=0, account_id="")
    view = dlg.get_view()
    assert view["is_valid"] is False
    assert set(view["errors"].keys()) == {"symbol", "account_id", "price", "qty"}

    ok = dlg.submit()
    assert ok is False
    assert dlg.get_view()["last_error"] == "FORM_INVALID"
    assert svc.calls == []
