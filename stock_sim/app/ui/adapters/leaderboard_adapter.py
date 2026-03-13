"""LeaderboardPanelAdapter (R4,R10 UI 基础)

功能:
- 窗口选择(QComboBox) -> 调用 logic.set_window(); 自动 refresh()
- 排序选择(QComboBox) -> 调用 logic.set_sort(); refresh()
- 表格显示 rows: rank, agent_id, return_pct, sharpe, equity, rank_delta
- 选中行 -> logic.select(agent_id); refresh() 后在曲线占位区域显示 equity_curve/drawdown_curve 点数
- 导出按钮(csv/xlsx) 异步线程执行 logic.export(fmt), 期间禁用按钮, 完成后在状态标签显示路径或错误

限制:
- 无真实图表：曲线仅以首/末/长度显示文本摘要 (后续可接入绘图)
- 未实现增量 diff (直接全量刷新; 行数较少性能足够)
- 不实现 force_refresh 逻辑 (依赖逻辑层缓存)
"""
from __future__ import annotations
from typing import Any, Dict, Optional, List
import threading

from .base_adapter import PanelAdapter

try:
    from PySide6.QtWidgets import (  # type: ignore
        QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QTableWidget,
        QTableWidgetItem, QLabel, QMessageBox
    )
except Exception:  # pragma: no cover - headless fallback
    QWidget = object  # type: ignore
    class QVBoxLayout:  # type: ignore
        def __init__(self,*_,**__): pass
        def addWidget(self,*_): pass
        def addLayout(self,*_): pass
    class QHBoxLayout:  # type: ignore
        def __init__(self,*_,**__): pass
        def addWidget(self,*_): pass
    class QComboBox:  # type: ignore
        def __init__(self): self._items=[]; self._current_index=-1; self.currentIndexChanged=_Sig()
        def addItems(self, arr): self._items.extend(arr)
        def currentText(self):
            if 0 <= self._current_index < len(self._items): return self._items[self._current_index]
            return ''
        def setCurrentIndex(self, i): self._current_index=i; self.currentIndexChanged.emit(i)
        def clear(self): self._items=[]; self._current_index=-1
    class QTableWidget:  # type: ignore
        def __init__(self, *_, **__): self._rows=[]
        def setColumnCount(self,n): pass
        def setHorizontalHeaderLabels(self,labels): pass
        def rowCount(self): return len(self._rows)
        def insertRow(self,r): self._rows.insert(r,[None]*6)
        def removeRow(self,r): self._rows.pop(r)
        def setItem(self,r,c,item): self._rows[r][c]=item
        def item(self,r,c):
            try: return self._rows[r][c]
            except Exception: return None
        def setCurrentCell(self,*_): pass
        def currentRow(self): return 0
    class QTableWidgetItem:  # type: ignore
        def __init__(self,text=""): self._text=text
        def text(self): return self._text
        def setText(self,t): self._text=t
    class QPushButton:  # type: ignore
        def __init__(self,text=""): self._text=text; self._enabled=True; self.clicked=_Sig()
        def setEnabled(self,val): self._enabled=val
    class QLabel:  # type: ignore
        def __init__(self,text=""): self._text=text
        def setText(self,t): self._text=t
    class QMessageBox:  # type: ignore
        @staticmethod
        def information(*_a, **_kw): pass
        @staticmethod
        def critical(*_a, **_kw): pass
    class _Sig:  # type: ignore
        def __init__(self): self._fn=[]
        def connect(self,f): self._fn.append(f)
        def emit(self,*a):
            for fn in list(self._fn):
                try: fn(*a)
                except Exception: pass

_SORT_OPTIONS = ["rank", "return_pct", "sharpe", "equity"]
_COLUMNS = ["rank", "agent_id", "return_pct", "sharpe", "equity", "rank_delta"]

class LeaderboardPanelAdapter(PanelAdapter):
    def __init__(self):
        super().__init__()
        self._root: Optional[Any] = None
        self._table: Optional[Any] = None
        self._combo_window: Optional[Any] = None
        self._combo_sort: Optional[Any] = None
        self._curve_label: Optional[Any] = None
        self._export_csv_btn: Optional[Any] = None
        self._export_xlsx_btn: Optional[Any] = None
        self._status_label: Optional[Any] = None
        self._export_lock = threading.Lock()
        self._exporting = False  # 并发保护
        self._current_rows: List[Dict[str, Any]] = []  # 缓存用于选择刷新

    # ---------- Overrides ----------
    def _create_widget(self):
        root = QWidget()  # type: ignore
        try:
            v = QVBoxLayout(root)  # type: ignore
            # Top controls
            top = QHBoxLayout()  # type: ignore
            self._combo_window = QComboBox()  # type: ignore
            self._combo_sort = QComboBox()  # type: ignore
            self._combo_sort.addItems(_SORT_OPTIONS)  # type: ignore
            try:
                self._combo_window.currentIndexChanged.connect(self._on_window_changed)  # type: ignore[attr-defined]
                self._combo_sort.currentIndexChanged.connect(self._on_sort_changed)  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                pass
            top.addWidget(self._combo_window)  # type: ignore
            top.addWidget(self._combo_sort)  # type: ignore
            # Export buttons
            self._export_csv_btn = QPushButton("Export CSV")  # type: ignore
            self._export_xlsx_btn = QPushButton("Export XLSX")  # type: ignore
            try:
                self._export_csv_btn.clicked.connect(lambda: self._start_export("csv"))  # type: ignore[attr-defined]
                self._export_xlsx_btn.clicked.connect(lambda: self._start_export("xlsx"))  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                pass
            top.addWidget(self._export_csv_btn)  # type: ignore
            top.addWidget(self._export_xlsx_btn)  # type: ignore
            self._status_label = QLabel("")  # type: ignore
            top.addWidget(self._status_label)  # type: ignore
            v.addLayout(top)  # type: ignore
            # Table
            self._table = QTableWidget(0, len(_COLUMNS))  # type: ignore
            self._table.setColumnCount(len(_COLUMNS))  # type: ignore
            self._table.setHorizontalHeaderLabels(_COLUMNS)  # type: ignore
            v.addWidget(self._table)  # type: ignore
            # Curve summary label
            self._curve_label = QLabel("curve: -")  # type: ignore
            v.addWidget(self._curve_label)  # type: ignore
        except Exception:  # pragma: no cover
            pass
        self._root = root
        return root

    def _apply_view(self, view: Dict[str, Any]):
        # 更新窗口列表
        windows = view.get('windows', []) if isinstance(view, dict) else []
        cur_win = view.get('window') if isinstance(view, dict) else None
        if self._combo_window is not None:
            try:
                # 仅当列表变化才重建
                rebuild = False
                existing = getattr(self._combo_window, 'count', lambda: len(getattr(self._combo_window, '_items', [])))()
                if existing != len(windows):
                    rebuild = True
                if rebuild:
                    self._combo_window.clear()  # type: ignore
                    if hasattr(self._combo_window, 'addItems'):
                        self._combo_window.addItems(windows)  # type: ignore
                # 设置当前窗口索引
                if cur_win in windows:
                    idx = windows.index(cur_win)
                    set_idx = getattr(self._combo_window, 'setCurrentIndex', None)
                    if callable(set_idx):
                        set_idx(idx)  # type: ignore
            except Exception:  # pragma: no cover
                pass
        # 排序当前值
        cur_sort = view.get('sort_by') if isinstance(view, dict) else None
        if self._combo_sort is not None and cur_sort in _SORT_OPTIONS:
            try:
                idx = _SORT_OPTIONS.index(cur_sort)
                self._combo_sort.setCurrentIndex(idx)  # type: ignore
            except Exception:  # pragma: no cover
                pass
        # rows
        rows = view.get('rows', []) if isinstance(view, dict) else []
        self._current_rows = rows  # 缓存
        self._refresh_table(rows)
        # 选中曲线
        sel = view.get('selected') if isinstance(view, dict) else None
        if sel and isinstance(sel, dict):
            self._update_curve(sel)

    # ---------- Internal UI Ops ----------
    def _refresh_table(self, rows: List[Dict[str, Any]]):
        table = self._table
        if table is None:
            return
        # 简单全量重建
        try:
            # 清空: 头保持, 移除所有行
            existing = getattr(table, 'rowCount', lambda: 0)()
            for r in reversed(range(existing)):
                try: table.removeRow(r)  # type: ignore
                except Exception: pass
            for i, row in enumerate(rows):
                try: table.insertRow(i)  # type: ignore
                except Exception: continue
                for c, col_key in enumerate(_COLUMNS):
                    val = row.get(col_key)
                    try:
                        item = QTableWidgetItem(str(val))  # type: ignore
                        table.setItem(i, c, item)  # type: ignore
                    except Exception:  # pragma: no cover
                        pass
            # 默认选中第一行若存在
            if rows:
                try: table.setCurrentCell(0, 0)  # type: ignore
                except Exception: pass
        except Exception:  # pragma: no cover
            pass

    def _update_curve(self, selected: Dict[str, Any]):
        if self._curve_label is None:
            return
        eq = selected.get('equity_curve') or []
        dd = selected.get('drawdown_curve') or []
        # 摘要: 长度+首末
        def summary(arr):
            if not arr: return "0"
            return f"len={len(arr)} start={arr[0]:.3f} end={arr[-1]:.3f}"
        text = f"equity[{summary(eq)}]; drawdown[{summary(dd)}]"
        try:
            self._curve_label.setText(text)  # type: ignore
        except Exception:  # pragma: no cover
            pass

    # ---------- Events ----------
    def _on_window_changed(self, *_):
        if not self._combo_window or self._logic is None:
            return
        win = self._combo_window.currentText()
        fn = getattr(self._logic, 'set_window', None)
        if callable(fn) and win:
            try:
                fn(win)
                self.refresh()
            except Exception:  # pragma: no cover
                pass

    def _on_sort_changed(self, *_):
        if not self._combo_sort or self._logic is None:
            return
        sort = self._combo_sort.currentText()
        fn = getattr(self._logic, 'set_sort', None)
        if callable(fn) and sort:
            try:
                fn(sort)
                self.refresh()
            except Exception:  # pragma: no cover
                pass

    def _set_exporting(self, flag: bool):
        with self._export_lock:
            self._exporting = flag

    def _is_exporting(self) -> bool:
        with self._export_lock:
            return self._exporting

    def _start_export(self, fmt: str):
        if self._logic is None:
            return
        # 防止并发: 若正在进行直接忽略第二次点击
        if self._is_exporting():
            if self._status_label is not None:
                try: self._status_label.setText("export already running...")  # type: ignore
                except Exception: pass
            return
        self._set_exporting(True)
        btns = [self._export_csv_btn, self._export_xlsx_btn]
        # 禁用按钮防止重复
        for b in btns:
            try: b.setEnabled(False)  # type: ignore
            except Exception: pass
        if self._status_label is not None:
            try: self._status_label.setText(f"exporting {fmt}...")  # type: ignore
            except Exception: pass
        def _run():
            path = None
            error = None
            try:
                export_fn = getattr(self._logic, 'export', None)
                if callable(export_fn):
                    path = export_fn(fmt)
            except Exception as e:  # pragma: no cover
                error = str(e)
            # 回主线程假设：直接设置 (未加线程切换; 简化)
            if self._status_label is not None:
                try:
                    if error:
                        self._status_label.setText(f"export fail: {error}")  # type: ignore
                        try:
                            if 'QMessageBox' in globals() and QMessageBox:  # type: ignore
                                QMessageBox.critical(None, "Export Failed", error)  # type: ignore
                        except Exception:  # pragma: no cover
                            pass
                    else:
                        self._status_label.setText(f"export ok: {path}")  # type: ignore
                        try:
                            if 'QMessageBox' in globals() and QMessageBox and path:  # type: ignore
                                QMessageBox.information(None, "Export Success", path)  # type: ignore
                        except Exception:  # pragma: no cover
                            pass
                except Exception:  # pragma: no cover
                    pass
            for b in btns:
                try: b.setEnabled(True)  # type: ignore
                except Exception: pass
            self._set_exporting(False)
        t = threading.Thread(target=_run, daemon=True)
        t.start()

__all__ = ["LeaderboardPanelAdapter"]
