"""SnapshotVerifier

快速( <50ms 典型 )校验当前运行态与基线摘要是否匹配:
- 字段: account_id, equity, agent_count
- 仅做轻量对比 (跳过重量 diff)
- 不一致时发布 alert.triggered 事件 (code = snapshot.mismatch)

用法:
    baseline = SnapshotVerifier.capture(account_service, agent_service)
    ... 状态变化 ...
    ok = SnapshotVerifier.verify(baseline, account_service, agent_service)

返回 True 表示一致, False 表示不一致 (已发送 ALERT)。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
from infra.event_bus import event_bus
from observability.metrics import metrics

@dataclass
class SnapshotSummary:
    account_id: Optional[str]
    equity: float
    agent_count: int

class SnapshotVerifier:
    @staticmethod
    def capture(account_service, agent_service) -> SnapshotSummary:  # noqa: ANN001
        acc = getattr(account_service, 'get_cached', lambda: None)()
        account_id = getattr(acc, 'account_id', None)
        equity = float(getattr(acc, 'equity', 0.0) or 0.0)
        agents = getattr(agent_service, 'list_agents', lambda: [])()
        agent_count = len(agents) if agents else 0
        return SnapshotSummary(account_id=account_id, equity=equity, agent_count=agent_count)

    @staticmethod
    def verify(baseline: SnapshotSummary, account_service, agent_service, *, equity_tol_ratio: float = 1e-6) -> bool:  # noqa: ANN001
        """对比当前摘要与 baseline.
        equity 允许极小相对误差 (默认 1e-6)。
        任意字段不匹配 -> 发布 ALERT (snapshot.mismatch)。
        """
        current = SnapshotVerifier.capture(account_service, agent_service)
        mismatches: Dict[str, Any] = {}
        if baseline.account_id != current.account_id:
            mismatches['account_id'] = {'baseline': baseline.account_id, 'current': current.account_id}
        # equity 比较
        denom = abs(baseline.equity) if baseline.equity != 0 else 1.0
        if abs(baseline.equity - current.equity) / denom > equity_tol_ratio:
            mismatches['equity'] = {'baseline': baseline.equity, 'current': current.equity}
        if baseline.agent_count != current.agent_count:
            mismatches['agent_count'] = {'baseline': baseline.agent_count, 'current': current.agent_count}
        if not mismatches:
            metrics.inc('snapshot_verify_ok')
            return True
        # 构造消息 (限制长度)
        fields = ', '.join(mismatches.keys())
        msg = f'Snapshot mismatch: {fields}'
        event_bus.publish('alert.triggered', {
            'type': 'snapshot.mismatch',
            'message': msg,
            'data': {
                'mismatches': mismatches,
            }
        })
        metrics.inc('snapshot_verify_fail')
        return False

__all__ = ['SnapshotVerifier', 'SnapshotSummary']

