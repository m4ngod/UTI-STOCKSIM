from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from strategy_diagnostics import (
    InMemoryMarketPathArtifactStore,
    InstrumentState,
    MarketPathNode,
    MaterializedMarketPath,
    SessionPriceLimitReference,
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
        price_limit_references=tuple(
            SessionPriceLimitReference(
                instrument=instrument,
                session_date=date(2024, 1, 2),
                previous_close=previous_close,
                effective_at=datetime(2024, 1, 2, 9, 25),
                provenance="strategy-run-hand-calculable-fixture",
                profile_version="a-share-cash-equity.v1",
                board=board,
                is_st=False,
                listing_stage="continuous",
                limit_fraction=Decimal("0.10"),
                rule_code=(
                    f"{board}.ordinary.10pct.effective-2024-01-02"
                ),
            )
            for instrument, previous_close, board in (
                ("sh.600000", Decimal("10.00"), "sh-main"),
                ("sz.000001", Decimal("20.00"), "sz-main"),
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
        execution_policy_version="a-share-cash-equity-execution.v1",
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
    assert order.accepted_shares == 100
    assert order.reason_code == "accepted"
    assert order.cash_change == Decimal("-1005.01")
    assert order.position_change == 100
    assert completed.fills[0].simulation_time == datetime(2024, 1, 2, 10, 0, 30)
    assert completed.fills[0].instrument == "sh.600000"
    assert completed.fills[0].fees.total == Decimal("5.01")
    assert completed.fills[0].cash_change == Decimal("-1005.01")
    assert completed.positions[0].shares == 100
    assert completed.equity_curve[-1].equity == Decimal("99994.99")
    assert completed.run_artifact_hash is not None


def test_cash_check_includes_policy_fees_and_records_rejection_evidence() -> None:
    path = _reference_path()
    engine = _engine(path)
    specification = replace(_spec(path), initial_cash=Decimal("1005.00"))

    completed = engine.run_to_completion(engine.start(specification).run_id)

    assert completed.status == "completed"
    assert len(completed.orders) == 1
    assert completed.orders[0].status == "rejected"
    assert completed.orders[0].accepted_shares == 0
    assert completed.orders[0].reason_code == "account.insufficient_cash"
    assert completed.orders[0].cash_change == Decimal("0")
    assert completed.orders[0].position_change == 0
    assert completed.fills == ()
    assert completed.cash == Decimal("1005.00")


def test_activation_uses_point_in_time_suspension_state() -> None:
    original = _reference_path()
    suspended_state = replace(
        original.instrument_states[0],
        effective_at=datetime(2024, 1, 2, 10, 0, 30),
        trading_status="suspended",
    )
    path = replace(
        original,
        instrument_states=original.instrument_states + (suspended_state,),
    )
    engine = _engine(path)

    completed = engine.run_to_completion(engine.start(_spec(path)).run_id)

    assert completed.orders[0].status == "rejected"
    assert completed.orders[0].reason_code == "market.suspended"
    assert completed.fills == ()


def test_suspension_rejects_even_when_the_activation_node_has_no_trade() -> None:
    original = _reference_path()
    activation_time = datetime(2024, 1, 2, 10, 0, 30)
    suspended_state = replace(
        original.instrument_states[0],
        effective_at=activation_time,
        trading_status="suspended",
    )
    path = replace(
        original,
        nodes=tuple(
            node
            for node in original.nodes
            if not (
                node.instrument == "sh.600000"
                and node.simulation_time == activation_time
            )
        ),
        instrument_states=original.instrument_states + (suspended_state,),
    )
    engine = _engine(path)

    completed = engine.run_to_completion(engine.start(_spec(path)).run_id)

    assert completed.orders[0].status == "rejected"
    assert completed.orders[0].reason_code == "market.suspended"
    assert completed.fills == ()


def test_activation_fails_closed_without_price_limit_reference() -> None:
    path = replace(_reference_path(), price_limit_references=())
    engine = _engine(path)

    completed = engine.run_to_completion(engine.start(_spec(path)).run_id)

    assert completed.orders[0].status == "rejected"
    assert (
        completed.orders[0].reason_code
        == "market.price_limit_reference_missing"
    )
    assert completed.fills == ()


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
        order_audit = connection.execute(
            text(
                "SELECT accepted_shares, reason_code, execution_price, "
                "price_limit_lower, price_limit_upper, cash_change, "
                "position_change, sellable_shares_change "
                "FROM diagnostic_run_orders"
            )
        ).one()
        fill_audit = connection.execute(
            text(
                "SELECT commission, transfer_fee, stamp_duty, total_fee, "
                "cash_change FROM diagnostic_run_fills"
            )
        ).one()
        position_audit = connection.execute(
            text(
                "SELECT t_plus_one_locked_shares, lock_session_date "
                "FROM diagnostic_run_positions"
            )
        ).one()
    assert counts == {
        "diagnostic_strategy_runs": 1,
        "diagnostic_run_orders": 1,
        "diagnostic_run_fills": 1,
        "diagnostic_run_positions": 1,
        "diagnostic_run_equity": completed.total_node_count,
    }
    assert order_audit == (
        100,
        "accepted",
        "10.00",
        "9.00",
        "11.00",
        "-1005.01",
        100,
        0,
    )
    assert fill_audit == ("5.00", "0.01", "0.00", "5.01", "-1005.01")
    assert position_audit == (100, "2024-01-02")


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


def test_pre_execution_profile_paused_run_is_read_only_after_upgrade(
    tmp_path: Path,
) -> None:
    path = _reference_path()
    store = InMemoryMarketPathArtifactStore()
    store.put(path)
    database = create_engine(
        f"sqlite:///{tmp_path / 'pre-execution-profile.db'}",
        future=True,
    )
    legacy_specification = replace(
        _spec(path, replica_id="legacy-0005-run"),
        execution_policy_version="private-ledger-baseline.v1",
    )
    legacy_specification_payload = legacy_specification.to_dict()
    for name in (
        "commission_bps",
        "minimum_commission",
        "transfer_fee_bps",
        "sell_stamp_duty_bps",
    ):
        legacy_specification_payload.pop(name)
    legacy_run_id = "strategy-run-" + hashlib.sha256(
        json.dumps(
            legacy_specification_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:24]
    legacy_state = {
        "run_id": legacy_run_id,
        "status": "paused",
        "specification": legacy_specification_payload,
        "current_simulation_time": None,
        "processed_node_count": 0,
        "decision_times": [],
        "orders": [],
        "fills": [],
        "cash": "100000",
        "positions": [],
        "equity_curve": [],
        "failure_code": None,
        "failure_message": None,
        "run_artifact_hash": None,
    }
    _create_actual_0005_strategy_run_database(
        database,
        run_id=legacy_run_id,
        state_json=json.dumps(
            legacy_state,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    migration = initialize_diagnostic_persistence(database)
    repository = SqlStrategyRunRepository(database)
    engine = StrategyRunEngine(store.get, repository=repository)

    restored = engine.get(legacy_run_id)
    with pytest.raises(ValueError, match="execution policy version"):
        engine.resume(legacy_run_id)

    assert migration.applied_revisions == ("0006_a_share_execution_audit",)
    assert restored.run_id == legacy_run_id
    assert restored.status == "paused"
    assert engine.get(legacy_run_id).status == "paused"
    assert restored.specification.execution_economics_pinned is False
    assert (
        restored.specification.execution_policy_version
        == "private-ledger-baseline.v1"
    )


def _create_actual_0005_strategy_run_database(
    database: Engine,
    *,
    run_id: str,
    state_json: str,
) -> None:
    with database.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE diagnostic_schema_migrations ("
            "revision VARCHAR(128) PRIMARY KEY NOT NULL, "
            "applied_at_utc VARCHAR(64) NOT NULL)"
        )
        for revision in (
            "0001_diagnostics_baseline",
            "0002_historical_segment_catalog",
            "0003_scenario_recipe_lifecycle",
            "0004_ai_recipe_assistant",
            "0005_strategy_runs",
        ):
            connection.execute(
                text(
                    "INSERT INTO diagnostic_schema_migrations "
                    "(revision, applied_at_utc) VALUES (:revision, :applied_at_utc)"
                ),
                {"revision": revision, "applied_at_utc": "2026-07-21T00:00:00Z"},
            )
        connection.exec_driver_sql(
            "CREATE TABLE diagnostic_strategy_runs ("
            "run_id VARCHAR(96) PRIMARY KEY NOT NULL, status VARCHAR(32) NOT NULL, "
            "materialization_hash VARCHAR(64) NOT NULL, "
            "recipe_version_id VARCHAR(96) NOT NULL, "
            "strategy_id VARCHAR(128) NOT NULL, "
            "strategy_version VARCHAR(128) NOT NULL, "
            "decision_cadence_minutes INTEGER NOT NULL, "
            "current_simulation_time VARCHAR(64) NULL, "
            "next_node_index INTEGER NOT NULL, state_json TEXT NOT NULL, "
            "run_artifact_hash VARCHAR(64) NULL, failure_code VARCHAR(128) NULL, "
            "failure_message TEXT NULL, updated_at_utc VARCHAR(64) NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE diagnostic_run_orders ("
            "order_id VARCHAR(160) PRIMARY KEY NOT NULL, run_id VARCHAR(96) NOT NULL, "
            "instrument VARCHAR(32) NOT NULL, shares INTEGER NOT NULL, "
            "decision_time VARCHAR(64) NOT NULL, activation_time VARCHAR(64) NOT NULL, "
            "status VARCHAR(32) NOT NULL, rejection_reason VARCHAR(128) NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE diagnostic_run_fills ("
            "fill_id VARCHAR(192) PRIMARY KEY NOT NULL, run_id VARCHAR(96) NOT NULL, "
            "order_id VARCHAR(160) NOT NULL, instrument VARCHAR(32) NOT NULL, "
            "shares INTEGER NOT NULL, price VARCHAR(64) NOT NULL, "
            "gross_value VARCHAR(64) NOT NULL, simulation_time VARCHAR(64) NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE diagnostic_run_positions ("
            "run_id VARCHAR(96) NOT NULL, instrument VARCHAR(32) NOT NULL, "
            "shares INTEGER NOT NULL, total_cost VARCHAR(64) NOT NULL, "
            "PRIMARY KEY(run_id, instrument))"
        )
        connection.exec_driver_sql(
            "CREATE TABLE diagnostic_run_equity ("
            "run_id VARCHAR(96) NOT NULL, simulation_time VARCHAR(64) NOT NULL, "
            "cash VARCHAR(64) NOT NULL, positions_value VARCHAR(64) NOT NULL, "
            "equity VARCHAR(64) NOT NULL, PRIMARY KEY(run_id, simulation_time))"
        )
        connection.execute(
            text(
                "INSERT INTO diagnostic_strategy_runs ("
                "run_id, status, materialization_hash, recipe_version_id, "
                "strategy_id, strategy_version, decision_cadence_minutes, "
                "current_simulation_time, next_node_index, state_json, "
                "run_artifact_hash, failure_code, failure_message, updated_at_utc"
                ") VALUES ("
                ":run_id, 'paused', :materialization_hash, :recipe_version_id, "
                ":strategy_id, :strategy_version, 30, NULL, 0, :state_json, "
                "NULL, NULL, NULL, '2026-07-21T00:00:00Z')"
            ),
            {
                "run_id": run_id,
                "materialization_hash": "a" * 64,
                "recipe_version_id": "recipe-version-baseline",
                "strategy_id": "anchored-ranked-candidate-reference",
                "strategy_version": "anchored-ranked-candidate-reference.v1",
                "state_json": state_json,
            },
        )
