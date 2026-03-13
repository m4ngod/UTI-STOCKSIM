"""Settings 与 Clock 加速比联动桥接

功能:
- 监听 SettingsStore playback_speed 变更 -> 调用 ClockPanel.set_speed
- 忽略非法值 (<=0 或 非数字) 并发送 warning 通知 (code=settings.playback_speed.invalid)
- 幂等: 多次调用 wire_playback_speed 不重复注册
"""
from __future__ import annotations
from typing import Any, Callable

try:  # 通知中心可选
    from app.panels.shared.notifications import notification_center  # type: ignore
except Exception:  # pragma: no cover
    notification_center = None  # type: ignore

def wire_playback_speed(settings_controller, clock_panel):  # noqa: ANN001
    """桥接设置倍速 -> 时钟面板.

    settings_controller: SettingsController 实例
    clock_panel: ClockPanel 实例
    """
    # 防止重复注册 (给 panel 打标记)
    if getattr(clock_panel, '_playback_speed_wired', False):  # noqa: SLF001
        return

    def _cb(kind: str, value: Any, full: dict):  # noqa: ANN001
        # kind == 'playback_speed'
        try:
            spd = float(value)
        except Exception:
            if notification_center:
                notification_center.publish_warning('settings.playback_speed.invalid', f'invalid playback_speed value: {value!r}')
            return
        if spd <= 0:
            if notification_center:
                notification_center.publish_warning('settings.playback_speed.invalid', f'non-positive playback_speed ignored: {spd}')
            return
        # 合法，应用到 clock_panel (它会调用 controller 再更新自身缓存)
        try:
            clock_panel.set_speed(spd)
        except Exception as e:  # pragma: no cover - 防御
            if notification_center:
                notification_center.publish_warning('settings.playback_speed.apply_fail', f'apply speed failed: {e}')

    settings_controller.on_playback_speed(_cb)
    setattr(clock_panel, '_playback_speed_wired', True)  # noqa: SLF001

__all__ = ["wire_playback_speed"]

