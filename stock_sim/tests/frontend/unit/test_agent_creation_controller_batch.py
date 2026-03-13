# pytest: unit tests for AgentCreationController batch create
from __future__ import annotations
import time
import threading
import pytest

from app.controllers.agent_creation_controller import AgentCreationController
from app.services.agent_service import AgentServiceError, BATCH_ALLOWED_TYPES, BatchCreateConfig
from infra.event_bus import event_bus


class FakeAgentService:
    def __init__(self):
        self._lock = threading.RLock()
        self._counter = 0

    def batch_create_retail(self, cfg: BatchCreateConfig):
        if cfg.count <= 0:
            return {"success_ids": [], "failed": ["INVALID_COUNT"]}
        if cfg.agent_type not in BATCH_ALLOWED_TYPES:
            raise AgentServiceError("AGENT_BATCH_UNSUPPORTED", f"type {cfg.agent_type} not allowed for batch")
        ids = []
        with self._lock:
            base = self._counter
            self._counter += cfg.count
        for i in range(cfg.count):
            ids.append(f"{cfg.agent_type[:3].lower()}-{cfg.name_prefix}-{base + i}")
        return {"success_ids": ids, "failed": []}


@pytest.fixture()
def controller():
    svc = FakeAgentService()
    ctl = AgentCreationController(svc)  # type: ignore[arg-type]
    yield ctl


def test_batch_success_progress_and_complete(controller: AgentCreationController):
    progress_events = []
    completed_events = []

    def on_progress(_topic, payload):
        progress_events.append(payload)

    def on_completed(_topic, payload):
        completed_events.append(payload)

    topic_p = "agent.batch.create.progress"
    topic_c = "agent.batch.create.completed"
    try:
        event_bus.subscribe(topic_p, on_progress)
        event_bus.subscribe(topic_c, on_completed)
        res = controller.batch_create_multi_strategy(
            count=23, chunk_size=5, concurrency=2, name_prefix="u1", progress_topic=topic_p, completed_topic=topic_c
        )
        assert "job_id" in res
        jid = res["job_id"]
        # 等待完成
        t0 = time.time()
        while True:
            st = controller.get_job_status(jid)
            if st.get("done"):
                break
            assert time.time() - t0 < 5, "timeout waiting job done"
            time.sleep(0.05)
        # 校验最终状态
        st = controller.get_job_status(jid)
        assert st["done"] is True
        assert st["completed"] == 23
        assert st["success"] == 23
        assert st["failed"] == 0
        # 事件至少各触发一次
        assert any(e.get("status", {}).get("completed") for e in progress_events)
        assert completed_events and completed_events[-1]["status"]["done"] is True
    finally:
        event_bus.unsubscribe(topic_p, on_progress)
        event_bus.unsubscribe(topic_c, on_completed)


def test_cancel_job_best_effort(controller: AgentCreationController):
    topic_p = "agent.batch.create.progress"
    topic_c = "agent.batch.create.completed"
    got_first_progress = threading.Event()

    def on_progress(_topic, payload):
        if payload.get("status", {}).get("scheduled", 0) > 0:
            got_first_progress.set()

    try:
        event_bus.subscribe(topic_p, on_progress)
        res = controller.batch_create_multi_strategy(
            count=100, chunk_size=25, concurrency=2, name_prefix="u2", progress_topic=topic_p, completed_topic=topic_c
        )
        jid = res["job_id"]
        # 等到开始调度后立即取消
        got_first_progress.wait(timeout=1.0)
        controller.cancel_job(jid)
        # 等待结束
        t0 = time.time()
        while True:
            st = controller.get_job_status(jid)
            if st.get("done"):
                break
            assert time.time() - t0 < 5, "timeout waiting job done after cancel"
            time.sleep(0.05)
        st = controller.get_job_status(jid)
        assert st["done"] is True
        assert st["cancel_requested"] is True
        # 取消为尽力而为：允许已完成 >=1，但不强求小于总数（竞态）。至少总数一致性成立
        assert st["success"] + st["failed"] == st["completed"]
        assert st["completed"] <= 100
    finally:
        event_bus.unsubscribe(topic_p, on_progress)


def test_invalid_and_unsupported_type(controller: AgentCreationController):
    # invalid count
    with pytest.raises(AgentServiceError) as ei:
        controller.batch_create_multi_strategy(count=0)
    assert ei.value.code == "INVALID_COUNT"
    # unsupported type
    with pytest.raises(AgentServiceError) as ei2:
        controller.batch_create_multi_strategy(count=1, agent_type="HedgeFund")
    assert ei2.value.code == "AGENT_BATCH_UNSUPPORTED"


def test_idempotent_job_id(controller: AgentCreationController):
    jid = "job-fixed-1"
    r1 = controller.batch_create_multi_strategy(count=5, job_id=jid)
    r2 = controller.batch_create_multi_strategy(count=5, job_id=jid)
    assert r1["job_id"] == jid and r2["job_id"] == jid
    st1 = r1["status"]
    st2 = r2["status"]
    assert st1["job_id"] == st2["job_id"] == jid
