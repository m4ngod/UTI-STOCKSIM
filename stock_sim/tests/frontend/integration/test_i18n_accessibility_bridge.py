# Bridge test to ensure E2E i18n & accessibility scenarios are executed under integration path
import pytest
from app.i18n import t, set_language, current_language
from app.state.settings_store import SettingsStore
from app.utils.shortcuts import ShortcutManager, apply_high_contrast_vars

def test_i18n_language_switch_and_callbacks_bridge(tmp_path):
    settings_path = tmp_path / 'settings.json'
    store = SettingsStore(path=str(settings_path), auto_save=False)
    fired = {"lang": None, "theme": None}
    store.on_language(lambda f,v,full: fired.__setitem__('lang',(f,v)))
    store.on_theme(lambda f,v,full: fired.__setitem__('theme',(f,v)))
    set_language(store.get_state().language)
    assert current_language() == 'zh_CN'
    assert t('app.title') in {'股票模拟','Stock Simulation'}  # 容忍文件顺序差异
    store.set_language('en_US')
    assert current_language() == 'en_US'
    assert t('app.title') == 'Stock Simulation'
    assert fired['lang'] == ('language','en_US')
    assert t('greet', name='Bob').startswith('Hello')
    mk = 'some.missing.i18n.key.for.bridge'
    assert t(mk) == mk
    store.set_theme('dark')
    assert fired['theme'] == ('theme','dark')
    adjusted = apply_high_contrast_vars({"color_text":"#abc","color_background":"#DEF"}, enabled=True)
    assert adjusted['color_text'] == '#ABC' and adjusted['color_background'] == '#def'


def test_shortcut_manager_cycle_bridge(monkeypatch):
    fake_panels = [
        {"name":"account"}, {"name":"market"}, {"name":"agents"}, {"name":"settings"}
    ]
    monkeypatch.setattr('app.utils.shortcuts.list_panels', lambda: fake_panels)
    mgr = ShortcutManager()
    assert mgr.get_active() == 'account'
    seq = [mgr.next_panel(), mgr.next_panel(), mgr.next_panel(), mgr.next_panel()]
    assert seq[0]=='market' and seq[1]=='agents' and seq[2]=='settings' and seq[3]=='account'
    assert mgr.prev_panel() == 'settings'
    mgr.refresh_order()
    assert mgr.get_active() in {'account','market','agents','settings'}

