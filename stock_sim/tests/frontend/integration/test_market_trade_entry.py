from app.panels.market.panel import MarketPanel
from app.ui.adapters.market_adapter import MarketPanelAdapter
from app.services.market_data_service import MarketDataService


class _Ctl:
    def __init__(self):
        self.submits = []

    def list_snapshots(self, page: int = 1, page_size: int = 100, symbol_filter=None, sort_by: str = 'symbol'):
        return {'items': [], 'total': 0, 'page': 1}

    def get_snapshot(self, symbol: str):
        return None


def test_market_adapter_headless_trade_entry_uses_selected_symbol(monkeypatch):
    svc = MarketDataService()
    ctl = _Ctl()
    logic = MarketPanel(ctl, svc)
    adapter = MarketPanelAdapter().bind(logic)
    _ = adapter.widget()

    logic.add_symbol('T1')
    adapter._handle_select('T1')

    calls = []
    def _fake_submit_order(**kwargs):
        calls.append(kwargs)
        return {
            'ok': True,
            'order_id': 'ord-1',
            'symbol': kwargs['symbol'],
            'account_id': kwargs['account_id'],
            'side': kwargs['side'],
            'price': kwargs['price'],
            'qty': kwargs['qty'],
            'filled': 0,
            'status': 'NEW',
            'trade_count': 0,
            'ts': 1,
        }

    monkeypatch.setattr(adapter._trade_ctl, 'submit_order', _fake_submit_order)
    adapter._open_trade_dialog('buy')

    assert len(calls) == 1
    call = calls[0]
    assert call['symbol'] == 'T1'
    assert call['side'] == 'buy'
    assert call['qty'] == 100
