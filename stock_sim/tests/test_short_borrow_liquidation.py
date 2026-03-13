import math
from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_account import Account  # noqa: F401 (可能用于调试)
from stock_sim.persistence.models_position import Position
from stock_sim.persistence.models_snapshot import Snapshot1s
from stock_sim.persistence.models_ledger import Ledger
from stock_sim.services.account_service import AccountService
from stock_sim.services.borrow_fee_scheduler import borrow_fee_scheduler
from stock_sim.services.forced_liquidation_service import liquidation_service
from stock_sim.services.sim_clock import ensure_sim_clock_started, _sim_clock_singleton  # type: ignore
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType, OrderSide
from stock_sim.settings import settings


class DummyOrderService:
    def __init__(self):
        self.orders = []
    def place_order(self, order):  # 简化: 只收集
        self.orders.append(order)
        return order

def test_short_borrow_fee_and_liquidation_integration():
    # 1. 重置数据库
    models_init.init_models()
    # 2. 启动模拟时钟并设置为第1日
    ensure_sim_clock_started()
    if _sim_clock_singleton:
        _sim_clock_singleton._day_index = 1  # type: ignore

    # 3. 创建账户与空头持仓 (构造低权益以触发强平)
    s = SessionLocal()
    acc_service = AccountService(s)
    acc = acc_service.get_or_create('ACC_SHORT', cash=100.0)  # 很低现金
    pos = Position(account_id=acc.id, symbol='XYZ', quantity=-100, avg_price=10.0, borrowed_qty=100)
    s.add(pos)
    snap = Snapshot1s(symbol='XYZ', last_price=12.0, bid1=12.0, ask1=12.1, bid1_qty=100, ask1_qty=100,
                      volume=5000, turnover=60000.0)
    s.add(snap)
    s.commit()

    # 4. 订阅事件捕获
    borrow_events = []
    liq_events = []
    event_bus.subscribe(EventType.BORROW_FEE_ACCRUED, lambda t,p: borrow_events.append(p))
    event_bus.subscribe(EventType.LIQUIDATION_TRIGGERED, lambda t,p: liq_events.append(p))

    # 5. 计提借券费用
    count, total_fee = borrow_fee_scheduler.run()
    assert count == 1 and total_fee > 0

    # 6. 校验 Ledger 记录存在
    ledgers = s.query(Ledger).filter(Ledger.account_id==acc.id, Ledger.side=='BORROW_FEE').all()
    assert len(ledgers) == 1

    # 7. 重新打开 session (borrow_fee_scheduler 内部已提交)
    s.close()
    s2 = SessionLocal()

    # 8. 触发强平评估+提交
    dummy_order_service = DummyOrderService()
    plans = liquidation_service.evaluate_and_submit(s2, dummy_order_service)

    # 9. 校验生成强平计划与订单 (应为买入回补短仓)
    assert plans, '应生成至少一个强平计划'
    # 找到该账户的第一条计划
    plan = next((p for p in plans if p.account_id == acc.id), None)
    assert plan is not None
    assert plan.side == OrderSide.BUY  # 回补空头
    expected_qty = max(1, math.ceil(100 * settings.LIQUIDATION_ORDER_SLICE_RATIO))
    assert plan.qty == expected_qty

    # 10. 确认强平订单被下发到 dummy_order_service
    assert any(o.account_id == acc.id and o.side == OrderSide.BUY for o in dummy_order_service.orders)

    # 11. 事件捕获: 借券费用事件 + 强平事件
    assert borrow_events and borrow_events[0]['symbol'] == 'XYZ'
    assert liq_events and liq_events[0]['account_id'] == acc.id
    assert liq_events[0]['orders'][0]['side'] == 'BUY'

    s2.close()

