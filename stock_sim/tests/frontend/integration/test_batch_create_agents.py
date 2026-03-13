import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
import threading
import types
import pytest

from infra.event_bus import event_bus
from app.ui.adapters.agents_adapter import AgentsPanelAdapter
from app.controllers.agent_creation_controller import AgentCreationController

# 确保 Qt 应用环境（若可用）
try:
    from PySide6.QtWidgets import QApplication  # type: ignore
except Exception:  # pragma: no cover
    QApplication = None  # type: ignore


def _ensure_qapp():
    if QApplication is None:
        return None
    return QApplication.instance() or QApplication([])


def _label_text(lbl):
    if lbl is None:
        return ""
    # 兼容真实 Qt 与 headless stub
    t = getattr(lbl, "text", None)
    if callable(t):
        try:
            return t()
        except Exception:
            pass
    return getattr(lbl, "_text", "")


class FakeAgentService:
    def __init__(self):
        self._lock = threading.RLock()
        self._counter = 0

    def batch_create_retail(self, cfg):
        # 模拟较快创建以驱动多次进度事件
        time.sleep(0.01)
        with self._lock:
            base = self._counter
            self._counter += cfg.count
        ids = [f"rt-{base + i}" for i in range(cfg.count)]
        return {"success_ids": ids, "failed": []}


class BatchAwareLogic:
    def __init__(self, status_ref: dict):
        self.calls = 0
        self._status = status_ref
        self._lock = threading.RLock()

    def get_view(self):
        with self._lock:
            self.calls += 1
            # 由外部事件处理器写入的状态生成 batch 视图
            st = dict(self._status)
            batch = {}
            if st:
                batch = {
                    "created": st.get("success", 0),
                    "requested": st.get("count", 0),
                    "failed": st.get("failed", 0),
                    "in_progress": max(0, st.get("scheduled", 0) - st.get("completed", 0)),
                }
            return {
                "agents": {"items": []},
                "batch": batch,
            }


@pytest.mark.timeout(10)
def test_batch_create_events_drive_adapter_refresh_and_label_updates():
    _ensure_qapp()
    # 共享状态由事件回调更新，逻辑层从中构造 batch 视图
    current_status = {}

    def on_progress(_topic, payload):
        st = payload.get("status") or {}
        current_status.clear()
        current_status.update(st)

    def on_completed(_topic, payload):
        st = payload.get("status") or {}
        current_status.clear()
        current_status.update(st)

    topic_p = "agent.batch.create.progress"
    topic_c = "agent.batch.create.completed"

    # 适配器 + 伪轮询（快速退出，避免时间不确定性）
    adapter = AgentsPanelAdapter()
    logic = BatchAwareLogic(current_status)
    adapter.bind(logic)

    def _fake_poll_loop(self):
        for _ in range(20):
            if self._stop_evt.wait(0.01):
                break
            self._refresh_throttle.submit()
        try:
            self._refresh_throttle.flush_pending(force=True)
        except Exception:
            pass

    adapter._poll_loop = types.MethodType(_fake_poll_loop, adapter)  # type: ignore[attr-defined]

    _ = adapter.widget()

    svc = FakeAgentService()
    ctl = AgentCreationController(svc)  # type: ignore[arg-type]

    try:
        event_bus.subscribe(topic_p, on_progress)
        event_bus.subscribe(topic_c, on_completed)
        # 启动批量任务（多个分块触发进度）
        res = ctl.batch_create_multi_strategy(count=17, chunk_size=5, concurrency=2, progress_topic=topic_p, completed_topic=topic_c)
        jid = res["job_id"]

        # 等待出现第一个刷新，且标签包含 batch 文本
        t0 = time.perf_counter()
        ok = False
        while time.perf_counter() - t0 < 3.0:
            lbl = getattr(adapter, "_progress_label", None)
            txt = _label_text(lbl)
            if txt.startswith("batch:") and "/" in txt:
                ok = True
                break
            time.sleep(0.02)
        assert ok, "未看到批量进度标签更新"

        # 等待完成
        t1 = time.time()
        while True:
            st = ctl.get_job_status(jid)
            if st.get("done"):
                break
            assert time.time() - t1 < 5.0, "等待批量任务完成超时"
            time.sleep(0.05)

        # 最终标签应包含总创建数量
        lbl = getattr(adapter, "_progress_label", None)
        txt = _label_text(lbl)
        assert str(current_status.get("count", 17)) in txt
    finally:
        try:
            event_bus.unsubscribe(topic_p, on_progress)
            event_bus.unsubscribe(topic_c, on_completed)
        except Exception:
            pass
        adapter.stop()


@pytest.mark.timeout(10)
def test_cancel_batch_stops_progress_and_adapter_keeps_stable():
    _ensure_qapp()
    current_status = {}

    def on_progress(_t, p):
        st = p.get("status") or {}
        current_status.clear()
        current_status.update(st)

    topic_p = "agent.batch.create.progress"
    topic_c = "agent.batch.create.completed"

    adapter = AgentsPanelAdapter()
    logic = BatchAwareLogic(current_status)
    adapter.bind(logic)

    def _fake_poll_loop(self):
        for _ in range(30):
            if self._stop_evt.wait(0.01):
                break
            self._refresh_throttle.submit()
        try:
            self._refresh_throttle.flush_pending(force=True)
        except Exception:
            pass

    adapter._poll_loop = types.MethodType(_fake_poll_loop, adapter)  # type: ignore[attr-defined]
    _ = adapter.widget()

    svc = FakeAgentService()
    ctl = AgentCreationController(svc)  # type: ignore[arg-type]

    try:
        event_bus.subscribe(topic_p, on_progress)
        res = ctl.batch_create_multi_strategy(count=100, chunk_size=10, concurrency=2, progress_topic=topic_p, completed_topic=topic_c)
        jid = res["job_id"]

        # 等一个进度后立刻取消
        t0 = time.time()
        while current_status.get("scheduled", 0) == 0:
            assert time.time() - t0 < 2.0, "未收到进度事件"
            time.sleep(0.02)
        ctl.cancel_job(jid)

        # 等待结束
        t1 = time.time()
        while True:
            st = ctl.get_job_status(jid)
            if st.get("done"):
                break
            assert time.time() - t1 < 5.0, "取消后等待完成超时"
            time.sleep(0.05)

        # 记录刷新次数，短暂等待不应明显增长（伪轮询已很短，且任务完成后无新事件）
        calls = logic.calls
        time.sleep(0.2)
        assert logic.calls - calls <= 1
    finally:
        try:
            event_bus.unsubscribe(topic_p, on_progress)
        except Exception:
            pass
        adapter.stop()
