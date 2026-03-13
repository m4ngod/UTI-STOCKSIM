from __future__ import annotations
from app.panels import replace_panel
from app.controllers.clock_controller import ClockController
from .panel import ClockPanel

__all__ = ["ClockPanel", "register_clock_panel"]

def register_clock_panel(controller: ClockController):
    replace_panel("clock", lambda: ClockPanel(controller), title="Clock", meta={"i18n_key": "panel.clock"})
