from app.panels import reset_registry, register_builtin_panels
from app.utils.shortcuts import get_global_shortcut_manager, apply_high_contrast_vars
from app.state import SettingsStore
from observability.metrics import metrics

def test_shortcut_cycle_basic():
    reset_registry()
    register_builtin_panels()
    mgr = get_global_shortcut_manager()
    mgr.refresh_order()
    # 初始激活应为第一个面板
    assert mgr.get_active() == 'account'
    order = mgr.order.copy()
    seen = []
    for _ in range(len(order)):
        seen.append(mgr.get_active())
        mgr.next_panel()
    # 循环一次应包含所有面板名称
    assert set(seen) == set(order)
    # prev 循环回到最后一个
    last = mgr.prev_panel()
    assert last == order[-1]
    # metrics 计数应 >0
    assert metrics.counters.get('shortcut_cycle', 0) > 0
    assert metrics.counters.get('shortcut_cycle_next', 0) > 0
    assert metrics.counters.get('shortcut_cycle_prev', 0) > 0


def test_high_contrast_persist_and_callback(tmp_path):
    path = tmp_path / 'settings.json'
    store = SettingsStore(path=str(path))
    assert store.get_state().high_contrast is False
    called = {}
    def on_hc(field, value, full):
        called['field'] = field
        called['value'] = value
        called['full'] = full
    store.on_high_contrast(on_hc)
    store.set_high_contrast(True)
    assert called.get('field') == 'high_contrast'
    assert called.get('value') is True
    text = path.read_text(encoding='utf-8')
    assert '"high_contrast": true' in text.lower()
    # reload
    store2 = SettingsStore(path=str(path))
    assert store2.get_state().high_contrast is True


def test_apply_high_contrast_vars():
    base = {'color_text': '#1a1a1a', 'color_background': '#FFFFFF'}
    out = apply_high_contrast_vars(base, enabled=True)
    # 不修改原对象
    assert base['color_text'] == '#1a1a1a'
    # 输出已转大写/小写处理
    assert out['color_text'] == '#1A1A1A'
    assert out['color_background'] == '#ffffff'
    assert 'border_focus' in out

