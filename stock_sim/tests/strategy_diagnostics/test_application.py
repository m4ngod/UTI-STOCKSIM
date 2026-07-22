from __future__ import annotations

from strategy_diagnostics import create_diagnostics_application


def test_headless_application_starts_the_diagnostics_workspace() -> None:
    application = create_diagnostics_application()

    state = application.start()

    assert state.to_dict() == {
        "product": "Strategy Diagnostics Laboratory",
        "workspace": "Diagnostics",
        "status": "ready",
        "message": "Diagnostics workspace is ready.",
        "persistence_status": "not_initialized",
        "persistence_revision": None,
        "supported_persistence_revision": "0004_ai_recipe_assistant",
    }
    assert application.status() == state
