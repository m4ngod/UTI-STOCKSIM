"""Headless-safe AccountPanelAdapter.

发布前优先保证：
- account.created 事件可把账户加入下拉框
- 账户摘要和持仓表能稳定接收 view
- 在无完整 Qt 生命周期时不触发进程级退出

当前实现刻意采用纯 headless-safe 轻量对象，避免在测试/无 GUI 场景中
误入 PySide6/Qt 真实控件路径。
"""
from __future__ import annotations

from typing import Any, Dict, Optional, List

from .base_adapter import PanelAdapter
from infra.event_bus import event_bus

try:
    from app.event_bridge import subscribe_topic  # type: ignore
except Exception:  # pragma: no cover
    def subscribe_topic(topic, handler, *, async_mode=False):  # type: ignore
        event_bus.subscribe(topic, handler, async_mode=async_mode)
        return lambda: event_bus.unsubscribe(topic, handler)


class QLabel:  # headless-safe label
    def __init__(self, text: str = ""):
        self._text = text
    def setText(self, t: str):
        self._text = t
    def text(self) -> str:
        return self._text


class QTableWidgetItem:
    def __init__(self, text: str = ""):
        self._text = text
    def setText(self, t: str):
        self._text = t
    def text(self) -> str:
        return self._text


class QTableWidget:
    def __init__(self, *_a, **_k):
        self._rows: list[list[QTableWidgetItem | None]] = []
        self._cols = 0
    def setColumnCount(self, n: int):
        self._cols = n
    def setHorizontalHeaderLabels(self, _labels):
        pass
    def rowCount(self):
        return len(self._rows)
    def insertRow(self, r: int):
        self._rows.insert(r, [None] * self._cols)
    def removeRow(self, r: int):
        self._rows.pop(r)
    def setItem(self, r: int, c: int, item: QTableWidgetItem):
        self._rows[r][c] = item
    def item(self, r: int, c: int):
        try:
            return self._rows[r][c]
        except Exception:
            return None


class QComboBox:
    def __init__(self):
        self._items: List[str] = []
        self._idx = -1
    def addItems(self, items: List[str]):
        for i in items:
            self.addItem(i)
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
    def setCurrentIndex(self, i: int):
        self._idx = i if 0 <= i < len(self._items) else -1


class _HeadlessAccountWidget:
    pass


class AccountPanelAdapter(PanelAdapter):
    COLS = ["symbol", "quantity", "frozen_qty", "borrowed_qty", "exposure_state", "avg_price", "pnl_unreal", "pnl_ratio"]

    def __init__(self):
        super().__init__()
        self._summary: Dict[str, QLabel] = {}
        self._table: Optional[QTableWidget] = None
        self._row_index: Dict[str, int] = {}
        self._account_combo: Optional[Any] = None
        self._orders_box: Optional[Any] = None
        self._orders_adapter: Optional[Any] = None
        self._cancel_subs: List[Any] = []
        self._items: List[Dict[str, Any]] = []
        self._last_view: Dict[str, Any] = {}

    def _create_widget(self):
        self._account_combo = QComboBox()
        self._table = QTableWidget(0, len(self.COLS))
        self._table.setColumnCount(len(self.COLS))
        self._table.setHorizontalHeaderLabels(self.COLS)
        for key in ["account_id", "cash", "frozen_cash", "frozen_fee", "equity", "utilization", "realized_pnl", "unrealized_pnl"]:
            self._summary[key] = QLabel(f"{key}:")
        self._summary["semantic_gap"] = QLabel("account semantics: summary-oriented view")
        self._setup_subscriptions()
        return _HeadlessAccountWidget()

    def _setup_subscriptions(self):
        try:
            def _on_batch_completed(_topic: str, payload: Dict[str, Any]):
                ids: List[str] = []
                if isinstance(payload, dict):
                    ids = list(payload.get("success_ids") or [])
                combo = self._account_combo
                if combo is None:
                    return
                for aid in ids:
                    if combo.findText(aid) == -1:
                        combo.addItem(aid)
            self._cancel_subs.append(subscribe_topic("agent.batch.create.completed", _on_batch_completed, async_mode=False))
        except Exception:
            pass

        try:
            def _on_account_created(_topic: str, payload: Dict[str, Any]):
                aid = payload.get("account_id") if isinstance(payload, dict) else None
                combo = self._account_combo
                if not aid or combo is None:
                    return
                if combo.findText(aid) == -1:
                    combo.addItem(aid)
                    combo.setCurrentIndex(combo.findText(aid))
            self._cancel_subs.append(subscribe_topic("account.created", _on_account_created, async_mode=False))
        except Exception:
            pass

    def __del__(self):
        try:
            for c in list(self._cancel_subs):
                try:
                    c()
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
        for k, lbl in self._summary.items():
            if k == "semantic_gap":
                meta = acc.get("account_meta") or {}
                gap = meta.get("semantic_gap") or "summary-oriented view"
                emphasized = meta.get("runtime_fields_emphasized") or []
                extra = f" | focus={','.join(emphasized)}" if emphasized else ""
                lbl.setText(f"account semantics: {gap}{extra}")
                continue
            lbl.setText(f"{k}:{acc.get(k)}")

    def _clear_summary(self):
        for k, lbl in self._summary.items():
            lbl.setText("account semantics:" if k == "semantic_gap" else f"{k}:")

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

    def _diff_update_rows(self, rows: list[Dict[str, Any]]):
        table = self._table
        if table is None:
            return
        new_symbols = [r.get("symbol") for r in rows if isinstance(r, dict) and r.get("symbol")]
        to_remove = [sym for sym in list(self._row_index.keys()) if sym not in new_symbols]
        for sym in sorted(to_remove, key=lambda s: self._row_index[s], reverse=True):
            row_idx = self._row_index.pop(sym, None)
            if row_idx is not None:
                table.removeRow(row_idx)
        self._reindex()
        for r in rows:
            sym = r.get("symbol")
            if not sym:
                continue
            row_idx = self._row_index.get(sym)
            if row_idx is None:
                row_idx = table.rowCount()
                table.insertRow(row_idx)
                self._row_index[sym] = row_idx
                for col_idx, _col_key in enumerate(self.COLS):
                    table.setItem(row_idx, col_idx, QTableWidgetItem(""))
            for col_idx, col_key in enumerate(self.COLS):
                val = r.get(col_key)
                item = table.item(row_idx, col_idx)
                if item is None:
                    continue
                item.setText("" if val is None else f"{val}")

    def _reindex(self):
        new_map: Dict[str, int] = {}
        table = self._table
        if table is None:
            return
        rc = table.rowCount()
        for r in range(rc):
            item = table.item(r, 0)
            sym = item.text() if item else None
            if sym:
                new_map[sym] = r
        self._row_index = new_map

    # ---------- Headless/integration helpers ----------
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
