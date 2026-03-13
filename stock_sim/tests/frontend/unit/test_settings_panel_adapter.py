from app.state.settings_store import SettingsStore
from app.controllers.settings_controller import SettingsController
from app.panels.settings.panel import SettingsPanel
from app.ui.adapters.settings_adapter import SettingsPanelAdapter


def test_settings_panel_adapter_batch_and_undo(tmp_path):
    path = tmp_path / 'settings_adapter_test.json'
    store = SettingsStore(path=str(path), auto_save=False)
    ctl = SettingsController(store)
    panel = SettingsPanel(ctl)
    adapter = SettingsPanelAdapter().bind(panel)

    # 初始视图
    v0 = panel.get_view()
    s0 = v0['settings']
    assert s0['language'] == 'zh_CN'
    assert s0['theme'] == 'light'
    assert s0['refresh_interval_ms'] == 1000
    assert s0['playback_speed'] == 1.0
    assert s0['alert_thresholds']['drawdown_pct'] == 0.1

    # 批量暂存
    adapter.stage_language('en_US') \
           .stage_theme('dark') \
           .stage_refresh_interval(2222) \
           .stage_playback_speed(1.25) \
           .set_alert_threshold('drawdown_pct', 0.15)

    staged = adapter.get_staged()
    assert staged['language'] == 'en_US'
    assert staged['theme'] == 'dark'
    assert staged['refresh_interval_ms'] == 2222
    assert staged['playback_speed'] == 1.25
    assert staged['alert_thresholds']['drawdown_pct'] == 0.15

    # 提交 (单次 transaction)
    adapter.apply()

    v1 = panel.get_view()
    s1 = v1['settings']
    rc1 = v1['recent_changes']
    # 设置已更新
    assert s1['language'] == 'en_US'
    assert s1['theme'] == 'dark'
    assert s1['refresh_interval_ms'] == 2222
    assert s1['playback_speed'] == 1.25
    assert s1['alert_thresholds']['drawdown_pct'] == 0.15
    # recent_changes 至少包含这些字段 (alert_thresholds 合并为单字段)
    for f in ['language','theme','refresh_interval_ms','playback_speed','alert_thresholds']:
        assert f in rc1

    # 撤销 (恢复默认)
    ok = adapter.undo()
    assert ok is True
    v2 = panel.get_view()
    s2 = v2['settings']
    rc2 = v2['recent_changes']
    assert s2['language'] == 'zh_CN'
    assert s2['theme'] == 'light'
    assert s2['refresh_interval_ms'] == 1000
    assert s2['playback_speed'] == 1.0
    assert s2['alert_thresholds']['drawdown_pct'] == 0.1
    # recent_changes 反映撤销字段
    for f in ['language','theme','refresh_interval_ms','playback_speed','alert_thresholds']:
        assert f in rc2

    # Redo 重新应用变更
    ok2 = adapter.redo()
    assert ok2 is True
    v3 = panel.get_view()
    s3 = v3['settings']
    assert s3['language'] == 'en_US'
    assert s3['theme'] == 'dark'
    assert s3['refresh_interval_ms'] == 2222
    assert s3['playback_speed'] == 1.25
    assert s3['alert_thresholds']['drawdown_pct'] == 0.15

