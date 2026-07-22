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
            "message": "Materialize an approved baseline recipe to start a run.",
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
        baseline = self._materializations.get("baseline")
        if not isinstance(baseline, dict):
            raise ValueError("Materialize an approved baseline recipe before running it")
        snapshot = self._application.start_baseline_strategy_run(
            str(baseline["recipe_version_id"]),
            str(baseline["artifact_hash"]),
            initial_cash=Decimal(initial_cash),
            order_shares=order_shares,
            replica_id=replica_id,
        )
        return self._record_baseline_run(snapshot)

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

    def _require_workbench_item(self, key: str) -> dict[str, object]:
        item = self._recipe_workbench.get(key)
        if not isinstance(item, dict):
            raise ValueError(f"Scenario Recipe workbench has no {key.replace('_', ' ')}")
        return item


__all__ = ["DiagnosticsApplicationPort", "DiagnosticsPanel"]
