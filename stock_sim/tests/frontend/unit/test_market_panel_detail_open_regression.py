from __future__ import annotations

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from app.ui.adapters.market_adapter import MarketPanelAdapter


class _FakeSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, cb):
        self._callbacks.append(cb)

    def emit(self, *args, **kwargs):
        for cb in list(self._callbacks):
            cb(*args, **kwargs)


class _FakeListWidget:
    def __init__(self):
        self.itemClicked = _FakeSignal()
        self.itemDoubleClicked = _FakeSignal()
        self.itemActivated = _FakeSignal()
        self.items = []

    def clear(self):
        self.items.clear()

    def addItem(self, text):
        self.items.append(text)

    def setCurrentRow(self, _row):
        pass


class _FakeItem:
    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text


class _FakeLogic:
    def __init__(self):
        self.selected = []

    def select_symbol(self, sym):
        self.selected.append(sym)

    def detail_view(self):
        return {
            'symbol': self.selected[-1] if self.selected else '-',
            'snapshot': {'last': 1.0},
            'series': {'ts': [], 'open': [], 'high': [], 'low': [], 'close': [], 'volume': []},
            'order_book': {'bids': [], 'asks': []},
            'trades': [],
            'holdings': None,
        }


def test_double_click_selects_and_opens_symbol_detail_page(monkeypatch):
    import app.ui.adapters.market_adapter as market_adapter

    open_symbol_calls = []
    open_panel_calls = []

    monkeypatch.setattr(market_adapter, 'open_symbol_page', lambda *args, **kwargs: open_symbol_calls.append((args, kwargs)) or object())
    monkeypatch.setattr(market_adapter, '_open_panel', lambda *args, **kwargs: open_panel_calls.append((args, kwargs)))
    monkeypatch.setattr(market_adapter, 'ui_runtime_enabled', lambda: False)
    monkeypatch.setattr(market_adapter, 'QListWidget', _FakeListWidget)

    adapter = MarketPanelAdapter()
    adapter._logic = _FakeLogic()
    adapter._create_widget()

    item = _FakeItem('AAA')
    adapter._symbol_list.itemDoubleClicked.emit(item)  # type: ignore[attr-defined]

    assert adapter._logic.selected == ['AAA']
    assert adapter._selected_symbol == 'AAA'
    assert open_symbol_calls == [(('AAA',), {'controller': None, 'service': None, 'timeframe': '1d'})]
    assert open_panel_calls == []
