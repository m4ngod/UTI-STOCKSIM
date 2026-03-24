from app.controllers.account_controller import AccountController
from app.core_dto.account import AccountDTO, PositionDTO
from app.panels.account.panel import AccountPanel
from app.ui.adapters.account_adapter import AccountPanelAdapter


class _StubAccountService:
    def load_account(self, account_id: str):
        positions = [
            PositionDTO(symbol="AAA", quantity=100, frozen_qty=10, avg_price=12.5, borrowed_qty=0, pnl_unreal=50.0),
            PositionDTO(symbol="BBB", quantity=200, frozen_qty=0, avg_price=8.0, borrowed_qty=20, pnl_unreal=-120.0),
        ]
        return AccountDTO(
            account_id=account_id,
            cash=100000.0,
            frozen_cash=3000.0,
            positions=positions,
            realized_pnl=12.0,
            unrealized_pnl=-70.0,
            equity=103000.0,
            utilization=0.03,
            snapshot_id="snap-adapter-1",
            sim_day="2026-03-25",
        )


def test_account_panel_adapter_exposes_logic_bridge_methods_headless():
    logic = AccountPanel(AccountController(_StubAccountService()))
    adapter = AccountPanelAdapter().bind(logic)
    _ = adapter.widget()

    adapter.switch_account("ACC-BRIDGE")
    view = adapter.get_view()

    assert view["account"]["account_id"] == "ACC-BRIDGE"
    assert view["account"]["frozen_cash"] == 3000.0

    items = adapter.get_items()
    assert len(items) == 2
    assert items[0]["symbol"] == "AAA"

    adapter.set_filter("bb")
    filtered = adapter.get_items()
    assert len(filtered) == 1
    assert filtered[0]["symbol"] == "BBB"

    adapter.set_filter(None)
    adapter.set_page(1, 1)
    paged = adapter.get_items()
    assert len(paged) == 1
