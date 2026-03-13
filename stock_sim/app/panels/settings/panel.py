"""SettingsPanel (Spec Task 29)

职责 (R6,R11):
- 展示与修改前端设置: 语言/主题/刷新频率/告警阈值/倍速
- 管理布局 LayoutPersistence (读取/增量更新/全量替换)
- 语言切换后 300ms 内 get_view 看到新语言 (依赖 SettingsStore 同步更新)
- 提供 batch 更新接口 (减少多次回调抖动, 此处顺序调用 controller.update)

get_view() 结构:
{
  'settings': {language, theme, refresh_interval_ms, playback_speed, alert_thresholds},
  'layout': {...layout dict...},
  'recent_changes': {<field>: <value>, ...} | None,
  'last_update_ms': epoch_ms,
}

扩展 TODO:
- TODO: 增加 metrics 记录各字段修改次数 (Spec Task 30 已实现)
- TODO: 支持事务式批量更新 (一次回调)
"""
from __future__ import annotations
from threading import RLock
from typing import Any, Dict, Optional
import time

from app.controllers.settings_controller import SettingsController
from app.state.layout_persistence import LayoutPersistence
# 新增: 通知中心可选导入
try:  # pragma: no cover
    from app.panels.shared.notifications import notification_center as _notification_center
except Exception:  # pragma: no cover
    _notification_center = None

__all__ = ["SettingsPanel"]

class SettingsPanel:
    def __init__(self, controller: SettingsController, layout: Optional[LayoutPersistence] = None):
        self._ctl = controller
        self._layout = layout or LayoutPersistence(path="layout_settings_panel.json")
        self._lock = RLock()
        st = controller.get_state()
        self._settings_cache: Dict[str, Any] = self._extract_settings(st)
        self._recent_changes: Optional[Dict[str, Any]] = None
        self._last_update_ms: int = int(time.time()*1000)
        # 订阅变化
        self._ctl.on_any(self._on_any)
        self._history: list[Dict[str, Any]] = []  # Task33: 历史栈 (旧设置快照)
        self._undoing: bool = False  # Task33
        self._history_limit = 10
        self._redo_stack: list[Dict[str, Any]] = []  # Task34: redo 栈 (存放撤销前的当前状态)
        self._redoing: bool = False  # Task34: 标记 redo 中
        # 播放速度桥接标记/缓存
        self._playback_speed_bridge_done: bool = False
        self._clock_panel_cached = None
        # 监听单字段 playback_speed 以桥接到 ClockPanel.set_speed
        self._ctl.on_playback_speed(self._on_playback_speed_change)

    # -------- Internal Bridge --------
    def _on_playback_speed_change(self, kind: str, value, full):  # noqa: ANN001
        # 懒加载取得 clock 面板
        if not self._playback_speed_bridge_done:
            try:
                from app.panels import get_panel  # 延迟导入避免循环
                cp = get_panel('clock')
                self._clock_panel_cached = cp
                # 调用桥接工具 (若存在) 供后续变更使用
                try:
                    from app.bridge.settings_clock import wire_playback_speed  # type: ignore
                    wire_playback_speed(self._ctl, cp)
                except Exception:
                    pass
                self._playback_speed_bridge_done = True
            except Exception:
                # 时钟面板尚未创建, 下次再尝试
                pass
        # 当前变更立即尝试应用(若已有 clock 面板)
        if self._clock_panel_cached is not None:
            try:
                spd = float(value)
            except Exception:
                if _notification_center:
                    _notification_center.publish_warning('settings.playback_speed.invalid', f'invalid playback_speed value: {value!r}')
                return
            if spd <= 0:
                if _notification_center:
                    _notification_center.publish_warning('settings.playback_speed.invalid', f'non-positive playback_speed ignored: {spd}')
                return
            try:
                self._clock_panel_cached.set_speed(spd)
            except Exception as e:  # pragma: no cover
                if _notification_center:
                    _notification_center.publish_warning('settings.playback_speed.apply_fail', f'apply speed failed: {e}')

    # -------- Public API: Settings --------
    def set_language(self, lang: str):
        t0 = time.perf_counter()
        self._ctl.set_language(lang)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        # 新增: 语言切换耗时分布
        try:
            from observability.metrics import metrics  # 低开销导入
            metrics.add_timing("language_switch_ms", float(elapsed_ms))
        except Exception:
            pass
        if elapsed_ms > 300:  # 仅记录, 不抛异常
            try:
                from observability.metrics import metrics
                metrics.inc("settings_panel_language_slow")
            except Exception:  # pragma: no cover
                pass

    def set_theme(self, theme: str):
        self._ctl.set_theme(theme)

    def set_refresh_interval(self, ms: int):
        self._ctl.set_refresh_interval(ms)

    def set_playback_speed(self, speed: float):
        self._ctl.set_playback_speed(speed)

    def update_alert_threshold(self, key: str, value: Any):
        self._ctl.update_alert_threshold(key, value)

    def batch_update(self, **kwargs):
        # 直接走 controller.update (SettingsStore 已合����逻辑)
        if kwargs:
            self._ctl.update(**kwargs)

    def undo_last(self) -> bool:  # Task33
        """撤销最近一次 settings 变更 (不含布局)。成功返回 True, 否则 False。
        会触发一次 update (单次 any 回调)；撤销操作自身不会再被记录入历史。
        """
        snap: Optional[Dict[str, Any]] = None
        with self._lock:
            if self._history:
                snap = self._history.pop()
                # Task34: 将当前状态快照推入 redo 栈 (供 redo 返回)
                current_snapshot = dict(self._settings_cache)
                self._redo_stack.append(current_snapshot)
        if not snap:
            try:
                from observability.metrics import metrics
                metrics.inc('settings_panel_undo_empty')
            except Exception:  # pragma: no cover
                pass
            return False
        try:
            self._undoing = True
            # 直接全量应用 snapshot (alert_thresholds为dict)
            self._ctl.update(**snap)
            try:
                from observability.metrics import metrics
                metrics.inc('settings_panel_undo_success')
            except Exception:  # pragma: no cover
                pass
            return True
        finally:
            self._undoing = False

    def redo_next(self) -> bool:  # Task34
        """重做：恢复最近一次被撤销前的状态 (与 undo 配套)。成功返回 True。
        """
        snap: Optional[Dict[str, Any]] = None
        with self._lock:
            if self._redo_stack:
                snap = self._redo_stack.pop()
        if not snap:
            try:
                from observability.metrics import metrics
                metrics.inc('settings_panel_redo_empty')
            except Exception:  # pragma: no cover
                pass
            return False
        try:
            self._redoing = True
            self._ctl.update(**snap)
            try:
                from observability.metrics import metrics
                metrics.inc('settings_panel_redo_success')
            except Exception:  # pragma: no cover
                pass
            return True
        finally:
            self._redoing = False

    # -------- Transaction (Spec Task 31) --------
    class _Txn:
        def __init__(self, panel: 'SettingsPanel'):
            self._panel = panel
            self._changes: Dict[str, Any] = {}
            self._alert_patch: Dict[str, Any] = {}
            self._committed = False
            self._cancelled = False  # Task32
        # 字段方法
        def language(self, lang: str): self._changes['language'] = lang; return self
        def theme(self, theme: str): self._changes['theme'] = theme; return self
        def refresh_interval(self, ms: int): self._changes['refresh_interval_ms'] = ms; return self
        def playback_speed(self, speed: float): self._changes['playback_speed'] = speed; return self
        def alert_threshold(self, key: str, value: Any): self._alert_patch[key] = value; return self
        def update(self, **kwargs):
            # 直接写入 _changes (警告: alert_thresholds 需专门函数)
            for k,v in kwargs.items():
                if k == 'alert_thresholds' and isinstance(v, dict):
                    for ak,av in v.items():
                        self._alert_patch[ak] = av
                else:
                    self._changes[k] = v
            return self
        def commit(self):
            if self._committed or self._cancelled:
                return
            if self._alert_patch:
                self._changes['alert_thresholds'] = dict(self._alert_patch)
            if self._changes:
                self._panel._ctl.update(**self._changes)
                # metrics: txn commit 次数 (Task32)
                try:  # pragma: no cover (失败容忍)
                    from observability.metrics import metrics
                    metrics.inc('settings_panel_txn_commit')
                    metrics.inc('settings_panel_txn_commit_fields', len(self._changes))
                except Exception:  # pragma: no cover
                    pass
            self._committed = True
        def cancel(self):  # Task32
            if self._committed:
                return
            self._cancelled = True
            # metrics: txn cancel 次数
            try:  # pragma: no cover
                from observability.metrics import metrics
                metrics.inc('settings_panel_txn_cancel')
            except Exception:  # pragma: no cover
                pass
        def preview(self) -> Dict[str, Any]:  # Task32
            # 返回若 commit 时将要提交的最终字段 dict (含合并 alert_thresholds)
            merged = dict(self._changes)
            if self._alert_patch:
                merged.setdefault('alert_thresholds', {})
                # 如果已有 alert_thresholds (通过 update 提供), 需要合并
                if not isinstance(merged['alert_thresholds'], dict):
                    merged['alert_thresholds'] = {}
                for k, v in self._alert_patch.items():
                    merged['alert_thresholds'][k] = v
            return merged
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb):
            if exc_type is None and not self._cancelled:
                self.commit()
            return False
    def transaction(self) -> '_Txn':
        """开启事务: 聚合多字段修改 -> 单次 update。使用示例:
        with panel.transaction() as tx:
            tx.language('en_US').theme('dark')
            tx.alert_threshold('drawdown_pct', 0.2)
        """
        return SettingsPanel._Txn(self)
    # -------- Public API: Layout --------
    def update_layout(self, patch: Dict[str, Any]):
        self._layout.update(patch)
        self._touch_layout()

    def replace_layout(self, layout: Dict[str, Any]):
        self._layout.save(layout)
        self._touch_layout()

    def get_layout(self) -> Dict[str, Any]:
        return self._layout.get()

    # -------- View --------
    def get_view(self) -> Dict[str, Any]:  # R6 AC1-6 + R11 AC1/2
        with self._lock:
            settings = dict(self._settings_cache)
            recent = dict(self._recent_changes) if self._recent_changes else None
            last_ms = self._last_update_ms
        return {
            'settings': settings,
            'layout': self._layout.get(),
            'recent_changes': recent,
            'last_update_ms': last_ms,
        }

    # -------- Internal Callbacks --------
    def _on_any(self, kind: str, changed: Any, full: Dict[str, Any]):  # noqa: ANN001
        # kind == 'any'; changed 是 dict
        if not isinstance(changed, dict):
            return
        with self._lock:
            # Task33/34: 记录快照 & 栈维护
            if not self._undoing:
                prev_snapshot = dict(self._settings_cache)
                self._history.append(prev_snapshot)
                if len(self._history) > self._history_limit:
                    self._history.pop(0)
                # 新的用户变更(非 undo/redo) 清空 redo 栈
                if not self._redoing:
                    self._redo_stack.clear()
            for k, v in changed.items():
                self._settings_cache[k] = v
            self._recent_changes = dict(changed)
            self._last_update_ms = int(time.time()*1000)
        # Metrics 统计 (Spec Task 30): 每个字段 + 总计数
        try:  # 不影响主流程
            from observability.metrics import metrics
            total = 0
            for field in changed.keys():
                metrics.inc(f"settings_panel_change_{field}")
                total += 1
            if total:
                metrics.inc("settings_panel_change_total", total)
        except Exception:  # pragma: no cover
            pass

    def _touch_layout(self):
        with self._lock:
            self._last_update_ms = int(time.time()*1000)
            # recent_changes 不变 (布局修改不算设置字段)

    @staticmethod
    def _extract_settings(st) -> Dict[str, Any]:  # noqa: ANN001
        return {
            'language': st.language,
            'theme': st.theme,
            'refresh_interval_ms': st.refresh_interval_ms,
            'playback_speed': st.playback_speed,
            'alert_thresholds': dict(st.alert_thresholds),
        }
