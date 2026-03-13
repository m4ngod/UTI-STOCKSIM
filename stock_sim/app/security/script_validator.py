"""ScriptValidator (Spec Task 14)

目标:
- 读取脚本 (文件/内存字符串) -> AST 解析
- 运行 ASTRuleRegistry 规则 (危险 import / 属性, 以及可选 import 白名单)
- 文件大小/行数限制; 语法错误捕获
- 返回 violations 列表; 若致命错误 (文件过大/语法错误) 抛出 ScriptValidationError

指标(可选):
- script_validate_start / script_validate_ok / script_validate_fail

后续扩展 (Task 36 会增加频率限制整合):
- 复杂资源访问模式检测
- 动态执行 (exec/eval 变体) 模式识别
"""
from __future__ import annotations
import ast
import os
from typing import List, Iterable, Optional, Dict, Any

from observability.metrics import metrics
from .ast_rules import (
    ASTRuleRegistry,
    build_default_registry,
    Violation,
)

# 可选通知中心 (Spec: Script 失败触发通知 + 去重)
try:  # pragma: no cover
    from app.panels.shared.notifications import notification_center as _notification_center
except Exception:  # pragma: no cover
    _notification_center = None

class ScriptValidationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

class ScriptValidator:
    def __init__(
        self,
        *,
        whitelist: Optional[Iterable[str]] = None,
        max_bytes: int = 50_000,
        registry: ASTRuleRegistry | None = None,
    ):
        self._whitelist = set(whitelist) if whitelist else None
        self._max_bytes = max_bytes
        self._registry = registry or build_default_registry(whitelist=self._whitelist)
        # 连续失败去重签名
        self._last_fail_sig: Optional[str] = None

    # ------------- Public API -------------
    def validate_file(self, path: str) -> List[Violation]:
        metrics.inc("script_validate_start")
        try:
            st = os.stat(path)
            if st.st_size > self._max_bytes:
                raise ScriptValidationError("FILE_TOO_LARGE", f"script size {st.st_size} > limit {self._max_bytes}")
            with open(path, "r", encoding="utf-8") as f:
                code = f.read()
            return self._validate_source(code, filename=path)
        except ScriptValidationError as e:
            metrics.inc("script_validate_fail")
            self._notify_exception_if_needed(e, path)
            raise

    def validate_source(self, code: str, *, filename: str = "<memory>") -> List[Violation]:
        metrics.inc("script_validate_start")
        try:
            return self._validate_source(code, filename=filename)
        except ScriptValidationError as e:
            metrics.inc("script_validate_fail")
            self._notify_exception_if_needed(e, filename, code)
            raise

    # ------------- Internal -------------
    def _validate_source(self, code: str, *, filename: str) -> List[Violation]:
        try:
            module = ast.parse(code, filename=filename, mode="exec")
        except SyntaxError as e:  # 语法错误直接抛异常
            raise ScriptValidationError("SYNTAX_ERROR", f"syntax error: {e.msg} at line {e.lineno}") from e
        context: Dict[str, Any] = {}
        if self._whitelist is not None:
            context['whitelist'] = self._whitelist
        violations = self._registry.run(module, context)
        if violations:
            # 不抛出, 交由上层展示; 仅记录失败计数
            metrics.inc("script_validate_fail")
            self._notify_violations_if_needed(violations, code, filename)
        else:
            metrics.inc("script_validate_ok")
        return violations

    # ------------- Notification Helpers -------------
    def _notify_violations_if_needed(self, violations: List[Violation], code: str, filename: str):
        if _notification_center is None:
            return
        # 签名: 违规代码 + 行列 (排序稳定)
        parts = sorted(f"{v.code}:{v.lineno}:{v.col}" for v in violations)
        sig = "VIOL:" + ";".join(parts)
        if sig == self._last_fail_sig:
            return
        self._last_fail_sig = sig
        codes_unique = sorted({v.code for v in violations})
        summary = f"Script validation failed ({len(violations)} violations): {', '.join(codes_unique)}"
        data = {
            'filename': filename,
            'violations': [
                {
                    'code': v.code,
                    'rule_id': v.rule_id,
                    'message': v.message,
                    'lineno': v.lineno,
                    'col': v.col,
                } for v in violations
            ],
            'signature': sig,
            'code_excerpt': code[:200],
        }
        try:  # 不影响主流程
            _notification_center.publish_error('script_violation', summary, data=data)
        except Exception:  # pragma: no cover
            pass

    def _notify_exception_if_needed(self, exc: ScriptValidationError, filename: str, code: str | None = None):
        if _notification_center is None:
            return
        sig = f"EXC:{exc.code}:{filename}"
        if sig == self._last_fail_sig:
            return
        self._last_fail_sig = sig
        summary = f"Script validation error ({exc.code})"
        data = {
            'filename': filename,
            'error_code': exc.code,
            'error_message': exc.message,
            'signature': sig,
        }
        if code is not None:
            data['code_excerpt'] = code[:200]
        try:  # pragma: no cover
            _notification_center.publish_error('script_violation', summary, data=data)
        except Exception:  # pragma: no cover
            pass

__all__ = [
    'ScriptValidator',
    'ScriptValidationError',
]
