# file: simulation/ipo_allocator.py
# python
from dataclasses import dataclass
from typing import Dict

@dataclass
class Allocation:
    account_id: str
    symbol: str
    quantity: int
    price: float

class IPOAllocator:
    def allocate(self, demand: Dict[str, int], total: int, price: float, symbol: str) -> list[Allocation]:
        total_demand = sum(demand.values()) or 1
        allocs = []
        remain = total
        # 简单比例分配
        for aid, want in demand.items():
            qty = min(want, max(1, int(total * want / total_demand)))
            qty = min(qty, remain)
            remain -= qty
            allocs.append(Allocation(aid, symbol, qty, price))
            if remain <= 0:
                break
        return allocs