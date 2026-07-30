"""Agent parameter versioning DTO."""
from __future__ import annotations
from typing import Optional, Dict, Any
from pydantic import Field

from ._compat import BaseModel

class AgentVersionDTO(BaseModel):
    version: int = Field(ge=0)
    created_at: int  # epoch ms
    author: str
    diff_json: Dict[str, Any]
    rollback_of: Optional[int] = None

__all__ = ["AgentVersionDTO"]

