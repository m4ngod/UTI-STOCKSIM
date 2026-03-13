from tests.frontend.unit.test_settings_panel import _build
from observability.metrics import metrics


def test_settings_panel_metrics_counts():
    panel, ctl, store, layout = _build()
    baseline_total = metrics.counters.get("settings_panel_change_total", 0)

    panel.set_language('en_US')
    panel.set_theme('dark')
    panel.set_refresh_interval(1500)
    panel.set_playback_speed(2.0)
    panel.update_alert_threshold('drawdown_pct', 0.2)
    panel.batch_update(language='zh_CN', playback_speed=1.5)

    c = metrics.counters
    # 每字段至少一次（language 与 playback_speed 两次）
    assert c.get('settings_panel_change_language', 0) >= 2
    assert c.get('settings_panel_change_playback_speed', 0) >= 2
    assert c.get('settings_panel_change_theme', 0) >= 1
    assert c.get('settings_panel_change_refresh_interval_ms', 0) >= 1
    assert c.get('settings_panel_change_alert_thresholds', 0) >= 1

    expected_increment = 7  # 1+1+1+1+1 + (batch 2)
    assert c.get('settings_panel_change_total', 0) >= baseline_total + expected_increment

    # 布局修改不应增加计数
    total_before_layout = c.get('settings_panel_change_total', 0)
    panel.update_layout({'panels': {'account': {'x': 42}}})
    assert c.get('settings_panel_change_total', 0) == total_before_layout

