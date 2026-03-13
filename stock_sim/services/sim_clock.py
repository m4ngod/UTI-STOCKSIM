# python
"""Simulation Clock Service (简化测试版)
原计划: 压缩交易日并通过线程周期发布事件。
测试最小需求:
  - ensure_sim_clock_started() 返回单例并可被测试重置 _day_index。
  - current_sim_day() 返回当前模拟日 (int)。
  - virtual_datetime(sim_day) 提供与模拟日对应的虚拟 datetime。
后续可扩展 tick()/start_loop() 发布 EventType.SIM_DAY 事件。
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional
try:
    from stock_sim.infra.event_bus import event_bus  # type: ignore
    from stock_sim.core.const import EventType  # type: ignore
except Exception:  # noqa
    from infra.event_bus import event_bus  # type: ignore
    from core.const import EventType  # type: ignore

class _SimClock:
    def __init__(self):
        # 从 1 开始符合测试中直接设置为 1 的语义
        self._day_index: int = 1
        self.started: bool = True

    def current_day(self) -> int:
        return self._day_index

    def tick(self) -> int:
        """人工推进一个模拟日 (测试/后续集成可用)."""
        self._day_index += 1
        try:
            event_bus.publish(EventType.SIM_DAY, {  # type: ignore
                "sim_day_index": self._day_index,
                "real_ts": datetime.utcnow().isoformat(timespec='seconds'),
            })
        except Exception:
            pass
        return self._day_index

# 单例引用 (测试会直接访问)_sim_clock_singleton
_sim_clock_singleton: Optional[_SimClock] = None

def ensure_sim_clock_started() -> _SimClock:
    global _sim_clock_singleton
    if _sim_clock_singleton is None:
        _sim_clock_singleton = _SimClock()
    return _sim_clock_singleton

def current_sim_day() -> Optional[int]:  # 与持久化层兼容可返回 None
    clk = ensure_sim_clock_started()
    return clk.current_day()

def virtual_datetime(sim_day: int) -> datetime:
    # 虚拟时间: 以公元 1 年 1 月 1 日为起点按日累加
    return datetime(1,1,1) + timedelta(days=sim_day-1)

__all__ = [
    "ensure_sim_clock_started","current_sim_day","virtual_datetime","_sim_clock_singleton"
]
