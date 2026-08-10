"""AccountPanelAdapter with real-UI and headless-safe modes."""
from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional

from infra.event_bus import event_bus

from .base_adapter import PanelAdapter
from .runtime_mode import ui_runtime_enabled

try:
    from app.event_bridge import on_account_created, on_account_updated, subscribe_topic  # type: ignore
except Exception:  # pragma: no cover
    def on_account_created(handler, *, async_mode=False):  # type: ignore
        return subscribe_topic("account.created", handler, async_mode=async_mode)

    def on_account_updated(handler, *, async_mode=False):  # type: ignore
        return subscribe_topic("AccountUpdated", handler, async_mode=async_mode)

    def subscribe_topic(topic, handler, *, async_mode=False):  # type: ignore
        event_bus.subscribe(topic, handler, async_mode=async_mode)
        return lambda: event_bus.unsubscribe(topic, handler)


class _RuntimeUiTypes(NamedTuple):
    timer: Any
    combo_box: Any
    horizontal_layout: Any
    label: Any
    table: Any
    table_item: Any
    vertical_layout: Any
    widget: Any


def _load_runtime_ui_types() -> Optional[_RuntimeUiTypes]:
    """Load Qt widget classes for the current application lifecycle."""

    if not ui_runtime_enabled():
        return None
    try:
        from PySide6.QtCore import QTimer  # type: ignore
        from PySide6.QtWidgets import (  # type: ignore
            QComboBox,
            QHBoxLayout,
            QLabel,
            QTableWidget,
            QTableWidgetItem,
            QVBoxLayout,
            QWidget,
        )
    except Exception:  # pragma: no cover
        return None
    return _RuntimeUiTypes(
        timer=QTimer,
        combo_box=QComboBox,
        horizontal_layout=QHBoxLayout,
        label=QLabel,
        table=QTableWidget,
        table_item=QTableWidgetItem,
        vertical_layout=QVBoxLayout,
        widget=QWidget,
    )


class _HeadlessLabel:
    def __init__(self, text: str = ""):
        self._text = text

    def setText(self, text: str):
        self._text = text

    def text(self) -> str:
        return self._text


class _HeadlessTableWidgetItem:
    def __init__(self, text: str = ""):
        self._text = text

    def setText(self, text: str):
        self._text = text

    def text(self) -> str:
        return self._text


class _HeadlessTableWidget:
    def __init__(self, *_args, **_kwargs):
        self._rows: list[list[_HeadlessTableWidgetItem | None]] = []
        self._cols = 0

    def setColumnCount(self, count: int):
        self._cols = count

    def setHorizontalHeaderLabels(self, _labels):
        return None

    def rowCount(self):
        return len(self._rows)

    def insertRow(self, row: int):
        self._rows.insert(row, [None] * self._cols)

    def removeRow(self, row: int):
        self._rows.pop(row)

    def setItem(self, row: int, column: int, item: _HeadlessTableWidgetItem):
        self._rows[row][column] = item

    def item(self, row: int, column: int):
        try:
            return self._rows[row][column]
        except Exception:
            return None


class _HeadlessSignal:
    def connect(self, *_args):
        return None


class _HeadlessComboBox:
    def __init__(self):
        self._items: List[str] = []
        self._idx = -1

    def addItems(self, items: List[str]):
        for item in items:
            self.addItem(item)

    def addItem(self, text: str):
        self._items.append(text)
        if self._idx == -1:
            self._idx = 0

    def clear(self):
        self._items.clear()
        self._idx = -1

    def currentText(self):
        if 0 <= self._idx < len(self._items):
            return self._items[self._idx]
        return ""

    def findText(self, text: str):
        try:
            return self._items.index(text)
        except Exception:
            return -1

    def setCurrentIndex(self, index: int):
        self._idx = index if 0 <= index < len(self._items) else -1

    @property
    def currentTextChanged(self):
        return _HeadlessSignal()


class _HeadlessAccountWidget:
    pass


class AccountPanelAdapter(PanelAdapter):
    SUMMARY_FIELDS = [
        ("account_id", "Account ID"),
        ("cash", "Cash"),
        ("frozen_cash", "Frozen Cash"),
        ("frozen_fee", "Frozen Fee"),
        ("equity", "Equity"),
        ("utilization", "Utilization"),
        ("realized_pnl", "Realized PnL"),
        ("unrealized_pnl", "Unrealized PnL"),
    ]

    COLS = [
        "symbol",
        "quantity",
        "frozen_qty",
        "borrowed_qty",
        "exposure_state",
        "avg_price",
        "pnl_unreal",
        "pnl_ratio",
    ]

    def __init__(self):
        super().__init__()
        self._summary: Dict[str, Any] = {}
        self._summary_table: Optional[Any] = None
        self._table: Optional[Any] = None
        self._row_index: Dict[str, int] = {}
        self._account_combo: Optional[Any] = None
        self._orders_box: Optional[Any] = None
        self._orders_adapter: Optional[Any] = None
        self._cancel_subs: List[Any] = []
        self._items: List[Dict[str, Any]] = []
        self._last_view: Dict[str, Any] = {}
        self._item_type: Any = _HeadlessTableWidgetItem
        self._timer_type: Optional[Any] = None
        self._real_ui = False

    def _post_to_ui(self, fn):
        try:
            if self._real_ui and self._widget is not None:
                assert self._timer_type is not None
                self._timer_type.singleShot(0, fn)
                return
        except Exception:
            pass
        try:
            fn()
        except Exception:
            pass

    def refresh(self):
        self._post_to_ui(lambda: PanelAdapter.refresh(self))

    def _create_widget(self):
        runtime_ui = _load_runtime_ui_types()
        if runtime_ui is None:
            root: Any = _HeadlessAccountWidget()
            combo_type = _HeadlessComboBox
            label_type = _HeadlessLabel
            table_type = _HeadlessTableWidget
            item_type = _HeadlessTableWidgetItem
            horizontal_layout_type = None
            vertical_layout_type = None
            self._timer_type = None
            self._real_ui = False
        else:
            self._timer_type = runtime_ui.timer
            combo_type = runtime_ui.combo_box
            horizontal_layout_type = runtime_ui.horizontal_layout
            label_type = runtime_ui.label
            table_type = runtime_ui.table
            item_type = runtime_ui.table_item
            vertical_layout_type = runtime_ui.vertical_layout
            root = runtime_ui.widget()
            self._real_ui = True
        self._item_type = item_type
        self._account_combo = combo_type()
        self._summary_table = table_type(0, 2)
        self._summary_table.setColumnCount(2)
        self._summary_table.setHorizontalHeaderLabels(["Field", "Value"])
        self._table = table_type(0, len(self.COLS))
        self._table.setColumnCount(len(self.COLS))
        self._table.setHorizontalHeaderLabels(self.COLS)

        for key, _label in self.SUMMARY_FIELDS:
            self._summary[key] = label_type(f"{key}:")
        self._summary["semantic_gap"] = label_type(
            "account semantics: summary-oriented view"
        )

        if self._real_ui:
            try:
                assert vertical_layout_type is not None
                assert horizontal_layout_type is not None
                layout = vertical_layout_type(root)
                top = horizontal_layout_type()
                top.addWidget(label_type("Account"))
                top.addWidget(self._account_combo, 1)  # type: ignore[arg-type]
                layout.addLayout(top)
                layout.addWidget(self._summary_table)  # type: ignore[arg-type]
                layout.addWidget(self._summary["semantic_gap"])  # type: ignore[arg-type]
                layout.addWidget(self._table, 1)  # type: ignore[arg-type]
            except Exception:
                pass

        self._connect_combo()
        self._setup_subscriptions()
        self._prefill_accounts()
        return root

    def _discover_runtime_accounts(self) -> List[str]:
        try:
            from app.app_context import get_app_context

            return get_app_context().runtime_gateway.list_account_ids()
        except Exception:
            return []

    def _prefill_accounts(self) -> None:
        combo = self._account_combo
        if combo is None:
            return
        account_ids = self._discover_runtime_accounts()
        if not account_ids:
            return
        for aid in account_ids:
            if combo.findText(aid) == -1:
                combo.addItem(aid)
        current = str(combo.currentText() or "").strip()
        target = current or account_ids[0]
        idx = combo.findText(target)
        if idx >= 0:
            combo.setCurrentIndex(idx)
            self.switch_account(target)

    def _connect_combo(self):
        combo = self._account_combo
        if combo is None:
            return
        try:
            def _on_account_changed(account_id: str):
                aid = (account_id or "").strip()
                if not aid or self._logic is None:
                    return
                fn = getattr(self._logic, "switch_account", None)
                if not callable(fn):
                    return
                try:
                    fn(aid)
                    self.refresh()
                except Exception:
                    pass

            combo.currentTextChanged.connect(_on_account_changed)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _setup_subscriptions(self):
        try:
            def _on_batch_completed(_topic: str, payload: Dict[str, Any]):
                ids: List[str] = []
                if isinstance(payload, dict):
                    ids = list(payload.get("success_ids") or [])
                def _apply():
                    combo = self._account_combo
                    if combo is None:
                        return
                    for aid in ids:
                        if combo.findText(aid) == -1:
                            combo.addItem(aid)
                self._post_to_ui(_apply)

            self._cancel_subs.append(
                subscribe_topic("agent.batch.create.completed", _on_batch_completed, async_mode=False)
            )
        except Exception:
            pass

        try:
            def _on_account_created(_topic: str, payload: Dict[str, Any]):
                aid = payload.get("account_id") if isinstance(payload, dict) else None
                def _apply():
                    combo = self._account_combo
                    if not aid or combo is None:
                        return
                    if combo.findText(aid) == -1:
                        combo.addItem(aid)
                    idx = combo.findText(aid)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
                        self.switch_account(aid)
                self._post_to_ui(_apply)

            self._cancel_subs.append(on_account_created(_on_account_created, async_mode=False))
        except Exception:
            pass

        try:
            def _on_account_updated(_topic: str, payload: Dict[str, Any]):
                aid = None
                if isinstance(payload, dict):
                    aid = payload.get("id")
                    if aid is None and isinstance(payload.get("account"), dict):
                        aid = payload.get("account", {}).get("id")
                aid = str(aid or "").strip()
                if not aid:
                    return
                def _apply():
                    combo = self._account_combo
                    if combo is None:
                        return
                    if combo.findText(aid) == -1:
                        combo.addItem(aid)
                    current = str(combo.currentText() or "").strip()
                    if not current:
                        idx = combo.findText(aid)
                        if idx >= 0:
                            combo.setCurrentIndex(idx)
                            self.switch_account(aid)
                        return
                    if current == aid:
                        self.refresh()
                self._post_to_ui(_apply)

            self._cancel_subs.append(on_account_updated(_on_account_updated, async_mode=False))
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

    def _apply_view(self, view: Dict[str, Any]):
        self._last_view = dict(view) if isinstance(view, dict) else {}
        acc = view.get("account") if isinstance(view, dict) else None
        if acc:
            self._update_summary(acc)
            self._sync_account_combo(acc)
        else:
            self._clear_summary()

        positions = view.get("positions", {}) if isinstance(view, dict) else {}
        items = positions.get("items", []) if isinstance(positions, dict) else []
        self._items = list(items) if isinstance(items, list) else []
        if self._table is None:
            return
        self._diff_update_rows(self._items)

    def _update_summary(self, acc: Dict[str, Any]):
        self._sync_summary_table(acc)
        for key, lbl in self._summary.items():
            if key == "semantic_gap":
                meta = acc.get("account_meta") or {}
                gap = meta.get("semantic_gap") or "summary-oriented view"
                emphasized = meta.get("runtime_fields_emphasized") or []
                extra = f" | focus={','.join(emphasized)}" if emphasized else ""
                lbl.setText(f"account semantics: {gap}{extra}")
                continue
            lbl.setText(f"{key}:{acc.get(key)}")

    def _clear_summary(self):
        self._clear_summary_table()
        for key, lbl in self._summary.items():
            lbl.setText("account semantics:" if key == "semantic_gap" else f"{key}:")

    def _sync_summary_table(self, acc: Dict[str, Any]):
        table = self._summary_table
        if table is None:
            return
        rows = list(self.SUMMARY_FIELDS)
        try:
            while table.rowCount() < len(rows):
                table.insertRow(table.rowCount())
            while table.rowCount() > len(rows):
                table.removeRow(table.rowCount() - 1)
            for row_idx, (key, label) in enumerate(rows):
                label_item = table.item(row_idx, 0)
                if label_item is None:
                    label_item = self._item_type(label)
                    table.setItem(row_idx, 0, label_item)
                else:
                    label_item.setText(label)
                value_item = table.item(row_idx, 1)
                if value_item is None:
                    value_item = self._item_type("")
                    table.setItem(row_idx, 1, value_item)
                value_item.setText(self._format_summary_value(key, acc.get(key)))
        except Exception:
            pass

    def _clear_summary_table(self):
        table = self._summary_table
        if table is None:
            return
        try:
            while table.rowCount() > 0:
                table.removeRow(table.rowCount() - 1)
        except Exception:
            pass

    @staticmethod
    def _format_summary_value(key: str, value: Any) -> str:
        if value is None:
            return "-"
        if key == "utilization":
            try:
                return f"{float(value):.4%}"
            except Exception:
                return str(value)
        if key in {"cash", "frozen_cash", "frozen_fee", "equity", "realized_pnl", "unrealized_pnl"}:
            try:
                return f"{float(value):,.2f}"
            except Exception:
                return str(value)
        return str(value)

    def _sync_account_combo(self, acc: Dict[str, Any]):
        combo = self._account_combo
        if combo is None:
            return
        aid = acc.get("account_id")
        if not aid:
            return
        idx = combo.findText(aid)
        if idx == -1:
            combo.addItem(aid)
            idx = combo.findText(aid)
        combo.setCurrentIndex(idx)

    def _diff_update_rows(self, rows: List[Dict[str, Any]]):
        table = self._table
        if table is None:
            return

        new_symbols = [row.get("symbol") for row in rows if isinstance(row, dict) and row.get("symbol")]
        to_remove = [sym for sym in list(self._row_index.keys()) if sym not in new_symbols]
        for sym in sorted(to_remove, key=lambda symbol: self._row_index[symbol], reverse=True):
            row_idx = self._row_index.pop(sym, None)
            if row_idx is not None:
                table.removeRow(row_idx)

        self._reindex()
        for row in rows:
            sym = row.get("symbol")
            if not sym:
                continue
            row_idx = self._row_index.get(sym)
            if row_idx is None:
                row_idx = table.rowCount()
                table.insertRow(row_idx)
                self._row_index[sym] = row_idx
                for col_idx, _ in enumerate(self.COLS):
                    table.setItem(row_idx, col_idx, self._item_type(""))
            for col_idx, col_key in enumerate(self.COLS):
                val = row.get(col_key)
                item = table.item(row_idx, col_idx)
                if item is None:
                    continue
                item.setText("" if val is None else f"{val}")

    def _reindex(self):
        new_map: Dict[str, int] = {}
        table = self._table
        if table is None:
            return
        for row_idx in range(table.rowCount()):
            item = table.item(row_idx, 0)
            sym = item.text() if item else None
            if sym:
                new_map[sym] = row_idx
        self._row_index = new_map

    def get_view(self) -> Dict[str, Any]:
        try:
            if self._logic is not None:
                view = self._logic.get_view()
                if isinstance(view, dict):
                    self._apply_view(view)
        except Exception:
            pass
        return dict(self._last_view)

    def get_items(self) -> List[Dict[str, Any]]:
        view = self.get_view()
        positions = view.get("positions", {}) if isinstance(view, dict) else {}
        items = positions.get("items", []) if isinstance(positions, dict) else []
        return list(items) if isinstance(items, list) else []

    def switch_account(self, account_id: str):
        if self._logic is None:
            return None
        fn = getattr(self._logic, "switch_account", None)
        if not callable(fn):
            return None
        try:
            result = fn(account_id)
            self.refresh()
            return result
        except Exception:
            return None

    def set_filter(self, symbol_substring: Optional[str]):
        if self._logic is None:
            return None
        fn = getattr(self._logic, "set_filter", None)
        if not callable(fn):
            return None
        try:
            result = fn(symbol_substring)
            self.refresh()
            return result
        except Exception:
            return None

    def set_page(self, page: int, page_size: int):
        if self._logic is None:
            return None
        fn = getattr(self._logic, "set_page", None)
        if not callable(fn):
            return None
        try:
            result = fn(page, page_size)
            self.refresh()
            return result
        except Exception:
            return None


__all__ = ["AccountPanelAdapter"]
