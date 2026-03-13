from app.panels.settings.panel import SettingsPanel

class _MockState:
    def __init__(self):
        self.language = 'en_US'
        self.theme = 'light'
        self.refresh_interval_ms = 1000
        self.playback_speed = 1.0
        self.alert_thresholds = {'drawdown_pct': 0.1}
        self.high_contrast = False

class _MockSettingsController:
    def __init__(self):
        self._state = _MockState()
        self._cb_any = []
        self._cb_playback = []
        self.playback_updates = []  # 记录 set_playback_speed 被调用次数 (有效与否都记录)
    def get_state(self):
        return self._state
    # 回调注册
    def on_any(self, cb):
        self._cb_any.append(cb)
    def on_playback_speed(self, cb):
        self._cb_playback.append(cb)
    # 控制器接口
    def set_playback_speed(self, speed: float):
        # 控制器本身对值不做过滤 (仿真真实实现), 记录后再触发回调
        self.playback_updates.append(speed)
        changed = False
        if self._state.playback_speed != speed:
            self._state.playback_speed = speed
            changed = True
        if changed:
            payload = {
                'language': self._state.language,
                'theme': self._state.theme,
                'refresh_interval_ms': self._state.refresh_interval_ms,
                'playback_speed': self._state.playback_speed,
                'alert_thresholds': self._state.alert_thresholds,
                'high_contrast': self._state.high_contrast,
            }
            for cb in list(self._cb_playback):
                cb('playback_speed', speed, payload)
            for cb in list(self._cb_any):
                cb('playback_speed', speed, payload)
    # 供 SettingsPanel 使用的统一 update (最小实现)
    def update(self, **kwargs):
        if 'playback_speed' in kwargs:
            self.set_playback_speed(kwargs['playback_speed'])
    # 其它字段接口占位 (不被此测试使用)
    def set_language(self, lang: str): pass
    def set_theme(self, theme: str): pass
    def set_refresh_interval(self, ms: int): pass
    def update_alert_threshold(self, key: str, value): pass

class _MockClockPanel:
    def __init__(self):
        self.speeds = []
    def set_speed(self, speed: float):
        self.speeds.append(speed)


def test_settings_panel_playback_speed_valid_then_invalid_ignored():
    ctl = _MockSettingsController()
    panel = SettingsPanel(ctl, layout=None)
    # 注入 mock clock panel & 设置桥接完成标记，避免真正的 get_panel/wire 调用
    mock_clock = _MockClockPanel()
    panel._clock_panel_cached = mock_clock  # type: ignore
    panel._playback_speed_bridge_done = True  # type: ignore

    # 1) 设置有效速度 -> 应调用 clock.set_speed 一次
    panel.set_playback_speed(1.5)
    assert mock_clock.speeds == [1.5]
    # 控制器记录到一次更新
    assert ctl.playback_updates == [1.5]

    # 2) 设置无效速度 (0) -> SettingsPanel._on_playback_speed_change 里应被忽略, clock 不再调用
    panel.set_playback_speed(0)
    # 控制器仍然会记录尝试 (它本身不验证), 但 clock 不更新
    assert ctl.playback_updates == [1.5, 0]
    assert mock_clock.speeds == [1.5], '无效速度不应再次调用 clock.set_speed'

    # 3) 再次设置负值 -> 同样忽略
    panel.set_playback_speed(-2)
    assert ctl.playback_updates == [1.5, 0, -2]
    assert mock_clock.speeds == [1.5]

    # 4) 设置另一个有效值 -> 应再次调用 clock.set_speed
    panel.set_playback_speed(2.0)
    assert ctl.playback_updates[-1] == 2.0
    assert mock_clock.speeds == [1.5, 2.0]

    # 成功条件: 有效速度 (1.5, 2.0) 各调用一次; 无效 (0, -2) 被忽略 (未出现在 mock_clock.speeds)
    assert len(mock_clock.speeds) == 2
