"""AccountPanelAdapter (R1)

桥接 AccountPanel 逻辑与 QWidget:
- 顶部摘要: 账户 id / cash / equity / utilization / realized / unrealized
- 持仓表格: symbol, quantity, avg_price, pnl_unreal, pnl_ratio
- 根据 view['positions']['items'] 中的 highlight 字段着色行背景 (浅红/浅绿按 pnl_ratio 正负)
- 差异更新: 复用已存在行(按 symbol)；新增/移除最小操作，降低 repaint
- 新增: 账户选择下拉框(QComboBox)，选择后切换账户并同步下方订单视图（仅显示该账户订单）

在无 PySide6 环境下降级为占位对象 (headless 测试)。

限制:
- 不做排序/分页 (分页由逻辑层处理, adapter 直接渲染当前页)
- 不做阻塞 IO (所有数据来自内存 view dict)
"""
from __future__ import annotations
from typing import Any, Dict, Optional, List

from .base_adapter import PanelAdapter

try:  # 尝试导入 PySide6
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QComboBox, QGroupBox
    )  # type: ignore
    from PySide6.QtGui import QColor  # type: ignore
except Exception:  # pragma: no cover - headless fallback
    QWidget = object  # type: ignore
    class QLabel:  # type: ignore
        def __init__(self, text=""):
            self._text = text
        def setText(self, t):  # noqa: D401
            self._text = t
    class QTableWidget:  # type: ignore
        def __init__(self, *_, **__):
            self._rows = []
        def setColumnCount(self, n):
            pass
        def setHorizontalHeaderLabels(self, labels):
            pass
        def rowCount(self):
            return len(self._rows)
        def insertRow(self, r):
            self._rows.insert(r, [None]*5)
        def removeRow(self, r):
            self._rows.pop(r)
        def setItem(self, r, c, item):
            self._rows[r][c] = item
        def item(self, r, c):
            try:
                return self._rows[r][c]
            except Exception:
                return None
    class QTableWidgetItem:  # type: ignore
        def __init__(self, text=""):
            self._text = text
        def setText(self, t):
            self._text = t
        def text(self):  # noqa: D401
            return self._text
    class QVBoxLayout:  # type: ignore
        def __init__(self, *_, **__):
            pass
        def addLayout(self, *_):
            pass
        def addWidget(self, *_):
            pass
    class QHBoxLayout:  # type: ignore
        def __init__(self, *_, **__):
            pass
        def addWidget(self, *_):
            pass
    class QComboBox:  # type: ignore
        def __init__(self):
            self._items: List[str] = []
            self._idx = -1
        def addItems(self, items: List[str]):
            self._items.extend(items)
            if self._idx == -1 and self._items:
                self._idx = 0
        def addItem(self, text: str):
            self._items.append(text)
            if self._idx == -1:
                self._idx = 0
        def clear(self):
            self._items.clear(); self._idx = -1
        def currentText(self):
            if 0 <= self._idx < len(self._items):
                return self._items[self._idx]
            return ""
        def findText(self, text: str):
            try: return self._items.index(text)
            except Exception: return -1
        def setCurrentIndex(self, i: int):
            self._idx = i if 0 <= i < len(self._items) else -1
    class QGroupBox:  # type: ignore
        def __init__(self, *_): pass
    class QColor:  # type: ignore
        def __init__(self, *_):
            pass

# 事件订阅（后备 event_bus）
from infra.event_bus import event_bus
try:
    from app.event_bridge import subscribe_topic  # type: ignore
except Exception:  # pragma: no cover
    def subscribe_topic(topic, handler, *, async_mode=False):  # type: ignore
        event_bus.subscribe(topic, handler, async_mode=async_mode)
        return lambda: event_bus.unsubscribe(topic, handler)

# 颜色（Qt 有效时生效）
_HIGHLIGHT_POS = QColor(230, 255, 230) if isinstance(QWidget, type) else None  # 绿色浅色
_HIGHLIGHT_NEG = QColor(255, 235, 235) if isinstance(QWidget, type) else None  # 红色浅色

# 嵌入 Orders 视图
try:
    from app.ui.adapters.orders_adapter import OrdersPanelAdapter
except Exception:  # pragma: no cover
    OrdersPanelAdapter = None  # type: ignore

class AccountPanelAdapter(PanelAdapter):
    COLS = ["symbol", "quantity", "avg_price", "pnl_unreal", "pnl_ratio"]

    def __init__(self):  # noqa: D401
        super().__init__()
        self._summary: Dict[str, QLabel] = {}
        self._table: Optional[QTableWidget] = None  # type: ignore
        self._row_index: Dict[str, int] = {}  # symbol -> row
        # 新增: 账户选择与订单适配器
        self._account_combo: Optional[Any] = None
        self._orders_box: Optional[Any] = None
        self._orders_adapter: Optional[Any] = None
        # 订阅取消函数
        self._cancel_subs: List[Any] = []

    # ---------- PanelAdapter overrides ----------
    def _create_widget(self):  # noqa: D401
        container = QWidget()  # type: ignore
        try:  # GUI 可用时构建布局
            if isinstance(container, QWidget):  # type: ignore
                v = QVBoxLayout(container)  # type: ignore
                # 账户选择
                acct_row = QHBoxLayout()  # type: ignore
                acct_row.addWidget(QLabel("Account:"))  # type: ignore
                self._account_combo = QComboBox()  # type: ignore
                try:
                    # 允许手动输入账户 id
                    if hasattr(self._account_combo, 'setEditable'):
                        self._account_combo.setEditable(True)  # type: ignore[attr-defined]
                except Exception:
                    pass
                try:
                    def _on_acct_change(*_):
                        aid = None
                        try:
                            aid = self._account_combo.currentText()  # type: ignore[attr-defined]
                        except Exception:
                            aid = None
                        if aid and self._logic is not None:
                            try:
                                switch = getattr(self._logic, 'switch_account', None)
                                if callable(switch):
                                    switch(aid)
                            except Exception:
                                pass
                        # 同步 orders 过滤
                        if self._orders_adapter is not None and hasattr(self._orders_adapter, 'set_account_filter'):
                            try:
                                self._orders_adapter.set_account_filter(aid)
                            except Exception:
                                pass
                        self.refresh()
                    # 真实 Qt: currentIndexChanged 信号
                    try:
                        self._account_combo.currentIndexChanged.connect(_on_acct_change)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                except Exception:
                    pass
                acct_row.addWidget(self._account_combo)  # type: ignore
                v.addLayout(acct_row)  # type: ignore
                # Summary 行
                h = QHBoxLayout()  # type: ignore
                for key in ["account_id", "cash", "equity", "utilization", "realized_pnl", "unrealized_pnl"]:
                    lbl = QLabel(f"{key}:")  # type: ignore
                    self._summary[key] = lbl  # 存 label
                    h.addWidget(lbl)  # type: ignore
                v.addLayout(h)  # type: ignore
                # Table
                table = QTableWidget(0, len(self.COLS))  # type: ignore
                table.setColumnCount(len(self.COLS))  # type: ignore
                table.setHorizontalHeaderLabels(self.COLS)  # type: ignore
                v.addWidget(table)  # type: ignore
                self._table = table
                # Orders 子视图
                if OrdersPanelAdapter is not None:
                    try:
                        self._orders_box = QGroupBox("Orders")  # type: ignore
                        ov = QVBoxLayout(self._orders_box)  # type: ignore
                        self._orders_adapter = OrdersPanelAdapter()
                        ov.addWidget(self._orders_adapter.widget())  # type: ignore
                        v.addWidget(self._orders_box)  # type: ignore
                    except Exception:
                        self._orders_adapter = None
                # 订阅批量创建完成事件以动态填充账户 id
                try:
                    def _on_batch_completed(_topic: str, payload: Dict[str, Any]):
                        try:
                            ids: List[str] = []
                            if isinstance(payload, dict):
                                ids = list(payload.get('success_ids') or [])
                            if not ids:
                                return
                            combo = self._account_combo
                            if combo is None:
                                return
                            for aid in ids:
                                try:
                                    idx = combo.findText(aid)  # type: ignore[attr-defined]
                                except Exception:
                                    idx = -1
                                if idx == -1:
                                    try:
                                        combo.addItem(aid)  # type: ignore[attr-defined]
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                    self._cancel_subs.append(subscribe_topic("agent.batch.create.completed", _on_batch_completed, async_mode=False))
                except Exception:
                    pass
                # 新增：订阅单个账户创建事件
                try:
                    def _on_account_created(_topic: str, payload: Dict[str, Any]):
                        try:
                            aid = None
                            if isinstance(payload, dict):
                                aid = payload.get('account_id')
                            if not aid:
                                return
                            combo = self._account_combo
                            if combo is None:
                                return
                            try:
                                idx = combo.findText(aid)  # type: ignore[attr-defined]
                            except Exception:
                                idx = -1
                            if idx == -1:
                                try:
                                    combo.addItem(aid)  # type: ignore[attr-defined]
                                    try:
                                        combo.setCurrentIndex(combo.findText(aid))  # type: ignore[attr-defined]
                                    except Exception:
                                        pass
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    self._cancel_subs.append(subscribe_topic("account.created", _on_account_created, async_mode=False))
                except Exception:
                    pass
        except Exception:  # pragma: no cover
            pass
        return container

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
        try:
            super_del = getattr(super(), '__del__', None)
            if callable(super_del):
                super_del()
        except Exception:
            pass

    def _apply_view(self, view: Dict[str, Any]):  # noqa: D401
        # 更新摘要
        acc = view.get('account') if isinstance(view, dict) else None
        if acc:
            self._update_summary(acc)
            # 同步下拉框选项（懒更新）
            self._sync_account_combo(acc)
            # 同步订单过滤
            if self._orders_adapter is not None and hasattr(self._orders_adapter, 'set_account_filter'):
                try:
                    self._orders_adapter.set_account_filter(acc.get('account_id'))
                except Exception:
                    pass
        else:
            self._clear_summary()
        # 更新表格
        positions = view.get('positions', {}) if isinstance(view, dict) else {}
        items = positions.get('items', []) if isinstance(positions, dict) else []
        if self._table is None:
            return
        self._diff_update_rows(items)

    # ---------- Internal: summary ----------
    def _update_summary(self, acc: Dict[str, Any]):
        for k, lbl in self._summary.items():
            val = acc.get(k)
            try:
                if isinstance(lbl, QLabel):  # type: ignore
                    lbl.setText(f"{k}:{val}")  # type: ignore
            except Exception:  # pragma: no cover
                pass

    def _clear_summary(self):
        for k, lbl in self._summary.items():
            try:
                if isinstance(lbl, QLabel):  # type: ignore
                    lbl.setText(f"{k}:")  # type: ignore
            except Exception:  # pragma: no cover
                pass

    def _sync_account_combo(self, acc: Dict[str, Any]):
        combo = self._account_combo
        if combo is None:
            return
        try:
            aid = acc.get('account_id')
            if not aid:
                return
            # 若不存在则加入；并选中该项
            idx = combo.findText(aid)  # type: ignore[attr-defined]
            if idx == -1:
                try:
                    combo.addItem(aid)  # type: ignore[attr-defined]
                except Exception:
                    pass
                idx = combo.findText(aid)  # type: ignore[attr-defined]
            try:
                combo.setCurrentIndex(idx)  # type: ignore[attr-defined]
            except Exception:
                pass
        except Exception:  # pragma: no cover
            pass

    # ---------- Internal: table diff ----------
    def _diff_update_rows(self, rows: list[Dict[str, Any]]):
        table = self._table
        if table is None:
            return
        # 构建新 symbol 集
        new_symbols = [r.get('symbol') for r in rows if isinstance(r, dict) and r.get('symbol')]
        # 移除不存在的行 (逆序删除避免索引移动问题)
        to_remove = [sym for sym in list(self._row_index.keys()) if sym not in new_symbols]
        if to_remove:
            # 按 row 倒序
            for sym in sorted(to_remove, key=lambda s: self._row_index[s], reverse=True):
                row_idx = self._row_index.pop(sym, None)
                if row_idx is not None:
                    try:
                        table.removeRow(row_idx)  # type: ignore
                    except Exception:  # pragma: no cover
                        pass
            # 重建索引
            self._reindex()
        # 更新/新增
        for r in rows:
            sym = r.get('symbol')
            if not sym:
                continue
            row_idx = self._row_index.get(sym)
            if row_idx is None:  # 新增
                row_idx = table.rowCount()  # type: ignore
                try:
                    table.insertRow(row_idx)  # type: ignore
                except Exception:  # pragma: no cover
                    continue
                self._row_index[sym] = row_idx
                # 初始化列
                for col_idx, col_key in enumerate(self.COLS):
                    item = QTableWidgetItem("")  # type: ignore
                    try:
                        table.setItem(row_idx, col_idx, item)  # type: ignore
                    except Exception:  # pragma: no cover
                        pass
            # 更新列文本
            for col_idx, col_key in enumerate(self.COLS):
                val = r.get(col_key)
                item = table.item(row_idx, col_idx)  # type: ignore
                if item is None:
                    continue
                new_text = f"{val}" if val is not None else ""
                try:
                    # 仅当变更再 setText 减少 repaint
                    if not hasattr(item, 'text') or item.text() != new_text:  # type: ignore
                        item.setText(new_text)  # type: ignore
                except Exception:  # pragma: no cover
                    pass
            # 行高亮
            self._apply_row_highlight(row_idx, r)

    def _apply_row_highlight(self, row_idx: int, r: Dict[str, Any]):
        table = self._table
        if table is None:
            return
        highlight = r.get('highlight')
        ratio = r.get('pnl_ratio') or 0.0
        color: Optional[Any] = None
        if highlight:
            color = _HIGHLIGHT_POS if ratio >= 0 else _HIGHLIGHT_NEG
        # 设置每列背景
        if color is not None and hasattr(color, 'isValid'):
            for col_idx in range(len(self.COLS)):
                item = table.item(row_idx, col_idx)  # type: ignore
                if item is None:
                    continue
                try:
                    # Qt: item.setBackground(color)
                    setter = getattr(item, 'setBackground', None)
                    if callable(setter):
                        setter(color)
                except Exception:  # pragma: no cover
                    pass
        else:
            # 取消背景: 设置为透明（简单方式: new item background omitted）
            for col_idx in range(len(self.COLS)):
                item = table.item(row_idx, col_idx)  # type: ignore
                if item is None:
                    continue
                try:
                    setter = getattr(item, 'setBackground', None)
                    if callable(setter):
                        # 传 None/空色 (某些实现可能需要QColor())
                        setter(QColor(255, 255, 255, 0))  # type: ignore
                except Exception:  # pragma: no cover
                    pass

    def _reindex(self):
        # 重新扫描表格构建 symbol->row（当删除行后）
        new_map: Dict[str, int] = {}
        table = self._table
        if table is None:
            return
        # 遍历所有行第一列 (symbol)
        try:
            rc = table.rowCount()  # type: ignore
        except Exception:
            rc = 0
        for r in range(rc):
            item = table.item(r, 0)  # type: ignore
            try:
                sym = item.text() if item else None  # type: ignore
            except Exception:
                sym = None
            if sym:
                new_map[sym] = r
        self._row_index = new_map

__all__ = ["AccountPanelAdapter"]
