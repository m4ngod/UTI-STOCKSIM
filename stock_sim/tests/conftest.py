import pytest
import os
import sys, pathlib

# 确保项目根在 sys.path 开头 (避免上级目录存在同名 app 包冲突)
_ROOT = pathlib.Path(__file__).resolve().parent.parent
root_str = str(_ROOT)
os.environ.setdefault("STOCKSIM_DB_URL", "sqlite:///stock_sim_test.db")
# 移除已存在的其它位置
sys.path = [p for p in sys.path if p != root_str]
# 插入最前
sys.path.insert(0, root_str)

# Frontend V2 contract collection mixes the installed ``stock_sim.*`` import
# surface with legacy top-level ``app`` imports.  Preload the package-qualified
# persistence model graph so SQLAlchemy sees one canonical model set, while
# production ``import stock_sim`` remains lazy.
try:
    from stock_sim.persistence import models_init as _package_models_init  # noqa: F401
except Exception:
    pass

# 自动隔离事件持久化以避免 sqlite 锁 (需测试的场景可显式调用 enable_event_persistence(force=True))
def disable_event_persistence():  # type: ignore
    """Disable event persistence only when a test already imported the service."""

    for module_name in (
        "stock_sim.services.event_persistence_service",
        "services.event_persistence_service",
    ):
        module = sys.modules.get(module_name)
        disable = getattr(module, "disable_event_persistence", None)
        if callable(disable):
            disable()
    return True


@pytest.fixture(autouse=True)
def _isolate_event_persist():
    # 测试开始前禁用 (若此前被其它测试开启)
    try:
        disable_event_persistence()
    except Exception:
        pass
    yield
    # 测试结束后再次禁用确保无遗留订阅副作用
    try:
        disable_event_persistence()
    except Exception:
        pass
