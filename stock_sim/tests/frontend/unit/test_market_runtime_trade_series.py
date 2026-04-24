from app.controllers.market_controller import MarketController
from app.panels.market.panel import SymbolDetailPanel
from app.services.market_data_service import MarketDataService


def test_symbol_detail_trade_creates_runtime_series():
    svc = MarketDataService()
    ctl = MarketController(svc)
    detail = SymbolDetailPanel(ctl, svc)
    svc.register_symbol_meta("AAA", reference_price=12.0, price_step=0.01, limit_pct=0.10)

    detail.load_symbol("AAA", "1d")
    before = detail.get_view()
    assert before["series_meta"]["placeholder"] is True

    detail.add_trade(
        {
            "symbol": "AAA",
            "price": 12.34,
            "qty": 100,
            "side": "buy",
            "ts": 1234567890000,
        }
    )

    after = detail.get_view()
    assert after["series"] is not None
    assert len(after["series"]["close"]) == 1
    assert after["series"]["close"][0] == 12.34
    assert after["series_meta"]["placeholder"] is False
    assert after["series_meta"]["authoritative"] is True
    assert after["series_meta"]["origin"] == "runtime-trade-cache"
    assert after["chart_meta"]["reference_price"] == 12.0
    assert after["chart_meta"]["limit_down"] == 10.8
    assert after["chart_meta"]["limit_up"] == 13.2
    assert len(after["trades"]) == 1
    assert after["trades_meta"]["source"] == "runtime-trade-log+local-overlay"
