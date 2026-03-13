from __future__ import annotations
from app.panels import replace_panel
from app.controllers.agent_controller import AgentController
from app.services.agent_service import AgentService
from .panel import AgentsPanel

__all__ = ["AgentsPanel", "register_agents_panel"]

def register_agents_panel(controller: AgentController, service: AgentService, *, heartbeat_threshold_ms: int = 10_000):
    replace_panel("agents", lambda: AgentsPanel(controller, service, heartbeat_threshold_ms=heartbeat_threshold_ms), title="Agents", meta={"i18n_key": "panel.agents"})
