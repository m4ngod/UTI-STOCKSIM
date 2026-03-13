# python
# file: services/risk_storage.py
from __future__ import annotations
from typing import Protocol, Dict
from threading import RLock

class RiskStorage(Protocol):
    def incr_day_notional(self, account_id: str, value: float) -> None: ...
    def get_day_notional(self, account_id: str) -> float: ...
    def reset_day(self) -> None: ...

class InMemoryRiskStorage:
    def __init__(self):
        self._day_notional: Dict[str, float] = {}
        self._lock = RLock()
    def incr_day_notional(self, account_id: str, value: float) -> None:
        if value <= 0:
            return
        with self._lock:
            self._day_notional[account_id] = self._day_notional.get(account_id, 0.0) + value
    def get_day_notional(self, account_id: str) -> float:
        with self._lock:
            return self._day_notional.get(account_id, 0.0)
    def reset_day(self) -> None:
        with self._lock:
            self._day_notional.clear()

