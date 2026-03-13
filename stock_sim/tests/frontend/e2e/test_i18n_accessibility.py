import pytest

from app.i18n import t, set_language, current_language
from app.state.settings_store import SettingsStore
from app.utils.shortcuts import ShortcutManager, apply_high_contrast_vars
from observability.metrics import metrics  # 新增: 验证快捷键与 i18n 指标

# 目标覆盖: R6 (设置变更回调/主题/语言/high_contrast) R11 (多语言加载与占位符) R12 (快捷键循环 + 高对比)

def test_i18n_language_switch_and_callbacks(tmp_path):
    settings_path = tmp_path / 'settings.json'
    store = SettingsStore(path=str(settings_path), auto_save=False)
    fired = {"lang": None, "theme": None, "contrast": None}

    def on_lang(field, val, full):  # 回调签名 (field, new_value, full_state_dict)
        fired["lang"] = (field, val)
    def on_theme(field, val, full):
        fired["theme"] = (field, val)
    def on_contrast(field, val, full):
        fired["contrast"] = (field, val)

    store.on_language(on_lang)
    store.on_theme(on_theme)
    store.on_high_contrast(on_contrast)

    # 初始语言 (SettingsState 默认 zh_CN), 但 i18n 默认 current_language() 为 en_US 需先对齐
    set_language(store.get_state().language)
    assert current_language() == 'zh_CN'
    assert t('app.title') == '股票模拟'

    # 切换语言 -> en_US
    store.set_language('en_US')
    assert current_language() == 'en_US'
    assert t('app.title') == 'Stock Simulation'
    assert fired['lang'][0] == 'language' and fired['lang'][1] == 'en_US'

    # 占位符格式化
    assert t('greet', name='Alice').startswith('Hello')

    # 缺失 key 回退返回 key 本身 (使用一个不存在键)
    missing_key = 'non.existent.key.for.test'
    before_missing = metrics.counters.get('i18n_missing', 0)
    assert t(missing_key) == missing_key
    assert metrics.counters.get('i18n_missing', 0) >= before_missing + 1

    # 主题切换 / 高对比
    store.set_theme('dark')
    assert fired['theme'] == ('theme', 'dark')

    # 高对比启用
    store.set_high_contrast(True)
    assert fired['contrast'] == ('high_contrast', True)
    assert store.get_state().high_contrast is True

    base_theme_vars = {"color_text": "#123abc", "color_background": "#FAFAFA"}
    adjusted = apply_high_contrast_vars(base_theme_vars, enabled=True)
    assert adjusted['color_text'] == base_theme_vars['color_text'].upper()
    assert adjusted['color_background'] == base_theme_vars['color_background'].lower()
    # 原字典未被修改
    assert base_theme_vars['color_text'] == '#123abc'


def test_shortcut_manager_cycle(monkeypatch):
    # 模拟 panels 列表 (避免依赖真实 GUI 注册)
    fake_panels = [
        {"name": "account"},
        {"name": "market"},
        {"name": "agents"},
    ]
    monkeypatch.setattr('app.utils.shortcuts.list_panels', lambda: fake_panels)
    mgr = ShortcutManager()
    # 初始激活应为第一个
    assert mgr.get_active() == 'account'

    before_cycle = metrics.counters.get('shortcut_cycle', 0)
    before_next = metrics.counters.get('shortcut_cycle_next', 0)
    before_prev = metrics.counters.get('shortcut_cycle_prev', 0)

    # 循环 next
    assert mgr.next_panel() == 'market'
    assert mgr.next_panel() == 'agents'
    # wrap around
    assert mgr.next_panel() == 'account'
    # prev 循环
    assert mgr.prev_panel() == 'agents'
    # 刷新顺序后保持仍能循环
    mgr.refresh_order()
    assert mgr.next_panel() in {'account','market','agents'}

    # 期望: 共调用 next 4 次, prev 1 次 => cycle 总数 +5
    assert metrics.counters.get('shortcut_cycle', 0) >= before_cycle + 5
    assert metrics.counters.get('shortcut_cycle_next', 0) >= before_next + 4
    assert metrics.counters.get('shortcut_cycle_prev', 0) >= before_prev + 1
