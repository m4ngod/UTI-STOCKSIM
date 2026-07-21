"""Headless application boundary for the Strategy Diagnostics Laboratory."""

from __future__ import annotations

from dataclasses import dataclass, replace

from sqlalchemy.engine import Engine

from .persistence import (
    DIAGNOSTIC_SCHEMA_REVISION,
    DiagnosticMigrationReport,
    initialize_diagnostic_persistence,
)


@dataclass(frozen=True, slots=True)
class DiagnosticsApplicationState:
    """User-visible state returned by the diagnostic application boundary."""

    product: str
    workspace: str
    status: str
    message: str
    persistence_status: str
    persistence_revision: str | None
    supported_persistence_revision: str

    def to_dict(self) -> dict[str, object]:
        return {
            "product": self.product,
            "workspace": self.workspace,
            "status": self.status,
            "message": self.message,
            "persistence_status": self.persistence_status,
            "persistence_revision": self.persistence_revision,
            "supported_persistence_revision": self.supported_persistence_revision,
        }


class DiagnosticsApplication:
    """Small product interface shared by headless and presentation adapters."""

    def __init__(self) -> None:
        self._state: DiagnosticsApplicationState | None = None

    def start(self) -> DiagnosticsApplicationState:
        if self._state is None:
            self._state = DiagnosticsApplicationState(
                product="Strategy Diagnostics Laboratory",
                workspace="Diagnostics",
                status="ready",
                message="Diagnostics workspace is ready.",
                persistence_status="not_initialized",
                persistence_revision=None,
                supported_persistence_revision=DIAGNOSTIC_SCHEMA_REVISION,
            )
        return self._state

    def initialize_persistence(self, engine: Engine) -> DiagnosticMigrationReport:
        report = initialize_diagnostic_persistence(engine)
        state = self.start()
        self._state = replace(
            state,
            persistence_status="ready",
            persistence_revision=report.current_revision,
        )
        return report

    def status(self) -> DiagnosticsApplicationState:
        if self._state is None:
            raise RuntimeError("Diagnostics application has not been started")
        return self._state


def create_diagnostics_application() -> DiagnosticsApplication:
    return DiagnosticsApplication()


__all__ = [
    "DIAGNOSTIC_SCHEMA_REVISION",
    "DiagnosticsApplication",
    "DiagnosticsApplicationState",
    "create_diagnostics_application",
]
