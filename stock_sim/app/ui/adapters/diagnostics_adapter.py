"""Qt presentation adapter for the empty Diagnostics workspace."""

from __future__ import annotations

from typing import Any

from .base_adapter import PanelAdapter

try:
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
except Exception:  # pragma: no cover - exercised only without Qt installed
    class QWidget:  # type: ignore[no-redef]
        pass

    class QLabel:  # type: ignore[no-redef]
        def __init__(self, text: str = "") -> None:
            self.text = text

        def setText(self, text: str) -> None:
            self.text = text

    class QVBoxLayout:  # type: ignore[no-redef]
        def __init__(self, *_: object) -> None:
            self.widgets: list[object] = []

        def addWidget(self, widget: object) -> None:
            self.widgets.append(widget)


class DiagnosticsPanelAdapter(PanelAdapter):  # type: ignore[misc]
    def __init__(self) -> None:
        super().__init__()
        self._current_view: dict[str, str] = {}
        self._product_label: Any = None
        self._status_label: Any = None
        self._message_label: Any = None

    def current_view(self) -> dict[str, str]:
        return dict(self._current_view)

    def _create_widget(self) -> Any:
        root = QWidget()
        layout = QVBoxLayout(root)
        self._product_label = QLabel("Strategy Diagnostics Laboratory")
        self._status_label = QLabel("Status: starting")
        self._message_label = QLabel("")
        layout.addWidget(self._product_label)
        layout.addWidget(self._status_label)
        layout.addWidget(self._message_label)
        return root

    def _apply_view(self, view: dict[str, Any]) -> None:
        self._current_view = {str(key): str(value) for key, value in view.items()}
        if self._product_label is not None:
            self._product_label.setText(self._current_view.get("product", "Diagnostics"))
        if self._status_label is not None:
            self._status_label.setText(
                f"Status: {self._current_view.get('status', 'unknown')}"
            )
        if self._message_label is not None:
            self._message_label.setText(self._current_view.get("message", ""))


__all__ = ["DiagnosticsPanelAdapter"]
