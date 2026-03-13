from app.ui.adapters.leaderboard_adapter import LeaderboardPanelAdapter
import time

class _MockLogic:
    def __init__(self):
        self.calls = 0
    def export(self, fmt: str):  # noqa: ARG002
        self.calls += 1
        # 模拟较长导出
        time.sleep(0.2)
        return f"/tmp/mock-{self.calls}.csv"


def test_leaderboard_export_concurrency():
    adapter = LeaderboardPanelAdapter()
    adapter._create_widget()  # 初始化组件
    logic = _MockLogic()
    adapter.set_logic(logic)
    # 第一次启动
    adapter._start_export('csv')
    # 立刻第二次启动应被忽略
    adapter._start_export('csv')
    # 短暂等待仍在执行
    time.sleep(0.05)
    assert logic.calls == 1, '第二次点击不应触发新的导出'
    # 等待线程完成
    time.sleep(0.3)
    assert logic.calls == 1, '结束后总调用次数仍应为 1'

