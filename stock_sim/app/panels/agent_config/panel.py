"""AgentConfigPanel (Spec Task 30)

职责 (R7,R8,R9):
- 参数版本管理: 列表 / 新增 / 回滚 (依赖 AgentConfigController)
- 热更新: 新增版本后若 agent 存在其 params_version 已由控制器同步 (R7,R8)
- 脚本上传校验: 调用 ScriptValidator (经控制器接口) -> 若存在 violations 或抛 ScriptValidationError 则阻断版本新增 ("AST 校验失败阻断") (R9)

设计:
- 纯逻辑, 与实际 GUI 解耦; 可被 UI 周期性 get_view()
- 线程安全: RLock

get_view() 返回结构:
{
  'agent_id': str,
  'versions': [ {version, created_at, author, rollback_of}... ],
  'latest_version': int | None,
  'latest_params_version': int | None,  # 若 AgentService 中存在该智能体
  'script': {
      'last_violations': [ {rule_id, code, message, lineno, col} ... ] | None,
      'last_error': str | None,  # 语法错误/文件过大等异常 code
  }
}

公开方法:
- refresh()
- add_version(diff_json: dict, *, author: str, script_code: str | None = None) -> bool
- rollback(target_version: int, *, author: str) -> bool

返回值: True=成功(产生新版本); False=失败(脚本不通过或异常)
"""
from __future__ import annotations
from threading import RLock
from typing import Dict, Any, List, Optional

from app.controllers.agent_config_controller import AgentConfigController
from app.services.agent_service import AgentService, AgentServiceError
from app.state.version_store import VersionStoreError
from app.security.script_validator import ScriptValidationError

try:  # metrics 可选
    from observability.metrics import metrics
except Exception:  # pragma: no cover
    class _Dummy:
        def inc(self, *a, **kw):
            pass
    metrics = _Dummy()

__all__ = ["AgentConfigPanel"]

class AgentConfigPanel:
    def __init__(self, agent_id: str, controller: AgentConfigController, service: AgentService):
        self._agent_id = agent_id
        self._ctl = controller
        self._svc = service
        self._lock = RLock()
        self._versions_cache: List[Dict[str, Any]] = []
        self._latest_version: Optional[int] = None
        self._last_violations: Optional[List[Dict[str, Any]]] = None
        self._last_error: Optional[str] = None
        self.refresh()

    # --------------- Core Ops ---------------
    def refresh(self):
        try:
            versions = self._ctl.list_versions(self._agent_id, reverse=False)
        except VersionStoreError:
            versions = []
        arr: List[Dict[str, Any]] = []
        latest = None
        for v in versions:
            arr.append({
                'version': v.version,
                'created_at': v.created_at,
                'author': v.author,
                'rollback_of': v.rollback_of,
            })
            latest = v.version
        with self._lock:
            self._versions_cache = arr
            self._latest_version = latest

    def add_version(self, diff_json: Dict[str, Any], *, author: str, script_code: Optional[str] = None) -> bool:
        # 脚本校验
        if script_code is not None:
            try:
                violations = self._ctl.validate_script(script_code)
            except ScriptValidationError as e:
                with self._lock:
                    self._last_error = e.code
                    self._last_violations = None
                metrics.inc('agent_config_script_error')
                return False
            if violations:  # 有违规 -> 阻断
                with self._lock:
                    self._last_violations = violations
                    self._last_error = 'SCRIPT_VIOLATIONS'
                metrics.inc('agent_config_script_violation_block')
                return False
        # 清理脚本状态
        with self._lock:
            self._last_violations = None
            self._last_error = None
        # 捕获新增前 params_version 以检测异常 (若被外部篡改则 diff 不为 1)
        prev_params_version = None
        try:
            ag_before = self._svc.get(self._agent_id)
            if ag_before:
                prev_params_version = ag_before.params_version
        except Exception:  # pragma: no cover
            pass
        try:
            dto = self._ctl.add_version(self._agent_id, diff_json=diff_json, author=author)
            metrics.inc('agent_config_version_add')
        except Exception:  # noqa: BLE001 - 任何异常视为失败
            metrics.inc('agent_config_version_add_fail')
            return False
        # 刷新缓存
        self.refresh()
        # 校验 params_version 逻辑: 正常情况下新版本应为 prev+1 (或 prev 为 0/None -> 新=1)
        if prev_params_version is not None:
            try:
                if (dto.version - prev_params_version) != 1:
                    metrics.inc('agent_config_params_version_mismatch')
            except Exception:  # pragma: no cover
                pass
        return True

    def rollback(self, target_version: int, *, author: str) -> bool:
        try:
            dto = self._ctl.rollback(self._agent_id, target_version, author)
            metrics.inc('agent_config_version_rollback')
        except VersionStoreError:
            metrics.inc('agent_config_version_rollback_fail')
            return False
        except Exception:
            metrics.inc('agent_config_version_rollback_fail')
            return False
        self.refresh()
        # 回滚后版本应大于之前最新
        with self._lock:
            if self._latest_version is not None and dto.version < self._latest_version:
                metrics.inc('agent_config_version_rollback_anomaly')
        return True

    # --------------- View ---------------
    def get_view(self) -> Dict[str, Any]:
        with self._lock:
            versions = list(self._versions_cache)
            latest = self._latest_version
            last_violations = None if self._last_violations is None else [dict(v) for v in self._last_violations]
            last_error = self._last_error
        ag = self._svc.get(self._agent_id)
        return {
            'agent_id': self._agent_id,
            'versions': versions,
            'latest_version': latest,
            'latest_params_version': (ag.params_version if ag else None),
            'script': {
                'last_violations': last_violations,
                'last_error': last_error,
            }
        }
