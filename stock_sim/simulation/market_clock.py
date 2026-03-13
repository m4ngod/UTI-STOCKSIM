# file: simulation/market_clock.py
# python
import time
from datetime import datetime, timedelta
from typing import Callable, List

class MarketClock:
    def __init__(self, start: datetime, end: datetime, step: timedelta):
        self.current = start
        self.end = end
        self.step = step
        self._listeners: List[Callable[[datetime], None]] = []

    def on_tick(self, cb: Callable[[datetime], None]):
        self._listeners.append(cb)

    def run(self):
        while self.current <= self.end:
            for cb in self._listeners:
                cb(self.current)
            self.current += self.step