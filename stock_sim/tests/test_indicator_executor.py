import time
import numpy as np
from app.indicators.executor import IndicatorExecutor
from app.indicators import indicator_registry


def test_indicator_executor_batch_and_error():
    execu = IndicatorExecutor(indicator_registry, max_workers=8)
    results = []

    def cb(res, *, symbol, name, params, error, duration_ms, cache_key):  # noqa: D401
        results.append({
            'symbol': symbol,
            'name': name,
            'params': params,
            'error': error,
            'duration_ms': duration_ms,
            'cache_key': cache_key,
            'is_macd': isinstance(res, dict) and set(res.keys()) == {'macd', 'signal', 'hist'},
            'length': len(res['macd']) if isinstance(res, dict) else len(res) if res is not None else None,
        })

    symbols = [f'S{i}' for i in range(5)]
    arrs = {s: np.random.random(1200).astype(np.float64) * 100 for s in symbols}

    start = time.perf_counter()
    # 提交 5 * 3 = 15 个正常任务
    for s in symbols:
        execu.submit('ma', arrs[s], symbol=s, window=20, callback=cb)
        execu.submit('rsi', arrs[s], symbol=s, period=14, callback=cb)
        execu.submit('macd', arrs[s], symbol=s, fast=12, slow=26, signal=9, callback=cb)
    # 额外一个错误任务 (window=0)
    execu.submit('ma', arrs[symbols[0]], symbol=symbols[0], window=0, callback=cb)

    # 轮询直至全部完成 (15 + 1 错误)
    expected = 16
    deadline = time.perf_counter() + 2.0  # 2s 超时
    while len(results) < expected and time.perf_counter() < deadline:
        execu.poll_callbacks()
        time.sleep(0.01)

    wall_ms = (time.perf_counter() - start) * 1000
    execu.shutdown()

    assert len(results) == expected, f"expected {expected} results got {len(results)}"
    # 校验 macd 结果长度匹配输入
    macd_rows = [r for r in results if r['name'] == 'macd']
    assert macd_rows and all(r['is_macd'] for r in macd_rows)
    length_ref = arrs[symbols[0]].shape[0]
    assert all(r['length'] == length_ref for r in macd_rows)
    # 错误任务存在且 error 不为 None
    err_rows = [r for r in results if r['name'] == 'ma' and r['params'].get('window') == 0]
    assert len(err_rows) == 1 and err_rows[0]['error'] is not None
    # 性能: 总墙钟时间 (包含调度) 应显著低于 1s, 并接近 spec (≤200ms 给一定裕量)
    assert wall_ms < 1000, f"batch execution too slow: {wall_ms:.2f}ms"

