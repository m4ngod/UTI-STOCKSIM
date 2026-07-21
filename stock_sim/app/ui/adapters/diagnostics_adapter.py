"""Qt presentation adapter for the Diagnostics workspace."""

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
        self._current_view: dict[str, Any] = {}
        self._product_label: Any = None
        self._status_label: Any = None
        self._message_label: Any = None
        self._catalog_status_label: Any = None
        self._segment_label: Any = None
        self._provenance_label: Any = None
        self._admission_label: Any = None

    def current_view(self) -> dict[str, Any]:
        return dict(self._current_view)

    def _create_widget(self) -> Any:
        root = QWidget()
        layout = QVBoxLayout(root)
        self._product_label = QLabel("Strategy Diagnostics Laboratory")
        self._status_label = QLabel("Status: starting")
        self._message_label = QLabel("")
        self._catalog_status_label = QLabel("Historical segment: not checked")
        self._segment_label = QLabel("No admitted historical segment")
        self._provenance_label = QLabel("Source: not available")
        self._admission_label = QLabel("")
        layout.addWidget(self._product_label)
        layout.addWidget(self._status_label)
        layout.addWidget(self._message_label)
        layout.addWidget(self._catalog_status_label)
        layout.addWidget(self._segment_label)
        layout.addWidget(self._provenance_label)
        layout.addWidget(self._admission_label)
        return root

    def _apply_view(self, view: dict[str, Any]) -> None:
        self._current_view = dict(view)
        if self._product_label is not None:
            self._product_label.setText(
                str(self._current_view.get("product", "Diagnostics"))
            )
        if self._status_label is not None:
            self._status_label.setText(
                f"Status: {self._current_view.get('status', 'unknown')}"
            )
        if self._message_label is not None:
            self._message_label.setText(str(self._current_view.get("message", "")))
        catalog = self._current_view.get("historical_segment_catalog", {})
        if not isinstance(catalog, dict):
            catalog = {}
        if self._catalog_status_label is not None:
            self._catalog_status_label.setText(
                f"Historical segment: {catalog.get('status', 'not checked')}"
            )
        segments = catalog.get("segments", [])
        latest_segment = segments[-1] if isinstance(segments, list) and segments else {}
        if not isinstance(latest_segment, dict):
            latest_segment = {}
        if self._segment_label is not None:
            label = latest_segment.get("label", "No admitted historical segment")
            start = latest_segment.get("start_date")
            end = latest_segment.get("end_date")
            interval = f" ({start} to {end})" if start and end else ""
            self._segment_label.setText(f"{label}{interval}")
        provenance = latest_segment.get("provenance", {})
        if not isinstance(provenance, dict):
            provenance = {}
        if self._provenance_label is not None:
            provider = provenance.get("provider", "not available")
            dataset = provenance.get("dataset", "")
            version = provenance.get("version", "")
            details = " / ".join(
                str(value) for value in (provider, dataset, version) if value
            )
            self._provenance_label.setText(f"Source: {details}")
        latest_admission = catalog.get("latest_admission")
        if self._admission_label is not None:
            if isinstance(latest_admission, dict):
                reasons = latest_admission.get("failure_reasons", [])
                if isinstance(reasons, list) and reasons:
                    self._admission_label.setText("; ".join(map(str, reasons)))
                else:
                    self._admission_label.setText(
                        f"Admission: {latest_admission.get('status', 'unknown')}"
                    )
            else:
                self._admission_label.setText("")


__all__ = ["DiagnosticsPanelAdapter"]
