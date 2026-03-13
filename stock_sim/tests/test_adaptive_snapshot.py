from stock_sim.services.adaptive_snapshot_service import AdaptiveSnapshotPolicyManager
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType

def test_adaptive_snapshot_threshold_adjust():
    mgr = AdaptiveSnapshotPolicyManager(base_threshold=5, window_sec=0.5)
    captured = []
    event_bus.subscribe(EventType.SNAPSHOT_POLICY_CHANGED, lambda t,p: captured.append(p))
    sym = 'ABC'
    # 初始阈值
    assert mgr.get_threshold(sym) == 5
    # 模拟高频操作
    for _ in range(120):
        mgr.on_book_op(sym)
    mgr.maybe_adjust(sym)
    # 速率应提升阈值 (>=100 -> base*4)
    assert mgr.get_threshold(sym) >= 20
    assert any(c['new_threshold'] >= 20 for c in captured)

