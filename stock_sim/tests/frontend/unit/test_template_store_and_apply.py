from app.services.agent_service import AgentService
from app.controllers.agent_config_controller import AgentConfigController
from app.state.version_store import VersionStore
from app.state.template_store import TemplateStore, TemplateStoreError
from app.security.script_validator import ScriptValidator


def build_env(tmp_path):
    svc = AgentService()
    vs = VersionStore(path=str(tmp_path / 'vs.json'))
    tpl = TemplateStore(path=str(tmp_path / 'tpl.json'))
    validator = ScriptValidator()
    ctl = AgentConfigController(svc, vs, validator, template_store=tpl)
    # 创建一个 agent
    resp = svc.batch_create_retail.__self__ if False else None  # 防 IDE 去掉 import
    # 简化: 直接调用批量创建
    b = svc.batch_create_retail(type('Cfg', (), {'count':1,'agent_type':'Retail','name_prefix':'tp'})())  # type: ignore
    agent_id = b['success_ids'][0]
    return ctl, svc, tpl, agent_id


def test_template_add_and_uniqueness(tmp_path):
    ctl, svc, tpl, agent_id = build_env(tmp_path)
    tpl.add_template('base', {'lr':0.01}, 'alice')
    try:
        tpl.add_template('base', {'lr':0.02}, 'bob')
        assert False, 'should raise TEMPLATE_EXISTS'
    except TemplateStoreError as e:
        assert e.code == 'TEMPLATE_EXISTS'


def test_apply_template_increments_params_version(tmp_path):
    ctl, svc, tpl, agent_id = build_env(tmp_path)
    tpl.add_template('fast', {'lr':0.1}, 'u1')
    # 初始 params_version=0
    ag0 = svc.get(agent_id)
    assert ag0.params_version == 0
    v1 = ctl.apply_template(agent_id, 'fast', author='u1')
    ag_after = svc.get(agent_id)
    assert ag_after.params_version == 1
    assert v1.version == 1
    # 再次应用同一模板 -> version 2
    v2 = ctl.apply_template(agent_id, 'fast', author='u2')
    assert svc.get(agent_id).params_version == 2
    assert v2.version == 2


def test_apply_template_not_found(tmp_path):
    ctl, svc, tpl, agent_id = build_env(tmp_path)
    try:
        ctl.apply_template(agent_id, 'nope', author='x')
        assert False, 'expected TEMPLATE_NOT_FOUND'
    except TemplateStoreError as e:
        assert e.code == 'TEMPLATE_NOT_FOUND'

