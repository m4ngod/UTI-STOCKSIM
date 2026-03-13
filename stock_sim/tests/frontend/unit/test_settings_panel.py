import time

from app.state.settings_store import SettingsStore
from app.controllers.settings_controller import SettingsController
from app.panels import reset_registry, register_builtin_panels, get_panel
from app.panels.settings import register_settings_panel
from app.state.layout_persistence import LayoutPersistence


def _build():
    reset_registry()
    register_builtin_panels()
    store = SettingsStore(path="test_settings.json", auto_save=False)
    ctl = SettingsController(store)
    layout = LayoutPersistence(path="test_layout.json")
    register_settings_panel(ctl, layout)
    panel = get_panel('settings')
    return panel, ctl, store, layout


def test_settings_panel_basic():
    panel, ctl, store, layout = _build()
    v0 = panel.get_view()
    assert v0['settings']['language'] == store.get_state().language
    # 修改语言
    panel.set_language('en_US')
    v1 = panel.get_view()
    assert v1['settings']['language'] == 'en_US'
    assert v1['recent_changes'] and v1['recent_changes'].get('language') == 'en_US'
    # 修改主题/刷新/倍速/阈值
    panel.set_theme('dark')
    panel.set_refresh_interval(2000)
    panel.set_playback_speed(2.0)
    panel.update_alert_threshold('drawdown_pct', 0.2)
    v2 = panel.get_view()
    assert v2['settings']['theme'] == 'dark'
    assert v2['settings']['refresh_interval_ms'] == 2000
    assert abs(v2['settings']['playback_speed'] - 2.0) < 1e-9
    assert abs(v2['settings']['alert_thresholds']['drawdown_pct'] - 0.2) < 1e-9
    # 批量更新
    panel.batch_update(language='zh_CN', playback_speed=1.5)
    v3 = panel.get_view()
    assert v3['settings']['language'] == 'zh_CN'
    assert abs(v3['settings']['playback_speed'] - 1.5) < 1e-9
    # 布局更新
    panel.update_layout({'panels': {'account': {'x': 10}}})
    assert panel.get_view()['layout']['panels']['account']['x'] == 10
    panel.replace_layout({'panels': {'market': {'y': 5}}})
    assert panel.get_view()['layout']['panels']['market']['y'] == 5


