from app.services.market_data_service import MarketDataService


class _StubRuntimeGateway:
    def get_bars(self, symbol: str, timeframe: str, *, limit: int):
        return []

    def get_current_sim_day(self) -> int:
        return 3

    def get_current_run_id(self) -> str | None:
        return "RUN-FRONTEND-001"


def test_market_data_service_exposes_active_run_in_chart_meta():
    svc = MarketDataService(runtime_gateway=_StubRuntimeGateway())

    detail = svc.request_detail("AAA", "1m", ensure_loaded=True, limit=5)
    chart_meta = detail["chart_meta"]

    assert chart_meta["current_sim_day"] == 3
    assert chart_meta["active_run_id"] == "RUN-FRONTEND-001"
    assert chart_meta["history_scope_requested"] == "active-run"
    assert chart_meta["history_scope_resolved"] == "synthetic-fallback"
    assert chart_meta["history_scope"] == "synthetic-fallback"


class _RuntimeBarsGateway:
    def get_bars(self, symbol: str, timeframe: str, *, limit: int):
        return [
            {
                "ts": 1_700_000_000_000,
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
                "volume": 100.0,
                "_history_scope": "unscoped",
                "run_id": "RUN-OLD-001",
            }
        ]

    def get_current_sim_day(self) -> int:
        return 3

    def get_current_run_id(self) -> str | None:
        return "RUN-FRONTEND-001"


def test_market_data_service_exposes_resolved_runtime_history_scope_from_runtime_rows():
    svc = MarketDataService(
        allow_synthetic_fallback=False,
        runtime_gateway=_RuntimeBarsGateway(),
    )

    detail = svc.request_detail("AAA", "1m", ensure_loaded=True, limit=5)
    chart_meta = detail["chart_meta"]

    assert detail["series_origin"] == "runtime-persisted-bars"
    assert detail["series_authoritative"] is True
    assert chart_meta["history_scope_requested"] == "active-run"
    assert chart_meta["history_scope_resolved"] == "unscoped"
    assert chart_meta["history_scope"] == "unscoped"
