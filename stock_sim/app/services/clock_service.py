"""Frontend clock service.

Maintains app-visible clock state and, when available, drives the runtime
simulation day loop so one `sim_day` advances every configured real-time window.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
import os
import time
from typing import Literal

from observability.metrics import metrics
from app.core_dto.clock import ClockStateDTO
from app.runtime_gateway import RuntimeGateway

try:
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
    sim_day: str = "0"
    speed: float = 1.0
    ts_ms: int = int(time.time() * 1000)


class ClockService:
    def __init__(self, *, runtime_gateway: RuntimeGateway | None = None):
        self._lock = RLock()
        self._state = _ClockInternal()
        self._runtime_day_seconds = max(1.0, float(os.environ.get("STOCKSIM_SIM_DAY_SECONDS", "120")))
        self._runtime_gateway = runtime_gateway or RuntimeGateway()

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

    def _publish_state(self):
        if event_bus is None:
            return
        try:
            event_bus.publish("clock.state", self._to_dto().model_dump())
        except Exception:
            pass

    def _try_parse_runtime_day(self, sim_day: str | None) -> int | None:
        if sim_day is None:
            return None
        text = str(sim_day).strip()
        if not text.isdigit():
            return None
        try:
            return max(0, int(text))
        except Exception:
            return None

    def _sync_runtime(self, action: str):
        parsed_day = self._try_parse_runtime_day(self._state.sim_day)
        try:
            if action == "start":
                self._runtime_gateway.start_clock(
                    sim_day=parsed_day,
                    day_seconds=self._runtime_day_seconds,
                    speed=self._state.speed,
                    allocate_pending_ipo=True,
                )
            elif action == "pause":
                self._runtime_gateway.pause_clock()
            elif action == "resume":
                self._runtime_gateway.resume_clock(
                    day_seconds=self._runtime_day_seconds,
                    speed=self._state.speed,
                )
            elif action == "stop":
                self._runtime_gateway.stop_clock()
            elif action == "speed":
                self._runtime_gateway.set_clock_speed(self._state.speed)
        except Exception:
            pass

    def start(self, sim_day: str | None = None) -> ClockStateDTO:
        t0 = time.perf_counter()
        with self._lock:
            if self._state.status == "RUNNING":
                if sim_day and sim_day != self._state.sim_day:
                    self._state.sim_day = sim_day
                    self._state.ts_ms = self._now_ms()
                    metrics.inc("clock_simday_switch")
                    self._publish_state()
                return self._to_dto()
            if sim_day:
                self._state.sim_day = sim_day
            elif not str(self._state.sim_day).strip().isdigit():
                self._state.sim_day = "0"
            self._set_status("RUNNING")
            metrics.inc("clock_start")
            self._sync_runtime("start")
            self._publish_state()
        metrics.add_timing("clock_state_change_ms", (time.perf_counter() - t0) * 1000)
        return self.get_state()

    def pause(self) -> ClockStateDTO:
        t0 = time.perf_counter()
        with self._lock:
            if self._state.status != "RUNNING":
                raise ClockServiceError("INVALID_STATE", "only RUNNING can pause")
            self._set_status("PAUSED")
            metrics.inc("clock_pause")
            self._sync_runtime("pause")
            self._publish_state()
        metrics.add_timing("clock_state_change_ms", (time.perf_counter() - t0) * 1000)
        return self.get_state()

    def resume(self) -> ClockStateDTO:
        t0 = time.perf_counter()
        with self._lock:
            if self._state.status != "PAUSED":
                raise ClockServiceError("INVALID_STATE", "only PAUSED can resume")
            self._set_status("RUNNING")
            metrics.inc("clock_resume")
            self._sync_runtime("resume")
            self._publish_state()
        metrics.add_timing("clock_state_change_ms", (time.perf_counter() - t0) * 1000)
        return self.get_state()

    def stop(self) -> ClockStateDTO:
        t0 = time.perf_counter()
        with self._lock:
            if self._state.status == "STOPPED":
                return self._to_dto()
            self._set_status("STOPPED")
            metrics.inc("clock_stop")
            self._sync_runtime("stop")
            self._publish_state()
        metrics.add_timing("clock_state_change_ms", (time.perf_counter() - t0) * 1000)
        return self.get_state()

    def set_speed(self, speed: float) -> ClockStateDTO:
        if speed <= 0:
            raise ClockServiceError("INVALID_SPEED", "speed must > 0")
        with self._lock:
            self._state.speed = speed
            metrics.inc("clock_speed_set")
            self._sync_runtime("speed")
            self._publish_state()
        return self.get_state()

    def tick(self) -> ClockStateDTO:
        with self._lock:
            self._state.ts_ms = self._now_ms()
            metrics.inc("clock_tick")
            if event_bus is not None:
                try:
                    event_bus.publish("clock.tick", self._to_dto().model_dump())
                except Exception:
                    pass
            return self._to_dto()

    def get_state(self) -> ClockStateDTO:
        with self._lock:
            return self._to_dto()


__all__ = ["ClockService", "ClockServiceError"]
