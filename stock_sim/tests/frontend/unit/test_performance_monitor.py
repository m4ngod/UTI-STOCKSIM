from observability.performance_monitor import PerformanceMonitor
from observability.metrics import metrics
import time

def test_performance_monitor_basic_section_flush():
    pm = PerformanceMonitor(flush_interval_ms=10, auto_start=False)
    before_keys = set(metrics.timings.keys())
    with pm.section('ui_freeze.block'):
        time.sleep(0.01)
    with pm.section('ui_freeze.block'):
        time.sleep(0.005)
    pm.flush()
    # 验证产生新 timing key
    new_keys = set(metrics.timings.keys()) - before_keys
    assert any(k.startswith('perf::ui_freeze.block') for k in new_keys) or 'perf::ui_freeze.block' in metrics.timings
    # 验证计数累加
    cnt = metrics.counters.get('perf_count::ui_freeze.block', 0)
    assert cnt == 2


def test_performance_monitor_disabled():
    pm = PerformanceMonitor(enabled=False, auto_start=False)
    before = dict(metrics.timings)
    with pm.section('ui_freeze.nouse'):
        time.sleep(0.002)
    pm.flush()
    # 不应新增 timing
    assert set(metrics.timings.keys()) == set(before.keys())

