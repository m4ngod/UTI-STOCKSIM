"""Agent meta DTO."""
from __future__ import annotations
from typing import Optional, Literal
from pydantic import Field

from ._compat import BaseModel

StatusType = Literal["RUNNING", "PAUSED", "STOPPED", "INACTIVE"]

class AgentMetaDTO(BaseModel):
    agent_id: str
    name: str
    type: str
    status: StatusType
    start_time: Optional[int] = None  # epoch ms
    last_heartbeat: Optional[int] = None  # epoch ms
    params_version: int = Field(ge=0)
    strategy: Optional[str] = None
    model_id: Optional[str] = None
    mode: Optional[str] = None
    episode_id: Optional[str] = None
    last_reward: Optional[float] = None
    equity: Optional[float] = None
    pnl: Optional[float] = None
    last_action: Optional[str] = None

__all__ = ["AgentMetaDTO", "StatusType"]

