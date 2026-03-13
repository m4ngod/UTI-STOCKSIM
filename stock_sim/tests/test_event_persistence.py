import time
from stock_sim.services.event_persistence_service import enable_event_persistence
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType
from stock_sim.persistence.models_event_log import EventLog
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence import models_init

def test_event_persistence_write_and_flush():
    models_init.init_models()
    ok = enable_event_persistence(force=True)
    assert ok
    # 发布若干事件
    for i in range(5):
        event_bus.publish(EventType.ACCOUNT_UPDATED, {'i': i})
    # 等待后台线程 flush
    time.sleep(0.3)
    s = SessionLocal()
    try:
        cnt = s.query(EventLog).count()
        assert cnt >= 5
    finally:
        s.close()

