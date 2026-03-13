# python
"""snapshot_service.py

按模拟日(SIM_DAY)周期生成 RDB 风格快照 (JSON 压缩文件)。
配置:
  settings.SNAPSHOT_ENABLE: 总开关
  settings.SNAPSHOT_INTERVAL_DAYS: 每隔多少个模拟日生成一次
  settings.SNAPSHOT_DIR: 输出目录 (自动创建)

快照内容 (Schema v1):
  meta: { day, generated_at, interval, version }
  engine: [ { symbol, last_price, best_bid, best_ask, bid_levels, ask_levels } ]
  accounts: [ { id, cash, frozen_cash, frozen_fee } ]
  positions: [ { account_id, symbol, quantity, frozen_qty, avg_price } ]
  instruments: [ { symbol, name, tick_size, lot_size, min_qty, settlement_cycle, initial_price, free_float_shares } ]

注意: 仅做读操作/文件输出，避免阻塞 SIM_DAY 事件线程，使用后台线程执行实际 dump。
"""
from __future__ import annotations
import os, json, gzip, threading, time
from datetime import datetime
from typing import Any

from stock_sim.settings import settings
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_account import Account
from stock_sim.persistence.models_position import Position
from stock_sim.persistence.models_instrument import Instrument
from stock_sim.persistence.models_order import OrderORM
from stock_sim.persistence.models_trade import TradeORM
from FE.engine_registry import engine_registry

_SNAPSHOT_VERSION = 1
_started = False
_lock = threading.Lock()


def _safe_mkdir(path: str):
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass

def _collect_engine_state():
    data = []
    for sym in engine_registry.symbols():
        eng = engine_registry.get(sym)
        if not eng:
            continue
        try:
            snap = eng.get_book(sym).snapshot if hasattr(eng, 'get_book') else eng.snapshot
        except Exception:
            snap = getattr(eng, 'snapshot', None)
        rec = {
            'symbol': sym,
            'last_price': getattr(snap, 'last_price', None),
            'best_bid': getattr(snap, 'best_bid_price', None),
            'best_ask': getattr(snap, 'best_ask_price', None),
            'bid_levels': getattr(snap, 'bid_levels', None),
            'ask_levels': getattr(snap, 'ask_levels', None),
        }
        data.append(rec)
    return data

def _collect_db_state(session):
    accounts = [
        {
            'id': a.id,
            'cash': a.cash,
            'frozen_cash': a.frozen_cash,
            'frozen_fee': a.frozen_fee,
        } for a in session.query(Account).all()
    ]
    positions = [
        {
            'account_id': p.account_id,
            'symbol': p.symbol,
            'quantity': p.quantity,
            'frozen_qty': p.frozen_qty,
            'avg_price': p.avg_price,
        } for p in session.query(Position).all()
    ]
    instruments = [
        {
            'symbol': ins.symbol,
            'name': ins.name,
            'tick_size': ins.tick_size,
            'lot_size': ins.lot_size,
            'min_qty': ins.min_qty,
            'settlement_cycle': ins.settlement_cycle,
            'initial_price': ins.initial_price,
            'free_float_shares': ins.free_float_shares,
        } for ins in session.query(Instrument).all()
    ]
    # 可按需裁剪订单/成交 (防止超大)
    orders = []
    trades = []
    return {
        'accounts': accounts,
        'positions': positions,
        'instruments': instruments,
        'orders': orders,
        'trades': trades,
    }


def _write_snapshot(day: int):
    _safe_mkdir(settings.SNAPSHOT_DIR)
    fname = os.path.join(settings.SNAPSHOT_DIR, f"snapshot_day{day:05d}.json.gz")
    start = time.time()
    try:
        with SessionLocal() as s:
            db_state = _collect_db_state(s)
        eng_state = _collect_engine_state()
        payload: dict[str, Any] = {
            'meta': {
                'day': day,
                'generated_at': datetime.utcnow().isoformat(),
                'interval': settings.SNAPSHOT_INTERVAL_DAYS,
                'version': _SNAPSHOT_VERSION,
            },
            'engine': eng_state,
            **db_state,
        }
        tmp_name = fname + '.tmp'
        with gzip.open(tmp_name, 'wt', encoding='utf-8') as f:
            json.dump(payload, f, separators=(',', ':'), ensure_ascii=False)
        os.replace(tmp_name, fname)
        dur = (time.time() - start) * 1000
        print(f"[SNAPSHOT] day={day} ok file={fname} size={os.path.getsize(fname)}B dur={dur:.1f}ms")
    except Exception as e:
        print(f"[SNAPSHOT] day={day} fail err={e}")


def _schedule_snapshot(day: int):
    th = threading.Thread(target=_write_snapshot, args=(day,), daemon=True)
    th.start()


def _on_sim_day(topic: str, payload: dict):
    if not settings.SNAPSHOT_ENABLE:
        return
    day = payload.get('sim_day_index') if isinstance(payload, dict) else None
    if not day:
        return
    if day % max(1, settings.SNAPSHOT_INTERVAL_DAYS) != 0:
        return
    # 避免同一日重复触发（若事件被多次发布）
    with _lock:
        # 简单标记：创建一个空标志文件，存在则跳过
        flag_path = os.path.join(settings.SNAPSHOT_DIR, f".done_day{day}")
        if os.path.exists(flag_path):
            return
        _safe_mkdir(settings.SNAPSHOT_DIR)
        try:
            with open(flag_path, 'w') as fp:
                fp.write(datetime.utcnow().isoformat())
        except Exception:
            pass
    _schedule_snapshot(day)


def ensure_snapshot_service_started():
    global _started
    if _started:
        return True
    event_bus.subscribe(EventType.SIM_DAY, _on_sim_day, async_mode=False)
    _started = True
    print(f"[SNAPSHOT] service_started interval={settings.SNAPSHOT_INTERVAL_DAYS} dir={settings.SNAPSHOT_DIR}")
    return True

