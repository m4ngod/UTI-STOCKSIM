import time

from app.core_dto import SnapshotDTO
from app.event_bridge import (
    BACKEND_RUNTIME_SNAPSHOT_TOPIC,
    EventBridge,
    FRONTEND_SNAPSHOT_BATCH_TOPIC,
    get_frontend_bridge,
    start_frontend_bridge,
    stop_frontend_bridge,
)
from infra.event_bus import event_bus


def test_event_bridge_batch_flush():
    batches = []
    event_bus.subscribe(FRONTEND_SNAPSHOT_BATCH_TOPIC, lambda t, p: batches.append(p))

    bridge = EventBridge(flush_interval_ms=40, max_batch_size=500, subscribe_backend=False)
    bridge.start()

    base_ts = int(time.time() * 1000)
    for i in range(50):
        snap = SnapshotDTO(
            symbol=f"SYM{i % 3}",
            last=100.0 + i,
            bid_levels=[(100.0, 10)],
            ask_levels=[(101.0, 12)],
            volume=100 + i,
            turnover=1000.0 + i,
            ts=base_ts + i,
            snapshot_id=f"s{i}",
        )
        bridge.on_snapshot(snap)

    time.sleep(0.12)
    bridge.stop()

    total = sum(batch["count"] for batch in batches)
    assert total == 50
    assert len(batches) <= 2
    assert bridge.flush_count <= 2


def test_event_bridge_normalizes_runtime_snapshotupdated():
    batches = []
    event_bus.subscribe(FRONTEND_SNAPSHOT_BATCH_TOPIC, lambda t, p: batches.append(p))

    bridge = EventBridge(flush_interval_ms=20, max_batch_size=8, subscribe_backend=True)
    bridge.start()
    try:
        event_bus.publish(
            BACKEND_RUNTIME_SNAPSHOT_TOPIC,
            {
                "symbol": "AAA",
                "run_id": "RUN-1",
                "ts_ms": 1234567890000,
                "snapshot": {
                    "symbol": "AAA",
                    "bids": [(9.9, 100)],
                    "asks": [(10.1, 120)],
                    "last": 10.0,
                    "vol": 300,
                    "turnover": 3000.0,
                },
            },
        )
        time.sleep(0.08)
    finally:
        bridge.stop()

    merged = []
    for batch in batches:
        merged.extend(batch.get("snapshots") or [])
    item = next((snap for snap in merged if snap.get("symbol") == "AAA"), None)
    assert item is not None
    assert item["run_id"] == "RUN-1"
    assert item["last"] == 10.0
    assert item["bid_levels"] == [(9.9, 100)]
    assert item["ask_levels"] == [(10.1, 120)]
    assert item["volume"] == 300
    assert item["turnover"] == 3000.0
    assert item["ts"] == 1234567890000


def test_start_frontend_bridge_returns_singleton():
    stop_frontend_bridge()
    bridge1 = start_frontend_bridge(flush_interval_ms=15, max_batch_size=16)
    bridge2 = start_frontend_bridge(flush_interval_ms=30, max_batch_size=32)
    try:
        assert bridge1 is bridge2
        assert get_frontend_bridge() is bridge1
    finally:
        stop_frontend_bridge()
