from __future__ import annotations

from app.controllers.account_controller import AccountController
from app.core_dto.account import AccountDTO, PositionDTO


class _StoreAwareAccountService:
    def __init__(self):
        self._accounts = {
            "ACC-1": AccountDTO(
                account_id="ACC-1",
                cash=1000.0,
                frozen_cash=0.0,
                positions=[PositionDTO(symbol="AAA", quantity=10, frozen_qty=0, avg_price=10.0, borrowed_qty=0, pnl_unreal=1.0)],
                realized_pnl=0.0,
                unrealized_pnl=1.0,
                equity=1100.0,
                utilization=0.0,
                snapshot_id="snap-1",
                sim_day="0",
            )
        }

    def load_account(self, account_id: str):
        return self._accounts[account_id]

    def get_account(self, account_id: str | None = None, *, refresh: bool = False):
        if refresh:
            self._accounts["ACC-1"] = AccountDTO(
                account_id="ACC-1",
                cash=900.0,
                frozen_cash=10.0,
                positions=[PositionDTO(symbol="AAA", quantity=12, frozen_qty=1, avg_price=10.5, borrowed_qty=0, pnl_unreal=2.0)],
                realized_pnl=0.0,
                unrealized_pnl=2.0,
                equity=1036.0,
                utilization=0.01,
                snapshot_id="snap-2",
                sim_day="1",
            )
        return self._accounts.get(account_id or "ACC-1")

    def list_account_ids(self):
        return ["ACC-1"]


def test_account_controller_prefers_latest_service_account_state():
    svc = _StoreAwareAccountService()
    ctl = AccountController(svc)

    first = ctl.load_account("ACC-1")
    assert first.snapshot_id == "snap-1"

    latest = ctl.refresh()
    assert latest is not None
    assert latest.snapshot_id == "snap-2"

    current = ctl.get_account()
    assert current is not None
    assert current.snapshot_id == "snap-2"
    assert current.positions[0].quantity == 12


def test_account_controller_lists_account_ids_from_service():
    ctl = AccountController(_StoreAwareAccountService())
    assert ctl.list_account_ids() == ["ACC-1"]
