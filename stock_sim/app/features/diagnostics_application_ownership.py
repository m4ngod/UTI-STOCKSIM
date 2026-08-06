"""Opaque ownership identity for live DiagnosticsApplication adapters."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Protocol, runtime_checkable
from uuid import uuid4
from weakref import WeakKeyDictionary


@dataclass(frozen=True, slots=True)
class DiagnosticsApplicationIdentity:
    """Process-local opaque proof that adapters share one application."""

    value: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.value, str)
            or len(self.value) != 32
            or any(character not in "0123456789abcdef" for character in self.value)
        ):
            raise ValueError(
                "Diagnostics application identity must be opaque lowercase hex"
            )


@runtime_checkable
class DiagnosticsApplicationOwned(Protocol):
    @property
    def application_identity(self) -> DiagnosticsApplicationIdentity: ...


_registry_lock = Lock()
_application_identities: WeakKeyDictionary[
    object,
    DiagnosticsApplicationIdentity,
] = WeakKeyDictionary()


def diagnostics_application_identity(
    application: object,
) -> DiagnosticsApplicationIdentity:
    """Return the stable opaque ownership identity for one live application."""

    with _registry_lock:
        identity = _application_identities.get(application)
        if identity is None:
            identity = DiagnosticsApplicationIdentity(uuid4().hex)
            _application_identities[application] = identity
        return identity


__all__ = [
    "DiagnosticsApplicationIdentity",
    "DiagnosticsApplicationOwned",
    "diagnostics_application_identity",
]
