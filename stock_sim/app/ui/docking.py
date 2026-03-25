"""Dock / PanelHost Skeleton (R20,R25)

提供 DockManager: 仅封装最小面板(Widget) 注册 / 移除 / 列表功能。
当前阶段不做:
- 布局持久化 (任务3)
- 高级 Tab / 拖拽策略重写
- 适配器绑定 (任务5+)

PySide6 可能在 CI/headless 缺失, 采用降级占位实现: 若不可用则内部仅存储 dict, 不创建真实 QDockWidget。
"""
from __future__ import annotations
from typing import Dict, Optional, List, Any

DEFAULT_DOCK_AREAS = {
    'account': 'left',
    'market': 'center',
    'agents': 'right',
    'leaderboard': 'bottom',
    'clock': 'right',
    'orders': 'bottom',
}

try:  # noqa: SIM105
    from PySide6.QtCore import Qt  # type: ignore
    from PySide6.QtWidgets import QMainWindow, QWidget, QDockWidget  # type: ignore
except Exception:  # pragma: no cover - headless fallback
    QMainWindow = object  # type: ignore
    QWidget = object  # type: ignore
    class QDockWidget:  # type: ignore
        def __init__(self, *_, **__):
            self._widget = None
        def setWidget(self, w):  # noqa: N802
            self._widget = w
    class Qt:  # type: ignore
        LeftDockWidgetArea = 0

class DockManager:
    """最小 Dock 管理.

    注意: 当前不处理可见性/浮动/关闭事件; 仅存储引用供后续扩展。
    """
    def __init__(self, main_window: QMainWindow):  # type: ignore[override]
        self._mw = main_window
        self._panels: Dict[str, Any] = {}      # name -> widget
        self._docks: Dict[str, Any] = {}       # name -> QDockWidget / placeholder

    def _resolve_area(self, name: str):
        pref = DEFAULT_DOCK_AREAS.get(name, 'left')
        if pref == 'right':
            return getattr(Qt, 'RightDockWidgetArea', getattr(Qt, 'LeftDockWidgetArea', 0))
        if pref == 'bottom':
            return getattr(Qt, 'BottomDockWidgetArea', getattr(Qt, 'LeftDockWidgetArea', 0))
        if pref == 'top':
            return getattr(Qt, 'TopDockWidgetArea', getattr(Qt, 'LeftDockWidgetArea', 0))
        return getattr(Qt, 'LeftDockWidgetArea', 0)

    def add_panel(self, name: str, widget: Any) -> bool:
        if name in self._panels:
            return False
        self._panels[name] = widget
        if isinstance(self._mw, QMainWindow) and hasattr(self._mw, 'addDockWidget'):
            try:
                dock = QDockWidget(name)  # type: ignore
                if hasattr(dock, 'setWidget'):
                    dock.setWidget(widget)
                if hasattr(dock, 'setObjectName'):
                    try:
                        dock.setObjectName(f'dock::{name}')  # type: ignore[attr-defined]
                    except Exception:
                        pass
                area = self._resolve_area(name)
                self._mw.addDockWidget(area, dock)  # type: ignore
                self._docks[name] = dock
            except Exception:  # pragma: no cover - 防御
                pass
        return True

    def remove_panel(self, name: str) -> bool:
        if name not in self._panels:
            return False
        dock = self._docks.pop(name, None)
        if dock and isinstance(self._mw, QMainWindow) and hasattr(self._mw, 'removeDockWidget'):
            try:
                self._mw.removeDockWidget(dock)  # type: ignore
            except Exception:  # pragma: no cover
                pass
        self._panels.pop(name, None)
        return True

    def get_panel(self, name: str) -> Optional[Any]:
        return self._panels.get(name)

    def list_open(self) -> List[str]:
        return list(self._panels.keys())

    # 预留: serialize / restore (任务3)

__all__ = ["DockManager"]

