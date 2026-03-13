# 行情快照、指标计算
# MarketSnapshot
# • last_price
# • bid1/ask1…
# • vol_turnover（成交额）
# • turnover_rate（换手率）
# • kline_buffer（1m/1d/1w 等）

from dataclasses import dataclass, field
from collections import deque

@dataclass
class MarketSnapshot:
    ticker: str
    last_price: float
    volume: int
    turnover: float
    turnover_rate: float
    bid1: float | None = None
    ask1: float | None = None
    kline_1m: deque = field(default_factory=lambda: deque(maxlen=240))
    kline_1d: deque = field(default_factory=lambda: deque(maxlen=60))
