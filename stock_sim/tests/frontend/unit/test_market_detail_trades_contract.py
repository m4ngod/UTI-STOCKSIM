from app.panels.market.panel import MarketPanel, SymbolDetailPanel
from app.services.market_data_service import MarketDataService


class _StubControllerNoSnapshot:
    def list_snapshots(self, page: int, page_size: int, symbol_filter, sort_by: str):
        return {"items": [], "total": 0, "page": 1}

    def get_snapshot(self, symbol: str):
        return None


class _ServiceWithRuntimeTrades(MarketDataService):
    def get_recent_trades(self, symbol: str, limit: int = 20):
        return [
            {
                "trade_id": "TR-001",
                "symbol": symbol,
                "price": 12.34,
                "qty": 100,
                "ts": 1234567890000,
            }
        ]


def test_detail_view_prefers_runtime_trade_log_contract():
    svc = _ServiceWithRuntimeTrades()
    panel = MarketPanel(_StubControllerNoSnapshot(), svc)
    panel.select_symbol("AAA", timeframe="1m")

    detail = panel.detail_view()

    assert len(detail["trades"]) == 1
    assert detail["trades"][0]["trade_id"] == "TR-001"
    assert detail["trades_meta"]["source"] == "runtime-trade-log"
    assert detail["trades_meta"]["authoritative"] is True
    assert detail["trades_meta"]["status"] == "available"


def test_detail_view_dedupes_local_overlay_against_runtime_trade_log():
    svc = _ServiceWithRuntimeTrades()
    detail = SymbolDetailPanel(_StubControllerNoSnapshot(), svc)
    detail.load_symbol("AAA", "1m")

    detail.add_trade(
        {
            "symbol": "AAA",
            "price": 12.34,
            "qty": 100,
            "side": "buy",
            "ts": 1234567890000,
        }
    )

    view = detail.get_view()

    assert len(view["trades"]) == 1
    assert view["trades_meta"]["source"] == "runtime-trade-log+local-overlay"
    assert view["trades_meta"]["authoritative"] is True
