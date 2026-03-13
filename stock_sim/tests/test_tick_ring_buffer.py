from datetime import datetime, timedelta
import threading

from core.ring_buffer import RingBuffer, TickAggregator
from services.market_data_query_service import TickDTO

def make_tick(i: int) -> TickDTO:
    base = datetime(2025,1,1)
    return TickDTO(
        ts=base + timedelta(seconds=i),
        last=float(i),
        volume=i,
        turnover=float(i)*10.0,
        change_pct=None,
        change_speed=None,
        volume_delta=None,
        turnover_delta=None,
        turnover_rate=None,
        spread=None,
        imbalance=None,
        trade_count_sec=None,
        vwap=None,
    )

def test_ring_buffer_eviction_and_order():
    rb = RingBuffer[int](capacity=3)
    assert rb.append(1) is None
    assert rb.append(2) is None
    assert rb.append(3) is None  # 满
    ev = rb.append(4)
    assert ev == 1  # 淘汰最旧
    ev = rb.append(5)
    assert ev == 2
    # 顺序应该是 3,4,5
    snap = rb.snapshot()
    assert snap == [3,4,5]
    # get 按序
    assert rb.get(0) == 3
    assert rb.get(2) == 5


def test_tick_aggregator_basic():
    agg = TickAggregator(capacity=3)
    for i in range(1,4):
        agg.append(make_tick(i))
    assert agg.size() == 3
    # last 平均: (1+2+3)/3
    assert abs(agg.avg_last_price() - 2.0) < 1e-9
    assert agg.total_volume() == 1+2+3
    assert abs(agg.total_turnover() - (1+2+3)*10.0) < 1e-9

    # 追加新 tick 触发淘汰 1
    agg.append(make_tick(4))
    # 应该是 2,3,4
    snap = agg.snapshot()
    assert [int(t.last) for t in snap] == [2,3,4]
    # 平均: (2+3+4)/3=3
    assert abs(agg.avg_last_price() - 3.0) < 1e-9
    assert agg.total_volume() == 2+3+4
    assert abs(agg.total_turnover() - (2+3+4)*10.0) < 1e-9


def test_thread_safety_light():
    agg = TickAggregator(capacity=50)
    N = 1000
    def worker(offset: int):
        for k in range(N):
            agg.append(make_tick(offset + k))
    threads = [threading.Thread(target=worker, args=(i*10000,)) for i in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    # 容量 clamp
    assert agg.size() == 50
    # 平均值与快照一致
    snap = agg.snapshot()
    assert len(snap) == 50
    av = agg.avg_last_price()
    if av is not None:
        calc = sum(t.last for t in snap if t.last is not None)/len([t for t in snap if t.last is not None])
        assert abs(av - calc) < 1e-9

