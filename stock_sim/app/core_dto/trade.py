"""Trade DTO definition."""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Literal

class TradeDTO(BaseModel):
    symbol: str
    price: float = Field(ge=0)
    qty: int = Field(ge=1)
    side: Literal["buy", "sell"]
    ts: int  # epoch ms

__all__ = ["TradeDTO"]

