from __future__ import annotations
from typing import Optional
from .panel import AccountPanel
from app.controllers.account_controller import AccountController
from app.state.settings_store import SettingsStore
from app.panels import replace_panel

__all__ = ["AccountPanel", "register_account_panel"]

def register_account_panel(controller: AccountController, settings_store: Optional[SettingsStore] = None):
    """替换占位 account 面板为真实 AccountPanel 实例 (惰性)."""
    replace_panel("account", lambda: AccountPanel(controller, settings_store), meta={"i18n_key": "panel.account"}, title="Account")
