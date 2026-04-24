"""Leaderboard panel adapter."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
import threading

from .base_adapter import PanelAdapter

try:
    from PySide6.QtCore import QTimer  # type: ignore
    from PySide6.QtWidgets import (  # type: ignore
        QApplication,
        QComboBox,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except Exception:  # pragma: no cover
    QApplication = None  # type: ignore
    QTimer = None  # type: ignore
    QComboBox = None  # type: ignore
    QHBoxLayout = None  # type: ignore
    QLabel = None  # type: ignore
    QPushButton = None  # type: ignore
    QTableWidget = None  # type: ignore
    QTableWidgetItem = None  # type: ignore
    QVBoxLayout = None  # type: ignore
    QWidget = None  # type: ignore


class _Sig:
    def __init__(self):
        self._callbacks = []

    def connect(self, fn):
        self._callbacks.append(fn)

    def emit(self, *args):
        for fn in list(self._callbacks):
            try:
                fn(*args)
            except Exception:
                pass


class _HeadlessWidget:
    pass


class _HeadlessVBoxLayout:
    def __init__(self, *_, **__):
        pass

    def addWidget(self, *_):
        pass

    def addLayout(self, *_):
        pass


class _HeadlessHBoxLayout:
    def __init__(self, *_, **__):
        pass

    def addWidget(self, *_):
        pass


class _HeadlessComboBox:
    def __init__(self):
        self._items: List[str] = []
        self._current_index = -1
        self.currentIndexChanged = _Sig()

    def addItems(self, items):
        self._items.extend(items)

    def currentText(self):
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index]
        return ""

    def setCurrentIndex(self, index):
        self._current_index = index
        self.currentIndexChanged.emit(index)

    def clear(self):
        self._items = []
        self._current_index = -1


class _HeadlessTableWidget:
    def __init__(self, *_, **__):
        self._rows: List[List[Any]] = []

    def setColumnCount(self, _n):
        pass

    def setHorizontalHeaderLabels(self, _labels):
        pass

    def rowCount(self):
        return len(self._rows)

    def insertRow(self, row):
        self._rows.insert(row, [None] * 6)

    def removeRow(self, row):
        self._rows.pop(row)

    def setItem(self, row, col, item):
        self._rows[row][col] = item

    def item(self, row, col):
        try:
            return self._rows[row][col]
        except Exception:
            return None

    def setCurrentCell(self, *_):
        pass


class _HeadlessTableWidgetItem:
    def __init__(self, text=""):
        self._text = text

    def text(self):
        return self._text

    def setText(self, text):
        self._text = text


class _HeadlessPushButton:
    def __init__(self, text=""):
        self._text = text
        self._enabled = True
        self.clicked = _Sig()

    def setEnabled(self, enabled):
        self._enabled = enabled


class _HeadlessLabel:
    def __init__(self, text=""):
        self._text = text

    def setText(self, text):
        self._text = text


_SORT_OPTIONS = ["rank", "return_pct", "sharpe", "equity"]
_COLUMNS = ["rank", "agent_id", "return_pct", "sharpe", "equity", "rank_delta"]


def _has_qt_app() -> bool:
    try:
        return QApplication is not None and QApplication.instance() is not None
    except Exception:
        return False


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
        self._exporting = False
        self._current_rows: List[Dict[str, Any]] = []

    def set_logic(self, logic: Any):
        self.bind(logic)
        return self

    def _post_to_ui(self, cb) -> bool:
        if QTimer is None or not _has_qt_app():
            return False
        try:
            QTimer.singleShot(0, cb)
            return True
        except Exception:
            return False

    def _create_widget(self):
        if _has_qt_app():
            root = QWidget()  # type: ignore
            layout_cls = QVBoxLayout  # type: ignore
            row_layout_cls = QHBoxLayout  # type: ignore
            combo_cls = QComboBox  # type: ignore
            table_cls = QTableWidget  # type: ignore
            item_cls = QTableWidgetItem  # type: ignore
            button_cls = QPushButton  # type: ignore
            label_cls = QLabel  # type: ignore
        else:
            root = _HeadlessWidget()
            layout_cls = _HeadlessVBoxLayout
            row_layout_cls = _HeadlessHBoxLayout
            combo_cls = _HeadlessComboBox
            table_cls = _HeadlessTableWidget
            item_cls = _HeadlessTableWidgetItem
            button_cls = _HeadlessPushButton
            label_cls = _HeadlessLabel

        try:
            layout = layout_cls(root)
            top = row_layout_cls()

            self._combo_window = combo_cls()
            self._combo_sort = combo_cls()
            self._combo_sort.addItems(_SORT_OPTIONS)
            try:
                self._combo_window.currentIndexChanged.connect(self._on_window_changed)
                self._combo_sort.currentIndexChanged.connect(self._on_sort_changed)
            except Exception:
                pass
            top.addWidget(self._combo_window)
            top.addWidget(self._combo_sort)

            self._export_csv_btn = button_cls("Export CSV")
            self._export_xlsx_btn = button_cls("Export XLSX")
            try:
                self._export_csv_btn.clicked.connect(lambda: self._start_export("csv"))
                self._export_xlsx_btn.clicked.connect(lambda: self._start_export("xlsx"))
            except Exception:
                pass
            top.addWidget(self._export_csv_btn)
            top.addWidget(self._export_xlsx_btn)

            self._status_label = label_cls("")
            top.addWidget(self._status_label)
            layout.addLayout(top)

            self._table = table_cls(0, len(_COLUMNS))
            self._table.setColumnCount(len(_COLUMNS))
            self._table.setHorizontalHeaderLabels(_COLUMNS)
            layout.addWidget(self._table)

            self._curve_label = label_cls("curve: -")
            layout.addWidget(self._curve_label)
            self._item_cls = item_cls
        except Exception:
            self._item_cls = _HeadlessTableWidgetItem

        self._root = root
        return root

    def _apply_view(self, view: Dict[str, Any]):
        windows = view.get("windows", []) if isinstance(view, dict) else []
        current_window = view.get("window") if isinstance(view, dict) else None
        if self._combo_window is not None:
            try:
                existing = getattr(
                    self._combo_window,
                    "count",
                    lambda: len(getattr(self._combo_window, "_items", [])),
                )()
                if existing != len(windows):
                    self._combo_window.clear()
                    if hasattr(self._combo_window, "addItems"):
                        self._combo_window.addItems(windows)
                if current_window in windows:
                    self._combo_window.setCurrentIndex(windows.index(current_window))
            except Exception:
                pass

        current_sort = view.get("sort_by") if isinstance(view, dict) else None
        if self._combo_sort is not None and current_sort in _SORT_OPTIONS:
            try:
                self._combo_sort.setCurrentIndex(_SORT_OPTIONS.index(current_sort))
            except Exception:
                pass

        rows = view.get("rows", []) if isinstance(view, dict) else []
        self._current_rows = rows
        self._refresh_table(rows)

        selected = view.get("selected") if isinstance(view, dict) else None
        if isinstance(selected, dict):
            self._update_curve(selected)

    def _refresh_table(self, rows: List[Dict[str, Any]]):
        if self._table is None:
            return
        try:
            existing = getattr(self._table, "rowCount", lambda: 0)()
            for row in reversed(range(existing)):
                try:
                    self._table.removeRow(row)
                except Exception:
                    pass
            for row_index, row in enumerate(rows):
                try:
                    self._table.insertRow(row_index)
                except Exception:
                    continue
                for col_index, col_key in enumerate(_COLUMNS):
                    try:
                        item = self._item_cls(str(row.get(col_key)))
                        self._table.setItem(row_index, col_index, item)
                    except Exception:
                        pass
            if rows:
                try:
                    self._table.setCurrentCell(0, 0)
                except Exception:
                    pass
        except Exception:
            pass

    def _update_curve(self, selected: Dict[str, Any]):
        if self._curve_label is None:
            return
        equity = selected.get("equity_curve") or []
        drawdown = selected.get("drawdown_curve") or []

        def _summary(values):
            if not values:
                return "0"
            return f"len={len(values)} start={values[0]:.3f} end={values[-1]:.3f}"

        try:
            self._curve_label.setText(
                f"equity[{_summary(equity)}]; drawdown[{_summary(drawdown)}]"
            )
        except Exception:
            pass

    def _on_window_changed(self, *_):
        if not self._combo_window or self._logic is None:
            return
        window = self._combo_window.currentText()
        fn = getattr(self._logic, "set_window", None)
        if callable(fn) and window:
            try:
                fn(window)
                self.refresh()
            except Exception:
                pass

    def _on_sort_changed(self, *_):
        if not self._combo_sort or self._logic is None:
            return
        sort_by = self._combo_sort.currentText()
        fn = getattr(self._logic, "set_sort", None)
        if callable(fn) and sort_by:
            try:
                fn(sort_by)
                self.refresh()
            except Exception:
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
        if self._is_exporting():
            if self._status_label is not None:
                try:
                    self._status_label.setText("export already running...")
                except Exception:
                    pass
            return

        self._set_exporting(True)
        buttons = [self._export_csv_btn, self._export_xlsx_btn]
        for button in buttons:
            try:
                button.setEnabled(False)
            except Exception:
                pass
        if self._status_label is not None:
            try:
                self._status_label.setText(f"exporting {fmt}...")
            except Exception:
                pass

        def _run():
            path = None
            error = None
            try:
                export_fn = getattr(self._logic, "export", None)
                if callable(export_fn):
                    path = export_fn(fmt)
            except Exception as exc:  # pragma: no cover
                error = str(exc)

            def _finish_ui():
                if self._status_label is not None:
                    try:
                        if error:
                            self._status_label.setText(f"export fail: {error}")
                        else:
                            self._status_label.setText(f"export ok: {path}")
                    except Exception:
                        pass
                for button in buttons:
                    try:
                        button.setEnabled(True)
                    except Exception:
                        pass
                self._set_exporting(False)

            if not self._post_to_ui(_finish_ui):
                _finish_ui()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()


__all__ = ["LeaderboardPanelAdapter"]
