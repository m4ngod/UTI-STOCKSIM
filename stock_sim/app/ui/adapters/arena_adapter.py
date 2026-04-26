"""Arena panel adapter."""
from __future__ import annotations

from typing import Any

from .base_adapter import PanelAdapter

try:
    from PySide6.QtCore import QTimer  # type: ignore
    from PySide6.QtWidgets import (  # type: ignore
        QApplication,
        QAbstractItemView,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QSplitter,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except Exception:  # pragma: no cover
    QApplication = None  # type: ignore
    QTimer = None  # type: ignore
    QAbstractItemView = None  # type: ignore
    QHBoxLayout = None  # type: ignore
    QLabel = None  # type: ignore
    QPushButton = None  # type: ignore
    QSplitter = None  # type: ignore
    QTableWidget = None  # type: ignore
    QTableWidgetItem = None  # type: ignore
    QVBoxLayout = None  # type: ignore
    QWidget = None  # type: ignore

_ARENA_COLUMNS = ["arena_id", "status", "episode_id", "generation", "model_count", "retail_count", "symbols"]
_RANK_COLUMNS = ["rank", "agent_id", "model_id", "score", "equity_return", "reward_total"]


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


class _HeadlessLayout:
    def __init__(self, *_, **__):
        pass

    def addWidget(self, *_):
        pass

    def addLayout(self, *_):
        pass


class _HeadlessSplitter:
    def __init__(self, *_, **__):
        self._widgets = []

    def addWidget(self, widget):
        self._widgets.append(widget)


class _HeadlessButton:
    def __init__(self, text=""):
        self._text = text
        self._enabled = True
        self.clicked = _Sig()

    def setEnabled(self, enabled):
        self._enabled = bool(enabled)

    def setObjectName(self, _name):
        pass


class _HeadlessLabel:
    def __init__(self, text=""):
        self._text = text

    def setText(self, text):
        self._text = str(text)

    def text(self):
        return self._text


class _HeadlessTable:
    def __init__(self, *_, **__):
        self._rows = []
        self._headers = []
        self.cellClicked = _Sig()

    def setColumnCount(self, count):
        self._column_count = count

    def setHorizontalHeaderLabels(self, labels):
        self._headers = list(labels)

    def setSelectionBehavior(self, *_):
        pass

    def rowCount(self):
        return len(self._rows)

    def insertRow(self, row):
        cols = getattr(self, "_column_count", len(self._headers) or 1)
        self._rows.insert(row, [None] * cols)

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


class _HeadlessItem:
    def __init__(self, text=""):
        self._text = str(text)

    def text(self):
        return self._text


def _has_qt_app() -> bool:
    try:
        return QApplication is not None and QApplication.instance() is not None
    except Exception:
        return False


class ArenaPanelAdapter(PanelAdapter):
    def __init__(self):
        super().__init__()
        self._root: Any = None
        self._arena_table: Any = None
        self._rank_table: Any = None
        self._status_label: Any = None
        self._create_btn: Any = None
        self._start_btn: Any = None
        self._stop_btn: Any = None
        self._eval_btn: Any = None
        self._item_cls: Any = _HeadlessItem
        self._arena_rows: list[dict[str, Any]] = []

    def set_logic(self, logic: Any):
        self.bind(logic)
        return self

    def _create_widget(self):
        if _has_qt_app():
            root = QWidget()  # type: ignore
            vbox = QVBoxLayout  # type: ignore
            hbox = QHBoxLayout  # type: ignore
            label = QLabel  # type: ignore
            button = QPushButton  # type: ignore
            table = QTableWidget  # type: ignore
            item = QTableWidgetItem  # type: ignore
            splitter = QSplitter  # type: ignore
        else:
            root = _HeadlessWidget()
            vbox = _HeadlessLayout
            hbox = _HeadlessLayout
            label = _HeadlessLabel
            button = _HeadlessButton
            table = _HeadlessTable
            item = _HeadlessItem
            splitter = _HeadlessSplitter

        self._item_cls = item
        try:
            layout = vbox(root)
            toolbar = hbox()
            self._create_btn = button("Create Arena")
            self._start_btn = button("Start")
            self._stop_btn = button("Stop")
            self._eval_btn = button("Evaluate")
            for name, btn in [
                ("primaryAction", self._create_btn),
                ("primaryAction", self._start_btn),
                ("secondaryAction", self._stop_btn),
                ("secondaryAction", self._eval_btn),
            ]:
                try:
                    btn.setObjectName(name)
                except Exception:
                    pass
                toolbar.addWidget(btn)
            self._status_label = label("Arena: idle")
            toolbar.addWidget(self._status_label)
            layout.addLayout(toolbar)

            body = splitter()
            self._arena_table = table(0, len(_ARENA_COLUMNS))
            self._arena_table.setColumnCount(len(_ARENA_COLUMNS))
            self._arena_table.setHorizontalHeaderLabels(_ARENA_COLUMNS)
            self._rank_table = table(0, len(_RANK_COLUMNS))
            self._rank_table.setColumnCount(len(_RANK_COLUMNS))
            self._rank_table.setHorizontalHeaderLabels(_RANK_COLUMNS)
            if QAbstractItemView is not None:
                try:
                    self._arena_table.setSelectionBehavior(QAbstractItemView.SelectRows)
                    self._rank_table.setSelectionBehavior(QAbstractItemView.SelectRows)
                except Exception:
                    pass
            body.addWidget(self._arena_table)
            body.addWidget(self._rank_table)
            layout.addWidget(body)

            self._wire_buttons()
        except Exception:
            pass
        self._root = root
        return root

    def refresh(self):
        if QTimer is not None and _has_qt_app():
            try:
                QTimer.singleShot(0, lambda: super(ArenaPanelAdapter, self).refresh())
                return
            except Exception:
                pass
        super().refresh()

    def _apply_view(self, view: dict[str, Any]):
        arena_block = view.get("arena") or {}
        self._arena_rows = list(arena_block.get("items") or [])
        self._fill_table(self._arena_table, _ARENA_COLUMNS, self._arena_rows)
        self._fill_table(self._rank_table, _RANK_COLUMNS, list(view.get("leaderboard") or []))
        self._apply_controls(view.get("controls") or {})
        self._apply_status(view)

    def _wire_buttons(self):
        for button, handler in [
            (self._create_btn, self._on_create),
            (self._start_btn, self._on_start),
            (self._stop_btn, self._on_stop),
            (self._eval_btn, self._on_evaluate),
        ]:
            try:
                button.clicked.connect(handler)
            except Exception:
                pass
        try:
            self._arena_table.cellClicked.connect(self._on_arena_clicked)
        except Exception:
            pass

    def _fill_table(self, table: Any, columns: list[str], rows: list[dict[str, Any]]):
        if table is None:
            return
        try:
            existing = getattr(table, "rowCount", lambda: 0)()
            for row in reversed(range(existing)):
                table.removeRow(row)
            for row_index, row in enumerate(rows):
                table.insertRow(row_index)
                for col_index, col in enumerate(columns):
                    value = row.get(col)
                    if isinstance(value, list):
                        value = ", ".join(str(item) for item in value)
                    table.setItem(row_index, col_index, self._item_cls(_format_value(value)))
            if rows:
                table.setCurrentCell(0, 0)
        except Exception:
            pass

    def _apply_controls(self, controls: dict[str, Any]):
        for key, button in [
            ("can_create", self._create_btn),
            ("can_start", self._start_btn),
            ("can_stop", self._stop_btn),
            ("can_evaluate", self._eval_btn),
        ]:
            if button is None:
                continue
            try:
                button.setEnabled(bool(controls.get(key, False)))
            except Exception:
                pass

    def _apply_status(self, view: dict[str, Any]):
        if self._status_label is None:
            return
        error = view.get("error")
        selected = view.get("selected") or {}
        if error:
            text = f"Arena error: {error}"
        elif selected:
            text = (
                f"Arena {selected.get('arena_id')} | {selected.get('status')} | "
                f"episode={selected.get('current_episode_id') or '-'}"
            )
        else:
            text = "Arena: create or select an arena"
        try:
            self._status_label.setText(text)
        except Exception:
            pass

    def _on_arena_clicked(self, row: int, *_):
        if self._logic is None:
            return
        try:
            item = self._arena_rows[row]
            arena_id = item.get("arena_id")
            if arena_id:
                self._logic.select_arena(arena_id)
                self.refresh()
        except Exception:
            pass

    def _on_create(self):
        self._call_logic("create_arena")

    def _on_start(self):
        self._call_logic("start_arena")

    def _on_stop(self):
        self._call_logic("stop_arena")

    def _on_evaluate(self):
        self._call_logic("evaluate_arena")

    def _call_logic(self, method_name: str):
        if self._logic is None:
            return
        fn = getattr(self._logic, method_name, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
        self.refresh()


def _format_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


__all__ = ["ArenaPanelAdapter"]
