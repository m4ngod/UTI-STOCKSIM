from app.services.market_data_service import MarketDataService


class _EmptyRuntimeGateway:
    def get_bars(self, symbol: str, timeframe: str, *, limit: int):
        return []

    def get_current_sim_day(self) -> int:
        return 0

    def get_current_run_id(self) -> str | None:
        return "RUN-DESKTOP-001"


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
