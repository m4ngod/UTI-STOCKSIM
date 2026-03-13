import time
from typing import List, Dict

from infra.event_bus import event_bus
from app.panels.orders.panel import OrdersPanel
from app.ui.adapters.orders_adapter import OrdersPanelAdapter
from app.panels.market.panel import MarketPanel
from app.ui.adapters.market_adapter import MarketPanelAdapter
from app.services.market_data_service import MarketDataService


def test_orders_panel_adapter_headless_flow():
    # capture notifications
    notes: List[Dict] = []
    def _on_note(_topic: str, payload: Dict):
        notes.append(payload)
    event_bus.subscribe('ui.notification', _on_note, async_mode=False)

    # setup orders logic + adapter
    logic = OrdersPanel(capacity=10)
    adapter = OrdersPanelAdapter().bind(logic)
    _ = adapter.widget()  # init stubs if headless

    # publish events
    event_bus.publish('Trade', {'trade': {'symbol': 'AAA', 'price': 10.5, 'qty': 2, 'side': 'buy', 'ts': 1}})
    event_bus.publish('OrderRejected', {
        'order': {'order_id': 'O1', 'symbol': 'AAA', 'price': 10.5, 'qty': 1, 'side': 'buy', 'status': 'REJECTED'},
        'reason': 'risk',
    })
    event_bus.publish('OrderCanceled', {'order_id': 'O2', 'reason': 'user'})

    # ensure refresh applied (OrdersPanelAdapter uses throttle)
    adapter.refresh()
    time.sleep(0.05)

    items = adapter.get_items()
    assert len(items) >= 3
    kinds = {it.get('type') for it in items}
    assert {'Trade', 'OrderRejected', 'OrderCanceled'}.issubset(kinds)

    # filters: symbol
    adapter.set_symbol_filter('aa')  # lowercase should match 'AAA'
    adapter.refresh()
    time.sleep(0.02)
    items2 = adapter.get_items()
    assert items2 and all((it.get('symbol') or '').lower().find('aa') >= 0 for it in items2 if it.get('symbol'))

    # filters: type only Trade
    adapter.set_type_filter(['Trade'])
    adapter.refresh()
    time.sleep(0.02)
    items3 = adapter.get_items()
    assert items3 and all(it.get('type') == 'Trade' for it in items3)

    # notifications for rejected/canceled
    levels = [n.get('level') for n in notes]
    codes = [n.get('code') for n in notes]
    assert ('error' in levels and 'ORDER_REJECTED' in codes) or any(n.get('code') == 'ORDER_REJECTED' for n in notes)
    assert ('warning' in levels and 'ORDER_CANCELED' in codes) or any(n.get('code') == 'ORDER_CANCELED' for n in notes)


def test_market_adapter_trade_pass_through():
    # MarketPanel + Adapter
    class _Ctl:
        def list_snapshots(self, page: int = 1, page_size: int = 100, symbol_filter=None, sort_by: str = 'symbol'):
            return {'items': [], 'total': 0, 'page': 1}
        def get_snapshot(self, symbol: str):
            return None

    svc = MarketDataService()
    logic = MarketPanel(_Ctl(), svc)
    m_adapter = MarketPanelAdapter().bind(logic)
    _ = m_adapter.widget()

    # select symbol
    logic.add_symbol('T1')
    m_adapter._handle_select('T1')

    # publish trade for selected symbol
    event_bus.publish('Trade', {'trade': {'symbol': 'T1', 'price': 1.23, 'qty': 5, 'side': 'buy', 'ts': 1}})

    # wait until trade visible in detail_view (<=200ms throttle + small processing)
    deadline = time.perf_counter() + 0.5
    got = False
    while time.perf_counter() < deadline:
        dv = logic.detail_view()
        trades = dv.get('trades') or []
        if isinstance(trades, list) and len(trades) >= 1:
            got = True
            break
        time.sleep(0.02)
    assert got, "trade not passed through to MarketPanel.detail_view()"

