from __future__ import annotations

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QTimer  # type: ignore
from PySide6.QtWidgets import QApplication, QDialog, QPushButton  # type: ignore

from app.ui.adapters.market_adapter import MarketPanelAdapter


class _FakeCreateInstrumentDialog:
    submit_calls = 0

    def __init__(self, controller):
        self.controller = controller
        self.fields = {}

    def set_fields(self, **kwargs):
        self.fields.update(kwargs)

    def get_view(self):
        return {
            'derived': {'field': None, 'value': None},
            'errors': {},
            'is_valid': True,
        }

    def submit(self):
        type(self).submit_calls += 1
        return True


class _FakeLogic:
    def __init__(self):
        self._ctl = object()
        self.added = []
        self.selected = []
        self.detail_calls = 0

    def add_symbol(self, sym):
        self.added.append(sym)

    def select_symbol(self, sym):
        self.selected.append(sym)

    def detail_view(self):
        self.detail_calls += 1
        return {
            'symbol': self.selected[-1] if self.selected else '-',
            'snapshot': {'last': 1.0},
            'series': {
                'ts': [1, 2],
                'open': [1.0, 1.1],
                'high': [1.2, 1.3],
                'low': [0.9, 1.0],
                'close': [1.1, 1.2],
                'volume': [10, 20],
            },
            'order_book': {'bids': [], 'asks': []},
            'trades': [],
            'holdings': None,
        }


def test_create_dialog_submit_only_once(monkeypatch):
    app = QApplication.instance() or QApplication([])
    _ = app

    import app.ui.adapters.market_adapter as market_adapter

    _FakeCreateInstrumentDialog.submit_calls = 0
    monkeypatch.setattr(market_adapter, 'CreateInstrumentDialog', _FakeCreateInstrumentDialog)

    adapter = MarketPanelAdapter()
    adapter._logic = _FakeLogic()
    adapter._create_widget()

    original_exec = QDialog.exec

    def _fake_exec(self):
        buttons = self.findChildren(QPushButton)
        create_buttons = [b for b in buttons if getattr(b, 'text', lambda: '')() == 'Create']
        assert create_buttons, 'Create button not found'
        create_buttons[0].click()
        return 1

    monkeypatch.setattr(QDialog, 'exec', _fake_exec)
    try:
        adapter._open_create_dialog()
        QTimer.singleShot(10, app.quit)
        app.exec()
    finally:
        monkeypatch.setattr(QDialog, 'exec', original_exec)

    assert _FakeCreateInstrumentDialog.submit_calls == 1
    assert len(adapter._logic.added) == 1
    assert len(adapter._logic.added[0]) == 3
    assert adapter._logic.added[0].isdigit()
    # 创建成功后仍不自动切详情，避免把创建链路和详情链路耦合
    assert adapter._logic.selected == []
    assert adapter._selected_symbol is None
