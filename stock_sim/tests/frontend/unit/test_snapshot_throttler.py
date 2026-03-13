import types
from app.utils.snapshot_throttler import SnapshotThrottler
from observability.metrics import metrics


def test_snapshot_throttler_50_events_per_second_max_10_refresh(monkeypatch):
    # 准备: 伪造 perf_counter 时间轴
    class FakeClock:
        def __init__(self):
            self.t = 1000.0
        def advance(self, dt: float):
            self.t += dt
        def perf_counter(self):
            return self.t
    clock = FakeClock()
    # patch 目标模块内的 perf_counter
    monkeypatch.setattr("app.utils.snapshot_throttler.time.perf_counter", clock.perf_counter)

    refreshed = []
    def refresh_fn(snap):
        refreshed.append(snap)

    throttler = SnapshotThrottler(refresh_fn, max_refresh_per_sec=10)

    base = metrics.counters.get("snapshot_throttled_refresh", 0)

    # 模拟 1 秒内 50 次事件 (每 0.02s 一个)
    for i in range(50):
        throttler.update({"seq": i})
        clock.advance(0.02)

    # 刷新次数应 <=10 (节流), 也应 >=1
    assert 1 <= throttler.refresh_count <= 10
    assert len(refreshed) == throttler.refresh_count
    assert metrics.counters.get("snapshot_throttled_refresh", 0) == base + throttler.refresh_count

    # 验证最后一次刷新内容接近末尾 (>=40 确保合并后仍拿到最新)
    assert refreshed[-1]["seq"] >= 40  # 最近批次的��后一个覆盖
