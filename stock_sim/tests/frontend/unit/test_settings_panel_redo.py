from tests.frontend.unit.test_settings_panel import _build
from observability.metrics import metrics

def test_settings_panel_redo_sequence_metrics_and_clear():
    panel, ctl, store, layout = _build()

    redo_success_before = metrics.counters.get('settings_panel_redo_success', 0)
    redo_empty_before = metrics.counters.get('settings_panel_redo_empty', 0)

    # 初始 (zh_CN, light, speed 1.0)
    panel.set_language('en_US')          # step1
    panel.set_theme('dark')              # step2
    panel.set_playback_speed(2.0)        # step3

    # 三次撤销 => 回到初始
    assert panel.undo_last() is True      # 撤销 speed -> speed 回到 1.0
    assert panel.undo_last() is True      # 撤销 theme -> theme 回到 light
    assert panel.undo_last() is True      # 撤销 language -> language 回到 zh_CN

    s_init = panel.get_view()['settings']
    assert s_init['language'] == store.get_state().language
    assert s_init['theme'] == 'light'
    assert abs(s_init['playback_speed'] - 1.0) < 1e-9

    # 依次 redo 三次 (顺序应为: 撤销前第三次的前状态 -> 第二次 -> 第一次)
    assert panel.redo_next() is True  # 还原 language 修改前第三次撤销的前状态: language en_US, theme light
    s_r1 = panel.get_view()['settings']
    assert s_r1['language'] == 'en_US'
    assert s_r1['theme'] == 'light'
    assert abs(s_r1['playback_speed'] - 1.0) < 1e-9

    assert panel.redo_next() is True  # 还原 theme dark
    s_r2 = panel.get_view()['settings']
    assert s_r2['language'] == 'en_US'
    assert s_r2['theme'] == 'dark'
    assert abs(s_r2['playback_speed'] - 1.0) < 1e-9

    assert panel.redo_next() is True  # 还原 speed 2.0
    s_r3 = panel.get_view()['settings']
    assert s_r3['language'] == 'en_US'
    assert s_r3['theme'] == 'dark'
    assert abs(s_r3['playback_speed'] - 2.0) < 1e-9

    # redo 栈已空，再次 redo -> False
    assert panel.redo_next() is False

    redo_success_after = metrics.counters.get('settings_panel_redo_success', 0)
    redo_empty_after = metrics.counters.get('settings_panel_redo_empty', 0)
    assert redo_success_after >= redo_success_before + 3
    assert redo_empty_after >= redo_empty_before + 1

    # 新用户修改应清空 redo 栈
    panel.set_theme('light')
    # redo 再次应为空
    empty_before2 = metrics.counters.get('settings_panel_redo_empty', 0)
    assert panel.redo_next() is False
    assert metrics.counters.get('settings_panel_redo_empty', 0) >= empty_before2 + 1

