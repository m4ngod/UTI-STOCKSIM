from __future__ import annotations

from types import SimpleNamespace

import app.app_context as app_context
import app.panels as panels
import app.panels.market.panel as market_panel
import app.ui.adapters.market_adapter as market_adapter
import app.ui.ui_refresh as ui_refresh


class _FakeSymbolDetailPanel:
    def __init__(self, controller, service):
        self.controller = controller
        self.service = service
        self.loaded = None

    def load_symbol(self, symbol, timeframe):
        self.loaded = (symbol, timeframe)


class _FakeSymbolDetailAdapter:
    def __init__(self):
        self.logic = None
        self.refreshed = False

    def bind(self, logic):
        self.logic = logic
        return self

    def refresh(self):
        self.refreshed = True


def test_open_symbol_page_reuses_shared_market_context(monkeypatch):
    shared_controller = object()
    shared_service = object()
    shared_ctx = SimpleNamespace(
        market_controller=shared_controller,
        market_data_service=shared_service,
    )
    registered: dict[str, object] = {}

    monkeypatch.setattr(ui_refresh, "_main_window", None)
    monkeypatch.setattr(app_context, "get_app_context", lambda **_: shared_ctx)
    monkeypatch.setattr(panels, "list_panels", lambda: [])

    def _register_panel(name, factory, title=None, meta=None):
        registered["name"] = name
        registered["factory"] = factory
        registered["title"] = title
        registered["meta"] = meta

    monkeypatch.setattr(panels, "register_panel", _register_panel)
    monkeypatch.setattr(panels, "get_panel", lambda _name: registered["factory"]())
    monkeypatch.setattr(market_panel, "SymbolDetailPanel", _FakeSymbolDetailPanel)
    monkeypatch.setattr(market_adapter, "SymbolDetailPanelAdapter", _FakeSymbolDetailAdapter)

    result = ui_refresh.open_symbol_page("AAA", timeframe="1m")

    assert registered["name"] == "symbol:AAA"
    assert registered["title"] == "AAA Detail"
    assert isinstance(result, _FakeSymbolDetailAdapter)
    assert result.logic.controller is shared_controller
    assert result.logic.service is shared_service
    assert result.logic.loaded == ("AAA", "1m")
    assert result.refreshed is True
