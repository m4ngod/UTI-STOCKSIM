"""AgentService (Spec Task 10)

职责 (R3 AC1/2/3/4):
- list_agents(): 列出 {id, 名称, 类型, 状态, 运行起始时间, 最近心跳, params_version}
- control(agent_id, action): 启动/暂停/停止 (action in start|pause|stop) → 更新状态 (AC2)
- batch_create_retail(config): 批量创建仅限 {Retail, MultiStrategyRetail}; 其他类型批量返回业务错误 AGENT_BATCH_UNSUPPORTED (修订要求)
- 日志: 创建后写入初始日志 “Agent Created” (AC4 与日志查看配合)
- tail_logs / page_logs: 读取日志滚动内容 (通过 LogStreamService)

实现策略:
- 内存模拟: 未对接真实后端, 使用 _synthetic_factory 生成 AgentMetaDTO
- 心跳: control(start) 时记录 start_time 与 last_heartbeat=当前; 后续可由外部调度器刷新
- 线程安全: RLock
- 错误模型: 统一 AgentServiceError(code, message)

指标 (metrics):
- agent_create_success / agent_create_fail
- agent_control_action_start|pause|stop
- agent_batch_unsupported

未来扩展 TODO:
- TODO: 对接真实后端 RPC (create_agent / control_agent / list_agents)
- TODO: 心跳刷新调度器 (定时更新 last_heartbeat)
- TODO: 运行参数/可热更新参数整合 VersionStore
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Literal, Any
import time
import threading

from observability.metrics import metrics
from app.core_dto.agent import AgentMetaDTO
from .log_stream_service import LogStreamService
from infra.event_bus import event_bus  # 新增：事件发布

ActionType = Literal["start", "pause", "stop"]
BATCH_ALLOWED_TYPES = {"Retail", "MultiStrategyRetail"}

class AgentServiceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

@dataclass
class BatchCreateConfig:
    count: int
    agent_type: str
    name_prefix: str = "agent"
    initial_cash: float = 100_000.0  # 占位 (未真正使用)
    strategies: Optional[List[str]] = None  # 对 MultiStrategyRetail 可能用到 (占位)

class AgentService:
    def __init__(self, *, log_stream: Optional[LogStreamService] = None):
        self._agents: Dict[str, AgentMetaDTO] = {}
        self._lock = threading.RLock()
        self._log = log_stream or LogStreamService()
        # 新增：MSR 计数器（会话内自增）
        self._msr_counter: int = 0

    # ------------- Public API -------------
    def list_agents(self) -> List[AgentMetaDTO]:  # R3 AC1
        with self._lock:
            return list(self._agents.values())

    def get(self, agent_id: str) -> Optional[AgentMetaDTO]:
        with self._lock:
            return self._agents.get(agent_id)

    def update_params_version(self, agent_id: str, new_version: int) -> AgentMetaDTO:
        """更新智能体参数版本号 (供配置控制器调用)."""
        with self._lock:
            ag = self._agents.get(agent_id)
            if ag is None:
                raise AgentServiceError("AGENT_NOT_FOUND", f"agent not found: {agent_id}")
            ag.params_version = new_version  # type: ignore[assignment]
            self._agents[agent_id] = ag
            return ag

    def control(self, agent_id: str, action: ActionType) -> AgentMetaDTO:  # R3 AC2
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                raise AgentServiceError("AGENT_NOT_FOUND", f"agent not found: {agent_id}")
            now = int(time.time()*1000)
            if action == "start":
                agent.status = "RUNNING"  # type: ignore[assignment]
                if agent.start_time is None:
                    agent.start_time = now
                agent.last_heartbeat = now
            elif action == "pause":
                agent.status = "PAUSED"  # type: ignore[assignment]
            elif action == "stop":
                agent.status = "STOPPED"  # type: ignore[assignment]
            else:  # 理论不可达
                raise AgentServiceError("INVALID_ACTION", action)
            metrics.inc(f"agent_control_action_{action}")
            self._agents[agent_id] = agent
            self._log.append(agent_id, f"Control action={action}")
            return agent

    def batch_create_retail(self, cfg: BatchCreateConfig) -> Dict[str, Any]:  # R3 AC3
        if cfg.count <= 0:
            return {"success_ids": [], "failed": ["INVALID_COUNT"]}
        if cfg.agent_type not in BATCH_ALLOWED_TYPES:
            metrics.inc("agent_batch_unsupported")
            raise AgentServiceError("AGENT_BATCH_UNSUPPORTED", f"type {cfg.agent_type} not allowed for batch")
        success: List[str] = []
        failed: List[str] = []
        created: List[AgentMetaDTO] = []
        now = int(time.time()*1000)
        with self._lock:
            for i in range(cfg.count):
                try:
                    if cfg.agent_type == "MultiStrategyRetail":
                        # 忽略 name_prefix，自动命名 MSR0001, MSR0002
                        self._msr_counter += 1
                        msr_id = f"MSR{self._msr_counter:04d}"
                        agent_id = msr_id
                        agent_name = msr_id
                    else:
                        agent_id = f"{cfg.agent_type[:3].lower()}-{cfg.name_prefix}-{now}-{i}"
                        agent_name = f"{cfg.name_prefix}-{i}"
                    if agent_id in self._agents:
                        failed.append(agent_id)
                        metrics.inc("agent_create_fail")
                        continue
                    meta = _synthetic_factory(agent_id=agent_id, name=agent_name, a_type=cfg.agent_type)
                    self._agents[agent_id] = meta
                    success.append(agent_id)
                    created.append(meta)
                    metrics.inc("agent_create_success")
                    # 若是多策略散户，发布账户创建事件（账户与 agent 同名）
                    if cfg.agent_type == "MultiStrategyRetail":
                        try:
                            event_bus.publish("account.created", {"account_id": agent_id, "initial_cash": cfg.initial_cash})
                        except Exception:
                            pass
                except Exception:  # noqa: BLE001
                    failed.append(f"{cfg.name_prefix}-{i}")
                    metrics.inc("agent_create_fail")
        # 初始日志写入 (锁外逐个)
        for m in created:
            self._log.generate_initial(m.agent_id)
        # 发布进度与完成事件（本次调用粒度）
        payload = {"success_ids": list(success), "failed": list(failed), "type": cfg.agent_type, "count": cfg.count, "initial_cash": cfg.initial_cash}
        try:
            event_bus.publish("agent.batch.create.progress", payload)
            event_bus.publish("agent.batch.create.completed", payload)
        except Exception:
            pass
        return {"success_ids": success, "failed": failed}

    def tail_logs(self, agent_id: str, n: int = 100) -> List[str]:  # R3 AC4
        return self._log.tail(agent_id, n)

    def page_logs(self, agent_id: str, page: int, page_size: int) -> List[str]:
        return self._log.page(agent_id, page, page_size)

# ------------- Synthetic factory -------------

def _synthetic_factory(*, agent_id: str, name: str, a_type: str) -> AgentMetaDTO:
    now = int(time.time()*1000)
    return AgentMetaDTO(
        agent_id=agent_id,
        name=name,
        type=a_type,
        status="STOPPED",
        start_time=None,
        last_heartbeat=None,
        params_version=0,
    )

__all__ = [
    "AgentService",
    "AgentServiceError",
    "BatchCreateConfig",
    "BATCH_ALLOWED_TYPES",
]
