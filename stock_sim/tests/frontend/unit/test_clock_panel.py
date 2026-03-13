import time
import pytest

from app.services.clock_service import ClockService
from app.services.rollback_service import RollbackService, RollbackServiceError
from app.controllers.clock_controller import ClockController
from app.panels import reset_registry, register_builtin_panels, get_panel
from app.panels.clock import register_clock_panel


def _build_panel():
    reset_registry()
    register_builtin_panels()
    clock = ClockService()
    rollback = RollbackService(clock)
    ctl = ClockController(clock, rollback)
    register_clock_panel(ctl)
    panel = get_panel('clock')
    return panel, ctl, clock, rollback


def test_clock_panel_basic_flow():
    panel, ctl, clock, rb = _build_panel()
    v0 = panel.get_view()
    assert v0['state']['status'] == 'STOPPED'
    # start to day1
    panel.start('2025-01-01')
    v1 = panel.get_view()
    assert v1['state']['status'] == 'RUNNING'
    assert v1['state']['sim_day'] == '2025-01-01'
    # create checkpoint cp1
    cp1 = panel.create_checkpoint('cp1')
    v2 = panel.get_view()
    assert any(c['id'] == cp1 for c in v2['checkpoints'])
    assert v2['current_checkpoint'] == cp1
    # switch sim_day to day2 while RUNNING
    panel.switch_sim_day('2025-01-02')
    v3 = panel.get_view()
    assert v3['state']['sim_day'] == '2025-01-02'
    # create cp2
    cp2 = panel.create_checkpoint('cp2')
    v4 = panel.get_view()
    assert v4['current_checkpoint'] == cp2
    # pause & resume
    panel.pause()
    assert panel.get_view()['state']['status'] == 'PAUSED'
    panel.resume()
    assert panel.get_view()['state']['status'] == 'RUNNING'
    # set speed
    panel.set_speed(2.5)
    assert abs(panel.get_view()['state']['speed'] - 2.5) < 1e-9
    # rollback to cp1
    panel.rollback(cp1)
    v5 = panel.get_view()
    assert v5['state']['sim_day'] == '2025-01-01'
    # inconsistent rollback simulation (should raise and not change state)
    before = panel.get_view()['state']['sim_day']
    with pytest.raises(RollbackServiceError):
        panel.rollback(cp2, simulate_inconsistent=True)
    assert panel.get_view()['state']['sim_day'] == before


