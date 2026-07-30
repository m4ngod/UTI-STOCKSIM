from __future__ import annotations

from infra.event_bus import event_bus

from app.services.account_runtime_store import AccountRuntimeStore


class _FakeRuntimeGateway:
    def __init__(self):
        self.snapshots = {
            "ACC-1": {
                "account_id": "ACC-1",
                "cash": 1000.0,
                "frozen_cash": 20.0,
                "positions": [
                    {
                        "symbol": "AAA",
                        "quantity": 100,
                        "frozen_qty": 0,
                        "avg_price": 10.0,
                        "borrowed_qty": 0,
                        "pnl_unreal": 0.0,
                    }
                ],
                "equity": 2000.0,
                "utilization": 0.01,
                "sim_day": "0",
            }
        }

    def get_account_snapshot(self, account_id: str):
        return self.snapshots.get(account_id)

    def list_account_ids(self):
        return list(self.snapshots.keys())


def test_account_runtime_store_prefers_event_payload_for_live_updates():
    store = AccountRuntimeStore(_FakeRuntimeGateway())
    try:
        event_bus.publish(
            "AccountUpdated",
            {
                "account": {
                    "id": "ACC-1",
                    "cash": 900.0,
                    "frozen_cash": 10.0,
                    "positions": [
                        {
                            "symbol": "AAA",
                            "quantity": 120,
                            "frozen_qty": 5,
                            "avg_price": 10.5,
                            "borrowed_qty": 0,
                        }
                    ],
                    "sim_day": "1",
                }
            },
        )
        dto = store.get("ACC-1")
    finally:
        store.close()

    assert dto is not None
    assert dto.account_id == "ACC-1"
    assert dto.cash == 900.0
    assert dto.positions[0].quantity == 120
    assert dto.positions[0].frozen_qty == 5


def test_account_runtime_store_fetches_from_runtime_gateway_when_missing():
    gateway = _FakeRuntimeGateway()
    store = AccountRuntimeStore(gateway)
    try:
        dto = store.get_or_fetch("ACC-1")
    finally:
        store.close()

    assert dto is not None
    assert dto.account_id == "ACC-1"
    assert dto.equity == 2000.0
    assert store.list_account_ids() == ["ACC-1"]
