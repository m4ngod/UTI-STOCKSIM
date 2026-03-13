# file: simulation/market_replay.py
# python
from dataclasses import dataclass
from typing import Iterable, Callable

@dataclass
class ReplayEvent:
    ts: float
    symbol: str
    price: float
    qty: int

class MarketReplay:
    def __init__(self, events: Iterable[ReplayEvent]):
        self.events = sorted(events, key=lambda e: e.ts)

    def play(self, on_trade: Callable[[ReplayEvent], None]):
        for ev in self.events:
            on_trade(ev)