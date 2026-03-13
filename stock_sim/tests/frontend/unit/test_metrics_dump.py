from app.utils.metrics_adapter import dump_metrics, reset_metrics
from observability.metrics import metrics


def test_dump_metrics_and_reset_behavior():
    reset_metrics()
    metrics.inc('test_counter', 3)
    metrics.add_timing('latency.render', 5.0)
    metrics.add_timing('latency.render', 7.0)

    data = dump_metrics()
    assert 'ts' in data and isinstance(data['ts'], int)
    assert data['counters']['test_counter'] == 3
    assert 'latency.render' in data['timings']
    t = data['timings']['latency.render']
    # 基本统计存在
    for k in ('p50', 'p95', 'p99', 'count'):
        assert k in t
    assert t['count'] == 2.0

    # reset=True 生效
    metrics.inc('another', 2)
    data2 = dump_metrics(reset=True)
    assert 'another' in data2['counters']
    # 再次导出应无 another (已 reset)
    empty_after_reset = dump_metrics()
    assert 'another' not in empty_after_reset['counters']

