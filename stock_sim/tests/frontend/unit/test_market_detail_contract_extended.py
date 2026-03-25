from __future__ import annotations

from app.controllers.market_controller import MarketController
from app.panels.market.panel import MarketPanel
from app.services.market_data_service import MarketDataService


class _StubControllerNoSnapshot:
    def list_snapshots(self, page: int, page_size: int, symbol_filter, sort_by: str):
        return {"items": [], "total": 0, "page": 1}

    def get_snapshot(self, symbol: str):
        return None


class _ServiceWithHoldings(MarketDataService):
    def get_retail_holdings(self, symbol: str):
        return {
            "labels": ["retail", "agent"],
            "pct": [60, 40],
        }


def test_detail_view_marks_holdings_placeholder_when_helper_missing():
    svc = MarketDataService()
    panel = MarketPanel(_StubControllerNoSnapshot(), svc)
    panel.select_symbol("AAA", timeframe="1m")

    detail = panel.detail_view()

    assert detail["holdings"]["placeholder"] is True
    assert detail["holdings_meta"]["status"] == "placeholder"
    assert detail["detail_health"]["holdings_status"] == "placeholder"
    assert detail["detail_health"]["overall"] == "degraded"
    assert detail["detail_health"]["auxiliary_blocks"]["holdings"] == "placeholder"



def test_detail_view_marks_holdings_available_when_helper_returns_data():
    svc = _ServiceWithHoldings()
    panel = MarketPanel(_StubControllerNoSnapshot(), svc)
    panel.select_symbol("AAA", timeframe="1m")

    detail = panel.detail_view()

    assert detail["holdings"]["labels"] == ["retail", "agent"]
    assert detail["holdings_meta"]["status"] == "available"
    assert detail["detail_health"]["holdings_status"] == "available"



def test_detail_view_marks_indicators_pending_or_available_consistently():
    svc = MarketDataService()
    ctl = MarketController(svc)
    panel = MarketPanel(ctl, svc)
    panel.select_symbol("AAA", timeframe="1m")

    detail = panel.detail_view()

    assert detail["indicators_meta"]["status"] in {"pending", "available", "missing"}
    assert detail["detail_health"]["indicators_status"] == detail["indicators_meta"]["status"]



def test_detail_view_marks_series_stale_as_degraded():
    svc = MarketDataService()
    panel = MarketPanel(_StubControllerNoSnapshot(), svc)
    panel.select_symbol("AAA", timeframe="1m")

    panel._detail._is_stale = True  # type: ignore[attr-defined]
    detail = panel.detail_view()

    assert detail["series_meta"]["status"] == "stale"
    assert detail["detail_health"]["series_status"] == "stale"
    assert detail["detail_health"]["overall"] == "degraded"
