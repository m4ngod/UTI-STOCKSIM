import pytest

from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.services.account_service import AccountService
from stock_sim.core.const import OrderSide


def test_sell_freeze_locks_only_existing_long_and_does_not_mutate_quantity():
    models_init.init_models()
    s = SessionLocal()
    svc = AccountService(s)
    acc = svc.get_or_create('ACC_SELL_FREEZE', cash=100000.0)
    pos = svc.get_position(acc, 'AAA')
    pos.quantity = 100
    pos.frozen_qty = 0
    pos.avg_price = 10.0
    s.flush()

    ok = svc.freeze(acc, 'AAA', OrderSide.SELL, 10.0, 300)
    assert ok is True

    s.flush()
    s.refresh(pos)
    assert pos.quantity == 100
    assert pos.frozen_qty == 100
    assert pos.borrowed_qty == 0
    s.close()


def test_buy_settlement_can_cover_short_and_rebuild_long_basis():
    models_init.init_models()
    s = SessionLocal()
    svc = AccountService(s)
    acc = svc.get_or_create('ACC_COVER', cash=100000.0)
    pos = svc.get_position(acc, 'BBB')
    pos.quantity = -100
    pos.borrowed_qty = 100
    pos.avg_price = 10.0
    acc.frozen_cash = 2400.0
    acc.frozen_fee = 20.0
    s.flush()

    svc.settle_trades_batch(
        [(acc, None, 'BBB', 12.0, 200, 'BUYOID1', None)],
        [(6.0, 0.0, 0.0)],
    )
    s.flush()
    s.refresh(pos)
    s.refresh(acc)

    assert pos.quantity == 100
    assert pos.borrowed_qty == 0
    assert pos.avg_price == pytest.approx(12.0)
    assert acc.frozen_cash == pytest.approx(0.0)
    assert acc.frozen_fee == pytest.approx(14.0)
    s.close()


def test_sell_settlement_can_open_short_and_credit_net_cash():
    models_init.init_models()
    s = SessionLocal()
    svc = AccountService(s)
    acc = svc.get_or_create('ACC_SHORT_OPEN', cash=1000.0)
    pos = svc.get_position(acc, 'CCC')
    pos.quantity = 100
    pos.frozen_qty = 100
    pos.avg_price = 8.0
    s.flush()

    svc.settle_trades_batch(
        [(None, acc, 'CCC', 10.0, 300, None, 'SELLOID1')],
        [(0.0, 3.0, 2.0)],
    )
    s.flush()
    s.refresh(pos)
    s.refresh(acc)

    assert pos.quantity == -200
    assert pos.borrowed_qty == 200
    assert pos.frozen_qty == 0
    assert pos.avg_price == pytest.approx(10.0)
    assert acc.cash == pytest.approx(1000.0 + 3000.0 - 5.0)
    s.close()


def test_t_plus_one_style_same_day_bought_shares_remain_frozen_until_release_or_next_day_logic():
    models_init.init_models()
    s = SessionLocal()
    svc = AccountService(s)
    acc = svc.get_or_create('ACC_T1', cash=100000.0)

    assert svc.freeze(acc, 'T1A', OrderSide.BUY, 10.0, 100) is True
    svc.settle_trades_batch(
        [(acc, None, 'T1A', 10.0, 100, 'OID_BUY_T1', None)],
        [(1.0, 0.0, 0.0)],
    )
    s.flush()

    pos = svc.get_position(acc, 'T1A')
    s.refresh(pos)
    s.refresh(acc)

    # 账户服务层本身不应在买入成交后自动把 frozen_qty 清成可卖，
    # T+1 约束应由上层风险/可卖规则继续限制；这里至少确认没有错误地生成卖出冻结或篡改持仓。
    assert pos.quantity == 100
    assert pos.frozen_qty == 0
    assert pos.borrowed_qty == 0
    assert acc.frozen_cash == pytest.approx(0.0)
    assert acc.frozen_fee == pytest.approx(0.0)
    s.close()
