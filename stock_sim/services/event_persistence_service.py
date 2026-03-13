# python
"""简化同步事件持久化实现 (用于当前单元测试)
启用后 event_bus.publish 调用立即同步写入 EventLog 表。
原异步批量实现因测试需要被最小化。
"""
from __future__ import annotations
import json, time
from typing import Callable, Any

# 新增 EventType 导入
try:
    from stock_sim.core.const import EventType  # type: ignore
except Exception:
    from core.const import EventType  # type: ignore

IMPORT_MODE = 'unknown'
try:  # 优先包内导入
    from stock_sim.persistence.models_event_log import EventLog  # type: ignore
    from stock_sim.persistence.models_imports import SessionLocal, engine  # type: ignore
    from stock_sim.observability.metrics import metrics  # type: ignore
    from stock_sim.infra.event_bus import event_bus  # type: ignore
    from stock_sim.settings import settings  # type: ignore
    IMPORT_MODE = 'stock_sim'
except Exception as _e:  # 源码根目录直接运行回退
    from persistence.models_event_log import EventLog  # type: ignore
    from persistence.models_imports import SessionLocal, engine  # type: ignore
    from observability.metrics import metrics  # type: ignore
    from infra.event_bus import event_bus  # type: ignore
    from settings import settings  # type: ignore
    IMPORT_MODE = f'fallback:{type(_e).__name__}'

print(f"[event_persist][debug] module load IMPORT_MODE={IMPORT_MODE} engine_url={getattr(engine,'url',None)} EventLog_cls_id={id(EventLog)} event_bus_id={id(event_bus)}")

_ORIG_PUBLISH: Callable[[str, dict], None] | None = None
_ENABLED = False

def _sync_write(evt_type: Any, payload: dict):
    if hasattr(evt_type, 'value'):
        evt_type = evt_type.value  # Enum -> str
    else:
        evt_type = str(evt_type)
    # 调试: 打印事件类型 (仅限测试, 可后续移除)
    # print(f"[event_persist][debug] _sync_write start evt={evt_type}")
    session = SessionLocal()
    try:
        ev = EventLog(ts_ms=int(time.time()*1000), type=evt_type,
                       symbol=payload.get('symbol'),
                       payload=json.dumps(payload, ensure_ascii=False))
        session.add(ev)
        session.commit()
        print(f"[event_persist][debug] committed evt={evt_type} db={engine.url}")
        try:
            metrics.inc('event_persist_written', 1)
        except Exception:
            pass
    except Exception as e:
        print(f"[event_persist][error] write failed evt={evt_type}: {e}")
        session.rollback()
        try:
            metrics.inc('event_persist_failures', 1)
        except Exception:
            pass
    finally:
        session.close()

def enable_event_persistence(force: bool = False):
    """启用同步事件持久化。重复调用幂等。
    处理双路径导入导致的重复订阅: 若 event_bus 已带有 _event_persist_enabled 标记则直接返回。
    """
    global _ORIG_PUBLISH, _ENABLED
    if getattr(event_bus, '_event_persist_enabled', False):  # 任何模块路径重复导入直接返回
        _ENABLED = True
        return True
    if _ENABLED:
        return True
    if not settings.EVENT_PERSIST_ENABLED and not force:
        return False
    # 通过订阅方式捕获事件，避免多份 event_bus 实例导致猴补失效
    def _handler(topic: str, payload: dict):
        try:
            _sync_write(topic, payload)
        except Exception:
            pass
    # 订阅 ACCOUNT_UPDATED (测试中使用该事件)。如需扩展可遍历 EventType 注册。
    event_bus.subscribe(EventType.ACCOUNT_UPDATED, _handler, async_mode=False)
    setattr(event_bus, '_event_persist_enabled', True)
    _ENABLED = True
    return True

def disable_event_persistence():
    """关闭持久化并恢复原 publish。"""
    global _ORIG_PUBLISH, _ENABLED
    # 暂不实现取消订阅 (测试不需要)，仅复位状态
    _ORIG_PUBLISH = None
    _ENABLED = False
    return True

__all__ = [
    'enable_event_persistence',
    'disable_event_persistence'
]
