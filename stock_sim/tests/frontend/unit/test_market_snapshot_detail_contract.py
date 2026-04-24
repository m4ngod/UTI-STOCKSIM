from __future__ import annotations

import time

from app.controllers.market_controller import MarketController
from app.services.market_data_service import MarketDataService


def test_market_controller_exposes_snapshot_and_order_book_detail_contract():
    svc = MarketDataService()
    ctl = MarketController(svc)
    now = int(time.time() * 1000)
    ctl.merge_batch(
        [
            {
                "symbol": "AAA",
                "last": 12.3,
                "bid_levels": [(12.2, 10)],
                "ask_levels": [(12.4, 8)],
                "volume": 100,
                "turnover": 1230.0,
                "ts": now,
                "snapshot_id": "snap-live-aaa",
            }
        ]
    )

    detail = ctl.get_detail_snapshot("AAA")

    assert detail["snapshot"]["symbol"] == "AAA"
    assert detail["snapshot_meta"]["source"] == "market-controller-merged-snapshot-cache"
    assert detail["snapshot_meta"]["authoritative"] is True
    assert detail["snapshot_meta"]["status"] == "available"
    assert detail["snapshot_meta"]["freshness_model"] == "snapshot-ts-age"
    assert detail["snapshot_meta"]["timestamp_ms"] == now
    assert detail["order_book"]["bids"] == [(12.2, 10.0)]
    assert detail["order_book"]["asks"] == [(12.4, 8.0)]
    assert detail["order_book_meta"]["source"] == "snapshot-derived-order-book-view"
    assert detail["order_book_meta"]["status"] == "available"
    assert detail["order_book_meta"]["freshness_model"] == "inherit-snapshot-age"
    assert detail["order_book_meta"]["derived_from"] == "snapshot"
