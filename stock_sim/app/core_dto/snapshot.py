"""Snapshot & related market data DTOs."""
from __future__ import annotations
from typing import List, Tuple
from pydantic import BaseModel, Field

Level = Tuple[float, float]  # price, qty

class SnapshotDTO(BaseModel):
    symbol: str
    last: float
    bid_levels: List[Level] = Field(default_factory=list)
    ask_levels: List[Level] = Field(default_factory=list)
    volume: int = 0
    turnover: float = 0.0
    ts: int  # epoch ms
    snapshot_id: str

__all__ = ["SnapshotDTO", "Level"]

