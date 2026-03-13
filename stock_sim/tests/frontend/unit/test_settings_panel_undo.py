from tests.frontend.unit.test_settings_panel import _build
from observability.metrics import metrics

def test_settings_panel_undo_basic_and_metrics():
    panel, ctl, store, layout = _build()

    success_before = metrics.counters.get('settings_panel_undo_success', 0)
    empty_before = metrics.counters.get('settings_panel_undo_empty', 0)

    # 进行多次设置变更
    panel.set_language('en_US')  # 1
    panel.set_theme('dark')      # 2
    panel.set_playback_speed(2.0)  # 3

    v3 = panel.get_view()['settings']
    assert v3['language'] == 'en_US'
    assert v3['theme'] == 'dark'
    assert abs(v3['playback_speed'] - 2.0) < 1e-9

    # 第一次撤销 -> 回到设置速度前
    assert panel.undo_last() is True
    v_after1 = panel.get_view()['settings']
    assert v_after1['language'] == 'en_US'
    assert v_after1['theme'] == 'dark'
    assert abs(v_after1['playback_speed'] - 1.0) < 1e-9  # 恢复默认

    # 第二次撤销 -> 回到主题修改前
    assert panel.undo_last() is True
    v_after2 = panel.get_view()['settings']
    assert v_after2['language'] == 'en_US'
    assert v_after2['theme'] == 'light'

    # 第三次撤销 -> 回到语言修改前
    assert panel.undo_last() is True
    v_after3 = panel.get_view()['settings']
    assert v_after3['language'] == store.get_state().language  # 初始 zh_CN
    assert v_after3['theme'] == 'light'

    # 第四次撤销 -> 无可撤销
    assert panel.undo_last() is False

    success_after = metrics.counters.get('settings_panel_undo_success', 0)
    empty_after = metrics.counters.get('settings_panel_undo_empty', 0)

    assert success_after >= success_before + 3
    assert empty_after >= empty_before + 1

