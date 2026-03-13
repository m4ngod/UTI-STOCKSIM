import time
from stock_sim.persistence import models_init
from stock_sim.services.event_persistence_service import enable_event_persistence
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType
from stock_sim.services.replay_service import replay_service
from stock_sim.services.recovery_service import recovery_service


def test_replay_and_recovery_integration():
    # 1. 初始化数据库模型 (清理旧表)
    models_init.init_models()
    # 2. 启用事件持久化 (强制)
    assert enable_event_persistence(force=True)

    # 3. 生成一批可回放事件 (ACCOUNT_UPDATED 已被持久化订阅)
    N = 8
    for i in range(N):
        event_bus.publish(EventType.ACCOUNT_UPDATED, {"i": i, "balance": 1000 + i})

    # 按当前同步写设计理论不需等待，为稳健性保留极短 sleep
    time.sleep(0.05)

    # 4. 回放前直接装载事件验证数量
    loaded = replay_service.load_events()
    assert len(loaded) >= N
    first_payload_keys = set(loaded[0]['payload'].keys())
    assert 'i' in first_payload_keys

    # 5. 回放: 收集 payload.i 顺序，确保顺序与生成一致 (前 N 条)
    collected = []
    replay_count = replay_service.replay(lambda ev: collected.append(ev['payload'].get('i')) if 'i' in ev['payload'] else None)
    assert replay_count == len(loaded)
    # 断言前 N 条的 i 单调递增 (存在足够事件)
    assert collected[:N] == list(range(N))

    # 6. 模拟“崩溃”：这里简化为清空本地聚合，再执行恢复
    collected.clear()

    captured_recovery = []
    event_bus.subscribe(EventType.RECOVERY_RESUMED, lambda t, p: captured_recovery.append(p))
    rep = recovery_service.recover()
    assert rep['status'] == 'ok'
    assert captured_recovery and captured_recovery[0]['status'] == 'ok'

    # 7. 再次回放验证仍可访问历史事件 (幂等性: 数据未丢失)
    replay_service.replay(lambda ev: collected.append(ev['payload'].get('i')) if 'i' in ev['payload'] else None, limit=N)
    assert collected == list(range(N))

