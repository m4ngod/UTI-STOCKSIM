from app.controllers.market_controller import MarketController
from app.panels.market.panel import MarketPanel
from app.services.market_data_service import MarketDataService
from app.ui.adapters.market_adapter import FRONTEND_SNAPSHOT_BATCH_TOPIC, MarketPanelAdapter
from infra.event_bus import event_bus


def test_market_adapter_merges_frontend_snapshot_batch_into_controller():
    svc = MarketDataService()
    ctl = MarketController(svc)
    logic = MarketPanel(ctl, svc)
    adapter = MarketPanelAdapter().bind(logic)
    _ = adapter.widget()

    logic.add_symbol("AAA")
    adapter._handle_select("AAA")

    event_bus.publish(
        FRONTEND_SNAPSHOT_BATCH_TOPIC,
        {
            "snapshots": [
                {
                    "symbol": "AAA",
                    "last": 12.34,
                    "bid_levels": [(12.33, 100)],
                    "ask_levels": [(12.35, 120)],
                    "volume": 500,
                    "turnover": 6170.0,
                    "ts": 1234567890,
                    "snapshot_id": "snap-aaa-1",
                }
            ],
            "count": 1,
        },
    )

    detail = logic.detail_view()
    assert detail["snapshot"]["last"] == 12.34
    assert detail["snapshot"]["bid_levels"] == [(12.33, 100.0)]
    assert detail["snapshot"]["ask_levels"] == [(12.35, 120.0)]


class _PersistedInstrumentLogic:
    def __init__(self):
        self.loaded = 0

    def load_persisted_instruments(self):
        self.loaded += 1
        return ["OLD1"]

    def get_view(self):
        return {
            "watchlist": {
                "symbols": ["OLD1"],
                "snapshots": {"items": [{"symbol": "OLD1"}]},
            },
            "selected": None,
        }

    def detail_view(self):
        return {}


def test_market_adapter_refreshes_persisted_instruments_when_widget_is_created():
    logic = _PersistedInstrumentLogic()
    adapter = MarketPanelAdapter().bind(logic)

    _ = adapter.widget()

    assert logic.loaded >= 1
    assert getattr(adapter._symbol_list, "_items", []) == ["OLD1"]
