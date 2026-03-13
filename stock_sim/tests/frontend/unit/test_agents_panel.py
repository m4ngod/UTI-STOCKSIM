import time

from app.services.agent_service import AgentService, BatchCreateConfig, AgentServiceError
from app.controllers.agent_controller import AgentController
from app.panels import reset_registry, register_builtin_panels, get_panel
from app.panels.agents import register_agents_panel


def _build_agents_panel(threshold_ms=10000):
    reset_registry()
    register_builtin_panels()
    svc = AgentService()
    ctl = AgentController(svc)
    register_agents_panel(ctl, svc, heartbeat_threshold_ms=threshold_ms)
    panel = get_panel('agents')
    return panel, ctl, svc


def test_agents_panel_batch_create_success():
    panel, ctl, svc = _build_agents_panel()
    # 启动批量创建 5 个 Retail
    ok = panel.start_batch_create(count=5, agent_type='Retail', name_prefix='ret')
    assert ok
    # 等待批量线程完成
    for _ in range(200):
        v = panel.get_view()
        if not v['batch']['in_progress']:
            break
        time.sleep(0.01)
    v = panel.get_view()
    assert v['batch']['created'] == 5
    assert v['batch']['failed'] == 0
    assert v['agents']['total'] == 5


def test_agents_panel_batch_create_unsupported_type():
    panel, ctl, svc = _build_agents_panel()
    ok = panel.start_batch_create(count=3, agent_type='PPO', name_prefix='ppo')  # 不被允许
    assert ok
    # 等待线程结束
    for _ in range(200):
        v = panel.get_view()
        if not v['batch']['in_progress']:
            break
        time.sleep(0.01)
    v = panel.get_view()
    # 至少应出现错误码
    assert v['batch']['error'] == 'AGENT_BATCH_UNSUPPORTED'
    # created 可能为 0 (立即失败)
    assert v['batch']['created'] <= 1


def test_agents_panel_control_and_heartbeat_stale():
    panel, ctl, svc = _build_agents_panel(threshold_ms=1)  # 极低阈值便于判定 stale
    # 先创建一个 Retail
    svc.batch_create_retail(BatchCreateConfig(count=1, agent_type='Retail', name_prefix='one'))
    ag_id = svc.list_agents()[0].agent_id
    panel.control(ag_id, 'start')
    # 强制回溯心跳时间 (模拟过期)
    agent = svc.list_agents()[0]
    agent.last_heartbeat = agent.last_heartbeat - 10_000 if agent.last_heartbeat else 0
    # 获取视图
    v = panel.get_view()
    items = v['agents']['items']
    assert len(items) == 1
    assert items[0]['agent_id'] == ag_id
    assert items[0]['status'] == 'RUNNING'
    assert items[0]['heartbeat_stale'] is True
    # 控制暂停
    panel.control(ag_id, 'pause')
    v2 = panel.get_view()
    items2 = v2['agents']['items']
    assert items2[0]['status'] == 'PAUSED'
    # 暂停状态不再强调 heartbeat_stale (可为 True/False, 这里断言字段存在)
    assert 'heartbeat_stale' in items2[0]

