"""Headless logic panel for the Diagnostics workspace."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Mapping, Protocol

from strategy_diagnostics import HistoricalSegmentSelection


class _DiagnosticsState(Protocol):
    def to_dict(self) -> dict[str, object]: ...


class _MaterializedMarketPath(Protocol):
    def to_preview_dict(self) -> dict[str, object]: ...


class _StrategyRunSnapshot(Protocol):
    def to_dict(self) -> dict[str, object]: ...


class _SensitivityCampaignCase(Protocol):
    @property
    def case_id(self) -> str: ...

    def to_dict(self) -> dict[str, object]: ...


class _DiagnosticCampaignCase(_SensitivityCampaignCase, Protocol):
    @property
    def layer(self) -> str: ...


class DiagnosticsApplicationPort(Protocol):
    def start(self) -> _DiagnosticsState: ...

    def status(self) -> _DiagnosticsState: ...

    def historical_segment_catalog_view(self) -> dict[str, object]: ...

    def transformation_catalog_view(self) -> dict[str, object]: ...

    def admit_historical_segment(
        self, selection: HistoricalSegmentSelection
    ) -> _DiagnosticsState: ...

    def recommend_historical_segments(
        self,
        intent: str = "",
        limit: int = 3,
    ) -> tuple[_DiagnosticsState, ...]: ...

    def create_manual_recipe_draft(
        self,
        payload: Mapping[str, object],
        *,
        author: str,
    ) -> _DiagnosticsState: ...

    def validate_recipe_draft(self, draft_id: str) -> _DiagnosticsState: ...

    def approve_recipe_draft(
        self,
        draft_id: str,
        *,
        actor: str,
    ) -> _DiagnosticsState: ...

    def revise_recipe_version(
        self,
        version_id: str,
        payload: Mapping[str, object],
        *,
        author: str,
    ) -> _DiagnosticsState: ...

    def materialize_reference_path(
        self,
        recipe_version_id: str,
    ) -> _MaterializedMarketPath: ...

    def compare_reference_market_paths(
        self,
        baseline_artifact_hash: str,
        transformed_artifact_hash: str,
        *,
        at_time: datetime,
    ) -> dict[str, object]: ...

    def start_baseline_strategy_run(
        self,
        recipe_version_id: str,
        materialization_hash: str,
        *,
        initial_cash: Decimal,
        order_shares: int,
        replica_id: str,
        strategy_id: str = "anchored-ranked-candidate-reference",
        strategy_version: str = "anchored-ranked-candidate-reference.v1",
    ) -> _StrategyRunSnapshot: ...

    def run_baseline_campaign(
        self,
        recipe_version_id: str,
        materialization_hash: str,
        *,
        initial_cash: Decimal,
        order_shares: int,
        campaign_replica_id: str,
        nodes_per_batch: int = 10_000,
    ) -> _StrategyRunSnapshot: ...

    def create_isolated_sensitivity_case(
        self,
        recipe_version_id: str,
        materialization_hash: str,
    ) -> _SensitivityCampaignCase: ...

    def plan_isolated_sensitivity_set(
        self,
        case_anchors: tuple[tuple[str, str], ...],
        *,
        initial_cash: Decimal,
        order_shares: int,
        sensitivity_set_replica_id: str,
    ) -> _StrategyRunSnapshot: ...

    def advance_isolated_sensitivity_set(
        self,
        sensitivity_set_id: str,
        *,
        max_cases: int = 1,
        nodes_per_batch: int = 10_000,
    ) -> _StrategyRunSnapshot: ...

    def resume_isolated_sensitivity_set(
        self,
        sensitivity_set_id: str,
        *,
        max_cases: int | None = None,
        nodes_per_batch: int = 10_000,
    ) -> _StrategyRunSnapshot: ...

    def retry_isolated_sensitivity_case(
        self,
        sensitivity_set_id: str,
        case_id: str,
        *,
        nodes_per_batch: int = 10_000,
    ) -> _StrategyRunSnapshot: ...

    def create_diagnostic_campaign_case(
        self,
        recipe_version_id: str,
        materialization_hash: str,
    ) -> _DiagnosticCampaignCase: ...

    def plan_diagnostic_campaign(
        self,
        *,
        baseline_anchor: tuple[str, str] | None,
        isolated_sensitivity_set_id: str | None,
        compound_case_anchors: tuple[tuple[str, str], ...],
        initial_cash: Decimal,
        order_shares: int,
        campaign_replica_id: str,
    ) -> _StrategyRunSnapshot: ...

    def advance_diagnostic_campaign(
        self,
        campaign_id: str,
        *,
        max_cases: int = 1,
        nodes_per_batch: int = 10_000,
    ) -> _StrategyRunSnapshot: ...

    def resume_diagnostic_campaign(
        self,
        campaign_id: str,
        *,
        max_cases: int | None = None,
        nodes_per_batch: int = 10_000,
    ) -> _StrategyRunSnapshot: ...

    def retry_diagnostic_campaign_case(
        self,
        campaign_id: str,
        case_id: str,
        *,
        nodes_per_batch: int = 10_000,
    ) -> _StrategyRunSnapshot: ...

    def build_diagnostic_evidence(
        self,
        campaign_id: str,
    ) -> _StrategyRunSnapshot: ...

    def diagnostic_evidence_status(
        self,
        evidence_package_id: str,
    ) -> _StrategyRunSnapshot: ...

    def explain_diagnostic_findings(
        self,
        evidence_package_id: str,
    ) -> _StrategyRunSnapshot: ...

    def strategy_run_status(self, run_id: str) -> _StrategyRunSnapshot: ...

    def advance_strategy_run(
        self,
        run_id: str,
        *,
        node_count: int = 1,
    ) -> _StrategyRunSnapshot: ...

    def complete_strategy_run(
        self,
        run_id: str,
        *,
        nodes_per_batch: int = 10_000,
    ) -> _StrategyRunSnapshot: ...

    def pause_strategy_run(self, run_id: str) -> _StrategyRunSnapshot: ...

    def resume_strategy_run(self, run_id: str) -> _StrategyRunSnapshot: ...

    def cancel_strategy_run(self, run_id: str) -> _StrategyRunSnapshot: ...


class DiagnosticsPanel:
    def __init__(self, application: DiagnosticsApplicationPort) -> None:
        self._application = application
        self._recommendations: list[dict[str, object]] = []
        self._recipe_workbench: dict[str, object] = {
            "status": "not_started",
            "draft": None,
            "validation": None,
            "approved_version": None,
            "materialization": None,
        }
        self._materializations: dict[str, dict[str, object] | None] = {
            "baseline": None,
            "transformed": None,
        }
        self._scenario_comparison_preview: dict[str, object] = {
            "status": "not_ready",
            "message": "Materialize a baseline and transformed recipe to compare them.",
        }
        self._baseline_strategy_run: dict[str, object] = {
            "status": "not_started",
            "message": "Materialize an approved anchored recipe to start a run.",
        }
        self._baseline_campaign: dict[str, object] = {
            "status": "not_started",
            "message": (
                "Materialize an approved anchored recipe to compare both strategies."
            ),
        }
        self._baseline_campaign_anchor: tuple[str, str] | None = None
        self._sensitivity_case_anchors: list[tuple[str, str]] = []
        self._sensitivity_case_views: list[dict[str, object]] = []
        self._isolated_sensitivity_set: dict[str, object] = {
            "status": "not_planned",
            "message": (
                "Stage approved single-family materializations before planning."
            ),
            "sensitivity_curves": [],
        }
        self._compound_case_anchors: list[tuple[str, str]] = []
        self._compound_case_views: list[dict[str, object]] = []
        self._diagnostic_campaign: dict[str, object] = {
            "status": "not_planned",
            "campaign_type": "quick_experiment",
            "formal_attribution": {
                "eligible": False,
                "claim_status": "not_permitted",
                "missing_layers": [
                    "baseline",
                    "isolated_sensitivity",
                    "compound",
                ],
            },
            "progress": {
                "completed_count": 0,
                "incomplete_count": 0,
                "pending_count": 0,
                "total_count": 0,
            },
            "layers": {},
            "failures": [],
            "compound_case_outcomes": [],
        }
        self._diagnostic_evidence: dict[str, object] = {
            "status": "not_built",
            "message": (
                "Complete a Formal Diagnostic Campaign to seal evidence."
            ),
            "metrics": [],
            "comparisons": [],
            "guardrail_breaches": [],
            "sensitivity_breakpoints": [],
            "diagnostic_findings": [],
        }
        self._diagnostic_explanations: dict[str, object] = {
            "status": "not_requested",
            "message": (
                "Optional explanations can reference sealed findings only."
            ),
            "explanations": [],
        }
        self._application.start()

    def get_view(self) -> dict[str, object]:
        view = self._application.status().to_dict()
        catalog = dict(self._application.historical_segment_catalog_view())
        catalog["recommendations"] = list(self._recommendations)
        view["historical_segment_catalog"] = catalog
        view["transformation_catalog"] = dict(
            self._application.transformation_catalog_view()
        )
        view["scenario_recipe_workbench"] = dict(self._recipe_workbench)
        view["scenario_comparison_preview"] = dict(
            self._scenario_comparison_preview
        )
        view["baseline_strategy_run"] = dict(self._baseline_strategy_run)
        view["baseline_campaign"] = dict(self._baseline_campaign)
        view["isolated_sensitivity_case_staging"] = {
            "case_count": len(self._sensitivity_case_views),
            "cases": [dict(case) for case in self._sensitivity_case_views],
        }
        view["isolated_sensitivity_set"] = dict(
            self._isolated_sensitivity_set
        )
        view["compound_campaign_case_staging"] = {
            "case_count": len(self._compound_case_views),
            "cases": [dict(case) for case in self._compound_case_views],
        }
        view["diagnostic_campaign"] = dict(self._diagnostic_campaign)
        view["diagnostic_evidence"] = dict(self._diagnostic_evidence)
        view["diagnostic_finding_explanations"] = dict(
            self._diagnostic_explanations
        )
        return view

    def admit_historical_segment(
        self,
        *,
        market: str,
        start_date: str,
        end_date: str,
    ) -> dict[str, object]:
        report = self._application.admit_historical_segment(
            HistoricalSegmentSelection(
                market=market,
                start_date=date.fromisoformat(start_date),
                end_date=date.fromisoformat(end_date),
            )
        )
        return report.to_dict()

    def recommend_historical_segments(
        self,
        *,
        intent: str = "",
        limit: int = 3,
    ) -> list[dict[str, object]]:
        recommendations = self._application.recommend_historical_segments(
            intent=intent,
            limit=limit,
        )
        self._recommendations = [item.to_dict() for item in recommendations]
        return list(self._recommendations)

    def create_baseline_recipe(
        self,
        *,
        name: str,
        segment_id: str,
        author: str,
        cadence_minutes: int,
        seed: int,
        commission_bps: str = "3",
        slippage_bps: str = "0",
        max_fill_fraction: str = "1",
        latency_nodes: int = 0,
        allow_partial_fills: bool = True,
    ) -> dict[str, object]:
        return self._create_recipe(
            name=name,
            segment_id=segment_id,
            author=author,
            cadence_minutes=cadence_minutes,
            seed=seed,
            transformations=(),
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            max_fill_fraction=max_fill_fraction,
            latency_nodes=latency_nodes,
            allow_partial_fills=allow_partial_fills,
        )

    def create_trend_regime_recipe(
        self,
        *,
        name: str,
        segment_id: str,
        author: str,
        cadence_minutes: int,
        seed: int,
        direction: str,
        strength: str,
        commission_bps: str = "3",
        slippage_bps: str = "0",
        max_fill_fraction: str = "1",
        latency_nodes: int = 0,
        allow_partial_fills: bool = True,
    ) -> dict[str, object]:
        return self._create_recipe(
            name=name,
            segment_id=segment_id,
            author=author,
            cadence_minutes=cadence_minutes,
            seed=seed,
            transformations=(
                {
                    "transformation_id": "trend-regime.v1",
                    "parameters": {
                        "direction": direction,
                        "strength": strength,
                    },
                },
            ),
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            max_fill_fraction=max_fill_fraction,
            latency_nodes=latency_nodes,
            allow_partial_fills=allow_partial_fills,
        )

    def create_volatility_recipe(
        self,
        *,
        name: str,
        segment_id: str,
        author: str,
        cadence_minutes: int,
        seed: int,
        multiplier: str,
        commission_bps: str = "3",
        slippage_bps: str = "0",
        max_fill_fraction: str = "1",
        latency_nodes: int = 0,
        allow_partial_fills: bool = True,
    ) -> dict[str, object]:
        return self._create_recipe(
            name=name,
            segment_id=segment_id,
            author=author,
            cadence_minutes=cadence_minutes,
            seed=seed,
            transformations=(
                {
                    "transformation_id": "volatility-scaling.v1",
                    "parameters": {"multiplier": multiplier},
                },
            ),
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            max_fill_fraction=max_fill_fraction,
            latency_nodes=latency_nodes,
            allow_partial_fills=allow_partial_fills,
        )

    def create_compound_recipe(
        self,
        *,
        name: str,
        segment_id: str,
        author: str,
        cadence_minutes: int,
        seed: int,
        transformations: tuple[dict[str, object], ...],
        commission_bps: str = "3",
        slippage_bps: str = "0",
        max_fill_fraction: str = "1",
        latency_nodes: int = 0,
        allow_partial_fills: bool = True,
    ) -> dict[str, object]:
        if len(transformations) < 2:
            raise ValueError(
                "A Compound Scenario Case requires at least two transformations"
            )
        return self._create_recipe(
            name=name,
            segment_id=segment_id,
            author=author,
            cadence_minutes=cadence_minutes,
            seed=seed,
            transformations=transformations,
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            max_fill_fraction=max_fill_fraction,
            latency_nodes=latency_nodes,
            allow_partial_fills=allow_partial_fills,
        )

    def create_shock_recovery_recipe(
        self,
        *,
        name: str,
        segment_id: str,
        author: str,
        cadence_minutes: int,
        seed: int,
        direction: str,
        gap_fraction: str,
        shock_fraction: str,
        shock_duration_bars: int,
        persistence_duration_bars: int,
        recovery_duration_bars: int,
        commission_bps: str = "3",
        slippage_bps: str = "0",
        max_fill_fraction: str = "1",
        latency_nodes: int = 0,
        allow_partial_fills: bool = True,
    ) -> dict[str, object]:
        return self._create_recipe(
            name=name,
            segment_id=segment_id,
            author=author,
            cadence_minutes=cadence_minutes,
            seed=seed,
            transformations=(
                {
                    "transformation_id": "shock-recovery.v1",
                    "parameters": {
                        "direction": direction,
                        "gap_fraction": gap_fraction,
                        "shock_fraction": shock_fraction,
                        "shock_duration_bars": shock_duration_bars,
                        "persistence_duration_bars": persistence_duration_bars,
                        "recovery_duration_bars": recovery_duration_bars,
                    },
                },
            ),
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            max_fill_fraction=max_fill_fraction,
            latency_nodes=latency_nodes,
            allow_partial_fills=allow_partial_fills,
        )

    def create_market_structure_recipe(
        self,
        *,
        name: str,
        segment_id: str,
        author: str,
        cadence_minutes: int,
        seed: int,
        breadth_target: str,
        dispersion_fraction: str,
        sector_concentration: str,
        commission_bps: str = "3",
        slippage_bps: str = "0",
        max_fill_fraction: str = "1",
        latency_nodes: int = 0,
        allow_partial_fills: bool = True,
    ) -> dict[str, object]:
        return self._create_recipe(
            name=name,
            segment_id=segment_id,
            author=author,
            cadence_minutes=cadence_minutes,
            seed=seed,
            transformations=(
                {
                    "transformation_id": "market-structure.v1",
                    "parameters": {
                        "breadth_target": breadth_target,
                        "dispersion_fraction": dispersion_fraction,
                        "sector_concentration": sector_concentration,
                    },
                },
            ),
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            max_fill_fraction=max_fill_fraction,
            latency_nodes=latency_nodes,
            allow_partial_fills=allow_partial_fills,
        )

    def create_liquidity_recipe(
        self,
        *,
        name: str,
        segment_id: str,
        author: str,
        cadence_minutes: int,
        seed: int,
        volume_multiplier: str,
        cross_sectional_concentration: str,
        commission_bps: str = "3",
        slippage_bps: str = "0",
        max_fill_fraction: str = "1",
        latency_nodes: int = 0,
        allow_partial_fills: bool = True,
    ) -> dict[str, object]:
        return self._create_recipe(
            name=name,
            segment_id=segment_id,
            author=author,
            cadence_minutes=cadence_minutes,
            seed=seed,
            transformations=(
                {
                    "transformation_id": "liquidity-stress.v1",
                    "parameters": {
                        "volume_multiplier": volume_multiplier,
                        "cross_sectional_concentration": (
                            cross_sectional_concentration
                        ),
                    },
                },
            ),
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            max_fill_fraction=max_fill_fraction,
            latency_nodes=latency_nodes,
            allow_partial_fills=allow_partial_fills,
        )

    def create_execution_stress_recipe(
        self,
        *,
        name: str,
        segment_id: str,
        author: str,
        cadence_minutes: int,
        seed: int,
        override_commission_bps: str | None,
        override_slippage_bps: str | None,
        override_max_fill_fraction: str | None,
        override_latency_nodes: int | None,
        override_allow_partial_fills: bool | None,
        rejection_mode: str | None,
        commission_bps: str = "3",
        slippage_bps: str = "0",
        max_fill_fraction: str = "1",
        latency_nodes: int = 0,
        allow_partial_fills: bool = True,
    ) -> dict[str, object]:
        override_parameters: dict[str, object] = {}
        for parameter_name, value in (
            ("commission_bps", override_commission_bps),
            ("slippage_bps", override_slippage_bps),
            ("max_fill_fraction", override_max_fill_fraction),
            ("rejection_mode", rejection_mode),
        ):
            if value is not None and value.strip():
                override_parameters[parameter_name] = value.strip()
        if override_latency_nodes is not None:
            override_parameters["latency_nodes"] = override_latency_nodes
        if override_allow_partial_fills is not None:
            override_parameters["allow_partial_fills"] = (
                "true" if override_allow_partial_fills else "false"
            )
        if not override_parameters:
            raise ValueError(
                "Execution stress requires at least one explicit scenario override"
            )
        return self._create_recipe(
            name=name,
            segment_id=segment_id,
            author=author,
            cadence_minutes=cadence_minutes,
            seed=seed,
            transformations=(
                {
                    "transformation_id": "execution-stress.v1",
                    "parameters": override_parameters,
                },
            ),
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            max_fill_fraction=max_fill_fraction,
            latency_nodes=latency_nodes,
            allow_partial_fills=allow_partial_fills,
        )

    def _create_recipe(
        self,
        *,
        name: str,
        segment_id: str,
        author: str,
        cadence_minutes: int,
        seed: int,
        transformations: tuple[dict[str, object], ...],
        commission_bps: str,
        slippage_bps: str,
        max_fill_fraction: str,
        latency_nodes: int,
        allow_partial_fills: bool,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "scenario_recipe.v1",
            "name": name,
            "historical_segment_id": segment_id,
            "transformations": list(transformations),
            "execution_conditions": {
                "commission_bps": commission_bps,
                "slippage_bps": slippage_bps,
                "max_fill_fraction": max_fill_fraction,
                "latency_nodes": latency_nodes,
                "allow_partial_fills": allow_partial_fills,
            },
            "decision_cadence_minutes": cadence_minutes,
            "materialization_seed": seed,
            "data_policy": "point-in-time",
            "market_rule_profile": "a-share-cash-equity.v1",
        }
        approved = self._recipe_workbench.get("approved_version")
        if isinstance(approved, dict):
            draft = self._application.revise_recipe_version(
                str(approved["version_id"]),
                payload,
                author=author,
            )
        else:
            draft = self._application.create_manual_recipe_draft(
                payload,
                author=author,
            )
        draft_view = draft.to_dict()
        self._recipe_workbench = {
            "status": "draft",
            "draft": draft_view,
            "validation": None,
            "approved_version": None,
            "materialization": None,
        }
        return draft_view

    def validate_current_recipe(self) -> dict[str, object]:
        draft = self._require_workbench_item("draft")
        draft_id = str(draft["draft_id"])
        validation = self._application.validate_recipe_draft(draft_id)
        validation_view = validation.to_dict()
        self._recipe_workbench["status"] = (
            "validated" if validation_view["is_valid"] else "validation_failed"
        )
        self._recipe_workbench["validation"] = validation_view
        return validation_view

    def approve_current_recipe(self, *, actor: str) -> dict[str, object]:
        draft = self._require_workbench_item("draft")
        approved = self._application.approve_recipe_draft(
            str(draft["draft_id"]),
            actor=actor,
        )
        approved_view = approved.to_dict()
        self._recipe_workbench["status"] = "approved"
        self._recipe_workbench["approved_version"] = approved_view
        return approved_view

    def materialize_current_recipe(self) -> dict[str, object]:
        approved = self._require_workbench_item("approved_version")
        path = self._application.materialize_reference_path(
            str(approved["version_id"])
        )
        materialized_view = path.to_preview_dict()
        materialized_view["recipe_version_id"] = approved["version_id"]
        materialized_view["recipe_content_hash"] = approved["content_hash"]
        applied = materialized_view.get("applied_transformations", [])
        materialization_kind = "transformed" if applied else "baseline"
        self._materializations[materialization_kind] = materialized_view
        baseline = self._materializations["baseline"]
        transformed = self._materializations["transformed"]
        if baseline is not None and transformed is not None:
            preview_time = datetime.fromisoformat(
                min(str(baseline["end_time"]), str(transformed["end_time"]))
            )
            self._scenario_comparison_preview = (
                self._application.compare_reference_market_paths(
                    str(baseline["artifact_hash"]),
                    str(transformed["artifact_hash"]),
                    at_time=preview_time,
                )
            )
        self._recipe_workbench["status"] = "materialized"
        self._recipe_workbench["materialization"] = materialized_view
        return materialized_view

    def start_baseline_run(
        self,
        *,
        initial_cash: str,
        order_shares: int,
        replica_id: str,
    ) -> dict[str, object]:
        materialization = self._recipe_workbench.get("materialization")
        if not isinstance(materialization, dict):
            raise ValueError("Materialize an approved anchored recipe before running it")
        snapshot = self._application.start_baseline_strategy_run(
            str(materialization["recipe_version_id"]),
            str(materialization["artifact_hash"]),
            initial_cash=Decimal(initial_cash),
            order_shares=order_shares,
            replica_id=replica_id,
        )
        return self._record_baseline_run(snapshot)

    def run_baseline_campaign(
        self,
        *,
        initial_cash: str,
        order_shares: int,
        campaign_replica_id: str,
        nodes_per_batch: int = 10_000,
    ) -> dict[str, object]:
        materialization = self._recipe_workbench.get("materialization")
        if not isinstance(materialization, dict):
            raise ValueError(
                "Materialize an approved anchored recipe before running a campaign"
            )
        snapshot = self._application.run_baseline_campaign(
            str(materialization["recipe_version_id"]),
            str(materialization["artifact_hash"]),
            initial_cash=Decimal(initial_cash),
            order_shares=order_shares,
            campaign_replica_id=campaign_replica_id,
            nodes_per_batch=nodes_per_batch,
        )
        self._baseline_campaign_anchor = (
            str(materialization["recipe_version_id"]),
            str(materialization["artifact_hash"]),
        )
        self._baseline_campaign = snapshot.to_dict()
        return dict(self._baseline_campaign)

    def stage_current_materialization_as_sensitivity_case(
        self,
    ) -> dict[str, object]:
        materialization = self._recipe_workbench.get("materialization")
        if not isinstance(materialization, dict):
            raise ValueError(
                "Materialize an approved single-family recipe before staging a case"
            )
        case = self._application.create_isolated_sensitivity_case(
            str(materialization["recipe_version_id"]),
            str(materialization["artifact_hash"]),
        )
        if any(
            str(existing.get("case_id")) == case.case_id
            for existing in self._sensitivity_case_views
        ):
            raise ValueError("This Sensitivity Campaign Case is already staged")
        case_view = case.to_dict()
        case_view["case_id"] = case.case_id
        self._sensitivity_case_anchors.append(
            (
                str(materialization["recipe_version_id"]),
                str(materialization["artifact_hash"]),
            )
        )
        self._sensitivity_case_views.append(case_view)
        return dict(case_view)

    def plan_isolated_sensitivity_set(
        self,
        *,
        initial_cash: str,
        order_shares: int,
        sensitivity_set_replica_id: str,
    ) -> dict[str, object]:
        snapshot = self._application.plan_isolated_sensitivity_set(
            tuple(self._sensitivity_case_anchors),
            initial_cash=Decimal(initial_cash),
            order_shares=order_shares,
            sensitivity_set_replica_id=sensitivity_set_replica_id,
        )
        return self._record_isolated_sensitivity_set(snapshot)

    def advance_isolated_sensitivity_set(
        self,
        *,
        max_cases: int = 1,
        nodes_per_batch: int = 10_000,
    ) -> dict[str, object]:
        snapshot = self._application.advance_isolated_sensitivity_set(
            self._sensitivity_set_id(),
            max_cases=max_cases,
            nodes_per_batch=nodes_per_batch,
        )
        return self._record_isolated_sensitivity_set(snapshot)

    def resume_isolated_sensitivity_set(
        self,
        *,
        max_cases: int | None = None,
        nodes_per_batch: int = 10_000,
    ) -> dict[str, object]:
        snapshot = self._application.resume_isolated_sensitivity_set(
            self._sensitivity_set_id(),
            max_cases=max_cases,
            nodes_per_batch=nodes_per_batch,
        )
        return self._record_isolated_sensitivity_set(snapshot)

    def retry_isolated_sensitivity_case(
        self,
        *,
        case_id: str,
        nodes_per_batch: int = 10_000,
    ) -> dict[str, object]:
        snapshot = self._application.retry_isolated_sensitivity_case(
            self._sensitivity_set_id(),
            case_id,
            nodes_per_batch=nodes_per_batch,
        )
        return self._record_isolated_sensitivity_set(snapshot)

    def stage_current_materialization_as_compound_case(
        self,
    ) -> dict[str, object]:
        materialization = self._recipe_workbench.get("materialization")
        if not isinstance(materialization, dict):
            raise ValueError(
                "Materialize an approved compound recipe before staging a case"
            )
        case = self._application.create_diagnostic_campaign_case(
            str(materialization["recipe_version_id"]),
            str(materialization["artifact_hash"]),
        )
        if case.layer != "compound":
            raise ValueError(
                "A Compound Scenario Case requires at least two transformations"
            )
        if any(
            str(existing.get("case_id")) == case.case_id
            for existing in self._compound_case_views
        ):
            raise ValueError("This Compound Campaign Case is already staged")
        case_view = case.to_dict()
        case_view["case_id"] = case.case_id
        case_view["layer"] = case.layer
        self._compound_case_anchors.append(
            (
                str(materialization["recipe_version_id"]),
                str(materialization["artifact_hash"]),
            )
        )
        self._compound_case_views.append(case_view)
        return dict(case_view)

    def plan_diagnostic_campaign(
        self,
        *,
        initial_cash: str,
        order_shares: int,
        campaign_replica_id: str,
    ) -> dict[str, object]:
        isolated_sensitivity_set_id = self._isolated_sensitivity_set.get(
            "sensitivity_set_id"
        )
        snapshot = self._application.plan_diagnostic_campaign(
            baseline_anchor=self._baseline_campaign_anchor,
            isolated_sensitivity_set_id=(
                str(isolated_sensitivity_set_id)
                if isinstance(isolated_sensitivity_set_id, str)
                else None
            ),
            compound_case_anchors=tuple(self._compound_case_anchors),
            initial_cash=Decimal(initial_cash),
            order_shares=order_shares,
            campaign_replica_id=campaign_replica_id,
        )
        return self._record_diagnostic_campaign(snapshot)

    def advance_diagnostic_campaign(
        self,
        *,
        max_cases: int = 1,
        nodes_per_batch: int = 10_000,
    ) -> dict[str, object]:
        snapshot = self._application.advance_diagnostic_campaign(
            self._diagnostic_campaign_id(),
            max_cases=max_cases,
            nodes_per_batch=nodes_per_batch,
        )
        return self._record_diagnostic_campaign(snapshot)

    def resume_diagnostic_campaign(
        self,
        *,
        max_cases: int | None = None,
        nodes_per_batch: int = 10_000,
    ) -> dict[str, object]:
        snapshot = self._application.resume_diagnostic_campaign(
            self._diagnostic_campaign_id(),
            max_cases=max_cases,
            nodes_per_batch=nodes_per_batch,
        )
        return self._record_diagnostic_campaign(snapshot)

    def retry_diagnostic_campaign_case(
        self,
        *,
        case_id: str,
        nodes_per_batch: int = 10_000,
    ) -> dict[str, object]:
        snapshot = self._application.retry_diagnostic_campaign_case(
            self._diagnostic_campaign_id(),
            case_id,
            nodes_per_batch=nodes_per_batch,
        )
        return self._record_diagnostic_campaign(snapshot)

    def build_diagnostic_evidence(self) -> dict[str, object]:
        campaign_id = self._diagnostic_campaign_id()
        package = self._application.build_diagnostic_evidence(
            campaign_id
        )
        evidence = package.to_dict()
        if evidence.get("campaign_id") != campaign_id:
            raise ValueError(
                "Diagnostic Evidence Package does not belong to the current "
                "Diagnostic Campaign"
            )
        self._diagnostic_evidence = evidence
        self._diagnostic_explanations = {
            "status": "not_requested",
            "message": (
                "Optional explanations can reference sealed findings only."
            ),
            "explanations": [],
        }
        return dict(self._diagnostic_evidence)

    def refresh_diagnostic_evidence(self) -> dict[str, object]:
        campaign_id = self._diagnostic_campaign_id()
        package = self._application.diagnostic_evidence_status(
            self._diagnostic_evidence_id()
        )
        evidence = package.to_dict()
        if evidence.get("campaign_id") != campaign_id:
            raise ValueError(
                "Diagnostic Evidence Package does not belong to the current "
                "Diagnostic Campaign"
            )
        self._diagnostic_evidence = evidence
        return dict(self._diagnostic_evidence)

    def explain_diagnostic_findings(self) -> dict[str, object]:
        bundle = self._application.explain_diagnostic_findings(
            self._diagnostic_evidence_id()
        )
        self._diagnostic_explanations = {
            "status": "available",
            **bundle.to_dict(),
        }
        return dict(self._diagnostic_explanations)

    def advance_baseline_run(self, *, node_count: int = 1) -> dict[str, object]:
        snapshot = self._application.advance_strategy_run(
            self._baseline_run_id(),
            node_count=node_count,
        )
        return self._record_baseline_run(snapshot)

    def complete_baseline_run(
        self,
        *,
        nodes_per_batch: int = 10_000,
    ) -> dict[str, object]:
        snapshot = self._application.complete_strategy_run(
            self._baseline_run_id(),
            nodes_per_batch=nodes_per_batch,
        )
        return self._record_baseline_run(snapshot)

    def pause_baseline_run(self) -> dict[str, object]:
        snapshot = self._application.pause_strategy_run(self._baseline_run_id())
        return self._record_baseline_run(snapshot)

    def resume_baseline_run(self) -> dict[str, object]:
        snapshot = self._application.resume_strategy_run(self._baseline_run_id())
        return self._record_baseline_run(snapshot)

    def cancel_baseline_run(self) -> dict[str, object]:
        snapshot = self._application.cancel_strategy_run(self._baseline_run_id())
        return self._record_baseline_run(snapshot)

    def _baseline_run_id(self) -> str:
        run_id = self._baseline_strategy_run.get("run_id")
        if not isinstance(run_id, str):
            raise ValueError("No baseline Strategy Run has been started")
        return run_id

    def _record_baseline_run(
        self,
        snapshot: _StrategyRunSnapshot,
    ) -> dict[str, object]:
        self._baseline_strategy_run = snapshot.to_dict()
        return dict(self._baseline_strategy_run)

    def _sensitivity_set_id(self) -> str:
        sensitivity_set_id = self._isolated_sensitivity_set.get(
            "sensitivity_set_id"
        )
        if not isinstance(sensitivity_set_id, str):
            raise ValueError("No Isolated Sensitivity Set has been planned")
        return sensitivity_set_id

    def _record_isolated_sensitivity_set(
        self,
        snapshot: _StrategyRunSnapshot,
    ) -> dict[str, object]:
        self._isolated_sensitivity_set = snapshot.to_dict()
        return dict(self._isolated_sensitivity_set)

    def _diagnostic_campaign_id(self) -> str:
        campaign_id = self._diagnostic_campaign.get("campaign_id")
        if not isinstance(campaign_id, str):
            raise ValueError("No Diagnostic Campaign has been planned")
        return campaign_id

    def _record_diagnostic_campaign(
        self,
        snapshot: _StrategyRunSnapshot,
    ) -> dict[str, object]:
        previous_campaign_id = self._diagnostic_campaign.get("campaign_id")
        campaign = snapshot.to_dict()
        next_campaign_id = campaign.get("campaign_id")
        if (
            isinstance(next_campaign_id, str)
            and next_campaign_id != previous_campaign_id
        ):
            self._diagnostic_evidence = {
                "status": "not_built",
                "message": (
                    "Complete this Formal Diagnostic Campaign to seal evidence."
                ),
                "metrics": [],
                "comparisons": [],
                "guardrail_breaches": [],
                "sensitivity_breakpoints": [],
                "diagnostic_findings": [],
            }
            self._diagnostic_explanations = {
                "status": "not_requested",
                "message": (
                    "Optional explanations can reference sealed findings only."
                ),
                "explanations": [],
            }
        self._diagnostic_campaign = campaign
        return dict(self._diagnostic_campaign)

    def _diagnostic_evidence_id(self) -> str:
        evidence_package_id = self._diagnostic_evidence.get(
            "evidence_package_id"
        )
        if not isinstance(evidence_package_id, str):
            raise ValueError("No sealed Diagnostic Evidence Package exists")
        if (
            self._diagnostic_evidence.get("campaign_id")
            != self._diagnostic_campaign_id()
        ):
            raise ValueError(
                "No sealed Diagnostic Evidence Package exists for the current "
                "Diagnostic Campaign"
            )
        return evidence_package_id

    def _require_workbench_item(self, key: str) -> dict[str, object]:
        item = self._recipe_workbench.get(key)
        if not isinstance(item, dict):
            raise ValueError(f"Scenario Recipe workbench has no {key.replace('_', ' ')}")
        return item


__all__ = ["DiagnosticsApplicationPort", "DiagnosticsPanel"]
