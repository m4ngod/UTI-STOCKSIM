"""Panel Registry (Spec Task 23)

目标:
- 提供 register_panel(name, factory, *, title=None, group=None, on_register=None, on_dispose=None)
- 惰性加载: 首次 get_panel(name) 时调用 factory() 创建实例并缓存
- 提供 list_panels() -> List[dict] (不触发实例化)
- 支持重复注册保护 (抛 PanelRegistryError)
- 生命周期钩子: on_register(panel_instance) / on_dispose(panel_instance)

设计:
- 线程安全: 简单 RLock
- Panel 可以是任意对象; 面板后续任务(24~30) 可继承 UI 基类
- 轻量 metrics 记录: panel_registered / panel_created / panel_disposed

未来扩展 TODO:
- TODO: 增加分组/排序权重 & 菜单构建辅助
- TODO: 增加热替换 (reload) 支持
- TODO: 增加权限过滤 (依据用户角色隐藏)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from threading import RLock
from typing import Callable, Dict, Any, List, Optional
from stock_sim.observability.metrics import metrics
try:
    from app.i18n.loader import t  # 动态翻译面板标题
except Exception:  # pragma: no cover
    def t(key: str, **kwargs):  # type: ignore
        return key

__all__ = [
    "PanelRegistryError",
    "PanelDescriptor",
    "register_panel",
    "get_panel",
    "list_panels",
    "dispose_panel",
    "reset_registry",
    "replace_panel",
]

PanelFactory = Callable[[], Any]
LifecycleHook = Callable[[Any], None]

class PanelRegistryError(RuntimeError):
    pass

@dataclass
class PanelDescriptor:
    name: str
    factory: PanelFactory
    title: Optional[str] = None
    group: Optional[str] = None
    on_register: Optional[LifecycleHook] = None
    on_dispose: Optional[LifecycleHook] = None
    created: bool = False
    instance: Any = None
    meta: Dict[str, Any] = field(default_factory=dict)

class _PanelRegistry:
    def __init__(self):
        self._lock = RLock()
        self._descriptors: Dict[str, PanelDescriptor] = {}

    # --------------- API ---------------
    def register(self, name: str, factory: PanelFactory, *, title: str | None = None,
                 group: str | None = None, on_register: LifecycleHook | None = None,
                 on_dispose: LifecycleHook | None = None, meta: Dict[str, Any] | None = None):
        with self._lock:
            if name in self._descriptors:
                raise PanelRegistryError(f"panel '{name}' already registered")
            desc = PanelDescriptor(name=name, factory=factory, title=title,
                                   group=group, on_register=on_register, on_dispose=on_dispose,
                                   meta=meta or {})
            self._descriptors[name] = desc
            metrics.inc("panel_registered")
        return desc

    def replace(self, name: str, factory: PanelFactory, *, title: str | None = None,
                 group: str | None = None, on_register: LifecycleHook | None = None,
                 on_dispose: LifecycleHook | None = None, meta: Dict[str, Any] | None = None):
        """替换已存在面板定义 (若实例已创建则先 dispose)。"""
        with self._lock:
            old = self._descriptors.get(name)
            if old and old.created and old.on_dispose:
                try:
                    old.on_dispose(old.instance)
                except Exception:
                    pass
            merged_meta = meta or {}
            if old and not meta:  # 继承旧 meta
                merged_meta = old.meta
            desc = PanelDescriptor(name=name, factory=factory, title=title or (old.title if old else None),
                                   group=group or (old.group if old else None), on_register=on_register, on_dispose=on_dispose,
                                   meta=merged_meta)
            self._descriptors[name] = desc
            metrics.inc("panel_replaced")
        return desc

    def get(self, name: str):
        with self._lock:
            desc = self._descriptors.get(name)
            if not desc:
                raise PanelRegistryError(f"panel '{name}' not found")
            if not desc.created:
                inst = desc.factory()
                desc.instance = inst
                desc.created = True
                metrics.inc("panel_created")
                if desc.on_register:
                    try:
                        desc.on_register(inst)
                    except Exception:  # noqa: BLE001
                        pass
            return desc.instance

    def dispose(self, name: str):
        with self._lock:
            desc = self._descriptors.get(name)
            if not desc or not desc.created:
                return False
            inst = desc.instance
            desc.instance = None
            desc.created = False
            if desc.on_dispose:
                try:
                    desc.on_dispose(inst)
                except Exception:  # noqa: BLE001
                    pass
            metrics.inc("panel_disposed")
            return True

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            out: List[Dict[str, Any]] = []
            for d in self._descriptors.values():
                title = d.title or d.name
                i18n_key = d.meta.get('i18n_key') if isinstance(d.meta, dict) else None
                if i18n_key:
                    try:
                        title = t(i18n_key)
                    except Exception:  # pragma: no cover
                        pass
                out.append({
                    "name": d.name,
                    "title": title,
                    "group": d.group,
                    "created": d.created,
                })
            return out

    def reset(self):  # 仅测试使用
        with self._lock:
            self._descriptors.clear()

_registry = _PanelRegistry()

# --------------- Module level helpers ---------------

def register_panel(name: str, factory: PanelFactory, **kwargs):
    return _registry.register(name, factory, **kwargs)

def get_panel(name: str):
    return _registry.get(name)

def list_panels() -> List[Dict[str, Any]]:
    return _registry.list()

def dispose_panel(name: str) -> bool:
    return _registry.dispose(name)

def reset_registry():  # 测试辅助
    _registry.reset()

def replace_panel(name: str, factory: PanelFactory, **kwargs):
    return _registry.replace(name, factory, **kwargs)
