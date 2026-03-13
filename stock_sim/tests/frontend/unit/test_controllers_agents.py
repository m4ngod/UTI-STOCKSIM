from app.controllers import AgentController, AgentCreationController, AgentConfigController
from app.services.agent_service import AgentService, AgentServiceError
from app.services.agent_service import BatchCreateConfig
from app.state.version_store import VersionStore
from app.security.script_validator import ScriptValidator


def test_agent_batch_create_and_control():
    svc = AgentService()
    create_ctl = AgentCreationController(svc)
    # 合法批量
    resp = create_ctl.batch_create(agent_type='Retail', count=3, name_prefix='rt')
    assert len(resp['success_ids']) == 3
    # 不支持批量类型
    try:
        create_ctl.batch_create(agent_type='PPO', count=1)
        assert False, 'should raise'
    except AgentServiceError as e:
        assert e.code == 'AGENT_BATCH_UNSUPPORTED'
    agent_ids = resp['success_ids']
    ctl = AgentController(svc)
    # 控制第一个
    meta = ctl.control(agent_ids[0], 'start')
    assert meta.status == 'RUNNING'
    logs = ctl.tail_logs(agent_ids[0], 5)
    assert any('Control action=start' in l for l in logs)


def test_agent_config_versions_and_rollback_and_validation(tmp_path):
    svc = AgentService()
    vs = VersionStore(path=str(tmp_path / 'versions.json'))
    validator = ScriptValidator()
    cfg_ctl = AgentConfigController(svc, vs, validator)

    # 先创建 agent 以便 params_version 更新
    create_ctl = AgentCreationController(svc)
    resp = create_ctl.batch_create(agent_type='Retail', count=1, name_prefix='cfg')
    agent_id = resp['success_ids'][0]

    v1 = cfg_ctl.add_version(agent_id, diff_json={'lr':0.01}, author='alice')
    assert v1.version == 1
    v2 = cfg_ctl.add_version(agent_id, diff_json={'lr':0.02}, author='alice')
    assert v2.version == 2
    rb = cfg_ctl.rollback(agent_id, 1, author='bob')
    assert rb.rollback_of == 1 and rb.version == 3
    latest = cfg_ctl.latest(agent_id)
    assert latest.version == 3
    lst = cfg_ctl.list_versions(agent_id)
    assert len(lst) == 3
    # 校验脚本 (包含 forbidden import)
    violations = cfg_ctl.validate_script('import os\nprint(123)')
    assert any(v['code']=='FORBIDDEN_IMPORT' for v in violations)
    ok = cfg_ctl.validate_script('import math\nprint(math.sqrt(4))')
    # math 不在 forbidden 列表，不应产生 FORBIDDEN_IMPORT
    assert not any(v['code']=='FORBIDDEN_IMPORT' for v in ok)

