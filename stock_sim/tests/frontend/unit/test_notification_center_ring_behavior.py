from app.utils.notification_center import NotificationCenter
from observability.metrics import metrics


def test_notification_center_overflow_and_observer_count():
    cap = 10
    total = 25
    center = NotificationCenter(capacity=cap)
    calls = []
    def obs(note):  # 收集所有推送 id
        calls.append(note.id)
    center.add_observer(obs)

    base_push = metrics.counters.get('notification_push', 0)
    for i in range(total):
        n = center.push('info', f'msg-{i}')
        assert n.id == i  # 递增 id
    # observer 调用次数 = total
    assert len(calls) == total
    # ring 中仅保留最后 cap 条
    notes = center.get_all()
    assert len(notes) == cap
    # 校验顺序 oldest -> newest & id 范围
    expected_ids = list(range(total - cap, total))
    assert [n.id for n in notes] == expected_ids
    # size() 与 capacity()
    assert center.size() == cap
    assert center.capacity() == cap
    # metrics push 计数增量
    assert metrics.counters.get('notification_push', 0) >= base_push + total


def test_notification_center_clear_resets_and_restarts_ids():
    center = NotificationCenter(capacity=5)
    for i in range(7):
        center.push('warn', f'w{i}')
    assert center.size() == 5
    base_clear = metrics.counters.get('notification_clear', 0)
    center.clear()
    assert center.size() == 0
    # clear 后 id 重置
    n0 = center.push('info', 'after-clear')
    assert n0.id == 0
    assert metrics.counters.get('notification_clear', 0) == base_clear + 1


def test_notification_center_remove_observer():
    center = NotificationCenter(capacity=5)
    calls_a = []
    calls_b = []
    def oa(n): calls_a.append(n.id)
    def ob(n): calls_b.append(n.id)
    center.add_observer(oa)
    center.add_observer(ob)
    for i in range(3):
        center.push('info', f'a{i}')
    assert calls_a == [0,1,2]
    assert calls_b == [0,1,2]
    center.remove_observer(ob)
    for i in range(3,6):
        center.push('info', f'a{i}')
    # oa 收到全部 0..5
    assert calls_a == [0,1,2,3,4,5]
    # ob 只收到移除前的 0..2
    assert calls_b == [0,1,2]

