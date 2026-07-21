"""Headless application boundary for the Strategy Diagnostics Laboratory."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .persistence import DIAGNOSTIC_SCHEMA_REVISION


@dataclass(frozen=True, slots=True)
class DiagnosticsApplicationState:
    """User-visible state returned by the diagnostic application boundary."""

    product: str
    workspace: str
    status: str
    message: str
    persistence_revision: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


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
                persistence_revision=DIAGNOSTIC_SCHEMA_REVISION,
            )
        return self._state

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
