# python
"""Runtime simulation clock.

Provides a singleton day-based runtime clock used by settlement/T+1/persistence code.
The desktop app may start a background loop that advances one `sim_day` every
configured number of real seconds.
"""
from __future__ import annotations

import os
import sys
import threading
import time
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
        self._day_index: int = 0
        self.started: bool = False
        self._day_seconds: float = max(1.0, float(os.environ.get("STOCKSIM_SIM_DAY_SECONDS", "120")))
        self._speed: float = 1.0
        self._run_id: str | None = None
        self._running = False
        self._stop_evt = threading.Event()
        self._wake_evt = threading.Event()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None

    def current_day(self) -> int:
        with self._lock:
            return self._day_index

    def set_day(self, day_index: int) -> int:
        with self._lock:
            self._day_index = max(0, int(day_index))
            return self._day_index

    def set_speed(self, speed: float) -> float:
        with self._lock:
            self._speed = max(0.01, float(speed))
        self._wake_evt.set()
        return self._speed

    def configure(self, *, day_seconds: float | None = None, run_id: str | None = None):
        with self._lock:
            if day_seconds is not None:
                self._day_seconds = max(1.0, float(day_seconds))
            if run_id is not None:
                self._run_id = run_id
        self._wake_evt.set()

    def tick(self, run_id: str | None = None) -> int:
        """Manually advance one simulation day."""
        with self._lock:
            self._day_index += 1
            day_index = self._day_index
            active_run_id = run_id if run_id is not None else self._run_id
        try:
            event_bus.publish(EventType.SIM_DAY, {  # type: ignore
                "run_id": active_run_id,
                "sim_day_index": day_index,
                "sim_day": day_index,
                "sim_dt": virtual_datetime(day_index).isoformat(),
                "real_ts": datetime.utcnow().isoformat(timespec="seconds"),
            })
        except Exception:
            pass
        return day_index

    def start_loop(self, *, day_seconds: float | None = None, speed: float | None = None, run_id: str | None = None):
        with self._lock:
            if day_seconds is not None:
                self._day_seconds = max(1.0, float(day_seconds))
            if speed is not None:
                self._speed = max(0.01, float(speed))
            if run_id is not None:
                self._run_id = run_id
            self._running = True
            self.started = True
            if self._thread is None or not self._thread.is_alive():
                self._stop_evt.clear()
                self._thread = threading.Thread(target=self._loop, name="stock-sim-clock", daemon=True)
                self._thread.start()
        self._wake_evt.set()

    def pause_loop(self):
        with self._lock:
            self._running = False
        self._wake_evt.set()

    def stop_loop(self):
        with self._lock:
            self._running = False
        self._wake_evt.set()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "sim_day": self._day_index,
                "day_seconds": self._day_seconds,
                "speed": self._speed,
                "running": self._running,
                "run_id": self._run_id,
            }

    def _loop(self):
        while not self._stop_evt.is_set():
            with self._lock:
                running = self._running
                delay = self._day_seconds / max(self._speed, 0.01)
                run_id = self._run_id
            if not running:
                self._wake_evt.wait(0.2)
                self._wake_evt.clear()
                continue
            awakened = self._wake_evt.wait(delay)
            self._wake_evt.clear()
            if self._stop_evt.is_set():
                break
            if awakened:
                continue
            self.tick(run_id=run_id)


_sim_clock_singleton: Optional[_SimClock] = None


def ensure_sim_clock_started() -> _SimClock:
    global _sim_clock_singleton
    if _sim_clock_singleton is None:
        _sim_clock_singleton = _SimClock()
    return _sim_clock_singleton


def current_sim_day() -> Optional[int]:
    clk = ensure_sim_clock_started()
    return clk.current_day()


def virtual_datetime(sim_day: int) -> datetime:
    return datetime(1, 1, 1) + timedelta(days=max(int(sim_day), 0))


__all__ = [
    "ensure_sim_clock_started",
    "current_sim_day",
    "virtual_datetime",
    "_sim_clock_singleton",
]

if __name__ == "services.sim_clock":
    sys.modules.setdefault("stock_sim.services.sim_clock", sys.modules[__name__])
elif __name__ == "stock_sim.services.sim_clock":
    sys.modules.setdefault("services.sim_clock", sys.modules[__name__])
