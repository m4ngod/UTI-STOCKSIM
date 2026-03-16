"""Legacy frontend entry wrapper.

This module intentionally stays thin.
Real window structure lives in :mod:`app.ui.main_window`; this file only keeps
historical import paths and the process entry helper alive while migration is in
progress.
"""
from __future__ import annotations

import atexit
import os
from typing import Any

try:
    from PySide6.QtCore import QTimer  # type: ignore
    from PySide6.QtWidgets import QApplication  # type: ignore
except Exception:  # pragma: no cover
    QApplication = None  # type: ignore
    QTimer = None  # type: ignore

from app.panels import register_builtin_panels, register_ui_adapters
from app.ui.main_window import MainWindow
from app.utils.metrics_adapter import flush_metrics

try:
    from app.ui.ui_refresh import register_main_window as _ui_register_main_window  # type: ignore
except Exception:  # pragma: no cover
    _ui_register_main_window = None  # type: ignore

__all__ = ["run_frontend", "MainWindow"]

_DEFAULT_PRELOAD = ["account", "market", "agents", "leaderboard", "clock", "orders"]


class HeadlessMainWindow:
    """Minimal headless facade kept for legacy tests and entry flows."""

    def __init__(self):
        self.opened_panels: dict[str, Any] = {}

    def open_panel(self, name: str):
        from app.panels import get_panel

        inst = get_panel(name)
        self.opened_panels[name] = inst
        return inst

    def list_available(self):
        from app.panels import list_panels

        return list_panels()


_periodic_timer = None


def _setup_periodic_metrics_flush(interval_ms: int = 5000):  # pragma: no cover
    global _periodic_timer
    if QApplication is None or QTimer is None:
        return
    _periodic_timer = QTimer()
    _periodic_timer.setInterval(interval_ms)
    _periodic_timer.timeout.connect(lambda: flush_metrics(reason="periodic"))  # type: ignore
    _periodic_timer.start()


@atexit.register
def _flush_on_exit():  # pragma: no cover
    try:
        flush_metrics(forced=True, reason="shutdown")
    except Exception:
        pass


def run_frontend(*, headless: bool = False) -> MainWindow | HeadlessMainWindow:
    """Start the frontend using the single real MainWindow implementation."""
    register_builtin_panels()
    try:
        register_ui_adapters()
    except Exception:
        pass
    flush_metrics(reason="startup")

    if headless or QApplication is None:
        return HeadlessMainWindow()

    app = QApplication.instance() or QApplication([])
    mw = MainWindow()
    try:
        if callable(_ui_register_main_window):
            _ui_register_main_window(mw)  # type: ignore
    except Exception:
        pass

    debug = os.environ.get("STOCKSIM_DEBUG_UI", "").lower() in ("1", "true", "yes", "on")
    for name in _DEFAULT_PRELOAD:
        try:
            mw.open_panel(name)
        except Exception:
            if debug:
                print(f"[DEBUG] preload failed: {name}")

    try:
        _setup_periodic_metrics_flush()
        mw.show()
        app.exec()
    except Exception:
        pass
    return mw
