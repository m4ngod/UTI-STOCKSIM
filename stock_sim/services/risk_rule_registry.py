"""Risk Rule Registry (minimal)
提供风险规则注册/列出功能，供 RiskEngine 使用。
"""
from __future__ import annotations
from typing import List, Iterable
try:
    from stock_sim.infra.interfaces import IRiskRule  # type: ignore
except Exception:  # noqa
    from infra.interfaces import IRiskRule  # type: ignore

class RiskRuleRegistry:
    def __init__(self):
        self._rules: List[IRiskRule] = []  # type: ignore

    def register(self, rule: IRiskRule):  # type: ignore
        # 去重按 name
        names = {getattr(r, 'name', None) for r in self._rules}
        nm = getattr(rule, 'name', None)
        if nm and nm in names:
            return
        self._rules.append(rule)

    def list_rules(self) -> List[IRiskRule]:  # type: ignore
        return list(self._rules)

risk_rule_registry = RiskRuleRegistry()

# ---- 示例规则 (仅演示，不做真实约束) ----
class NoopAllowAllRule:
    name = "NoopAllowAll"
    def evaluate(self, **kwargs):  # 返回 None 表示通过
        return None

risk_rule_registry.register(NoopAllowAllRule())

__all__ = ["risk_rule_registry", "RiskRuleRegistry", "NoopAllowAllRule"]
