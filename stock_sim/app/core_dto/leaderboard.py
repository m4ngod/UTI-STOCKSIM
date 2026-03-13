"""Leaderboard row DTO."""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional

class LeaderboardRowDTO(BaseModel):
    agent_id: str
    return_pct: float
    annualized: Optional[float] = None
    sharpe: Optional[float] = None
    max_drawdown: Optional[float] = None
    win_rate: Optional[float] = None
    equity: Optional[float] = None
    rank: int = Field(ge=1)
    rank_delta: Optional[int] = None

__all__ = ["LeaderboardRowDTO"]

