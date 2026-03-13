"""LogStreamService (Spec Task 10)

职责: 提供智能体日志的内存滚动缓冲读取 (R3 AC4)
- 追加日志 append(agent_id, line)
- 获取最近 N 条 tail(agent_id, n)
- 分页读取 page(agent_id, page, page_size)

实现:
- 使用 RingBuffer[str] (Task 5) 每个 agent 独立实例, 默认容量 2000 行
- 线程安全 (RLock)
- 结构化指标: metrics.inc("logstream_append")
- 初次访问若不存在缓冲按需创建 (懒加载)

未来扩展 TODO:
- TODO: 支持持久化到文件并按需回放
- TODO: 支持按关键字过滤 / severity 级别
"""
from __future__ import annotations
from typing import Dict, List
import time
import threading

from observability.metrics import metrics
from app.utils.ring_buffer import RingBuffer

class LogStreamService:
    def __init__(self, *, capacity: int = 2000):
        self._capacity = capacity
        self._buffers: Dict[str, RingBuffer[str]] = {}
        self._lock = threading.RLock()

    # -------- internal helpers --------
    def _get_buf(self, agent_id: str) -> RingBuffer[str]:
        buf = self._buffers.get(agent_id)
        if buf is None:
            buf = RingBuffer[str](self._capacity, metrics_prefix="agent_log")
            self._buffers[agent_id] = buf
        return buf

    # -------- public API --------
    def append(self, agent_id: str, line: str):
        ts = int(time.time() * 1000)
        msg = f"{ts} {line}"  # 简单时间前缀
        with self._lock:
            self._get_buf(agent_id).append(msg)
        metrics.inc("logstream_append")

    def tail(self, agent_id: str, n: int = 100) -> List[str]:  # 最近 n 行
        if n <= 0:
            return []
        with self._lock:
            buf = self._buffers.get(agent_id)
            if not buf:
                return []
            data = buf.to_list()
        if not data:
            return []
        return data[-n:]

    def page(self, agent_id: str, page: int, page_size: int) -> List[str]:
        if page < 1 or page_size <= 0:
            return []
        with self._lock:
            buf = self._buffers.get(agent_id)
            if not buf:
                return []
            data = buf.to_list()
        total = len(data)
        start = (page - 1) * page_size
        if start >= total:
            return []
        end = min(start + page_size, total)
        return data[start:end]

    def generate_initial(self, agent_id: str):  # 供 AgentService 在创建后写入初始日志
        self.append(agent_id, "Agent Created")

__all__ = ["LogStreamService"]

