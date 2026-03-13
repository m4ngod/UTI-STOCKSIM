from app.event_bridge import EventBridge, FRONTEND_SNAPSHOT_BATCH_TOPIC
from app.core_dto import SnapshotDTO
from infra.event_bus import event_bus
import time


def test_event_bridge_batch_flush():
    batches = []
    event_bus.subscribe(FRONTEND_SNAPSHOT_BATCH_TOPIC, lambda t, p: batches.append(p))

    bridge = EventBridge(flush_interval_ms=40, max_batch_size=500, subscribe_backend=False)
    bridge.start()

    base_ts = int(time.time() * 1000)
    for i in range(50):
        snap = SnapshotDTO(
            symbol=f"SYM{i%3}",
            last=100.0 + i,
            bid_levels=[(100.0, 10)],
            ask_levels=[(101.0, 12)],
            volume=100 + i,
            turnover=1000.0 + i,
            ts=base_ts + i,
            snapshot_id=f"s{i}",
        )
        bridge.on_snapshot(snap)

    # 等待至少一个 flush 周期 (40ms) + 余量
    time.sleep(0.12)
    bridge.stop()

    total = sum(b["count"] for b in batches)
    assert total == 50, f"Expected 50 snapshots aggregated, got {total}"
    # flush 次数 (batches) 应 <=2 (允许 1 或 2)
    assert len(batches) <= 2, f"Too many flushes: {len(batches)} > 2"
    assert bridge.flush_count <= 2, f"Internal flush_count {bridge.flush_count} > 2"

