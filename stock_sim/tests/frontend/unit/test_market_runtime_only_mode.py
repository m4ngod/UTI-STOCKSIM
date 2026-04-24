from app.services.market_data_service import MarketDataService


class _EmptyRuntimeGateway:
    def get_bars(self, symbol: str, timeframe: str, *, limit: int):
        return []

    def get_current_sim_day(self) -> int:
        return 0

    def get_current_run_id(self) -> str | None:
        return "RUN-DESKTOP-001"

    def get_recent_trades(self, symbol: str, *, limit: int = 20):
        return []


def test_market_data_service_runtime_only_mode_does_not_fallback_to_synthetic():
    svc = MarketDataService(
        allow_synthetic_fallback=False,
        runtime_gateway=_EmptyRuntimeGateway(),
    )

    detail = svc.request_detail("AAA", "1m", ensure_loaded=True, limit=10)

    assert detail["series"] is None
    assert detail["series_placeholder"] is False
    assert detail["series_origin"] == "runtime-empty"
    assert detail["chart_meta"]["active_run_id"] == "RUN-DESKTOP-001"
    assert detail["chart_meta"]["history_scope_requested"] == "active-run"
    assert detail["chart_meta"]["history_scope_resolved"] == "none"


class _TradeOnlyRuntimeGateway(_EmptyRuntimeGateway):
    def __init__(self):
        self.trade_limits = []

    def get_recent_trades(self, symbol: str, *, limit: int = 20):
        assert symbol == "AAA"
        self.trade_limits.append(limit)
        return [
            {"symbol": "AAA", "price": 10.3, "qty": 20, "ts": 1_700_000_070_000},
            {"symbol": "AAA", "price": 10.2, "qty": 30, "ts": 1_700_000_030_000},
            {"symbol": "AAA", "price": 10.0, "qty": 10, "ts": 1_700_000_010_000},
        ]


def test_market_data_service_runtime_only_builds_bars_from_trade_log_when_persisted_bars_missing():
    gateway = _TradeOnlyRuntimeGateway()
    svc = MarketDataService(
        allow_synthetic_fallback=False,
        runtime_gateway=gateway,
    )

    detail = svc.request_detail("AAA", "1m", ensure_loaded=True, limit=10)
    series = detail["series"]

    assert series is not None
    assert detail["series_origin"] == "runtime-trade-log-bars"
    assert detail["series_authoritative"] is True
    assert detail["chart_meta"]["history_scope_resolved"] == "runtime-trade-log"
    assert list(series.close) == [10.2, 10.3]
    assert list(series.volume) == [40.0, 20.0]
    assert gateway.trade_limits == [200]


def test_market_data_service_trade_log_bar_lookup_is_bounded():
    gateway = _TradeOnlyRuntimeGateway()
    svc = MarketDataService(
        allow_synthetic_fallback=False,
        runtime_gateway=gateway,
    )

    svc.request_detail("AAA", "1m", ensure_loaded=True, limit=500)

    assert gateway.trade_limits == [1000]
