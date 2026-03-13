from __future__ import annotations
from typing import Any, Dict
try:
    from stock_sim.infra.event_bus import event_bus  # type: ignore
    from stock_sim.core.const import EventType  # type: ignore
except Exception:  # 源码直接运行
    from infra.event_bus import event_bus  # type: ignore
    from core.const import EventType  # type: ignore

# ---- 全局状态 (简化) ----
_READONLY = False          # 恢复失败进入只读
_SENT_RESUMED = False      # 是否已发送恢复完成事件（首笔订单时避免重复）

class RecoveryService:
    """最小恢复服务占位实现。
    真实实现应: 读取最近快照 / 事件回放 / 校验一致性。
    这里仅模拟发布 RECOVERY_RESUMED 事件并返回报告。
    """
    def recover(self) -> Dict[str, Any]:
        global _READONLY, _SENT_RESUMED
        _READONLY = False
        report = {"status": "ok", "details": "stub", "restored_entities": 0}
        try:
            event_bus.publish(EventType.RECOVERY_RESUMED, report)
            _SENT_RESUMED = True
        except Exception:  # noqa
            pass
        return report

def is_readonly() -> bool:
    return _READONLY

def mark_failed(reason: str = "unknown"):
    """标记恢复失败进入只读 (当前未被测试调用, 为兼容扩展)。"""
    global _READONLY
    if _READONLY:
        return
    _READONLY = True
    try:
        event_bus.publish(EventType.RECOVERY_FAILED, {"reason": reason})
    except Exception:
        pass

def mark_resumed_if_needed():
    """若不在只读且尚未发送过 RECOVERY_RESUMED，则发送一次。
    OrderService.place_order 首笔调用时使用。"""
    global _SENT_RESUMED
    if _READONLY:
        return
    if _SENT_RESUMED:
        return
    try:
        event_bus.publish(EventType.RECOVERY_RESUMED, {"status": "ok", "lazy": True})
        _SENT_RESUMED = True
    except Exception:
        pass

recovery_service = RecoveryService()

__all__ = ["RecoveryService", "recovery_service", "is_readonly", "mark_resumed_if_needed", "mark_failed"]
