"""NotificationWidget 简单头less 组件

用途: E2E 测试中验证通知中心是否已收到告警(ALERT)。
提供 list_items() 返回最近通知 (level 大写) 以便断言。
"""
from __future__ import annotations
from typing import List, Dict
from .notifications import notification_center

class NotificationWidget:
    def __init__(self, *, center=notification_center):
        self._center = center
    def list_items(self, limit: int = 50) -> List[Dict]:
        items = self._center.get_recent(limit)
        return [
            {"level": n.level.upper(), "code": n.code, "message": n.message, "id": n.id}
            for n in items
        ]

__all__ = ["NotificationWidget"]

