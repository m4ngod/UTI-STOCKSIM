"""BasePanelLogic (R25)

抽象/轻量面板逻辑基类: 供后续 UI Adapter 绑定。保持可选使用——现有面板不强制继承。

设计原则:
- 无 Qt 依赖, 纯逻辑, 便于单元测试 / 复用。
- attach/detach 幂等; 不抛出外部异常。
- apply_settings: 供语言/主题/阈值等批量更新 (SettingsStore 广播)。
- get_view: 子类实现, 返回结构化 dict/DTO; 基类仅提供占位。

使用示例:
    class AccountPanel(BasePanelLogic):
        def get_view(self):
            return {...}

注意: 后续若增加生命周期扩展(如 before_refresh/after_refresh) 保持向后兼容。
"""
from __future__ import annotations
from typing import Any, Dict, Optional, Protocol, runtime_checkable

__all__ = ["BasePanelLogic", "PanelContextProtocol"]

@runtime_checkable
class PanelContextProtocol(Protocol):  # 运行时可检查, 用于类型提示 (可选)
    """可选上下文协议: MainWindow/DI 容器可实现此协议以向面板提供依赖。
    预留属性示例 (不强制存在):
    - settings_store
    - notification_center
    - controllers
    """
    ...  # noqa: D401 / future extension

class BasePanelLogic:
    """基础面板逻辑抽象 (非强制).

    子类可覆盖:
      - apply_settings: 响应语言/主题/配置变更
      - detach: 清理引用/缓存
      - get_view: 返回视图模型(dict / dataclass / TypedDict)
    """
    __slots__ = ("_context", "_attached")

    def __init__(self) -> None:
        self._context: Optional[PanelContextProtocol] = None
        self._attached: bool = False

    # ---------------- Lifecycle ----------------
    def attach(self, context: PanelContextProtocol | None) -> "BasePanelLogic":
        """绑定外部上下文(幂等). 若已附加且同对象则忽略。
        context 为 None 允许在测试中独立使用。
        """
        if self._attached and context is self._context:
            return self
        self._context = context  # 可为 None
        self._attached = True
        self.on_attached()
        return self

    def on_attached(self) -> None:  # 钩子: 子类可覆写
        pass

    def detach(self) -> None:
        """释放上下文(幂等)."""
        if not self._attached:
            return
        try:
            self.on_detaching()
        finally:
            self._context = None
            self._attached = False

    def on_detaching(self) -> None:  # 钩子: 子类清理缓存/订阅
        pass

    # ---------------- Settings ----------------
    def apply_settings(self, settings: Dict[str, Any] | None) -> None:
        """应用批量设置变更 (语言/主题/阈值)。默认无操作。"""
        pass

    # ---------------- View ----------------
    def get_view(self) -> Dict[str, Any]:  # 子类应重写
        raise NotImplementedError("Subclasses must implement get_view()")

    # ---------------- Helpers ----------------
    @property
    def attached(self) -> bool:
        return self._attached

    @property
    def context(self) -> Optional[PanelContextProtocol]:  # 允许测试中访问
        return self._context

