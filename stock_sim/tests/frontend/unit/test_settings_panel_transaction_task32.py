from tests.frontend.unit.test_settings_panel import _build
from observability.metrics import metrics


def test_settings_panel_transaction_preview_commit_cancel_metrics():
    panel, ctl, store, layout = _build()

    commit_before = metrics.counters.get('settings_panel_txn_commit', 0)
    commit_fields_before = metrics.counters.get('settings_panel_txn_commit_fields', 0)
    cancel_before = metrics.counters.get('settings_panel_txn_cancel', 0)

    # 事务提交测试 + preview
    with panel.transaction() as tx:
        tx.language('en_US').theme('dark').playback_speed(1.1).refresh_interval(2222).alert_threshold('drawdown_pct', 0.12)
        pv = tx.preview()
        # preview 不应修改真实状态
        v_mid = panel.get_view()
        assert v_mid['settings']['language'] != 'en_US'  # 尚未提交
        # preview 字段完整
        assert set(pv.keys()) == {'language','theme','playback_speed','refresh_interval_ms','alert_thresholds'}
        assert pv['alert_thresholds']['drawdown_pct'] == 0.12
    # 提交后状态变更
    v_after = panel.get_view()
    assert v_after['settings']['language'] == 'en_US'
    assert v_after['settings']['theme'] == 'dark'
    assert v_after['settings']['refresh_interval_ms'] == 2222
    assert abs(v_after['settings']['playback_speed'] - 1.1) < 1e-9
    assert abs(v_after['settings']['alert_thresholds']['drawdown_pct'] - 0.12) < 1e-9

    commit_after = metrics.counters.get('settings_panel_txn_commit', 0)
    commit_fields_after = metrics.counters.get('settings_panel_txn_commit_fields', 0)
    assert commit_after == commit_before + 1
    # 至少增加 5 个字段计数 (language/theme/playback_speed/refresh_interval_ms/alert_thresholds)
    assert commit_fields_after >= commit_fields_before + 5

    # 事务取消测试
    with panel.transaction() as tx2:
        tx2.language('zh_CN').theme('light')
        # 取消事务
        tx2.cancel()
        # cancel 后修改不生效
        tx2.playback_speed(2.0)
    v_cancel = panel.get_view()
    # 仍保持之前 commit 的语言与主题
    assert v_cancel['settings']['language'] == 'en_US'
    assert v_cancel['settings']['theme'] == 'dark'

    cancel_after = metrics.counters.get('settings_panel_txn_cancel', 0)
    # 至少有一次取消
    assert cancel_after == cancel_before + 1
    # 取消不应增加 commit 计数
    assert metrics.counters.get('settings_panel_txn_commit', 0) == commit_after

