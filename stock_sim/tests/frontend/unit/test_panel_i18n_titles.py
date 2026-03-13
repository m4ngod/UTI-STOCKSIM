from app.panels import reset_registry, register_builtin_panels, list_panels
from app.i18n.loader import set_language, translate, get_missing_keys


def _collect_titles():
    return {p['name']: p['title'] for p in list_panels()}

def test_panel_titles_i18n_switch():
    reset_registry()
    set_language('en_US')
    register_builtin_panels()
    titles_en = _collect_titles()
    assert titles_en['account'] == 'Account'
    assert titles_en['market'] == 'Market'
    # 切换中文
    set_language('zh_CN')
    titles_cn = _collect_titles()
    assert titles_cn['account'] == '账户'
    assert titles_cn['market'] == '行情'
    # 确认无缺失 key (新增 panel.* 已提供)
    missing = [k for k in get_missing_keys() if k.split(':',1)[-1].startswith('panel.')]  # 仅面板相关
    assert not missing

