# python
"""ConfigHotReloader (platform-hardening Task10)

功能:
  - apply(patch: dict) -> dict  (返回 {changed: {k: new_v}, invalid: {k: reason}})
  - 仅允许白名单字段热更新 (最小侵入, 避免破坏运行时语义)
  - 类型校验: 按当前 settings.<field> 的类型尝试转换; 失败则 invalid
  - 若有至少 1 个字段成功变更 -> 发布 EventType.CONFIG_CHANGED
  - 对部分联动字段执行简单后处理 (如 SNAPSHOT_THROTTLE_N_PER_SYMBOL 调整)

白名单字段 (可扩展):
  BORROW_RATE_DAILY, BORROW_FEE_MIN_NOTIONAL,
  MAX_SINGLE_ORDER_NOTIONAL, MAX_ORDER_QTY, MAX_POSITION_RATIO,
  MAX_NET_EXPOSURE_NOTIONAL, MAX_GROSS_EXPOSURE_NOTIONAL,
  ORDER_RATE_WINDOW_SEC, ORDER_RATE_MAX,
  SNAPSHOT_THROTTLE_N_PER_SYMBOL, SNAPSHOT_ENABLE,
  LIQUIDATION_ENABLED, MAINTENANCE_MARGIN_RATIO, LIQUIDATION_ORDER_SLICE_RATIO,
  RISK_DISABLE_SHORT, BROKER_UNLIMITED_LENDING

使用:
  from services.config_hot_reload import config_hot_reloader
  result = config_hot_reloader.apply({"BORROW_RATE_DAILY":0.0007})

线程安全:
  - 简单 RLock 序列化 apply 调用

容错:
  - 单字段失败不影响其它字段
"""
from __future__ import annotations
from typing import Any, Dict
from threading import RLock

try:
    from stock_sim.settings import settings  # type: ignore
    from stock_sim.infra.event_bus import event_bus  # type: ignore
    from stock_sim.core.const import EventType  # type: ignore
    from stock_sim.observability.metrics import metrics  # type: ignore
except Exception:  # noqa
    from settings import settings  # type: ignore
    from infra.event_bus import event_bus  # type: ignore
    from core.const import EventType  # type: ignore
    from observability.metrics import metrics  # type: ignore

_ALLOWED_FIELDS = {
    "BORROW_RATE_DAILY", "BORROW_FEE_MIN_NOTIONAL",
    "MAX_SINGLE_ORDER_NOTIONAL", "MAX_ORDER_QTY", "MAX_POSITION_RATIO",
    "MAX_NET_EXPOSURE_NOTIONAL", "MAX_GROSS_EXPOSURE_NOTIONAL",
    "ORDER_RATE_WINDOW_SEC", "ORDER_RATE_MAX",
    "SNAPSHOT_THROTTLE_N_PER_SYMBOL", "SNAPSHOT_ENABLE",
    "LIQUIDATION_ENABLED", "MAINTENANCE_MARGIN_RATIO", "LIQUIDATION_ORDER_SLICE_RATIO",
    "RISK_DISABLE_SHORT", "BROKER_UNLIMITED_LENDING",
}

class ConfigHotReloader:
    def __init__(self):
        self._lock = RLock()

    def apply(self, patch: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """应用热更新补丁。
        返回: { 'changed': {...}, 'invalid': {...} }
        """
        changed: Dict[str, Any] = {}
        invalid: Dict[str, str] = {}
        with self._lock:
            for k, v in patch.items():
                if k not in _ALLOWED_FIELDS:
                    invalid[k] = "FIELD_NOT_ALLOWED"
                    continue
                if not hasattr(settings, k):
                    invalid[k] = "FIELD_NOT_EXIST"
                    continue
                current = getattr(settings, k)
                target_type = type(current)
                # bool 特判 (避免 bool("0") == True 问题)
                try:
                    if target_type is bool:
                        if isinstance(v, str):
                            lv = v.lower()
                            if lv in ("true","1","yes","y","on"):  # noqa
                                casted = True
                            elif lv in ("false","0","no","n","off"):
                                casted = False
                            else:
                                raise ValueError("INVALID_BOOL_STRING")
                        else:
                            casted = bool(v)
                    else:
                        casted = target_type(v)
                except Exception:
                    invalid[k] = "TYPE_CAST_FAIL"
                    continue
                if casted == current:
                    # 未变化, 忽略 (不视为 invalid)
                    continue
                try:
                    setattr(settings, k, casted)
                    changed[k] = casted
                except Exception:
                    invalid[k] = "SET_ATTR_FAIL"
                    continue
            # 后处理: 若 snapshot 基准阈值降低, 可通知自适应管理器(若存在)
            if "SNAPSHOT_THROTTLE_N_PER_SYMBOL" in changed:
                try:  # 尝试同步自适应管理器 base (软耦合)
                    from services.adaptive_snapshot_service import AdaptiveSnapshotPolicyManager  # type: ignore
                    # 用户可能有单例实例, 尝试探测
                    import services.adaptive_snapshot_service as asp_mod  # type: ignore
                    for name in ("adaptive_manager","adaptive_snapshot_manager","ASPM","manager"):
                        inst = getattr(asp_mod, name, None)
                        if isinstance(inst, AdaptiveSnapshotPolicyManager):
                            inst.base = getattr(settings, "SNAPSHOT_THROTTLE_N_PER_SYMBOL")
                except Exception:  # noqa
                    pass
            # 发布事件
            if changed:
                try:
                    event_bus.publish(EventType.CONFIG_CHANGED, {"changed": changed, "invalid": invalid})
                except Exception:
                    pass
                try:
                    metrics.inc("config_hot_reload_changed", len(changed))
                except Exception:
                    pass
            if invalid:
                try:
                    metrics.inc("config_hot_reload_invalid", len(invalid))
                except Exception:
                    pass
        return {"changed": changed, "invalid": invalid}

config_hot_reloader = ConfigHotReloader()

__all__ = ["config_hot_reloader", "ConfigHotReloader"]

