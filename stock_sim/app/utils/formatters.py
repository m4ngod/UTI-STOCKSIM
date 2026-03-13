"""通用格式化与本地化工具 (Spec Task 18)

需求:
- 金额/数字/日期本地化输出 (R11 AC2, R1 汇总展示)
- 支持千分位、精度、去除尾随 0、百分比与货币前缀
- 简单 locale 适配: 通过 app.i18n.current_language() 推断 (en_US / zh_CN)

说明:
- 不调用系统 locale (避免线程副作用), 内部实现分组
- 极值 / None 处理: None -> '-' ; 非数字抛 ValueError
- 可选 compact (K/M/B) 输出
"""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from datetime import datetime, date
from typing import Optional

try:  # 软依赖 i18n
    from app.i18n import current_language  # type: ignore
except Exception:  # pragma: no cover
    def current_language():  # type: ignore
        return "en_US"

__all__ = [
    "format_number", "format_currency", "format_percent", "format_date"
]

_GROUP_SEP = {"en_US": ",", "zh_CN": ","}  # 目前中英文都使用逗号
_DECIMAL_POINT = {"en_US": ".", "zh_CN": "."}

_SUFFIX_COMPACT = [
    (Decimal('1e12'), 'T'),
    (Decimal('1e9'), 'B'),
    (Decimal('1e6'), 'M'),
    (Decimal('1e3'), 'K'),
]


def _to_decimal(val) -> Decimal:
    if isinstance(val, Decimal):
        return val
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"Cannot convert {val!r} to Decimal")


def format_number(value, *, decimals: int = 2, thousands_sep: bool = True,
                  trim_trailing_zeros: bool = False, compact: bool = False,
                  locale: Optional[str] = None) -> str:
    if value is None:
        return '-'
    loc = locale or current_language()
    group_sep = _GROUP_SEP.get(loc, ',')
    dec_point = _DECIMAL_POINT.get(loc, '.')

    d = _to_decimal(value)
    sign = '-' if d < 0 else ''
    d = abs(d)

    suffix = ''
    if compact:
        for threshold, suf in _SUFFIX_COMPACT:
            if d >= threshold:
                d = d / threshold
                suffix = suf
                break

    q = Decimal('1').scaleb(-decimals)  # 10^-decimals
    d_q = d.quantize(q, rounding=ROUND_HALF_UP)

    int_part, _, frac_part = f"{d_q:f}".partition('.')

    if thousands_sep:
        # 手动分组
        chars = []
        for i, ch in enumerate(reversed(int_part)):
            if i and i % 3 == 0:
                chars.append(group_sep)
            chars.append(ch)
        int_part = ''.join(reversed(chars))

    if decimals > 0:
        if len(frac_part) < decimals:
            frac_part = frac_part + '0' * (decimals - len(frac_part))
        if trim_trailing_zeros:
            frac_part = frac_part.rstrip('0')
        if frac_part:
            result = f"{sign}{int_part}{dec_point}{frac_part}{suffix}"
        else:
            result = f"{sign}{int_part}{suffix}"
    else:
        result = f"{sign}{int_part}{suffix}"

    return result


def format_currency(value, currency: str = 'USD', **kwargs) -> str:
    num = format_number(value, **kwargs)
    if num == '-':
        return num
    return f"{currency} {num}"


def format_percent(value, *, decimals: int = 2, sign: bool = False, **kwargs) -> str:
    if value is None:
        return '-'
    d = _to_decimal(value) * Decimal('100')
    s = format_number(d, decimals=decimals, **kwargs)
    if s == '-':
        return s
    if sign and not s.startswith('-'):
        s = '+' + s
    return s + '%'


def format_date(dt, fmt: Optional[str] = None, *, locale: Optional[str] = None) -> str:
    if dt is None:
        return '-'
    if isinstance(dt, (int, float)):
        dt_obj = datetime.fromtimestamp(dt)
    elif isinstance(dt, datetime):
        dt_obj = dt
    elif isinstance(dt, date):
        dt_obj = datetime(dt.year, dt.month, dt.day)
    else:
        raise ValueError("Unsupported date type")
    loc = locale or current_language()
    if fmt:
        return dt_obj.strftime(fmt)
    # 默认格式
    if loc.startswith('zh'):
        return dt_obj.strftime('%Y-%m-%d %H:%M:%S')
    return dt_obj.strftime('%Y-%m-%d %H:%M:%S')

