from __future__ import annotations
"""OrdersPanelAdapter (R1, R2, R3, R4, R5)

- Binds to OrdersPanel logic (headless-safe, no heavy deps)
- Subscribes to Trade / OrderRejected / OrderCanceled using subscribe_topic (fallback to event_bus)
- Normalizes by delegating to logic.add_line(payload); throttles refresh (200ms)
- Publishes ui.notification on rejected/canceled (via NotificationCenter)
- Provides basic UI: symbol filter input, type toggle buttons, and a simple table view
- Headless stubs provided when PySide6 is unavailable
"""
from typing import Any, Dict, List, Optional, Iterable, Set
from .base_adapter import PanelAdapter
from infra.event_bus import event_bus

# Subscribe helper (fallback)
try:
    from app.event_bridge import subscribe_topic  # type: ignore
except Exception:  # pragma: no cover
    def subscribe_topic(topic, handler, *, async_mode=False):  # type: ignore
        event_bus.subscribe(topic, handler, async_mode=async_mode)
        return lambda: event_bus.unsubscribe(topic, handler)

# Notification center for ui.notification publishing
try:
    from app.panels.shared.notifications import notification_center  # type: ignore
except Exception:  # pragma: no cover
    class _NC:  # minimal fallback
        def publish_error(self, code: str, message: str, *, data: Optional[Dict] = None):
            event_bus.publish('ui.notification', {'level':'error','code':code,'message':message,'ts':0,'id':0,'mode':'toast'})
        def publish_warning(self, code: str, message: str, *, data: Optional[Dict] = None):
            event_bus.publish('ui.notification', {'level':'warning','code':code,'message':message,'ts':0,'id':0,'mode':'toast'})
    notification_center = _NC()  # type: ignore

# Throttle utility (fallback minimal)
try:
    from app.utils.throttle import Throttle  # type: ignore
except Exception:  # pragma: no cover
    class Throttle:  # type: ignore
        def __init__(self, *_a, **_k): self.fn = _k.get('fn')
        def submit(self, *a, **k):
            try:
                (self.fn or (lambda *_, **__: None))(*a, **k)
            except Exception:
                pass
        def flush_pending(self, *, force: bool = False):
            return False
        @property
        def has_pending(self): return False

# Qt (headless stubs when unavailable)
try:
    from PySide6.QtWidgets import (  # type: ignore
        QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QLabel
    )
except Exception:  # pragma: no cover
    QWidget = object  # type: ignore
    class QVBoxLayout:  # type: ignore
        def __init__(self, *_, **__): pass
        def addWidget(self, *_): pass
        def addLayout(self, *_): pass
    class QHBoxLayout:  # type: ignore
        def __init__(self, *_, **__): pass
        def addWidget(self, *_): pass
    class QLineEdit:  # type: ignore
        def __init__(self, text=""): self._text=text
        def text(self): return self._text
        def setText(self, t): self._text=t
        @property
        def textChanged(self):
            class _Sig:
                def connect(self, *_): pass
            return _Sig()
    class QPushButton:  # type: ignore
        def __init__(self, text=""): self._text=text; self._check=True
        def setCheckable(self, v): self._check=v
        def isChecked(self): return self._check
        def setChecked(self, v): self._check=v
        @property
        def clicked(self):
            class _Sig:
                def connect(self, *_): pass
            return _Sig()
    class QTableWidget:  # type: ignore
        def __init__(self, *_a, **_k): pass
        def setColumnCount(self, *_): pass
        def setHorizontalHeaderLabels(self, *_): pass
        def setRowCount(self, *_): pass
        def setItem(self, *_): pass
    class QTableWidgetItem:  # type: ignore
        def __init__(self, text=""): self._text=text
        def text(self): return self._text
    class QLabel:  # type: ignore
        def __init__(self, text=""): self._text=text
        def setText(self, t): self._text=t

_COLS = ["ts","type","order_id","symbol","side","price","qty","status","reason"]

class OrdersPanelAdapter(PanelAdapter):
    def __init__(self):
        super().__init__()
        self._root: Optional[Any] = None
        self._table: Optional[Any] = None
        self._lbl_count: Optional[Any] = None
        self._symbol_input: Optional[Any] = None
        self._type_btns: Dict[str, Any] = {}
        self._active_types: Optional[Set[str]] = None  # None=all
        self._cancel_subs: List[callable] = []
        self._items: List[Dict[str, Any]] = []  # cached
        # throttle refresh (~200ms)
        self._refresh_throttle = Throttle(200, self._do_refresh, metrics_prefix="orders_adapter_refresh")
        # subscribe immediately (headless friendly)
        self._setup_subscriptions()

    # -------- Test helpers --------
    def get_items(self) -> List[Dict[str, Any]]:
        return list(self._items)
    def set_symbol_filter(self, s: Optional[str]):
        if self._logic is None: return
        try:
            self._logic.set_symbol_filter(s)
        except Exception:
            pass
        self._refresh_throttle.submit()
    def set_type_filter(self, types: Optional[Iterable[str]]):
        if self._logic is None: return
        try:
            self._active_types = set(types) if types else None
            self._logic.set_type_filter(self._active_types)
        except Exception:
            pass
        self._refresh_throttle.submit()
    def set_account_filter(self, account_id: Optional[str]):
        """Filter orders by account_id and refresh UI."""
        if self._logic is None:
            return
        try:
            self._logic.set_account_filter(account_id)
        except Exception:
            pass
        self._refresh_throttle.submit()

    # -------- PanelAdapter overrides --------
    def _create_widget(self):
        root = QWidget()  # type: ignore
        try:
            v = QVBoxLayout(root)  # type: ignore
            # filters
            hb = QHBoxLayout()  # type: ignore
            hb.addWidget(QLabel("Symbol:"))  # type: ignore
            self._symbol_input = QLineEdit("")  # type: ignore
            try:
                def _on_text_changed(*_):
                    s = None
                    try: s = self._symbol_input.text()  # type: ignore[attr-defined]
                    except Exception: s = None
                    if self._logic is not None:
                        try: self._logic.set_symbol_filter(s)
                        except Exception: pass
                    self._refresh_throttle.submit()
                self._symbol_input.textChanged.connect(_on_text_changed)  # type: ignore[attr-defined]
            except Exception:
                pass
            hb.addWidget(self._symbol_input)  # type: ignore
            # type toggles
            for t in ("Trade","OrderRejected","OrderCanceled"):
                btn = QPushButton(t)  # type: ignore
                try:
                    btn.setCheckable(True)  # type: ignore[attr-defined]
                    btn.setChecked(True)
                    def _make(t_):
                        def _h():
                            act = {k for k, b in self._type_btns.items() if getattr(b, 'isChecked', lambda: True)()}
                            self._active_types = None if len(act) == 3 else act
                            if self._logic is not None:
                                try: self._logic.set_type_filter(self._active_types)
                                except Exception: pass
                            self._refresh_throttle.submit()
                        return _h
                    btn.clicked.connect(_make(t))  # type: ignore[attr-defined]
                except Exception:
                    pass
                self._type_btns[t] = btn
                hb.addWidget(btn)  # type: ignore
            v.addLayout(hb)  # type: ignore
            # table
            self._table = QTableWidget(0, len(_COLS))  # type: ignore
            try:
                self._table.setColumnCount(len(_COLS))  # type: ignore[attr-defined]
                self._table.setHorizontalHeaderLabels(_COLS)  # type: ignore[attr-defined]
            except Exception:
                pass
            v.addWidget(self._table)  # type: ignore
            self._lbl_count = QLabel("0 items")  # type: ignore
            v.addWidget(self._lbl_count)  # type: ignore
        except Exception:  # pragma: no cover
            pass
        self._root = root
        return root

    # Ensure UI-thread refresh when possible
    def refresh(self):  # type: ignore[override]
        def _do():
            try:
                PanelAdapter.refresh(self)
            except Exception:
                pass
        # try to schedule in Qt main thread
        try:
            from PySide6.QtCore import QTimer  # type: ignore
            QTimer.singleShot(0, _do)
        except Exception:
            _do()

    def _apply_view(self, view: Dict[str, Any]):
        items = view.get('items', []) if isinstance(view, dict) else []
        # cache and clamp defensively
        self._items = items[-1000:] if len(items) > 1000 else list(items)
        # update table UI (best-effort)
        tbl = self._table
        if tbl is not None:
            try:
                tbl.setRowCount(len(self._items))  # type: ignore[attr-defined]
                for r, it in enumerate(self._items):
                    for c, k in enumerate(_COLS):
                        val = it.get(k)
                        s = "" if val is None else str(val)
                        try:
                            tbl.setItem(r, c, QTableWidgetItem(s))  # type: ignore
                        except Exception:
                            pass
            except Exception:  # pragma: no cover
                pass
        if self._lbl_count is not None:
            try:
                self._lbl_count.setText(f"{len(self._items)} items")  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                pass

    # -------- Subscriptions --------
    def _setup_subscriptions(self):
        # Register and keep cancel functions
        try:
            self._cancel_subs.append(subscribe_topic("Trade", self._on_trade, async_mode=False))
        except Exception:
            pass
        try:
            self._cancel_subs.append(subscribe_topic("OrderRejected", self._on_rejected, async_mode=False))
        except Exception:
            pass
        try:
            self._cancel_subs.append(subscribe_topic("OrderCanceled", self._on_canceled, async_mode=False))
        except Exception:
            pass

    def __del__(self):  # cleanup
        try:
            for cancel in list(self._cancel_subs):
                try: cancel()
                except Exception: pass
            self._cancel_subs.clear()
        except Exception:
            pass

    # -------- Event handlers --------
    def _on_trade(self, _topic: str, payload: Dict[str, Any]):
        if self._logic is None:
            return
        try:
            add = getattr(self._logic, 'add_line', None)
            if callable(add):
                add(payload)
        except Exception:
            pass
        self._refresh_throttle.submit()

    def _on_rejected(self, _topic: str, payload: Dict[str, Any]):
        # Publish notification
        try:
            oid = None
            try:
                od = payload.get('order') or {}
                oid = od.get('order_id')
            except Exception:
                oid = None
            reason = payload.get('reason')
            msg = f"OrderRejected: {oid or '-'} reason={reason}"
            notification_center.publish_error('ORDER_REJECTED', msg)
        except Exception:
            pass
        # Push to logic and refresh
        self._on_trade(_topic, payload)  # same add_line path

    def _on_canceled(self, _topic: str, payload: Dict[str, Any]):
        # Publish notification
        try:
            oid = payload.get('order_id')
            reason = payload.get('reason')
            msg = f"OrderCanceled: {oid or '-'} reason={reason}"
            notification_center.publish_warning('ORDER_CANCELED', msg)
        except Exception:
            pass
        # Push to logic and refresh
        self._on_trade(_topic, payload)

    # -------- Internals --------
    def _do_refresh(self):
        try:
            PanelAdapter.refresh(self)
        except Exception:
            pass

__all__ = ["OrdersPanelAdapter"]
