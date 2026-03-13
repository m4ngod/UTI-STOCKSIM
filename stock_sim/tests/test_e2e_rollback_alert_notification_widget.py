from dataclasses import dataclass
from typing import List, Dict, Optional
import time

from infra.event_bus import event_bus
from app.panels.clock.panel import ClockPanel
from app.panels.shared.notifications import notification_center
from app.panels.shared.notification_widget import NotificationWidget

"""E2E: 回滚 -> 一致性校验失败 -> 触发 alert.triggered -> NotificationWidget 显示 ALERT 级别
成功标准: NotificationWidget 列表中包含 level='ALERT' 且 code='rollback.consistency' 的项
限制: 纯 headless + stub controller
"""

@dataclass
class _State:
    status: str = "RUNNING"
    sim_day: str = "2025-01-01"
    speed: float = 1.0
    ts: int = int(time.time()*1000)

class _StubRollbackController:
    def __init__(self):
        self._state = _State()
        self._cps: Dict[str, Dict] = {}
        self._order: List[str] = []
        self._seq = 0
    def state(self):
        return self._state
    # clock ops (最小实现)
    def start(self, sim_day: Optional[str] = None):
        if sim_day:
            self._state.sim_day = sim_day
        self._state.status = "RUNNING"
        self._state.ts = int(time.time()*1000)
        return self._state
    def pause(self):
        self._state.status = "PAUSED"; self._state.ts = int(time.time()*1000); return self._state
    def resume(self):
        self._state.status = "RUNNING"; self._state.ts = int(time.time()*1000); return self._state
    def stop(self):
        self._state.status = "STOPPED"; self._state.ts = int(time.time()*1000); return self._state
    def set_speed(self, speed: float):
        self._state.speed = speed; self._state.ts = int(time.time()*1000); return self._state
    # checkpoints
    def create_checkpoint(self, label: str) -> str:
        self._seq += 1
        cid = f"cp{self._seq}"
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
            # 触发系统级 alert 事件 -> notification_center ���听并转换为 ALERT
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
        return self._state


def test_e2e_rollback_alert_notification_widget():
    notification_center.clear_all()
    ctl = _StubRollbackController()
    panel = ClockPanel(ctl)
    cp1 = panel.create_checkpoint('base')
    panel.switch_sim_day('2025-02-01')
    panel.create_checkpoint('after_switch')
    # 触发不一致 -> 发布 alert
    try:
        panel.rollback(cp1, simulate_inconsistent=True)
    except Exception:
        pass
    widget = NotificationWidget()
    items = widget.list_items()
    alerts = [i for i in items if i['level'] == 'ALERT' and i['code'] == 'rollback.consistency']
    assert len(alerts) == 1, f"expected 1 rollback.consistency ALERT, got {alerts} from {items}"


# 新增：headless 路径无 GUI 属性校验（不导入 PySide6）
import sys, types, importlib

def test_e2e_headless_path_has_no_gui_attrs_without_pyside6_import():
    orig_pyside6 = sys.modules.get("PySide6")
    orig_main = sys.modules.get("app.main")

    dummy = types.ModuleType("PySide6")
    if hasattr(dummy, "__path__"):
        delattr(dummy, "__path__")
    sys.modules.pop("PySide6.QtWidgets", None)
    sys.modules.pop("PySide6.QtCore", None)
    sys.modules["PySide6"] = dummy
    if "app.main" in sys.modules:
        del sys.modules["app.main"]

    try:
        import app.main as main
        # 成功标准：未使用 GUI（QApplication 为 None），且返回 headless 窗口对象无 GUI 属性
        assert main.QApplication is None

        from app.panels import reset_registry, register_panel
        reset_registry()
        class P: ...
        register_panel("h", lambda: P())

        mw = main.run_frontend(headless=True)
        assert not hasattr(mw, "_ensure_central_layout")
        assert not hasattr(mw, "_layout")
        assert not hasattr(mw, "_panel_widgets")

        inst = mw.open_panel("h")
        assert isinstance(inst, P)
        assert "h" in mw.opened_panels
        assert isinstance(mw.list_available(), list)
    finally:
        if orig_pyside6 is None:
            sys.modules.pop("PySide6", None)
        else:
            sys.modules["PySide6"] = orig_pyside6
        if "app.main" in sys.modules:
            import app.main as main2
            importlib.reload(main2)
        elif orig_main is not None:
            sys.modules["app.main"] = orig_main
