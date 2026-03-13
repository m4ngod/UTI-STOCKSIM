from app.utils.notification_center import NotificationCenter


def test_notification_center_capacity_and_order():
    center = NotificationCenter(capacity=1000)
    observed = []
    center.add_observer(lambda n: observed.append(n.id))
    for i in range(1100):
        center.push('info', f'msg-{i}')
    all_notes = center.get_all()
    assert center.size() == 1000
    assert len(all_notes) == 1000
    # 剩余应为 100..1099
    ids = [n.id for n in all_notes]
    assert ids[0] == 100
    assert ids[-1] == 1099
    assert ids == list(range(100, 1100))
    # 观察者收到全部 1100 次回调
    assert len(observed) == 1100
    assert observed[-1] == 1099


def test_notification_center_observer_remove_and_clear():
    center = NotificationCenter(capacity=5)
    called = []
    def obs(n):
        called.append(n.id)
    center.add_observer(obs)
    center.push('warn', 'a')
    center.remove_observer(obs)
    center.push('warn', 'b')
    assert called == [0]
    center.clear()
    assert center.size() == 0
    # 再 push 重新计数 id 从 0 开始
    note = center.push('info', 'after-clear')
    assert note.id == 0


def test_notification_center_invalid_capacity():
    import pytest
    with pytest.raises(ValueError):
        NotificationCenter(capacity=0)

