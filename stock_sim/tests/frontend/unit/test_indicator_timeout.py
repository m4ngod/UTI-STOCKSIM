import time
from app.indicators.executor import IndicatorExecutor
from app.indicators.registry import IndicatorRegistry
from observability.metrics import metrics
import numpy as np


def test_indicator_timeout_metric_and_skip_callback():
    reg = IndicatorRegistry()

    # 注册一个耗时指标: 睡眠 delay 秒
    def slow_indicator(arr, params):  # noqa: D401
        delay = params.get('delay', 0.05)
        time.sleep(delay)
        return arr  # 返回原数组

    reg.register('sleep', slow_indicator)

    execu = IndicatorExecutor(reg, max_workers=2)

    callbacks = []

    def cb(res, *, symbol, name, params, error, duration_ms, cache_key):  # noqa: D401
        callbacks.append({'res': res, 'name': name, 'error': error})

    base = metrics.counters.get('indicator_timeout', 0)
    data = np.random.random(20)
    # 设置 delay=0.05s; timeout 10ms -> 必然超时
    execu.submit('sleep', data, delay=0.05, callback=cb, timeout_ms=10)

    deadline = time.perf_counter() + 0.2
    # 周期轮询, 触发超时检测
    while time.perf_counter() < deadline:
        execu.poll_callbacks()
        if metrics.counters.get('indicator_timeout', 0) > base:
            break
        time.sleep(0.005)

    # 验证 timeout 计数增加
    assert metrics.counters.get('indicator_timeout', 0) == base + 1
    # 回调不应执行
    assert not callbacks
    # pending 列表被清理
    assert execu.pending_count() == 0
    execu.shutdown()

