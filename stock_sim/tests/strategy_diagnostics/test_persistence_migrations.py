from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from strategy_diagnostics import (
    AdmissionCheck,
    HistoricalSegmentSelection,
    HistoricalSourceInspection,
    InMemoryHistoricalSource,
    SourceArtifact,
    SourceProvenance,
    create_diagnostics_application,
)
from strategy_diagnostics.persistence import SqlHistoricalSegmentCatalog

REQUIRED_CHECKS = (
    "bar_continuity",
    "instrument_coverage",
    "eligible_universe",
    "trading_status",
    "st_status",
    "suspension_state",
    "industry_as_of",
    "adjustment_consistency",
    "causal_availability",
    "required_fields",
    "missing_data",
    "duplicates",
    "timestamps",
)


def _column_contract(engine: object, table_name: str) -> list[tuple[object, ...]]:
    return [
        (
            column["name"],
            str(column["type"]),
            column["nullable"],
            column["default"],
            column["primary_key"],
        )
        for column in inspect(engine).get_columns(table_name)
    ]


def test_diagnostic_migration_baseline_preserves_legacy_tables(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'diagnostics.db'}", future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE legacy_accounts ("
            "id INTEGER PRIMARY KEY, owner VARCHAR(64) NOT NULL, balance INTEGER NOT NULL"
            ")"
        )
        connection.execute(
            text(
                "INSERT INTO legacy_accounts (id, owner, balance) "
                "VALUES (1, 'existing-user', 125000)"
            )
        )

    columns_before = _column_contract(engine, "legacy_accounts")

    application = create_diagnostics_application()
    application.start()
    first = application.initialize_persistence(engine)
    second = application.initialize_persistence(engine)

    assert first.current_revision == "0013_diagnostic_tasks"
    assert first.applied_revisions == (
        "0001_diagnostics_baseline",
        "0002_historical_segment_catalog",
        "0003_scenario_recipe_lifecycle",
        "0004_ai_recipe_assistant",
        "0005_strategy_runs",
        "0006_a_share_execution_audit",
        "0007_execution_stress_audit",
        "0008_ptrade_host_audit",
        "0009_isolated_sensitivity_sets",
        "0010_formal_diagnostic_campaigns",
        "0011_diagnostic_evidence",
        "0012_reproduction_manifests",
        "0013_diagnostic_tasks",
    )
    assert second.current_revision == "0013_diagnostic_tasks"
    assert second.applied_revisions == ()
    assert application.status().persistence_status == "ready"
    assert (
        application.status().persistence_revision
        == "0013_diagnostic_tasks"
    )
    assert _column_contract(engine, "legacy_accounts") == columns_before
    with engine.connect() as connection:
        legacy_row = connection.execute(
            text("SELECT id, owner, balance FROM legacy_accounts")
        ).one()
        revisions = connection.execute(
            text(
                "SELECT revision FROM diagnostic_schema_migrations "
                "ORDER BY revision"
            )
        ).scalars().all()
    assert legacy_row == (1, "existing-user", 125000)
    assert revisions == [
        "0001_diagnostics_baseline",
        "0002_historical_segment_catalog",
        "0003_scenario_recipe_lifecycle",
        "0004_ai_recipe_assistant",
        "0005_strategy_runs",
        "0006_a_share_execution_audit",
        "0007_execution_stress_audit",
        "0008_ptrade_host_audit",
        "0009_isolated_sensitivity_sets",
        "0010_formal_diagnostic_campaigns",
        "0011_diagnostic_evidence",
        "0012_reproduction_manifests",
        "0013_diagnostic_tasks",
    ]
    strategy_run_columns = {
        column["name"]
        for column in inspect(engine).get_columns("diagnostic_strategy_runs")
    }
    assert {
        "ptrade_surface_version",
        "ptrade_manifest_hash",
        "ptrade_host_adapter_version",
        "ptrade_host_audit_json",
    } <= strategy_run_columns
    assert {
        "diagnostic_source_snapshots",
        "diagnostic_historical_segments",
        "diagnostic_recipe_drafts",
        "diagnostic_recipe_validations",
        "diagnostic_recipe_approvals",
        "diagnostic_recipe_versions",
        "diagnostic_ai_recipe_attempts",
        "diagnostic_strategy_runs",
        "diagnostic_isolated_sensitivity_sets",
        "diagnostic_campaigns",
        "diagnostic_guardrail_profiles",
        "diagnostic_evidence_packages",
        "diagnostic_findings",
        "diagnostic_reproduction_manifests",
        "diagnostic_reproduction_attempts",
        "diagnostic_tasks",
        "diagnostic_task_commands",
        "diagnostic_task_handles",
        "diagnostic_task_sequences",
        "diagnostic_run_orders",
        "diagnostic_run_fills",
        "diagnostic_run_positions",
        "diagnostic_run_equity",
    }.issubset(set(inspect(engine).get_table_names()))


def test_admitted_segment_catalog_survives_application_restart(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'diagnostics.db'}", future=True)
    selection = HistoricalSegmentSelection(
        market="mainland-a-share",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
    )
    inspection_result = HistoricalSourceInspection(
        selection=selection,
        label="Durable development interval",
        provenance=SourceProvenance(
            provider="BaoStock",
            dataset="restart-fixture",
            version="v1",
            observed_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
        ),
        artifacts=(SourceArtifact("bars", "a" * 64, 100),),
        eligible_instrument_count=2,
        trading_day_count=2,
        bar_count=100,
        checks=tuple(
            AdmissionCheck(code, True, f"{code} passed")
            for code in REQUIRED_CHECKS
        ),
    )
    source = InMemoryHistoricalSource((inspection_result,))

    first_application = create_diagnostics_application(historical_source=source)
    first_application.start()
    first_application.initialize_persistence(engine)
    admitted = first_application.admit_historical_segment(selection)

    restarted_application = create_diagnostics_application(historical_source=source)
    restarted_application.start()
    restarted_application.initialize_persistence(engine)

    assert admitted.segment is not None
    assert admitted.source_snapshot is not None
    assert restarted_application.list_historical_segments() == (admitted.segment,)
    assert restarted_application.recommend_historical_segments()[0].segment == admitted.segment
    catalog = SqlHistoricalSegmentCatalog(engine)
    assert catalog.get_source_snapshot(
        admitted.source_snapshot.snapshot_id
    ) == admitted.source_snapshot

    provenance = admitted.source_snapshot.provenance.to_dict()
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_source_snapshots "
                "SET provenance_json = :provenance_json "
                "WHERE snapshot_id = :snapshot_id"
            ),
            {
                "provenance_json": json.dumps(
                    {**provenance, "unexpected": "must fail closed"},
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "snapshot_id": admitted.source_snapshot.snapshot_id,
            },
        )
    with pytest.raises(ValueError, match="provenance schema mismatch"):
        catalog.get_source_snapshot(admitted.source_snapshot.snapshot_id)

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_source_snapshots "
                "SET provenance_json = :provenance_json "
                "WHERE snapshot_id = :snapshot_id"
            ),
            {
                "provenance_json": json.dumps(
                    {
                        **provenance,
                        "observed_at": "2026-07-21T00:00:00",
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "snapshot_id": admitted.source_snapshot.snapshot_id,
            },
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        catalog.get_source_snapshot(admitted.source_snapshot.snapshot_id)


def test_diagnostic_migration_rejects_an_unknown_future_revision(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'future.db'}", future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE diagnostic_schema_migrations ("
            "revision VARCHAR(128) PRIMARY KEY NOT NULL, "
            "applied_at_utc VARCHAR(64) NOT NULL"
            ")"
        )
        connection.execute(
            text(
                "INSERT INTO diagnostic_schema_migrations "
                "(revision, applied_at_utc) VALUES "
                "('9999_future_schema', '2030-01-01T00:00:00+00:00')"
            )
        )

    application = create_diagnostics_application()
    application.start()

    with pytest.raises(ValueError, match="incompatible diagnostic schema"):
        application.initialize_persistence(engine)
    assert "diagnostic_tasks" not in inspect(engine).get_table_names()
