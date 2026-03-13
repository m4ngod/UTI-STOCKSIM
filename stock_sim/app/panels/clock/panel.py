"""ClockPanel (Spec Task 28)

职责 (R5):
- 封装 ClockController 提供启停/暂停/恢复/速度调整
- 展示当前时钟状态 (status/sim_day/speed/ts)
- 管理检查点: 创建/列出/回滚 (调用 RollbackService 通过 controller 接口)
- 读档(sim_day 切换): start(sim_day) 即可; 若已 RUNNING 则切换交易日

视图结构 get_view():
{
  'state': {status, sim_day, speed, ts},
  'checkpoints': [ {id,label,sim_day,created_ms,is_current} ],
  'current_checkpoint': str | None,
  'last_action_ms': epoch_ms,
}

扩展 TODO:
- TODO: 进度 (replay %) / 事件统计
- TODO: 一致性校验报告 surface 在回滚后
"""
from __future__ import annotations
from threading import RLock
from typing import Any, Dict, List, Optional
import time

from app.controllers.clock_controller import ClockController
from app.services.rollback_service import RollbackServiceError
from app.services.clock_service import ClockServiceError
from app.core_dto.clock import ClockStateDTO

__all__ = ["ClockPanel"]

class ClockPanel:
    def __init__(self, controller: ClockController):
        self._ctl = controller
        self._lock = RLock()
        self._state: ClockStateDTO = self._ctl.state()
        self._last_action_ms: int = int(time.time()*1000)
        self._checkpoints_cache: List[Dict[str, Any]] = self._ctl.list_checkpoints() if hasattr(self._ctl, 'list_checkpoints') else []

    # ---------------- Basic Controls ----------------
    def start(self, sim_day: str | None = None):  # R5 AC1
        st = self._ctl.start(sim_day)
        with self._lock:
            self._state = st
            self._last_action_ms = int(time.time()*1000)

    def pause(self):  # R5 AC1
        st = self._ctl.pause()
        with self._lock:
            self._state = st
            self._last_action_ms = int(time.time()*1000)

    def resume(self):  # R5 AC1
        st = self._ctl.resume()
        with self._lock:
            self._state = st
            self._last_action_ms = int(time.time()*1000)

    def stop(self):  # R5 AC1
        st = self._ctl.stop()
        with self._lock:
            self._state = st
            self._last_action_ms = int(time.time()*1000)

    def set_speed(self, speed: float):  # R5 AC2
        st = self._ctl.set_speed(speed)
        with self._lock:
            self._state = st
            self._last_action_ms = int(time.time()*1000)

    # ---------------- Checkpoints / Rollback ----------------
    def create_checkpoint(self, label: str) -> str:  # R5 AC3
        cp_id = self._ctl.create_checkpoint(label)
        with self._lock:
            self._checkpoints_cache = self._ctl.list_checkpoints()
            self._last_action_ms = int(time.time()*1000)
        return cp_id

    def list_checkpoints(self) -> List[Dict[str, Any]]:  # R5 AC3
        with self._lock:
            return list(self._checkpoints_cache)

    def rollback(self, checkpoint_id: str, *, simulate_inconsistent: bool = False):  # R5 AC4/5
        try:
            st = self._ctl.rollback(checkpoint_id, simulate_inconsistent=simulate_inconsistent)
        except RollbackServiceError:
            # 回滚失败不更新 state/checkpoints (控制器已回退)
            raise
        with self._lock:
            self._state = st
            # 刷新检查点列表 (current 标记可能变化)
            self._checkpoints_cache = self._ctl.list_checkpoints()
            self._last_action_ms = int(time.time()*1000)

    # ---------------- Reading State ----------------
    def get_view(self) -> Dict[str, Any]:  # R5 AC6
        with self._lock:
            st = self._state
            cps = list(self._checkpoints_cache)
            last_ms = self._last_action_ms
        current_id = None
        for c in cps:
            if c.get('is_current'):
                current_id = c['id']
                break
        return {
            'state': {
                'status': st.status,
                'sim_day': st.sim_day,
                'speed': st.speed,
                'ts': st.ts,
            },
            'checkpoints': cps,
            'current_checkpoint': current_id,
            'last_action_ms': last_ms,
        }

    # Convenience: 切换交易日 (读档) 等价直接 start(sim_day)
    def switch_sim_day(self, sim_day: str):  # R5 AC5
        self.start(sim_day)


