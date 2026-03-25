from app.panels import register_panel, get_panel, list_panels, dispose_panel, reset_registry, register_builtin_panels
from app.ui.main_window import MainWindow


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


def test_mainwindow_registered_panels_open():
    reset_registry()
    register_builtin_panels()
    mw = MainWindow()
    avail = set(mw.list_registered())
    for name in {"account", "market", "agents", "leaderboard", "clock", "orders"}:
        assert name in avail
    acc_panel = mw.open_panel('account')
    assert acc_panel is not None
    assert 'account' in getattr(mw, '_panel_widgets', {})

