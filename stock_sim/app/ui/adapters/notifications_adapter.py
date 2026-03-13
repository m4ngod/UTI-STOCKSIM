"""NotificationsPanelAdapter

功能:
- 绑定 NotificationsPanel 逻辑层
- 订阅 event_bus topic 'ui.notification' 实时刷新
- 提供级别过滤 (info / warning / error / alert) 按钮; 支持多个级别 toggle
- 保留最近 <=500 条 (逻辑层已限制, 适配器再防御截断)
- headless 环境下使用 stub 控件

测试钩子:
- get_items() 返回当前缓存的通知列表 (list[dict])
- set_filter(levels|None) / clear_filter()
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Iterable
from .base_adapter import PanelAdapter
from infra.event_bus import event_bus

try:  # GUI
    from PySide6.QtWidgets import (  # type: ignore
        QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QListWidgetItem, QLabel
    )
except Exception:  # pragma: no cover - headless fallback
    QWidget = object  # type: ignore
    class _Sig:  # type: ignore
        def __init__(self): self._fn=[]
        def connect(self,f): self._fn.append(f)
        def emit(self,*a,**k):
            for fn in list(self._fn):
                try: fn(*a, **k)
                except Exception: pass
    class QVBoxLayout:  # type: ignore
        def __init__(self,*_,**__): pass
        def addWidget(self,*_): pass
        def addLayout(self,*_): pass
    class QHBoxLayout:  # type: ignore
        def __init__(self,*_,**__): pass
        def addWidget(self,*_): pass
    class QPushButton:  # type: ignore
        def __init__(self,text=''): self._text=text; self._enabled=True; self.clicked=_Sig(); self._check=False
        def setCheckable(self,v): self._check=v
        def setChecked(self,v): self._check=v
        def isChecked(self): return self._check
    class QListWidget:  # type: ignore
        def __init__(self): self._items: List[str]=[]
        def clear(self): self._items.clear()
        def addItem(self, s): self._items.append(s)
        def count(self): return len(self._items)
    class QListWidgetItem:  # type: ignore
        def __init__(self,text=''): self._text=text
    class QLabel:  # type: ignore
        def __init__(self,text=''): self._text=text
        def setText(self,t): self._text=t

_LEVELS = ["info","warning","error","alert"]

class NotificationsPanelAdapter(PanelAdapter):
    def __init__(self):
        super().__init__()
        self._root: Optional[Any] = None
        self._list: Optional[Any] = None
        self._lbl_count: Optional[Any] = None
        self._btns: Dict[str, Any] = {}
        self._active_levels: Optional[set[str]] = None  # None=全部
        self._items: List[Dict[str, Any]] = []  # 缓存最近显示的数据
        # 订阅通知事件
        event_bus.subscribe('ui.notification', self._on_notification, async_mode=False)

    # ---- Public helpers (测试使用) ----
    def get_items(self) -> List[Dict[str, Any]]:
        return list(self._items)
    def set_filter(self, levels: Iterable[str] | None):
        self._active_levels = set(levels) if levels else None
        logic = getattr(self, '_logic', None)
        if logic is not None and hasattr(logic, 'set_filter_levels'):
            logic.set_filter_levels(self._active_levels)
        self.refresh()
    def clear_filter(self):
        self.set_filter(None)

    # ---- Event handler ----
    def _on_notification(self, _topic: str, _payload: dict):  # noqa: ANN001
        # 来新通知时刷新 (依赖逻辑层 get_view)
        self.refresh()

    # ---- Overrides ----
    def _create_widget(self):  # noqa: D401
        root = QWidget()  # type: ignore
        try:
            v = QVBoxLayout(root)  # type: ignore
            # filter buttons
            hb = QHBoxLayout()  # type: ignore
            for lv in _LEVELS:
                btn = QPushButton(lv.capitalize())  # type: ignore
                try:
                    btn.setCheckable(True)  # type: ignore[attr-defined]
                    btn.setChecked(True)  # 默认选中 (表示不过滤)
                    btn.clicked.connect(self._make_toggle_handler(lv))  # type: ignore[attr-defined]
                except Exception:  # pragma: no cover
                    pass
                self._btns[lv] = btn
                hb.addWidget(btn)  # type: ignore
            v.addLayout(hb)  # type: ignore
            self._list = QListWidget()  # type: ignore
            v.addWidget(self._list)  # type: ignore
            self._lbl_count = QLabel("0 items")  # type: ignore
            v.addWidget(self._lbl_count)  # type: ignore
        except Exception:  # pragma: no cover
            pass
        self._root = root
        return root

    def _make_toggle_handler(self, level: str):  # 返回闭包
        def _handler():  # toggle -> 重算 active_levels
            active = {lv for lv, btn in self._btns.items() if getattr(btn, 'isChecked', lambda: True)()}
            # 若全部选中, 视为不过滤 -> None
            self._active_levels = None if len(active) == len(_LEVELS) else active
            logic = getattr(self, '_logic', None)
            if logic is not None and hasattr(logic, 'set_filter_levels'):
                logic.set_filter_levels(self._active_levels)
            self.refresh()
        return _handler

    def _apply_view(self, view: Dict[str, Any]):  # noqa: D401
        notes = view.get('notifications', []) if isinstance(view, dict) else []
        # 防御截断
        if len(notes) > 500:
            notes = notes[-500:]
        self._items = notes
        # 更新 UI 控件
        if self._list is not None:
            try:
                self._list.clear()  # type: ignore
                for n in notes:
                    txt = f"[{n['level']}] {n['code']}: {n['message']}"
                    self._list.addItem(txt)  # type: ignore
            except Exception:  # pragma: no cover
                pass
        if self._lbl_count is not None:
            try:
                self._lbl_count.setText(f"{len(notes)} items")  # type: ignore
            except Exception:  # pragma: no cover
                pass

__all__ = ["NotificationsPanelAdapter"]

