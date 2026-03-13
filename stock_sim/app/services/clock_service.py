"""ClockService (Spec Task 12 Part 1)

职责 (R5 AC1/2/5):
- 启动(start) / 暂停(pause) / 恢复(resume) / 停止(stop)
- 设置加速比(set_speed) (speed > 0)
- 维护当前 sim_day、状态、时间戳 (epoch ms)
- 线程安全; 提供 get_state()

扩展 (R5 AC3/4/6 后续由 RollbackService/Controller/Panel 驱动):
- 回滚与一致性校验不在此类实现, 仅暴露状态
- TODO: 后续对接真实事件推进 (撮合/回放) 时钟驱动

指标:
- clock_start / clock_pause / clock_resume / clock_stop / clock_speed_set / clock_tick / clock_simday_switch
- clock_state_change_ms 记录状态切换耗时 (极小, 仅供观测)

"""
from __future__ import annotations
from dataclasses import dataclass
from threading import RLock
import time
from typing import Literal

from observability.metrics import metrics
from app.core_dto.clock import ClockStateDTO
# 新增: 事件发布
try:  # 运行期可选
    from infra.event_bus import event_bus  # type: ignore
except Exception:  # pragma: no cover
    event_bus = None  # type: ignore

ClockStatus = Literal["RUNNING", "PAUSED", "STOPPED"]

class ClockServiceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

@dataclass
class _ClockInternal:
    status: ClockStatus = "STOPPED"
    sim_day: str = time.strftime("%Y-%m-%d")
    speed: float = 1.0
    ts_ms: int = int(time.time()*1000)

class ClockService:
    def __init__(self):
        self._lock = RLock()
        self._state = _ClockInternal()

    # ---------------- Internal helpers ----------------
    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _to_dto(self) -> ClockStateDTO:
        return ClockStateDTO(
            status=self._state.status,
            sim_day=self._state.sim_day,
            speed=self._state.speed,
            ts=self._state.ts_ms,
        )

    def _set_status(self, status: ClockStatus):
        self._state.status = status
        self._state.ts_ms = self._now_ms()

    def _publish_state(self):  # 新增：统一发布当前状态
        if event_bus is None:
            return
        try:
            event_bus.publish("clock.state", self._to_dto().dict())
        except Exception:  # pragma: no cover
            pass

    # ---------------- Public API ----------------
    def start(self, sim_day: str | None = None) -> ClockStateDTO:
        t0 = time.perf_counter()
        with self._lock:
            # 若已经 RUNNING 但提供新的 sim_day -> 切换交易日 (支持回滚/读档)
            if self._state.status == "RUNNING":
                if sim_day and sim_day != self._state.sim_day:
                    self._state.sim_day = sim_day
                    self._state.ts_ms = self._now_ms()
                    metrics.inc("clock_simday_switch")
                    # 发布状态（交易日切换）
                    self._publish_state()
                return self._to_dto()
            if sim_day:
                self._state.sim_day = sim_day
            else:
                self._state.sim_day = time.strftime("%Y-%m-%d")
            self._set_status("RUNNING")
            metrics.inc("clock_start")
            # 发布状态
            self._publish_state()
        metrics.add_timing("clock_state_change_ms", (time.perf_counter()-t0)*1000)
        return self.get_state()

    def pause(self) -> ClockStateDTO:
        t0 = time.perf_counter()
        with self._lock:
            if self._state.status != "RUNNING":
                raise ClockServiceError("INVALID_STATE", "only RUNNING can pause")
            self._set_status("PAUSED")
            metrics.inc("clock_pause")
            # 发布状态
            self._publish_state()
        metrics.add_timing("clock_state_change_ms", (time.perf_counter()-t0)*1000)
        return self.get_state()

    def resume(self) -> ClockStateDTO:
        t0 = time.perf_counter()
        with self._lock:
            if self._state.status != "PAUSED":
                raise ClockServiceError("INVALID_STATE", "only PAUSED can resume")
            self._set_status("RUNNING")
            metrics.inc("clock_resume")
            # 发布状态
            self._publish_state()
        metrics.add_timing("clock_state_change_ms", (time.perf_counter()-t0)*1000)
        return self.get_state()

    def stop(self) -> ClockStateDTO:
        t0 = time.perf_counter()
        with self._lock:
            if self._state.status == "STOPPED":
                return self._to_dto()
            self._set_status("STOPPED")
            metrics.inc("clock_stop")
            # 发布状态
            self._publish_state()
        metrics.add_timing("clock_state_change_ms", (time.perf_counter()-t0)*1000)
        return self.get_state()

    def set_speed(self, speed: float) -> ClockStateDTO:
        if speed <= 0:
            raise ClockServiceError("INVALID_SPEED", "speed must > 0")
        with self._lock:
            self._state.speed = speed
            metrics.inc("clock_speed_set")
            # 发布状态（速度变更）
            self._publish_state()
        return self.get_state()

    def tick(self) -> ClockStateDTO:
        with self._lock:
            self._state.ts_ms = self._now_ms()
            metrics.inc("clock_tick")
            # 发布 tick（轻量）
            if event_bus is not None:
                try:
                    event_bus.publish("clock.tick", self._to_dto().dict())
                except Exception:  # pragma: no cover
                    pass
            return self._to_dto()

    def get_state(self) -> ClockStateDTO:
        with self._lock:
            return self._to_dto()

__all__ = ["ClockService", "ClockServiceError"]
