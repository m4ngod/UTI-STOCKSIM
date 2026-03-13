from __future__ import annotations
"""测试: 语言/主题变更触发 SettingsSync 向注册的 adapter.apply_settings 推送最新设置."""
from app.ui.settings_sync import SettingsSync
from app.ui.theme import ThemeManager
from app.ui.i18n_bind import I18nManager
from app.state.settings_store import SettingsStore

class DummyAdapter:
    def __init__(self):
        self.calls = []  # list[dict]
    def apply_settings(self, settings):  # noqa: D401
        self.calls.append(settings)

class DummyThemeManager(ThemeManager):  # 复用接口, 捕获调用
    def __init__(self):
        self.applied = []
    def apply_theme(self, theme: str):  # noqa: D401
        self.applied.append(theme)

class DummyI18n(I18nManager):  # 捕获 refresh
    def __init__(self):
        self.refreshed = 0
    def refresh(self):  # noqa: D401
        self.refreshed += 1


def test_settings_sync_adapter_receives_language_and_theme_updates(tmp_path):
    store_path = tmp_path / "settings.json"
    store = SettingsStore(path=str(store_path), auto_save=False)
    theme_mgr = DummyThemeManager()
    i18n_mgr = DummyI18n()
    sync = SettingsSync(theme_mgr, i18n_mgr)
    adapter = DummyAdapter()
    sync.register_adapter(adapter)  # 先注册 adapter (start 前)
    sync.start(store)

    # 启动时应推送一次 (初始 settings)
    assert len(adapter.calls) == 1
    first = adapter.calls[-1]
    assert first["language"] == store.get_state().language
    assert first["theme"] == store.get_state().theme

    # 改语言
    store.set_language("en_US")
    assert adapter.calls[-1]["language"] == "en_US"
    # 改主题
    store.set_theme("dark")
    assert adapter.calls[-1]["theme"] == "dark"

    # 再注册新 adapter (启动后) 应立即收到完整设置 (包含最新语言/主题)
    adapter2 = DummyAdapter()
    sync.register_adapter(adapter2)
    assert len(adapter2.calls) == 1
    latest = adapter2.calls[-1]
    assert latest["language"] == "en_US"
    assert latest["theme"] == "dark"

