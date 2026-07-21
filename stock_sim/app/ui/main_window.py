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
    from PySide6.QtCore import Qt  # type: ignore
    from PySide6.QtGui import QAction, QFont  # type: ignore
    from PySide6.QtWidgets import (
        QMainWindow, QWidget, QLabel, QMenuBar, QVBoxLayout, QDockWidget,
        QHBoxLayout, QListWidget, QListWidgetItem, QStackedWidget, QPushButton
    )  # type: ignore
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
    class QFont:  # type: ignore
        def __init__(self, *_, **__):
            pass
    class QVBoxLayout:  # type: ignore
        def __init__(self, *_, **__):
            self._items = []
        def addWidget(self, widget):
            self._items.append(widget)
        def count(self):
            return len(self._items)
        def setContentsMargins(self, *_, **__):
            pass
    class Qt:  # type: ignore
        LeftDockWidgetArea = 0

from app.panels import list_panels, get_panel  # 惰性加载
from .docking import DockManager
from app.state.layout_persistence import LayoutPersistence  # 新增
from observability.metrics import metrics
# 新增：UI 桥
try:
    from app.ui.ui_refresh import register_main_window as _register_mw  # type: ignore
except Exception:  # pragma: no cover
    _register_mw = None  # type: ignore

DEFAULT_PRELOAD_PANELS = ["account", "diagnostics", "market", "agents", "arena", "leaderboard", "clock", "orders"]

__all__ = ["MainWindow", "DEFAULT_PRELOAD_PANELS"]

class MainWindow(QMainWindow):  # type: ignore[misc]
    def __init__(self):  # noqa: D401
        super().__init__()  # type: ignore
        self._dock = DockManager(self)
        self._layout_store = LayoutPersistence(path="layout_main.json")  # 持久化实例
        self._legacy_central: Any = None
        self._legacy_layout: Any = None
        # 现代主框架：左导航 + 中央主工作区；同时兼容旧测试接口
        self._layout: Any = None
        self._panel_widgets: Dict[str, Any] = {}
        self._nav_list: Any = None
        self._workspace_stack: Any = None
        self._workspace_container: Any = None
        self._workspace_pages: Dict[str, Any] = {}
        self._workspace_index_to_name: Dict[int, str] = {}
        self._page_history: List[str] = []
        self._last_non_symbol_page: str = 'market'
        # 简易标题
        if hasattr(self, 'setWindowTitle'):
            try:
                self.setWindowTitle("StockSim Frontend")  # type: ignore
            except Exception:  # pragma: no cover
                pass
        try:
            if hasattr(self, 'setMinimumSize'):
                self.setMinimumSize(900, 600)  # type: ignore[attr-defined]
            if hasattr(self, 'resize'):
                self.resize(1280, 820)  # type: ignore[attr-defined]
        except Exception:
            pass
        self._init_menu()
        self._init_window_style()
        self._restore_layout_safe()  # 启动时恢复
        # 向 UI 桥注册自身，以允许外部打开动态面板
        try:
            if callable(_register_mw):
                _register_mw(self)  # type: ignore
        except Exception:  # pragma: no cover
            pass

    def ensure_legacy_central_layout(self):
        if self._legacy_central is not None and self._legacy_layout is not None:
            self._layout = self._legacy_layout
            return self._legacy_layout
        if not hasattr(self, 'setCentralWidget'):
            return None
        try:
            central = QWidget(self)  # type: ignore
            root = QHBoxLayout(central)  # type: ignore
            if hasattr(root, 'setContentsMargins'):
                root.setContentsMargins(0, 0, 0, 0)
            if hasattr(root, 'setSpacing'):
                root.setSpacing(0)

            nav = QListWidget()  # type: ignore
            if hasattr(nav, 'setObjectName'):
                nav.setObjectName('mainNavList')  # type: ignore[attr-defined]
            if hasattr(nav, 'setMinimumWidth'):
                nav.setMinimumWidth(164)  # type: ignore[attr-defined]
            if hasattr(nav, 'setMaximumWidth'):
                nav.setMaximumWidth(220)  # type: ignore[attr-defined]
            try:
                if hasattr(nav, 'setSpacing'):
                    nav.setSpacing(4)  # type: ignore[attr-defined]
            except Exception:
                pass

            workspace_wrap = QWidget()  # type: ignore
            if hasattr(workspace_wrap, 'setObjectName'):
                workspace_wrap.setObjectName('workspaceWrap')  # type: ignore[attr-defined]
            workspace_layout = QVBoxLayout(workspace_wrap)  # type: ignore
            if hasattr(workspace_layout, 'setContentsMargins'):
                workspace_layout.setContentsMargins(20, 18, 20, 18)
            if hasattr(workspace_layout, 'setSpacing'):
                workspace_layout.setSpacing(12)
            stack = QStackedWidget()  # type: ignore
            workspace_layout.addWidget(stack)  # type: ignore

            root.addWidget(nav)  # type: ignore
            root.addWidget(workspace_wrap, 1)  # type: ignore
            self.setCentralWidget(central)  # type: ignore[attr-defined]

            self._legacy_central = central
            self._legacy_layout = workspace_layout
            self._layout = workspace_layout
            self._nav_list = nav
            self._workspace_stack = stack
            self._workspace_container = workspace_wrap

            try:
                if hasattr(nav, 'currentRowChanged'):
                    def _switch_workspace(index):
                        try:
                            if self._workspace_stack is not None and hasattr(self._workspace_stack, 'setCurrentIndex'):
                                if index >= 0:
                                    self._workspace_stack.setCurrentIndex(index)  # type: ignore[attr-defined]
                                    name = self._workspace_index_to_name.get(index)
                                    if name and not str(name).startswith('symbol:'):
                                        if not self._page_history or self._page_history[-1] != name:
                                            self._page_history.append(name)
                        except Exception:
                            pass
                    nav.currentRowChanged.connect(_switch_workspace)  # type: ignore[attr-defined]
            except Exception:
                pass
        except Exception:
            self._legacy_central = None
            self._legacy_layout = None
            self._layout = None
            self._nav_list = None
            self._workspace_stack = None
            self._workspace_container = None
        return self._legacy_layout

    def _ensure_central_layout(self):
        """Compatibility shim for older tests/helpers.

        Real panel hosting is dock-based now, but a stable central layout object is
        still exposed so historical tests can assert idempotence and inspect mount
        bookkeeping without forcing a second structural implementation.
        """
        return self.ensure_legacy_central_layout()

    def _make_workspace_page(self, name: str, widget: Any, title: str):
        try:
            page = QWidget()  # type: ignore
            outer = QVBoxLayout(page)  # type: ignore
            if hasattr(outer, 'setContentsMargins'):
                outer.setContentsMargins(0, 0, 0, 0)
            if hasattr(outer, 'setSpacing'):
                outer.setSpacing(8)
            if str(name).startswith('symbol:'):
                header = QWidget()  # type: ignore
                row = QHBoxLayout(header)  # type: ignore
                if hasattr(row, 'setContentsMargins'):
                    row.setContentsMargins(0, 0, 0, 0)
                if hasattr(row, 'setSpacing'):
                    row.setSpacing(8)
                back = QPushButton('←')  # type: ignore
                if hasattr(back, 'setFixedWidth'):
                    back.setFixedWidth(40)  # type: ignore[attr-defined]
                if hasattr(back, 'setToolTip'):
                    back.setToolTip('Back')  # type: ignore[attr-defined]
                def _go_back():
                    try:
                        target = getattr(self, '_last_non_symbol_page', 'market') or 'market'
                        for candidate in reversed(self._page_history):
                            if not str(candidate).startswith('symbol:'):
                                target = candidate
                                break
                        self.show_workspace_page(target)
                    except Exception:
                        pass
                if hasattr(back, 'clicked'):
                    back.clicked.connect(_go_back)  # type: ignore[attr-defined]
                label = QLabel(title)  # type: ignore
                row.addWidget(back)  # type: ignore
                row.addWidget(label, 1)  # type: ignore
                outer.addWidget(header)  # type: ignore
            outer.addWidget(widget, 1)  # type: ignore
            return page
        except Exception:
            return widget

    def show_workspace_page(self, name: str):
        try:
            if name not in self._workspace_pages:
                return
            page = self._workspace_pages[name]
            if self._workspace_stack is not None and hasattr(self._workspace_stack, 'indexOf'):
                idx = self._workspace_stack.indexOf(page)  # type: ignore[attr-defined]
                if idx >= 0 and hasattr(self._workspace_stack, 'setCurrentIndex'):
                    self._workspace_stack.setCurrentIndex(idx)  # type: ignore[attr-defined]
                if self._nav_list is not None and hasattr(self._nav_list, 'setCurrentRow') and not str(name).startswith('symbol:'):
                    self._nav_list.setCurrentRow(idx)  # type: ignore[attr-defined]
            if not str(name).startswith('symbol:'):
                self._last_non_symbol_page = name
            if not self._page_history or self._page_history[-1] != name:
                self._page_history.append(name)
            try:
                target = self._panel_widgets.get(name)
                refresh = getattr(target, 'refresh', None)
                if callable(refresh):
                    refresh()
            except Exception:
                pass
        except Exception:
            pass

    def _init_window_style(self):
        try:
            if hasattr(self, 'setFont'):
                self.setFont(QFont("Segoe UI", 10))  # type: ignore[attr-defined]
            if hasattr(self, 'setDockOptions'):
                opts = 0
                for name in ('AllowNestedDocks', 'AllowTabbedDocks', 'AnimatedDocks'):
                    opt = getattr(QMainWindow, name, None)
                    if opt is not None:
                        opts = opts | opt
                if opts:
                    self.setDockOptions(opts)  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            if hasattr(self, 'setStyleSheet'):
                self.setStyleSheet(
                    'QMainWindow { background: #0f141b; } '
                    'QWidget { color: #d8dee8; font-family: "Segoe UI", "Microsoft YaHei UI", Arial; font-size: 13px; background: #121821; } '
                    'QWidget#workspaceWrap { background: #121821; } '
                    'QStackedWidget { background: #121821; border: none; } '
                    'QDockWidget::title { background: #171f2a; padding: 6px 10px; font-weight: 600; border: none; } '
                    'QDockWidget { color: #d8dee8; border: 1px solid #26313f; } '
                    'QMenuBar { background: #0f141b; color: #c6d0dd; border-bottom: 1px solid #26313f; } '
                    'QMenuBar::item { padding: 6px 10px; border-radius: 6px; } '
                    'QMenuBar::item:selected { background: #202a36; color: #ffffff; } '
                    'QListWidget#mainNavList { background: #0b1017; border: none; padding: 18px 10px; outline: none; } '
                    'QListWidget#mainNavList::item { padding: 11px 14px; margin: 3px 0; border-radius: 8px; color: #9da8b7; } '
                    'QListWidget#mainNavList::item:selected { background: #1e2937; color: #ffffff; border-left: 3px solid #38bdf8; } '
                    'QListWidget#mainNavList::item:hover { background: #182231; color: #e7edf5; } '
                    'QPushButton { background: #1a2430; border: 1px solid #2b3848; padding: 7px 12px; border-radius: 7px; color: #dfe7f1; font-weight: 500; } '
                    'QPushButton:hover { background: #223044; border-color: #3b4a60; } '
                    'QPushButton:pressed { background: #111923; } '
                    'QPushButton#primaryAction { background: #0e7490; border-color: #0891b2; color: #ffffff; } '
                    'QPushButton#secondaryAction { background: #151e29; color: #b9c3d0; } '
                    'QLineEdit, QComboBox { background: #0d131b; border: 1px solid #273444; border-radius: 6px; padding: 6px 8px; color: #e5edf7; selection-background-color: #0e7490; } '
                    'QLineEdit:focus, QComboBox:focus { border-color: #38bdf8; } '
                    'QTableWidget { background: #111821; alternate-background-color: #151e29; color: #d8dee8; gridline-color: #26313f; border: 1px solid #26313f; border-radius: 6px; selection-background-color: #1f3b52; selection-color: #ffffff; } '
                    'QHeaderView::section { background: #17202b; color: #9fb0c3; border: none; border-right: 1px solid #26313f; border-bottom: 1px solid #26313f; padding: 6px 8px; font-weight: 600; } '
                    'QTextEdit { background: #0d131b; border: 1px solid #26313f; border-radius: 6px; color: #cfd8e3; } '
                    'QLabel { background: transparent; } '
                    'QLabel#detailSymbolLabel { color: #f8fafc; font-size: 22px; font-weight: 700; } '
                    'QLabel#detailMetaLabel { color: #9fb0c3; font-size: 12px; } '
                    'QLabel#detailStatusLabel { color: #67e8f9; font-size: 12px; font-weight: 600; } '
                    'QLabel#detailDebugLabel { color: #94a3b8; font-size: 11px; } '
                    'QFrame#detailHeader { background: #141d28; border: 1px solid #26313f; border-radius: 8px; } '
                    'QFrame#marketSidebar { background: #0d131b; border: 1px solid #26313f; border-radius: 8px; } '
                    'QListWidget#marketSymbolList { background: #0d131b; border: none; outline: none; padding: 6px; } '
                    'QListWidget#marketSymbolList::item { padding: 8px 10px; margin: 2px 0; border-radius: 6px; color: #b8c2cf; } '
                    'QListWidget#marketSymbolList::item:selected { background: #1f3b52; color: #ffffff; } '
                    'QListWidget#marketSymbolList::item:hover { background: #172334; } '
                )  # type: ignore[attr-defined]
        except Exception:
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
        """Serialize the current workspace-oriented app state.

        Current policy:
        - persist only primary workspace pages
        - do not persist dynamic symbol detail pages yet
        - remember the currently active non-symbol page
        """
        workspace_names = [
            name for name in self._workspace_pages.keys()
            if not str(name).startswith('symbol:')
        ]
        ordered_names = [
            name for name in self._workspace_index_to_name.values()
            if name in workspace_names
        ]
        if not ordered_names:
            ordered_names = [
                name for name in ['market', 'account', 'diagnostics', 'agents', 'arena', 'leaderboard', 'clock', 'orders']
                if name in self._workspace_pages
            ]
        active_page = getattr(self, '_last_non_symbol_page', 'market') or 'market'
        if active_page not in ordered_names and ordered_names:
            active_page = ordered_names[0]
        return {
            "panels": {name: {"open": True, "order": idx} for idx, name in enumerate(ordered_names)},
            "workspace": {
                "active_page": active_page,
            },
        }

    def restore_layout(self, layout: Dict[str, Any]):  # 外部可调用
        try:
            panels_def = layout.get("panels", {}) if isinstance(layout, dict) else {}
            workspace_def = layout.get("workspace", {}) if isinstance(layout, dict) else {}
        except Exception:
            panels_def = {}
            workspace_def = {}
        # 按 order 排序打开；当前阶段仅恢复主 workspace pages，不自动恢复 symbol:* detail pages
        ordered = sorted(
            [
                (name, cfg) for name, cfg in panels_def.items()
                if isinstance(cfg, dict) and cfg.get("open") and not str(name).startswith('symbol:')
            ],
            key=lambda x: x[1].get("order", 0)
        )
        restored_names: List[str] = []
        for name, _ in ordered:
            try:
                opened = self.open_panel(name)
                if opened is not None:
                    restored_names.append(name)
            except Exception:  # pragma: no cover
                pass
        active_page = workspace_def.get('active_page') if isinstance(workspace_def, dict) else None
        if active_page in restored_names:
            try:
                self.show_workspace_page(active_page)
            except Exception:
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
        # 先看 workspace page，再看 dock；否则主页面已在 workspace 中时，
        # 重复 open_panel(name) 会因为 _dock 中查不到而再挂一份同名页面。
        if name in self._workspace_pages:
            try:
                self.show_workspace_page(name)
            except Exception:
                pass
            return self._panel_widgets.get(name)
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
                widget = QLabel(f"Placeholder panel: {name}")  # type: ignore
        elif isinstance(obj, QWidget):  # type: ignore
            widget = obj
        else:
            widget = QLabel(f"Placeholder panel: {name}")  # type: ignore

        self._ensure_central_layout()
        try:
            self._panel_widgets[name] = widget
            primary_panels = {'market', 'account', 'diagnostics', 'agents', 'arena', 'clock', 'leaderboard', 'orders'} | {n for n in self.list_open() if str(n).startswith('symbol:')}
            if name in primary_panels or str(name).startswith('symbol:'):
                try:
                    if self._workspace_stack is not None and hasattr(self._workspace_stack, 'addWidget'):
                        title = next((p.get('title') for p in list_panels() if p.get('name') == name), None) or name
                        page = self._make_workspace_page(name, widget, title)
                        self._workspace_stack.addWidget(page)  # type: ignore[attr-defined]
                        idx = self._workspace_stack.count() - 1 if hasattr(self._workspace_stack, 'count') else 0
                        self._workspace_pages[name] = page
                        self._workspace_index_to_name[idx] = name
                        if self._nav_list is not None and hasattr(self._nav_list, 'addItem') and not str(name).startswith('symbol:'):
                            nav_titles = {
                                'diagnostics': 'Diagnostics',
                                'market': 'Market',
                                'account': 'Account',
                                'agents': 'Agents',
                                'arena': 'Arena',
                                'clock': 'Clock',
                                'leaderboard': 'Leaderboard',
                                'orders': 'Orders',
                            }
                            self._nav_list.addItem(nav_titles.get(name, title))  # type: ignore[attr-defined]
                        self.show_workspace_page(name)
                        try:
                            if hasattr(page, 'update'):
                                page.update()  # type: ignore[attr-defined]
                            if hasattr(page, 'repaint'):
                                page.repaint()  # type: ignore[attr-defined]
                        except Exception:
                            pass
                except Exception:
                    if self._layout is not None and hasattr(self._layout, 'addWidget'):
                        self._layout.addWidget(widget)
            else:
                self._dock.add_panel(name, widget)
            metrics.inc("panel_mount_success")
            self._save_layout()
            return widget
        except Exception:
            metrics.inc("panel_mount_failure")
            raise

    def close_panel(self, name: str) -> bool:
        ok = self._dock.remove_panel(name)
        if ok:
            self._panel_widgets.pop(name, None)
            self._save_layout()
        return ok

    def list_registered(self) -> List[str]:
        return [p["name"] for p in list_panels()]

    def list_open(self) -> List[str]:
        """Return the current app-open state with workspace-first semantics.

        Current policy:
        - primary workspace pages come first in workspace order
        - dynamic symbol workspace pages come next in workspace order
        - supporting dock-only panels are appended afterward
        """
        workspace_names = [name for name in self._workspace_index_to_name.values() if name in self._workspace_pages]
        dock_names = [name for name in self._dock.list_open() if name not in workspace_names]
        return workspace_names + dock_names

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
