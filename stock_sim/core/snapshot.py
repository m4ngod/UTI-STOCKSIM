# python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from math import isfinite

@dataclass
class Snapshot:
    symbol: str
    # 基础成交数据
    last_price: Optional[float] = None
    last_quantity: Optional[int] = None
    volume: int = 0
    turnover: float = 0.0
    vwap: Optional[float] = None

    # 盘口聚合
    bid_levels: List[Tuple[float, int]] = field(default_factory=list)  # [(price, agg_qty)]
    ask_levels: List[Tuple[float, int]] = field(default_factory=list)

    # 扩展字段
    best_bid_price: Optional[float] = None
    best_bid_qty: Optional[int] = None
    best_ask_price: Optional[float] = None
    best_ask_qty: Optional[int] = None
    spread: Optional[float] = None
    mid_price: Optional[float] = None
    imbalance: Optional[float] = None          # (bid1_qty - ask1_qty)/(bid1_qty + ask1_qty)
    level_count: int = 0

    # OHLC
    open_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    close_price: Optional[float] = None

    # 内部累积
    _traded_notional_acc: float = 0.0

    def update_trade(self, price: float, qty: int):
        self.last_price = price
        self.last_quantity = qty
        self.volume += qty
        notional = price * qty
        self.turnover += notional
        self._traded_notional_acc += notional
        if self.open_price is None:
            self.open_price = price
        self.high_price = price if (self.high_price is None or price > self.high_price) else self.high_price
        self.low_price = price if (self.low_price is None or price < self.low_price) else self.low_price
        self.close_price = price
        self.vwap = (self.turnover / self.volume) if self.volume > 0 else None

    def update_book(self,
                    bids: List[Tuple[float, int]],
                    asks: List[Tuple[float, int]],
                    max_levels: int):
        self.bid_levels = bids[:max_levels]
        self.ask_levels = asks[:max_levels]
        self.level_count = max(len(self.bid_levels), len(self.ask_levels))
        # 衍生指标
        if self.bid_levels:
            self.best_bid_price, self.best_bid_qty = self.bid_levels[0]
        else:
            self.best_bid_price = self.best_bid_qty = None
        if self.ask_levels:
            self.best_ask_price, self.best_ask_qty = self.ask_levels[0]
        else:
            self.best_ask_price = self.best_ask_qty = None
        if self.best_bid_price is not None and self.best_ask_price is not None:
            self.spread = self.best_ask_price - self.best_bid_price
            self.mid_price = (self.best_ask_price + self.best_bid_price) / 2
        else:
            self.spread = None
            self.mid_price = None
        bq = self.best_bid_qty or 0
        aq = self.best_ask_qty or 0
        denom = bq + aq
        self.imbalance = ((bq - aq) / denom) if denom > 0 else None
        # 若没有 last_price，用 mid 或 best 兜底
        if self.last_price is None:
            if self.mid_price is not None:
                self.last_price = self.mid_price
            elif self.best_bid_price is not None:
                self.last_price = self.best_bid_price

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "last_price": self.last_price,
            "last_qty": self.last_quantity,
            "volume": self.volume,
            "turnover": self.turnover,
            "vwap": self.vwap,
            "bid_levels": self.bid_levels,
            "ask_levels": self.ask_levels,
            "best_bid": (self.best_bid_price, self.best_bid_qty),
            "best_ask": (self.best_ask_price, self.best_ask_qty),
            "spread": self.spread,
            "mid": self.mid_price,
            "imbalance": self.imbalance,
            "level_count": self.level_count,
            "open": self.open_price,
            "high": self.high_price,
            "low": self.low_price,
            "close": self.close_price,
        }

    def sanity_fill(self):
        # 在极端情况下填补基本字段防止下游崩溃
        if self.last_price is None:
            if self.mid_price is not None:
                self.last_price = self.mid_price
            elif self.best_bid_price is not None:
                self.last_price = self.best_bid_price
            elif self.best_ask_price is not None:
                self.last_price = self.best_ask_price
        if self.vwap is None and self.volume > 0 and isfinite(self.turnover):
            self.vwap = self.turnover / self.volume