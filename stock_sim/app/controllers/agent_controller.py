"""AgentController (Spec Task 21)

职责 (R3):
- 列出智能体元数据
- 控制 start/pause/stop
- 读取日志 (tail / page)
- 批量创建(仅零售类型: Retail / MultiStrategyRetail)  // 增量 Task 37

上层 UI 可轮询 list_agents() 与心跳字段, 控制操作后刷新。

限制:
- 批量创建仅允许 BATCH_ALLOWED_TYPES; 其它类型抛出 AGENT_BATCH_UNSUPPORTED
- 未来扩展: PPO/Transformer 等模型类仅支持单实例创建 (TODO: RL stats hook)

Future Hooks (Task50):
- TODO: RL 运行时统计 (reward_mean, episode_len) 聚合并注入 AgentMetaDTO 扩展字段
- TODO: Kafka 推送 Agent 状态 (AGENT_META_UPDATE -> kafka topic agents.meta)
- TODO: WebSocket 旁路广播 (供后续 Web UI 复用)
- TODO: 失败重启策略 (backoff 重启计划) 配置入口
"""
from __future__ import annotations
from typing import List, Dict, Any
from app.services.agent_service import (
    AgentService,
    ActionType,
    AgentServiceError,
    BATCH_ALLOWED_TYPES,
    BatchCreateConfig,
)
from app.core_dto.agent import AgentMetaDTO
from threading import RLock
from observability.metrics import metrics

__all__ = ["AgentController"]

class AgentController:
    def __init__(self, service: AgentService):
        self._service = service
        self._lock = RLock()

    def list_agents(self) -> List[AgentMetaDTO]:  # R3 AC1
        return self._service.list_agents()

    def control(self, agent_id: str, action: ActionType) -> AgentMetaDTO:  # R3 AC2
        return self._service.control(agent_id, action)

    def tail_logs(self, agent_id: str, n: int = 100) -> List[str]:  # R3 AC4
        return self._service.tail_logs(agent_id, n)

    def page_logs(self, agent_id: str, page: int, page_size: int) -> List[str]:  # R3 AC4
        return self._service.page_logs(agent_id, page, page_size)

    # --- 增量: 批量创建零售智能体 (Task 37) ---
    def batch_create(self, *, agent_type: str, count: int, name_prefix: str = "agent") -> Dict[str, Any]:
        """批量创建智能体 (仅限 Retail / MultiStrategyRetail)

        返回结构: { success_ids: list[str], failed: list[str] }
        错误:
          - 非允许类型 → AgentServiceError(code='AGENT_BATCH_UNSUPPORTED')
        """
        if agent_type not in BATCH_ALLOWED_TYPES:
            metrics.inc("agent_batch_unsupported")
            raise AgentServiceError("AGENT_BATCH_UNSUPPORTED", f"type {agent_type} not allowed for batch")
        cfg = BatchCreateConfig(count=count, agent_type=agent_type, name_prefix=name_prefix)
        return self._service.batch_create_retail(cfg)

