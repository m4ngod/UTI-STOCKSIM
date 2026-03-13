import pytest
from app.services.agent_service import AgentService, AgentServiceError
from app.controllers.agent_creation_controller import AgentCreationController
from app.controllers.agent_config_controller import AgentConfigController
from app.security.script_validator import ScriptValidator, ScriptValidationError
from app.state.version_store import VersionStore

# 覆盖: R3 批量零售创建/限制, R7 热更新 (参数版本同步), R8 版本链 & 回滚, R9 脚本安全校验

def test_agents_flow_integration(tmp_path):
    # --- 初始化服务 & 控制器 ---
    svc = AgentService()
    creation = AgentCreationController(svc)
    vs_path = tmp_path / 'version_store.json'
    version_store = VersionStore(str(vs_path))
    validator = ScriptValidator()  # 默认含危险 import/属性规则
    config_ctrl = AgentConfigController(svc, version_store, validator)

    # --- 1. 批量创建允许类型 (Retail) ---
    result = creation.batch_create(agent_type='Retail', count=3, name_prefix='rt')
    assert len(result['success_ids']) == 3 and not result['failed']
    agents = svc.list_agents()
    assert len(agents) == 3

    first_id = agents[0].agent_id

    # --- 2. 不允许类型 (PPO) 抛出业务错误 ---
    with pytest.raises(AgentServiceError) as ei:
        creation.batch_create(agent_type='PPO', count=2)
    assert ei.value.code == 'AGENT_BATCH_UNSUPPORTED'

    # --- 3. 版本新增 & 同步参数版本 ---
    v1 = config_ctrl.add_version(first_id, {'lr': 0.001}, author='tester')
    assert v1.version == 1
    ag_after_v1 = svc.get(first_id)
    assert ag_after_v1 is not None and ag_after_v1.params_version == 1

    v2 = config_ctrl.add_version(first_id, {'lr': 0.002}, author='tester')
    assert v2.version == 2
    assert svc.get(first_id).params_version == 2  # type: ignore

    # --- 4. 回滚生成新版本 (rollback_of=1) 并同步 ---
    v3 = config_ctrl.rollback(first_id, target_version=1, author='tester')
    assert v3.version == 3 and v3.rollback_of == 1
    assert svc.get(first_id).params_version == 3  # type: ignore

    versions = config_ctrl.list_versions(first_id)
    assert [v.version for v in versions] == [1, 2, 3]
    latest = config_ctrl.latest(first_id)
    assert latest.version == 3

    # --- 5. 脚本校验: 安全脚本 ---
    safe_code = 'a=1\nvalue=a+2'  # 无违规
    violations_safe = config_ctrl.validate_script(safe_code)
    assert violations_safe == []

    # --- 6. 脚本校验: 危险 import + eval ---
    dangerous = 'import os\nres = eval("1+2")'  # os & eval
    violations_danger = config_ctrl.validate_script(dangerous)
    rule_ids = {v['rule_id'] for v in violations_danger}
    codes = {v['code'] for v in violations_danger}
    # 需同时命中 forbidden_imports & forbidden_attributes 规则
    assert 'forbidden_imports' in rule_ids and 'forbidden_attributes' in rule_ids
    assert 'FORBIDDEN_IMPORT' in codes and 'FORBIDDEN_ATTR' in codes

    # --- 7. 脚本校验: 语法错误抛异常 ---
    bad_code = 'def x(:\n  pass'  # 语法错误
    with pytest.raises(ScriptValidationError) as se:
        validator.validate_source(bad_code)
    assert se.value.code == 'SYNTAX_ERROR'

    # --- 8. 持久化文件写入验证 (版本链) ---
    assert vs_path.is_file()

    # 简单输出便于调试
    print(f"agents_batch={len(agents)} versions={[v.version for v in versions]} violations_danger={len(violations_danger)}")

