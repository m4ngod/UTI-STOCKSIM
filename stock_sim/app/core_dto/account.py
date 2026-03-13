"""Account & Position DTO definitions.
Aligned with design document Data Models.
"""
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field, validator

class PositionDTO(BaseModel):
    symbol: str
    quantity: int = Field(ge=0)
    frozen_qty: int = Field(ge=0)
    avg_price: float = Field(ge=0)
    borrowed_qty: int = Field(ge=0)
    pnl_unreal: Optional[float] = None

class AccountDTO(BaseModel):
    account_id: str
    cash: float
    frozen_cash: float = 0.0
    positions: List[PositionDTO] = Field(default_factory=list)
    realized_pnl: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    equity: float
    utilization: float = Field(ge=0, le=1)
    snapshot_id: str
    sim_day: str  # YYYY-MM-DD

    @validator("equity")
    def equity_non_negative(cls, v: float):
        if v < 0:
            raise ValueError("equity must be >=0")
        return v

    @validator("cash")
    def cash_non_negative(cls, v: float):
        if v < 0:
            raise ValueError("cash must be >=0")
        return v

__all__ = [
    "PositionDTO",
    "AccountDTO",
]
