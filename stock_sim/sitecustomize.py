"""sitecustomize: 为源码根目录提供 stock_sim.* 兼容导入映射。
如果已经存在真实包目录 stock_sim/ 则直接使用真实包，避免 stub 覆盖。
"""
from __future__ import annotations
import importlib, sys, types, importlib.util
from pathlib import Path

PKG_NAME = 'stock_sim'
_root = Path(__file__).resolve().parent
_pkg_dir = _root / PKG_NAME

# 如果真实包目录存在且含 __init__.py, 直接 import 真实包
if _pkg_dir.is_dir() and (_pkg_dir / '__init__.py').exists():
    try:
        importlib.import_module(PKG_NAME)
    except Exception:
        # 回退到动态 stub
        pass

# 若仍未加载则创建动态 stub
if PKG_NAME not in sys.modules:
    pkg = types.ModuleType(PKG_NAME)
    pkg.__dict__['__path__'] = [_pkg_dir.as_posix()] if _pkg_dir.exists() else []  # 标记为包
    sys.modules[PKG_NAME] = pkg
else:
    pkg = sys.modules[PKG_NAME]

# 动态挂载顶层子模块 (若真实包已提供则无需再做)
_subpackages = ['core','infra','services','persistence','observability','rl','agents','settings']
for name in _subpackages:
    full = f'{PKG_NAME}.{name}'
    if full in sys.modules:
        continue
    try:
        mod = importlib.import_module(name)
    except Exception:
        continue
    sys.modules[full] = mod
    setattr(pkg, name, mod)

# 可选预热
_preload = [
    'core.const','infra.event_bus','observability.metrics',
]
for m in _preload:
    full = f'{PKG_NAME}.{m}'
    if full in sys.modules:
        continue
    try:
        mod = importlib.import_module(m)
        sys.modules[full] = mod
    except Exception:
        pass
