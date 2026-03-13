from dataclasses import dataclass
from typing import List, Dict, Optional
import time

from infra.event_bus import event_bus
from app.panels.clock.panel import ClockPanel
from app.panels.shared.notifications import notification_center

@dataclass
class _State:
    status: str = "RUNNING"
    sim_day: str = "2025-01-01"
    speed: float = 1.0
    ts: int = int(time.time()*1000)

class _FakeClockRollbackController:
    def __init__(self):
        self._state = _State()
        self._cps: Dict[str, Dict] = {}
        self._order: List[str] = []
        self._id_seq = 0
    def state(self):
        return self._state
    def start(self, sim_day: Optional[str] = None):
        if sim_day:
            self._state.sim_day = sim_day
        self._state.status = "RUNNING"
        self._state.ts = int(time.time()*1000)
        return self._state
    def pause(self):
        self._state.status = "PAUSED"
        self._state.ts = int(time.time()*1000)
        return self._state
    def resume(self):
        self._state.status = "RUNNING"
        self._state.ts = int(time.time()*1000)
        return self._state
    def stop(self):
        self._state.status = "STOPPED"
        self._state.ts = int(time.time()*1000)
        return self._state
    def set_speed(self, speed: float):
        self._state.speed = speed
        self._state.ts = int(time.time()*1000)
        return self._state
    def create_checkpoint(self, label: str) -> str:
        self._id_seq += 1
        cid = f"cp{self._id_seq}"
        self._cps[cid] = {"id": cid, "label": label, "sim_day": self._state.sim_day, "created_ms": int(time.time()*1000), "is_current": True}
        for k,v in self._cps.items():
            if k != cid:
                v['is_current'] = False
        self._order.append(cid)
        return cid
    def list_checkpoints(self) -> List[Dict]:
        return [self._cps[i] for i in self._order]
    def rollback(self, checkpoint_id: str, *, simulate_inconsistent: bool = False):
        if checkpoint_id not in self._cps:
            raise RuntimeError("NOT_FOUND")
        if simulate_inconsistent:
            event_bus.publish('alert.triggered', {
                'type': 'rollback.consistency',
                'message': 'rollback consistency mismatch',
                'data': {'checkpoint_id': checkpoint_id},
                'ts': time.time(),
            })
            raise RuntimeError("CONSISTENCY_FAIL")
        cp = self._cps[checkpoint_id]
        self.start(cp['sim_day'])
        for k,v in self._cps.items():
            v['is_current'] = (k == checkpoint_id)


def test_rollback_inconsistency_emits_alert_notification():
    notification_center.clear_all()
    ctl = _FakeClockRollbackController()
    panel = ClockPanel(ctl)
    cp1 = panel.create_checkpoint('base')
    panel.switch_sim_day('2025-02-01')
    cp2 = panel.create_checkpoint('after_switch')  # noqa: F841
    try:
        panel.rollback(cp1, simulate_inconsistent=True)
    except Exception:
        pass
    alerts = [n for n in notification_center.get_recent(20) if n.level == 'alert' and n.code == 'rollback.consistency']
    assert len(alerts) == 1
    assert 'consistency' in alerts[0].message.lower()

