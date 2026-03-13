from datetime import datetime
from app.utils.formatters import (
    format_number, format_currency, format_percent, format_date
)


def test_format_number_basic_rounding():
    assert format_number(1234.567, decimals=2) == '1,234.57'
    assert format_number(-1234.561, decimals=2) == '-1,234.56'


def test_format_number_trim_and_compact():
    assert format_number(1000, compact=True) == '1.00K'
    assert format_number(1500000, compact=True, decimals=1) == '1.5M'
    # 去掉尾随 0
    assert format_number(1234.5000, decimals=4, trim_trailing_zeros=True) == '1,234.5'
    # None -> '-'
    assert format_number(None) == '-'


def test_format_number_zero_decimals_and_sign_compact():
    assert format_number(12345.67, decimals=0) == '12,346'
    assert format_number(-9876, compact=True, decimals=1) == '-9.9K'


def test_format_currency_and_percent():
    assert format_currency(1234.5, currency='USD') == 'USD 1,234.50'
    assert format_percent(0.1234, decimals=2) == '12.34%'
    assert format_percent(-0.1, sign=True) == '-10.00%'
    assert format_percent(0.1, sign=True) == '+10.00%'


def test_format_percent_trim_trailing():
    # 0.1 => 10 -> trim 后没有多余 0
    assert format_percent(0.1, decimals=2, trim_trailing_zeros=True) == '10%'  # 10.00 -> 10


def test_format_date_default_and_custom_and_timestamp():
    dt = datetime(2024, 1, 2, 3, 4, 5)
    out = format_date(dt)
    assert out.startswith('2024-01-02') and '03:04:05' in out
    custom = format_date(dt, fmt='%Y/%m/%d')
    assert custom == '2024/01/02'
    ts_out = format_date(dt.timestamp())
    assert '03:04:05' in ts_out


def test_format_number_edge_large_compact():
    val = 9876543210.12
    assert format_number(val, decimals=2, compact=False).startswith('9,876,543,210.12')
    c = format_number(val, compact=True, decimals=2)
    assert c.endswith('B')
