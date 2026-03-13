import time
from app.event_bridge import EventBridge, BACKEND_SNAPSHOT_TOPIC
from infra.event_bus import event_bus
from observability.metrics import metrics

class _RuntimeFallbackSub:
    def __init__(self, channels, cb):  # noqa: D401
        self.channels = channels
        self.cb = cb
        self.fallback = False
    def start(self):
        # 模拟启动成功后很快断线
        def _flip():
            time.sleep(0.01)
            self.fallback = True
        import threading
        threading.Thread(target=_flip, daemon=True).start()
    def stop(self):
        pass

def test_event_bridge_redis_start_failure_fallback():
    base = metrics.counters.get('redis_fallback', 0)
    def bad_factory(channels, cb):  # noqa: ARG001
        raise RuntimeError('redis connect fail')
    br = EventBridge(use_redis=True, redis_subscriber_factory=bad_factory, flush_interval_ms=10)
    br.start()
    time.sleep(0.03)  # 等待启动失败处理
    # 发布后端事件应因本地订阅生效而被聚合
    event_bus.publish(BACKEND_SNAPSHOT_TOPIC, {'p':1})
    time.sleep(0.05)
    br.stop()
    assert metrics.counters.get('redis_fallback', 0) >= base + 1
    assert br.flush_count >= 1


def test_event_bridge_runtime_fallback():
    base = metrics.counters.get('redis_fallback', 0)
    br = EventBridge(use_redis=True, redis_subscriber_factory=lambda ch, cb: _RuntimeFallbackSub(ch, cb), flush_interval_ms=10)
    br.start()
    # 等待 fallback 切换
    time.sleep(0.05)
    event_bus.publish(BACKEND_SNAPSHOT_TOPIC, {'p':2})
    time.sleep(0.05)
    br.stop()
    assert metrics.counters.get('redis_fallback', 0) >= base + 1
    assert br.flush_count >= 1

