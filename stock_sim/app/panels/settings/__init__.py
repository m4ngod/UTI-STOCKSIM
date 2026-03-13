from __future__ import annotations
from app.panels import replace_panel
from app.controllers.settings_controller import SettingsController
from app.state.layout_persistence import LayoutPersistence
from .panel import SettingsPanel

__all__ = ["SettingsPanel", "register_settings_panel"]

def register_settings_panel(controller: SettingsController, layout: LayoutPersistence | None = None):
    # 使用闭包捕获 layout
    replace_panel("settings", lambda: SettingsPanel(controller, layout=layout), title="Settings", meta={"i18n_key": "panel.settings"})
