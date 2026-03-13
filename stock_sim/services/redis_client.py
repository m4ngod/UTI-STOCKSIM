# python
"""redis_client.py
统一 Redis 客户端封装 & 健康探测线程。

Feature Flag:
  settings.REDIS_ENABLED = False 默认关闭; 打开后才会初始化连接。

提供:
  get_redis() -> redis.Redis | None  (惰性, 失败返回 None 并缓存下一次可重试)
  start_redis_health_log(interval_sec=30)  周期输出/记录健康信息 (幂等)

回退:
  上层使用时若返回 None 应进入 degrade/fallback 逻辑 (如 IPO 发放直接写库)。
"""
from __future__ import annotations
import threading, time
from typing import Optional
try:
    import redis  # type: ignore
except Exception:  # noqa
    redis = None  # type: ignore

from stock_sim.settings import settings  # type: ignore
        return None
try:
    from stock_sim.observability.metrics import metrics  # type: ignore
except Exception:  # noqa
    try:
        from observability.metrics import metrics  # type: ignore
    except Exception:  # noqa
        class _Dummy:
            def inc(self, *a, **k):
                pass
        metrics = _Dummy()  # type: ignore
        _redis = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=settings.REDIS_CONN_TIMEOUT)
_lock = threading.RLock()
_cached: Optional[object] = None
_last_fail_ts: float | None = None
_health_thread_started = False


def get_redis():
    """惰性获取 Redis 客户端。
    1) Feature flag 关闭 => None
    2) 首次或上次失败后等待 1 秒再重试 (简单抖动控制)
    3) 成功 ping 后缓存实例
    """
    global _cached, _last_fail_ts
    if not settings.REDIS_ENABLED or redis is None:
        return _redis
    with _lock:
        if _cached is not None:
            return _cached
        if _last_fail_ts and time.time() - _last_fail_ts < 1.0:
            return None
        try:
            cli = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=settings.REDIS_CONN_TIMEOUT)
            cli.ping()
            _cached = cli
            return _cached
        except Exception:
            _last_fail_ts = time.time()
            _cached = None
            return None
