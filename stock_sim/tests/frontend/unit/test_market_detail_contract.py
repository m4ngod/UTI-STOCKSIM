from __future__ import annotations

import time

from app.controllers.market_controller import MarketController
from app.panels.market.panel import MarketPanel
from app.services.market_data_service import MarketDataService


class _StubControllerNoSnapshot:
    def list_snapshots(self, page: int, page_size: int, symbol_filter, sort_by: str):
        return {"items": [], "total": 0, "page": 1}

    def get_snapshot(self, symbol: str):
        return None


def _snapshot(symbol: str, last: float):
    now = int(time.time() * 1000)
    return {
        "symbol": symbol,
        "last": last,
        "bid_levels": [(last - 0.1, 10)],
        "ask_levels": [(last + 0.1, 10)],
        "volume": 1000,
        "turnover": last * 1000,
        "ts": now,
        "snapshot_id": f"snap-{symbol}-{now}",
    }


def test_detail_view_exposes_contract_metadata_and_placeholder_holdings():
    svc = MarketDataService()
    panel = MarketPanel(_StubControllerNoSnapshot(), svc)
    panel.select_symbol("AAA", timeframe="1m")

    detail = panel.detail_view()

    assert detail["symbol"] == "AAA"
    assert "series_meta" in detail
    assert "snapshot_meta" in detail
    assert "order_book_meta" in detail
    assert "trades_meta" in detail
    assert "indicators_meta" in detail
    assert "holdings_meta" in detail
    assert "detail_health" in detail

    assert detail["series_meta"]["source"] == "default-synthetic-fetcher"
    assert detail["series_meta"]["placeholder"] is True
    assert detail["snapshot_meta"]["source"] == "market-controller-merged-snapshot-cache"
    assert detail["snapshot_meta"]["freshness_model"] == "snapshot-ts-age"
    assert detail["order_book_meta"]["source"] == "snapshot-derived-order-book-view"
    assert detail["order_book_meta"]["freshness_model"] == "inherit-snapshot-age"
    assert detail["order_book_meta"]["derived_from"] == "snapshot"
    assert detail["trades_meta"]["source"] == "runtime-trade-log"
    assert detail["indicators_meta"]["source"] == "indicator-executor-from-series"

    for key in ("series_meta", "snapshot_meta", "order_book_meta", "trades_meta", "indicators_meta", "holdings_meta"):
        assert "source" in detail[key]
        assert "authoritative" in detail[key]
        assert "status" in detail[key]
        assert "refresh" in detail[key]

    assert detail["holdings_meta"]["authoritative"] is False
    assert detail["holdings_meta"]["status"] == "placeholder"
    assert detail["holdings"]["placeholder"] is True
    assert detail["holdings"]["labels"] == []
    assert detail["holdings"]["pct"] == []

    assert detail["detail_health"]["snapshot_status"] == "missing"
    assert detail["detail_health"]["order_book_status"] == "missing"
    assert detail["detail_health"]["holdings_status"] == "placeholder"
    assert detail["detail_health"]["overall"] == "degraded"


def test_detail_view_health_ok_when_series_and_snapshot_are_available():
    svc = MarketDataService()
    ctl = MarketController(svc)
    panel = MarketPanel(ctl, svc)

    ctl.merge_batch([_snapshot("AAA", 12.3)])
    panel.select_symbol("AAA", timeframe="1m")
    detail = panel.detail_view()

    assert detail["series"] is not None
    assert detail["snapshot"] is not None
    assert detail["order_book"] is not None
    assert detail["detail_health"]["series_status"] == "placeholder"
    assert detail["detail_health"]["snapshot_status"] == "available"
    assert detail["detail_health"]["order_book_status"] == "available"
    assert detail["detail_health"]["overall"] == "degraded"
    assert detail["snapshot_meta"]["status"] == "available"
    assert detail["order_book_meta"]["status"] == "available"
