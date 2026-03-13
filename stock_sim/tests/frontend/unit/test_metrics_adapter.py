from app.utils.metrics_adapter import snapshot, flush_metrics, reset_metrics, set_logger
from observability.metrics import metrics

class _DummyLogger:
    def __init__(self):
        self.records = []
    def log(self, category: str, **fields):
        self.records.append((category, fields))


def test_flush_with_metrics_and_reason():
    reset_metrics()
    dummy = _DummyLogger()
    set_logger(dummy)
    metrics.inc('test_counter')
    metrics.add_timing('latency.render', 10.0)
    payload = flush_metrics(reason='unit')
    assert payload is not None
    assert 'test_counter' in payload['counters']
    assert 'latency.render' in payload['timings']
    t = payload['timings']['latency.render']
    # 单点统计: p50=p95=p99=10.0, count=1
    assert t['p50'] == t['p95'] == t['p99'] == 10.0
    assert t['count'] == 1.0
    # 日志写入
    assert dummy.records and dummy.records[-1][0] == 'metrics'
    assert dummy.records[-1][1]['reason'] == 'unit'


def test_flush_empty_forced():
    reset_metrics()
    dummy = _DummyLogger()
    set_logger(dummy)
    # 非 forced 情况下为空返回 None
    assert flush_metrics(reason='empty') is None
    # forced 输出空结构
    payload = flush_metrics(forced=True, reason='forced')
    assert payload is not None
    assert payload['counters'] == {}
    assert payload['timings'] == {}
    assert dummy.records[-1][1]['reason'] == 'forced'

