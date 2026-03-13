from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Optional, Dict, Any

__all__ = [
    "safe_float",
    "safe_int",
    "round_to_price_step",
    "derive_third_value",
]


def _to_decimal(val: Any) -> Decimal:
    if isinstance(val, Decimal):
        return val
    # 允许常见分隔符：逗号、空格、下划线
    if isinstance(val, str):
        s = val.strip()
        # 去除千分位/空格/下划线
        s = s.replace(",", "").replace("_", "").replace(" ", "")
        try:
            return Decimal(s)
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError(f"Cannot convert {val!r} to Decimal")
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"Cannot convert {val!r} to Decimal")


def safe_float(val: Any, *, min_value: Optional[float | Decimal] = None,
               max_value: Optional[float | Decimal] = None) -> float:
    """Parse to float with optional bounds checking.

    Raises ValueError on invalid input or out of range.
    """
    d = _to_decimal(val)
    if min_value is not None and d < _to_decimal(min_value):
        raise ValueError(f"Value {d} < min {min_value}")
    if max_value is not None and d > _to_decimal(max_value):
        raise ValueError(f"Value {d} > max {max_value}")
    # disallow NaN/Infinity via Decimal to float conversion check
    f = float(d)
    if f != f or f in (float("inf"), float("-inf")):
        raise ValueError("Value is not finite")
    return f


def safe_int(val: Any, *, min_value: Optional[int] = None,
             max_value: Optional[int] = None) -> int:
    """Parse to int with optional bounds checking.

    Accepts numeric strings like "123" or Decimal with integer value.
    Raises ValueError on invalid input or non-integer numeric.
    """
    d = _to_decimal(val)
    # ensure integral value
    if d != d.to_integral_value(rounding=ROUND_HALF_UP):
        # allow "123.0" as integral
        if d.quantize(Decimal("1"), rounding=ROUND_HALF_UP) != d:
            raise ValueError(f"Non-integer value: {val!r}")
    i = int(d)
    if min_value is not None and i < min_value:
        raise ValueError(f"Value {i} < min {min_value}")
    if max_value is not None and i > max_value:
        raise ValueError(f"Value {i} > max {max_value}")
    return i


def round_to_price_step(price: Any, *, step: float | Decimal = 0.01,
                        rounding=ROUND_HALF_UP) -> float:
    """Round price to the nearest step (grid) using Decimal for precision.

    step must be > 0.
    """
    d_price = _to_decimal(price)
    d_step = _to_decimal(step)
    if d_step <= 0:
        raise ValueError("step must be positive")
    # quantize to step: scale price by (1/step), round, then rescale
    scaled = (d_price / d_step).quantize(Decimal("1"), rounding=rounding)
    rounded = scaled * d_step
    return float(rounded)


def derive_third_value(*, float_shares: Optional[int | Decimal | str] = None,
                       market_cap: Optional[float | Decimal | str] = None,
                       price: Optional[float | Decimal | str] = None,
                       price_step: float | Decimal = 0.01) -> Dict[str, Any]:
    """Given exactly two of (float_shares, market_cap, price), derive the third.

    Rules:
    - float_shares derived as floor(market_cap / price), integer shares (>=0)
    - market_cap derived as float_shares * price (rounded to 0.01)
    - price derived as market_cap / float_shares (rounded to nearest price_step)
    Edge cases raise ValueError: missing/too many values, division by zero, negatives.
    Returns a dict with keys among {'float_shares','market_cap','price'} only for the derived field.
    """
    provided = {
        'float_shares': float_shares,
        'market_cap': market_cap,
        'price': price,
    }
    none_count = sum(v is None for v in provided.values())
    if none_count != 1:
        raise ValueError("Exactly one of (float_shares, market_cap, price) must be None")

    if float_shares is None:
        d_mcap = _to_decimal(market_cap)  # type: ignore[arg-type]
        d_price = _to_decimal(price)      # type: ignore[arg-type]
        if d_price <= 0:
            raise ValueError("price must be > 0")
        if d_mcap < 0:
            raise ValueError("market_cap must be >= 0")
        shares = int((d_mcap / d_price).to_integral_value(rounding=ROUND_HALF_UP))
        # floor towards zero for safety if rounding could bump up
        if Decimal(shares) > (d_mcap / d_price):
            shares -= 1
        if shares < 0:
            shares = 0
        return {"float_shares": shares}

    if market_cap is None:
        d_shares = _to_decimal(float_shares)  # type: ignore[arg-type]
        d_price = _to_decimal(price)          # type: ignore[arg-type]
        if d_shares < 0:
            raise ValueError("float_shares must be >= 0")
        if d_price < 0:
            raise ValueError("price must be >= 0")
        mcap = (d_shares * d_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return {"market_cap": float(mcap)}

    # price is None
    d_shares = _to_decimal(float_shares)  # type: ignore[arg-type]
    d_mcap = _to_decimal(market_cap)      # type: ignore[arg-type]
    if d_shares <= 0:
        raise ValueError("float_shares must be > 0")
    if d_mcap < 0:
        raise ValueError("market_cap must be >= 0")
    raw_price = d_mcap / d_shares
    rounded_price = round_to_price_step(raw_price, step=price_step)
    return {"price": rounded_price}
