# python
"""ipo_grant_queue.py
Redis 队列集中处理 IPO 初始持仓发放与 free_float_shares 扣减。

模式:
  Agent 启动 -> enqueue_ipo_grant(account_id, symbols, grant)
  Worker 单线程消费, 幂等: 若该账户该标的已有数量>0 则跳过。
  成功后发布 ACCOUNT_UPDATED 事件。

回退:
  若 Redis 不可用, 调用 fallback_direct_grant() 直接写库。
"""
from __future__ import annotations
import json, threading, time
from dataclasses import dataclass
from typing import List
from stock_sim.settings import settings
from stock_sim.services.redis_client import get_redis
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_account import Account
from stock_sim.persistence.models_position import Position
from stock_sim.persistence.models_instrument import Instrument
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType

QUEUE_KEY = lambda: f"{settings.REDIS_PREFIX}:ipo_grant_queue"
_START_FLAG = False
_STOP_EVENT: threading.Event | None = None

@dataclass
class GrantRequest:
    account_id: str
    symbols: List[str]
    grant: int
    req_id: str
    ts: float

# --------------- Enqueue API ---------------

def enqueue_ipo_grant(account_id: str, symbols: List[str], grant: int):
    r = get_redis()
    if not r or not settings.REDIS_ENABLED:
        # 回退直接授予
        fallback_direct_grant(account_id, symbols, grant)
        return False
    payload = {
        'account_id': account_id,
        'symbols': symbols,
        'grant': int(grant),
        'req_id': f"GRQ-{int(time.time()*1000)}-{account_id}",
        'ts': time.time(),
    }
    try:
        r.lpush(QUEUE_KEY(), json.dumps(payload, separators=(',', ':')))
        return True
    except Exception:
        fallback_direct_grant(account_id, symbols, grant)
        return False

# --------------- Worker ---------------

def _publish_account(s, acc: Account):
    nav = acc.cash + sum(p.quantity * (p.avg_price or 0) for p in acc.positions)
    event_bus.publish(EventType.ACCOUNT_UPDATED, {
        'account': {
            'id': acc.id,
            'cash': acc.cash,
            'frozen_cash': acc.frozen_cash,
            'frozen_fee': acc.frozen_fee,
            'positions': [
                {
                    'symbol': p.symbol,
                    'quantity': p.quantity,
                    'frozen_qty': p.frozen_qty,
                    'avg_price': p.avg_price
                } for p in acc.positions
            ],
            'nav': nav,
            'tradable_t0': getattr(acc, 'tradable_t0', True),
            'tradable_t1': getattr(acc, 'tradable_t1', True)
        }
    })


def _process_one(sess, req: GrantRequest):
    acc = sess.get(Account, req.account_id)
    if not acc:
        return
    changed = False
    for sym in sorted(set(req.symbols)):
        pos = None
        for p in acc.positions:
            if p.symbol == sym:
                pos = p
                break
        if pos is None:
            pos = Position(account_id=acc.id, symbol=sym, quantity=0, frozen_qty=0, avg_price=0.0)
            sess.add(pos)
            try:
                acc.positions.append(pos)  # relationship 装载时可能自动同步
            except Exception:
                pass
        if pos.quantity > 0:  # 已有数量视为已授予
            continue
        inst = sess.get(Instrument, sym)
        grant = int(req.grant)
        if inst and getattr(inst, 'free_float_shares', None) is not None and inst.free_float_shares and inst.free_float_shares >= grant:
            inst.free_float_shares -= grant
        pos.quantity += grant
        if pos.avg_price <= 0:
            base_px = None
            if inst:
                for k in ('initial_price', 'ipo_price', 'issue_price', 'list_price', 'last_close'):
                    if getattr(inst, k, None):
                        base_px = float(getattr(inst, k))
                        break
            pos.avg_price = base_px or 1.0
        changed = True
    if changed:
        sess.flush()
        _publish_account(sess, acc)


def _worker_loop():
    r = get_redis()
    if not r:
        return
    global _STOP_EVENT
    while _STOP_EVENT and not _STOP_EVENT.is_set():
        try:
            item = r.brpop(QUEUE_KEY(), timeout=1)
        except Exception:
            time.sleep(0.5)
            continue
        if not item:
            continue
        try:
            data = json.loads(item[1])
            req = GrantRequest(
                account_id=data['account_id'],
                symbols=list(data.get('symbols') or []),
                grant=int(data.get('grant', 0)),
                req_id=data.get('req_id', ''),
                ts=float(data.get('ts', 0.0))
            )
        except Exception:
            continue
        if req.grant <= 0 or not req.account_id or not req.symbols:
            continue
        try:
            with SessionLocal() as s:
                _process_one(s, req)
                s.commit()
        except Exception as e:
            # 失败简单重试: push 回队列尾部 (有限次数可在 req 中计数字段，这里简化)
            try:
                r.lpush(QUEUE_KEY(), json.dumps(data))
            except Exception:
                pass
            time.sleep(0.2)


def ensure_ipo_grant_worker_started():
    global _START_FLAG, _STOP_EVENT
    if _START_FLAG:
        return True
    if not settings.REDIS_ENABLED:
        return False
    if not get_redis():
        return False
    _STOP_EVENT = threading.Event()
    th = threading.Thread(target=_worker_loop, name="IPOGrantWorker", daemon=True)
    th.start()
    _START_FLAG = True
    print(f"[IPO_GRANT] worker_started queue={QUEUE_KEY()}")
    return True

# --------------- Direct fallback ---------------

def fallback_direct_grant(account_id: str, symbols: List[str], grant: int):
    if grant <= 0:
        return False
    try:
        with SessionLocal() as s:
            acc = s.get(Account, account_id)
            if not acc:
                return False
            changed = False
            for sym in symbols:
                pos = next((p for p in acc.positions if p.symbol == sym), None)
                if pos is None:
                    pos = Position(account_id=acc.id, symbol=sym, quantity=0, frozen_qty=0, avg_price=0.0)
                    s.add(pos)
                    try:
                        acc.positions.append(pos)
                    except Exception:
                        pass
                if pos.quantity > 0:
                    continue
                inst = s.get(Instrument, sym)
                if inst and getattr(inst, 'free_float_shares', None) and inst.free_float_shares >= grant:
                    inst.free_float_shares -= grant
                pos.quantity += grant
                if pos.avg_price <= 0:
                    base_px = None
                    if inst:
                        for k in ('initial_price', 'ipo_price', 'issue_price', 'list_price', 'last_close'):
                            if getattr(inst, k, None):
                                base_px = float(getattr(inst, k)); break
                    pos.avg_price = base_px or 1.0
                changed = True
            if changed:
                s.flush(); _publish_account(s, acc)
            s.commit()
            return True
    except Exception:
        return False
    return False

