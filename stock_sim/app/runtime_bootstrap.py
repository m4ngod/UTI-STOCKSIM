"""Frontend/runtime bootstrap helpers."""
from __future__ import annotations

from typing import Any, Dict


def start_runtime_support_services() -> Dict[str, Any]:
    status: Dict[str, Any] = {
        "snapshot_listener": False,
        "bar_aggregator": False,
        "instrument_restore": False,
        "instrument_restore_count": 0,
    }
    try:
        from stock_sim.services.snapshot_listener import ensure_snapshot_listener_started  # type: ignore
    except Exception:  # pragma: no cover
        try:
            from services.snapshot_listener import ensure_snapshot_listener_started  # type: ignore
        except Exception:
            ensure_snapshot_listener_started = None  # type: ignore
    try:
        from stock_sim.services.bar_aggregator import ensure_bar_aggregator_started  # type: ignore
    except Exception:  # pragma: no cover
        try:
            from services.bar_aggregator import ensure_bar_aggregator_started  # type: ignore
        except Exception:
            ensure_bar_aggregator_started = None  # type: ignore
    if callable(ensure_snapshot_listener_started):
        try:
            ensure_snapshot_listener_started()
            status["snapshot_listener"] = True
        except Exception:
            pass
    if callable(ensure_bar_aggregator_started):
        try:
            ensure_bar_aggregator_started()
            status["bar_aggregator"] = True
        except Exception:
            pass
    try:
        from app.runtime_gateway import RuntimeGateway

        result = RuntimeGateway().restore_runtime_instruments()
        status["instrument_restore"] = bool(result.get("ok"))
        status["instrument_restore_count"] = int(result.get("restored") or 0)
    except Exception:
        pass
    return status


__all__ = ["start_runtime_support_services"]
