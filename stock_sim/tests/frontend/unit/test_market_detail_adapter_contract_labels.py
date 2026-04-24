from app.ui.adapters.market_adapter import (
    _build_order_book_rows,
    _build_chart_empty_text,
    _build_detail_debug_label_text,
    _build_detail_snapshot_label_text,
    _build_symbol_label_text,
    _count_render_bars,
)


def test_detail_snapshot_label_text_uses_contract_status_and_age():
    text = _build_detail_snapshot_label_text(
        {
            "snapshot": {"last": 12.34},
            "snapshot_meta": {"status": "stale", "age_ms": 18000},
            "order_book_meta": {"status": "stale"},
            "series_meta": {"status": "available"},
            "detail_health": {
                "overall": "degraded",
                "snapshot_status": "stale",
                "order_book_status": "stale",
                "series_status": "available",
            },
        },
        bars_count=8,
    )

    assert "last=12.34" in text
    assert "bars=8" in text
    assert "state=degraded" in text
    assert "snap=stale" in text
    assert "book=stale" in text
    assert "series=available" in text
    assert "snap_age_ms=18000" in text


def test_detail_debug_label_text_tracks_contract_metadata_fields():
    text = _build_detail_debug_label_text(
        {
            "chart_meta": {
                "active_run_id": "RUN-001",
                "history_scope_requested": "active-run",
                "history_scope_resolved": "runtime-trade-cache",
            },
            "series_meta": {
                "source": "runtime-trade-cache",
                "placeholder": True,
            },
            "snapshot_meta": {"freshness_model": "snapshot-ts-age"},
            "order_book_meta": {"freshness_model": "inherit-snapshot-age"},
            "trades_meta": {"status": "available"},
            "indicators_meta": {"status": "pending"},
            "holdings_meta": {"status": "placeholder", "authoritative": False},
            "holdings": {"placeholder": True},
            "detail_health": {
                "trades_status": "available",
                "indicators_status": "pending",
                "holdings_status": "placeholder",
            },
        },
        chart_mode="fallback",
        symbol="AAA",
        bars_count=3,
    )

    assert "mode=fallback" in text
    assert "symbol=AAA" in text
    assert "bars=3" in text
    assert "trades=available" in text
    assert "indicators=pending" in text
    assert "holdings=placeholder/non-auth" in text
    assert "history=runtime-trade-cache" in text
    assert "requested=active-run" in text
    assert "source=runtime-trade-cache" in text
    assert "snap_model=snapshot-ts-age" in text
    assert "book_model=inherit-snapshot-age" in text
    assert "run=RUN-001" in text
    assert "holdings_ui=placeholder" in text
    assert "series_ui=placeholder" in text


def test_chart_empty_text_uses_series_contract_status():
    assert _build_chart_empty_text({"series_meta": {"status": "missing"}}) == "K: no runtime history"
    assert _build_chart_empty_text({"series_meta": {"status": "stale"}}) == "K: stale history"
    assert _build_chart_empty_text({"series_meta": {"status": "placeholder"}}) == "K: synthetic placeholder hidden"


def test_symbol_label_and_bar_count_helpers_are_contract_focused():
    assert _build_symbol_label_text("AAA") == "symbol: AAA"
    assert _build_symbol_label_text("") == "symbol: -"
    assert _count_render_bars({"close": [1, 2, 3]}) == 3
    assert _count_render_bars(None) == 0


def test_order_book_rows_are_flattened_for_table_rendering():
    rows = _build_order_book_rows(
        {
            "bids": [(12.2, 10), (12.1, 8)],
            "asks": [(12.4, 9)],
        },
        depth=5,
    )

    assert rows == [
        ("BID", "12.2", "10"),
        ("ASK", "12.4", "9"),
        ("BID", "12.1", "8"),
    ]
