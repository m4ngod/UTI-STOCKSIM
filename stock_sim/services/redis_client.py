from __future__ import annotations

"""Feature-flagged Redis client with safe local fallback.

Redis is optional in the current runtime. When the feature flag is off, the
library is missing, or the connection fails, callers receive ``None`` and can
continue through their local/PostgreSQL-backed path.
"""

import logging
import threading
import time
from typing import Any, Optional

try:
    import redis  # type: ignore
except Exception:  # noqa
    redis = None  # type: ignore

try:
    from stock_sim.settings import settings  # type: ignore
except Exception:  # noqa
    from settings import settings  # type: ignore

try:
    from stock_sim.observability.metrics import metrics  # type: ignore
except Exception:  # noqa
    from observability.metrics import metrics  # type: ignore

logger = logging.getLogger(__name__)

DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_REDIS_CONN_TIMEOUT = 1.0
RETRY_BACKOFF_SECONDS = 1.0

_lock = threading.RLock()
_cached: Optional[Any] = None
_last_fail_ts: float | None = None
_health_thread_started = False


def _redis_enabled() -> bool:
    return bool(getattr(settings, "REDIS_ENABLED", False))


def _redis_url() -> str:
    return str(getattr(settings, "REDIS_URL", DEFAULT_REDIS_URL))


def _redis_conn_timeout() -> float:
    return float(getattr(settings, "REDIS_CONN_TIMEOUT", DEFAULT_REDIS_CONN_TIMEOUT))


def _clear_cache() -> None:
    global _cached
    _cached = None


def get_redis() -> Optional[Any]:
    """Return a live Redis client, or ``None`` when Redis should be bypassed."""
    global _cached, _last_fail_ts

    if not _redis_enabled():
        return None

    if redis is None:
        metrics.inc("redis_fallback")
        return None

    with _lock:
        if _cached is not None:
            return _cached
        if _last_fail_ts and time.time() - _last_fail_ts < RETRY_BACKOFF_SECONDS:
            return None

        try:
            timeout = _redis_conn_timeout()
            cli = redis.Redis.from_url(
                _redis_url(),
                socket_timeout=timeout,
                socket_connect_timeout=timeout,
                decode_responses=True,
            )
            cli.ping()
            _cached = cli
            metrics.inc("redis_connect_success")
            return _cached
        except Exception:
            _last_fail_ts = time.time()
            _clear_cache()
            metrics.inc("redis_fallback")
            return None


def start_redis_health_log(interval_sec: float = 30.0) -> bool:
    """Start one daemon health logger when Redis is enabled.

    Returns ``True`` when a new thread is started and ``False`` when Redis is
    disabled or the thread was already running.
    """
    global _health_thread_started

    if not _redis_enabled():
        return False

    with _lock:
        if _health_thread_started:
            return False
        _health_thread_started = True

    thread = threading.Thread(
        target=_redis_health_loop,
        args=(max(1.0, float(interval_sec)),),
        name="redis-health-log",
        daemon=True,
    )
    thread.start()
    return True


def _redis_health_loop(interval_sec: float) -> None:
    while True:
        healthy = False
        client = get_redis()
        if client is not None:
            try:
                client.ping()
                healthy = True
            except Exception:
                with _lock:
                    _clear_cache()
                metrics.inc("redis_fallback")

        metrics.gauge("redis_healthy", 1.0 if healthy else 0.0)
        logger.info("redis_health healthy=%s enabled=%s", healthy, _redis_enabled())
        time.sleep(interval_sec)


__all__ = ["get_redis", "start_redis_health_log"]
