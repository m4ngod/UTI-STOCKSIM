"""Headless logic panel for the Diagnostics workspace."""

from __future__ import annotations

from typing import Protocol


class _DiagnosticsState(Protocol):
    def to_dict(self) -> dict[str, object]: ...


class DiagnosticsApplicationPort(Protocol):
    def start(self) -> _DiagnosticsState: ...

    def status(self) -> _DiagnosticsState: ...


class DiagnosticsPanel:
    def __init__(self, application: DiagnosticsApplicationPort) -> None:
        self._application = application
        self._application.start()

    def get_view(self) -> dict[str, object]:
        return self._application.status().to_dict()


__all__ = ["DiagnosticsApplicationPort", "DiagnosticsPanel"]
