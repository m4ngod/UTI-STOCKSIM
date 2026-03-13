# python
"""Strategy Supervisor
监听 ACCOUNT_UPDATED 事件, 基于账户收益率触发策略轮换。
规则:
  - 首次见到账户 nav 记录 baseline_nav
  - 当前收益率 r = (nav - baseline)/baseline
  - 若 abs(r) >= 0.20 且冷却期(默认60s)已过 => 轮换策略 (A->B->C->D->A)
  - 发布 EventType.STRATEGY_CHANGED:
       {account_id, old_strategy, new_strategy, yield_pct, nav, ts}
  - MultiStrategyRetail 若持仓!=0 则延迟到清仓后应用 (其内部逻辑已处理)
"""
from __future__ import annotations
from datetime import datetime, timedelta
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType
try:
    # 新引用: 使用新多策略页面的 registry
    from agents.multi_strategy_retail import strategy_registry
except Exception:
    strategy_registry = None

class StrategySupervisor:
    """策略监督器 (扩展版)
    功能:
      1. 正向收益多级触发: 收益率 >= 任一级 up 阈值 -> 按 rotate_map 前进一档
      2. 回撤触发回退: 相对峰值回撤 >= drawdown_threshold -> 按 reverse_map 回退一档 (或回到 safe_strategy)
      3. 冷却: 每次触发后需经过 cooldown 才能再次触发
      4. 基线 baseline_nav: 用于收益率计算; 每次正向轮换或回撤回退后重置为当前 nav
      5. 峰值 peak_nav: 用于计算回撤 (peak - nav)/peak
    """
    def __init__(self,
                 rotate_map=None,             # 正向轮换映射 A->B->C->D->A
                 reverse_map=None,            # 回撤回退映射 D->C->B->A 等
                 up_thresholds=None,          # 多级正收益阈值列表 (升序)
                 drawdown_threshold: float = 0.10,  # 回撤阈值 (>= 则触发回退)
                 cooldown_sec: int = 60,
                 safe_strategy: str = 'A'):
        self.baseline: dict[str, float] = {}
        self.peak: dict[str, float] = {}
        self.last_switch: dict[str, datetime] = {}
        self.rotate_map = rotate_map or {"A": "B", "B": "C", "C": "D", "D": "A"}
        # 反向回退默认: 反向映射; 未列出保持原策略
        self.reverse_map = reverse_map or {"D": "C", "C": "B", "B": "A"}
        self.up_thresholds = sorted(up_thresholds or [0.20])  # 升序
        self.drawdown_threshold = drawdown_threshold
        self.cooldown = timedelta(seconds=cooldown_sec)
        self.safe_strategy = safe_strategy
        event_bus.subscribe(EventType.ACCOUNT_UPDATED, self._on_account)

    # ---- 内部工具 ----
    def _current_strategy(self, account_id: str) -> str | None:
        if strategy_registry:
            try:
                return strategy_registry.get(account_id)
            except Exception:
                return None
        return None

    def _forward(self, cur: str) -> str:
        return self.rotate_map.get(cur, cur)

    def _backward(self, cur: str) -> str:
        return self.reverse_map.get(cur, cur)

    # ---- 事件处理 ----
    def _on_account(self, topic: str, payload: dict):
        acc = (payload or {}).get("account") or {}
        aid = acc.get("id")
        if not aid:
            return
        nav = acc.get("nav") or acc.get("cash")
        if nav is None:
            return
        nav = float(nav)
        base = self.baseline.get(aid)
        if base is None or base <= 0:
            self.baseline[aid] = nav
            self.peak[aid] = nav
            return
        # 更新峰值
        if nav > self.peak.get(aid, nav):
            self.peak[aid] = nav
        peak = self.peak.get(aid, nav)
        # 计算收益与回撤
        ret = (nav - base) / base
        drawdown = (peak - nav) / peak if peak > 0 else 0.0
        now = datetime.utcnow()
        last = self.last_switch.get(aid)
        if last and now - last < self.cooldown:
            return
        cur = self._current_strategy(aid)
        if not cur:
            return
        # 1. 回撤优先: 若达到回撤阈值 -> 回退
        if drawdown >= self.drawdown_threshold:
            new_stg = self._backward(cur)
            # 若已经是 safe 策略或无法回退则直接重置基线防抖
            if new_stg == cur and cur != self.safe_strategy:
                # 回退表未给出, 回到 safe
                new_stg = self.safe_strategy
            if new_stg != cur:
                self._publish_change(aid, cur, new_stg, ret, nav, reason='drawdown', drawdown=drawdown)
                self._reset_after_switch(aid, nav, now)
            return
        # 2. 正向收益: 找到最高满足的阈值 (多级一次只前进一步)
        trigger = None
        for th in reversed(self.up_thresholds):  # 最高优先
            if ret >= th:
                trigger = th
                break
        if trigger is not None:
            new_stg = self._forward(cur)
            if new_stg != cur:
                self._publish_change(aid, cur, new_stg, ret, nav, reason='profit', threshold=trigger)
                self._reset_after_switch(aid, nav, now)
            else:
                # 已在末级, 重置基线避免频繁触发
                self.baseline[aid] = nav
                self.peak[aid] = nav
                self.last_switch[aid] = now

    def _publish_change(self, aid: str, old: str, new: str, ret: float, nav: float, **extra):
        event = {"account_id": aid, "old_strategy": old, "new_strategy": new, "yield_pct": ret, "nav": nav, "ts": datetime.utcnow().isoformat()}
        event.update(extra)
        event_bus.publish(EventType.STRATEGY_CHANGED, event)

    def _reset_after_switch(self, aid: str, nav: float, now: datetime):
        self.baseline[aid] = nav
        self.peak[aid] = nav
        self.last_switch[aid] = now

# ---- 单例启动 ----
_supervisor_singleton: StrategySupervisor | None = None

def ensure_strategy_supervisor_started(**kwargs):
    global _supervisor_singleton
    if _supervisor_singleton is None:
        _supervisor_singleton = StrategySupervisor(**kwargs)
    return _supervisor_singleton
