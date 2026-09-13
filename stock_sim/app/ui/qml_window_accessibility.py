"""Expose QML focus through the retained QWidget product window's accessible root."""
from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtGui import QAccessible, QAccessibleInterface
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QAccessibleWidget, QMainWindow


class _QmlWindowAccessible(QAccessibleWidget):
    """Keep Qt's widget tree/actions; only bridge the embedded QML focus leaf."""

    # Qt permits a null focus child; PySide6 6.9's stub omits that nullability.
    def focusChild(self) -> QAccessibleInterface | None:  # type: ignore[override]
        window = self.object()
        if isinstance(window, QMainWindow):
            focused_widget = window.focusWidget()
            if isinstance(focused_widget, QQuickWidget) and focused_widget.hasFocus():
                item = focused_widget.quickWindow().activeFocusItem()
                if item is not None:
                    interface = QAccessible.queryAccessibleInterface(item)
                    if interface is not None and interface.isValid():
                        # PySide exposes State's C++ bitfields but omits their stubs.
                        if interface.state().focused:  # type: ignore[attr-defined]
                            return interface
        return super().focusChild()


def _factory(_class_name: str, obj: QObject) -> QAccessibleInterface | None:
    if isinstance(obj, QMainWindow) and obj.property("stockSimQmlWindow") is True:
        return _QmlWindowAccessible(obj, QAccessible.Role.Window)
    return None


_installed = False


def enable_qml_window_accessibility(window: QMainWindow) -> None:
    """Opt in only the product QML window; do not replace the QQuickWidget tree."""
    global _installed
    window.setProperty("stockSimQmlWindow", True)
    if not _installed:
        QAccessible.installFactory(_factory)
        _installed = True
