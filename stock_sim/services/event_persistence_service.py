from __future__ import annotations

import atexit
import json
import os
import queue
import threading
import time
from datetime import datetime
from typing import Any

try:
    from stock_sim.persistence import models_init  # type: ignore
    from stock_sim.persistence.models_event_log import EventLog  # type: ignore
    from stock_sim.persistence.models_imports import SessionLocal  # type: ignore
    from stock_sim.observability.metrics import metrics  # type: ignore
    from stock_sim.infra.event_bus import event_bus  # type: ignore
    from stock_sim.settings import settings  # type: ignore
    from stock_sim.services.sim_clock import current_sim_day, virtual_datetime  # type: ignore
except Exception:  # noqa
    from persistence import models_init  # type: ignore
    from persistence.models_event_log import EventLog  # type: ignore
    from persistence.models_imports import SessionLocal  # type: ignore
    from observability.metrics import metrics  # type: ignore
    from infra.event_bus import event_bus  # type: ignore
    from settings import settings  # type: ignore
    from services.sim_clock import current_sim_day, virtual_datetime  # type: ignore

_ENABLED = False
_ASYNC_ENABLED = False
_QUEUE: queue.Queue[tuple[Any, dict[str, Any]]] | None = None
_STOP_EVT = threading.Event()
_WORKER: threading.Thread | None = None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


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


def _extract_ts_ms(payload: dict[str, Any]) -> int:
    if isinstance(payload, dict):
        for candidate in (
            payload.get("ts_ms"),
            payload.get("ts"),
            payload.get("snapshot", {}).get("ts_ms") if isinstance(payload.get("snapshot"), dict) else None,
            payload.get("snapshot", {}).get("ts") if isinstance(payload.get("snapshot"), dict) else None,
            payload.get("trade", {}).get("ts_ms") if isinstance(payload.get("trade"), dict) else None,
            payload.get("trade", {}).get("ts") if isinstance(payload.get("trade"), dict) else None,
        ):
            if candidate is None:
                continue
            try:
                return int(candidate)
            except Exception:
                continue
    return int(time.time() * 1000)


def _sync_write(evt_type: Any, payload: dict[str, Any]):
    evt_name = evt_type.value if hasattr(evt_type, "value") else str(evt_type)
    sim_day = _extract_sim_day(payload)
    sim_dt = _extract_sim_dt(payload, sim_day)
    ts_ms = _extract_ts_ms(payload)
    schema_lock = getattr(models_init, "_SCHEMA_LOCK", None)
    if schema_lock is not None:
        schema_lock.acquire()
    try:
        for attempt in range(3):
            session = SessionLocal()
            try:
                ev = EventLog(
                    ts_ms=ts_ms,
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
                return
            except Exception:
                session.rollback()
                if attempt < 2:
                    try:
                        EventLog.__table__.create(bind=session.get_bind(), checkfirst=True)
                    except Exception:
                        pass
                    time.sleep(0.05 * (attempt + 1))
                    continue
                try:
                    metrics.inc("event_persist_failures", 1)
                except Exception:
                    pass
            finally:
                session.close()
    finally:
        if schema_lock is not None:
            schema_lock.release()


def _start_async_worker() -> None:
    global _QUEUE, _WORKER
    if _QUEUE is None:
        _QUEUE = queue.Queue(maxsize=max(1, _env_int("STOCKSIM_EVENT_PERSIST_MAX_QUEUE", 20000)))
    if _WORKER is not None and _WORKER.is_alive():
        return
    _STOP_EVT.clear()
    _WORKER = threading.Thread(
        target=_async_worker_loop,
        name="EventPersistenceWriter",
        daemon=True,
    )
    _WORKER.start()
    atexit.register(flush_event_persistence)


def _async_worker_loop() -> None:
    q = _QUEUE
    if q is None:
        return
    while not _STOP_EVT.is_set() or not q.empty():
        try:
            topic, payload = q.get(timeout=0.25)
        except queue.Empty:
            continue
        try:
            _sync_write(topic, payload)
        finally:
            try:
                q.task_done()
            except Exception:
                pass


def _async_write(evt_type: Any, payload: dict[str, Any]) -> None:
    q = _QUEUE
    if q is None:
        _sync_write(evt_type, payload)
        return
    try:
        q.put_nowait((evt_type, dict(payload)))
    except queue.Full:
        try:
            metrics.inc("event_persist_dropped", 1)
        except Exception:
            pass


def flush_event_persistence(timeout: float = 1.0) -> bool:
    q = _QUEUE
    if q is None:
        return True
    stop_at = time.monotonic() + max(0.0, float(timeout))
    while getattr(q, "unfinished_tasks", 0) and time.monotonic() < stop_at:
        time.sleep(0.01)
    return not bool(getattr(q, "unfinished_tasks", 0))


def _stop_async_worker() -> None:
    global _WORKER
    flush_event_persistence(timeout=1.0)
    _STOP_EVT.set()
    worker = _WORKER
    if worker is not None and worker.is_alive():
        worker.join(timeout=1.0)
    _WORKER = None


def enable_event_persistence(force: bool = False):
    global _ASYNC_ENABLED, _ENABLED
    if _ENABLED:
        return True
    if not getattr(settings, 'EVENT_PERSIST_ENABLED', True) and not force:
        return False
    _ASYNC_ENABLED = (not force) and _env_bool("STOCKSIM_EVENT_PERSIST_ASYNC", True)
    if _ASYNC_ENABLED:
        _start_async_worker()

    def _hook(topic: str, payload: dict[str, Any]):
        try:
            if _ASYNC_ENABLED:
                _async_write(topic, payload)
            else:
                _sync_write(topic, payload)
        except Exception:
            pass

    event_bus._persist_hook = _hook
    event_bus._persist_flush = flush_event_persistence
    event_bus._event_persist_enabled = True
    _ENABLED = True
    return True


def disable_event_persistence():
    global _ASYNC_ENABLED, _ENABLED
    event_bus._persist_hook = None
    event_bus._persist_flush = None
    event_bus._event_persist_enabled = False
    if _ASYNC_ENABLED:
        _stop_async_worker()
    _ASYNC_ENABLED = False
    _ENABLED = False
    return True


__all__ = [
    "enable_event_persistence",
    "disable_event_persistence",
    "flush_event_persistence",
]
