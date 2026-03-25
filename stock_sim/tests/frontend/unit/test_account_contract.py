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
    settings = SettingsStore(path='settings_test_contract.json', auto_save=False)
    register_account_panel(ctl, settings)
    return get_panel('account')


def test_account_view_exposes_contract_fields():
    panel = _build_panel()
    panel.switch_account('acc-contract')
    view = panel.get_view()

    account = view['account']
    assert 'frozen_cash' in account
    assert 'frozen_fee' in account
    assert 'account_meta' in account
    assert account['account_meta']['source'] == 'app-account-dto-service'
    assert account['account_meta']['authoritative'] is False
    assert account['account_meta']['runtime_fields_emphasized'] == ['frozen_cash', 'frozen_fee']

    items = view['positions']['items']
    assert items, 'expected at least one position item'
    first = items[0]
    assert 'frozen_qty' in first
    assert 'borrowed_qty' in first
    assert 'position_meta' in first
    assert first['position_meta']['source'] == 'app-account-dto-service'
    assert first['position_meta']['authoritative'] is False
    assert first['position_meta']['exposure_state'] in {'normal', 'frozen', 'short'}
