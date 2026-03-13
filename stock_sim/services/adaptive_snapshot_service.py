# python
# file: services/adaptive_snapshot_service.py
"""Adaptive Snapshot Policy Manager

根据每 symbol 的撮合/簿操作速率自适应调整快照阈值。
- 高速: 提升阈值以降低 I/O
- 低速: 降低阈值保证实时性

初版策略: 窗口=2s, 按 ops/sec 分档：
  ops_rate >= 200  -> 阈值 = base * 8
  ops_rate >= 100  -> 阈值 = base * 4
  ops_rate >= 50   -> 阈值 = base * 2
  ops_rate <= 5    -> 阈值 = base (回落)
可在后续通过配置热更新或更复杂自适应模型替换。

与 MatchingEngine 协同:
  - engine 调用 on_book_op() / on_trade()
  - engine._conditional_refresh_snapshot 使用 get_threshold(symbol) 作为动态阈值
  - 若阈值变化 -> 发布 EventType.SNAPSHOT_POLICY_CHANGED

"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from time import time
from typing import Deque, Dict

try:
    from stock_sim.settings import settings  # type: ignore
    from stock_sim.infra.event_bus import event_bus  # type: ignore
    from stock_sim.core.const import EventType  # type: ignore
except Exception:  # noqa: fallback to source layout
    try:
        from settings import settings  # type: ignore
    except Exception:  # noqa
        settings = None  # type: ignore
    try:
        from infra.event_bus import event_bus  # type: ignore
    except Exception:  # noqa
        class _DummyBus:  # minimal placeholder
            def publish(self, *a, **kw):
                pass
        event_bus = _DummyBus()  # type: ignore
    try:
        from core.const import EventType  # type: ignore
    except Exception:  # noqa
        class EventType:  # placeholder enum-like
            SNAPSHOT_POLICY_CHANGED = "SnapshotPolicyChanged"

@dataclass
class SymbolAdaptiveState:
    ops_timestamps: Deque[float]
    current_threshold: int

class AdaptiveSnapshotPolicyManager:
    def __init__(self, *, base_threshold: int | None = None, window_sec: float = 2.0, max_multiplier: int = 8):
        self.base = base_threshold or getattr(settings, 'SNAPSHOT_THROTTLE_N_PER_SYMBOL', 5)
        self.window = window_sec
        self.max_multiplier = max_multiplier
        self._states: Dict[str, SymbolAdaptiveState] = {}

    # ---- PUBLIC API ----
    def on_book_op(self, symbol: str):
        st = self._ensure(symbol)
        now = time()
        st.ops_timestamps.append(now)
        self._trim(st, now)

    def on_trade(self, symbol: str):
        # 交易也视为一次操作 (已被 on_book_op 调用覆盖, 这里可追加策略)
        self.on_book_op(symbol)

    def get_threshold(self, symbol: str) -> int:
        return self._ensure(symbol).current_threshold

    def maybe_adjust(self, symbol: str):
        st = self._ensure(symbol)
        now = time()
        self._trim(st, now)
        rate = len(st.ops_timestamps) / max(1e-6, self.window)
        # 计算目标阈值
        target = self.base
        if rate >= 200:
            target = self.base * 8
        elif rate >= 100:
            target = self.base * 4
        elif rate >= 50:
            target = self.base * 2
        elif rate <= 5:
            target = self.base  # 回落
        # clamp
        max_allowed = self.base * self.max_multiplier
        if target > max_allowed:
            target = max_allowed
        if target < self.base:
            target = self.base
        if target != st.current_threshold:
            old = st.current_threshold
            st.current_threshold = int(target)
            event_bus.publish(EventType.SNAPSHOT_POLICY_CHANGED, {
                'symbol': symbol,
                'old_threshold': old,
                'new_threshold': st.current_threshold,
                'ops_rate': rate,
            })

    # ---- INTERNAL ----
    def _ensure(self, symbol: str) -> SymbolAdaptiveState:
        sym = symbol.upper()
        st = self._states.get(sym)
        if not st:
            st = SymbolAdaptiveState(ops_timestamps=deque(), current_threshold=self.base)
            self._states[sym] = st
        return st

    def _trim(self, st: SymbolAdaptiveState, now: float):
        w = self.window
        dq = st.ops_timestamps
        while dq and now - dq[0] > w:
            dq.popleft()

__all__ = ["AdaptiveSnapshotPolicyManager"]
