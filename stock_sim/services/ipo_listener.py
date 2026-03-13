# python
"""IPO 持久化监听器
监听 EventType.IPO_OPENED 事件, 将内存 MatchingEngine 中的 IPO 开盘结果(流通股调整、开盘标记) 持久化到 instruments 表。
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy.orm import Session
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_instrument import Instrument

class IPOPersistenceListener:
    def __init__(self, session_factory=SessionLocal):
        self._sf = session_factory
        self._started = False

    def start(self):
        if self._started:
            return
        event_bus.subscribe(EventType.IPO_OPENED, self._on_ipo_opened, async_mode=False)
        self._started = True

    # 事件处理
    def _on_ipo_opened(self, topic: str, payload: dict):  # noqa: ARG002
        if not isinstance(payload, dict):
            return
        symbol = payload.get('symbol')
        if not symbol:
            return
        supply_after = payload.get('supply_after')
        open_price = payload.get('open_price')
        try:
            sess: Session = self._sf()
            try:
                inst = sess.get(Instrument, symbol.upper())
                if not inst:
                    return
                changed = False
                if supply_after is not None:
                    try:
                        supply_after_f = float(supply_after)
                        if inst.free_float_shares is None or abs(inst.free_float_shares - supply_after_f) > 1e-9:
                            inst.free_float_shares = supply_after_f
                            changed = True
                    except Exception:
                        pass
                if not getattr(inst, 'ipo_opened', False):
                    inst.ipo_opened = True
                    changed = True
                # 无论发行价是否存在，都将 initial_price 更新为开盘价，以作为 prev_close 基准
                if open_price is not None:
                    try:
                        opf = float(open_price)
                        if inst.initial_price is None or abs(inst.initial_price - opf) > 1e-9:
                            inst.initial_price = opf
                            changed = True
                    except Exception:
                        pass
                if changed:
                    sess.flush(); sess.commit()
            finally:
                sess.close()
        except Exception:
            pass

# 单例辅助
_ipo_listener_singleton: Optional[IPOPersistenceListener] = None

def ensure_ipo_listener_started() -> IPOPersistenceListener:
    global _ipo_listener_singleton
    if _ipo_listener_singleton is None:
        _ipo_listener_singleton = IPOPersistenceListener()
        _ipo_listener_singleton.start()
    return _ipo_listener_singleton
