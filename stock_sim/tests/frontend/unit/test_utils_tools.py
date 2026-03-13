from app.utils import Throttle, RingBuffer
import time


def test_throttle_leading_and_trailing():
    calls = []
    th = Throttle(50, lambda x: calls.append(x), metrics_prefix="test_thr")
    th.submit(1)
    for i in range(2, 6):
        th.submit(i)
    assert calls == [1]
    assert th.dropped_count == 4
    assert th.has_pending
    flushed = th.flush_pending()
    assert not flushed
    time.sleep(0.06)
    flushed = th.flush_pending()
    assert flushed
    assert calls == [1, 5]
    assert th.executed_count == 2


def test_throttle_force_flush():
    calls = []
    th = Throttle(100, lambda x: calls.append(x))
    th.submit(1)
    th.submit(2)
    assert calls == [1]
    th.flush_pending(force=True)
    assert calls == [1, 2]


def test_ring_buffer_basic():
    rb = RingBuffer[int](3, metrics_prefix="test_ring")
    assert rb.capacity == 3
    assert rb.size == 0
    rb.append(1)
    rb.append(2)
    rb.append(3)
    assert rb.size == 3
    assert rb.to_list() == [1, 2, 3]
    ev = rb.append(4)
    assert ev == 1
    assert rb.to_list() == [2, 3, 4]
    ev2 = rb.append(5)
    assert ev2 == 2
    assert rb.to_list() == [3, 4, 5]
    rb.extend([6, 7])
    assert rb.to_list() == [5, 6, 7]
    rb.clear()
    assert rb.to_list() == []
    assert rb.size == 0
