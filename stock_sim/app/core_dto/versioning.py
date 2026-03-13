"""Agent parameter versioning DTO."""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class AgentVersionDTO(BaseModel):
    version: int = Field(ge=0)
    created_at: int  # epoch ms
    author: str
    diff_json: Dict[str, Any]
    rollback_of: Optional[int] = None

__all__ = ["AgentVersionDTO"]

