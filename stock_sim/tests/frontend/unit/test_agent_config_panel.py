import time
from app.services.agent_service import AgentService
from app.controllers.agent_config_controller import AgentConfigController
from app.controllers.agent_creation_controller import AgentCreationController
from app.security.script_validator import ScriptValidator
from app.state.version_store import VersionStore
from app.panels.agent_config.panel import AgentConfigPanel
from observability.metrics import metrics

def build_env(tmp_path, agent_id='ag-1'):
    svc = AgentService()
    vs = VersionStore(path=str(tmp_path / 'versions.json'))
    validator = ScriptValidator()
    cfg_ctl = AgentConfigController(svc, vs, validator)
    create_ctl = AgentCreationController(svc)
    # 创建一个 agent 使 params_version 能同步
    resp = create_ctl.batch_create(agent_type='Retail', count=1, name_prefix='cfg')
    real_agent_id = resp['success_ids'][0]
    panel = AgentConfigPanel(real_agent_id, cfg_ctl, svc)
    return panel, cfg_ctl, svc, real_agent_id

def test_agent_config_panel_add_version_and_script_block(tmp_path):
    panel, ctl, svc, agent_id = build_env(tmp_path)
    base_add = metrics.counters.get('agent_config_version_add', 0)
    # 初始无版本
    v0 = panel.get_view()
    assert v0['latest_version'] is None
    # 添加版本 (脚本合法)
    ok = panel.add_version({'lr':0.01}, author='alice', script_code='import math\nprint(math.sqrt(4))')
    assert ok
    v1 = panel.get_view()
    assert v1['latest_version'] == 1
    assert v1['latest_params_version'] == 1
    # 再添加一个版本 (非法脚本: forbidden import)
    ok2 = panel.add_version({'lr':0.02}, author='alice', script_code='import os\nprint(1)')
    assert not ok2  # 被阻断
    v_after_block = panel.get_view()
    assert v_after_block['latest_version'] == 1  # 未新增
    assert v_after_block['script']['last_error'] == 'SCRIPT_VIOLATIONS'
    assert v_after_block['script']['last_violations']
    # 回滚 (target=1) -> 生成 v2
    ok_rb = panel.rollback(1, author='bob')
    assert ok_rb
    v2 = panel.get_view()
    assert v2['latest_version'] == 2
    # 指标至少 +1
    assert metrics.counters.get('agent_config_version_add', 0) >= base_add + 1

def test_agent_config_panel_params_version_mismatch_metric(tmp_path):
    panel, ctl, svc, agent_id = build_env(tmp_path)
    # 添加版本
    panel.add_version({'p':1}, author='u')
    # 人为篡改 service 中 version 以制造 mismatch
    ag = svc.get(agent_id)
    ag.params_version = 999  # type: ignore
    svc._agents[agent_id] = ag  # type: ignore
    panel.add_version({'p':2}, author='u')
    # 检查 mismatch 指标
    assert metrics.counters.get('agent_config_params_version_mismatch', 0) >= 1

