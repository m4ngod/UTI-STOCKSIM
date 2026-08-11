"""Read-only production runtime boundary for Frontend V2 diagnostics."""

from __future__ import annotations

from threading import RLock
from typing import Any


class DiagnosticsRuntimeGateway:
    """Expose runtime query capabilities without any command dispatcher."""

    _READ_PREFIXES = ("get_", "list_")

    def __init__(self, query_service: Any | None = None) -> None:
        self._queries = query_service
        self._query_lock = RLock()

    def get_run_monitoring_snapshot(
        self,
        run_id: str,
    ) -> dict[str, Any] | None:
        result = self._query_service().get_run_monitoring_snapshot(run_id)
        if result is None:
            return None
        if not isinstance(result, dict):
            raise RuntimeError(
                "Run Monitoring query returned an invalid record"
            )
        return dict(result)

    def get_evidence_and_findings_snapshot(
        self,
        run_id: str,
    ) -> dict[str, Any] | None:
        result = self._query_service().get_evidence_and_findings_snapshot(run_id)
        if result is None:
            return None
        if not isinstance(result, dict):
            raise RuntimeError(
                "Evidence & Findings query returned an invalid record"
            )
        return dict(result)

    def __getattr__(self, name: str) -> Any:
        if not name.startswith(self._READ_PREFIXES):
            raise AttributeError(
                f"Read-only diagnostics runtime has no capability {name!r}"
            )
        capability = getattr(self._query_service(), name)
        if not callable(capability):
            raise AttributeError(name)
        return capability

    def _query_service(self) -> Any:
        queries = self._queries
        if queries is not None:
            return queries
        with self._query_lock:
            queries = self._queries
            if queries is None:
                from services.runtime_query_service import RuntimeQueryService

                queries = RuntimeQueryService()
                self._queries = queries
        return queries


__all__ = ["DiagnosticsRuntimeGateway"]
