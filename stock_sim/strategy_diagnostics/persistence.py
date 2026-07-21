"""Versioned persistence baseline owned by the diagnostic product path."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

from sqlalchemy import text
from sqlalchemy.engine import Engine


DIAGNOSTIC_SCHEMA_REVISION: Final = "0001_diagnostics_baseline"
_MIGRATION_TABLE: Final = "diagnostic_schema_migrations"


@dataclass(frozen=True, slots=True)
class DiagnosticMigrationReport:
    current_revision: str
    applied_revisions: tuple[str, ...]


def initialize_diagnostic_persistence(engine: Engine) -> DiagnosticMigrationReport:
    """Apply diagnostic-only migrations without touching legacy metadata."""

    applied_revisions: list[str] = []
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE TABLE IF NOT EXISTS {_MIGRATION_TABLE} ("
            "revision VARCHAR(128) PRIMARY KEY NOT NULL, "
            "applied_at_utc VARCHAR(64) NOT NULL"
            ")"
        )
        existing = connection.execute(
            text(
                f"SELECT revision FROM {_MIGRATION_TABLE} "
                "WHERE revision = :revision"
            ),
            {"revision": DIAGNOSTIC_SCHEMA_REVISION},
        ).scalar_one_or_none()
        if existing is None:
            connection.execute(
                text(
                    f"INSERT INTO {_MIGRATION_TABLE} "
                    "(revision, applied_at_utc) VALUES (:revision, :applied_at_utc)"
                ),
                {
                    "revision": DIAGNOSTIC_SCHEMA_REVISION,
                    "applied_at_utc": datetime.now(timezone.utc).isoformat(),
                },
            )
            applied_revisions.append(DIAGNOSTIC_SCHEMA_REVISION)

    return DiagnosticMigrationReport(
        current_revision=DIAGNOSTIC_SCHEMA_REVISION,
        applied_revisions=tuple(applied_revisions),
    )


__all__ = [
    "DIAGNOSTIC_SCHEMA_REVISION",
    "DiagnosticMigrationReport",
    "initialize_diagnostic_persistence",
]
