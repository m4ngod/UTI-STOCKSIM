from app.panels.account.panel import AccountPanel
from app.panels.shared.notifications import notification_center
from app.core_dto.account import AccountDTO, PositionDTO
from datetime import date

class _StubAccountController:
    def __init__(self):
        self._acc = None
    def load_account(self, account_id: str):
        # 构造两个高亮, 一个不高亮
        self._acc = AccountDTO(
            account_id=account_id,
            cash=100000,
            equity=100000,
            utilization=0.1,
            snapshot_id='s1',
            sim_day=str(date.today()),
            positions=[
                PositionDTO(symbol='AAA', quantity=100, frozen_qty=0, avg_price=10, borrowed_qty=0, pnl_unreal=2000),  # +2000 -> ratio=2000/(10*100)=0.2 highlight
                PositionDTO(symbol='BBB', quantity=50, frozen_qty=0, avg_price=20, borrowed_qty=0, pnl_unreal=-2500),  # -2500/(20*50)= -2.5 highlight
                PositionDTO(symbol='CCC', quantity=10, frozen_qty=0, avg_price=5, borrowed_qty=0, pnl_unreal=1),       # 1/(5*10)=0.02 not highlight
            ]
        )
        return self._acc
    def get_account(self):
        return self._acc

class _StubSettings:
    class _State:
        def __init__(self):
            self.alert_thresholds = {'drawdown_pct': 0.1}
    def __init__(self):
        self._callbacks = []
    def get_state(self):
        return self._State()
    def on_alert_thresholds(self, cb):
        self._callbacks.append(cb)


def test_highlight_notifications_dedup_and_account_switch():
    notification_center.clear_all()
    ctl = _StubAccountController()
    settings = _StubSettings()
    panel = AccountPanel(ctl, settings)
    # 初次加载账户
    panel.switch_account('ACC1')
    view = panel.get_view()
    # 获取通知 (应对 AAA/BBB 触发, code=position.highlight 共2条)
    notes = [n for n in notification_center.get_recent(20) if n.code == 'position.highlight']
    assert len(notes) == 2
    symbols_noted = {n.data['symbol'] for n in notes}
    assert symbols_noted == {'AAA','BBB'}
    # 再次 get_view 不应新增
    panel.get_view()
    notes2 = [n for n in notification_center.get_recent(20) if n.code == 'position.highlight']
    assert len(notes2) == 2
    # 切换账户 (相同数据) 应重新触发 (再 +2)
    panel.switch_account('ACC1')
    panel.get_view()
    notes3 = [n for n in notification_center.get_recent(50) if n.code == 'position.highlight']
    # 之前2 + 新2 = 4
    assert len(notes3) == 4

