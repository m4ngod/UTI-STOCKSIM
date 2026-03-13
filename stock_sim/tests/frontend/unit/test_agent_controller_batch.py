from app.services.agent_service import AgentService, AgentServiceError
from app.controllers.agent_controller import AgentController


def test_agent_controller_batch_create_allowed_and_disallowed():
    svc = AgentService()
    ctl = AgentController(svc)
    # 允许类型
    resp = ctl.batch_create(agent_type="Retail", count=2, name_prefix="ac")
    assert len(resp["success_ids"]) == 2
    # 不允许类型
    try:
        ctl.batch_create(agent_type="PPO", count=1)
        assert False, "should raise"
    except AgentServiceError as e:
        assert e.code == "AGENT_BATCH_UNSUPPORTED"

