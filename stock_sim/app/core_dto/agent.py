"""Agent meta DTO."""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Literal

StatusType = Literal["RUNNING", "PAUSED", "STOPPED", "INACTIVE"]

class AgentMetaDTO(BaseModel):
    agent_id: str
    name: str
    type: str
    status: StatusType
    start_time: Optional[int] = None  # epoch ms
    last_heartbeat: Optional[int] = None  # epoch ms
    params_version: int = Field(ge=0)

__all__ = ["AgentMetaDTO", "StatusType"]

