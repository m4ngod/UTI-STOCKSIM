import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
import threading
import pytest

from infra.event_bus import event_bus
from app.ui.adapters.agents_adapter import AgentsPanelAdapter


class FakeLogic:
    def __init__(self):
        self.calls = 0
        self.last_view = None
        self._lock = threading.RLock()

    def get_view(self):
        with self._lock:
            self.calls += 1
        # 返回最小可用视图结构
        return {
            "agents": {
                "items": [
                    {
                        "agent_id": "a1",
                        "name": "agent-1",
                        "type": "Retail",
                        "status": "ready",
                        "params_version": 1,
                        "heartbeat_stale": False,
                    }
                ]
            },
            "batch": {},
        }


@pytest.mark.timeout(5)
def test_event_refresh_under_500ms():
    adapter = AgentsPanelAdapter()
    logic = FakeLogic()
    adapter.bind(logic)
    # 创建控件会触发 _ensure_started -> 订阅事件 + 启动线程
    _ = adapter.widget()

    try:
        t0 = time.perf_counter()
        event_bus.publish("agent-status-changed", {"agent_id": "a1", "status": "running"})
        # 等待刷新发生（Throttle 200ms + flush_loop 100ms，故应在500ms内可见）
        while time.perf_counter() - t0 < 0.6:
            if logic.calls > 0:
                break
            time.sleep(0.01)
        assert logic.calls > 0, "事件触发后未在500ms内刷新"
    finally:
        adapter.stop()


@pytest.mark.timeout(5)
def test_polling_refresh_without_events_via_fake_loop():
    adapter = AgentsPanelAdapter()
    logic = FakeLogic()
    adapter.bind(logic)

    # 以快速伪轮询替换真实轮询，避免2s初始退避导致测试变慢
    def _fake_poll_loop(self):
        for _ in range(10):
            if self._stop_evt.wait(0.01):
                break
            # 模拟轮询触发刷新节流
            self._refresh_throttle.submit()
        # 退出前强制flush一次，确保至少有一次刷新执行
        try:
            self._refresh_throttle.flush_pending(force=True)
        except Exception:
            pass

    # 绑定到实例，使 _ensure_started 启动的线程运行伪循环
    import types
    adapter._poll_loop = types.MethodType(_fake_poll_loop, adapter)  # type: ignore[attr-defined]

    _ = adapter.widget()

    try:
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 0.6:
            if logic.calls > 0:
                break
            time.sleep(0.01)
        assert logic.calls > 0, "伪轮询触发后未在500ms内刷新"
    finally:
        adapter.stop()
        # 停止后等待一会，确保不再继续刷新
        calls_after_stop = logic.calls
        time.sleep(0.05)
        assert logic.calls == calls_after_stop

