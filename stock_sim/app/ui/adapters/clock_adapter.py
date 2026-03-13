"""ClockPanelAdapter (R5,R15 UI 部分)

功能:
- 控制按钮: Start / Pause / Resume / Stop
- 速度调节: QDoubleSpinBox (playback speed)
- Checkpoint: 列表(QTableWidget) + Create 按钮 + Rollback 按钮
- Rollback 执行期间禁用 Rollback 按钮与 Create 按钮
- refresh(): 从 logic.get_view() 取 state + checkpoints 刷新表格

限制:
- 未实现 sim_day 输入切换, 可后续扩展 (switch_sim_day)
- 回滚与创建操作同步执行 (逻辑侧预期快速); 若未来耗时需线程化
"""
from __future__ import annotations
from typing import Any, Dict, Optional, List
import threading

from .base_adapter import PanelAdapter

try:
    from PySide6.QtWidgets import (  # type: ignore
        QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QDoubleSpinBox,
        QTableWidget, QTableWidgetItem, QLineEdit
    )
except Exception:  # pragma: no cover
    QWidget = object  # type: ignore
    class QVBoxLayout:  # type: ignore
        def __init__(self,*_,**__): pass
        def addWidget(self,*_): pass
        def addLayout(self,*_): pass
    class QHBoxLayout:  # type: ignore
        def __init__(self,*_,**__): pass
        def addWidget(self,*_): pass
    class QPushButton:  # type: ignore
        def __init__(self,text=""): self._text=text; self._enabled=True; self.clicked=_Sig()
        def setEnabled(self,v): self._enabled=v
    class QLabel:  # type: ignore
        def __init__(self,text=""): self._text=text
        def setText(self,t): self._text=t
    class QDoubleSpinBox:  # type: ignore
        def __init__(self): self._v=1.0; self.valueChanged=_Sig()
        def setRange(self,a,b): pass
        def setDecimals(self,n): pass
        def setValue(self,v): self._v=v; self.valueChanged.emit(v)
        def value(self): return self._v
    class QTableWidget:  # type: ignore
        def __init__(self,*_,**__): self._rows=[]
        def setColumnCount(self,n): pass
        def setHorizontalHeaderLabels(self,l): pass
        def rowCount(self): return len(self._rows)
        def insertRow(self,r): self._rows.insert(r,[None]*5)
        def removeRow(self,r): self._rows.pop(r)
        def setItem(self,r,c,item): self._rows[r][c]=item
        def item(self,r,c):
            try: return self._rows[r][c]
            except Exception: return None
        def currentRow(self): return 0
        def setCurrentCell(self,*_): pass
    class QTableWidgetItem:  # type: ignore
        def __init__(self,text=""): self._text=text
        def text(self): return self._text
        def setText(self,t): self._text=t
    class QLineEdit:  # type: ignore
        def __init__(self): self._text=""
        def text(self): return self._text
        def setPlaceholderText(self,*_): pass
    class _Sig:  # type: ignore
        def __init__(self): self._f=[]
        def connect(self,f): self._f.append(f)
        def emit(self,*a):
            for fn in list(self._f):
                try: fn(*a)
                except Exception: pass

_COLUMNS = ["id", "label", "sim_day", "created_ms", "is_current"]

class ClockPanelAdapter(PanelAdapter):
    def __init__(self):
        super().__init__()
        self._root: Optional[Any] = None
        self._btn_start: Optional[Any] = None
        self._btn_pause: Optional[Any] = None
        self._btn_resume: Optional[Any] = None
        self._btn_stop: Optional[Any] = None
        self._btn_create_cp: Optional[Any] = None
        self._btn_rollback: Optional[Any] = None
        self._table: Optional[Any] = None
        self._speed_spin: Optional[Any] = None
        self._status_label: Optional[Any] = None
        self._cp_label_input: Optional[Any] = None
        self._current_checkpoint: Optional[str] = None
        self._rollback_lock = threading.Lock()

    def _create_widget(self):  # noqa: D401
        root = QWidget()  # type: ignore
        try:
            v = QVBoxLayout(root)  # type: ignore
            # Control row
            ctrl = QHBoxLayout()  # type: ignore
            self._btn_start = QPushButton("Start")  # type: ignore
            self._btn_pause = QPushButton("Pause")  # type: ignore
            self._btn_resume = QPushButton("Resume")  # type: ignore
            self._btn_stop = QPushButton("Stop")  # type: ignore
            for b, act in ((self._btn_start,'start'),(self._btn_pause,'pause'),(self._btn_resume,'resume'),(self._btn_stop,'stop')):
                try: b.clicked.connect(self._make_control_handler(act))  # type: ignore[attr-defined]
                except Exception: pass
                ctrl.addWidget(b)  # type: ignore
            # speed
            self._speed_spin = QDoubleSpinBox()  # type: ignore
            try:
                self._speed_spin.setRange(0.1, 100.0)  # type: ignore
                self._speed_spin.setDecimals(2)  # type: ignore
                self._speed_spin.setValue(1.0)  # type: ignore
                self._speed_spin.valueChanged.connect(self._on_speed_change)  # type: ignore[attr-defined]
            except Exception: pass
            ctrl.addWidget(self._speed_spin)  # type: ignore
            self._status_label = QLabel("state: -")  # type: ignore
            ctrl.addWidget(self._status_label)  # type: ignore
            v.addLayout(ctrl)  # type: ignore
            # checkpoint row
            cp_row = QHBoxLayout()  # type: ignore
            self._cp_label_input = QLineEdit()  # type: ignore
            try: self._cp_label_input.setPlaceholderText("checkpoint label")  # type: ignore
            except Exception: pass
            self._btn_create_cp = QPushButton("Create CP")  # type: ignore
            self._btn_rollback = QPushButton("Rollback")  # type: ignore
            try:
                self._btn_create_cp.clicked.connect(self._create_checkpoint)  # type: ignore[attr-defined]
                self._btn_rollback.clicked.connect(self._do_rollback)  # type: ignore[attr-defined]
            except Exception: pass
            for w in (self._cp_label_input, self._btn_create_cp, self._btn_rollback):
                cp_row.addWidget(w)  # type: ignore
            v.addLayout(cp_row)  # type: ignore
            # table
            self._table = QTableWidget(0, len(_COLUMNS))  # type: ignore
            try:
                self._table.setColumnCount(len(_COLUMNS))  # type: ignore
                self._table.setHorizontalHeaderLabels(_COLUMNS)  # type: ignore
            except Exception: pass
            v.addWidget(self._table)  # type: ignore
        except Exception:  # pragma: no cover
            pass
        self._root = root
        return root

    # ---------- Event Handlers ----------
    def _make_control_handler(self, action: str):
        def _h():
            if self._logic is None:
                return
            fn = getattr(self._logic, action, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass
                self.refresh()
        return _h

    def _on_speed_change(self, value: float):  # noqa: D401
        if self._logic is None:
            return
        set_speed = getattr(self._logic, 'set_speed', None)
        if callable(set_speed):
            try:
                set_speed(value)
            except Exception:
                pass
            self.refresh()

    def _create_checkpoint(self):
        if self._logic is None or self._btn_create_cp is None:
            return
        label = ""
        if self._cp_label_input is not None:
            try: label = self._cp_label_input.text()  # type: ignore
            except Exception: label = ""
        fn = getattr(self._logic, 'create_checkpoint', None)
        if callable(fn):
            try:
                fn(label or "cp")
            except Exception:
                pass
            self.refresh()

    def _do_rollback(self):
        if self._logic is None or self._btn_rollback is None:
            return
        if not self._try_lock():
            return
        cp_id = self._current_checkpoint
        if not cp_id:
            self._unlock()
            return
        rb = getattr(self._logic, 'rollback', None)
        if callable(rb):
            try:
                # 禁用按钮
                self._set_actions_enabled(False)
                rb(cp_id)
            except Exception:
                pass
            finally:
                self._set_actions_enabled(True)
                self._unlock()
                self.refresh()

    # ---------- Lock helpers ----------
    def _try_lock(self) -> bool:
        ok = self._rollback_lock.acquire(blocking=False)
        if ok and self._btn_rollback is not None:
            try: self._btn_rollback.setEnabled(False)  # type: ignore
            except Exception: pass
        return ok

    def _unlock(self):
        if self._rollback_lock.locked():
            self._rollback_lock.release()
        if self._btn_rollback is not None:
            try: self._btn_rollback.setEnabled(True)  # type: ignore
            except Exception: pass

    def _set_actions_enabled(self, enabled: bool):
        for b in (self._btn_create_cp, self._btn_rollback):
            if b is None: continue
            try: b.setEnabled(enabled)  # type: ignore
            except Exception: pass

    # ---------- Apply View ----------
    def _apply_view(self, view: Dict[str, Any]):
        state = view.get('state') if isinstance(view, dict) else None
        checkpoints = view.get('checkpoints') if isinstance(view, dict) else []
        current = view.get('current_checkpoint') if isinstance(view, dict) else None
        if isinstance(state, dict) and self._status_label is not None:
            try:
                self._status_label.setText(f"state: {state.get('status')} day={state.get('sim_day')} speed={state.get('speed')}")  # type: ignore
            except Exception: pass
            if self._speed_spin is not None:
                # 若外部修改 speed, 与 spin 不同步则更新
                try:
                    cur_speed = self._speed_spin.value()  # type: ignore
                    new_speed = state.get('speed')
                    if isinstance(new_speed, (int,float)) and abs(cur_speed - float(new_speed)) > 1e-6:
                        self._speed_spin.setValue(float(new_speed))  # type: ignore
                except Exception: pass
        self._current_checkpoint = current if isinstance(current, str) else None
        self._refresh_checkpoint_table(checkpoints, current)
        # rollback 按钮可用性: 需有 current checkpoint
        if self._btn_rollback is not None:
            try: self._btn_rollback.setEnabled(bool(self._current_checkpoint) and not self._rollback_lock.locked())  # type: ignore
            except Exception: pass

    def _refresh_checkpoint_table(self, checkpoints: Any, current: Any):
        if self._table is None or not isinstance(checkpoints, list):
            return
        try:
            # 全量重建 (后续可 diff)
            existing = self._table.rowCount()  # type: ignore
            for r in reversed(range(existing)):
                try: self._table.removeRow(r)  # type: ignore
                except Exception: pass
            for i, cp in enumerate(checkpoints):
                if not isinstance(cp, dict):
                    continue
                try: self._table.insertRow(i)  # type: ignore
                except Exception: continue
                for col_i, col_key in enumerate(_COLUMNS):
                    val = cp.get(col_key)
                    try:
                        item = QTableWidgetItem(str(val))  # type: ignore
                        self._table.setItem(i, col_i, item)  # type: ignore
                    except Exception: pass
            # 选中 current 行
            if current:
                for i, cp in enumerate(checkpoints):
                    if isinstance(cp, dict) and cp.get('id') == current:
                        try: self._table.setCurrentCell(i, 0)  # type: ignore
                        except Exception: pass
                        break
        except Exception:  # pragma: no cover
            pass

__all__ = ["ClockPanelAdapter"]

