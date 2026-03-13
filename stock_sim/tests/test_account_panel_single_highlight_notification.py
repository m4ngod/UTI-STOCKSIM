from app.panels.account.panel import AccountPanel
from app.panels.shared.notifications import notification_center
from app.core_dto.account import AccountDTO, PositionDTO
from datetime import date

class _StubAccountControllerSingle:
    def __init__(self):
        self._acc = None
    def load_account(self, account_id: str):
        # 仅构造 1 个高亮 + 1 个不高亮
        self._acc = AccountDTO(
            account_id=account_id,
            cash=100000,
            equity=100000,
            utilization=0.05,
            snapshot_id='s1',
            sim_day=str(date.today()),
            positions=[
                # ratio = 2000 / (10*100) = 0.2 >= 0.1 -> highlight
                PositionDTO(symbol='AAA', quantity=100, frozen_qty=0, avg_price=10, borrowed_qty=0, pnl_unreal=2000),
                # ratio = 10 / (20*50) = 0.01 -> not highlight
                PositionDTO(symbol='BBB', quantity=50, frozen_qty=0, avg_price=20, borrowed_qty=0, pnl_unreal=10),
            ]
        )
        return self._acc
    def get_account(self):
        return self._acc

class _StubSettings:
    class _State:
        def __init__(self):
            # 使用默认 0.1 阈值 (>=0.1 高亮)
            self.alert_thresholds = {'drawdown_pct': 0.1}
    def __init__(self):
        self._callbacks = []
    def get_state(self):
        return self._State()
    def on_alert_thresholds(self, cb):
        self._callbacks.append(cb)


def test_single_position_highlight_notification():
    """只应推送 1 条 position.highlight 通知"""
    notification_center.clear_all()
    ctl = _StubAccountControllerSingle()
    settings = _StubSettings()
    panel = AccountPanel(ctl, settings)
    panel.switch_account('ACC_SINGLE')
    panel.get_view()  # 触发高亮计算与通知

    notes = [n for n in notification_center.get_recent(10) if n.code == 'position.highlight']
    assert len(notes) == 1, f'期望 1 条 position.highlight, 实际 {len(notes)}'
    assert notes[0].data and notes[0].data.get('symbol') == 'AAA'

    # 再次 get_view 不应新增
    panel.get_view()
    notes2 = [n for n in notification_center.get_recent(10) if n.code == "position.highlight"]
    assert len(notes2) == 1

