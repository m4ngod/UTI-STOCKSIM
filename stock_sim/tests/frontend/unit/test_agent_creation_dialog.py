from app.controllers.agent_creation_controller import AgentCreationController
from app.services.agent_service import AgentService
from app.panels.agent_creation.dialog import AgentCreationDialog
from observability.metrics import metrics

def test_agent_creation_dialog_submit_success_and_error():
    svc = AgentService()
    ctl = AgentCreationController(svc)
    dlg = AgentCreationDialog(ctl)
    base_submit = metrics.counters.get('agent_creation_dialog_submit', 0)
    # 成功提交
    ok = dlg.submit(agent_type='Retail', count=2, name_prefix='dlg')
    assert ok
    v = dlg.get_view()
    assert v['last_result'] is not None and len(v['last_result']['success_ids']) == 2
    assert v['last_error'] is None
    # 不支持类型
    ok2 = dlg.submit(agent_type='PPO', count=1)
    assert not ok2
    v2 = dlg.get_view()
    assert v2['last_error'] == 'AGENT_BATCH_UNSUPPORTED'
    # 指标
    assert metrics.counters.get('agent_creation_dialog_submit', 0) >= base_submit + 1

