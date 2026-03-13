from app.utils.snapshot_throttler import SnapshotThrottler
from observability.metrics import metrics


def test_snapshot_throttle_integration_high_rate_with_fake_time(monkeypatch):
    """集成式: 模拟 1 秒内高频(100Hz)快照事件, max_refresh_per_sec=8;
    验证刷新次数受限 (<=8+1) 且最后一次刷新接近末尾事件。"""
    class FakeClock:
        def __init__(self):
            self.t = 5000.0  # 任意起点
        def advance(self, dt: float):
            self.t += dt
        def perf_counter(self):
            return self.t
    clock = FakeClock()
    monkeypatch.setattr("app.utils.snapshot_throttler.time.perf_counter", clock.perf_counter)

    refreshed = []
    def refresh_fn(snap):
        refreshed.append(snap)

    throttler = SnapshotThrottler(refresh_fn, max_refresh_per_sec=8)
    base = metrics.counters.get("snapshot_throttled_refresh", 0)

    # 1 秒内 100 次事件 (每 0.01s) -> 期望刷新次数 <= 8 (间隔 0.125s) + 首次立即 (最多 9)
    for i in range(100):
        throttler.update({"seq": i})
        clock.advance(0.01)

    assert 1 <= throttler.refresh_count <= 9
    assert len(refreshed) == throttler.refresh_count
    assert metrics.counters.get("snapshot_throttled_refresh", 0) == base + throttler.refresh_count
    # 最终刷新应包含接近末尾的序号 (>=90 确保覆盖最新)
    assert refreshed[-1]["seq"] >= 90

