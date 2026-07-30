"""Arena panel adapter."""
from __future__ import annotations

import threading
from typing import Any

from .base_adapter import PanelAdapter
from app.ui.widgets.mini_charts import HeadlessModelEquityChartWidget, ModelEquityChartWidget

try:
    from PySide6.QtCore import QObject, Signal, Slot, QTimer  # type: ignore
    from PySide6.QtWidgets import (  # type: ignore
        QApplication,
        QAbstractItemView,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QLineEdit,
        QSplitter,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except Exception:  # pragma: no cover
    QApplication = None  # type: ignore
    QObject = None  # type: ignore
    Signal = None  # type: ignore
    Slot = None  # type: ignore
    QTimer = None  # type: ignore
    QAbstractItemView = None  # type: ignore
    QHBoxLayout = None  # type: ignore
    QLabel = None  # type: ignore
    QPushButton = None  # type: ignore
    QLineEdit = None  # type: ignore
    QSplitter = None  # type: ignore
    QTableWidget = None  # type: ignore
    QTableWidgetItem = None  # type: ignore
    QVBoxLayout = None  # type: ignore
    QWidget = None  # type: ignore

if QObject is not None and Signal is not None and Slot is not None:  # pragma: no branch
    class _QtRefreshBridge(QObject):  # type: ignore[misc]
        refresh_requested = Signal()

        def __init__(self, callback):
            super().__init__()
            self._callback = callback
            self.refresh_requested.connect(self._run)

        @Slot()
        def _run(self):
            try:
                self._callback()
            except Exception:
                pass
else:  # pragma: no cover
    _QtRefreshBridge = None  # type: ignore

_ARENA_COLUMNS = ["arena_id", "status", "episode_id", "generation", "model_count", "retail_count", "symbols"]
_RANK_COLUMNS = [
    "rank",
    "agent_id",
    "model_id",
    "score",
    "equity_return",
    "reward_total",
    "submitted",
    "filled",
    "rejected",
    "noop",
    "rejected_reason",
]
_EVIDENCE_COLUMNS = [
    "candidate_id",
    "baseline",
    "calibration",
    "hidden",
    "exploit",
    "fee_impact_sensitivity",
    "parent_eligible",
    "research_claim_eligible",
]


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


class _HeadlessLineEdit:
    def __init__(self, text=""):
        self._text = str(text)

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
        self._state_lock = threading.RLock()
        self._busy_action: str | None = None
        self._qt_bridge: Any = None
        self._root: Any = None
        self._arena_table: Any = None
        self._rank_table: Any = None
        self._evidence_table: Any = None
        self._status_label: Any = None
        self._create_btn: Any = None
        self._start_btn: Any = None
        self._stop_btn: Any = None
        self._eval_btn: Any = None
        self._run_exp_btn: Any = None
        self._duration_input: Any = None
        self._symbols_input: Any = None
        self._prices_input: Any = None
        self._models_input: Any = None
        self._experiment_label: Any = None
        self._equity_chart: Any = None
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
            line_edit = QLineEdit  # type: ignore
            table = QTableWidget  # type: ignore
            item = QTableWidgetItem  # type: ignore
            splitter = QSplitter  # type: ignore
        else:
            root = _HeadlessWidget()
            vbox = _HeadlessLayout
            hbox = _HeadlessLayout
            label = _HeadlessLabel
            button = _HeadlessButton
            line_edit = _HeadlessLineEdit
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
            self._run_exp_btn = button("Run Experiment")
            self._ensure_qt_bridge()
            for name, btn in [
                ("primaryAction", self._create_btn),
                ("primaryAction", self._start_btn),
                ("primaryAction", self._run_exp_btn),
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

            config_bar = hbox()
            config_bar.addWidget(label("Duration(s)"))
            self._duration_input = line_edit("300")
            config_bar.addWidget(self._duration_input)
            config_bar.addWidget(label("Symbols"))
            self._symbols_input = line_edit("001,002")
            config_bar.addWidget(self._symbols_input)
            config_bar.addWidget(label("Prices"))
            self._prices_input = line_edit("20,30")
            config_bar.addWidget(self._prices_input)
            config_bar.addWidget(label("Models"))
            self._models_input = line_edit(
                "ppo_lstm_v1:MODEL_PPO_LSTM:online_train:50000000;"
                "hold_model_v1:MODEL_HOLD:collect_only:50000000"
            )
            config_bar.addWidget(self._models_input)
            layout.addLayout(config_bar)

            chart_cls = ModelEquityChartWidget if _has_qt_app() else HeadlessModelEquityChartWidget
            self._equity_chart = chart_cls()
            layout.addWidget(self._equity_chart)
            self._experiment_label = label("Experiment: idle")
            layout.addWidget(self._experiment_label)

            body = splitter()
            self._arena_table = table(0, len(_ARENA_COLUMNS))
            self._arena_table.setColumnCount(len(_ARENA_COLUMNS))
            self._arena_table.setHorizontalHeaderLabels(_ARENA_COLUMNS)
            self._rank_table = table(0, len(_RANK_COLUMNS))
            self._rank_table.setColumnCount(len(_RANK_COLUMNS))
            self._rank_table.setHorizontalHeaderLabels(_RANK_COLUMNS)
            self._evidence_table = table(0, len(_EVIDENCE_COLUMNS))
            self._evidence_table.setColumnCount(len(_EVIDENCE_COLUMNS))
            self._evidence_table.setHorizontalHeaderLabels(_EVIDENCE_COLUMNS)
            if QAbstractItemView is not None:
                try:
                    self._arena_table.setSelectionBehavior(QAbstractItemView.SelectRows)
                    self._rank_table.setSelectionBehavior(QAbstractItemView.SelectRows)
                    self._evidence_table.setSelectionBehavior(QAbstractItemView.SelectRows)
                except Exception:
                    pass
            body.addWidget(self._arena_table)
            body.addWidget(self._rank_table)
            body.addWidget(self._evidence_table)
            layout.addWidget(body)

            self._wire_buttons()
        except Exception:
            pass
        self._root = root
        return root

    def refresh(self):
        if _has_qt_app():
            self._ensure_qt_bridge()
            if self._qt_bridge is not None:
                try:
                    self._qt_bridge.refresh_requested.emit()
                    return
                except Exception:
                    pass
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
        leaderboard = list(view.get("leaderboard") or [])
        evidence_rows = list(((view.get("experiment") or {}).get("evidence_board") or {}).get("rows") or [])
        self._fill_table(self._arena_table, _ARENA_COLUMNS, self._arena_rows)
        self._fill_table(self._rank_table, _RANK_COLUMNS, leaderboard)
        self._fill_table(self._evidence_table, _EVIDENCE_COLUMNS, evidence_rows)
        if self._equity_chart is not None:
            try:
                self._equity_chart.set_data(leaderboard, selected=view.get("selected") or {})
            except Exception:
                pass
        controls = dict(view.get("controls") or {})
        with self._state_lock:
            busy = self._busy_action is not None
        if busy:
            for key in ("can_create", "can_start", "can_stop", "can_evaluate", "can_run_experiment"):
                controls[key] = False
        self._apply_controls(controls)
        self._apply_status(view)

    def _wire_buttons(self):
        for button, handler in [
            (self._create_btn, self._on_create),
            (self._start_btn, self._on_start),
            (self._stop_btn, self._on_stop),
            (self._eval_btn, self._on_evaluate),
            (self._run_exp_btn, self._on_run_experiment),
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
            ("can_run_experiment", self._run_exp_btn),
        ]:
            if button is None:
                continue
            enabled = bool(controls.get(key, False))
            try:
                button.setEnabled(enabled)
                setattr(button, "_enabled", enabled)
            except Exception:
                pass

    def _apply_status(self, view: dict[str, Any]):
        if self._status_label is None:
            return
        error = view.get("error")
        selected = view.get("selected") or {}
        if error:
            text = f"Arena error: {error}"
        elif self._current_busy_action():
            text = f"Arena: {self._current_busy_action()} running..."
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
        self._apply_experiment_status(view)

    def _apply_experiment_status(self, view: dict[str, Any]):
        if self._experiment_label is None:
            return
        exp = view.get("experiment") or {}
        if exp.get("running"):
            text = "Experiment: running"
        elif exp.get("report_path"):
            text = (
                f"Experiment: {exp.get('episode_id') or '-'} | "
                f"transitions={exp.get('transition_count', 0)} | "
                f"results={exp.get('result_count', 0)} | "
                f"checkpoints={exp.get('pbt_checkpoint_count', 0)} | "
                f"lineage={exp.get('pbt_lineage_count', 0)}"
            )
        elif exp.get("available"):
            text = "Experiment: ready"
        else:
            text = "Experiment: unavailable"
        try:
            self._experiment_label.setText(text)
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

    def _on_run_experiment(self):
        if self._logic is None:
            return
        fn = getattr(self._logic, "run_experiment", None)
        if not callable(fn):
            return
        kwargs = self._experiment_kwargs()
        if _has_qt_app():
            self._call_logic_async("run_experiment", lambda: fn(**kwargs))
            return
        try:
            fn(**kwargs)
        except Exception:
            pass
        self.refresh()

    def _experiment_kwargs(self) -> dict[str, Any]:
        return {
            "duration_seconds": _float_from_edit(self._duration_input, 300.0),
            "symbols": _split_csv(_text_from_edit(self._symbols_input)) or ["001", "002"],
            "instrument_prices": _split_floats(_text_from_edit(self._prices_input)),
            "model_specs": _parse_model_specs(_text_from_edit(self._models_input)),
            "run_pbt": False,
        }

    def _call_logic(self, method_name: str):
        if self._logic is None:
            return
        fn = getattr(self._logic, method_name, None)
        if not callable(fn):
            return
        if _has_qt_app() and method_name in {"start_arena", "stop_arena", "evaluate_arena", "run_experiment"}:
            self._call_logic_async(method_name, fn)
            return
        try:
            fn()
        except Exception:
            pass
        self.refresh()

    def _call_logic_async(self, method_name: str, fn: Any) -> None:
        if not self._begin_busy(method_name):
            self.refresh()
            return

        def _work():
            try:
                fn()
            except Exception:
                pass
            finally:
                self._end_busy()
                self.refresh()

        try:
            threading.Thread(target=_work, name=f"ArenaPanel-{method_name}", daemon=True).start()
        except Exception:
            try:
                fn()
            except Exception:
                pass
            finally:
                self._end_busy()
        self.refresh()

    def _begin_busy(self, method_name: str) -> bool:
        with self._state_lock:
            if self._busy_action is not None:
                return False
            self._busy_action = _action_label(method_name)
            return True

    def _end_busy(self) -> None:
        with self._state_lock:
            self._busy_action = None

    def _current_busy_action(self) -> str | None:
        with self._state_lock:
            return self._busy_action

    def _ensure_qt_bridge(self) -> None:
        if self._qt_bridge is not None or _QtRefreshBridge is None or not _has_qt_app():
            return
        try:
            self._qt_bridge = _QtRefreshBridge(lambda: super(ArenaPanelAdapter, self).refresh())
        except Exception:
            self._qt_bridge = None


def _format_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _text_from_edit(widget: Any) -> str:
    if widget is None:
        return ""
    try:
        return str(widget.text())
    except Exception:
        return ""


def _float_from_edit(widget: Any, default: float) -> float:
    try:
        return float(_text_from_edit(widget).strip())
    except Exception:
        return float(default)


def _split_csv(text: str) -> list[str]:
    return [item.strip() for item in str(text or "").split(",") if item.strip()]


def _split_floats(text: str) -> list[float]:
    out: list[float] = []
    for item in _split_csv(text):
        try:
            out.append(float(item))
        except Exception:
            pass
    return out


def _parse_model_specs(text: str) -> list[dict[str, Any]] | None:
    specs: list[dict[str, Any]] = []
    for raw in str(text or "").split(";"):
        parts = [part.strip() for part in raw.split(":")]
        if not parts or not parts[0]:
            continue
        spec: dict[str, Any] = {"model_id": parts[0]}
        if len(parts) > 1 and parts[1]:
            spec["agent_id"] = parts[1]
        if len(parts) > 2 and parts[2]:
            spec["mode"] = parts[2]
        if len(parts) > 3 and parts[3]:
            try:
                spec["initial_cash"] = float(parts[3])
            except Exception:
                pass
        specs.append(spec)
    return specs or None


def _action_label(method_name: str) -> str:
    return {
        "start_arena": "Start",
        "stop_arena": "Stop",
        "evaluate_arena": "Evaluate",
        "run_experiment": "Experiment",
    }.get(method_name, method_name)


__all__ = ["ArenaPanelAdapter"]
