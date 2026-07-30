from app.controllers.market_controller import MarketController
from app.panels.market.dialog import CreateInstrumentDialog, suggest_next_symbol
from app.panels.market.panel import MarketPanel
from app.services.market_data_service import MarketDataService


class _CaptureController:
    def __init__(self):
        self.calls = []

    def create_instrument(self, **kwargs):
        self.calls.append(dict(kwargs))
        return dict(kwargs)


def test_suggest_next_symbol_uses_highest_numeric_code_plus_one():
    assert suggest_next_symbol(["001", "003", "ABC", "099"]) == "100"
    assert suggest_next_symbol([]) == "001"


def test_create_instrument_dialog_derives_market_cap_and_submits_readonly_field():
    controller = _CaptureController()
    dialog = CreateInstrumentDialog(controller)  # type: ignore[arg-type]

    dialog.set_fields(
        name="Alpha Labs",
        symbol="001",
        initial_price="12.5",
        float_shares="1000000",
    )
    view = dialog.get_view()

    assert view["is_valid"] is True
    assert view["derived"]["field"] == "market_cap"
    assert view["normalized"]["market_cap"] == 12_500_000.0

    assert dialog.submit() is True
    assert controller.calls
    call = controller.calls[0]
    assert call["name"] == "Alpha Labs"
    assert call["symbol"] == "001"
    assert call["initial_price"] == 12.5
    assert call["float_shares"] == 1_000_000
    assert call["market_cap"] is None
    assert call["total_shares"] == 1_000_000


def test_market_panel_get_view_stays_healthy_before_detail_is_loaded():
    service = MarketDataService()
    controller = MarketController(service)
    panel = MarketPanel(controller, service)

    panel.add_symbol("001")

    view = panel.get_view()

    assert view["watchlist"]["symbols"] == ["001"]
    assert view["selected"] is None
