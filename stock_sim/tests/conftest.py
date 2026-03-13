import pytest
import sys, pathlib

# 确保项目根在 sys.path 开头 (避免上级目录存在同名 app 包冲突)
_ROOT = pathlib.Path(__file__).resolve().parent.parent
root_str = str(_ROOT)
# 移除已存在的其它位置
sys.path = [p for p in sys.path if p != root_str]
# 插入最前
sys.path.insert(0, root_str)

# 预载入 stock_sim 以执行动态别名映射 (可选)
try:
    import stock_sim  # noqa: F401
except Exception:
    pass

# 自动隔离事件持久化以避免 sqlite 锁 (需测试的场景可显式调用 enable_event_persistence(force=True))
try:
    from stock_sim.services.event_persistence_service import disable_event_persistence
except Exception:  # 回退
    try:
        from services.event_persistence_service import disable_event_persistence  # type: ignore
    except Exception:
        def disable_event_persistence():  # type: ignore
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
