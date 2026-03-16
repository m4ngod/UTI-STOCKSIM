"""Unified frontend entry.

This module exposes the historical ``app.main`` surface while delegating all
real window structure to :mod:`app.ui.main_window`.

The goal is to keep only one true MainWindow implementation. Compatibility
shims that old tests still touch live here, but layout/menu/docking behavior is
owned by ``app.ui.main_window.MainWindow``.
"""
from __future__ import annotations

import atexit
import os
from typing import Any, Dict, List

try:
    from PySide6.QtCore import QTimer  # type: ignore
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget  # type: ignore
except Exception:  # pragma: no cover
    QApplication = None  # type: ignore
    QLabel = None  # type: ignore
    QTimer = None  # type: ignore
    QVBoxLayout = None  # type: ignore
    QWidget = None  # type: ignore

from app.panels import list_panels, register_builtin_panels, register_ui_adapters
from app.ui.main_window import MainWindow as _UiMainWindow
from app.utils.metrics_adapter import flush_metrics

try:
    from app.ui.ui_refresh import register_main_window as _ui_register_main_window  # type: ignore
except Exception:  # pragma: no cover
    _ui_register_main_window = None  # type: ignore

__all__ = ["run_frontend", "MainWindow"]

_DEFAULT_PRELOAD = ["account", "market", "agents", "leaderboard", "clock", "orders"]


class MainWindow(_UiMainWindow):
    """Compatibility shell over the real UI MainWindow.

    ``app.ui.main_window.MainWindow`` remains the single structural authority.
    This subclass only backfills a few legacy attributes/methods that older
    tests still inspect directly.
    """

    def __init__(self):
        super().__init__()
        self.opened_panels: Dict[str, Any] = {}
        self._panel_widgets: Dict[str, Any] = {}
        self._central: Any = None
        self._layout: Any = None
        self._tabs = None

    def _ensure_central_layout(self):
        """Provide a legacy central layout for old widget-mount tests.

        The actual application uses dock widgets via ``DockManager``. This
        compatibility layout is only populated for tests that inspect
        ``_layout.count()`` / ``_panel_widgets`` directly.
        """
        if self._central is not None and self._layout is not None:
            return self._layout
        layout = None
        if hasattr(super(), "ensure_legacy_central_layout"):
            try:
                layout = super().ensure_legacy_central_layout()  # type: ignore[misc]
            except Exception:
                layout = None
        self._central = getattr(self, "_legacy_central", None)
        self._layout = layout if layout is not None else getattr(self, "_legacy_layout", None)
        return self._layout

    def _coerce_legacy_widget(self, name: str, obj: Any) -> Any:
        real_widget = getattr(obj, "widget", None)
        if callable(real_widget):
            try:
                widget = real_widget()
                if widget is not None:
                    return widget
            except Exception:
                pass
        if QWidget is not None and isinstance(obj, QWidget):  # type: ignore[arg-type]
            return obj
        text = f"Placeholder panel: {name}"
        if QLabel is not None:
            try:
                return QLabel(text)
            except Exception:
                pass
        return obj

    def open_panel(self, name: str):  # type: ignore[override]
        obj = super().open_panel(name)
        if obj is None:
            return None
        self.opened_panels[name] = obj
        if getattr(obj, "name", None) is None:
            try:
                setattr(obj, "name", name)
            except Exception:
                pass

        widget = self._coerce_legacy_widget(name, obj)
        existing = self._panel_widgets.get(name)
        if existing is None:
            self._panel_widgets[name] = widget
            layout = self._ensure_central_layout()
            if layout is not None and widget is not None and hasattr(layout, "addWidget"):
                try:
                    layout.addWidget(widget)
                except Exception:
                    pass
        return obj

    def list_available(self) -> List[dict]:
        return list_panels()


class HeadlessMainWindow:
    def __init__(self):
        self.opened_panels: Dict[str, Any] = {}

    def open_panel(self, name: str):
        from app.panels import get_panel

        inst = get_panel(name)
        self.opened_panels[name] = inst
        if getattr(inst, "name", None) is None:
            try:
                setattr(inst, "name", name)
            except Exception:
                pass
        return inst

    def list_available(self) -> List[dict]:
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
    register_builtin_panels()
    try:
        register_ui_adapters()
    except Exception:
        pass
    flush_metrics(reason="startup")
    debug = os.environ.get("STOCKSIM_DEBUG_UI", "").lower() in ("1", "true", "yes", "on")
    if headless or QApplication is None:
        if debug:
            try:
                available = [p.get("name") for p in list_panels()]
                print(f"[DEBUG] headless available={available}")
            except Exception:
                pass
        return HeadlessMainWindow()

    app = QApplication.instance() or QApplication([])
    mw = MainWindow()
    try:
        if callable(_ui_register_main_window):
            _ui_register_main_window(mw)  # type: ignore
    except Exception:
        pass

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
