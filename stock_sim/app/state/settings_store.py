"""SettingsStore (Spec Task 16)

目标:
- 封装 SettingsState, 提供回调订阅 (语言/主题/刷新频率/告警阈值/高对比/倍速 等变化)。(R6 AC1/2/3/4/5/6, R11, R12 Task33)
- 统一持久化: 初始化时加载 JSON, 每次更新自动保存 (可禁用 auto_save)。
- 提供 register_callback(kind, fn) / on_language(fn) 等简化接口。
- 语言切换触发回调 (Done 判定需求)。

设计:
- 内部持有 SettingsState (可从文件加载)。
- update(...) 时对比变更字段, 按字段类型调用对应回调列表。
- 回调类型枚举: any, language, theme, refresh, alert_thresholds, playback_speed, high_contrast。(Task33 新增)
- 线程安全: RLock.

不负责布局 (由 layout_persistence.py 负责)。
"""
from __future__ import annotations
from typing import Callable, Dict, Any, List
from threading import RLock, Thread
from .settings_state import SettingsState

try:  # 与 i18n 解耦: 若未实现不影响 SettingsStore 基础功能
    from app.i18n import set_language as _i18n_set_language  # type: ignore
    from app.i18n import reload as _i18n_reload  # type: ignore
except Exception:  # pragma: no cover - 仅在缺失模块时走这里
    _i18n_set_language = None  # type: ignore
    _i18n_reload = None  # type: ignore

Callback = Callable[[str, Any, Dict[str, Any]], None]  # (field, new_value, full_state_dict)

class SettingsStore:
    def __init__(self, *, path: str, auto_save: bool = True):
        self._lock = RLock()
        self._state = SettingsState.load(path)
        self._state.persist_path = path
        self._auto_save = auto_save
        self._callbacks: Dict[str, List[Callback]] = {
            'any': [],
            'language': [],
            'theme': [],
            'refresh_interval_ms': [],
            'alert_thresholds': [],
            'playback_speed': [],
            'high_contrast': [],  # Task33
        }
        # 启动时异步应用已持久化的语言偏好（不阻塞 UI 线程），失败时在 i18n 层回退
        self._apply_language_preference_async()

    # ---------------- Subscription API ----------------
    def register_callback(self, kind: str, fn: Callback):
        with self._lock:
            if kind not in self._callbacks:
                self._callbacks[kind] = []
            self._callbacks[kind].append(fn)

    # convenience
    def on_language(self, fn: Callback): self.register_callback('language', fn)
    def on_theme(self, fn: Callback): self.register_callback('theme', fn)
    def on_refresh(self, fn: Callback): self.register_callback('refresh_interval_ms', fn)
    def on_alert_thresholds(self, fn: Callback): self.register_callback('alert_thresholds', fn)
    def on_playback_speed(self, fn: Callback): self.register_callback('playback_speed', fn)
    def on_high_contrast(self, fn: Callback): self.register_callback('high_contrast', fn)  # Task33
    def on_any(self, fn: Callback): self.register_callback('any', fn)

    # ---------------- State Mutation -------------------
    def update(self, **kwargs):
        changed: Dict[str, Any] = {}
        with self._lock:
            for k, v in kwargs.items():
                if not hasattr(self._state, k):
                    continue
                current = getattr(self._state, k)
                if k == 'alert_thresholds' and isinstance(v, dict):
                    # 合并更新
                    merged = dict(current)
                    dirty = False
                    for ak, av in v.items():
                        if merged.get(ak) != av:
                            merged[ak] = av
                            dirty = True
                    if dirty:
                        setattr(self._state, k, merged)
                        changed[k] = merged
                else:
                    if current != v:
                        setattr(self._state, k, v)
                        changed[k] = v
            if changed:
                if self._auto_save:
                    self._state.save()
                # 发布回调
                payload = self._state._serializable_dict()
                for field, new_val in changed.items():
                    self._fire(field, new_val, payload)
                self._fire('any', changed, payload)
        return changed

    def set_language(self, lang: str):
        # 先更新 i18n 当前语言 (懒加载内部处理)，再写入状态
        if _i18n_set_language is not None:
            try:
                _i18n_set_language(lang)  # type: ignore
            except Exception:
                # 忽略 i18n 层错误，不阻断状态变更
                pass
        return self.update(language=lang)

    def set_theme(self, theme: str):
        return self.update(theme=theme)

    def set_refresh_interval(self, ms: int):
        return self.update(refresh_interval_ms=ms)

    def set_playback_speed(self, speed: float):
        return self.update(playback_speed=speed)

    def set_high_contrast(self, enabled: bool):  # Task33
        return self.update(high_contrast=enabled)

    def update_alert_threshold(self, key: str, value: Any):
        return self.update(alert_thresholds={key: value})

    # ---------------- Accessors -----------------------
    def get_state(self) -> SettingsState:
        with self._lock:
            return self._state

    # ---------------- Internal ------------------------
    def _fire(self, kind: str, val: Any, full: Dict[str, Any]):
        cbs = list(self._callbacks.get(kind, []))
        for cb in cbs:
            try:
                cb(kind, val, full)
            except Exception:
                # 忽略单个回调错误 (可后续加 metrics)
                pass

    def _apply_language_preference_async(self):
        """异步应用持久化的语言偏好。
        - 优先使用 i18n.reload(locale) 以便失败时自动回退默认语言。
        - 若回退后生效语言与持久化不一致，回写到设置状态并触发持久化与回调。
        - 全过程不阻塞 UI 线程。
        """
        lang = self._state.language
        def _job():
            applied = None
            try:
                if _i18n_reload is not None:
                    applied = _i18n_reload(lang)  # type: ignore
                elif _i18n_set_language is not None:
                    _i18n_set_language(lang)  # type: ignore
                    applied = lang
            except Exception:
                # 任何异常均忽略，由 i18n 层自行回退/保持
                pass
            if applied and applied != lang:
                # 回写回退后的实际生效语言
                try:
                    self.update(language=applied)
                except Exception:
                    pass
        t = Thread(target=_job, name="SettingsStore-ApplyLang", daemon=True)
        t.start()

__all__ = ["SettingsStore", "SettingsState"]
