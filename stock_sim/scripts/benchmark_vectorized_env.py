#!/usr/bin/env python
"""benchmark_vectorized_env (Req7)

评估向量化环境包装 (VectorizedEnvWrapper) 在随机策略下的 step 吞吐。

支持两类底层环境:
  legacy  -> LegacyTradingEnv (单标的盘口/账户简化环境)
  event   -> EventTradingEnv   (多标的事件节点权重环境)

指标输出:
  steps_total, envs, symbols, elapsed_sec, steps_per_sec_env (每环境秒步数), batch_steps_per_sec

用法示例:
  python -m scripts.benchmark_vectorized_env --env legacy --envs 8 --steps 500
  python -m scripts.benchmark_vectorized_env --env event  --envs 4 --symbols 6 --steps 300

参数:
  --env {legacy,event}
  --envs N           环境数量 (默认 4)
  --steps S          基准步数 (默认 1000)
  --symbols K        event 模式下符号数 (默认 4)
  --lookback L       event 模式回看节点数 (默认 10)
  --seed SEED        随机种子 (默认 42)

说明:
  - 动作为均匀随机/正态截断 (legacy: 3 维, event: K 维)
  - bars 使用简化随机几何布朗生成 (非金融精确模拟, 仅供性能测试)
  - 事件节点 provider 简化为固定间隔采样
"""
from __future__ import annotations
import argparse
import numpy as np
import time
from typing import List, Dict

try:
    from stock_sim.rl.trading_env import LegacyTradingEnv, EventTradingEnv, EnvConfig  # type: ignore
    from stock_sim.rl.vectorized_env import VectorizedEnvWrapper  # type: ignore
    from stock_sim.core.matching_engine import MatchingEngine  # type: ignore
    from stock_sim.core.order import Order  # type: ignore
    from stock_sim.core.const import OrderSide, OrderType, TimeInForce  # type: ignore
except Exception:  # 源码根目录回退
    from rl.trading_env import LegacyTradingEnv, EventTradingEnv, EnvConfig  # type: ignore
    from rl.vectorized_env import VectorizedEnvWrapper  # type: ignore
    from core.matching_engine import MatchingEngine  # type: ignore
    from core.order import Order  # type: ignore
    from core.const import OrderSide, OrderType, TimeInForce  # type: ignore

# 新增: DummyOrderService (避免 DB 依赖与锁)
class DummyOrderService:
    def __init__(self, engine: MatchingEngine):
        self.engine = engine
    def place_order(self, order: Order):  # 最小接口
        self.engine.submit_order(order)
        return []

# ---------------- 工具函数 ----------------
class _DummyInstrument:
    tick_size = 0.01
    lot_size = 100
    min_qty = 100
    settlement_cycle = 0
    market_cap = 1_000_000_000
    total_shares = 100_000_000
    free_float_shares = 80_000_000
    initial_price = 100.0

def _make_legacy_env(symbol: str):
    inst = _DummyInstrument()
    engine = MatchingEngine(symbol, inst)
    # 预置简单盘口深度 (仅内存)
    osvc = DummyOrderService(engine)
    for i in range(5):
        px = 100 - i * 0.01
        o = Order(symbol=symbol, side=OrderSide.BUY, price=px, quantity=100, order_type=OrderType.LIMIT, tif=TimeInForce.GFD)
        engine.submit_order(o)
    for i in range(5):
        px = 100 + i * 0.01
        o = Order(symbol=symbol, side=OrderSide.SELL, price=px, quantity=100, order_type=OrderType.LIMIT, tif=TimeInForce.GFD)
        engine.submit_order(o)
    env = LegacyTradingEnv(engine, osvc, account_id="ACC", symbol=symbol)
    return env

def _gbm_series(T: int, start: float = 100.0, mu=0.0, sigma=0.02, seed=0):
    rng = np.random.default_rng(seed)
    dt = 1.0 / 252
    prices = [start]
    for _ in range(T - 1):
        drift = (mu - 0.5 * sigma * sigma) * dt
        shock = sigma * np.sqrt(dt) * rng.standard_normal()
        prices.append(prices[-1] * np.exp(drift + shock))
    return np.array(prices, dtype=float)

def _make_event_env(symbols: List[str], lookback: int, seed: int):
    T = 2000  # 节点基础长度
    bars: Dict[str, np.ndarray] = {}
    rng = np.random.default_rng(seed)
    for i,sym in enumerate(symbols):
        px = _gbm_series(T, start=100 + i, sigma=0.03, seed=seed + i)
        vol = rng.integers(low=1000, high=5000, size=T)
        ts = np.arange(T) * 60_000  # 伪时间戳 (ms)
        o = px * (1 - 0.001)
        h = px * (1 + 0.002)
        l = px * (1 - 0.002)
        arr = np.stack([ts, o, h, l, px, vol], axis=0).T
        bars[sym] = arr
    def bars_provider(_syms: List[str]):
        return {s: bars[s] for s in _syms}
    def event_nodes_provider(_bars: Dict[str, np.ndarray]):
        # 固定间隔抽样: 每 10 根一个节点
        length = min(a.shape[0] for a in _bars.values())
        return list(range(0, length, 10))
    cfg = EnvConfig(symbols=symbols, lookback_nodes=lookback)
    env = EventTradingEnv(cfg, bars_provider=bars_provider, event_nodes_provider=event_nodes_provider, seed=seed)
    return env

# ---------------- 基准逻辑 ----------------

def run_benchmark(env_kind: str, n_envs: int, steps: int, symbols: int, lookback: int, seed: int):
    rng = np.random.default_rng(seed)
    if env_kind == 'legacy':
        envs = [_make_legacy_env(f"SYM{i+1}") for i in range(n_envs)]
        for e in envs:
            e.reset()
        act_dim = 3
    else:
        syms = [f"S{i+1}" for i in range(symbols)]
        envs = [_make_event_env(syms, lookback, seed + i) for i in range(n_envs)]
        for e in envs:
            e.reset()
        act_dim = symbols
    vec = VectorizedEnvWrapper(envs)
    # 预热
    obs0 = vec.reset()
    assert obs0.shape[0] == n_envs
    t0 = time.perf_counter()
    total_steps = 0
    for _ in range(steps):
        if env_kind == 'legacy':
            a = np.column_stack([
                rng.uniform(-1, 1, size=n_envs),
                rng.uniform(0, 1, size=n_envs),
                rng.uniform(0, 1, size=n_envs),
            ]).astype(np.float32)
        else:
            a = rng.uniform(-1, 1, size=(n_envs, act_dim)).astype(np.float32)
        obs, rew, done, infos = vec.step(a)
        total_steps += n_envs
    elapsed = time.perf_counter() - t0
    return {
        'env_kind': env_kind,
        'envs': n_envs,
        'symbols': symbols if env_kind == 'event' else 1,
        'steps_each': steps,
        'steps_total': total_steps,
        'elapsed_sec': round(elapsed, 4),
        'batch_steps_per_sec': round((steps) / elapsed, 2),
        'steps_per_sec_env': round((steps) / elapsed / n_envs, 2),
    }

# ---------------- main ----------------

def main():
    ap = argparse.ArgumentParser(description='Benchmark vectorized RL environments')
    ap.add_argument('--env', choices=['legacy','event'], default='legacy')
    ap.add_argument('--envs', type=int, default=4)
    ap.add_argument('--steps', type=int, default=1000)
    ap.add_argument('--symbols', type=int, default=4)
    ap.add_argument('--lookback', type=int, default=10)
    ap.add_argument('--seed', type=int, default=42)
    args = ap.parse_args()
    res = run_benchmark(args.env, args.envs, args.steps, args.symbols, args.lookback, args.seed)
    print('[benchmark_vectorized_env]', res)

if __name__ == '__main__':  # pragma: no cover
    main()
