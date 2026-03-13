import time
from typing import List, Dict

from infra.event_bus import event_bus
from app.panels.orders.panel import OrdersPanel
from app.ui.adapters.orders_adapter import OrdersPanelAdapter

notes: List[Dict] = []

def _on_note(_t, p):
    notes.append(p)

# capture notifications
event_bus.subscribe('ui.notification', _on_note)

logic = OrdersPanel(capacity=5)
adapter = OrdersPanelAdapter().bind(logic)
_ = adapter.widget()

# Publish sample events
event_bus.publish('Trade', {'trade': {'symbol': 'AAA', 'price': 10.5, 'qty': 2, 'side': 'buy', 'ts': 1}})
event_bus.publish('OrderRejected', {
    'order': {'order_id': 'O1', 'symbol': 'AAA', 'price': 10.5, 'qty': 1, 'side': 'buy', 'status': 'REJECTED'},
    'reason': 'risk',
})
event_bus.publish('OrderCanceled', {'order_id': 'O2', 'reason': 'user'})

adapter.refresh()
time.sleep(0.05)
items = adapter.get_items()
print('items', len(items))
print('kinds', sorted({it.get('type') for it in items}))
print('notes', len(notes))

