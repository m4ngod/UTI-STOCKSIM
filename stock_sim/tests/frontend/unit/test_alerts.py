import time
from infra.event_bus import event_bus
from observability.metrics import metrics
from app.utils.alerts import AlertManager


def test_alert_drawdown_debounce():
    collected = []
    event_bus.subscribe('alert.triggered', lambda topic, p: collected.append(p))
    base_drawdown_missing_before = metrics.counters.get('alert.drawdown', 0)
    suppressed_before = metrics.counters.get('alert_suppressed', 0)

    mgr = AlertManager(thresholds={'drawdown_pct': 0.1}, debounce_seconds=60)
    # peak 100, current 85 => 15% >=10% 触发
    fired1 = mgr.check_drawdown(85, 100)
    # 再次触发 (仍在 60s 窗口) 应去抖
    fired2 = mgr.check_drawdown(80, 100)

    assert fired1 is True
    assert fired2 is False
    assert len(collected) == 1
    assert metrics.counters.get('alert.drawdown', 0) == base_drawdown_missing_before + 1
    assert metrics.counters.get('alert_suppressed', 0) == suppressed_before + 1


def test_alert_heartbeat_and_low_balance():
    collected = []
    event_bus.subscribe('alert.triggered', lambda topic, p: collected.append(p))
    hb_before = metrics.counters.get('alert.heartbeat_timeout', 0)
    bal_before = metrics.counters.get('alert.low_balance', 0)

    mgr = AlertManager(thresholds={'heartbeat_ms': 50, 'min_balance': 1000}, debounce_seconds=1)
    # 心跳超时: 上次心跳 0.2s 之前 (>50ms)
    fired_hb = mgr.check_heartbeat(time.time() - 0.2)
    assert fired_hb is True
    # 低余额
    fired_bal = mgr.check_balance(500)
    assert fired_bal is True
    # 去抖: 立即重复不会触发
    fired_hb_2 = mgr.check_heartbeat(time.time() - 0.3)
    assert fired_hb_2 is False

    assert metrics.counters.get('alert.heartbeat_timeout', 0) == hb_before + 1
    assert metrics.counters.get('alert.low_balance', 0) == bal_before + 1
    # 至少两条事件 (heartbeat + low_balance)
    types = {p['type'] for p in collected}
    assert 'heartbeat_timeout' in types and 'low_balance' in types


def test_drawdown_no_peak_or_threshold():
    mgr = AlertManager(thresholds={'heartbeat_ms': 10})  # 无 drawdown_pct
    assert mgr.check_drawdown(90, 100) is False  # 未配置阈值
    mgr.update_thresholds(drawdown_pct=0.2)
    # peak=0 忽略
    assert mgr.check_drawdown(0, 0) is False

