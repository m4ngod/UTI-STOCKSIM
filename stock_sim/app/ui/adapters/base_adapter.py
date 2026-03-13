"""PanelAdapter Base (R25)

目标: 提供逻辑面板对象与 QWidget 之间的最小桥接接口。

限制:
- 不包含业务逻辑或数据处理; 仅封装绑定与刷新占位。
- 不强制依赖 PySide6 在导入阶段可用; 若不可用, 使用惰性占位。

方法:
- bind(logic): 绑定逻辑面板实例; 返回 self (链式)。
- widget(): 返回底层 QWidget (或占位对象) 供 DockManager 添加。
- refresh(): 由外部（计时器/事件）调用以拉取最新 view 并调用 _apply_view(view)。
- apply_settings(settings): 由 SettingsSync 调用应用主题/语言/阈值等; 默认 no-op。

子类需实现:
- _create_widget(): 构造并返回 QWidget / 占位
- _apply_view(view_dict): 将视图模型绑定到控件; 保持幂等

注意:
- 不在构造函数做重 IO; _create_widget 延迟直到第一次访问 widget()。
"""
from __future__ import annotations
from typing import Any, Optional, Dict

try:  # 可选 PySide6
    from PySide6.QtWidgets import QWidget  # type: ignore
except Exception:  # pragma: no cover
    class QWidget:  # type: ignore
        pass

class PanelAdapter:
    __slots__ = ("_logic", "_widget", "_initialized")

    def __init__(self) -> None:
        self._logic: Any = None
        self._widget: Optional[QWidget] = None  # type: ignore
        self._initialized: bool = False

    # ---------- Public API ----------
    def bind(self, logic: Any) -> "PanelAdapter":
        self._logic = logic
        return self

    def widget(self) -> QWidget:  # type: ignore[override]
        if self._widget is None:
            self._widget = self._create_widget()
            self._initialized = True
        return self._widget  # type: ignore

    def refresh(self):
        if self._logic is None:
            return
        # 逻辑层必须提供 get_view; 若没有则忽略
        get_view = getattr(self._logic, "get_view", None)
        if callable(get_view):
            try:
                view = get_view()
                if isinstance(view, dict):
                    self._apply_view(view)
            except Exception:  # pragma: no cover
                # 静默: 交由上层统一日志机制 (未来可注入 logger)
                pass

    def apply_settings(self, settings: Dict[str, Any] | None):  # noqa: D401
        # 默认无操作; 子类可覆写
        return None

    # ---------- Hooks for Subclass ----------
    def _create_widget(self) -> QWidget:  # type: ignore[override]
        # 子类应返回真实控件; 这里返回占位 QWidget
        return QWidget()  # type: ignore

    def _apply_view(self, view: Dict[str, Any]):  # noqa: D401
        # 子类实现: 将 view 字段映射到控件
        pass

__all__ = ["PanelAdapter"]

