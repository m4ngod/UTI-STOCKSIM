import pytest

from app.services.clock_service import ClockService, ClockServiceError
from app.services.rollback_service import RollbackService, RollbackServiceError
from observability.metrics import metrics


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
    # set speed
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
    # 再次 start 同日不增加 switch
    c.start("2025-01-01")
    assert metrics.counters.get("clock_simday_switch", 0) == base_switch
    # 切换交易日 (运行中)
    c.start("2025-01-02")
    assert metrics.counters.get("clock_simday_switch", 0) == base_switch + 1
    # clock_start 未再次增加
    assert metrics.counters.get("clock_start", 0) == base_start + 1


def test_rollback_success_and_list():
    c = ClockService()
    r = RollbackService(c)
    c.start("2025-03-01")
    cp1 = r.create_checkpoint("init")
    c.start("2025-03-02")  # 切换
    cp2 = r.create_checkpoint("after_switch")
    items = r.list_checkpoints()
    assert {i['id'] for i in items} == {cp1, cp2}
    # 回滚到 cp1
    r.rollback(cp1)
    state = c.get_state()
    assert state.sim_day == "2025-03-01"
    # current checkpoint id 更新
    assert any(i['id'] == cp1 and i['is_current'] for i in r.list_checkpoints())


def test_rollback_failure_consistency_restores_previous():
    c = ClockService()
    r = RollbackService(c)
    c.start("2025-04-01")
    cp1 = r.create_checkpoint("base")
    c.start("2025-04-02")
    # baseline metrics
    base_fail = metrics.counters.get("rollback_failure", 0)
    base_violation = metrics.counters.get("rollback_consistency_violation", 0)
    # 模拟失败
    with pytest.raises(RollbackServiceError):
        r.rollback(cp1, simulate_inconsistent=True)
    # 失败后应保持 2025-04-02
    assert c.get_state().sim_day == "2025-04-02"
    assert metrics.counters.get("rollback_failure", 0) == base_fail + 1
    assert metrics.counters.get("rollback_consistency_violation", 0) == base_violation + 1


def test_rollback_not_found():
    c = ClockService()
    r = RollbackService(c)
    c.start("2025-05-01")
    with pytest.raises(RollbackServiceError):
        r.rollback("no_such_id")

