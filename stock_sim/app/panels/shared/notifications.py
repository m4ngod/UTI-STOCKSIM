"""统一错误与告警通知组件 (Spec Task 35)

目标:
- 统一 toast / dialog / 高亮 概念：后端此处以结构化数据表示，真实 UI 层可据 level & mode 渲染
- 事件来源：
  * 主动 API: publish_error/warning/info
  * 系统告警: 订阅 event_bus -> topic = 'alert.triggered'
  * 未来可扩展: network.error / script.validation 等事件
- metrics:
  * ui.notification_published 总计
  * ui.notification.<level>
  * ui.notification.code.<code>
- 高亮逻辑: 未确认 (ack=False) 且 level ∈ {error, alert} 认为需要高亮 (例如面板 tab 标红)
- 线程安全: RLock

Done 条件 (Spec): 模拟 5 类错误均可被获取 (见单元测试)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, Iterable
import time
from threading import RLock
from observability.metrics import metrics
from infra.event_bus import event_bus
import itertools

__all__ = ["Notification", "NotificationCenter", "notification_center"]

@dataclass
class Notification:
    id: int
    level: str  # info | warning | error | alert
    code: str
    message: str
    ts: float = field(default_factory=lambda: time.time())
    data: Dict | None = None
    mode: str = "toast"  # toast | dialog | inline
    ack: bool = False

class NotificationCenter:
    def __init__(self, *, max_size: int = 500):
        self._lock = RLock()
        self._items: List[Notification] = []
        self._max_size = max_size
        self._id_iter = itertools.count(1)
        # 可配置：哪些 code/level 默认使用 dialog (严重错误)
        self._dialog_error_codes = {"backend_timeout", "permission_denied", "script_violation"}
        # 订阅系统告警
        event_bus.subscribe('alert.triggered', self._on_alert_event, async_mode=False)

    # ---------------- Core API -----------------
    def publish(self, level: str, code: str, message: str, *, data: Optional[Dict] = None,
                mode: Optional[str] = None) -> Notification:
        if mode is None:
            # 严重错误走 dialog，其余 toast
            if level in ("error", "alert") and code in self._dialog_error_codes:
                mode = "dialog"
            else:
                mode = "toast"
        n = Notification(id=next(self._id_iter), level=level, code=code, message=message, data=data, mode=mode)
        with self._lock:
            self._items.append(n)
            if len(self._items) > self._max_size:
                # 丢弃最早的
                self._items = self._items[-self._max_size:]
        metrics.inc('ui.notification_published', 1)
        metrics.inc(f'ui.notification.{level}', 1)
        metrics.inc(f'ui.notification.code.{code}', 1)
        # 事件总线广播，便于 UI 层订阅
        event_bus.publish('ui.notification', {
            'id': n.id,
            'level': n.level,
            'code': n.code,
            'message': n.message,
            'ts': n.ts,
            'mode': n.mode,
        })
        return n

    # 便捷方法
    def publish_error(self, code: str, message: str, *, data: Optional[Dict] = None):
        return self.publish('error', code, message, data=data)
    def publish_warning(self, code: str, message: str, *, data: Optional[Dict] = None):
        return self.publish('warning', code, message, data=data)
    def publish_info(self, code: str, message: str, *, data: Optional[Dict] = None):
        return self.publish('info', code, message, data=data)

    # ---------------- Retrieval ----------------
    def get_recent(self, limit: int = 50, *, levels: Optional[Iterable[str]] = None) -> List[Notification]:
        with self._lock:
            items = list(self._items)
        if levels:
            lv_set = set(levels)
            items = [n for n in items if n.level in lv_set]
        return items[-limit:]

    def get_unacked(self) -> List[Notification]:
        with self._lock:
            return [n for n in self._items if not n.ack]

    def acknowledge(self, notif_id: int) -> bool:
        with self._lock:
            for n in self._items:
                if n.id == notif_id:
                    n.ack = True
                    return True
        return False

    def clear_all(self):
        with self._lock:
            self._items.clear()

    def clear_by_code(self, code: str):
        with self._lock:
            self._items = [n for n in self._items if n.code != code]

    def get_highlight_codes(self) -> List[str]:
        with self._lock:
            return sorted({n.code for n in self._items if not n.ack and n.level in ("error", "alert")})

    # ---------------- Event Handlers -----------
    def _on_alert_event(self, _topic: str, payload: Dict):  # payload: {'type','message','data','ts'}
        kind = payload.get('type', 'alert')
        msg = payload.get('message', kind)
        # 归类为 alert level, code=kind
        self.publish('alert', kind, msg, data=payload.get('data'))

# 单例
notification_center = NotificationCenter()

