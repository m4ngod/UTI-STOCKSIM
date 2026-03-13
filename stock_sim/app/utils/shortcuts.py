"""ShortcutManager & Accessibility Helpers (Spec Task 33)

目标:
- 提供全局/实例级快捷键循环面板能力 (不依赖真实 GUI, 便于 headless 测试)
- 支持 next / prev 面板循环 (顺序遵循注册顺序)
- 提供刷新面板顺序 refresh_order()
- 可选: 维护当前激活面板索引
- 计数 metrics: shortcut_cycle, shortcut_cycle_prev, shortcut_cycle_next

可访问性: 与 SettingsState.high_contrast (新增字段) 协同, 此处仅提供 apply_high_contrast_vars 占位函数。

设计说明:
- 不直接绑定 PySide6 QShortcut, 留待后续 GUI 集成层调用
- 线程安全: 轻量使用 RLock 保护 (循环操作O(1))
"""
from __future__ import annotations
from threading import RLock
from typing import Callable, List, Optional
from observability.metrics import metrics

try:  # 延迟引用, 测试场景无需 GUI
    from app.panels import list_panels
except Exception:  # pragma: no cover
    def list_panels():  # type: ignore
        return []

__all__ = [
    "ShortcutManager",
    "get_global_shortcut_manager",
    "apply_high_contrast_vars",
]

PanelListProvider = Callable[[], List[dict]]

class ShortcutManager:
    def __init__(self, provider: PanelListProvider | None = None):
        self._provider = provider or list_panels
        self._lock = RLock()
        self.order: List[str] = []
        self.active_index: int = -1
        self.refresh_order()
        if self.order:
            self.active_index = 0

    # ------------- 基础 -------------
    def refresh_order(self):
        with self._lock:
            self.order = [p["name"] for p in self._provider()]
            # 若当前 active 不在新列表, 重置
            if self.active_index >= len(self.order):
                self.active_index = 0 if self.order else -1

    def set_active(self, name: str):
        with self._lock:
            if name in self.order:
                self.active_index = self.order.index(name)
            else:
                raise ValueError(f"panel '{name}' not in order")

    def get_active(self) -> Optional[str]:
        with self._lock:
            if 0 <= self.active_index < len(self.order):
                return self.order[self.active_index]
            return None

    # ------------- 循环 -------------
    def _cycle(self, delta: int) -> Optional[str]:
        with self._lock:
            if not self.order:
                return None
            self.active_index = (self.active_index + delta) % len(self.order)
            metrics.inc("shortcut_cycle")
            if delta > 0:
                metrics.inc("shortcut_cycle_next")
            else:
                metrics.inc("shortcut_cycle_prev")
            return self.order[self.active_index]

    def next_panel(self) -> Optional[str]:
        return self._cycle(1)

    def prev_panel(self) -> Optional[str]:
        return self._cycle(-1)

# ------------- 高对比主题占位 -------------

def apply_high_contrast_vars(theme_vars: dict, *, enabled: bool) -> dict:
    """返回调整后的主题变量 (浅实现):
    - enabled=True 时提升边框/文字对比度 (示例加粗/增加 alpha)
    - 不直接修改原字典 (返回浅拷贝)
    """
    new_vars = dict(theme_vars)
    if enabled:
        # 简单示例: 覆盖关键颜色键 (若存在)
        fg = new_vars.get("color_text", "#222")
        bg = new_vars.get("color_background", "#fff")
        # 伪处理: 强化对比 (这里不做真实色彩计算, 保持 deterministic)
        new_vars["color_text"] = fg.upper()
        new_vars["color_background"] = bg.lower()
        new_vars["border_focus"] = new_vars.get("border_focus", "#000000")
    return new_vars

# ------------- 全局单例 -------------
_global_manager: ShortcutManager | None = None

def get_global_shortcut_manager() -> ShortcutManager:
    global _global_manager
    if _global_manager is None:
        _global_manager = ShortcutManager()
    return _global_manager

