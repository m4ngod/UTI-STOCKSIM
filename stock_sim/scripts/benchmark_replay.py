#!/usr/bin/env python
"""benchmark_replay (Req2)

目标: 评估事件持久化与回放服务在本地 sqlite (测试默认) 下的插入与读取/回放吞吐。

指标:
  - insert_events_per_sec
  - load_events_per_sec (ReplayService.load_events)
  - replay_events_per_sec (ReplayService.replay, no-op apply_fn)
  - total_events
  - db_url (简化输出)

用法:
  python -m scripts.benchmark_replay --events 50000 --batch-size 1000
  python -m scripts.benchmark_replay --events 20000 --skip-generate 1  # 仅对已有数据回放

参数:
  --events N          生成事件数量 (默认 20000)
  --batch-size B      插入批大小 (默认 1000)
  --seed S            随机种子 (默认 42)
  --skip-generate {0,1}  跳过生成 (仅回放测试)
  --type TYPE         事件类型 (默认 Trade)

实现说明:
  - 事件行使用 EventLog ORM, payload 为最小 JSON 字符串。
  - ts_ms 单调递增 (基于起始时间 + i)。
  - 回放使用 no-op lambda 评估纯调度开销。

"""
from __future__ import annotations
import argparse
import json
import random
import time
from typing import List

try:
    from stock_sim.persistence.models_imports import SessionLocal
    from stock_sim.persistence.models_event_log import EventLog
    from stock_sim.persistence import models_init  # type: ignore
    from stock_sim.services.replay_service import replay_service
    from stock_sim.settings import settings
except Exception:  # fallback 源码根目录
    from persistence.models_imports import SessionLocal  # type: ignore
    from persistence.models_event_log import EventLog  # type: ignore
    from persistence import models_init  # type: ignore
    from services.replay_service import replay_service  # type: ignore
    from settings import settings  # type: ignore


def _generate(events: int, batch_size: int, ev_type: str) -> float:
    s = SessionLocal()
    start_ts = int(time.time() * 1000)
    t0 = time.perf_counter()
    try:
        # 清空表 (仅 sqlite 测试环境; 若想保留旧数据可注释)
        s.query(EventLog).delete()
        s.commit()
        rows: List[EventLog] = []
        for i in range(events):
            payload = json.dumps({
                'idx': i,
                'side': 'B' if (i & 1) == 0 else 'S',
                'px': 100 + (i % 100) * 0.01,
                'qty': 100,
            })
            rows.append(EventLog(ts_ms=start_ts + i, type=ev_type, symbol='SYM', payload=payload, shard=0))
            if len(rows) >= batch_size:
                s.add_all(rows); s.commit(); rows.clear()
        if rows:
            s.add_all(rows); s.commit()
    finally:
        s.close()
    return time.perf_counter() - t0


def _bench_load() -> float:
    t0 = time.perf_counter()
    evs = replay_service.load_events()
    elapsed = time.perf_counter() - t0
    return elapsed, len(evs)


def _bench_replay() -> float:
    t0 = time.perf_counter()
    n = replay_service.replay(lambda _e: None)
    elapsed = time.perf_counter() - t0
    return elapsed, n


def main():
    parser = argparse.ArgumentParser(description='Benchmark event log replay throughput')
    parser.add_argument('--events', type=int, default=20000)
    parser.add_argument('--batch-size', type=int, default=1000)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--skip-generate', type=int, default=0)
    parser.add_argument('--type', type=str, default='Trade')
    args = parser.parse_args()
    random.seed(args.seed)
    # 初始化模型 (确保 event_log 存在)
    try:
        models_init.init_models()
    except Exception:
        pass
    inserted = 0
    gen_elapsed = 0.0
    if not args.skip_generate:
        gen_elapsed = _generate(args.events, args.batch_size, args.type)
        inserted = args.events
    load_elapsed, loaded = _bench_load()
    replay_elapsed, replayed = _bench_replay()
    res = {
        'db_url': settings.assembled_db_url(),
        'generated': inserted,
        'gen_elapsed_sec': round(gen_elapsed, 4),
        'insert_events_per_sec': round(inserted / gen_elapsed, 2) if gen_elapsed > 0 else None,
        'loaded': loaded,
        'load_elapsed_sec': round(load_elapsed, 4),
        'load_events_per_sec': round(loaded / load_elapsed, 2) if load_elapsed > 0 else None,
        'replayed': replayed,
        'replay_elapsed_sec': round(replay_elapsed, 4),
        'replay_events_per_sec': round(replayed / replay_elapsed, 2) if replay_elapsed > 0 else None,
    }
    print('[benchmark_replay]', res)

if __name__ == '__main__':  # pragma: no cover
    main()

