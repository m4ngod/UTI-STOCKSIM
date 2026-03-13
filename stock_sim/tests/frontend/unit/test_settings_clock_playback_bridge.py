from app.panels import reset_registry, register_builtin_panels, get_panel
from app.panels.clock import register_clock_panel
from app.services.clock_service import ClockService
from app.services.rollback_service import RollbackService
from app.controllers.clock_controller import ClockController
from app.state.settings_store import SettingsStore
from app.controllers.settings_controller import SettingsController
from app.panels.settings.panel import SettingsPanel
from app.panels.shared.notifications import notification_center


def _build_env(tmp_path):
    reset_registry()
    register_builtin_panels()
    # Clock stack
    clock = ClockService()
    rollback = RollbackService(clock)
    clock_ctl = ClockController(clock, rollback)
    register_clock_panel(clock_ctl)
    # Settings stack
    store = SettingsStore(path=str(tmp_path / 'settings.json'), auto_save=False)
    sctl = SettingsController(store)
    panel_settings = SettingsPanel(sctl)
    return panel_settings, clock_ctl


def test_playback_speed_updates_clock(tmp_path):
    spanel, cctl = _build_env(tmp_path)
    # 初始 clock speed
    clock_panel = get_panel('clock')
    v0 = clock_panel.get_view()
    assert abs(v0['state']['speed'] - 1.0) < 1e-9
    # 修改 settings 中 playback_speed -> 2.5
    spanel.set_playback_speed(2.5)
    # 同步后 clock panel speed 应更新 (同一调用周期内完成)
    v1 = clock_panel.get_view()
    assert abs(v1['state']['speed'] - 2.5) < 1e-9


def test_playback_speed_invalid_ignored_and_warn(tmp_path):
    spanel, cctl = _build_env(tmp_path)
    clock_panel = get_panel('clock')
    # 先设置一个合法速度, 建立桥接
    spanel.set_playback_speed(1.8)
    assert abs(clock_panel.get_view()['state']['speed'] - 1.8) < 1e-9
    # 清理通知
    notification_center.clear_all()
    # 设置非法速度 0 -> 应忽略并产生 warning
    spanel.set_playback_speed(0)
    v_after = clock_panel.get_view()
    assert abs(v_after['state']['speed'] - 1.8) < 1e-9  # 未改变
    warns = [n for n in notification_center.get_recent(10) if n.code == 'settings.playback_speed.invalid']
    assert len(warns) >= 1

