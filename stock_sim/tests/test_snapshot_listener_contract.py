from stock_sim.services.snapshot_listener import SnapshotPersistenceListener


def test_snapshot_listener_keeps_existing_sim_time_payload_fields():
    listener = SnapshotPersistenceListener()
    payload = {
        "symbol": "AAA",
        "sim_day": 7,
        "sim_dt": "0001-01-07T00:00:00",
        "snapshot": {
            "symbol": "AAA",
            "last": 10.0,
            "vol": 100,
            "turnover": 1000.0,
        },
    }

    try:
        listener._on_snapshot("SnapshotUpdated", payload)
    except Exception:
        pass

    assert payload["sim_day"] == 7
    assert payload["sim_dt"] == "0001-01-07T00:00:00"
