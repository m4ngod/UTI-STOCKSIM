import pytest
from app.services.clock_service import ClockService
from app.services.rollback_service import RollbackService, RollbackServiceError
from app.services.account_service import AccountService
from app.services.agent_service import AgentService, BatchCreateConfig


def _prepare_services():
    clock = ClockService()
    acc_svc = AccountService()
    ag_svc = AgentService()
    # 初始时钟 & 账户 & 智能体
    clock.start("2025-06-01")
    acc_svc.load_account("ACC1")
    ag_svc.batch_create_retail(BatchCreateConfig(count=2, agent_type="Retail", name_prefix="rb"))
    rb = RollbackService(clock, account_service=acc_svc, agent_service=ag_svc)
    return clock, acc_svc, ag_svc, rb


def test_rollback_consistency_success():
    clock, acc_svc, ag_svc, rb = _prepare_services()
    cp = rb.create_checkpoint("base")
    # 切换交易日 (制造回滚目标)
    clock.start("2025-06-02")
    rb.rollback(cp)
    assert clock.get_state().sim_day == "2025-06-01"


def test_rollback_consistency_equity_fail():
    clock, acc_svc, ag_svc, rb = _prepare_services()
    cp = rb.create_checkpoint("base")
    clock.start("2025-06-02")
    # 修改 equity 超过 0.01% 阈值: baseline * 1.001 (>0.0001 ratio)
    baseline = acc_svc.get_cached().equity  # type: ignore
    acc_svc._last_account.equity = baseline * 1.01  # type: ignore[attr-defined]  # 1% 差异
    with pytest.raises(RollbackServiceError) as e:
        rb.rollback(cp)
    assert e.value.code == "CONSISTENCY_FAIL"
    # 回退失败后保持 06-02
    assert clock.get_state().sim_day == "2025-06-02"


def test_rollback_consistency_agents_hash_fail():
    clock, acc_svc, ag_svc, rb = _prepare_services()
    cp = rb.create_checkpoint("base")
    clock.start("2025-06-02")
    # 修改一个智能体的 params_version 制造 hash 差异
    agents = ag_svc.list_agents()
    first = agents[0]
    ag_svc.update_params_version(first.agent_id, first.params_version + 1)
    with pytest.raises(RollbackServiceError) as e:
        rb.rollback(cp)
    assert e.value.code == "CONSISTENCY_FAIL"
    assert clock.get_state().sim_day == "2025-06-02"

