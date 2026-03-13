"""RedisSubscriber 服务

职责:
- 可选连接 Redis 订阅指定频道
- 接收消息回调 on_message(channel, data)
- 连接失败或中途异常 -> 标记 fallback 并停止内部线程 (由上层回退本地 EventBus)
- 允许注入 client_factory 以便测试模拟异常 / 伪客户端

设计要点:
- 不做复杂重试 (任务4 只需断线 fallback 行为 & 计数)
- 线程安全停止
"""
from __future__ import annotations
from typing import Callable, List, Optional, Any
from threading import Thread, Event
import json

try:
    import redis  # type: ignore
except Exception:  # noqa
    redis = None  # type: ignore

from observability.metrics import metrics

class RedisSubscriber:
    def __init__(
        self,
        channels: List[str],
        on_message: Callable[[str, Any], None],
        *,
        client_factory: Optional[Callable[[], Any]] = None,
        decode_responses: bool = True,
    ):
        self.channels = channels
        self.on_message = on_message
        self.client_factory = client_factory or self._default_factory
        self.decode_responses = decode_responses
        self._th: Optional[Thread] = None
        self._stop_evt = Event()
        self._fallback = False
        self._started = False

    @property
    def fallback(self) -> bool:
        return self._fallback

    def start(self):
        if self._started:
            return
        self._started = True
        self._th = Thread(target=self._run, daemon=True)
        self._th.start()

    def stop(self):
        self._stop_evt.set()
        if self._th:
            self._th.join(timeout=1)

    # ---- Internals --------------------------------------------------
    def _default_factory(self):
        if redis is None:  # 未安装 redis 库
            raise RuntimeError("redis library missing")
        return redis.Redis(host="localhost", port=6379, decode_responses=self.decode_responses)

    def _run(self):
        try:
            client = self.client_factory()
            pubsub = client.pubsub()
            pubsub.subscribe(*self.channels)
            for item in pubsub.listen():  # 阻塞迭代
                if self._stop_evt.is_set():
                    break
                if not item or item.get("type") != "message":
                    continue
                channel = item.get("channel")
                data = item.get("data")
                # 尝试解析 JSON
                if isinstance(data, str):
                    try:
                        data_obj = json.loads(data)
                    except Exception:
                        data_obj = {"raw": data}
                else:
                    data_obj = data
                try:
                    self.on_message(channel, data_obj)
                except Exception:
                    pass
        except Exception:
            self._fallback = True
            metrics.inc("redis_fallback")
        finally:
            # 结束: 若线程退出且未 stop 显示调用, 标记 fallback (保证异常/中断也计数)
            if not self._fallback and not self._stop_evt.is_set():
                self._fallback = True
                metrics.inc("redis_fallback")

__all__ = ["RedisSubscriber"]

