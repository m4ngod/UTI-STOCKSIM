from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

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

    assert first.current_revision == "0004_ai_recipe_assistant"
    assert first.applied_revisions == (
        "0001_diagnostics_baseline",
        "0002_historical_segment_catalog",
        "0003_scenario_recipe_lifecycle",
        "0004_ai_recipe_assistant",
    )
    assert second.current_revision == "0004_ai_recipe_assistant"
    assert second.applied_revisions == ()
    assert application.status().persistence_status == "ready"
    assert application.status().persistence_revision == "0004_ai_recipe_assistant"
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
    ]
    assert {
        "diagnostic_source_snapshots",
        "diagnostic_historical_segments",
        "diagnostic_recipe_drafts",
        "diagnostic_recipe_validations",
        "diagnostic_recipe_approvals",
        "diagnostic_recipe_versions",
        "diagnostic_ai_recipe_attempts",
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
    assert restarted_application.list_historical_segments() == (admitted.segment,)
    assert restarted_application.recommend_historical_segments()[0].segment == admitted.segment
