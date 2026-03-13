from __future__ import annotations
from app.panels import replace_panel
from app.controllers.leaderboard_controller import LeaderboardController
from .panel import LeaderboardPanel

__all__ = ["LeaderboardPanel", "register_leaderboard_panel"]

def register_leaderboard_panel(controller: LeaderboardController):
    replace_panel("leaderboard", lambda: LeaderboardPanel(controller), title="Leaderboard", meta={"i18n_key": "panel.leaderboard"})
