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

def _alias_submodule(fullname: str):
    try:
        mod = importlib.import_module(fullname)
    except Exception:
        return None
    sys.modules[f'{PKG}.{fullname}'] = mod
    parent_name, _, child_name = fullname.rpartition('.')
    parent = sys.modules.get(f'{PKG}.{parent_name}')
    if parent is not None:
        setattr(parent, child_name, mod)
    return mod


for fullname in [
    'core.const',
    'infra.event_bus',
    'observability.metrics',
    'observability.struct_logger',
]:
    _alias_submodule(fullname)

_alias_submodule('persistence.models_init')
for loaded_name, loaded_mod in list(sys.modules.items()):
    if loaded_name.startswith('persistence.'):
        sys.modules[f'{PKG}.{loaded_name}'] = loaded_mod
        parent_name, _, child_name = loaded_name.rpartition('.')
        parent = sys.modules.get(f'{PKG}.{parent_name}')
        if parent is not None:
            setattr(parent, child_name, loaded_mod)

for fullname in [
    'services.sim_clock',
    'services.event_persistence_service',
]:
    _alias_submodule(fullname)

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
