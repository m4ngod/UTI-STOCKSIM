from tests.frontend.unit.test_settings_panel import _build
from observability.metrics import metrics


def test_settings_panel_transaction_basic_and_idempotent():
    panel, ctl, store, layout = _build()
    before = {k: v for k, v in metrics.counters.items() if k.startswith('settings_panel_change_')}

    with panel.transaction() as tx:
        tx.language('en_US').theme('dark').refresh_interval(2500).playback_speed(1.25).alert_threshold('drawdown_pct', 0.15)

    v = panel.get_view()
    rc = v['recent_changes']
    # recent_changes 包含 5 个字段
    assert set(rc.keys()) == {'language', 'theme', 'refresh_interval_ms', 'playback_speed', 'alert_thresholds'}
    assert v['settings']['language'] == 'en_US'
    assert v['settings']['theme'] == 'dark'
    assert v['settings']['refresh_interval_ms'] == 2500
    assert abs(v['settings']['playback_speed'] - 1.25) < 1e-9
    assert abs(v['settings']['alert_thresholds']['drawdown_pct'] - 0.15) < 1e-9

    after = metrics.counters
    # 每字段至少 +1
    for f in ['language','theme','refresh_interval_ms','playback_speed','alert_thresholds']:
        assert after.get(f'settings_panel_change_{f}', 0) >= before.get(f'settings_panel_change_{f}', 0) + 1
    # 总计数至少增加 5
    total_before = before.get('settings_panel_change_total', 0)
    total_after = after.get('settings_panel_change_total', 0)
    assert total_after >= total_before + 5

    # commit 幂等: 手动 commit 后的修改不应再次应用
    with panel.transaction() as tx2:
        tx2.language('zh_CN')
        tx2.commit()
        # commit 后继续追加修改不生效
        tx2.theme('light')  # 不应被应用
    v2 = panel.get_view()
    assert v2['settings']['language'] == 'zh_CN'
    # theme 仍是之前 dark 而不是 light
    assert v2['settings']['theme'] == 'dark'

