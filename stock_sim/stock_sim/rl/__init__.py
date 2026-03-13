"""Bridge package: stock_sim.rl

将顶层 rl/* 模块映射到命名空间 stock_sim.rl.* 以兼容测试中 from stock_sim.rl.vectorized_env 导入。
避免复制源码，仅通过 importlib 与 sys.modules 重定向。
"""
from __future__ import annotations
import importlib, sys

_pkg = __name__  # stock_sim.rl
_parent_rl = 'rl'
_modules = [
    'vectorized_env', 'account_adapter', 'trading_env'
]
for m in _modules:
    full_src = f'{_parent_rl}.{m}'
    try:
        mod = importlib.import_module(full_src)
    except Exception:  # 某些模块可能缺失 (例如尚未实现)
        continue
    alias = f'{_pkg}.{m}'
    sys.modules[alias] = mod
    # 将其属性透出 (仅最小化处理)
    for k,v in mod.__dict__.items():
        if k.startswith('_'): continue
        if k in globals(): continue
        globals()[k] = v

__all__ = [k for k in list(globals().keys()) if not k.startswith('_')]

