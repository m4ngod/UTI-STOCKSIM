"""SettingsSync (R6,R21)

监听 SettingsStore 变更并触发:
- 语言(language) -> i18n_manager.refresh()
- 主题(theme) -> theme_manager.apply_theme(theme)
- 其他字段保留钩子 (未来扩展: playback_speed, refresh_interval_ms)

设计:
- start(store) 注册回调一次; 多次调用幂等。
- 非阻塞: 回调内仅做快速调度 (<50ms)。
- 提供 register_i18n_widget(widget, key, attr='setText') 便捷注册翻译控件。

依赖注入:
- ThemeManager
- I18nManager

若 PySide6 不存在 (headless) 主题应用自动忽略。
"""
from __future__ import annotations
from typing import Optional, Any
from app.state.settings_store import SettingsStore
from .theme import ThemeManager
from .i18n_bind import I18nManager
from observability.metrics import metrics

class SettingsSync:
    def __init__(self, theme_manager: ThemeManager, i18n_manager: I18nManager):
        self._tm = theme_manager
        self._im = i18n_manager
        self._store: Optional[SettingsStore] = None
        self._started = False
        # 新增: 已注册的 adapters 列表 (需具有 apply_settings 方法)
        self._adapters: list[Any] = []

    # ---------- Public API ----------
    def start(self, store: SettingsStore):  # 幂等
        if self._started and self._store is store:
            return
        self._store = store
        # 注册回调
        store.on_language(self._on_language)
        store.on_theme(self._on_theme)
        # 预应用当前状态（启动即可同步）
        st = store.get_state()
        try:
            self._tm.apply_theme(st.theme)
            self._im.refresh()
        except Exception:  # pragma: no cover
            metrics.inc('settings_sync_init_error')
        # 启动时向已注册 adapters 推送一次完整设置
        self._apply_to_adapters(st)
        self._started = True

    def register_adapter(self, adapter: Any):  # noqa: D401
        """注册一个具有 apply_settings(settings_dict|None) 方法的对象.
        若已启动且已绑定 store, 立即推送一次完整设置.
        """
        if adapter not in self._adapters:
            self._adapters.append(adapter)
            if self._store is not None:  # 已启动立即同步
                st = self._store.get_state()
                self._apply_to_single(adapter, st)
        return adapter

    def register_i18n_widget(self, widget: Any, key: str, attr: str = 'setText'):
        self._im.register(widget, key, attr)

    # ---------- Internal Helpers ----------
    def _apply_to_single(self, adapter: Any, st):  # noqa: D401
        fn = getattr(adapter, 'apply_settings', None)
        if callable(fn):
            try:
                # SettingsState 提供 _serializable_dict
                data = st._serializable_dict() if hasattr(st, '_serializable_dict') else None
                fn(data)
            except Exception:  # pragma: no cover
                pass

    def _apply_to_adapters(self, st):  # noqa: D401
        for ad in list(self._adapters):
            self._apply_to_single(ad, st)

    # ---------- Callbacks ----------
    def _on_language(self, kind: str, value, full):  # noqa: D401, ANN001
        try:
            self._im.refresh()
        except Exception:  # pragma: no cover
            metrics.inc('settings_sync_lang_error')
        # 语言变更后推送最新完整设置
        if self._store is not None:
            self._apply_to_adapters(self._store.get_state())

    def _on_theme(self, kind: str, value, full):  # noqa: D401, ANN001
        try:
            self._tm.apply_theme(value)
        except Exception:  # pragma: no cover
            metrics.inc('settings_sync_theme_error')
        # 主题变更后推送最新完整设置
        if self._store is not None:
            self._apply_to_adapters(self._store.get_state())

__all__ = ["SettingsSync"]
