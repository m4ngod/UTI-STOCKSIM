"""
Smoke script for new metrics:
- ui_refresh_latency_ms (AgentsPanelAdapter event->refresh delay)
- agent_create_success / agent_create_failed (AgentCreationController batch)
- language_switch_ms (SettingsPanel.set_language)

Run:
  python -m scripts.metrics_smoke_new_indicators
Expect:
  Prints counters/timings snapshots with above keys present (values > 0 for timings, >=0 for counters).
"""
from __future__ import annotations
import time

from observability.metrics import metrics
from infra.event_bus import event_bus

# 1) language_switch_ms
from app.controllers.settings_controller import SettingsController
from app.state.settings_store import SettingsStore
from app.panels.settings.panel import SettingsPanel

store = SettingsStore(path="frontend_settings.json", auto_save=False)
ctl = SettingsController(store)
panel = SettingsPanel(ctl)
# language switch twice to record timings
panel.set_language("en_US")
panel.set_language("zh_CN")

# 2) agent_create_success/failed via AgentCreationController
from app.controllers.agent_creation_controller import AgentCreationController
from app.services.agent_service import AgentService

svc = AgentService()
creator = AgentCreationController(svc)
res = creator.batch_create_multi_strategy(count=5, chunk_size=2, concurrency=1, name_prefix="smk")
jid = res["job_id"]
# Wait until done (max 3s)
t0 = time.time()
while True:
    st = creator.get_job_status(jid)
    if st.get("done"):
        break
    assert time.time() - t0 < 3.0, "timeout waiting for agent batch"
    time.sleep(0.05)

# 3) ui_refresh_latency_ms via AgentsPanelAdapter
from app.ui.adapters.agents_adapter import AgentsPanelAdapter

class _Logic:
    def __init__(self):
        self._view_calls = 0
    def get_view(self):
        self._view_calls += 1
        return {"agents": {"items": []}, "batch": {}}

adapter = AgentsPanelAdapter().bind(_Logic())
_ = adapter.widget()
# Publish a progress event to trigger refresh
payload = {"status": {"requested": 1, "created": 0, "failed": 0}}
event_bus.publish("agent.batch.create.progress", payload)
# Allow throttle to run and flush thread to flush
time.sleep(0.4)
adapter.stop()

# ---- Print snapshot ----
print("counters:", dict(metrics.counters))
print("timings-keys:", list(metrics.timings.keys()))
# show basic stats if available
def _stat(name: str):
    arr = metrics.timings.get(name, [])
    if not arr:
        return None
    return {
        "count": len(arr),
        "p50": metrics.get_percentile(name, 50),
        "p95": metrics.get_percentile(name, 95),
        "p99": metrics.get_percentile(name, 99),
    }
print("ui_refresh_latency_ms:", _stat("ui_refresh_latency_ms"))
print("language_switch_ms:", _stat("language_switch_ms"))

