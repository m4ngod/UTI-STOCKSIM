from app.panels.market.panel import MarketPanel
from app.ui.adapters.market_adapter import MarketPanelAdapter
from app.services.market_data_service import MarketDataService


class _Ctl:
    def list_snapshots(self, page: int = 1, page_size: int = 100, symbol_filter=None, sort_by: str = 'symbol'):
        return {'items': [], 'total': 0, 'page': 1}

    def get_snapshot(self, symbol: str):
        return None


def test_market_adapter_no_manual_trade_buttons():
    logic = MarketPanel(_Ctl(), MarketDataService())
    adapter = MarketPanelAdapter().bind(logic)
    _ = adapter.widget()

    assert getattr(adapter, '_btn_buy', None) is None
    assert getattr(adapter, '_btn_sell', None) is None
