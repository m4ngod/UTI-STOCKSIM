"""Script Upload Rate Limiter (Spec Task 36)

需求: 每策略名 (script/strategy identifier) 1 小时内 >3 次上传需拒绝 (即允许 3 次, 第 4 次及以上被限流)。
符合 R9 AC4.

设计:
- 内存固定/滑动窗口: 记录每 key 的时间戳列表 (秒精度)。
- allow(key) 执行: 清理窗口外旧记录 -> 判断当前计数 >= limit 则拒绝 -> 否则追加并允许。
- 指标:
  * metrics.inc('script_upload_attempt') 每次调用
  * metrics.inc('script_upload_allowed') 允许
  * metrics.inc('script_upload_rate_limited') 拒绝
- 线程安全: RLock 保护 key map。
- 可注入 time_fn 便于测试 (虚拟推进时间)。

API:
- allow(key: str) -> bool  (True=允许, False=拒绝)
- get_remaining(key: str) -> int   剩余可用次数 (>=0)
- reset() 清空所有记录 (测试辅助)
- set_limit(limit: int, window_seconds: int) 动态调整 (测试/未来需求)
- get_script_rate_limiter(): 全局单例

边界与扩展:
- 若系统时间回退, 不特殊处理; 旧时间戳将自然在窗口外被清理。
- 未来可扩展持久化/分布式 (Redis 计数器 / 滑动窗口)。
"""
from __future__ import annotations
from typing import Dict, List, Callable
from threading import RLock
import time
from observability.metrics import metrics

__all__ = [
    'ScriptUploadRateLimiter', 'RateLimitExceeded', 'get_script_rate_limiter'
]

class RateLimitExceeded(RuntimeError):
    """Raised (可选使用) 当达到限制; 当前实现 allow 返回 False, 不默认抛异常。"""
    pass

TimeFn = Callable[[], float]

class ScriptUploadRateLimiter:
    def __init__(self, *, limit: int = 3, window_seconds: int = 3600, time_fn: TimeFn | None = None):
        self._limit = limit
        self._window = window_seconds
        self._time_fn = time_fn or time.time
        self._lock = RLock()
        self._events: Dict[str, List[float]] = {}

    # ------------- Public API -------------
    def allow(self, key: str) -> bool:
        now = self._time_fn()
        metrics.inc('script_upload_attempt')
        with self._lock:
            buf = self._events.get(key)
            if buf is None:
                buf = []
                self._events[key] = buf
            # 清理窗口外
            cutoff = now - self._window
            # 原地过滤 (小列表, 简化)
            if buf and buf[0] < cutoff:
                buf[:] = [ts for ts in buf if ts >= cutoff]
            if len(buf) >= self._limit:
                metrics.inc('script_upload_rate_limited')
                return False
            buf.append(now)
            metrics.inc('script_upload_allowed')
            return True

    def get_remaining(self, key: str) -> int:
        now = self._time_fn()
        with self._lock:
            buf = self._events.get(key, [])
            cutoff = now - self._window
            if buf and buf[0] < cutoff:
                buf = [ts for ts in buf if ts >= cutoff]
                self._events[key] = buf
            used = len(buf)
            remaining = self._limit - used
            return remaining if remaining >= 0 else 0

    def reset(self):  # 测试辅助
        with self._lock:
            self._events.clear()

    def set_limit(self, limit: int, window_seconds: int | None = None):
        with self._lock:
            self._limit = limit
            if window_seconds is not None:
                self._window = window_seconds

# ------------- Global Singleton -------------
_global_limiter: ScriptUploadRateLimiter | None = None

def get_script_rate_limiter() -> ScriptUploadRateLimiter:
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = ScriptUploadRateLimiter()
    return _global_limiter

