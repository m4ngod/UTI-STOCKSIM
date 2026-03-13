# python
# file: core/instruments.py
from dataclasses import dataclass
import re

@dataclass(slots=True)
class Stock:
    ticker: str
    total_shares: int
    free_float: int
    tick_size: float = 0.01
    lot_size: int = 1
    min_qty: int = 1
    settlement_cycle: int = 0  # 0 = T+0, 1 = T+1
    # ---- 新增扩展字段 ----
    free_float_shares: float | None = None  # 与 free_float 兼容（旧字段仍保留）
    initial_price: float | None = None      # 前端创建时配置的初始/发行价
    ipo_opened: bool = False                # 是否已从集合竞价进入连续

# --- Instrument Factory ---
FUTURE_PREFIXES = {"IF", "IH", "IC", "IM", "CU", "AL", "ZN", "RB", "AU", "AG", "BU", "RU", "FU", "HC", "SS", "PF", "PG", "SA"}

def create_instrument(symbol: str, *, tick_size: float = 0.01, lot_size: int = 1, min_qty: int = 1,
                      initial_price: float | None = None) -> Stock:
    """根据符号自动推断 settlement_cycle 并可选设定 initial_price。
    增强: 支持前端配置的 initial_price 直接注入到 Stock, 避免后续因 slots 限制无法动态添加。
    """
    upper = symbol.upper()
    cycle = 1  # 默认股票 T+1
    # 期货判断: 前缀字母 + 4 位数字
    m = re.match(r"^([A-Z]{1,3})(\d{3,4})$", upper)
    if m:
        prefix = m.group(1)
        if prefix in FUTURE_PREFIXES:
            cycle = 0
    stk = Stock(symbol, 0, 0, tick_size=tick_size, lot_size=lot_size, min_qty=min_qty, settlement_cycle=cycle,
                initial_price=initial_price)
    return stk
