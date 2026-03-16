"""stock_sim 包动态映射顶层同名目录下已有功能子包。
用于兼容当前源码布局(顶层 core/ services/ 等在同一物理层级)。
测试代码可直接使用: from stock_sim.services.xxx import ...
"""
from __future__ import annotations
import importlib, sys
from pathlib import Path

PKG = __name__  # 'stock_sim'
_ROOT = Path(__file__).resolve().parent.parent
_SUBPACKAGES = [
    'core','infra','services','persistence','observability','rl','agents','settings'
]
for name in _SUBPACKAGES:
    if f'{PKG}.{name}' in sys.modules:
        continue
    try:
        mod = importlib.import_module(name)
    except Exception:  # 忽略缺失/初始化异常
        continue
    sys.modules[f'{PKG}.{name}'] = mod
    setattr(sys.modules[PKG], name, mod)

# 公开常用对象 (与原根 __init__.py 类似)
try:
    from core.order import Order  # type: ignore
    from persistence.models_account import Account  # type: ignore
    from core.const import OrderType, OrderSide, TimeInForce  # type: ignore
    from core.market_data import MarketSnapshot  # type: ignore
    from core.matching_engine import MatchingEngine  # type: ignore
    from core.instruments import Stock  # type: ignore
except Exception:
    # 允许部分导入失败 (例如尚未安装依赖)
    Order = Account = OrderType = OrderSide = TimeInForce = MarketSnapshot = MatchingEngine = Stock = None  # type: ignore

__all__ = [
    'Stock','MatchingEngine','Order','OrderSide','Account','MarketSnapshot','OrderType','TimeInForce'
]

PACKAGE_ROOT = _ROOT
__version__ = '0.0.1'
