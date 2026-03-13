from __future__ import annotations
import time
from typing import Any, Dict, List

# Clock events
from app.services.clock_service import ClockService
from infra.event_bus import event_bus

# Account dropdown adapter
from app.ui.adapters.account_adapter import AccountPanelAdapter

# Agents panel and service
from app.panels.agents.panel import AgentsPanel

class _StubAgentController:
    def list_agents(self):
        return []
    def control(self, agent_id: str, action: str):
        raise RuntimeError("not used in test")

from app.services.agent_service import AgentService


def test_clock_service_publishes_events():
    cs = ClockService()
    received: List[Dict[str, Any]] = []
    def on_state(_topic: str, payload: Dict[str, Any]):
        received.append({"topic": _topic, "p": payload})
    def on_tick(_topic: str, payload: Dict[str, Any]):
        received.append({"topic": _topic, "p": payload})
    # subscribe
    h1 = event_bus.subscribe("clock.state", on_state)
    h2 = event_bus.subscribe("clock.tick", on_tick)
    try:
        cs.start("2024-01-02")
        cs.tick()
        # allow async dispatch if any
        time.sleep(0.01)
        topics = [e["topic"] for e in received]
        assert "clock.state" in topics
        assert "clock.tick" in topics
        # basic payload fields
        for e in received:
            p = e["p"]
            assert isinstance(p, dict)
            assert "status" in p and "sim_day" in p and "ts" in p
    finally:
        event_bus.unsubscribe("clock.state", on_state)
        event_bus.unsubscribe("clock.tick", on_tick)


def test_account_adapter_adds_account_on_created_event():
    adp = AccountPanelAdapter()
    # build widget (headless fallback)
    _ = adp.widget()
    # publish account.created
    aid = "MSR9999"
    event_bus.publish("account.created", {"account_id": aid, "initial_cash": 123456.0})
    # allow handler to run
    time.sleep(0.01)
    combo = getattr(adp, "_account_combo", None)
    assert combo is not None
    # findText fallback exists in stub
    try:
        idx = combo.findText(aid)
    except Exception:
        idx = -1
    assert idx != -1, "account id should be added to combo"


def test_agents_panel_passes_initial_cash_and_service_emits():
    svc = AgentService()
    ctl = _StubAgentController()
    panel = AgentsPanel(ctl, svc)
    # capture completed payload
    got: List[Dict[str, Any]] = []
    def on_completed(_topic: str, payload: Dict[str, Any]):
        got.append(payload)
    h = event_bus.subscribe("agent.batch.create.completed", on_completed)
    try:
        ok = panel.start_batch_create(count=1, agent_type="MultiStrategyRetail", name_prefix="ignored", strategies=["s1"], initial_cash=200000.0)
        assert ok
        # wait for background thread
        for _ in range(100):
            v = panel.get_view()
            if not v.get("batch", {}).get("in_progress"):
                break
            time.sleep(0.01)
        # ensure event received
        assert got, "should receive completed event"
        last = got[-1]
        assert last.get("type") == "MultiStrategyRetail"
        assert abs(float(last.get("initial_cash", 0.0)) - 200000.0) < 1e-6
        # service also publishes account.created with same initial cash; optional check
    finally:
        event_bus.unsubscribe("agent.batch.create.completed", on_completed)

