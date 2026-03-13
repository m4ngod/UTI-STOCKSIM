"""Clock state DTO."""
from __future__ import annotations
from pydantic import BaseModel
from typing import Literal

ClockStatus = Literal["RUNNING", "PAUSED", "STOPPED"]

class ClockStateDTO(BaseModel):
    status: ClockStatus
    sim_day: str  # YYYY-MM-DD
    speed: float  # compression ratio
    ts: int       # epoch ms

__all__ = ["ClockStateDTO", "ClockStatus"]

