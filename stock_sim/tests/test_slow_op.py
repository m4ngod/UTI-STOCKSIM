import time
from observability.metrics import metrics, slow_op


def test_slow_op_basic_increment():
    # 清理旧计数
    metrics.counters.pop('slow_op::demo', None)

    @slow_op('demo', 5)  # 5ms 阈值
    def work():
        time.sleep(0.010)  # 10ms > 5ms

    work()
    assert metrics.counters.get('slow_op::demo', 0) >= 1


def test_slow_op_exception_path_still_counts():
    base = metrics.counters.get('slow_op::demo_exc', 0)

    @slow_op('demo_exc', 1)
    def boom():
        time.sleep(0.003)  # 3ms > 1ms
        raise RuntimeError('x')

    try:
        boom()
    except RuntimeError:
        pass
    assert metrics.counters.get('slow_op::demo_exc', 0) == base + 1

