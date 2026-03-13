"""MainWindow Skeleton (R20,R25)

最小 UI Shell：
- 集成 DockManager
- 提供 open_panel / close_panel / list_panels / list_open
- 暂不包含：布局持久化(任务3)、主题/语言同步(任务4)、通知中心(任务29)

在 headless 或缺失 PySide6 时退化为无窗口占位实现，方法仍可被调用以便测试。
"""
from __future__ import annotations
from typing import Any, Optional, List, Dict

try:  # PySide6 可选
    from PySide6.QtWidgets import QMainWindow, QWidget, QLabel, QMenuBar, QAction  # type: ignore
except Exception:  # pragma: no cover - headless fallback
    QMainWindow = object  # type: ignore
    class QWidget:  # type: ignore
        def __init__(self, *_, **__):
            pass
    class QLabel(QWidget):  # type: ignore
        def __init__(self, text: str):  # noqa: D401
            super().__init__()
            self.text = text
    class QMenuBar:  # type: ignore
        def __init__(self, *_, **__):
            pass
    class QAction:  # type: ignore
        def __init__(self, *_, **__):
            pass

from app.panels import list_panels, get_panel  # 惰性加载
from .docking import DockManager
from app.state.layout_persistence import LayoutPersistence  # 新增
# 新增：UI 桥
try:
    from app.ui.ui_refresh import register_main_window as _register_mw  # type: ignore
except Exception:  # pragma: no cover
    _register_mw = None  # type: ignore

__all__ = ["MainWindow"]

class MainWindow(QMainWindow):  # type: ignore[misc]
    def __init__(self):  # noqa: D401
        super().__init__()  # type: ignore
        self._dock = DockManager(self)
        self._layout_store = LayoutPersistence(path="layout_main.json")  # 持久化实例
        # 简易标题
        if hasattr(self, 'setWindowTitle'):
            try:
                self.setWindowTitle("StockSim Frontend")  # type: ignore
            except Exception:  # pragma: no cover
                pass
        self._init_menu()
        self._restore_layout_safe()  # 启动时恢复
        # 向 UI 桥注册自身，以允许外部打开动态面板
        try:
            if callable(_register_mw):
                _register_mw(self)  # type: ignore
        except Exception:  # pragma: no cover
            pass

    # -------- Menu --------
    def _init_menu(self):  # 轻量 Panels 菜单
        if not hasattr(self, 'menuBar'):
            return
        try:
            mb = self.menuBar()  # type: ignore[attr-defined]
            if mb is None:
                return
            panels_menu = None
            # 避免重复创建
            try:
                for a in getattr(mb, 'actions', lambda: [])():  # pragma: no cover (headless fallback)
                    if hasattr(a, 'text') and getattr(a, 'text')() == 'Panels':  # type: ignore
                        panels_menu = a.menu()  # type: ignore
                        break
            except Exception:  # pragma: no cover
                pass
            if panels_menu is None:
                panels_menu = mb.addMenu('Panels')  # type: ignore
            # 清空再重建（简单策略）
            try:
                for act in panels_menu.actions():  # type: ignore
                    panels_menu.removeAction(act)  # type: ignore
            except Exception:  # pragma: no cover
                pass
            for p in list_panels():
                name = p.get('name')
                if not name:
                    continue
                title = p.get('title') or name
                try:
                    act = QAction(title, self)  # type: ignore
                    def _handler(checked=False, n=name):  # noqa: ARG001
                        self.open_panel(n)
                    act.triggered.connect(_handler)  # type: ignore[attr-defined]
                    panels_menu.addAction(act)  # type: ignore
                except Exception:  # pragma: no cover
                    pass
        except Exception:  # pragma: no cover
            pass

    # -------- Layout Persistence --------
    def serialize_layout(self) -> Dict[str, Any]:
        """序列化当前打开面板列表 (简化：仅存 open=True 顺序)."""
        panels_open = self.list_open()
        return {
            "panels": {name: {"open": True, "order": idx} for idx, name in enumerate(panels_open)}
        }

    def restore_layout(self, layout: Dict[str, Any]):  # 外部可调用
        try:
            panels_def = layout.get("panels", {}) if isinstance(layout, dict) else {}
        except Exception:
            panels_def = {}
        # 按 order 排序打开
        ordered = sorted(
            [(name, cfg) for name, cfg in panels_def.items() if isinstance(cfg, dict) and cfg.get("open")],
            key=lambda x: x[1].get("order", 0)
        )
        for name, _ in ordered:
            try:
                self.open_panel(name)
            except Exception:  # pragma: no cover
                pass

    def _restore_layout_safe(self):
        try:
            layout = self._layout_store.get()
        except Exception:
            layout = {"panels": {}}
        # 若布局损坏/不是预期结构则回退默认
        if not isinstance(layout, dict) or "panels" not in layout:
            layout = {"panels": {}}
        self.restore_layout(layout)

    def _save_layout(self):
        try:
            self._layout_store.save(self.serialize_layout())
        except Exception:  # pragma: no cover
            pass

    # -------- Panel Ops --------
    def open_panel(self, name: str) -> Optional[Any]:
        existing = self._dock.get_panel(name)
        if existing is not None:
            return existing
        if not any(p["name"] == name for p in list_panels()):
            return None
        obj = get_panel(name)
        widget: Any
        # 支持 PanelAdapter: 若对象提供 widget() 则使用其返回的真实 QWidget
        real_widget = getattr(obj, 'widget', None)
        if callable(real_widget):
            try:
                widget = real_widget()
            except Exception:
                # 回退：若失败则使用占位标签
                widget = QLabel(f"Panel: {name}")  # type: ignore
        elif isinstance(obj, QWidget):  # type: ignore
            widget = obj
        else:
            widget = QLabel(f"Panel: {name}")  # type: ignore
        self._dock.add_panel(name, widget)
        # 保存布局（立即，后续可加节流）
        self._save_layout()
        return widget

    def close_panel(self, name: str) -> bool:
        ok = self._dock.remove_panel(name)
        if ok:
            self._save_layout()
        return ok

    def list_registered(self) -> List[str]:
        return [p["name"] for p in list_panels()]

    def list_open(self) -> List[str]:
        return self._dock.list_open()

    # 预留: 更复杂的 Qt saveState/saveGeometry 保存 (后续扩展)

    # -------- Qt Events --------
    def closeEvent(self, event):  # type: ignore[override]
        # 关闭时保存布局 (即便 headless fallback 也安全调用)
        self._save_layout()
        try:
            super_close = getattr(super(), 'closeEvent', None)
            if callable(super_close):  # pragma: no cover - 仅 GUI 下执行
                super_close(event)
        except Exception:  # pragma: no cover
            pass
