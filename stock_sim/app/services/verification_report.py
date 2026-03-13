from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, List, Dict, Iterable

__all__ = ["VerificationIssue", "VerificationReport", "generate_verification_report"]

@dataclass
class VerificationIssue:
    field: str
    expected: Any
    actual: Any
    kind: str  # 'missing' | 'extra' | 'diff'

@dataclass
class VerificationReport:
    ok: bool
    issues: List[VerificationIssue] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [issue.__dict__ for issue in self.issues],
            "issue_count": len(self.issues),
        }

def generate_verification_report(expected: Dict[str, Any], actual: Dict[str, Any], *, fields: Iterable[str] | None = None) -> VerificationReport:
    """对比 expected 与 actual, 生成 VerificationReport.
    - 缺失键: kind = 'missing'
    - 多余键: kind = 'extra'
    - 值不同: kind = 'diff'
    若 fields 指定, 只对该字段集合做 expected/actual 对比 (extra 逻辑仍在集合内)。
    """
    issues: List[VerificationIssue] = []
    if fields is None:
        key_set = set(expected.keys()) | set(actual.keys())
    else:
        fset = set(fields)
        key_set = (set(expected.keys()) | set(actual.keys())) & fset

    for k in sorted(key_set):
        exp_present = k in expected
        act_present = k in actual
        if not exp_present and act_present:
            issues.append(VerificationIssue(field=k, expected=None, actual=actual.get(k), kind='extra'))
            continue
        if exp_present and not act_present:
            issues.append(VerificationIssue(field=k, expected=expected.get(k), actual=None, kind='missing'))
            continue
        # both present
        if expected[k] != actual[k]:  # 简单值比较
            issues.append(VerificationIssue(field=k, expected=expected.get(k), actual=actual.get(k), kind='diff'))

    return VerificationReport(ok=len(issues) == 0, issues=issues)

