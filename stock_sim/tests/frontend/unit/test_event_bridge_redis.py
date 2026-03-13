from app.event_bridge import EventBridge, FRONTEND_SNAPSHOT_BATCH_TOPIC, BACKEND_SNAPSHOT_TOPIC
from infra.event_bus import event_bus
from observability.metrics import metrics
import time


def test_event_bridge_redis_fallback_to_local():
    # 记录初始计数
    before = metrics.counters.get("redis_fallback", 0)
    batches = []
    event_bus.subscribe(FRONTEND_SNAPSHOT_BATCH_TOPIC, lambda t, p: batches.append(p))

    # 工厂直接抛异常 -> 触发 fallback + 本地订阅
    def failing_factory(channels, cb):  # noqa: ARG001
        raise RuntimeError("redis down")

    bridge = EventBridge(
        flush_interval_ms=30,
        max_batch_size=100,
        subscribe_backend=True,
        use_redis=True,
        redis_subscriber_factory=failing_factory,
    )
    bridge.start()

    # 发布 3 条后端 snapshot 事件 (应被本地订阅捕获)
    for i in range(3):
        event_bus.publish(BACKEND_SNAPSHOT_TOPIC, {"symbol": f"X{i}", "last": 1.0 + i, "ts": i, "snapshot_id": f"s{i}"})

    time.sleep(0.12)  # 等待 flush
    bridge.stop()

    after = metrics.counters.get("redis_fallback", 0)
    assert after == before + 1, f"redis_fallback counter not incremented: before={before} after={after}"

    total = sum(b["count"] for b in batches)
    assert total == 3, f"Expected 3 snapshots via fallback local subscription, got {total}"
    assert bridge.flush_count >= 1


class _RuntimeFallbackSub:
    def __init__(self, channels, cb):  # noqa: D401
        self.channels = channels
        self.cb = cb
        self.fallback = False

    def start(self):
        # 模拟启动成功后很快断线
        def _flip():
            time.sleep(0.02)
            self.fallback = True

        import threading

        threading.Thread(target=_flip, daemon=True).start()

    def stop(self):
        pass


def test_event_bridge_runtime_fallback_detected():
    before = metrics.counters.get("redis_fallback", 0)
    batches = []
    event_bus.subscribe(FRONTEND_SNAPSHOT_BATCH_TOPIC, lambda t, p: batches.append(p))
    bridge = EventBridge(
        flush_interval_ms=20,
        use_redis=True,
        redis_subscriber_factory=lambda ch, cb: _RuntimeFallbackSub(ch, cb),
    )
    bridge.start()
    # 等待 runtime fallback 触发
    time.sleep(0.08)
    # 发布事件, 由于已 fallback 到本地应被聚合
    event_bus.publish(BACKEND_SNAPSHOT_TOPIC, {"symbol": "Y", "last": 10, "ts": 1, "snapshot_id": "sy"})
    time.sleep(0.06)
    bridge.stop()
    after = metrics.counters.get("redis_fallback", 0)
    assert after >= before + 1, f"runtime fallback metric not incremented (before={before}, after={after})"
    assert any(b["count"] >= 1 for b in batches), "No batch flushed after runtime fallback"
