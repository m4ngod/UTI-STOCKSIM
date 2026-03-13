from observability.metrics import metrics
from infra.event_bus import event_bus
from app.panels.shared.notifications import notification_center, Notification


def test_notification_center_publish_and_alert_bridge():
    # 清理初始状态
    notification_center.clear_all()

    base_total = metrics.counters.get('ui.notification_published', 0)
    base_info = metrics.counters.get('ui.notification.info', 0)
    base_warn = metrics.counters.get('ui.notification.warning', 0)
    base_err = metrics.counters.get('ui.notification.error', 0)
    base_alert = metrics.counters.get('ui.notification.alert', 0)

    # 1 info
    n_info = notification_center.publish_info('system.ready', 'Ready')
    # 2 warning
    n_warn = notification_center.publish_warning('latency.high', 'Latency high 180ms')
    # 3 error (dialog) - backend_timeout 在默认 dialog 错误集合
    n_err_dialog = notification_center.publish_error('backend_timeout', 'Backend timeout 2s')
    # 4 error (toast) - misc_error 不在 dialog 列表
    n_err_toast = notification_center.publish_error('misc_error', 'Unknown error occurred')
    # 5 alert 经由告警事件桥接 (模拟 drawdown)
    event_bus.publish('alert.triggered', {
        'type': 'drawdown',
        'message': 'Drawdown 15% >= 10%',
        'data': {'drawdown': 0.15, 'threshold': 0.10},
        'ts': 123.456,
    })

    recent = notification_center.get_recent(10)
    codes = [n.code for n in recent]
    assert {'system.ready','latency.high','backend_timeout','misc_error','drawdown'} <= set(codes)

    # 模式判定
    assert n_err_dialog.mode == 'dialog'
    assert n_err_toast.mode == 'toast'

    # 高亮代码: error + alert 且未 ack
    highlight = notification_center.get_highlight_codes()
    assert 'backend_timeout' in highlight and 'misc_error' in highlight and 'drawdown' in highlight
    assert 'system.ready' not in highlight and 'latency.high' not in highlight

    # ack 一个错误 -> highlight 移除
    notification_center.acknowledge(n_err_toast.id)
    highlight2 = notification_center.get_highlight_codes()
    assert 'misc_error' not in highlight2 and 'backend_timeout' in highlight2

    # 按级别过滤
    only_errors = notification_center.get_recent(10, levels=['error'])
    assert all(n.level == 'error' for n in only_errors)

    # 按 code 清理
    notification_center.clear_by_code('backend_timeout')
    codes_after_clear = [n.code for n in notification_center.get_recent(20)]
    assert 'backend_timeout' not in codes_after_clear

    # 指标: 总数至少 +5, 各级别至少 +1
    assert metrics.counters.get('ui.notification_published', 0) >= base_total + 5
    assert metrics.counters.get('ui.notification.info', 0) >= base_info + 1
    assert metrics.counters.get('ui.notification.warning', 0) >= base_warn + 1
    assert metrics.counters.get('ui.notification.error', 0) >= base_err + 2  # 两条 error
    assert metrics.counters.get('ui.notification.alert', 0) >= base_alert + 1

    # 代码级别计数存在
    for c in ['system.ready','latency.high','backend_timeout','misc_error','drawdown']:
        assert metrics.counters.get(f'ui.notification.code.{c}', 0) > 0

