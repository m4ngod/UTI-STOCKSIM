# python
"""事件节点生成模块 (M1 增强版)

输入: dict[symbol] -> ndarray[T,6]  (ts, open, high, low, close, volume)
输出: EventNodes(indices, event_flags)

说明:
- 当前仍使用 30s bar 粒度, 无法在同一 30s 内插入多个精确秒级节点; 若触发事件则标记该 bar 为事件节点。
- 维护每标的最近事件基准价 last_base_price, 若本 bar close 相对基准变动超过阈值则标记。
- 控制: 每自然 30s 窗口(即当前 bar)最多 1 个事件; min_event_spacing_seconds => 转换成 bar 间隔限制。
- 聚合: 全局 event_flags = 任一标的触发 => 1.
后续: 接入秒级或 tick 数据后可在 30s 内插入额外 synthetic 节点。
"""
from __future__ import annotations
from typing import Dict, List
import numpy as np
from dataclasses import dataclass

@dataclass
class EventConfig:
    threshold: float = 0.005            # 0.5%
    max_events_per_30s: int = 5          # 预留, 当前 bar 粒度最多标记 1
    min_event_spacing_seconds: int = 2   # 相邻事件最小间隔(秒)
    bar_seconds: int = 30

@dataclass
class EventNodes:
    indices: List[int]
    event_flags: np.ndarray  # shape (T,), 0/1


def build_event_nodes(bars: Dict[str, np.ndarray], cfg: EventConfig | None = None) -> EventNodes:
    cfg = cfg or EventConfig()
    if not bars:
        return EventNodes([], np.zeros((0,), dtype=np.int8))
    # 统一长度
    T = min(arr.shape[0] for arr in bars.values())
    symbols = list(bars.keys())
    # 初始化基准价: 各 symbol 第一根 close
    last_base_price = {s: float(bars[s][0,4]) for s in symbols}
    last_event_bar = {s: 0 for s in symbols}
    event_flags_symbol = {s: np.zeros(T, dtype=np.int8) for s in symbols}
    min_bar_gap = max(1, int(np.ceil(cfg.min_event_spacing_seconds / cfg.bar_seconds)))
    for i in range(1, T):
        for s in symbols:
            arr = bars[s]
            if i >= arr.shape[0]:
                continue
            close_i = float(arr[i,4])
            base = last_base_price[s] if last_base_price[s] > 0 else close_i
            if base <= 0:
                continue
            chg = abs(close_i / base - 1.0)
            if chg >= cfg.threshold and (i - last_event_bar[s]) >= min_bar_gap:
                # 标记事件
                event_flags_symbol[s][i] = 1
                last_base_price[s] = close_i
                last_event_bar[s] = i
    # 汇总 OR
    event_flags = np.zeros(T, dtype=np.int8)
    for s in symbols:
        event_flags = np.maximum(event_flags, event_flags_symbol[s])
    indices = list(range(T))
    return EventNodes(indices=indices, event_flags=event_flags)

__all__ = ["EventConfig", "EventNodes", "build_event_nodes"]
