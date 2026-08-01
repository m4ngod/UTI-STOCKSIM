"""Private serialization boundary for live DiagnosticsApplication adapters."""

from __future__ import annotations

from threading import Lock, RLock
from types import TracebackType
from typing import Protocol
from weakref import WeakKeyDictionary


class _ApplicationAccessGate(Protocol):
    def __enter__(self) -> object: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


_registry_lock = Lock()
_application_gates: WeakKeyDictionary[object, _ApplicationAccessGate] = (
    WeakKeyDictionary()
)


def shared_diagnostics_application_access_gate(
    application: object,
) -> _ApplicationAccessGate:
    """Return one private reentrant gate for adapters over one Application."""

    try:
        with _registry_lock:
            gate = _application_gates.get(application)
            if gate is None:
                gate = RLock()
                _application_gates[application] = gate
            return gate
    except TypeError:
        # Lightweight test doubles such as ``None`` need no cross-adapter
        # identity and cannot participate in weak-key registration.
        return RLock()
