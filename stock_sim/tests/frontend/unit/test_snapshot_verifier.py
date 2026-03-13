from app.services.account_service import AccountService
from app.services.agent_service import AgentService, BatchCreateConfig
from app.services.snapshot_verifier import SnapshotVerifier
from app.panels.shared.notifications import notification_center


def test_snapshot_verifier_ok():
    notification_center.clear_all()
    acc = AccountService()
    ag = AgentService()
    acc.load_account('ACC1')
    ag.batch_create_retail(BatchCreateConfig(count=2, agent_type='Retail', name_prefix='sv'))
    base = SnapshotVerifier.capture(acc, ag)
    assert SnapshotVerifier.verify(base, acc, ag) is True
    # 没有 mismatch 通知
    notes = [n for n in notification_center.get_recent(10) if n.code == 'snapshot.mismatch']
    assert len(notes) == 0


def test_snapshot_verifier_mismatch_triggers_alert():
    notification_center.clear_all()
    acc = AccountService()
    ag = AgentService()
    acc.load_account('ACCX')
    ag.batch_create_retail(BatchCreateConfig(count=1, agent_type='Retail', name_prefix='sv'))
    base = SnapshotVerifier.capture(acc, ag)
    # 制造不匹配: 改 equity 和 agents 数量
    # 修改账户 equity
    acc._last_account.equity += 123.45  # type: ignore[attr-defined]
    # 新增一个 agent
    ag.batch_create_retail(BatchCreateConfig(count=1, agent_type='Retail', name_prefix='sv2'))
    ok = SnapshotVerifier.verify(base, acc, ag, equity_tol_ratio=0.0)
    assert ok is False
    # alert 已转换为 notification (alert.triggered 订阅机制)
    notes = [n for n in notification_center.get_recent(10) if n.code == 'snapshot.mismatch']
    assert len(notes) == 1
    note = notes[0]
    assert 'equity' in note.message or 'agent_count' in note.message
    assert 'mismatches' in note.data

