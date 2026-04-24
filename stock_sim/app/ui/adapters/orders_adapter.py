from __future__ import annotations

"""OrdersPanelAdapter with real-UI and headless-safe modes."""

from typing import Any, Dict, Iterable, List, Optional, Set

from infra.event_bus import event_bus

from .base_adapter import PanelAdapter
from .runtime_mode import ui_runtime_enabled

try:
    from app.event_bridge import on_order_canceled, on_order_rejected, on_order_submitted, on_trade_executed, subscribe_topic  # type: ignore
except Exception:  # pragma: no cover
    def on_order_submitted(handler, *, async_mode=False):  # type: ignore
        event_bus.subscribe("frontend.order.submitted", handler, async_mode=async_mode)
        return lambda: event_bus.unsubscribe("frontend.order.submitted", handler)
    def on_trade_executed(handler, *, async_mode=False):  # type: ignore
        event_bus.subscribe("trade.executed", handler, async_mode=async_mode)
        return lambda: event_bus.unsubscribe("trade.executed", handler)
    def on_order_rejected(handler, *, async_mode=False):  # type: ignore
        event_bus.subscribe("OrderRejected", handler, async_mode=async_mode)
        return lambda: event_bus.unsubscribe("OrderRejected", handler)
    def on_order_canceled(handler, *, async_mode=False):  # type: ignore
        event_bus.subscribe("OrderCanceled", handler, async_mode=async_mode)
        return lambda: event_bus.unsubscribe("OrderCanceled", handler)
    def subscribe_topic(topic, handler, *, async_mode=False):  # type: ignore
        event_bus.subscribe(topic, handler, async_mode=async_mode)
        return lambda: event_bus.unsubscribe(topic, handler)


try:
    from app.panels.shared.notifications import notification_center  # type: ignore
except Exception:  # pragma: no cover
    class _NC:  # type: ignore
        def publish_error(self, code: str, message: str, *, data: Optional[Dict] = None):
            event_bus.publish(
                "ui.notification",
                {"level": "error", "code": code, "message": message, "ts": 0, "id": 0, "mode": "toast"},
            )

        def publish_warning(self, code: str, message: str, *, data: Optional[Dict] = None):
            event_bus.publish(
                "ui.notification",
                {"level": "warning", "code": code, "message": message, "ts": 0, "id": 0, "mode": "toast"},
            )

    notification_center = _NC()  # type: ignore


try:
    from app.utils.throttle import Throttle  # type: ignore
except Exception:  # pragma: no cover
    class Throttle:  # type: ignore
        def __init__(self, *_a, **_k):
            self.fn = _k.get("fn")

        def submit(self, *a, **k):
            try:
                (self.fn or (lambda *_, **__: None))(*a, **k)
            except Exception:
                pass

        def flush_pending(self, *, force: bool = False):
            return False

        @property
        def has_pending(self):
            return False


if ui_runtime_enabled():
    try:
        from PySide6.QtWidgets import (  # type: ignore
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QTableWidget,
            QTableWidgetItem,
            QVBoxLayout,
            QWidget,
        )
    except Exception:  # pragma: no cover
        ui_runtime = False
    else:
        ui_runtime = True
else:
    ui_runtime = False


if not ui_runtime:
    class _HeadlessRoot:
        pass


    class _HeadlessSig:
        def connect(self, *_):
            return None


    class QWidget:  # type: ignore
        def __init__(self, *_, **__):
            pass


    class QVBoxLayout:  # type: ignore
        def __init__(self, *_, **__):
            pass

        def addWidget(self, *_):
            return None

        def addLayout(self, *_):
            return None


    class QHBoxLayout:  # type: ignore
        def __init__(self, *_, **__):
            pass

        def addWidget(self, *_):
            return None


    class QLineEdit:  # type: ignore
        def __init__(self, text=""):
            self._text = text

        def text(self):
            return self._text

        def setText(self, t):
            self._text = t

        @property
        def textChanged(self):
            return _HeadlessSig()


    class QPushButton:  # type: ignore
        def __init__(self, text=""):
            self._text = text
            self._check = True

        def setCheckable(self, v):
            self._check = v

        def isChecked(self):
            return self._check

        def setChecked(self, v):
            self._check = v

        @property
        def clicked(self):
            return _HeadlessSig()


    class QTableWidget:  # type: ignore
        def __init__(self, *_a, **_k):
            self._rows = []
            self._col_count = 0

        def setColumnCount(self, n):
            self._col_count = n

        def setHorizontalHeaderLabels(self, *_):
            return None

        def setRowCount(self, n):
            while len(self._rows) < n:
                self._rows.append([None] * self._col_count)
            while len(self._rows) > n:
                self._rows.pop()

        def setItem(self, r, c, item):
            while len(self._rows) <= r:
                self._rows.append([None] * self._col_count)
            while len(self._rows[r]) < self._col_count:
                self._rows[r].append(None)
            self._rows[r][c] = item


    class QTableWidgetItem:  # type: ignore
        def __init__(self, text=""):
            self._text = text

        def text(self):
            return self._text


    class QLabel:  # type: ignore
        def __init__(self, text=""):
            self._text = text

        def setText(self, t):
            self._text = t


_COLS = ["ts", "type", "order_id", "symbol", "side", "price", "qty", "status", "reason"]
_FILTER_TYPES = ("OrderSubmitted", "Trade", "OrderRejected", "OrderCanceled")


class OrdersPanelAdapter(PanelAdapter):
    def __init__(self):
        super().__init__()
        self._root: Optional[Any] = None
        self._table: Optional[Any] = None
        self._lbl_count: Optional[Any] = None
        self._symbol_input: Optional[Any] = None
        self._type_btns: Dict[str, Any] = {}
        self._active_types: Optional[Set[str]] = None
        self._cancel_subs: List[callable] = []
        self._items: List[Dict[str, Any]] = []
        self._refresh_throttle = Throttle(200, self._do_refresh, metrics_prefix="orders_adapter_refresh")
        self._setup_subscriptions()

    def _post_to_ui(self, cb) -> bool:
        try:
            from PySide6.QtCore import QTimer  # type: ignore

            if getattr(self, "_root", None) is not None:
                try:
                    QTimer.singleShot(0, self._root, cb)  # type: ignore[arg-type]
                except Exception:
                    QTimer.singleShot(0, cb)
            else:
                QTimer.singleShot(0, cb)
            return True
        except Exception:
            return False

    def get_items(self) -> List[Dict[str, Any]]:
        try:
            if self._logic is not None:
                view = self._logic.get_view()
                self._apply_view(view)
        except Exception:
            pass
        return list(self._items)

    def set_symbol_filter(self, s: Optional[str]):
        if self._logic is None:
            return
        try:
            self._logic.set_symbol_filter(s)
        except Exception:
            pass
        self._refresh_throttle.submit()

    def set_type_filter(self, types: Optional[Iterable[str]]):
        if self._logic is None:
            return
        try:
            self._active_types = set(types) if types else None
            self._logic.set_type_filter(self._active_types)
        except Exception:
            pass
        self._refresh_throttle.submit()

    def set_account_filter(self, account_id: Optional[str]):
        if self._logic is None:
            return
        try:
            self._logic.set_account_filter(account_id)
        except Exception:
            pass
        self._refresh_throttle.submit()

    def _create_widget(self):
        root: Any = QWidget() if ui_runtime else _HeadlessRoot()
        try:
            v = QVBoxLayout(root)  # type: ignore[arg-type]
            hb = QHBoxLayout()
            hb.addWidget(QLabel("Symbol:"))  # type: ignore[arg-type]

            self._symbol_input = QLineEdit("")  # type: ignore[call-arg]

            def _on_text_changed(*_):
                value = None
                try:
                    value = self._symbol_input.text()  # type: ignore[attr-defined]
                except Exception:
                    value = None
                if self._logic is not None:
                    try:
                        self._logic.set_symbol_filter(value)
                    except Exception:
                        pass
                self._refresh_throttle.submit()

            try:
                self._symbol_input.textChanged.connect(_on_text_changed)  # type: ignore[attr-defined]
            except Exception:
                pass
            hb.addWidget(self._symbol_input)  # type: ignore[arg-type]

            for event_type in _FILTER_TYPES:
                btn = QPushButton(event_type)  # type: ignore[call-arg]
                try:
                    btn.setCheckable(True)  # type: ignore[attr-defined]
                    btn.setChecked(True)  # type: ignore[attr-defined]

                    def _make(_type: str):
                        def _handler():
                            active = {
                                name
                                for name, button in self._type_btns.items()
                                if getattr(button, "isChecked", lambda: True)()
                            }
                            self._active_types = None if len(active) == len(_FILTER_TYPES) else active
                            if self._logic is not None:
                                try:
                                    self._logic.set_type_filter(self._active_types)
                                except Exception:
                                    pass
                            self._refresh_throttle.submit()

                        return _handler

                    btn.clicked.connect(_make(event_type))  # type: ignore[attr-defined]
                except Exception:
                    pass
                self._type_btns[event_type] = btn
                hb.addWidget(btn)  # type: ignore[arg-type]

            v.addLayout(hb)  # type: ignore[arg-type]

            self._table = QTableWidget(0, len(_COLS))
            try:
                self._table.setColumnCount(len(_COLS))  # type: ignore[attr-defined]
                self._table.setHorizontalHeaderLabels(_COLS)  # type: ignore[attr-defined]
            except Exception:
                pass
            v.addWidget(self._table, 1)  # type: ignore[arg-type]

            self._lbl_count = QLabel("0 items")
            v.addWidget(self._lbl_count)  # type: ignore[arg-type]
        except Exception:
            pass
        self._root = root
        return root

    def refresh(self):  # type: ignore[override]
        def _do():
            try:
                PanelAdapter.refresh(self)
            except Exception:
                pass
        if not self._post_to_ui(_do):
            _do()

    def _apply_view(self, view: Dict[str, Any]):
        items = view.get("items", []) if isinstance(view, dict) else []
        self._items = items[-1000:] if len(items) > 1000 else list(items)

        tbl = self._table
        if tbl is not None:
            try:
                tbl.setRowCount(len(self._items))  # type: ignore[attr-defined]
                for row_idx, item in enumerate(self._items):
                    for col_idx, key in enumerate(_COLS):
                        value = item.get(key)
                        text = "" if value is None else str(value)
                        try:
                            tbl.setItem(row_idx, col_idx, QTableWidgetItem(text))  # type: ignore[arg-type]
                        except Exception:
                            pass
            except Exception:
                pass

        if self._lbl_count is not None:
            try:
                self._lbl_count.setText(f"{len(self._items)} items")  # type: ignore[attr-defined]
            except Exception:
                pass

    def _setup_subscriptions(self):
        try:
            self._cancel_subs.append(on_order_submitted(self._on_submitted, async_mode=False))
        except Exception:
            pass
        try:
            self._cancel_subs.append(on_trade_executed(self._on_trade, async_mode=False))
        except Exception:
            pass
        try:
            self._cancel_subs.append(on_order_rejected(self._on_rejected, async_mode=False))
        except Exception:
            pass
        try:
            self._cancel_subs.append(on_order_canceled(self._on_canceled, async_mode=False))
        except Exception:
            pass

    def __del__(self):
        try:
            for cancel in list(self._cancel_subs):
                try:
                    cancel()
                except Exception:
                    pass
            self._cancel_subs.clear()
        except Exception:
            pass

    def _on_trade(self, _topic: str, payload: Dict[str, Any]):
        if self._logic is None:
            return
        try:
            add = getattr(self._logic, "add_line", None)
            if callable(add):
                add(payload)
        except Exception:
            pass
        self._refresh_throttle.submit()

    def _on_submitted(self, _topic: str, payload: Dict[str, Any]):
        if self._logic is None:
            return
        try:
            add = getattr(self._logic, "add_line", None)
            if callable(add):
                add({
                    "ts": payload.get("ts"),
                    "type": "OrderSubmitted",
                    "order_id": payload.get("order_id"),
                    "symbol": payload.get("symbol"),
                    "side": payload.get("side"),
                    "price": payload.get("price"),
                    "qty": payload.get("qty"),
                    "status": payload.get("status"),
                    "reason": payload.get("reason"),
                    "account_id": payload.get("account_id"),
                })
        except Exception:
            pass
        self._refresh_throttle.submit()

    def _on_rejected(self, _topic: str, payload: Dict[str, Any]):
        try:
            order = payload.get("order") or {}
            order_id = order.get("order_id")
            reason = payload.get("reason")
            notification_center.publish_error("ORDER_REJECTED", f"OrderRejected: {order_id or '-'} reason={reason}")
        except Exception:
            pass
        self._on_trade(_topic, payload)

    def _on_canceled(self, _topic: str, payload: Dict[str, Any]):
        try:
            order_id = payload.get("order_id")
            reason = payload.get("reason")
            notification_center.publish_warning("ORDER_CANCELED", f"OrderCanceled: {order_id or '-'} reason={reason}")
        except Exception:
            pass
        self._on_trade(_topic, payload)

    def _do_refresh(self):
        try:
            self.refresh()
        except Exception:
            pass


__all__ = ["OrdersPanelAdapter"]
