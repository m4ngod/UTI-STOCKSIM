import app.utils.alerts as alerts_mod
from app.utils.alerts import AlertManager
from infra.event_bus import event_bus
from observability.metrics import metrics


def test_alert_heartbeat_manual_time_debounce_once():
    # 手动覆盖 alerts 模块内 time.time 以模拟时间推进
    fake_now = {'t': 1000.0}
    orig_time_fn = alerts_mod.time.time  # type: ignore[attr-defined]
    alerts_mod.time.time = lambda: fake_now['t']  # type: ignore
    try:
        collected = []
        event_bus.subscribe('alert.triggered', lambda topic, p: collected.append(p))
        hb_before = metrics.counters.get('alert.heartbeat_timeout', 0)
        suppressed_before = metrics.counters.get('alert_suppressed', 0)

        mgr = AlertManager(thresholds={'heartbeat_ms': 50}, debounce_seconds=60)
        # 第一次: 上次心跳 200ms 前 -> 触发
        fired1 = mgr.check_heartbeat(fake_now['t'] - 0.2)
        assert fired1 is True
        assert len(collected) == 1
        assert metrics.counters.get('alert.heartbeat_timeout', 0) == hb_before + 1

        # 时间推进 10s (仍在 60s 去抖窗口内) 再次检查 (仍满足超时条件) 应被去抑
        fake_now['t'] += 10.0
        fired2 = mgr.check_heartbeat(fake_now['t'] - 0.3)
        assert fired2 is False
        assert len(collected) == 1  # 仍只有一次通知
        assert metrics.counters.get('alert.heartbeat_timeout', 0) == hb_before + 1
        assert metrics.counters.get('alert_suppressed', 0) == suppressed_before + 1
    finally:
        alerts_mod.time.time = orig_time_fn  # 恢复

