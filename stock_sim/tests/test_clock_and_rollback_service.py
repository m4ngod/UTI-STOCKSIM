import pytest

from app.services.clock_service import ClockService, ClockServiceError
from app.services.rollback_service import RollbackService, RollbackServiceError
from observability.metrics import metrics
from services.sim_clock import ensure_sim_clock_started


def test_clock_start_pause_resume_stop_and_speed():
    c = ClockService()
    s1 = c.start("2025-01-01")
    assert s1.status == "RUNNING" and s1.sim_day == "2025-01-01"
    s_pause = c.pause()
    assert s_pause.status == "PAUSED"
    s_resume = c.resume()
    assert s_resume.status == "RUNNING"
    s_stop = c.stop()
    assert s_stop.status == "STOPPED"
    c.start("2025-01-02")
    s_speed = c.set_speed(2.5)
    assert s_speed.speed == 2.5
    with pytest.raises(ClockServiceError):
        c.set_speed(0)


def test_clock_simday_switch_metric():
    c = ClockService()
    base_start = metrics.counters.get("clock_start", 0)
    base_switch = metrics.counters.get("clock_simday_switch", 0)
    c.start("2025-01-01")
    assert metrics.counters.get("clock_start", 0) == base_start + 1
    c.start("2025-01-01")
    assert metrics.counters.get("clock_simday_switch", 0) == base_switch
    c.start("2025-01-02")
    assert metrics.counters.get("clock_simday_switch", 0) == base_switch + 1
    assert metrics.counters.get("clock_start", 0) == base_start + 1


def test_clock_service_controls_runtime_clock_state():
    clk = ensure_sim_clock_started()
    if hasattr(clk, "stop_loop"):
        clk.stop_loop()
    if hasattr(clk, "set_day"):
        clk.set_day(0)
    c = ClockService()
    c.start("0")
    snap = clk.snapshot()
    assert snap["running"] is True
    assert snap["sim_day"] == 0
    c.pause()
    assert clk.snapshot()["running"] is False
    c.resume()
    assert clk.snapshot()["running"] is True
    c.stop()
    assert clk.snapshot()["running"] is False


def test_rollback_success_and_list():
    c = ClockService()
    r = RollbackService(c)
    c.start("2025-03-01")
    cp1 = r.create_checkpoint("init")
    c.start("2025-03-02")
    cp2 = r.create_checkpoint("after_switch")
    items = r.list_checkpoints()
    assert {i["id"] for i in items} == {cp1, cp2}
    r.rollback(cp1)
    state = c.get_state()
    assert state.sim_day == "2025-03-01"
    assert any(i["id"] == cp1 and i["is_current"] for i in r.list_checkpoints())


def test_rollback_failure_consistency_restores_previous():
    c = ClockService()
    r = RollbackService(c)
    c.start("2025-04-01")
    cp1 = r.create_checkpoint("base")
    c.start("2025-04-02")
    base_fail = metrics.counters.get("rollback_failure", 0)
    base_violation = metrics.counters.get("rollback_consistency_violation", 0)
    with pytest.raises(RollbackServiceError):
        r.rollback(cp1, simulate_inconsistent=True)
    assert c.get_state().sim_day == "2025-04-02"
    assert metrics.counters.get("rollback_failure", 0) == base_fail + 1
    assert metrics.counters.get("rollback_consistency_violation", 0) == base_violation + 1


def test_rollback_not_found():
    c = ClockService()
    r = RollbackService(c)
    c.start("2025-05-01")
    with pytest.raises(RollbackServiceError):
        r.rollback("no_such_id")
