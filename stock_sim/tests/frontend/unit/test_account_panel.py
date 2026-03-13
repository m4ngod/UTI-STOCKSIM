from app.services.account_service import AccountService
from app.controllers.account_controller import AccountController
from app.state.settings_store import SettingsStore
from app.panels.account import register_account_panel
from app.panels import get_panel, reset_registry, register_builtin_panels


def _build_panel():
    reset_registry()
    register_builtin_panels()
    svc = AccountService()
    ctl = AccountController(svc)
    settings = SettingsStore(path='settings_test.json', auto_save=False)
    register_account_panel(ctl, settings)
    panel = get_panel('account')
    return panel, ctl, settings


def test_account_panel_switch_and_view():
    panel, ctl, settings = _build_panel()
    panel.switch_account('accA')
    view = panel.get_view()
    assert view['account']['account_id'] == 'accA'
    assert view['positions']['total'] >= 1


def test_account_panel_filter_and_pagination():
    panel, ctl, settings = _build_panel()
    panel.switch_account('accB')
    view_all = panel.get_view()
    total = view_all['positions']['total']
    panel.set_page(1, 2)
    panel.set_filter('sym')  # 通用前缀
    view_page = panel.get_view()
    assert view_page['positions']['page_size'] == 2
    assert len(view_page['positions']['items']) <= 2
    # 过滤后总数不大于原总数
    assert view_page['positions']['total'] <= total


def test_account_panel_threshold_update():
    panel, ctl, settings = _build_panel()
    panel.switch_account('accC')
    view_before = panel.get_view()
    # 收集存在高亮的数量
    highlighted_before = sum(1 for it in view_before['positions']['items'] if it['highlight'])
    # 提高阈值到 1 (几乎全部不高亮)
    settings.update_alert_threshold('drawdown_pct', 1.0)
    view_after = panel.get_view()
    highlighted_after = sum(1 for it in view_after['positions']['items'] if it['highlight'])
    assert highlighted_after <= highlighted_before

