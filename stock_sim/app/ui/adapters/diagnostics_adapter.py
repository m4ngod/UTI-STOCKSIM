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
        self._recipe_status_label: Any = None
        self._recipe_feedback_label: Any = None
        self._recipe_approval_label: Any = None
        self._recipe_materialization_label: Any = None
        self._recipe_name_input: Any = None
        self._recipe_segment_input: Any = None
        self._recipe_author_input: Any = None
        self._recipe_actor_input: Any = None
        self._cadence_input: Any = None
        self._seed_input: Any = None
        self._commission_input: Any = None
        self._slippage_input: Any = None
        self._fill_fraction_input: Any = None
        self._latency_input: Any = None
        self._partial_fills_input: Any = None
        self._create_recipe_button: Any = None
        self._validate_recipe_button: Any = None
        self._approve_recipe_button: Any = None
        self._materialize_recipe_button: Any = None
        self._action_error = ""
        self._recipe_action_error = ""

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
        self._recipe_status_label = QLabel("Scenario recipe: not started")
        self._recipe_feedback_label = QLabel("No validation feedback yet")
        self._recipe_approval_label = QLabel("Not approved")
        self._recipe_materialization_label = QLabel("Not materialized")
        self._recipe_name_input = QLineEdit("Baseline control")
        self._recipe_segment_input = QLineEdit()
        self._recipe_segment_input.setPlaceholderText(
            "Admitted segment ID (blank uses latest)"
        )
        self._recipe_author_input = QLineEdit()
        self._recipe_author_input.setPlaceholderText("Recipe author")
        self._recipe_actor_input = QLineEdit()
        self._recipe_actor_input.setPlaceholderText("Approval actor")
        self._cadence_input = QLineEdit("30")
        self._seed_input = QLineEdit("0")
        self._commission_input = QLineEdit("3")
        self._slippage_input = QLineEdit("0")
        self._fill_fraction_input = QLineEdit("1")
        self._latency_input = QLineEdit("0")
        self._partial_fills_input = QLineEdit("true")
        self._create_recipe_button = QPushButton("Create manual baseline recipe")
        self._create_recipe_button.clicked.connect(self._create_recipe_from_inputs)
        self._validate_recipe_button = QPushButton("Validate recipe")
        self._validate_recipe_button.clicked.connect(self._validate_current_recipe)
        self._approve_recipe_button = QPushButton("Approve recipe explicitly")
        self._approve_recipe_button.clicked.connect(self._approve_current_recipe)
        self._materialize_recipe_button = QPushButton("Materialize baseline")
        self._materialize_recipe_button.clicked.connect(
            self._materialize_current_recipe
        )
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
        layout.addWidget(self._recipe_status_label)
        layout.addWidget(self._recipe_feedback_label)
        layout.addWidget(self._recipe_approval_label)
        layout.addWidget(self._recipe_materialization_label)
        layout.addWidget(self._recipe_name_input)
        layout.addWidget(self._recipe_segment_input)
        layout.addWidget(self._recipe_author_input)
        layout.addWidget(self._recipe_actor_input)
        layout.addWidget(self._cadence_input)
        layout.addWidget(self._seed_input)
        layout.addWidget(self._commission_input)
        layout.addWidget(self._slippage_input)
        layout.addWidget(self._fill_fraction_input)
        layout.addWidget(self._latency_input)
        layout.addWidget(self._partial_fills_input)
        layout.addWidget(self._create_recipe_button)
        layout.addWidget(self._validate_recipe_button)
        layout.addWidget(self._approve_recipe_button)
        layout.addWidget(self._materialize_recipe_button)
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

    def _create_recipe_from_inputs(self) -> None:
        try:
            segment_id = str(self._recipe_segment_input.text()).strip()
            if not segment_id:
                catalog = self._current_view.get("historical_segment_catalog", {})
                segments = catalog.get("segments", []) if isinstance(catalog, dict) else []
                latest = segments[-1] if isinstance(segments, list) and segments else {}
                if not isinstance(latest, dict) or not latest.get("segment_id"):
                    raise ValueError("Admit a Historical Market Segment first")
                segment_id = str(latest["segment_id"])
            partial_fills = str(self._partial_fills_input.text()).strip().lower()
            if partial_fills not in {"true", "false"}:
                raise ValueError("Partial fills must be true or false")
            self._logic.create_baseline_recipe(
                name=str(self._recipe_name_input.text()),
                segment_id=segment_id,
                author=str(self._recipe_author_input.text()),
                cadence_minutes=int(str(self._cadence_input.text())),
                seed=int(str(self._seed_input.text())),
                commission_bps=str(self._commission_input.text()),
                slippage_bps=str(self._slippage_input.text()),
                max_fill_fraction=str(self._fill_fraction_input.text()),
                latency_nodes=int(str(self._latency_input.text())),
                allow_partial_fills=partial_fills == "true",
            )
            self._recipe_action_error = ""
        except (TypeError, ValueError):
            self._recipe_action_error = (
                "Check the recipe fields and select an admitted segment."
            )
        except Exception:
            self._recipe_action_error = "The recipe draft could not be created."
        self.refresh()

    def _validate_current_recipe(self) -> None:
        try:
            self._logic.validate_current_recipe()
            self._recipe_action_error = ""
        except Exception:
            self._recipe_action_error = "Create a recipe draft before validation."
        self.refresh()

    def _approve_current_recipe(self) -> None:
        try:
            self._logic.approve_current_recipe(
                actor=str(self._recipe_actor_input.text())
            )
            self._recipe_action_error = ""
        except Exception:
            self._recipe_action_error = (
                "Approval requires a valid recipe and a named approval actor."
            )
        self.refresh()

    def _materialize_current_recipe(self) -> None:
        try:
            self._logic.materialize_current_recipe()
            self._recipe_action_error = ""
        except Exception:
            self._recipe_action_error = (
                "Only an approved recipe version can be materialized."
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
        workbench = self._current_view.get("scenario_recipe_workbench", {})
        if not isinstance(workbench, dict):
            workbench = {}
        if self._recipe_status_label is not None:
            self._recipe_status_label.setText(
                f"Scenario recipe: {workbench.get('status', 'not started')}"
            )
        validation = workbench.get("validation")
        if self._recipe_feedback_label is not None:
            feedback = "No validation feedback yet"
            if isinstance(validation, dict):
                issues = validation.get("issues", [])
                if isinstance(issues, list) and issues:
                    feedback = "; ".join(
                        str(item.get("correction", item.get("message", "Invalid field")))
                        for item in issues
                        if isinstance(item, dict)
                    )
                elif validation.get("is_valid") is True:
                    feedback = "Validation passed"
            if self._recipe_action_error:
                feedback = self._recipe_action_error
            self._recipe_feedback_label.setText(feedback)
        approved = workbench.get("approved_version")
        if self._recipe_approval_label is not None:
            if isinstance(approved, dict):
                self._recipe_approval_label.setText(
                    "Approved by "
                    f"{approved.get('approval_actor', 'unknown')} at "
                    f"{approved.get('approved_at', 'unknown')}"
                )
            else:
                self._recipe_approval_label.setText("Not approved")
        materialization = workbench.get("materialization")
        if self._recipe_materialization_label is not None:
            if isinstance(materialization, dict):
                self._recipe_materialization_label.setText(
                    f"Materialized: {materialization.get('artifact_hash', 'unknown')}"
                )
            else:
                self._recipe_materialization_label.setText("Not materialized")


__all__ = ["DiagnosticsPanelAdapter"]
