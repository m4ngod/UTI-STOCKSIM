from app.panels.shared.notifications import notification_center
from app.panels.notifications_panel import NotificationsPanel
from app.ui.adapters.notifications_adapter import NotificationsPanelAdapter


def test_notifications_panel_adapter_push_and_filter():
    notification_center.clear_all()
    panel = NotificationsPanel()
    adapter = NotificationsPanelAdapter().bind(panel)
    # 初始刷新
    adapter.refresh()
    assert adapter.get_items() == []

    # 推送 3 条不同级别
    notification_center.publish_info('info.a', 'hello info')
    notification_center.publish_warning('warn.a', 'hello warn')
    notification_center.publish_error('err.a', 'hello error')

    items = adapter.get_items()
    assert len(items) == 3
    levels = {i['level'] for i in items}
    assert levels == {'info','warning','error'}

    # 过滤仅 error
    adapter.set_filter({'error'})
    items_err = adapter.get_items()
    assert len(items_err) == 1 and items_err[0]['level'] == 'error'

    # 清除过滤
    adapter.clear_filter()
    items_all = adapter.get_items()
    assert len(items_all) == 3

    # 压力: 超过 500 条 (中心最大 500) -> 保留最新
    notification_center.clear_all()
    # 再次推送 520 条 info
    for i in range(520):
        notification_center.publish_info(f'info.{i}', f'msg {i}')
    items2 = adapter.get_items()
    assert len(items2) == 500
    # 检查首尾 id 连续 (丢弃最早 20 条)
    first_id = items2[0]['id']
    last_id = items2[-1]['id']
    assert last_id - first_id + 1 == 500
    assert last_id == first_id + 499

