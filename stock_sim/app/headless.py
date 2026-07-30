"""Headless frontend compatibility surface.

This module owns the minimal non-GUI frontend facade used by tests and
headless entry flows. It exists so ``app.main`` can keep shrinking toward a
thin compatibility wrapper without remaining the structural owner of headless
behavior.
"""
from __future__ import annotations

from typing import Any

from app.app_context import reset_app_context
from app.event_bridge import start_frontend_bridge
from app.runtime_bootstrap import start_runtime_support_services
from app.panels import register_builtin_panels, register_ui_adapters, get_panel, list_panels


class HeadlessMainWindow:
    """Minimal headless facade kept for legacy tests and entry flows."""

    def __init__(self):
        self.opened_panels: dict[str, Any] = {}

    def open_panel(self, name: str):
        inst = get_panel(name)
        self.opened_panels[name] = inst
        return inst

    def list_available(self):
        return list_panels()



def run_headless_frontend() -> HeadlessMainWindow:
    """Return a minimal frontend facade without starting GUI runtime paths.

    Headless mode still tries to register UI adapters so tests and entry flows can
    access logic-backed panels when those adapters can bind without a visible GUI.
    If adapter registration fails, the placeholder registry remains available as a
    safe fallback.
    """
    reset_app_context()
    start_frontend_bridge()
    start_runtime_support_services()
    register_builtin_panels()
    try:
        register_ui_adapters()
    except Exception:
        pass
    return HeadlessMainWindow()


__all__ = ["HeadlessMainWindow", "run_headless_frontend"]
