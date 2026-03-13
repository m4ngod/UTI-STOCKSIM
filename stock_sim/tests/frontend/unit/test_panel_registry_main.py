from app.panels import register_panel, get_panel, list_panels, dispose_panel, reset_registry, register_builtin_panels
from app.main import run_frontend


def test_panel_registry_lazy_creation():
    reset_registry()
    created = []
    def factory():
        created.append('x')
        return {'panel': 'x'}
    register_panel('xpanel', factory, title='X Panel')
    info = list_panels()
    assert any(i['name'] == 'xpanel' and i['created'] is False for i in info)
    inst = get_panel('xpanel')
    assert inst == {'panel': 'x'}
    info2 = list_panels()
    assert any(i['name'] == 'xpanel' and i['created'] is True for i in info2)
    dispose_panel('xpanel')
    info3 = list_panels()
    assert any(i['name'] == 'xpanel' and i['created'] is False for i in info3)


def test_run_frontend_headless():
    reset_registry()
    mw = run_frontend(headless=True)
    avail = {p['name'] for p in mw.list_available()}
    # 内置占位面板应全部注册
    for name in {"account","market","agents","leaderboard","clock","settings"}:
        assert name in avail
    # 打开一个面板应惰性实例化
    acc_panel = mw.open_panel('account')
    assert getattr(acc_panel, 'name', None) == 'account'

