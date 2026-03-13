"""AgentsPanelAdapter (R3,R17,R18 UI 部分)

功能:
- 表格显示智能体: id, name, type, status, heartbeat_stale 标记
- 选中行下方显示控制按钮: Start / Pause / Stop
- 右侧嵌入日志 tail 视图 (与 LogsViewer 配合)
- 批量创建进度显示 (简单标签)

刷新策略:
- refresh() 调用逻辑 panel.get_view()
- 按 agent_id 进行行 diff 更新 (最小 repaint)
- heartbeat_stale=True 行浅红背景

限制:
- 不实现分页 (逻辑层返��已分页数据)
- 不做异步线程; 所有操作即时调用逻辑层 (Service 内部线程安全)
"""
from __future__ import annotations
from typing import Any, Dict, Optional, List
from .base_adapter import PanelAdapter

# 新增: 事件与节流/线程
import threading
import time
from infra.event_bus import event_bus
try:
    from app.utils.throttle import Throttle  # 优先 app 命名空间
except Exception:  # pragma: no cover
    # 最小后备实现：立即执行 submit；flush_pending 支持 force
    class Throttle:  # type: ignore
        def __init__(self, interval_ms, fn, *, metrics_prefix: str = "throttle"):
            self.fn = fn
        def submit(self, *a, **kw):
            try:
                self.fn(*a, **kw)
            except Exception:
                pass
        def flush_pending(self, *, force: bool = False):
            return False
        @property
        def has_pending(self):
            return False

# 新增: 事件订阅帮助方法（可取消）
try:
    from app.event_bridge import (
        on_agent_status_changed,
        subscribe_topic,
    )
except Exception:  # pragma: no cover
    def on_agent_status_changed(h, **kwargs):  # type: ignore
        event_bus.subscribe("agent-status-changed", h, async_mode=kwargs.get('async_mode', False))
        return lambda: event_bus.unsubscribe("agent-status-changed", h)
    def subscribe_topic(topic, h, **kwargs):  # type: ignore
        event_bus.subscribe(topic, h, async_mode=kwargs.get('async_mode', False))
        return lambda: event_bus.unsubscribe(topic, h)

try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
        QPushButton, QLabel, QListWidget, QListWidgetItem, QTextEdit,
        QDialog, QLineEdit, QComboBox
    )  # type: ignore
    from PySide6.QtGui import QColor  # type: ignore
except Exception:  # pragma: no cover - headless fallback
    QWidget = object  # type: ignore
    class QVBoxLayout:  # type: ignore
        def __init__(self, *_, **__): pass
        def addWidget(self, *_): pass
        def addLayout(self, *_): pass
    class QHBoxLayout:  # type: ignore
        def __init__(self, *_, **__): pass
        def addWidget(self, *_): pass
    class QTableWidget:  # type: ignore
        def __init__(self, *_, **__): self._rows=[]
        def setColumnCount(self, n): pass
        def setHorizontalHeaderLabels(self, labels): pass
        def rowCount(self): return len(self._rows)
        def insertRow(self, r): self._rows.insert(r, [None]*5)
        def removeRow(self, r): self._rows.pop(r)
        def setItem(self, r,c,item): self._rows[r][c]=item
        def item(self, r,c):
            try: return self._rows[r][c]
            except Exception: return None
        def setCurrentCell(self, *_): pass
        def currentRow(self): return 0
    class QTableWidgetItem:  # type: ignore
        def __init__(self, text=""): self._text=text
        def setText(self,t): self._text=t
        def text(self): return self._text
        def setBackground(self, *_): pass
    class QPushButton:  # type: ignore
        def __init__(self, text=""): self._text=text; self.clicked=_DummySig()
    class QLabel:  # type: ignore
        def __init__(self, text=""): self._text=text
        def setText(self,t): self._text=t
    class QTextEdit:  # type: ignore
        def __init__(self): self._content=""
        def setReadOnly(self, *_): pass
        def setPlainText(self, t): self._content=t
    class _DummySig:  # type: ignore
        def connect(self, *_): pass
    class QDialog:  # type: ignore
        def __init__(self, *a, **k): pass
        def exec(self): return 0
    class QLineEdit:  # type: ignore
        def __init__(self, text=""): self._text=text
        def text(self): return self._text
        def setText(self, t): self._text=t
    class QComboBox:  # type: ignore
        def __init__(self): self._items=["Retail","MultiStrategyRetail"]; self._idx=0
        def addItems(self, items): self._items=list(items)
        def currentText(self): return self._items[self._idx] if self._items else "Retail"
    QColor = lambda *a, **k: None  # type: ignore

_ROW_COLOR_STALE = QColor(255, 240, 240) if callable(getattr(QColor, '__call__', None)) else QColor(255, 240, 240)  # type: ignore

# 新增: 相关事件主题（部分来自控制器，部分预留占位）
_AGENT_PROGRESS_TOPIC = "agent.batch.create.progress"
_AGENT_COMPLETED_TOPIC = "agent.batch.create.completed"
_AGENT_STATUS_CHANGED = "agent-status-changed"  # 预留：若后端发布状态事件，将自动接入

class AgentsPanelAdapter(PanelAdapter):
    COLS = ["agent_id", "name", "type", "status", "params_version", "heartbeat_stale"]

    def __init__(self):
        super().__init__()
        self._table: Optional[Any] = None
        self._root: Optional[Any] = None
        self._row_index: Dict[str, int] = {}
        self._selected_agent: Optional[str] = None
        self._btn_start: Optional[Any] = None
        self._btn_pause: Optional[Any] = None
        self._btn_stop: Optional[Any] = None
        # 新增：批量创建按钮
        self._btn_batch: Optional[Any] = None
        self._progress_label: Optional[Any] = None
        self._log_view: Optional[Any] = None
        # 事件/轮询状态
        self._started = False
        self._lock = threading.RLock()
        self._stop_evt = threading.Event()
        self._poll_thread: Optional[threading.Thread] = None
        self._flush_thread: Optional[threading.Thread] = None
        self._last_event_ts = 0.0
        self._poll_backoff_s = 2.0  # 初始 2s
        self._poll_backoff_max_s = 16.0
        # 刷新节流: 200ms 内最多一次
        self._refresh_throttle = Throttle(200, self._do_refresh, metrics_prefix="agents_adapter_refresh")
        # 新增: 取消订阅函数集合
        self._cancel_subs: List[callable] = []

    # ---------- PanelAdapter overrides ----------
        # PyTest 环境：直接执行，保证测试无需事件循环即可观察到 UI 状态变化
        # try:
        #     import os
        #     if os.environ.get('PYTEST_CURRENT_TEST'):
        #         try:
        #             fn()
        #             return
        #         except Exception:
        #             pass
        # except Exception:
        #     pass
    def _create_widget(self):
        root = QWidget()  # type: ignore
        try:
            main_v = QVBoxLayout(root)  # type: ignore
            self._table = QTableWidget(0, len(self.COLS))  # type: ignore
            self._table.setColumnCount(len(self.COLS))  # type: ignore
            self._table.setHorizontalHeaderLabels(self.COLS)  # type: ignore
            main_v.addWidget(self._table)  # type: ignore
            # 控制区
            ctrl_h = QHBoxLayout()  # type: ignore
            self._btn_start = QPushButton("Start")  # type: ignore
            self._btn_pause = QPushButton("Pause")  # type: ignore
            self._btn_stop = QPushButton("Stop")  # type: ignore
            # 新增：批量创建按钮
            self._btn_batch = QPushButton("Batch Create…")  # type: ignore
            for b, act in ((self._btn_start, 'start'), (self._btn_pause, 'pause'), (self._btn_stop, 'stop')):
                if b is not None:
                    def _make_handler(a):
                        def _h():
                            self._do_control(a)
                        return _h
                    try:
                        b.clicked.connect(_make_handler(act))  # type: ignore[attr-defined]
                    except Exception:  # pragma: no cover
                        pass
                    ctrl_h.addWidget(b)  # type: ignore
            # 绑定批量创建点击
            try:
                def _on_batch():
                    getattr(self, '_open_batch_dialog', lambda: None)()
                self._btn_batch.clicked.connect(_on_batch)  # type: ignore[attr-defined]
            except Exception:
                pass
            ctrl_h.addWidget(self._btn_batch)  # type: ignore
            self._progress_label = QLabel("batch: idle")  # type: ignore
            ctrl_h.addWidget(self._progress_label)  # type: ignore
            main_v.addLayout(ctrl_h)  # type: ignore
            # 日志视图
            self._log_view = QTextEdit()  # type: ignore
            try:
                self._log_view.setReadOnly(True)  # type: ignore
            except Exception:  # pragma: no cover
                pass
            main_v.addWidget(self._log_view)  # type: ignore
        except Exception:  # pragma: no cover
            pass
        self._root = root
        # 启动事件订阅与兜底轮询
        self._ensure_started()
        return root

    # 新增：统一的 UI 线程投递方法（无 Qt 环境下返回 False）
    def _post_to_ui(self, cb) -> bool:
        try:
            from PySide6.QtCore import QTimer  # type: ignore
            # 若已有根部件，则将回调排入其所属线程；否则退化为全局 singleShot
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

    # 重写 refresh：确保所有刷新在 UI 主线程执行（测试/无 Qt 时直接调用基类）
    def refresh(self):  # type: ignore[override]
        def _do():
            try:
                PanelAdapter.refresh(self)
            except Exception:
                pass
        if not self._post_to_ui(_do):
            _do()

    def _apply_view(self, view: Dict[str, Any]):
        agents_block = view.get('agents', {}) if isinstance(view, dict) else {}
        items = agents_block.get('items', []) if isinstance(agents_block, dict) else []
        batch = view.get('batch', {}) if isinstance(view, dict) else {}
        self._update_progress(batch)
        # Diff 行
        self._sync_rows(items)
        self._refresh_log_tail()

    # ---------- Public lifecycle ----------
    def stop(self):
        """停止后台线程与事件订阅（用于窗口关闭/测试清理）。"""
        with self._lock:
            if not self._started:
                return
            self._started = False
        try:
            self._stop_evt.set()
            th, fh = self._poll_thread, self._flush_thread
            if th and th.is_alive():
                th.join(timeout=1.0)
            if fh and fh.is_alive():
                fh.join(timeout=1.0)
        except Exception:  # pragma: no cover
            pass
        # 取消订阅，���免内存泄漏
        for cancel in list(self._cancel_subs):
            try:
                cancel()
            except Exception:
                pass
        self._cancel_subs.clear()

    def __del__(self):  # 防泄漏
        try:
            self.stop()
        except Exception:
            pass

    # ---------- Internal (events/polling) ----------
    def _ensure_started(self):
        with self._lock:
            if self._started:
                return
            self._started = True
        # 订阅事件（同步通道，确保 <500ms 可见），保存取消函数
        try:
            self._cancel_subs.append(subscribe_topic(_AGENT_PROGRESS_TOPIC, self._on_agent_event, async_mode=False))
            self._cancel_subs.append(subscribe_topic(_AGENT_COMPLETED_TOPIC, self._on_agent_event, async_mode=False))
            self._cancel_subs.append(on_agent_status_changed(self._on_agent_event, async_mode=False))
        except Exception:  # pragma: no cover
            pass
        # 启动轮询线程（指数退避）
        self._stop_evt.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, name="AgentsAdapter-Poll", daemon=True)
        self._poll_thread.start()
        # 启动节流 flush 线程，确保尾部执行
        self._flush_thread = threading.Thread(target=self._flush_loop, name="AgentsAdapter-Flush", daemon=True)
        self._flush_thread.start()

    def _on_agent_event(self, _topic: str, _payload: Dict[str, Any]):
        # 记录事件时间并触发节流刷新
        self._last_event_ts = time.time()
        self._poll_backoff_s = 2.0  # 重置退避
        self._refresh_throttle.submit()

    def _poll_loop(self):
        backoff = self._poll_backoff_s
        while not self._stop_evt.wait(backoff):
            # 若近期收到事件，则保持最小退避；否则指数退避
            now = time.time()
            if now - self._last_event_ts <= 1.0:  # 1s 内有事件
                backoff = 2.0
            else:
                backoff = min(max(2.0, backoff * 2), self._poll_backoff_max_s)
            # 发起一次刷新（节流控制实际执行）
            self._refresh_throttle.submit()
        # 退出前尽量 flush 一次
        try:
            self._refresh_throttle.flush_pending(force=True)
        except Exception:
            pass

    def _flush_loop(self):
        # 定期 flush 节流尾部，避免最后一次事件后 pending 长时间不执行
        interval = 0.1  # 100ms 检查一次，保证<=200ms 尾部延迟
        while not self._stop_evt.wait(interval):
            try:
                self._refresh_throttle.flush_pending()
            except Exception:  # pragma: no cover
                pass

    def _do_refresh(self):
        # 新增: 记录事件到刷新执行的延迟 (ms)
        try:
            if self._last_event_ts:
                dt_ms = (time.time() - float(self._last_event_ts)) * 1000.0
                if dt_ms >= 0:
                    from observability.metrics import metrics  # 低开销内联导入
                    metrics.add_timing("ui_refresh_latency_ms", dt_ms)
        except Exception:
            pass
        # 关键：通过覆盖后的 refresh() 将刷新投递到 UI 线程
        try:
            self.refresh()
        except Exception:  # pragma: no cover
            pass

    # ---------- Internal ----------
    def _sync_rows(self, items: List[Dict[str, Any]]):
        table = self._table
        if table is None:
            return
        new_ids = [it.get('agent_id') for it in items if it.get('agent_id')]
        # 移除不存在
        removed = [aid for aid in list(self._row_index.keys()) if aid not in new_ids]
        for aid in sorted(removed, key=lambda a: self._row_index[a], reverse=True):
            idx = self._row_index.pop(aid)
            try: table.removeRow(idx)  # type: ignore
            except Exception: pass
        if removed:
            self._reindex()
        # 更新/新增
        for it in items:
            aid = it.get('agent_id')
            if not aid:
                continue
            row = self._row_index.get(aid)
            if row is None:
                row = getattr(table, 'rowCount')()  # type: ignore
                try: table.insertRow(row)  # type: ignore
                except Exception: continue
                self._row_index[aid] = row
                # init columns
                for col_i,_ in enumerate(self.COLS):
                    try: table.setItem(row, col_i, QTableWidgetItem(""))  # type: ignore
                    except Exception: pass
            # 更新列值
            for col_i, col_key in enumerate(self.COLS):
                val = it.get(col_key)
                item = table.item(row, col_i)  # type: ignore
                if item is None:
                    continue
                text_new = str(val)
                try:
                    if getattr(item, 'text', lambda: None)() != text_new:  # type: ignore
                        item.setText(text_new)  # type: ignore
                except Exception: pass
            # heartbeat_stale 着色
            self._apply_row_stale(row, it.get('heartbeat_stale'))
        # 若未选中 -> 默认第一行
        if self._selected_agent and self._selected_agent not in new_ids:
            self._selected_agent = None
        if not self._selected_agent and new_ids:
            self._selected_agent = new_ids[0]
        # 更新选择
        if self._selected_agent in self._row_index:
            try:
                table.setCurrentCell(self._row_index[self._selected_agent], 0)  # type: ignore
            except Exception: pass

    def _apply_row_stale(self, row: int, stale: Any):
        table = self._table
        if table is None:
            return
        if not stale:
            return
        for c in range(len(self.COLS)):
            item = table.item(row, c)  # type: ignore
            if item is None:
                continue
            try:
                bg = getattr(item, 'setBackground', None)
                if callable(bg):
                    bg(_ROW_COLOR_STALE)
            except Exception:  # pragma: no cover
                pass

    def _reindex(self):
        table = self._table
        if table is None: return
        new_map: Dict[str, int] = {}
        rc = getattr(table, 'rowCount', lambda: 0)()
        for r in range(rc):
            it = table.item(r, 0)  # type: ignore
            try:
                aid = it.text() if it else None  # type: ignore
            except Exception:
                aid = None
            if aid:
                new_map[aid] = r
        self._row_index = new_map

    def _do_control(self, action: str):
        if self._logic is None:
            return
        ctl_fn = getattr(self._logic, 'control', None)
        if not callable(ctl_fn):
            return
        # 优先: 选中行；若无选中，则对所有可见行执行
        targets: List[str] = []
        try:
            table = self._table
            if table is not None:
                sel_model = getattr(table, 'selectionModel', lambda: None)()
                selected_rows = []
                if sel_model is not None:
                    try:
                        selected_rows = [idx.row() for idx in sel_model.selectedRows()]  # type: ignore[attr-defined]
                    except Exception:
                        selected_rows = []
                if not selected_rows:
                    # 回退：全部行
                    try:
                        rc = table.rowCount()  # type: ignore[attr-defined]
                    except Exception:
                        rc = 0
                    selected_rows = list(range(rc))
                # 从第一列取 agent_id
                for r in selected_rows:
                    try:
                        it = table.item(r, 0)  # type: ignore[attr-defined]
                        aid = it.text() if it is not None else None
                        if isinstance(aid, str) and aid:
                            targets.append(aid)
                    except Exception:
                        pass
        except Exception:  # pragma: no cover
            pass
        # 若仍没有目标，使用当前选择的单个智能体（兼容旧逻辑）
        if not targets and getattr(self, '_selected_agent', None):
            targets = [self._selected_agent]  # type: ignore[attr-defined]
        # 执行动作
        for aid in targets:
            try:
                ctl_fn(aid, action)
            except Exception:  # pragma: no cover
                pass
        # 控制后立即刷新视图（轻量）— 也走 UI 主线程
        self.refresh()

    def _update_progress(self, batch: Dict[str, Any]):
        if self._progress_label is None:
            return
        try:
            if not batch:
                self._progress_label.setText("batch: -")  # type: ignore
                return
            txt = f"batch: {batch.get('created')}/{batch.get('requested')} fail={batch.get('failed')} in_progress={batch.get('in_progress')}"
            self._progress_label.setText(txt)  # type: ignore
        except Exception:  # pragma: no cover
            pass

    def _refresh_log_tail(self):
        if self._log_view is None or self._logic is None or not self._selected_agent:
            return
        tail_fn = getattr(self._logic, 'tail_logs', None)
        if not callable(tail_fn):
            return
        try:
            logs = tail_fn(self._selected_agent, 50)
            if isinstance(logs, list):
                text = "\n".join(logs)
                self._log_view.setPlainText(text)  # type: ignore
        except Exception:  # pragma: no cover
            pass

    # 新增：批量创建对话框（修复 _open_batch_dialog 缺失报错）
    def _open_batch_dialog(self):
        logic = self._logic
        if logic is None:
            return
        # 若没有真实 PySide6，可用性检测 -> 直接降级调用逻辑层
        try:
            from PySide6.QtWidgets import QDialog as _RealQDialog  # type: ignore
            _real_qt = True
        except Exception:  # pragma: no cover
            _real_qt = False
        if not _real_qt:
            try:
                start = getattr(logic, 'start_batch_create', None)
                if callable(start):
                    start(count=10, agent_type='Retail', name_prefix='agent', strategies=None)
                    self.refresh()
            except Exception:
                pass
            return
        # 首选 Qt 对话框
        try:
            # 延迟导入所需组件
            from app.ui.agent_creation_modal import AgentCreationModal  # type: ignore
            try:
                from app.services.agent_service import BATCH_ALLOWED_TYPES  # type: ignore
                _types = list(BATCH_ALLOWED_TYPES)
            except Exception:  # pragma: no cover
                _types = ["Retail", "MultiStrategyRetail"]
            dlg = QDialog()  # type: ignore
            layout = QVBoxLayout(dlg)  # type: ignore
            layout.addWidget(QLabel("Batch Create Agents"))  # type: ignore
            # Count
            layout.addWidget(QLabel("Count"))  # type: ignore
            count_edit = QLineEdit("10")  # type: ignore
            layout.addWidget(count_edit)  # type: ignore
            # Type
            layout.addWidget(QLabel("Type"))  # type: ignore
            type_combo = QComboBox()  # type: ignore
            try:
                type_combo.addItems(_types)  # type: ignore[attr-defined]
            except Exception:
                pass
            layout.addWidget(type_combo)  # type: ignore
            # Name Prefix (hidden/disabled when MSR)
            name_label = QLabel("Name Prefix")  # type: ignore
            name_edit = QLineEdit("agent")  # type: ignore
            layout.addWidget(name_label)  # type: ignore
            layout.addWidget(name_edit)  # type: ignore
            # Strategies
            layout.addWidget(QLabel("Strategies (one per line, for MultiStrategyRetail)"))  # type: ignore
            try:
                strategies_edit = QTextEdit()  # type: ignore
            except Exception:
                strategies_edit = QLineEdit("")  # type: ignore
            layout.addWidget(strategies_edit)  # type: ignore
            # Initial Cash (MSR only)
            init_cash_label = QLabel("Initial Cash (for MultiStrategyRetail)")  # type: ignore
            init_cash_edit = QLineEdit("100000")  # type: ignore
            layout.addWidget(init_cash_label)  # type: ignore
            layout.addWidget(init_cash_edit)  # type: ignore
            # 错误显示
            err_label = QLabel("")  # type: ignore
            layout.addWidget(err_label)  # type: ignore
            # 按钮
            btn_row = QHBoxLayout()  # type: ignore
            ok_btn = QPushButton("Start")  # type: ignore
            cancel_btn = QPushButton("Cancel")  # type: ignore
            btn_row.addWidget(ok_btn)  # type: ignore
            btn_row.addWidget(cancel_btn)  # type: ignore
            layout.addLayout(btn_row)  # type: ignore
            # 初始化 modal 逻辑
            modal = AgentCreationModal(logic)
            modal.open()
            # 根据类型切换可见性/可编辑状态
            def _apply_type_ui():
                t = getattr(type_combo, 'currentText', lambda: 'Retail')()
                is_msr = (t == 'MultiStrategyRetail')
                try:
                    # MSR: 隐藏/禁用 name prefix；显示 initial cash
                    name_label.setVisible(not is_msr)  # type: ignore[attr-defined]
                    name_edit.setVisible(not is_msr)  # type: ignore[attr-defined]
                except Exception:
                    try:
                        # 降级：禁用
                        name_edit.setEnabled(not is_msr)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                try:
                    init_cash_label.setVisible(is_msr)  # type: ignore[attr-defined]
                    init_cash_edit.setVisible(is_msr)  # type: ignore[attr-defined]
                except Exception:
                    pass
            try:
                type_combo.currentIndexChanged.connect(lambda *_: _apply_type_ui())  # type: ignore[attr-defined]
            except Exception:
                pass
            _apply_type_ui()
            # 提交
            def _ok():
                try:
                    try:
                        cnt = int(getattr(count_edit, 'text', lambda: '0')())
                    except Exception:
                        cnt = 0
                    agent_type = getattr(type_combo, 'currentText', lambda: 'Retail')()
                    name_prefix = getattr(name_edit, 'text', lambda: 'agent')()
                    if hasattr(strategies_edit, 'toPlainText'):
                        raw = strategies_edit.toPlainText()  # type: ignore[attr-defined]
                    else:
                        raw = getattr(strategies_edit, 'text', lambda: '')()
                    strategies = [s.strip() for s in (raw.splitlines() if raw else []) if s.strip()]
                    initial_cash = None
                    if agent_type == 'MultiStrategyRetail':
                        try:
                            initial_cash = float(getattr(init_cash_edit, 'text', lambda: '100000')())
                        except Exception:
                            initial_cash = 100000.0
                    ok = modal.submit(agent_type=agent_type, count=cnt, name_prefix=name_prefix, strategies=strategies, initial_cash=initial_cash)
                    if not ok:
                        v = modal.get_view()
                        code = v.get('error')
                        getattr(err_label, 'setText', lambda *_: None)(str(code) if code else 'UNKNOWN_ERROR')
                        return
                except Exception:
                    getattr(err_label, 'setText', lambda *_: None)('SUBMIT_FAILED')
                    return
                # 关闭对话框
                try:
                    dlg.accept()  # type: ignore[attr-defined]
                except Exception:
                    pass
                # 刷新视图（进度标签）
                try:
                    self.refresh()
                except Exception:
                    pass
            def _cancel():
                try:
                    dlg.reject()  # type: ignore[attr-defined]
                except Exception:
                    pass
            try:
                ok_btn.clicked.connect(_ok)  # type: ignore[attr-defined]
                cancel_btn.clicked.connect(_cancel)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                dlg.exec()  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        except Exception:
            pass
        # 回退：直接触发默认批量创建（保险）
        try:
            start = getattr(logic, 'start_batch_create', None)
            if callable(start):
                start(count=10, agent_type='Retail', name_prefix='agent', strategies=None)
                self.refresh()
        except Exception:
            pass

__all__ = ["AgentsPanelAdapter"]
