"""SettingsState: 负责前端可持久化设置 (语言/主题/刷新/告警/倍速)。
支持 JSON 文件持久化与事件发布。
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional
import json
import os
from infra.event_bus import event_bus

SETTINGS_STATE_INIT = "settings.state.init"
SETTINGS_STATE_UPDATED = "settings.state.updated"

_DEFAULT_ALERT_THRESHOLDS = {
    "drawdown_pct": 0.1,  # 10%
    "heartbeat_ms": 10_000,
}

@dataclass
class SettingsState:
    language: str = "zh_CN"
    theme: str = "light"
    refresh_interval_ms: int = 1_000
    playback_speed: float = 1.0
    alert_thresholds: Dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_ALERT_THRESHOLDS))
    # Task33 可访问性: 高对比模式 (后续可驱动主题变量调整)
    high_contrast: bool = False
    persist_path: Optional[str] = None

    def __post_init__(self):
        # 初始化后广播一次, 便于面板初始订阅
        event_bus.publish(SETTINGS_STATE_INIT, self.to_payload(full=True))

    # --- 更新 API -----------------------------------------------------
    def update(self, **kwargs):
        changed: Dict[str, Any] = {}
        for k, v in kwargs.items():
            if not hasattr(self, k):  # 忽略未知字段 (向前兼容)
                continue
            if getattr(self, k) != v:
                setattr(self, k, v)
                changed[k] = v
        if changed:
            self._publish(changed)

    def set_language(self, lang: str):
        self.update(language=lang)

    def set_theme(self, theme: str):
        self.update(theme=theme)

    def set_refresh_interval(self, ms: int):
        self.update(refresh_interval_ms=ms)

    def set_playback_speed(self, speed: float):
        self.update(playback_speed=speed)

    def set_high_contrast(self, enabled: bool):  # Task33 新增
        self.update(high_contrast=enabled)

    def update_alert_threshold(self, key: str, value: Any):
        if self.alert_thresholds.get(key) != value:
            self.alert_thresholds[key] = value
            self._publish({"alert_thresholds": self.alert_thresholds})

    # --- 持久化 -------------------------------------------------------
    def save(self, path: Optional[str] = None):
        p = path or self.persist_path
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self._serializable_dict(), f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @classmethod
    def load(cls, path: str) -> "SettingsState":
        if not os.path.exists(path):
            return cls(persist_path=path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            # 合并默认告警 (新增字段向前兼容)
            alert = dict(_DEFAULT_ALERT_THRESHOLDS)
            alert.update(raw.get("alert_thresholds", {}))
            inst = cls(
                language=raw.get("language", "zh_CN"),
                theme=raw.get("theme", "light"),
                refresh_interval_ms=raw.get("refresh_interval_ms", 1000),
                playback_speed=raw.get("playback_speed", 1.0),
                alert_thresholds=alert,
                high_contrast=raw.get("high_contrast", False),  # Task33 新增
                persist_path=path,
            )
            return inst
        except Exception:
            return cls(persist_path=path)

    # --- 工具 ---------------------------------------------------------
    def to_payload(self, *, full: bool = False) -> Dict[str, Any]:
        data = self._serializable_dict()
        if full:
            data["full"] = True
        return data

    def _serializable_dict(self) -> Dict[str, Any]:
        return {
            "language": self.language,
            "theme": self.theme,
            "refresh_interval_ms": self.refresh_interval_ms,
            "playback_speed": self.playback_speed,
            "alert_thresholds": self.alert_thresholds,
            "high_contrast": self.high_contrast,  # Task33
        }

    def _publish(self, changed: Dict[str, Any]):
        payload = {"changed": changed, **self.to_payload(full=False)}
        event_bus.publish(SETTINGS_STATE_UPDATED, payload)

__all__ = [
    "SettingsState",
    "SETTINGS_STATE_INIT",
    "SETTINGS_STATE_UPDATED",
]
