from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

try:
    from stock_sim.persistence.models_event_log import EventLog  # type: ignore
    from stock_sim.persistence.models_imports import SessionLocal  # type: ignore
    from stock_sim.observability.metrics import metrics  # type: ignore
    from stock_sim.infra.event_bus import event_bus  # type: ignore
    from stock_sim.settings import settings  # type: ignore
    from stock_sim.services.sim_clock import current_sim_day, virtual_datetime  # type: ignore
except Exception:  # noqa
    from persistence.models_event_log import EventLog  # type: ignore
    from persistence.models_imports import SessionLocal  # type: ignore
    from observability.metrics import metrics  # type: ignore
    from infra.event_bus import event_bus  # type: ignore
    from settings import settings  # type: ignore
    from services.sim_clock import current_sim_day, virtual_datetime  # type: ignore

_ENABLED = False


def _extract_symbol(payload: dict[str, Any]) -> str | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("symbol"):
        return payload.get("symbol")
    trade = payload.get("trade")
    if isinstance(trade, dict) and trade.get("symbol"):
        return trade.get("symbol")
    order = payload.get("order")
    if isinstance(order, dict) and order.get("symbol"):
        return order.get("symbol")
    return None


def _extract_run_id(payload: dict[str, Any]) -> str | None:
    if not isinstance(payload, dict):
        return None
    run_id = payload.get("run_id")
    if run_id:
        return run_id
    trade = payload.get("trade")
    if isinstance(trade, dict) and trade.get("run_id"):
        return trade.get("run_id")
    order = payload.get("order")
    if isinstance(order, dict) and order.get("run_id"):
        return order.get("run_id")
    return None


def _extract_sim_day(payload: dict[str, Any]) -> int | None:
    if not isinstance(payload, dict):
        return None
    sim_day = payload.get("sim_day")
    if sim_day is not None:
        return sim_day
    return current_sim_day()


def _extract_sim_dt(payload: dict[str, Any], sim_day: int | None):
    if not isinstance(payload, dict):
        return virtual_datetime(sim_day) if sim_day is not None else None
    sim_dt = payload.get("sim_dt")
    if isinstance(sim_dt, str):
        try:
            return datetime.fromisoformat(sim_dt.replace('Z', '+00:00')).replace(tzinfo=None)
        except Exception:
            sim_dt = None
    if sim_dt is not None:
        return sim_dt
    return virtual_datetime(sim_day) if sim_day is not None else None


def _sync_write(evt_type: Any, payload: dict[str, Any]):
    evt_name = evt_type.value if hasattr(evt_type, "value") else str(evt_type)
    sim_day = _extract_sim_day(payload)
    sim_dt = _extract_sim_dt(payload, sim_day)
    session = SessionLocal()
    try:
        ev = EventLog(
            ts_ms=int(time.time() * 1000),
            type=evt_name,
            symbol=_extract_symbol(payload),
            run_id=_extract_run_id(payload),
            sim_day=sim_day,
            sim_dt=sim_dt,
            payload=json.dumps(payload, ensure_ascii=False),
        )
        session.add(ev)
        session.commit()
        try:
            metrics.inc("event_persist_written", 1)
        except Exception:
            pass
    except Exception:
        session.rollback()
        try:
            metrics.inc("event_persist_failures", 1)
        except Exception:
            pass
    finally:
        session.close()


def enable_event_persistence(force: bool = False):
    global _ENABLED
    if _ENABLED:
        return True
    if not getattr(settings, 'EVENT_PERSIST_ENABLED', True) and not force:
        return False

    def _hook(topic: str, payload: dict[str, Any]):
        try:
            _sync_write(topic, payload)
        except Exception:
            pass

    event_bus._persist_hook = _hook
    event_bus._event_persist_enabled = True
    _ENABLED = True
    return True


def disable_event_persistence():
    global _ENABLED
    event_bus._persist_hook = None
    event_bus._event_persist_enabled = False
    _ENABLED = False
    return True


__all__ = [
    "enable_event_persistence",
    "disable_event_persistence",
]
