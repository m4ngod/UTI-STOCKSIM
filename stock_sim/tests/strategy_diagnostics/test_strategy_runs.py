from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from strategy_diagnostics import (
    InMemoryMarketPathArtifactStore,
    InstrumentState,
    MarketPathNode,
    MaterializedMarketPath,
    StrategyRunEngine,
    StrategyRunSpecification,
)
from strategy_diagnostics.persistence import initialize_diagnostic_persistence
from strategy_diagnostics.strategy_runs import SqlStrategyRunRepository


def _reference_path() -> MaterializedMarketPath:
    start = datetime(2024, 1, 2, 9, 59, 30)
    end = datetime(2024, 1, 2, 11, 0, 30)
    simulation_times: list[datetime] = []
    cursor = start
    while cursor <= end:
        simulation_times.append(cursor)
        cursor += timedelta(seconds=30)
    nodes = tuple(
        MarketPathNode(
            instrument=instrument,
            simulation_time=simulation_time,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=10_000,
            amount=price * 10_000,
            reconstructed=True,
            features=(
                ("candidate_rank", Decimal(rank)),
                ("candidate_score", Decimal(score)),
            ),
        )
        for simulation_time in simulation_times
        for instrument, price, rank, score in (
            ("sh.600000", Decimal("10.00"), 1, "2"),
            ("sz.000001", Decimal("20.00"), 2, "1"),
        )
    )
    return MaterializedMarketPath(
        artifact_hash="a" * 64,
        segment_id="segment-baseline",
        segment_content_hash="b" * 64,
        source_snapshot_id="snapshot-baseline",
        seed=17,
        expander_version="within-bar-expander.v1",
        source_resolution="5m",
        runtime_resolution="30s",
        reconstructed=True,
        numeric_tolerance="0.0001",
        normalization_provenance="fixture-unadjusted-v1",
        market_rule_profile_version="a-share-cash-equity.v1",
        transformation_catalog_version="initial-transformation-profile.v1",
        applied_transformations=(),
        nodes=nodes,
        instrument_states=tuple(
            InstrumentState(
                instrument=instrument,
                effective_at=datetime(2024, 1, 2, 9, 30),
                eligible=True,
                trading_status="trading",
                is_st=False,
                industry=industry,
                decision_adjustment_factor=Decimal("1"),
                decision_adjustment_provenance="fixture-v1",
            )
            for instrument, industry in (
                ("sh.600000", "banking"),
                ("sz.000001", "technology"),
            )
        ),
    )


def _engine(path: MaterializedMarketPath) -> StrategyRunEngine:
    store = InMemoryMarketPathArtifactStore()
    store.put(path)
    return StrategyRunEngine(store.get)


def _spec(
    path: MaterializedMarketPath,
    *,
    cadence_minutes: int = 30,
    order_shares: int = 100,
    replica_id: str = "baseline-replica-1",
) -> StrategyRunSpecification:
    return StrategyRunSpecification(
        recipe_version_id="recipe-version-baseline",
        recipe_content_hash="c" * 64,
        materialization_hash=path.artifact_hash,
        source_snapshot_id=path.source_snapshot_id,
        materialization_seed=path.seed,
        transformation_catalog_version=path.transformation_catalog_version,
        transformation_implementation_versions=(),
        market_rule_profile_version=path.market_rule_profile_version,
        execution_policy_version="private-ledger-baseline.v1",
        strategy_id="anchored-ranked-candidate-reference",
        strategy_version="anchored-ranked-candidate-reference.v1",
        decision_cadence_minutes=cadence_minutes,
        initial_cash=Decimal("100000"),
        order_shares=order_shares,
        replica_id=replica_id,
        code_identity="strategy-diagnostics.v1",
    )


def test_half_hour_decisions_use_simulation_time_and_next_node_activation() -> None:
    path = _reference_path()
    engine = _engine(path)

    started = engine.start(_spec(path, cadence_minutes=30))
    completed = engine.run_to_completion(started.run_id, nodes_per_batch=19)

    assert completed.status == "completed"
    assert completed.decision_times == (
        datetime(2024, 1, 2, 10, 0),
        datetime(2024, 1, 2, 10, 30),
        datetime(2024, 1, 2, 11, 0),
    )
    assert len(completed.orders) == 1
    order = completed.orders[0]
    assert order.decision_time == datetime(2024, 1, 2, 10, 0)
    assert order.activation_time == datetime(2024, 1, 2, 10, 0, 30)
    assert order.status == "filled"
    assert completed.fills[0].simulation_time == datetime(2024, 1, 2, 10, 0, 30)
    assert completed.fills[0].instrument == "sh.600000"
    assert completed.positions[0].shares == 100
    assert completed.equity_curve[-1].equity == Decimal("100000.00")
    assert completed.run_artifact_hash is not None


def test_hourly_decisions_are_independent_of_wall_time_batch_size() -> None:
    path = _reference_path()
    spec = _spec(path, cadence_minutes=60)

    fast = _engine(path)
    fast_started = fast.start(spec)
    fast_completed = fast.run_to_completion(
        fast_started.run_id,
        nodes_per_batch=10_000,
    )

    stepped = _engine(path)
    stepped_started = stepped.start(spec)
    stepped_completed = stepped.run_to_completion(
        stepped_started.run_id,
        nodes_per_batch=1,
    )

    assert fast_completed.decision_times == (
        datetime(2024, 1, 2, 10, 0),
        datetime(2024, 1, 2, 11, 0),
    )
    assert fast_completed.to_dict() == stepped_completed.to_dict()


def test_orders_change_only_the_private_portfolio_not_the_reference_path() -> None:
    path = _reference_path()
    nodes_before = path.nodes

    first_engine = _engine(path)
    first_started = first_engine.start(
        _spec(path, order_shares=100, replica_id="replica-100")
    )
    first = first_engine.run_to_completion(first_started.run_id)

    second_engine = _engine(path)
    second_started = second_engine.start(
        _spec(path, order_shares=200, replica_id="replica-200")
    )
    second = second_engine.run_to_completion(second_started.run_id)

    assert path.artifact_hash == "a" * 64
    assert path.nodes == nodes_before
    assert first.materialization_hash == second.materialization_hash == path.artifact_hash
    assert first.fills[0].shares == 100
    assert second.fills[0].shares == 200
    assert first.cash != second.cash
    assert first.positions != second.positions


def test_pause_resume_matches_an_uninterrupted_run_at_node_boundaries() -> None:
    path = _reference_path()
    spec = _spec(path)

    controlled_engine = _engine(path)
    started = controlled_engine.start(spec)
    at_decision = controlled_engine.advance(started.run_id, node_count=2)
    assert at_decision.current_simulation_time == datetime(2024, 1, 2, 10, 0)
    paused = controlled_engine.pause(started.run_id)
    assert paused.status == "paused"
    with pytest.raises(ValueError, match="running"):
        controlled_engine.advance(started.run_id, node_count=1)
    resumed = controlled_engine.resume(started.run_id)
    assert resumed.status == "running"
    controlled = controlled_engine.run_to_completion(started.run_id, nodes_per_batch=7)

    uninterrupted_engine = _engine(path)
    uninterrupted_started = uninterrupted_engine.start(spec)
    uninterrupted = uninterrupted_engine.run_to_completion(
        uninterrupted_started.run_id,
        nodes_per_batch=7,
    )

    assert controlled.to_dict() == uninterrupted.to_dict()


def test_cancel_stops_a_run_at_the_last_completed_node_boundary() -> None:
    path = _reference_path()
    engine = _engine(path)
    started = engine.start(_spec(path))
    advanced = engine.advance(started.run_id, node_count=1)

    cancelled = engine.cancel(started.run_id)

    assert cancelled.status == "cancelled"
    assert cancelled.current_simulation_time == advanced.current_simulation_time
    assert cancelled.processed_node_count == 1
    with pytest.raises(ValueError, match="cancelled"):
        engine.resume(started.run_id)


def test_missing_candidate_rank_fails_closed_at_the_last_node_boundary() -> None:
    original = _reference_path()
    invalid = replace(
        original,
        artifact_hash="d" * 64,
        nodes=tuple(replace(node, features=()) for node in original.nodes),
    )
    engine = _engine(invalid)
    started = engine.start(_spec(invalid))

    failed = engine.run_to_completion(started.run_id, nodes_per_batch=10)

    assert failed.status == "failed"
    assert failed.current_simulation_time == datetime(2024, 1, 2, 9, 59, 30)
    assert failed.processed_node_count == 1
    assert failed.failure_code == "ValueError"
    assert "candidate ranking" in str(failed.failure_message)
    assert failed.orders == ()
    assert failed.fills == ()


def test_paused_run_and_private_facts_survive_repository_restart(tmp_path: Path) -> None:
    path = _reference_path()
    store = InMemoryMarketPathArtifactStore()
    store.put(path)
    database = create_engine(
        f"sqlite:///{tmp_path / 'strategy-runs.db'}",
        future=True,
    )
    initialize_diagnostic_persistence(database)
    first_engine = StrategyRunEngine(
        store.get,
        repository=SqlStrategyRunRepository(database),
    )
    started = first_engine.start(_spec(path))
    first_engine.advance(started.run_id, node_count=2)
    paused = first_engine.pause(started.run_id)

    restarted_engine = StrategyRunEngine(
        store.get,
        repository=SqlStrategyRunRepository(database),
    )
    restored = restarted_engine.get(started.run_id)
    restarted_engine.resume(started.run_id)
    completed = restarted_engine.run_to_completion(started.run_id, nodes_per_batch=11)

    assert restored.to_dict() == paused.to_dict()
    assert completed.status == "completed"
    assert completed.fills[0].simulation_time == datetime(2024, 1, 2, 10, 0, 30)
    with database.connect() as connection:
        counts = {
            table: connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            for table in (
                "diagnostic_strategy_runs",
                "diagnostic_run_orders",
                "diagnostic_run_fills",
                "diagnostic_run_positions",
                "diagnostic_run_equity",
            )
        }
    assert counts == {
        "diagnostic_strategy_runs": 1,
        "diagnostic_run_orders": 1,
        "diagnostic_run_fills": 1,
        "diagnostic_run_positions": 1,
        "diagnostic_run_equity": completed.total_node_count,
    }


def test_failed_run_evidence_survives_repository_restart(tmp_path: Path) -> None:
    original = _reference_path()
    invalid = replace(
        original,
        artifact_hash="e" * 64,
        nodes=tuple(replace(node, features=()) for node in original.nodes),
    )
    store = InMemoryMarketPathArtifactStore()
    store.put(invalid)
    database = create_engine(
        f"sqlite:///{tmp_path / 'failed-strategy-run.db'}",
        future=True,
    )
    initialize_diagnostic_persistence(database)
    engine = StrategyRunEngine(
        store.get,
        repository=SqlStrategyRunRepository(database),
    )
    started = engine.start(_spec(invalid, replica_id="failed-replica"))
    failed = engine.run_to_completion(started.run_id)

    restarted = StrategyRunEngine(
        store.get,
        repository=SqlStrategyRunRepository(database),
    ).get(started.run_id)

    assert restarted.to_dict() == failed.to_dict()
    assert restarted.status == "failed"
    assert restarted.failure_code == "ValueError"
    assert "candidate ranking" in str(restarted.failure_message)
