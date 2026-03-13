import time

from app.services.agent_service import AgentService
from app.controllers.agent_controller import AgentController
from app.panels.agents import register_agents_panel
from app.panels import reset_registry, register_builtin_panels, get_panel
from app.ui.agent_creation_modal import AgentCreationModal, MAX_COUNT


def _build_agents_panel():
    reset_registry()
    register_builtin_panels()
    svc = AgentService()
    ctl = AgentController(svc)
    register_agents_panel(ctl, svc)
    panel = get_panel('agents')
    return panel, svc


def _wait_batch_done(panel, timeout_s=2.0):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        v = panel.get_view()
        if not v['batch']['in_progress']:
            return v
        time.sleep(0.01)
    return panel.get_view()


def test_agent_creation_modal_validation_and_progress():
    panel, svc = _build_agents_panel()
    modal = AgentCreationModal(panel)
    modal.open()

    # invalid count
    ok = modal.submit(agent_type='Retail', count=0)
    assert not ok
    assert modal.get_view()['error'] == 'INVALID_COUNT'

    # too large
    ok2 = modal.submit(agent_type='Retail', count=MAX_COUNT + 1)
    assert not ok2
    assert modal.get_view()['error'] == 'COUNT_TOO_LARGE'

    # unsupported type
    ok3 = modal.submit(agent_type='PPO', count=1)
    assert not ok3
    assert modal.get_view()['error'] == 'AGENT_BATCH_UNSUPPORTED'

    # MultiStrategyRetail without strategies
    ok4 = modal.submit(agent_type='MultiStrategyRetail', count=1, strategies=[])
    assert not ok4
    assert modal.get_view()['error'] == 'EMPTY_STRATEGIES'

    # MultiStrategyRetail with blank/dup strategies -> cleaned
    ok5 = modal.submit(agent_type='MultiStrategyRetail', count=3, strategies=['mean_rev', ' ', 'momentum', 'mean_rev'])
    assert ok5
    # 等待进度完成
    while True:
        modal.refresh_progress()
        v = modal.get_view()
        prog = v['progress']
        if prog and not prog['in_progress']:
            break
        time.sleep(0.01)
    v_done = modal.get_view()['progress']
    assert v_done['created'] == 3
    assert v_done['failed'] == 0
    # strategies 记录
    assert set(v_done['strategies']) == {'mean_rev', 'momentum'}

    # 再次提交 batch (快速第二次, 第一次已完成, 应可成功)
    ok6 = modal.submit(agent_type='Retail', count=2, name_prefix='retx')
    assert ok6
    # 在 batch 过程中再次提交 -> BATCH_IN_PROGRESS
    ok7 = modal.submit(agent_type='Retail', count=1)
    assert not ok7
    assert modal.get_view()['error'] == 'BATCH_IN_PROGRESS'
    # 等待第二批结束
    _wait_batch_done(panel)
    # 总 agent 数量 = 3 + 2 = 5
    assert len(svc.list_agents()) == 5

