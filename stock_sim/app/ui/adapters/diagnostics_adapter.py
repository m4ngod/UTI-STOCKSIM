"""Qt presentation adapter for the Diagnostics workspace."""

from __future__ import annotations

from typing import Any

from .base_adapter import PanelAdapter

try:
    from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget
except Exception:  # pragma: no cover - exercised only without Qt installed
    class QWidget:  # type: ignore[no-redef]
        pass

    class QLabel:  # type: ignore[no-redef]
        def __init__(self, text: str = "") -> None:
            self.text = text

        def setText(self, text: str) -> None:
            self.text = text

    class QLineEdit:  # type: ignore[no-redef]
        def __init__(self, text: str = "") -> None:
            self._text = text

        def setText(self, text: str) -> None:
            self._text = text

        def text(self) -> str:
            return self._text

        def setPlaceholderText(self, _: str) -> None:
            return None

    class _Signal:
        def __init__(self) -> None:
            self._callback: Any = None

        def connect(self, callback: Any) -> None:
            self._callback = callback

        def emit(self) -> None:
            if self._callback is not None:
                self._callback()

    class QPushButton:  # type: ignore[no-redef]
        def __init__(self, text: str = "") -> None:
            self.text = text
            self.clicked = _Signal()

        def click(self) -> None:
            self.clicked.emit()

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
        self._recommendation_label: Any = None
        self._market_input: Any = None
        self._start_date_input: Any = None
        self._end_date_input: Any = None
        self._intent_input: Any = None
        self._admit_button: Any = None
        self._recommend_button: Any = None
        self._action_error = ""

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
        self._market_input = QLineEdit("mainland-a-share")
        self._start_date_input = QLineEdit()
        self._start_date_input.setPlaceholderText("Start date (YYYY-MM-DD)")
        self._end_date_input = QLineEdit()
        self._end_date_input.setPlaceholderText("End date (YYYY-MM-DD)")
        self._admit_button = QPushButton("Inspect and admit segment")
        self._admit_button.clicked.connect(self._admit_from_inputs)
        self._intent_input = QLineEdit()
        self._intent_input.setPlaceholderText("What do you want to test?")
        self._recommend_button = QPushButton("Recommend admitted segments")
        self._recommend_button.clicked.connect(self._recommend_from_inputs)
        self._recommendation_label = QLabel("No recommendations yet")
        layout.addWidget(self._product_label)
        layout.addWidget(self._status_label)
        layout.addWidget(self._message_label)
        layout.addWidget(self._catalog_status_label)
        layout.addWidget(self._segment_label)
        layout.addWidget(self._provenance_label)
        layout.addWidget(self._admission_label)
        layout.addWidget(self._market_input)
        layout.addWidget(self._start_date_input)
        layout.addWidget(self._end_date_input)
        layout.addWidget(self._admit_button)
        layout.addWidget(self._intent_input)
        layout.addWidget(self._recommend_button)
        layout.addWidget(self._recommendation_label)
        return root

    def _admit_from_inputs(self) -> None:
        try:
            self._logic.admit_historical_segment(
                market=str(self._market_input.text()),
                start_date=str(self._start_date_input.text()),
                end_date=str(self._end_date_input.text()),
            )
            self._action_error = ""
        except ValueError:
            self._action_error = (
                "Enter a market and valid start/end dates in YYYY-MM-DD format."
            )
        except Exception:
            self._action_error = (
                "The segment inspection could not be completed. Check the local "
                "market data and try again."
            )
        self.refresh()

    def _recommend_from_inputs(self) -> None:
        try:
            self._logic.recommend_historical_segments(
                intent=str(self._intent_input.text()),
                limit=3,
            )
            self._action_error = ""
        except Exception:
            self._action_error = (
                "Recommendations could not be prepared. Admit a segment and try again."
            )
        self.refresh()

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
            if self._action_error:
                self._admission_label.setText(self._action_error)
        recommendations = catalog.get("recommendations", [])
        if self._recommendation_label is not None:
            if isinstance(recommendations, list) and recommendations:
                labels = []
                for item in recommendations[:3]:
                    if not isinstance(item, dict):
                        continue
                    segment = item.get("segment", {})
                    if isinstance(segment, dict):
                        labels.append(
                            f"{item.get('rank', '?')}. {segment.get('label', 'Admitted segment')}"
                        )
                self._recommendation_label.setText(" | ".join(labels))
            else:
                self._recommendation_label.setText("No recommendations yet")


__all__ = ["DiagnosticsPanelAdapter"]
