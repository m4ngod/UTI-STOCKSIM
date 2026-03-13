"""SettingsController (Spec Task 22)

职责 (R6,R11):
- 封装 SettingsStore 读写接口，提供 get_state / update / set_* 方法
- 支持注册字段级回调 (on(kind, fn)) 以便 UI 热更新 (语言/主题/刷新频率/阈值/倍速)

热更新判定: 调用 update / set_language 等后, get_state 返回最新值且回调触发。

扩展 TODO:
- TODO: 增加 metrics 统计每类设置变更次数
- TODO: 增加批量事务语义 (防止多次回调抖动)

Future Hooks (Task50):
- TODO: Settings 变更事件外部化 (Kafka topic settings.changes)
- TODO: A/B 实验参数注入 (feature flags) 与回滚策略
- TODO: 用户自定义快捷键映射持久化扩展
- TODO: 导出/导入配置 (JSON schema 验证)
"""
from __future__ import annotations
from typing import Any, Dict, Callable

from app.state.settings_store import SettingsStore, SettingsState

__all__ = ["SettingsController"]

Callback = Callable[[str, Any, Dict[str, Any]], None]

class SettingsController:
    def __init__(self, store: SettingsStore):
        self._store = store

    # -------- Accessors --------
    def get_state(self) -> SettingsState:
        return self._store.get_state()

    # -------- Mutations --------
    def update(self, **kwargs):  # 批量更新
        return self._store.update(**kwargs)

    def set_language(self, lang: str):
        """设置语言并驱动全局最小刷新。
        - 优先使用 i18n.reload(lang) 以获得失败回退后的实际生效语言。
        - 仅当生效语言变化时回写 SettingsStore（触发持久化与回调）。
        - 刷新策略：调用 ui_refresh.refresh_language_dependent_ui() 最小范围更新标题/菜单，避免闪烁。
        """
        applied = None
        # 1) 先尝试 reload 以处理无效语言的回退
        try:
            from app.i18n import reload as _i18n_reload  # type: ignore
            applied = _i18n_reload(lang)
        except Exception:
            # 回退：让 store 自行处理（内部 set_language 会懒加载）
            applied = lang
        # 2) 若生效语言与当前不同则回写
        st = self._store.get_state()
        final_locale = applied or lang
        if st.language != final_locale:
            # 用 update 避免再次触发 i18n.set_language
            self._store.update(language=final_locale)
        # 3) 触发 UI 端最小刷新（若可用）
        try:
            from app.ui import ui_refresh  # type: ignore
            if hasattr(ui_refresh, 'refresh_language_dependent_ui'):
                ui_refresh.refresh_language_dependent_ui()
        except Exception:
            # UI 不可用或不需要刷新时静默
            pass
        return {"language": final_locale}

    def set_theme(self, theme: str):
        return self._store.set_theme(theme)

    def set_refresh_interval(self, ms: int):
        return self._store.set_refresh_interval(ms)

    def set_playback_speed(self, speed: float):
        return self._store.set_playback_speed(speed)

    def update_alert_threshold(self, key: str, value: Any):
        return self._store.update_alert_threshold(key, value)

    # -------- Subscription --------
    def on(self, kind: str, fn: Callback):
        self._store.register_callback(kind, fn)
        return fn

    # 便捷
    def on_language(self, fn: Callback): return self.on('language', fn)
    def on_theme(self, fn: Callback): return self.on('theme', fn)
    def on_refresh(self, fn: Callback): return self.on('refresh_interval_ms', fn)
    def on_alert_thresholds(self, fn: Callback): return self.on('alert_thresholds', fn)
    def on_playback_speed(self, fn: Callback): return self.on('playback_speed', fn)
    def on_any(self, fn: Callback): return self.on('any', fn)
