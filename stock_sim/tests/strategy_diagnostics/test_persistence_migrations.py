from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from strategy_diagnostics import create_diagnostics_application


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

    assert first.current_revision == "0001_diagnostics_baseline"
    assert first.applied_revisions == ("0001_diagnostics_baseline",)
    assert second.current_revision == "0001_diagnostics_baseline"
    assert second.applied_revisions == ()
    assert application.status().persistence_status == "ready"
    assert application.status().persistence_revision == "0001_diagnostics_baseline"
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
    assert revisions == ["0001_diagnostics_baseline"]
