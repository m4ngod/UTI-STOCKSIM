"""AgentConfigController (Spec Task 21)

职责:
- 版本管理: 新增版本 / 回滚 / 列表 / 最新 (R8)
- 热更新: 新增版本后同步更新 AgentService.params_version (R7,R8)
- 脚本校验: 调用 ScriptValidator 返回 violations (R7,R9)
- 模板: 新增 / 列表 / 应用模板为新版本 (Task: strategy template persistence + apply_template)

假设 diff_json 为任意 dict, 不做 schema 校验。

Future Hooks (Task50):
- TODO: 版本元数据扩展 (评估指标 snapshot, rollback_reason)
- TODO: Kafka 事件推送 (AGENT_VERSION_CREATED, AGENT_VERSION_ROLLBACK)
- TODO: 参数基线签名 (hash) 验证一致性
- TODO: 增量 diff 可视化接口 (供后续 Web UI)
"""
from __future__ import annotations
from typing import Dict, Any, List, Optional
from app.state.version_store import VersionStore, VersionStoreError
from app.security.script_validator import ScriptValidator, ScriptValidationError
from app.services.agent_service import AgentService, AgentServiceError
from app.core_dto.versioning import AgentVersionDTO
from app.state.template_store import TemplateStore, TemplateStoreError

__all__ = ["AgentConfigController"]

class AgentConfigController:
    def __init__(self, service: AgentService, version_store: VersionStore, validator: ScriptValidator, template_store: TemplateStore | None = None):
        self._service = service
        self._vs = version_store
        self._validator = validator
        self._tpl = template_store or TemplateStore()

    # -------- Version Ops --------
    def add_version(self, agent_id: str, diff_json: Dict[str, Any], author: str) -> AgentVersionDTO:
        dto = self._vs.add_version(agent_id, diff_json=diff_json, author=author)
        # 同步更新 agent 参数版本
        try:
            self._service.update_params_version(agent_id, dto.version)
        except AgentServiceError:
            # 若 agent 尚不存在, 忽略 (可能稍后创建)
            pass
        return dto

    def rollback(self, agent_id: str, target_version: int, author: str) -> AgentVersionDTO:
        dto = self._vs.create_rollback(agent_id, target_version, author)
        try:
            self._service.update_params_version(agent_id, dto.version)
        except AgentServiceError:
            pass
        return dto

    def list_versions(self, agent_id: str, *, limit: Optional[int] = None, reverse: bool = False) -> List[AgentVersionDTO]:
        return self._vs.list_versions(agent_id, limit=limit, reverse=reverse)

    def latest(self, agent_id: str) -> AgentVersionDTO:
        return self._vs.get_latest_version(agent_id)

    # -------- Script Validation --------
    def validate_script(self, code: str) -> List[Dict[str, Any]]:
        violations = self._validator.validate_source(code)
        return [
            {"rule_id": v.rule_id, "code": v.code, "message": v.message, "lineno": v.lineno, "col": v.col}
            for v in violations
        ]

    # -------- Templates --------
    def add_template(self, name: str, diff_json: Dict[str, Any], author: str):
        return self._tpl.add_template(name, diff_json, author)

    def list_templates(self):
        return self._tpl.list_templates()

    def apply_template(self, agent_id: str, template_name: str, author: str) -> AgentVersionDTO:
        """读取模板 diff 并作为一个新版本应用; ���功后 params_version 递增 (通过 add_version)."""
        dto = self._tpl.get(template_name)  # 可能抛 TEMPLATE_NOT_FOUND
        return self.add_version(agent_id, diff_json=dto.diff_json, author=author)
