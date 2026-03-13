"""AST 规则与注册表 (Spec Task 14)

提供可扩展 ASTRuleRegistry, 支持注册多条规则并运行于 AST。规则需实现:
- id: str  唯一标识
- description: str 描述
- check(module_ast: ast.AST, context: dict) -> list[Violation]

Violation:
- rule_id
- message
- lineno / col_offset (可为 None)
- code: 简短错误代码

内置规则:
1. ForbiddenImportsRule: 禁止导入危险模块 (默认: os, sys, subprocess, socket)
2. ForbiddenAttributesRule: 禁止使用危险内置/名称 (默认: __import__, eval, exec)
3. WhitelistImportsRule: 若启用 import 白名单, 非白名单顶级模块即违规 (context['whitelist'] 提供)

后续可扩展: 文件系统访问, 网络访问调用, 动态执行等。
"""
from __future__ import annotations
import ast
from dataclasses import dataclass
from typing import List, Iterable, Dict, Any, Optional

@dataclass
class Violation:
    rule_id: str
    code: str
    message: str
    lineno: Optional[int]
    col: Optional[int]

class ASTRule:
    id: str = "base"
    description: str = ""
    def check(self, module_ast: ast.AST, context: Dict[str, Any]) -> List[Violation]:  # pragma: no cover - 接口
        raise NotImplementedError

# ---------------- 内置规则 ----------------
class ForbiddenImportsRule(ASTRule):
    id = "forbidden_imports"
    description = "禁止危险模块 import"
    def __init__(self, forbidden: Iterable[str]):
        self._forbidden = set(forbidden)
    def check(self, module_ast: ast.AST, context: Dict[str, Any]) -> List[Violation]:
        v: List[Violation] = []
        for node in ast.walk(module_ast):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split('.')[0]
                    if top in self._forbidden:
                        v.append(Violation(self.id, 'FORBIDDEN_IMPORT', f"forbidden import: {top}", node.lineno, node.col_offset))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split('.')[0]
                    if top in self._forbidden:
                        v.append(Violation(self.id, 'FORBIDDEN_IMPORT', f"forbidden import: {top}", node.lineno, node.col_offset))
        return v

class ForbiddenAttributesRule(ASTRule):
    id = "forbidden_attributes"
    description = "禁止危险内置/属性调用"
    def __init__(self, forbidden_names: Iterable[str]):
        self._forbidden = set(forbidden_names)
    def check(self, module_ast: ast.AST, context: Dict[str, Any]) -> List[Violation]:
        v: List[Violation] = []
        for node in ast.walk(module_ast):
            # 直接名称引用
            if isinstance(node, ast.Name) and node.id in self._forbidden:
                v.append(Violation(self.id, 'FORBIDDEN_ATTR', f"forbidden name usage: {node.id}", node.lineno, node.col_offset))
            # getattr 形式 eval/exec 变体暂不处理 (后续扩展)
        return v

class WhitelistImportsRule(ASTRule):
    id = "whitelist_imports"
    description = "限制仅允许 import 白名单模块"
    def check(self, module_ast: ast.AST, context: Dict[str, Any]) -> List[Violation]:
        whitelist: Optional[set[str]] = context.get('whitelist')  # type: ignore
        if not whitelist:
            return []
        v: List[Violation] = []
        for node in ast.walk(module_ast):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split('.')[0]
                    if top not in whitelist:
                        v.append(Violation(self.id, 'IMPORT_NOT_WHITELISTED', f"import not in whitelist: {top}", node.lineno, node.col_offset))
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split('.')[0]
                if top not in whitelist:
                    v.append(Violation(self.id, 'IMPORT_NOT_WHITELISTED', f"import not in whitelist: {top}", node.lineno, node.col_offset))
        return v

# ---------------- 注册表 ----------------
class ASTRuleRegistry:
    def __init__(self):
        self._rules: Dict[str, ASTRule] = {}
    def register(self, rule: ASTRule):
        self._rules[rule.id] = rule
    def run(self, module_ast: ast.AST, context: Dict[str, Any] | None = None) -> List[Violation]:
        ctx = context or {}
        violations: List[Violation] = []
        for r in self._rules.values():
            violations.extend(r.check(module_ast, ctx))
        return violations

# 默认注册表构造函数

def build_default_registry(whitelist: Iterable[str] | None = None) -> ASTRuleRegistry:
    reg = ASTRuleRegistry()
    reg.register(ForbiddenImportsRule(['os', 'sys', 'subprocess', 'socket']))
    reg.register(ForbiddenAttributesRule(['__import__', 'eval', 'exec']))
    if whitelist is not None:
        reg.register(WhitelistImportsRule())
    return reg

__all__ = [
    'Violation',
    'ASTRule',
    'ForbiddenImportsRule',
    'ForbiddenAttributesRule',
    'WhitelistImportsRule',
    'ASTRuleRegistry',
    'build_default_registry',
]

