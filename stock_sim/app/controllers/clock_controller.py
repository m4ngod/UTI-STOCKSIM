"""ClockController (Spec Task 22)

职责 (R5):
- 封装 ClockService 启停/暂停/恢复/速度调整/状态读取
- 集成 RollbackService: create_checkpoint / list_checkpoints / rollback
- 回滚后允许继续 start(sim_day) 以验证“回滚后再��启动事件继续流” (由上层 EventBridge 重新驱动)

接口:
start(sim_day=None) -> ClockStateDTO
pause() / resume() / stop() -> ClockStateDTO
set_speed(speed: float) -> ClockStateDTO
state() -> ClockStateDTO
create_checkpoint(label) -> str
list_checkpoints() -> List[dict]
rollback(checkpoint_id) -> ClockStateDTO (回滚后返回当前时钟状态)

扩展 TODO:
- TODO: 增加一致性校验汇总报告返回 (账户/持仓 hash)
- TODO: 集成事件桥在回滚后重放历史

Future Hooks (Task50):
- TODO: Kafka 推送时钟事件 (CLOCK_STATE, ROLLBACK_DONE)
- TODO: RL 时间加速统计 (speed 实际生效与 drift 指标)
- TODO: 回滚差异报告结构化 (added_orders / removed_positions)
- TODO: 失败场景自动触发 dump_metrics() 快照
"""
from __future__ import annotations
from threading import RLock
from typing import List, Dict

from app.services.clock_service import ClockService, ClockServiceError
from app.services.rollback_service import RollbackService, RollbackServiceError
from app.core_dto.clock import ClockStateDTO
from observability.metrics import metrics

__all__ = ["ClockController"]

class ClockController:
    def __init__(self, clock_service: ClockService, rollback_service: RollbackService):
        self._clock = clock_service
        self._rollback = rollback_service
        self._lock = RLock()

    # ---------------- Clock Controls ----------------
    def start(self, sim_day: str | None = None) -> ClockStateDTO:
        state = self._clock.start(sim_day)
        return state

    def pause(self) -> ClockStateDTO:
        return self._clock.pause()

    def resume(self) -> ClockStateDTO:
        return self._clock.resume()

    def stop(self) -> ClockStateDTO:
        return self._clock.stop()

    def set_speed(self, speed: float) -> ClockStateDTO:
        return self._clock.set_speed(speed)

    def state(self) -> ClockStateDTO:
        return self._clock.get_state()

    # ---------------- Rollback ----------------
    def create_checkpoint(self, label: str) -> str:
        return self._rollback.create_checkpoint(label)

    def list_checkpoints(self) -> List[Dict]:
        return self._rollback.list_checkpoints()

    def rollback(self, checkpoint_id: str, *, simulate_inconsistent: bool = False) -> ClockStateDTO:
        self._rollback.rollback(checkpoint_id, simulate_inconsistent=simulate_inconsistent)
        # 回滚后 clock 已切换到 checkpoint.sim_day 且处于 RUNNING 状态
        metrics.inc("clock_controller_rollback")
        return self.state()
