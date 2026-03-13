"""NotificationsPanel

逻辑: 基于 shared.notification_center 提供视图模型
view 结构:
{
  'notifications': [ {id, level, code, message, ts, mode, ack}, ... 按 id 升序截断 <=500 ],
  'filter_levels': list | None,
  'last_update_ms': epoch_ms
}

API:
- set_filter_levels(levels | None)
- clear_filter()
- get_view()

刷新策略: 每次 get_view 直接从 notification_center.get_recent(500, levels=filter) 拉取
(内部中心已保证最大 500, 再次截断防御)。
"""
from __future__ import annotations
from typing import Iterable, Optional, List, Dict, Any
import time
from app.panels.shared.notifications import notification_center

__all__ = ["NotificationsPanel"]

class NotificationsPanel:
    def __init__(self):
        self._filter: Optional[set[str]] = None
        self._last_update_ms: int = int(time.time()*1000)

    # ----- Public API -----
    def set_filter_levels(self, levels: Optional[Iterable[str]]):
        prev = self._filter
        self._filter = set(levels) if levels else None
        if prev != self._filter:
            self._touch()

    def clear_filter(self):
        if self._filter is not None:
            self._filter = None
            self._touch()

    def get_view(self) -> Dict[str, Any]:
        levels = list(self._filter) if self._filter else None
        notes = notification_center.get_recent(500, levels=levels)  # list[Notification]
        data: List[Dict[str, Any]] = []
        for n in notes:
            data.append({
                'id': n.id,
                'level': n.level,
                'code': n.code,
                'message': n.message,
                'ts': n.ts,
                'mode': n.mode,
                'ack': n.ack,
            })
        return {
            'notifications': data,
            'filter_levels': levels,
            'last_update_ms': self._last_update_ms,
        }

    # ----- Internal -----
    def _touch(self):
        self._last_update_ms = int(time.time()*1000)

