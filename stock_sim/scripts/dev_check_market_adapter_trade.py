import time
from app.ui.adapters.market_adapter import MarketPanelAdapter
from app.panels.market.panel import MarketPanel
from app.services.market_data_service import MarketDataService
from infra.event_bus import event_bus
try:
    from app.event_bridge import FRONTEND_SNAPSHOT_BATCH_TOPIC
except Exception:
    FRONTEND_SNAPSHOT_BATCH_TOPIC = "frontend.snapshot.batch"

class _Ctl:
    def list_snapshots(self, page, page_size, symbol_filter, sort_by):
        return {"items": [], "total": 0, "page": 1}
    def get_snapshot(self, symbol):
        return None

svc = MarketDataService()
logic = MarketPanel(_Ctl(), svc)
adapter = MarketPanelAdapter().bind(logic)
_ = adapter.widget()
logic.add_symbol('T1')
adapter._handle_select('T1')
# Publish a Trade for T1
event_bus.publish('Trade', {'trade': {'symbol':'T1','price':1.23,'qty':5,'side':'buy','ts':1}})
# Allow handler to run
time.sleep(0.05)
dv = logic.detail_view()
print('TRADES', len(dv.get('trades') or []))
# Publish many batch events to exercise throttle
for i in range(10):
    event_bus.publish(FRONTEND_SNAPSHOT_BATCH_TOPIC, {'snapshots': [], 'count': 0})
    time.sleep(0.02)
print('DONE')

