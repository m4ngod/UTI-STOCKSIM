from app.panels.agents.panel import AgentsPanel
from app.panels.shared.notifications import notification_center
from app.core_dto.agent import AgentMetaDTO

class _StubAgentController:
    def __init__(self, agents):
        self._agents = agents
    def list_agents(self):
        return self._agents
    def control(self, agent_id: str, action: str):
        # 不需要真正控制逻辑，直接返回
        for a in self._agents:
            if a.agent_id == agent_id:
                return a
        raise ValueError('not found')

class _StubAgentService:
    pass


def test_heartbeat_stale_notification_once():
    notification_center.clear_all()
    # 构造一个 RUNNING 且 last_heartbeat 超时的 agent
    stale_agent = AgentMetaDTO(agent_id='ag-1', name='A1', type='Retail', status='RUNNING', start_time=1, last_heartbeat=None, params_version=0)
    ctl = _StubAgentController([stale_agent])
    panel = AgentsPanel(ctl, _StubAgentService(), heartbeat_threshold_ms=10_000)
    # 多次 get_view
    for _ in range(5):
        panel.get_view()
    notes = [n for n in notification_center.get_recent(20) if n.code == 'agent.heartbeat.stale']
    assert len(notes) == 1
    assert notes[0].data['agent_id'] == 'ag-1'

