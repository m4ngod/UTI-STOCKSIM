import threading
from core.ring_buffer import RingBuffer


def test_ring_buffer_concurrency_overflow_order_maintained():
    capacity = 64
    total = 10_000
    rb = RingBuffer[int](capacity=capacity)

    counter = {"v": 0}
    lock = threading.Lock()

    def worker():
        while True:
            with lock:
                if counter["v"] >= total:
                    return
                idx = counter["v"]
                counter["v"] += 1
            rb.append(idx)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(rb) == capacity
    snap = rb.snapshot()
    # 应为最后 capacity 个递增整数
    expected_start = total - capacity
    assert snap == list(range(expected_start, total)), f"order mismatch: got head={snap[0]} expected {expected_start}"  # 顺序 & 内容
    # 进一步确认严格递增
    assert all(snap[i] + 1 == snap[i+1] for i in range(len(snap)-1))


def test_ring_buffer_concurrency_capacity_one():
    rb = RingBuffer[int](capacity=1)
    total = 5000
    counter = {"v": 0}
    lock = threading.Lock()

    def worker():
        while True:
            with lock:
                if counter["v"] >= total:
                    return
                idx = counter["v"]
                counter["v"] += 1
            rb.append(idx)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert len(rb) == 1
    snap = rb.snapshot()
    assert snap == [total - 1]

