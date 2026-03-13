from app.security import ScriptUploadRateLimiter
from observability.metrics import metrics

class _Time:
    def __init__(self, t: float = 0.0):
        self.t = t
    def now(self):
        return self.t
    def advance(self, sec: float):
        self.t += sec


def test_rate_limiter_basic_window():
    tm = _Time(1000.0)
    rl = ScriptUploadRateLimiter(limit=3, window_seconds=3600, time_fn=tm.now)
    key = 'strategy_alpha'
    # 前三次允许
    assert rl.allow(key) is True
    assert rl.allow(key) is True
    assert rl.allow(key) is True
    # 第四次拒绝
    assert rl.allow(key) is False
    # 剩余配额 0
    assert rl.get_remaining(key) == 0
    # 前进时间 1 小时 - 1 秒仍然拒绝
    tm.advance(3599)
    assert rl.allow(key) is False
    # 再前进 2 秒 (超窗) -> 旧记录过期，可再次允许
    tm.advance(2)
    assert rl.allow(key) is True
    # 剩余 2 次 (因为窗口内仅一条)
    assert rl.get_remaining(key) == 2


def test_rate_limiter_metrics_counts():
    tm = _Time(0)
    rl = ScriptUploadRateLimiter(limit=2, window_seconds=10, time_fn=tm.now)
    key = 'k'
    base_attempt = metrics.counters.get('script_upload_attempt', 0)
    base_allowed = metrics.counters.get('script_upload_allowed', 0)
    base_limited = metrics.counters.get('script_upload_rate_limited', 0)

    assert rl.allow(key) is True
    assert rl.allow(key) is True
    # 超限
    assert rl.allow(key) is False

    assert metrics.counters.get('script_upload_attempt', 0) >= base_attempt + 3
    assert metrics.counters.get('script_upload_allowed', 0) >= base_allowed + 2
    assert metrics.counters.get('script_upload_rate_limited', 0) >= base_limited + 1

