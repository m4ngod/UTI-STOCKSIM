# python
"""LendingPool 融资融券(融券)简单实现
设计目标(方案2部分):
  - 券商集中维护可出借库存 (symbol->shares)。
  - settings.BROKER_UNLIMITED_LENDING=True 时视为无限库存, borrow 总是成功。
  - 卖空流程:
      RiskEngine.validate 允许卖空 (库存检查) -> AccountService.freeze 在卖方可用不足时尝试借入缺口 borrowed
      -> 借入后临时将 position.quantity 增加 borrowed 再冻结 (使原流程无大改) -> 撮合成交 -> 结算后 position.quantity 下降, 可能为负(代表当前净空头)。
  - 回补流程: 买单结算时若旧仓位为负则计算覆盖收益并调整仓位, 覆盖全部后仓位可归零或转为多头。
  - 后续可扩展: 计息 / 强平 / 上限风控。
"""
from __future__ import annotations
from threading import RLock
from stock_sim.settings import settings

class LendingPool:
    def __init__(self):
        self._inventory: dict[str, float] = {}
        self._lock = RLock()

    def set_inventory(self, symbol: str, shares: float):
        with self._lock:
            self._inventory[symbol.upper()] = float(shares)

    def add_inventory(self, symbol: str, delta: float):
        if delta <= 0:
            return
        with self._lock:
            self._inventory[symbol.upper()] = self._inventory.get(symbol.upper(), 0.0) + float(delta)

    def available(self, symbol: str) -> float:
        if settings.BROKER_UNLIMITED_LENDING:
            return float('inf')
        return self._inventory.get(symbol.upper(), 0.0)

    def borrow(self, symbol: str, qty: float) -> bool:
        if qty <= 0:
            return True
        if settings.BROKER_UNLIMITED_LENDING:
            return True
        sym = symbol.upper()
        with self._lock:
            avail = self._inventory.get(sym, 0.0)
            if avail < qty:
                return False
            self._inventory[sym] = avail - qty
            return True

    def repay(self, symbol: str, qty: float):
        if qty <= 0:
            return
        if settings.BROKER_UNLIMITED_LENDING:
            return
        with self._lock:
            self._inventory[symbol.upper()] = self._inventory.get(symbol.upper(), 0.0) + float(qty)

# 全局实例
def get_lending_pool() -> LendingPool:
    global _LP
    try:
        return _LP
    except NameError:
        _LP = LendingPool()
        return _LP

