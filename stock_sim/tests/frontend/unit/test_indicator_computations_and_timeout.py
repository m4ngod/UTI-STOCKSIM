import math
from observability.metrics import metrics
from app.indicators.registry import IndicatorRegistry
from app.indicators.executor import IndicatorExecutor, time as _exec_time_mod
import numpy as np
from concurrent.futures import Future


def test_indicator_ma_deterministic():
    reg = IndicatorRegistry()
    from app.indicators.ma import indicator_ma  # reuse real impl
    reg.register('ma', indicator_ma)
    data = [1,2,3,4,5]
    out = reg.compute('ma', data, window=3)
    # 预期: [nan,nan,2,3,4]
    assert len(out) == 5
    assert math.isnan(out[0]) and math.isnan(out[1])
    assert out[2] == 2 and out[3] == 3 and out[4] == 4


def test_indicator_rsi_deterministic():
    reg = IndicatorRegistry()
    from app.indicators.rsi import indicator_rsi
    reg.register('rsi', indicator_rsi)
    # 构造小序列, 手工计算期望
    data = [1,2,3,2,1,2]
    out = reg.compute('rsi', data, period=3)
    # 期望 RSI 值位置 >= period: 66.6667, 44.4444, 62.963  (允许 1e-3 误差)
    exp = [math.nan, math.nan, math.nan, 66.6666667, 44.4444444, 62.9629629]
    assert len(out) == 6
    for i,(a,b) in enumerate(zip(out, exp)):
        if math.isnan(b):
            assert math.isnan(a)
        else:
            assert abs(a-b) < 1e-3, f"idx {i} got {a} exp {b}"


def test_indicator_macd_basic_shapes():
    reg = IndicatorRegistry()
    from app.indicators.macd import indicator_macd
    reg.register('macd', indicator_macd)
    data = [1,2,3,4,5]
    res = reg.compute('macd', data, fast=2, slow=4, signal=2)
    assert set(res.keys()) == {'macd','signal','hist'}
    for k,v in res.items():
        assert len(v) == len(data)
        # 值应为浮点且不含 nan (短序列 EMA 算法不产生 NaN)
        assert all(not math.isnan(x) for x in v)


def test_indicator_timeout_monkeypatched_no_sleep():
    # 构造 registry 与一个普通指标 (快速完成)
    reg = IndicatorRegistry()
    from app.indicators.ma import indicator_ma
    reg.register('ma', indicator_ma)
    execu = IndicatorExecutor(reg, max_workers=1)

    # fake perf_counter
    fake_time = {'t': 0.0}
    orig_perf = _exec_time_mod.perf_counter
    _exec_time_mod.perf_counter = lambda: fake_time['t']  # type: ignore

    # monkeypatch 提交逻辑: 返回一个永不完成的 Future 模拟长任务
    orig_submit = execu._pool.submit  # type: ignore[attr-defined]
    pending_futures = []
    def fake_submit(fn):  # noqa: D401
        fut = Future()
        pending_futures.append(fut)
        return fut
    execu._pool.submit = fake_submit  # type: ignore

    callbacks = []
    def cb(res, **meta):  # 不应被调用
        callbacks.append(res)

    base = metrics.counters.get('indicator_timeout', 0)
    # 提交 (记录 submit_ts=0)
    execu.submit('ma', [1,2,3,4,5], window=2, callback=cb, timeout_ms=5)
    # 推进时间到超时 (6ms)
    fake_time['t'] = 0.006
    # 轮询一次 -> 应超时
    executed = execu.poll_callbacks()
    assert executed == 0
    assert metrics.counters.get('indicator_timeout', 0) == base + 1
    assert not callbacks
    assert execu.pending_count() == 0

    # 清理: 还原 monkeypatch
    execu._pool.submit = orig_submit  # type: ignore
    _exec_time_mod.perf_counter = orig_perf  # type: ignore
    execu.shutdown()

