from dataclasses import dataclass
from typing import List, Dict, Optional
import time

from infra.event_bus import event_bus
from app.panels.clock.panel import ClockPanel
from app.panels.shared.notifications import notification_center

# 假状态 DTO (最小字段满足 ClockPanel 使用)
@dataclass
class _State:
    status: str = "RUNNING"
    sim_day: str = "2025-01-01"
    speed: float = 1.0
    ts: int = int(time.time()*1000)

# 假控制器: 实现 ClockPanel 所需接口 + 回滚时模拟不一致并触发 alert.triggered
class _FakeClockRollbackController:
    def __init__(self):
        self._state = _State()
        self._cps: Dict[str, Dict] = {}
        self._order: List[str] = []
        self._id_seq = 0
    # ClockController 期望接口
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
    # Checkpoint & rollback
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
            # 发布告警事件 (通知中心监听 'alert.triggered')
            event_bus.publish('alert.triggered', {
                'type': 'rollback.consistency',
                'message': 'rollback consistency mismatch',
                'data': {'checkpoint_id': checkpoint_id},
                'ts': time.time(),
            })
            # 模拟失败: 不修改状态
            raise RuntimeError("CONSISTENCY_FAIL")
        cp = self._cps[checkpoint_id]
        self.start(cp['sim_day'])
        for k,v in self._cps.items():
            v['is_current'] = (k == checkpoint_id)


def test_rollback_inconsistency_emits_alert_notification():
    notification_center.clear_all()
    ctl = _FakeClockRollbackController()
    panel = ClockPanel(ctl)  # 使用真实 ClockPanel 包装
    # 初始创建 checkpoint
    cp1 = panel.create_checkpoint('base')
    # 第二个交易日再创建一个 checkpoint
    panel.switch_sim_day('2025-02-01')
    cp2 = panel.create_checkpoint('after_switch')

    # 触发模拟不一致回滚 (期望抛异常并发出 alert)
    try:
        panel.rollback(cp1, simulate_inconsistent=True)
    except Exception:
        pass  # 预期异常

    # 验证通知中心收到 alert 级别通知 (code=rollback.consistency)
    alerts = [n for n in notification_center.get_recent(20) if n.level == 'alert' and n.code == 'rollback.consistency']
    assert len(alerts) == 1, f"期望 1 条 rollback.consistency alert, 实际 {len(alerts)}"
    assert 'consistency' in alerts[0].message.lower()

