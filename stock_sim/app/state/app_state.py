"""Global AppState implementation.
维护前端运行期全局共享状态: 当前账户/时钟/语言/主题/指标缓存 key 等。
更新时通过 infra.event_bus 发布事件, 供控制器/面板监听。
"""
from __future__ import annotations
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from infra.event_bus import event_bus
from app.core_dto import AccountDTO, ClockStateDTO

# 事件 topic 常量 (简单字符串, 便于后续跨进程或 Redis 复用)
APP_STATE_INIT = "app.state.init"
APP_STATE_UPDATED = "app.state.updated"

@dataclass
class AppState:
    current_account: Optional[AccountDTO] = None
    clock: Optional[ClockStateDTO] = None
    language: str = "zh_CN"  # 冗余: SettingsState 也维护, AppState 作为快照供消费
    theme: str = "light"
    _indicator_version: int = 0
    indicator_cache_key: str = field(default="indicators:v0")

    def __post_init__(self):  # 启动时广播一次 init
        event_bus.publish(APP_STATE_INIT, self.to_payload(full=True))

    # --- 公共更新接口 -------------------------------------------------
    def update_account(self, account: AccountDTO):
        self.current_account = account
        self._publish(field="account", value=account.dict())

    def update_clock(self, clock: ClockStateDTO):
        self.clock = clock
        self._publish(field="clock", value=clock.dict())

    def apply_settings_overlay(self, *, language: Optional[str] = None, theme: Optional[str] = None):
        changed: Dict[str, Any] = {}
        if language and language != self.language:
            self.language = language
            changed["language"] = language
        if theme and theme != self.theme:
            self.theme = theme
            changed["theme"] = theme
        if changed:
            self._publish(field="settings_overlay", value=changed)

    def bump_indicator_cache(self) -> str:
        self._indicator_version += 1
        self.indicator_cache_key = f"indicators:v{self._indicator_version}"
        self._publish(field="indicator_cache_key", value=self.indicator_cache_key)
        return self.indicator_cache_key

    # --- 序列化 & 事件封装 --------------------------------------------
    def to_payload(self, *, full: bool = False) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "language": self.language,
            "theme": self.theme,
            "indicator_cache_key": self.indicator_cache_key,
        }
        if self.current_account:
            data["account"] = self.current_account.dict()
        if self.clock:
            data["clock"] = self.clock.dict()
        if full:
            data["full"] = True
        return data

    def _publish(self, *, field: str, value: Any):
        payload = {"field": field, "value": value, **self.to_payload(full=False)}
        event_bus.publish(APP_STATE_UPDATED, payload)

__all__ = [
    "AppState",
    "APP_STATE_INIT",
    "APP_STATE_UPDATED",
]

