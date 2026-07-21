"""Trade DTO definition."""
from __future__ import annotations
from typing import Literal
from pydantic import Field

from ._compat import BaseModel

class TradeDTO(BaseModel):
    symbol: str
    price: float = Field(ge=0)
    qty: int = Field(ge=1)
    side: Literal["buy", "sell"]
    ts: int  # epoch ms

__all__ = ["TradeDTO"]

