from app.controllers.market_controller import MarketController
from app.panels.market.panel import SymbolDetailPanel
from app.services.market_data_service import MarketDataService


class _RuntimeGateway:
    def __init__(self, *, sim_day: int = 0):
        self.sim_day = sim_day

    def get_bars(self, symbol: str, timeframe: str, *, limit: int):
        return []

    def get_current_sim_day(self) -> int:
        return self.sim_day

    def get_current_run_id(self) -> str | None:
        return "RUN-TEST-001"

    def get_recent_trades(self, symbol: str, *, limit: int = 20):
        return []


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


def test_runtime_trade_daily_bar_uses_internal_sim_day_bucket():
    gateway = _RuntimeGateway(sim_day=7)
    svc = MarketDataService(runtime_gateway=gateway)
    ctl = MarketController(svc)
    detail = SymbolDetailPanel(ctl, svc)

    detail.load_symbol("AAA", "1d")
    detail.add_trade(
        {
            "symbol": "AAA",
            "price": 12.34,
            "qty": 100,
            "side": "buy",
            "ts": 1_777_000_000_000,
        }
    )

    after = detail.get_view()
    assert after["series"] is not None
    assert after["series"]["ts"] == [7 * 24 * 60 * 60 * 1000]
    assert after["chart_meta"]["current_sim_day"] == 7


def test_runtime_bar_update_replaces_trade_cache_with_persisted_bar_event():
    gateway = _RuntimeGateway(sim_day=3)
    svc = MarketDataService(runtime_gateway=gateway)
    ctl = MarketController(svc)
    detail = SymbolDetailPanel(ctl, svc)

    detail.load_symbol("AAA", "1d")
    detail.add_bar_update(
        {
            "symbol": "AAA",
            "run_id": "RUN-TEST-001",
            "timeframe": "1d",
            "sim_day": 3,
            "bar": {
                "ts": "0001-01-04T00:00:00",
                "open": 10.0,
                "high": 12.0,
                "low": 9.5,
                "close": 11.0,
                "volume": 300.0,
            },
        }
    )

    after = detail.get_view()
    assert after["series"] is not None
    assert after["series"]["ts"] == [3 * 24 * 60 * 60 * 1000]
    assert after["series"]["open"] == [10.0]
    assert after["series"]["close"] == [11.0]
    assert after["series_meta"]["origin"] == "runtime-persisted-bars"
    assert after["series_meta"]["refresh"] == "bar-event-append"
