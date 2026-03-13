"""Frontend Main Entry (Spec Task 23)

提供 run_frontend() 入口：
- 注册内置面板 (占位) —— 任务 24~30 将提供真实实现
- 构建 MainWindow (占位类)，管理面板打开
- 支持 headless 模式 (测试) 不创建 QApplication / 不进入事件循环

设计:
- MainWindow 仅维护 opened_panels: dict[str, Any]
- open_panel(name) -> 实例 (惰性, 通过 registry.get_panel)
- list_available() -> registry.list_panels()

未来扩展 TODO:
- TODO: 增加菜单/快捷键绑定
- TODO: 增加面板布局持久化 (对接 layout_persistence)
- TODO: 增加状态栏指标/metrics 展示

Task34 集成 (Metrics & Structured Logging):
- 启动时尝试 flush (reason=startup, 若有指标)
- GUI 模式下使用 QTimer 每 5s flush (reason=periodic)
- 注册 atexit 钩子 flush (reason=shutdown, forced=True)
"""
from __future__ import annotations
from typing import Dict, Any, List
import atexit
import os

try:  # PySide6 可选运行 (测试 headless 时无需真正 GUI)
    from PySide6.QtWidgets import QApplication, QMainWindow  # type: ignore
    from PySide6.QtCore import QTimer  # type: ignore
    from PySide6.QtWidgets import QWidget as _QWidget, QVBoxLayout as _QVBoxLayout  # type: ignore
    from PySide6.QtWidgets import QLabel as _QLabel  # type: ignore
    # 新增：可选标签容器
    try:
        from PySide6.QtWidgets import QTabWidget as _QTabWidget  # type: ignore
    except Exception:  # pragma: no cover
        _QTabWidget = None  # type: ignore
except Exception:  # pragma: no cover
    QApplication = None  # type: ignore
    class QMainWindow:  # type: ignore
        pass
    QTimer = None  # type: ignore
    _QWidget = None  # type: ignore
    _QVBoxLayout = None  # type: ignore
    _QLabel = None  # type: ignore
    _QTabWidget = None  # type: ignore

# 用 app.* 导入，避免测试环境找不到 stock_sim.*
from app.panels import register_builtin_panels, get_panel, list_panels
# 新增：在预加载/打开之前用适配器替换占位
try:  # 延迟引入，避免在无此符号时抛出导入期异常
    from app.panels import register_ui_adapters  # type: ignore
except Exception:  # pragma: no cover
    register_ui_adapters = None  # type: ignore
from app.utils.metrics_adapter import flush_metrics  # Task34
from observability.metrics import metrics  # 挂载过程计数

# 轻量 UI 刷新桥（可选）
try:
    from app.ui.ui_refresh import register_main_window as _ui_register_main_window  # type: ignore
except Exception:  # pragma: no cover
    _ui_register_main_window = None  # type: ignore

__all__ = ["run_frontend", "MainWindow"]

# 预加载面板列表
_DEFAULT_PRELOAD = ["account", "market", "agents", "settings", "leaderboard", "clock"]

class MainWindow(QMainWindow):  # 占位, 未来扩展 UI
    def __init__(self):  # type: ignore[override]
        super().__init__()  # type: ignore[misc]
        self.opened_panels: Dict[str, Any] = {}
        # 惰性创建的 central 容器与主布局
        self._central = None
        self._layout = None
        # 新增：标签容器
        self._tabs = None
        # 已挂载面板的可见部件，防重复
        self._panel_widgets: Dict[str, Any] = {}

    def open_panel(self, name: str):
        inst = get_panel(name)
        self.opened_panels[name] = inst
        # 保障布局与标签容器
        self._ensure_central_layout()
        self._ensure_tab_container()
        if self._layout is not None and self._tabs is not None:
            self._mount_panel(name, inst)
        # 兜底：若未记录挂载，则创建占位部件并作为 Tab 添加
        if name not in self._panel_widgets:
            local_QLabel = _QLabel
            if local_QLabel is None:
                try:
                    from PySide6.QtWidgets import QLabel as __QLabel  # type: ignore
                    local_QLabel = __QLabel
                except Exception:
                    local_QLabel = None
            if local_QLabel is not None:
                placeholder = local_QLabel(f"{name} panel (placeholder)")
            else:
                class _DummyLabel:
                    def __init__(self, text: str):
                        self._text = text
                    def text(self):
                        return self._text
                placeholder = _DummyLabel(f"{name} panel (placeholder)")
            try:
                title = self._panel_title(name)
                if hasattr(self._tabs, 'addTab'):
                    self._tabs.addTab(placeholder, title)  # type: ignore[attr-defined]
                elif hasattr(self._layout, 'addWidget'):
                    self._layout.addWidget(placeholder)  # 进一步回退
            except Exception:
                pass
            self._panel_widgets[name] = placeholder
        return inst

    def list_available(self) -> List[dict]:
        return list_panels()

    # ---- Internal helpers ----
    class _DummyLayout:
        def __init__(self):
            self._widgets: list[Any] = []
        def addWidget(self, w):  # noqa: D401
            self._widgets.append(w)
        def count(self):  # noqa: D401
            return len(self._widgets)

    class _DummyTabs:
        def __init__(self):
            self._tabs: list[tuple[Any, str]] = []
        def addTab(self, w, title: str):  # noqa: D401
            self._tabs.append((w, title))
        def count(self):  # noqa: D401
            return len(self._tabs)

    def _panel_title(self, name: str) -> str:
        try:
            for p in list_panels():
                if p.get('name') == name:
                    return p.get('title') or name
        except Exception:
            pass
        return name

    def _ensure_tab_container(self):
        if self._tabs is not None:
            return
        # 优先使用 QTabWidget
        local_QTabWidget = _QTabWidget
        if local_QTabWidget is None:
            try:
                from PySide6.QtWidgets import QTabWidget as __QTabWidget  # type: ignore
                local_QTabWidget = __QTabWidget
            except Exception:
                local_QTabWidget = None
        if local_QTabWidget is not None and self._layout is not None:
            try:
                tabs = local_QTabWidget()
                try:
                    self._layout.addWidget(tabs)  # type: ignore[attr-defined]
                except Exception:
                    pass
                self._tabs = tabs
                return
            except Exception:
                self._tabs = None
        # 回退：无 Qt 时使用 DummyTabs（保证测试与占位）
        self._tabs = MainWindow._DummyTabs()

    # ---- Internal: ensure central widget & layout (idempotent) ----
    def _ensure_central_layout(self):
        # 动态探测 Qt 组件，避免模块级导入被早期 headless 测试污染
        local_QWidget = _QWidget
        local_QVBoxLayout = _QVBoxLayout
        if local_QWidget is None or local_QVBoxLayout is None:
            try:
                from PySide6.QtWidgets import QWidget as __QWidget, QVBoxLayout as __QVBoxLayout  # type: ignore
                local_QWidget, local_QVBoxLayout = __QWidget, __QVBoxLayout
            except Exception:
                # 无法获取 Qt 组件，使用占位布局，确保测试可运行
                if self._layout is None:
                    self._central = object()
                    self._layout = MainWindow._DummyLayout()
                return
        if self._central is not None and self._layout is not None:
            return
        central = local_QWidget()
        layout = local_QVBoxLayout(central)
        try:
            self.setCentralWidget(central)  # type: ignore[attr-defined]
        except Exception:
            pass
        self._central = central
        self._layout = layout

    # ---- Internal: mount panel instance into tab (idempotent) ----
    def _mount_panel(self, name: str, inst: Any):
        if name in self._panel_widgets:
            return self._panel_widgets[name]
        if self._layout is None:
            return None
        self._ensure_tab_container()
        # 动态探测 QLabel
        local_QLabel = _QLabel
        if local_QLabel is None:
            try:
                from PySide6.QtWidgets import QLabel as __QLabel  # type: ignore
                local_QLabel = __QLabel
            except Exception:
                local_QLabel = None
        widget = None
        try:
            w_meth = getattr(inst, 'widget', None)
            if callable(w_meth):
                widget = w_meth()
            else:
                m_meth = getattr(inst, 'mount', None)
                if callable(m_meth):
                    maybe = m_meth(self._layout)
                    widget = maybe if maybe is not None else None
            if widget is None and local_QLabel is not None:
                widget = local_QLabel(f"{name} panel (placeholder)")
            if widget is not None:
                try:
                    title = self._panel_title(name)
                    if hasattr(self._tabs, 'addTab'):
                        self._tabs.addTab(widget, title)  # type: ignore[attr-defined]
                    else:
                        self._layout.addWidget(widget)  # type: ignore[attr-defined]
                except Exception:
                    pass
                self._panel_widgets[name] = widget
                metrics.inc('panel_mount_success')
            return widget
        except Exception:
            metrics.inc('panel_mount_failure')
            try:
                placeholder = None
                if local_QLabel is not None:
                    try:
                        placeholder = local_QLabel(f"{name} panel (placeholder)")
                    except Exception:
                        placeholder = None
                if placeholder is None:
                    class _DummyLabel:
                        def __init__(self, text: str):
                            self._text = text
                        def text(self):
                            return self._text
                    placeholder = _DummyLabel(f"{name} panel (placeholder)")
                try:
                    title = self._panel_title(name)
                    if hasattr(self._tabs, 'addTab'):
                        self._tabs.addTab(placeholder, title)  # type: ignore[attr-defined]
                    elif hasattr(self._layout, 'addWidget'):
                        self._layout.addWidget(placeholder)  # type: ignore[attr-defined]
                except Exception:
                    pass
                self._panel_widgets[name] = placeholder
                return placeholder
            except Exception:
                return None

# 轻量 headless 版本，避免 QMainWindow 依赖 QApplication
class HeadlessMainWindow:  # noqa: D401 - 简单容器
    def __init__(self):
        self.opened_panels: Dict[str, Any] = {}
    def open_panel(self, name: str):
        inst = get_panel(name)
        self.opened_panels[name] = inst
        return inst
    def list_available(self) -> List[dict]:
        return list_panels()

# --------------- Metrics Flush Hooks (Task34) ---------------
_periodic_timer = None  # 仅 GUI 模式

def _setup_periodic_metrics_flush(interval_ms: int = 5000):  # pragma: no cover (逻辑简单)
    global _periodic_timer
    if QApplication is None or QTimer is None:
        return
    _periodic_timer = QTimer()
    _periodic_timer.setInterval(interval_ms)
    _periodic_timer.timeout.connect(lambda: flush_metrics(reason="periodic"))  # type: ignore
    _periodic_timer.start()

# atexit 保证最终落盘
@atexit.register
def _flush_on_exit():  # pragma: no cover - 退出阶段
    try:
        flush_metrics(forced=True, reason="shutdown")
    except Exception:
        pass

# --------------- Entry ---------------

def run_frontend(*, headless: bool = False) -> MainWindow | HeadlessMainWindow:
    register_builtin_panels()
    # 在任何面板打开/预加载之前，尝试用 UI 适配器替换占位（幂等且防御性）
    adapters_called = False
    try:
        if callable(register_ui_adapters):  # type: ignore
            register_ui_adapters()  # type: ignore
            adapters_called = True
    except Exception:
        # 静默回退，占位仍��用
        pass
    flush_metrics(reason="startup")
    debug = os.environ.get("STOCKSIM_DEBUG_UI", "").lower() in ("1", "true", "yes", "on")
    if headless or QApplication is None:
        if debug:
            try:
                available = [p.get("name") for p in list_panels()]
                print(f"[DEBUG] headless adapters_called={adapters_called} available={available}")
            except Exception:
                pass
        return HeadlessMainWindow()
    import sys  # noqa: F401
    app = QApplication.instance() or QApplication([])
    mw = MainWindow()
    # 在 UI 刷新桥注册主窗口（若可用）；无 GUI/无桥均安全忽略
    try:
        if callable(_ui_register_main_window):
            _ui_register_main_window(mw)  # type: ignore
    except Exception:
        pass
    # 在预加载前确保 central/layout 已创建（仅 GUI 环境）
    mw._ensure_central_layout()
    for name in _DEFAULT_PRELOAD:
        try:
            mw.open_panel(name)
        except Exception:
            # 预加载失败不影响其��面板
            pass
    if debug:
        try:
            available = [p.get("name") for p in mw.list_available()]
            mounted = list(mw._panel_widgets.keys())
            opened = list(mw.opened_panels.keys())
            print(f"[DEBUG] gui-before-loop adapters_called={adapters_called} available={available} mounted={mounted} opened={opened}")
        except Exception:
            pass
    try:
        _setup_periodic_metrics_flush()
        mw.show()
        app.exec()
    except Exception:  # pragma: no cover
        pass
    if debug:
        try:
            available = [p.get("name") for p in mw.list_available()]
            mounted = list(mw._panel_widgets.keys())
            opened = list(mw.opened_panels.keys())
            print(f"[DEBUG] gui-after-loop adapters_called={adapters_called} available={available} mounted={mounted} opened={opened}")
        except Exception:
            pass
    return mw
