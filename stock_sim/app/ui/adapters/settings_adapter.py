"""SettingsPanelAdapter

目标:
- 将 SettingsPanel 逻辑 (含 transaction / undo / redo) 绑定到简单 UI 控件 (或 headless stub)
- 支持分步暂存(stage) -> 单次 Apply 触发批量更新 (transaction)
- 提供 undo()/redo() 按钮动作包装, 立即刷新 UI
- recent_changes: 依赖 SettingsPanel.get_view(); Apply 或 Undo 后调用 refresh() 立即反映

Headless 兼容:
- 若 PySide6 不可用, 使用轻量 stub 控件实现同名接口(最少属性)供测试

公开辅助方法(测试可直接调用):
- stage_language/theme/refresh_interval/playback_speed/set_alert_threshold
- apply()  (执行 transaction)
- undo()/redo()
- get_staged() 返回当前暂存字典 (便于断言)

"""
from __future__ import annotations
from typing import Any, Dict, Optional

from .base_adapter import PanelAdapter

try:  # GUI 分支
    from PySide6.QtWidgets import (  # type: ignore
        QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel,
        QSpinBox, QDoubleSpinBox
    )
except Exception:  # pragma: no cover - headless fallback
    QWidget = object  # type: ignore
    class _Sig:  # type: ignore
        def __init__(self): self._fn=[]
        def connect(self,f): self._fn.append(f)
        def emit(self,*a,**k):
            for fn in list(self._fn):
                try: fn(*a, **k)
                except Exception: pass
    class QVBoxLayout:  # type: ignore
        def __init__(self,*_,**__): pass
        def addWidget(self,*_): pass
        def addLayout(self,*_): pass
    class QHBoxLayout:  # type: ignore
        def __init__(self,*_,**__): pass
        def addWidget(self,*_): pass
    class QComboBox:  # type: ignore
        def __init__(self): self._items=[]; self._cur=-1; self.currentIndexChanged=_Sig()
        def addItems(self, arr): self._items.extend(arr)
        def clear(self): self._items=[]; self._cur=-1
        def currentText(self):
            if 0 <= self._cur < len(self._items): return self._items[self._cur]
            return ''
        def setCurrentIndex(self,i): self._cur=i; self.currentIndexChanged.emit(i)
        def count(self): return len(self._items)
    class QPushButton:  # type: ignore
        def __init__(self,text=''): self._text=text; self.clicked=_Sig(); self._en=True
        def setEnabled(self,v): self._en=v
    class QLabel:  # type: ignore
        def __init__(self,text=''): self._text=text
        def setText(self,t): self._text=t
    class QSpinBox:  # type: ignore
        def __init__(self): self._val=0; self.valueChanged=_Sig()
        def setRange(self,a,b): pass
        def setValue(self,v): self._val=v; self.valueChanged.emit(v)
        def value(self): return self._val
    class QDoubleSpinBox:  # type: ignore
        def __init__(self): self._val=0.0; self.valueChanged=_Sig()
        def setRange(self,a,b): pass
        def setDecimals(self,n): pass
        def setSingleStep(self,s): pass
        def setValue(self,v): self._val=v; self.valueChanged.emit(v)
        def value(self): return self._val


class SettingsPanelAdapter(PanelAdapter):
    def __init__(self):  # noqa: D401
        super().__init__()
        self._root: Optional[Any] = None
        self._combo_lang: Optional[Any] = None
        self._combo_theme: Optional[Any] = None
        self._spin_refresh: Optional[Any] = None
        self._spin_playback: Optional[Any] = None
        self._label_recent: Optional[Any] = None
        self._btn_apply: Optional[Any] = None
        self._btn_undo: Optional[Any] = None
        self._btn_redo: Optional[Any] = None
        # 暂存字段
        self._staged: Dict[str, Any] = {}
        self._staged_alerts: Dict[str, Any] = {}

    # ---------------------- staging helpers (public) ----------------------
    def stage_language(self, lang: str): self._staged['language'] = lang; return self
    def stage_theme(self, theme: str): self._staged['theme'] = theme; return self
    def stage_refresh_interval(self, ms: int): self._staged['refresh_interval_ms'] = ms; return self
    def stage_playback_speed(self, spd: float): self._staged['playback_speed'] = spd; return self
    def set_alert_threshold(self, key: str, value: Any): self._staged_alerts[key] = value; return self
    def clear_staged(self): self._staged.clear(); self._staged_alerts.clear(); return self
    def get_staged(self) -> Dict[str, Any]:
        merged = dict(self._staged)
        if self._staged_alerts:
            merged['alert_thresholds'] = dict(self._staged_alerts)
        return merged

    def apply(self):  # 执行批量提交
        if self._logic is None:
            return
        payload = self.get_staged()
        if not payload:
            return
        # 使用 SettingsPanel.transaction 聚合
        tx = getattr(self._logic, 'transaction', None)
        if not callable(tx):  # 回退: 直接 update
            ctl = getattr(self._logic, '_ctl', None)
            upd = getattr(ctl, 'update', None)
            if callable(upd):
                upd(**payload)
        else:
            with tx() as t:  # type: ignore
                if 'language' in payload: t.language(payload['language'])
                if 'theme' in payload: t.theme(payload['theme'])
                if 'refresh_interval_ms' in payload: t.refresh_interval(payload['refresh_interval_ms'])
                if 'playback_speed' in payload: t.playback_speed(payload['playback_speed'])
                alerts = payload.get('alert_thresholds')
                if isinstance(alerts, dict):
                    for k,v in alerts.items():
                        t.alert_threshold(k, v)
        self.clear_staged()
        self.refresh()  # 立刻反映 recent_changes
        try:  # metrics
            from observability.metrics import metrics
            metrics.inc('settings_panel_adapter_apply')
        except Exception:  # pragma: no cover
            pass

    def undo(self):
        if self._logic is None: return False
        fn = getattr(self._logic, 'undo_last', None)
        ok = False
        if callable(fn): ok = bool(fn())
        self.refresh()
        return ok

    def redo(self):
        if self._logic is None: return False
        fn = getattr(self._logic, 'redo_next', None)
        ok = False
        if callable(fn): ok = bool(fn())
        self.refresh()
        return ok

    # ---------------------- UI overrides ----------------------
    def _create_widget(self):  # noqa: D401
        root = QWidget()  # type: ignore
        try:  # GUI 布局 (若在 headless fallback 直接忽略)
            v = QVBoxLayout(root)  # type: ignore
            line1 = QHBoxLayout()  # type: ignore
            self._combo_lang = QComboBox()  # type: ignore
            self._combo_lang.addItems(['zh_CN','en_US'])  # type: ignore
            self._combo_theme = QComboBox()  # type: ignore
            self._combo_theme.addItems(['light','dark'])  # type: ignore
            try:
                self._combo_lang.currentIndexChanged.connect(self._on_lang_changed)  # type: ignore[attr-defined]
                self._combo_theme.currentIndexChanged.connect(self._on_theme_changed)  # type: ignore[attr-defined]
            except Exception: pass
            line1.addWidget(self._combo_lang)  # type: ignore
            line1.addWidget(self._combo_theme)  # type: ignore
            v.addLayout(line1)  # type: ignore
            line2 = QHBoxLayout()  # type: ignore
            self._spin_refresh = QSpinBox()  # type: ignore
            try: self._spin_refresh.setRange(100, 60_000)  # type: ignore
            except Exception: pass
            self._spin_playback = QDoubleSpinBox()  # type: ignore
            try:
                self._spin_playback.setRange(0.1, 10.0)  # type: ignore
                self._spin_playback.setSingleStep(0.1)  # type: ignore
            except Exception: pass
            try:
                self._spin_refresh.valueChanged.connect(self._on_refresh_changed)  # type: ignore[attr-defined]
                self._spin_playback.valueChanged.connect(self._on_playback_changed)  # type: ignore[attr-defined]
            except Exception: pass
            line2.addWidget(self._spin_refresh)  # type: ignore
            line2.addWidget(self._spin_playback)  # type: ignore
            v.addLayout(line2)  # type: ignore
            # Buttons
            btns = QHBoxLayout()  # type: ignore
            self._btn_apply = QPushButton('Apply')  # type: ignore
            self._btn_undo = QPushButton('Undo')  # type: ignore
            self._btn_redo = QPushButton('Redo')  # type: ignore
            try:
                self._btn_apply.clicked.connect(lambda: self.apply())  # type: ignore[attr-defined]
                self._btn_undo.clicked.connect(lambda: self.undo())  # type: ignore[attr-defined]
                self._btn_redo.clicked.connect(lambda: self.redo())  # type: ignore[attr-defined]
            except Exception: pass
            btns.addWidget(self._btn_apply)  # type: ignore
            btns.addWidget(self._btn_undo)  # type: ignore
            btns.addWidget(self._btn_redo)  # type: ignore
            v.addLayout(btns)  # type: ignore
            # recent label
            self._label_recent = QLabel('recent: -')  # type: ignore
            v.addWidget(self._label_recent)  # type: ignore
        except Exception:  # pragma: no cover
            pass
        self._root = root
        return root

    def _apply_view(self, view: Dict[str, Any]):  # noqa: D401
        s = view.get('settings', {}) if isinstance(view, dict) else {}
        recent = view.get('recent_changes') if isinstance(view, dict) else None
        # 若无 staging 才重置控件 (避免用户尚未 apply 时被覆盖)
        if not self._staged and isinstance(s, dict):
            lang = s.get('language'); theme = s.get('theme')
            ri = s.get('refresh_interval_ms'); spd = s.get('playback_speed')
            if self._combo_lang is not None and lang in ['zh_CN','en_US']:
                try:
                    idx = ['zh_CN','en_US'].index(lang)
                    self._combo_lang.setCurrentIndex(idx)  # type: ignore
                except Exception: pass
            if self._combo_theme is not None and theme in ['light','dark']:
                try:
                    idx = ['light','dark'].index(theme)
                    self._combo_theme.setCurrentIndex(idx)  # type: ignore
                except Exception: pass
            if self._spin_refresh is not None and isinstance(ri,int):
                try: self._spin_refresh.setValue(ri)  # type: ignore
                except Exception: pass
            if self._spin_playback is not None and isinstance(spd,(int,float)):
                try: self._spin_playback.setValue(float(spd))  # type: ignore
                except Exception: pass
        if self._label_recent is not None:
            try:
                self._label_recent.setText(f"recent: {recent!r}")  # type: ignore
            except Exception: pass

    # ---------------------- internal UI callbacks ----------------------
    def _on_lang_changed(self, *_):
        if self._combo_lang is None: return
        lang = self._combo_lang.currentText()  # type: ignore
        if lang: self.stage_language(lang)
    def _on_theme_changed(self, *_):
        if self._combo_theme is None: return
        th = self._combo_theme.currentText()  # type: ignore
        if th: self.stage_theme(th)
    def _on_refresh_changed(self, val):  # noqa: ANN001
        self.stage_refresh_interval(int(val))
    def _on_playback_changed(self, val):  # noqa: ANN001
        try: self.stage_playback_speed(float(val))
        except Exception: pass

__all__ = ["SettingsPanelAdapter"]

