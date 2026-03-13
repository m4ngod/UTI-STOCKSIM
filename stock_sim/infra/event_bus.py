# python
# file: infra/event_bus.py
from __future__ import annotations
from collections import defaultdict, deque
from threading import RLock, Thread
from typing import Callable, Any, Dict, List, Deque, Optional
from concurrent.futures import ThreadPoolExecutor
try:
    from stock_sim.core.const import EventType  # type: ignore
except Exception:  # 回退本地
    from core.const import EventType  # type: ignore

class EventBus:
    def __init__(self, async_workers: int = 4):
        self._subs_sync: Dict[str, List[Callable[[str, dict], None]]] = defaultdict(list)
        self._subs_async: Dict[str, List[Callable[[str, dict], None]]] = defaultdict(list)
        self._lock = RLock()
        self._queue: Deque[tuple[str, dict]] = deque()
        self._executor = ThreadPoolExecutor(max_workers=async_workers)
        self._bg_thread: Optional[Thread] = None
        self._running = False
        self._persist_hook = None  # 新增: 可由事件持久化服务注入 callable(topic,payload)

    def start(self):
        if self._running:
            return
        self._running = True
        self._bg_thread = Thread(target=self._loop, daemon=True)
        self._bg_thread.start()

    def stop(self):
        self._running = False
        if self._bg_thread:
            self._bg_thread.join(timeout=1)

    def subscribe(self, topic: str | EventType, handler: Callable[[str, dict], None], *, async_mode: bool = False):
        key = topic.value if isinstance(topic, EventType) else topic
        with self._lock:
            target = self._subs_async if async_mode else self._subs_sync
            target[key].append(handler)
        return handler  # 返回 handler 方便上层保存用于取消

    def unsubscribe(self, topic: str | EventType, handler: Callable[[str, dict], None]):
        key = topic.value if isinstance(topic, EventType) else topic
        with self._lock:
            arr = self._subs_sync.get(key)
            if arr and handler in arr:
                try:
                    arr.remove(handler)
                except ValueError:
                    pass
            arr2 = self._subs_async.get(key)
            if arr2 and handler in arr2:
                try:
                    arr2.remove(handler)
                except ValueError:
                    pass

    def publish(self, topic: str | EventType, payload: dict):
        key = topic.value if isinstance(topic, EventType) else topic
        sync_handlers: List[Callable[[str, dict], None]]
        async_handlers: List[Callable[[str, dict], None]]
        with self._lock:
            sync_handlers = list(self._subs_sync.get(key, []))
            async_handlers = list(self._subs_async.get(key, []))
        # 同步
        for h in sync_handlers:
            try:
                h(key, payload)
            except TypeError:
                # 回退兼容: 旧式 handler 仅一个参数 (payload)
                try:
                    h(payload)
                except Exception:
                    pass
            except Exception:  # noqa
                pass
        # 异步
        if async_handlers:
            with self._lock:
                self._queue.append((key, payload))
            if not self._running:
                self.start()
        # 新增: 持久化钩子 (同步调用, 保证测��立即可见)
        hook = getattr(self, '_persist_hook', None)
        if hook:
            try:
                hook(key, payload)
            except Exception:
                pass

    def _loop(self):
        while self._running:
            item = None
            with self._lock:
                if self._queue:
                    item = self._queue.popleft()
            if not item:
                continue
            topic, payload = item
            handlers = []
            with self._lock:
                handlers = list(self._subs_async.get(topic, []))
            for h in handlers:
                self._executor.submit(self._safe_call, h, topic, payload)

    @staticmethod
    def _safe_call(h, topic, payload):
        try:
            h(topic, payload)
        except TypeError:
            try:
                h(payload)
            except Exception:
                pass
        except Exception:
            pass

event_bus = EventBus()