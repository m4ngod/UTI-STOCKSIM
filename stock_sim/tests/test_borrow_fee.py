import json, time
from stock_sim.services.borrow_fee_scheduler import borrow_fee_scheduler
from stock_sim.services.sim_clock import ensure_sim_clock_started, _sim_clock_singleton  # type: ignore
from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_account import Account
from stock_sim.persistence.models_position import Position
from stock_sim.persistence.models_snapshot import Snapshot1s
from stock_sim.persistence.models_ledger import Ledger
from stock_sim.services.account_service import AccountService
from stock_sim.infra.event_bus import event_bus
from stock_sim.core.const import EventType


def test_borrow_fee_scheduler_accrues_and_emits():
    models_init.init_models()
    # 启动并强制设定模拟日 =1
    ensure_sim_clock_started()
    if _sim_clock_singleton:
        _sim_clock_singleton._day_index = 1  # type: ignore
    s = SessionLocal()
    acc_service = AccountService(s)
    acc = acc_service.get_or_create('ACC1', cash=100000.0)
    # 创建空头持仓 (borrowed_qty>0)
    pos = Position(account_id=acc.id, symbol='XYZ', quantity=-50, avg_price=10.0, borrowed_qty=50)
    s.add(pos)
    snap = Snapshot1s(symbol='XYZ', last_price=12.0, bid1=12.0, ask1=12.1, bid1_qty=100, ask1_qty=100,
                      volume=1000, turnover=12000.0)
    s.add(snap)
    s.commit()
    captured = []
    event_bus.subscribe(EventType.BORROW_FEE_ACCRUED, lambda t,p: captured.append(p))
    count, total = borrow_fee_scheduler.run()
    assert count == 1 and total > 0
    # 账本写入
    s.refresh(acc)
    ledgers = s.query(Ledger).filter(Ledger.account_id==acc.id, Ledger.side=='BORROW_FEE').all()
    assert len(ledgers) == 1
    # 事件捕获
    assert captured and captured[0]['symbol'] == 'XYZ'
    # 再次运行应不重复 (borrow_fee_last_day 已标记)
    count2, total2 = borrow_fee_scheduler.run()
    assert count2 == 0 and total2 == 0
    s.close()

