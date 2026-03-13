from app.services.agent_service import AgentService
from app.controllers.agent_creation_controller import AgentCreationController
from app.controllers.agent_config_controller import AgentConfigController
from app.security.script_validator import ScriptValidator
from app.state.version_store import VersionStore
from app.ui.adapters.agent_config_adapter import AgentConfigPanelAdapter, MAX_SCRIPT_BYTES
from app.panels.agent_config.panel import AgentConfigPanel


def build_env(tmp_path, agent_type='Retail'):
    svc = AgentService()
    create_ctl = AgentCreationController(svc)
    resp = create_ctl.batch_create(agent_type=agent_type, count=1, name_prefix='cfg')
    agent_id = resp['success_ids'][0]
    vs = VersionStore(path=str(tmp_path / 'versions.json'))
    validator = ScriptValidator()
    cfg_ctl = AgentConfigController(svc, vs, validator)
    panel = AgentConfigPanel(agent_id, cfg_ctl, svc)
    return panel, cfg_ctl, svc, agent_id


def test_agent_config_adapter_add_version_and_violations(tmp_path):
    panel, ctl, svc, agent_id = build_env(tmp_path)
    adapter = AgentConfigPanelAdapter(panel)
    # 合法脚本提交
    ok = adapter.add_version({'alpha': 1}, author='alice', script_code='import math\nprint(math.sqrt(9))')
    assert ok is True
    st = adapter.get_state()
    assert st['last_submit_ok'] is True
    assert st['panel']['latest_version'] == 1

    # 违规脚本 (import os) -> 被 panel 阻断
    ok2 = adapter.add_version({'alpha': 2}, author='alice', script_code='import os\nprint(1)')
    assert ok2 is False
    st2 = adapter.get_state()
    assert st2['last_submit_ok'] is False
    assert st2['last_submit_error'] == 'SCRIPT_VIOLATIONS'
    assert st2['panel']['script']['last_violations']

    # 超大脚本 (>200KB)
    big_code = 'a'* (MAX_SCRIPT_BYTES + 10)
    ok3 = adapter.add_version({'alpha': 3}, author='alice', script_code=big_code)
    assert ok3 is False
    st3 = adapter.get_state()
    assert st3['last_submit_error'] == 'SCRIPT_TOO_LARGE'
    # 版本号未增加
    assert st3['panel']['latest_version'] == 1

    # 回滚测试
    ok_rb = adapter.rollback(1, author='bob')
    assert ok_rb is True
    st4 = adapter.get_state()
    assert st4['last_submit_ok'] is True
    assert st4['panel']['latest_version'] == 2  # 回滚生成新版本 2

