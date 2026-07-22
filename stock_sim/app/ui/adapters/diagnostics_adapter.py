"""Qt presentation adapter for the Diagnostics workspace."""

from __future__ import annotations

import json
from typing import Any, Literal

from .base_adapter import PanelAdapter

try:
    from PySide6.QtWidgets import (
        QLabel,
        QLineEdit,
        QPlainTextEdit,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
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

    class QPlainTextEdit:  # type: ignore[no-redef]
        def __init__(self) -> None:
            self._text = ""

        def setReadOnly(self, _: bool) -> None:
            return None

        def setPlainText(self, text: str) -> None:
            self._text = text

        def toPlainText(self) -> str:
            return self._text

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
        self._transformation_catalog_label: Any = None
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
        self._recipe_draft_label: Any = None
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
        self._trend_direction_input: Any = None
        self._trend_strength_input: Any = None
        self._volatility_multiplier_input: Any = None
        self._shock_direction_input: Any = None
        self._gap_fraction_input: Any = None
        self._shock_fraction_input: Any = None
        self._shock_duration_input: Any = None
        self._persistence_duration_input: Any = None
        self._recovery_duration_input: Any = None
        self._breadth_target_input: Any = None
        self._dispersion_fraction_input: Any = None
        self._sector_concentration_input: Any = None
        self._volume_multiplier_input: Any = None
        self._cross_sectional_concentration_input: Any = None
        self._create_recipe_button: Any = None
        self._create_trend_recipe_button: Any = None
        self._create_volatility_recipe_button: Any = None
        self._create_shock_recovery_recipe_button: Any = None
        self._create_market_structure_recipe_button: Any = None
        self._create_liquidity_recipe_button: Any = None
        self._validate_recipe_button: Any = None
        self._approve_recipe_button: Any = None
        self._materialize_recipe_button: Any = None
        self._scenario_preview_label: Any = None
        self._run_status_label: Any = None
        self._run_equity_label: Any = None
        self._run_equity_curve_view: Any = None
        self._run_initial_cash_input: Any = None
        self._run_order_shares_input: Any = None
        self._run_replica_input: Any = None
        self._start_run_button: Any = None
        self._advance_run_button: Any = None
        self._pause_run_button: Any = None
        self._resume_run_button: Any = None
        self._complete_run_button: Any = None
        self._cancel_run_button: Any = None
        self._action_error = ""
        self._recipe_action_error = ""
        self._run_action_error = ""
        self._recipe_input_signature: tuple[str, ...] | None = None

    def current_view(self) -> dict[str, Any]:
        return dict(self._current_view)

    def _create_widget(self) -> Any:
        root = QWidget()
        layout = QVBoxLayout(root)
        self._product_label = QLabel("Strategy Diagnostics Laboratory")
        self._status_label = QLabel("Status: starting")
        self._message_label = QLabel("")
        self._catalog_status_label = QLabel("Historical segment: not checked")
        self._transformation_catalog_label = QLabel(
            "Transformation catalog: not loaded"
        )
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
        self._recipe_draft_label = QLabel("No reviewed draft")
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
        self._trend_direction_input = QLineEdit("bullish")
        self._trend_direction_input.setPlaceholderText("Trend direction")
        self._trend_strength_input = QLineEdit("0.5")
        self._trend_strength_input.setPlaceholderText("Trend strength (0 to 1)")
        self._volatility_multiplier_input = QLineEdit("1.5")
        self._volatility_multiplier_input.setPlaceholderText(
            "Volatility multiplier (0.5 to 2)"
        )
        self._shock_direction_input = QLineEdit("bearish")
        self._shock_direction_input.setPlaceholderText(
            "Shock direction (bearish or bullish)"
        )
        self._gap_fraction_input = QLineEdit("0.01")
        self._gap_fraction_input.setPlaceholderText(
            "Opening gap fraction (0 to 0.1)"
        )
        self._shock_fraction_input = QLineEdit("0.03")
        self._shock_fraction_input.setPlaceholderText(
            "Added shock fraction (0.01 to 0.2)"
        )
        self._shock_duration_input = QLineEdit("2")
        self._shock_duration_input.setPlaceholderText(
            "Shock duration in 5-minute bars"
        )
        self._persistence_duration_input = QLineEdit("1")
        self._persistence_duration_input.setPlaceholderText(
            "Persistence duration in 5-minute bars"
        )
        self._recovery_duration_input = QLineEdit("2")
        self._recovery_duration_input.setPlaceholderText(
            "Recovery duration in 5-minute bars"
        )
        self._breadth_target_input = QLineEdit("0.5")
        self._breadth_target_input.setPlaceholderText(
            "Target advancing breadth (0.1 to 0.9)"
        )
        self._dispersion_fraction_input = QLineEdit("0.04")
        self._dispersion_fraction_input.setPlaceholderText(
            "Target cross-sectional return spread (0.01 to 0.1)"
        )
        self._sector_concentration_input = QLineEdit("1")
        self._sector_concentration_input.setPlaceholderText(
            "Sector concentration (0 to 1)"
        )
        self._volume_multiplier_input = QLineEdit("0.5")
        self._volume_multiplier_input.setPlaceholderText(
            "Volume multiplier (0.25 to 2)"
        )
        self._cross_sectional_concentration_input = QLineEdit("1")
        self._cross_sectional_concentration_input.setPlaceholderText(
            "Cross-sectional liquidity concentration (0 to 1)"
        )
        self._create_recipe_button = QPushButton("Create manual baseline recipe")
        self._create_recipe_button.clicked.connect(self._create_recipe_from_inputs)
        self._create_trend_recipe_button = QPushButton(
            "Create trend/regime recipe"
        )
        self._create_trend_recipe_button.clicked.connect(
            self._create_trend_recipe_from_inputs
        )
        self._create_volatility_recipe_button = QPushButton(
            "Create volatility recipe"
        )
        self._create_volatility_recipe_button.clicked.connect(
            self._create_volatility_recipe_from_inputs
        )
        self._create_shock_recovery_recipe_button = QPushButton(
            "Create shock and recovery recipe"
        )
        self._create_shock_recovery_recipe_button.clicked.connect(
            self._create_shock_recovery_recipe_from_inputs
        )
        self._create_market_structure_recipe_button = QPushButton(
            "Create market structure recipe"
        )
        self._create_market_structure_recipe_button.clicked.connect(
            self._create_market_structure_recipe_from_inputs
        )
        self._create_liquidity_recipe_button = QPushButton(
            "Create liquidity stress recipe"
        )
        self._create_liquidity_recipe_button.clicked.connect(
            self._create_liquidity_recipe_from_inputs
        )
        self._validate_recipe_button = QPushButton("Validate recipe")
        self._validate_recipe_button.clicked.connect(self._validate_current_recipe)
        self._approve_recipe_button = QPushButton("Approve recipe explicitly")
        self._approve_recipe_button.clicked.connect(self._approve_current_recipe)
        self._materialize_recipe_button = QPushButton("Materialize recipe")
        self._materialize_recipe_button.clicked.connect(
            self._materialize_current_recipe
        )
        self._scenario_preview_label = QLabel(
            "Baseline vs transformed: materialize both recipes to compare"
        )
        self._run_status_label = QLabel("Baseline Strategy Run: not started")
        self._run_equity_label = QLabel("No private Portfolio Ledger yet")
        self._run_equity_curve_view = QPlainTextEdit()
        self._run_equity_curve_view.setReadOnly(True)
        self._run_equity_curve_view.setPlainText(
            "Equity curve: complete a baseline Strategy Run to inspect it."
        )
        self._run_initial_cash_input = QLineEdit("1000000")
        self._run_initial_cash_input.setPlaceholderText("Initial cash")
        self._run_order_shares_input = QLineEdit("100")
        self._run_order_shares_input.setPlaceholderText(
            "Reference strategy order shares"
        )
        self._run_replica_input = QLineEdit("baseline-replica-1")
        self._run_replica_input.setPlaceholderText("Scenario replica identity")
        self._start_run_button = QPushButton("Start baseline Strategy Run")
        self._start_run_button.clicked.connect(self._start_baseline_run_from_inputs)
        self._advance_run_button = QPushButton("Advance one Simulation Time node")
        self._advance_run_button.clicked.connect(self._advance_baseline_run)
        self._pause_run_button = QPushButton("Pause at node boundary")
        self._pause_run_button.clicked.connect(self._pause_baseline_run)
        self._resume_run_button = QPushButton("Resume baseline Strategy Run")
        self._resume_run_button.clicked.connect(self._resume_baseline_run)
        self._complete_run_button = QPushButton("Complete baseline Strategy Run")
        self._complete_run_button.clicked.connect(self._complete_baseline_run)
        self._cancel_run_button = QPushButton("Cancel at node boundary")
        self._cancel_run_button.clicked.connect(self._cancel_baseline_run)
        layout.addWidget(self._product_label)
        layout.addWidget(self._status_label)
        layout.addWidget(self._message_label)
        layout.addWidget(self._catalog_status_label)
        layout.addWidget(self._transformation_catalog_label)
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
        layout.addWidget(self._recipe_draft_label)
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
        layout.addWidget(self._trend_direction_input)
        layout.addWidget(self._trend_strength_input)
        layout.addWidget(self._volatility_multiplier_input)
        layout.addWidget(self._shock_direction_input)
        layout.addWidget(self._gap_fraction_input)
        layout.addWidget(self._shock_fraction_input)
        layout.addWidget(self._shock_duration_input)
        layout.addWidget(self._persistence_duration_input)
        layout.addWidget(self._recovery_duration_input)
        layout.addWidget(self._breadth_target_input)
        layout.addWidget(self._dispersion_fraction_input)
        layout.addWidget(self._sector_concentration_input)
        layout.addWidget(self._volume_multiplier_input)
        layout.addWidget(self._cross_sectional_concentration_input)
        layout.addWidget(self._create_recipe_button)
        layout.addWidget(self._create_trend_recipe_button)
        layout.addWidget(self._create_volatility_recipe_button)
        layout.addWidget(self._create_shock_recovery_recipe_button)
        layout.addWidget(self._create_market_structure_recipe_button)
        layout.addWidget(self._create_liquidity_recipe_button)
        layout.addWidget(self._validate_recipe_button)
        layout.addWidget(self._approve_recipe_button)
        layout.addWidget(self._materialize_recipe_button)
        layout.addWidget(self._scenario_preview_label)
        layout.addWidget(self._run_status_label)
        layout.addWidget(self._run_equity_label)
        layout.addWidget(self._run_equity_curve_view)
        layout.addWidget(self._run_initial_cash_input)
        layout.addWidget(self._run_order_shares_input)
        layout.addWidget(self._run_replica_input)
        layout.addWidget(self._start_run_button)
        layout.addWidget(self._advance_run_button)
        layout.addWidget(self._pause_run_button)
        layout.addWidget(self._resume_run_button)
        layout.addWidget(self._complete_run_button)
        layout.addWidget(self._cancel_run_button)
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
        self._submit_recipe_from_inputs(recipe_kind="baseline")

    def _create_trend_recipe_from_inputs(self) -> None:
        self._submit_recipe_from_inputs(recipe_kind="trend")

    def _create_volatility_recipe_from_inputs(self) -> None:
        self._submit_recipe_from_inputs(recipe_kind="volatility")

    def _create_shock_recovery_recipe_from_inputs(self) -> None:
        self._submit_recipe_from_inputs(recipe_kind="shock-recovery")

    def _create_market_structure_recipe_from_inputs(self) -> None:
        self._submit_recipe_from_inputs(recipe_kind="market-structure")

    def _create_liquidity_recipe_from_inputs(self) -> None:
        self._submit_recipe_from_inputs(recipe_kind="liquidity")

    def _submit_recipe_from_inputs(
        self,
        *,
        recipe_kind: Literal[
            "baseline",
            "trend",
            "volatility",
            "shock-recovery",
            "market-structure",
            "liquidity",
        ],
    ) -> None:
        try:
            segment_id = self._selected_recipe_segment_id()
            recipe_arguments = self._recipe_arguments(segment_id=segment_id)
            if recipe_kind == "trend":
                self._logic.create_trend_regime_recipe(
                    **recipe_arguments,
                    direction=str(self._trend_direction_input.text()),
                    strength=str(self._trend_strength_input.text()),
                )
            elif recipe_kind == "volatility":
                self._logic.create_volatility_recipe(
                    **recipe_arguments,
                    multiplier=str(self._volatility_multiplier_input.text()),
                )
            elif recipe_kind == "shock-recovery":
                self._logic.create_shock_recovery_recipe(
                    **recipe_arguments,
                    direction=str(self._shock_direction_input.text()),
                    gap_fraction=str(self._gap_fraction_input.text()),
                    shock_fraction=str(self._shock_fraction_input.text()),
                    shock_duration_bars=int(
                        str(self._shock_duration_input.text())
                    ),
                    persistence_duration_bars=int(
                        str(self._persistence_duration_input.text())
                    ),
                    recovery_duration_bars=int(
                        str(self._recovery_duration_input.text())
                    ),
                )
            elif recipe_kind == "market-structure":
                self._logic.create_market_structure_recipe(
                    **recipe_arguments,
                    breadth_target=str(self._breadth_target_input.text()),
                    dispersion_fraction=str(
                        self._dispersion_fraction_input.text()
                    ),
                    sector_concentration=str(
                        self._sector_concentration_input.text()
                    ),
                )
            elif recipe_kind == "liquidity":
                self._logic.create_liquidity_recipe(
                    **recipe_arguments,
                    volume_multiplier=str(self._volume_multiplier_input.text()),
                    cross_sectional_concentration=str(
                        self._cross_sectional_concentration_input.text()
                    ),
                )
            else:
                self._logic.create_baseline_recipe(**recipe_arguments)
            self._recipe_input_signature = self._recipe_authoring_signature(
                segment_id=segment_id
            )
            self._recipe_action_error = ""
        except (TypeError, ValueError):
            self._recipe_action_error = (
                "Check the recipe fields, transformation parameters, and admitted segment."
                if recipe_kind != "baseline"
                else "Check the recipe fields and select an admitted segment."
            )
        except Exception:
            labels = {
                "baseline": "recipe",
                "trend": "trend/regime",
                "volatility": "volatility",
                "shock-recovery": "shock and recovery",
                "market-structure": "market structure",
                "liquidity": "liquidity stress",
            }
            self._recipe_action_error = (
                f"The {labels[recipe_kind]} draft could not be created."
            )
        self.refresh()

    def _recipe_arguments(self, *, segment_id: str) -> dict[str, object]:
        partial_fills = str(self._partial_fills_input.text()).strip().lower()
        if partial_fills not in {"true", "false"}:
            raise ValueError("Partial fills must be true or false")
        return {
            "name": str(self._recipe_name_input.text()),
            "segment_id": segment_id,
            "author": str(self._recipe_author_input.text()),
            "cadence_minutes": int(str(self._cadence_input.text())),
            "seed": int(str(self._seed_input.text())),
            "commission_bps": str(self._commission_input.text()),
            "slippage_bps": str(self._slippage_input.text()),
            "max_fill_fraction": str(self._fill_fraction_input.text()),
            "latency_nodes": int(str(self._latency_input.text())),
            "allow_partial_fills": partial_fills == "true",
        }

    def _validate_current_recipe(self) -> None:
        try:
            self._assert_recipe_inputs_match_draft()
            self._logic.validate_current_recipe()
            self._recipe_action_error = ""
        except ValueError as error:
            self._recipe_action_error = self._recipe_input_error(
                error,
                fallback="Create a recipe draft before validation.",
            )
        except Exception:
            self._recipe_action_error = "Recipe validation could not be completed."
        self.refresh()

    def _approve_current_recipe(self) -> None:
        try:
            self._assert_recipe_inputs_match_draft()
            self._logic.approve_current_recipe(
                actor=str(self._recipe_actor_input.text())
            )
            self._recipe_action_error = ""
        except ValueError as error:
            self._recipe_action_error = self._recipe_input_error(
                error,
                fallback=(
                    "Approval requires a valid recipe and a named approval actor."
                ),
            )
        except Exception:
            self._recipe_action_error = "Recipe approval could not be completed."
        self.refresh()

    def _materialize_current_recipe(self) -> None:
        try:
            self._assert_recipe_inputs_match_draft()
            self._logic.materialize_current_recipe()
            self._recipe_action_error = ""
        except Exception:
            self._recipe_action_error = (
                "Only an approved recipe version can be materialized."
            )
        self.refresh()

    def _start_baseline_run_from_inputs(self) -> None:
        try:
            self._logic.start_baseline_run(
                initial_cash=str(self._run_initial_cash_input.text()).strip(),
                order_shares=int(str(self._run_order_shares_input.text()).strip()),
                replica_id=str(self._run_replica_input.text()).strip(),
            )
            self._run_action_error = ""
        except Exception as error:
            self._run_action_error = str(error) or "Unable to start baseline run."
        self.refresh()

    def _advance_baseline_run(self) -> None:
        self._apply_run_action(lambda: self._logic.advance_baseline_run(node_count=1))

    def _pause_baseline_run(self) -> None:
        self._apply_run_action(self._logic.pause_baseline_run)

    def _resume_baseline_run(self) -> None:
        self._apply_run_action(self._logic.resume_baseline_run)

    def _complete_baseline_run(self) -> None:
        self._apply_run_action(self._logic.complete_baseline_run)

    def _cancel_baseline_run(self) -> None:
        self._apply_run_action(self._logic.cancel_baseline_run)

    def _apply_run_action(self, action: Any) -> None:
        try:
            action()
            self._run_action_error = ""
        except Exception as error:
            self._run_action_error = str(error) or "Unable to control baseline run."
        self.refresh()

    def _selected_recipe_segment_id(self) -> str:
        segment_id = str(self._recipe_segment_input.text()).strip()
        if segment_id:
            return segment_id
        catalog = self._current_view.get("historical_segment_catalog", {})
        segments = catalog.get("segments", []) if isinstance(catalog, dict) else []
        latest = segments[-1] if isinstance(segments, list) and segments else {}
        if not isinstance(latest, dict) or not latest.get("segment_id"):
            raise ValueError("Admit a Historical Market Segment first")
        return str(latest["segment_id"])

    def _recipe_authoring_signature(
        self,
        *,
        segment_id: str | None = None,
    ) -> tuple[str, ...]:
        selected_segment = segment_id or self._selected_recipe_segment_id()
        return (
            str(self._recipe_name_input.text()),
            selected_segment,
            str(self._recipe_author_input.text()),
            str(self._cadence_input.text()),
            str(self._seed_input.text()),
            str(self._commission_input.text()),
            str(self._slippage_input.text()),
            str(self._fill_fraction_input.text()),
            str(self._latency_input.text()),
            str(self._partial_fills_input.text()).strip().lower(),
            str(self._trend_direction_input.text()).strip().lower(),
            str(self._trend_strength_input.text()).strip(),
            str(self._volatility_multiplier_input.text()).strip(),
            str(self._shock_direction_input.text()).strip().lower(),
            str(self._gap_fraction_input.text()).strip(),
            str(self._shock_fraction_input.text()).strip(),
            str(self._shock_duration_input.text()).strip(),
            str(self._persistence_duration_input.text()).strip(),
            str(self._recovery_duration_input.text()).strip(),
            str(self._breadth_target_input.text()).strip(),
            str(self._dispersion_fraction_input.text()).strip(),
            str(self._sector_concentration_input.text()).strip(),
            str(self._volume_multiplier_input.text()).strip(),
            str(self._cross_sectional_concentration_input.text()).strip(),
        )

    def _assert_recipe_inputs_match_draft(self) -> None:
        if (
            self._recipe_input_signature is None
            or self._recipe_authoring_signature() != self._recipe_input_signature
        ):
            raise ValueError(
                "Visible recipe fields changed; create a new draft before continuing."
            )

    @staticmethod
    def _recipe_input_error(error: ValueError, *, fallback: str) -> str:
        message = str(error)
        if "changed" in message:
            return message
        return fallback

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
        transformation_catalog = self._current_view.get(
            "transformation_catalog", {}
        )
        if not isinstance(transformation_catalog, dict):
            transformation_catalog = {}
        if self._transformation_catalog_label is not None:
            entries = transformation_catalog.get("transformations", [])
            identifiers = [
                str(item.get("transformation_id"))
                for item in entries
                if isinstance(item, dict) and item.get("transformation_id")
            ] if isinstance(entries, list) else []
            self._transformation_catalog_label.setText(
                "Transformation catalog: "
                + (", ".join(identifiers) if identifiers else "not loaded")
            )
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
        draft = workbench.get("draft")
        if self._recipe_draft_label is not None:
            if isinstance(draft, dict):
                payload = draft.get("payload", {})
                canonical = json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                self._recipe_draft_label.setText(
                    f"Draft hash: {draft.get('payload_hash', 'unknown')} | "
                    f"Reviewed payload: {canonical}"
                )
            else:
                self._recipe_draft_label.setText("No reviewed draft")
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
        strategy_run = self._current_view.get("baseline_strategy_run", {})
        if not isinstance(strategy_run, dict):
            strategy_run = {}
        if self._run_status_label is not None:
            run_status = str(strategy_run.get("status", "not_started"))
            current_time = strategy_run.get("current_simulation_time")
            progress = ""
            if strategy_run.get("total_node_count") is not None:
                progress = (
                    f" | nodes {strategy_run.get('processed_node_count', 0)}/"
                    f"{strategy_run.get('total_node_count', 0)}"
                )
            details = (
                f"Baseline Strategy Run: {run_status}{progress}"
                + (f" | Simulation Time {current_time}" if current_time else "")
            )
            failure = strategy_run.get("failure")
            if isinstance(failure, dict) and failure.get("message"):
                details += f" | failure: {failure['message']}"
            if self._run_action_error:
                details += f" | {self._run_action_error}"
            self._run_status_label.setText(details)
        if self._run_equity_label is not None:
            portfolio = strategy_run.get("portfolio", {})
            if not isinstance(portfolio, dict):
                portfolio = {}
            equity_curve = strategy_run.get("equity_curve", [])
            last_equity = (
                equity_curve[-1].get("equity", "not available")
                if isinstance(equity_curve, list)
                and equity_curve
                and isinstance(equity_curve[-1], dict)
                else "not available"
            )
            orders = strategy_run.get("orders", [])
            fills = strategy_run.get("fills", [])
            order_count = len(orders) if isinstance(orders, list) else 0
            fill_count = len(fills) if isinstance(fills, list) else 0
            self._run_equity_label.setText(
                "Private Portfolio Ledger | cash "
                f"{portfolio.get('cash', 'not available')} | equity {last_equity} | "
                f"orders {order_count} | fills {fill_count} | "
                "Reference Market Path prices and volumes remain immutable"
            )
        if self._run_equity_curve_view is not None:
            equity_curve = strategy_run.get("equity_curve", [])
            curve_lines = ["Simulation Time | Equity | Cash | Positions Value"]
            if isinstance(equity_curve, list):
                curve_lines.extend(
                    " | ".join(
                        (
                            str(point.get("simulation_time", "unknown")),
                            str(point.get("equity", "unknown")),
                            str(point.get("cash", "unknown")),
                            str(point.get("positions_value", "unknown")),
                        )
                    )
                    for point in equity_curve
                    if isinstance(point, dict)
                )
            if len(curve_lines) == 1:
                curve_lines.append("No equity points recorded yet")
            self._run_equity_curve_view.setPlainText("\n".join(curve_lines))
        comparison = self._current_view.get("scenario_comparison_preview", {})
        if not isinstance(comparison, dict):
            comparison = {}
        if self._scenario_preview_label is not None:
            if comparison.get("status") == "ready":
                baseline_preview = comparison.get("baseline", {})
                transformed_preview = comparison.get("transformed", {})
                if not isinstance(baseline_preview, dict):
                    baseline_preview = {}
                if not isinstance(transformed_preview, dict):
                    transformed_preview = {}
                baseline_market = baseline_preview.get("market_context", {})
                transformed_market = transformed_preview.get("market_context", {})
                if not isinstance(baseline_market, dict):
                    baseline_market = {}
                if not isinstance(transformed_market, dict):
                    transformed_market = {}
                rankings = transformed_preview.get("rankings", [])
                ranking_summary = ", ".join(
                    f"{item.get('rank', '?')}. {item.get('instrument', 'unknown')}"
                    for item in rankings
                    if isinstance(item, dict)
                ) if isinstance(rankings, list) else ""
                applied = transformed_preview.get("applied_transformations", [])
                transformation_summary = ", ".join(
                    (
                        f"{item.get('transformation_id', 'unknown')} ("
                        + ", ".join(
                            f"{name} {value}"
                            for name, value in parameters.items()
                        )
                        + ")"
                    )
                    for item in applied
                    if isinstance(item, dict)
                    and isinstance((parameters := item.get("parameters")), dict)
                ) if isinstance(applied, list) else ""
                phase_labels: list[str] = []
                effective_peak = ""
                market_structure_summary = ""
                liquidity_summary = ""
                if isinstance(applied, list):
                    for item in applied:
                        if not isinstance(item, dict):
                            continue
                        markers = item.get("phase_markers", [])
                        if isinstance(markers, list):
                            phase_labels.extend(
                                str(marker.get("phase", "unknown"))
                                for marker in markers
                                if isinstance(marker, dict)
                            )
                        statistics = item.get("statistics", {})
                        if isinstance(statistics, dict) and statistics.get(
                            "effective_peak_displacement_fraction"
                        ) is not None:
                            effective_peak = str(
                                statistics["effective_peak_displacement_fraction"]
                            )
                        parameters = item.get("parameters", {})
                        if (
                            item.get("transformation_id") == "market-structure.v1"
                            and isinstance(parameters, dict)
                            and isinstance(statistics, dict)
                        ):
                            market_structure_summary = (
                                " | market structure: requested breadth "
                                f"{parameters.get('breadth_target', 'unknown')}"
                                " | effective breadth "
                                f"{statistics.get('effective_final_breadth', 'unknown')}"
                                " | requested dispersion "
                                f"{parameters.get('dispersion_fraction', 'unknown')}"
                                " | effective spread "
                                f"{statistics.get('effective_final_return_spread_fraction', 'unknown')}"
                                " | requested sector concentration "
                                f"{parameters.get('sector_concentration', 'unknown')}"
                                " | effective sector winner concentration "
                                f"{statistics.get('effective_final_sector_winner_concentration', 'unknown')}"
                            )
                        if (
                            item.get("transformation_id") == "liquidity-stress.v1"
                            and isinstance(parameters, dict)
                            and isinstance(statistics, dict)
                        ):
                            liquidity_summary = (
                                " | liquidity: requested volume multiplier "
                                f"{parameters.get('volume_multiplier', 'unknown')}"
                                " | effective volume multiplier "
                                f"{statistics.get('effective_volume_multiplier', 'unknown')}"
                                " | requested concentration "
                                f"{parameters.get('cross_sectional_concentration', 'unknown')}"
                                " | effective top volume share "
                                f"{statistics.get('effective_top_volume_share', 'unknown')}"
                                " | market-path liquidity only; private execution "
                                "effects are not applied here"
                            )
                phase_summary = ""
                if phase_labels:
                    phase_summary = " | phases: " + " -> ".join(phase_labels)
                    if effective_peak:
                        phase_summary += f" | effective peak {effective_peak}"
                baseline_statistics = baseline_preview.get("path_statistics", {})
                transformed_statistics = transformed_preview.get(
                    "path_statistics", {}
                )
                if not isinstance(baseline_statistics, dict):
                    baseline_statistics = {}
                if not isinstance(transformed_statistics, dict):
                    transformed_statistics = {}
                reconstruction_notice = str(
                    transformed_preview.get(
                        "reconstruction_notice",
                        "Reconstructed path; not recorded microstructure.",
                    )
                )
                self._scenario_preview_label.setText(
                    "Baseline vs transformed | market return: "
                    f"{baseline_market.get('return', 'unknown')} -> "
                    f"{transformed_market.get('return', 'unknown')} | delta: "
                    f"{comparison.get('market_return_delta', 'unknown')} | ranking: "
                    f"{ranking_summary or 'not available'} | requested: "
                    f"{transformation_summary or 'not available'} | "
                    "mean |30s return|: "
                    f"{baseline_statistics.get('mean_absolute_return_30s', 'unknown')}"
                    " -> "
                    f"{transformed_statistics.get('mean_absolute_return_30s', 'unknown')}"
                    f"{phase_summary}{market_structure_summary}{liquidity_summary}"
                    " | provenance: "
                    f"{reconstruction_notice}"
                )
            else:
                self._scenario_preview_label.setText(
                    "Baseline vs transformed: materialize both recipes to compare"
                )


__all__ = ["DiagnosticsPanelAdapter"]
