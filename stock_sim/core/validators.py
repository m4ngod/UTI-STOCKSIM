# python
# file: core/validators.py
from math import isclose

def round_to_tick(price: float, tick: float) -> float:
    if tick <= 0:
        return price
    rounded = round(round(price / tick) * tick, 10)
    return float(f"{rounded:.10g}")

def validate_tick(price: float, tick: float) -> bool:
    if tick <= 0:
        return True
    return isclose((price / tick) - round(price / tick), 0.0, abs_tol=1e-9)

def normalize_price(price: float, tick: float) -> float:
    return round_to_tick(price, tick)

def validate_lot(qty: int, lot: int, min_qty: int) -> bool:
    if qty < min_qty:
        return False
    if lot <= 1:
        return True
    return qty % lot == 0

def align_lot_quantity(qty: int, lot: int, min_qty: int) -> int:
    """
    将数量向下对齐到合法档位；若低于最小值返回 0。
    """
    if qty < min_qty:
        return 0
    if lot <= 1:
        return qty
    return qty - (qty % lot)

def basic_order_checks(price: float, qty: int) -> tuple[bool, str]:
    if price <= 0:
        return False, "PRICE_LE_0"
    if qty <= 0:
        return False, "QTY_LE_0"
    return True, ""