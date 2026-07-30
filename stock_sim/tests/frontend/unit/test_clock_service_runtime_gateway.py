from __future__ import annotations

from app.services.clock_service import ClockService


class _FakeRuntimeGateway:
    def __init__(self):
        self.calls = []

    def start_clock(self, *, sim_day, day_seconds, speed, allocate_pending_ipo=False):
        self.calls.append(("start", sim_day, day_seconds, speed, allocate_pending_ipo))
        return {"running": True, "sim_day": sim_day}

    def pause_clock(self):
        self.calls.append(("pause",))
        return {"running": False}

    def resume_clock(self, *, day_seconds, speed):
        self.calls.append(("resume", day_seconds, speed))
        return {"running": True}

    def stop_clock(self):
        self.calls.append(("stop",))
        return {"running": False}

    def set_clock_speed(self, speed):
        self.calls.append(("speed", speed))
        return {"speed": speed}


def test_clock_service_uses_runtime_gateway_for_clock_actions():
    gateway = _FakeRuntimeGateway()
    clock = ClockService(runtime_gateway=gateway)

    clock.start("0")
    clock.pause()
    clock.resume()
    clock.set_speed(2.0)
    clock.stop()

    assert gateway.calls[0] == ("start", 0, clock._runtime_day_seconds, 1.0, True)
    assert gateway.calls[1] == ("pause",)
    assert gateway.calls[2] == ("resume", clock._runtime_day_seconds, 1.0)
    assert gateway.calls[3] == ("speed", 2.0)
    assert gateway.calls[4] == ("stop",)
