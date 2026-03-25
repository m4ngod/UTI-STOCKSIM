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


class _ServiceWithHoldings(MarketDataService):
    def get_retail_holdings(self, symbol: str):
        return {
            "labels": ["retail", "agent"],
            "pct": [60, 40],
        }



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



def test_detail_overall_health_depends_on_core_blocks_not_auxiliary_holdings_only():
    svc = _ServiceWithHoldings()
    ctl = MarketController(svc)
    panel = MarketPanel(ctl, svc)

    ctl.merge_batch([_snapshot("AAA", 12.3)])
    panel.select_symbol("AAA", timeframe="1m")
    detail = panel.detail_view()

    assert detail["detail_health"]["series_status"] == "available"
    assert detail["detail_health"]["snapshot_status"] == "available"
    assert detail["detail_health"]["order_book_status"] == "available"
    assert detail["detail_health"]["overall"] == "ok"
    assert detail["detail_health"]["core_blocks"] == {
        "series": "available",
        "snapshot": "available",
        "order_book": "available",
    }
    assert "holdings" in detail["detail_health"]["auxiliary_blocks"]
