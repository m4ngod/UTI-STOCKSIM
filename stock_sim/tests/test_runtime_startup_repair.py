from __future__ import annotations

import json
import time
import uuid

from stock_sim.core.const import OrderSide, OrderStatus, OrderType, TimeInForce
from stock_sim.persistence import models_init
from stock_sim.persistence.models_agent_binding import AgentBinding
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_order import OrderORM
from stock_sim.persistence.models_position import Position
from stock_sim.services.account_service import AccountService
from stock_sim.services.runtime_command_service import RuntimeCommandService
from stock_sim.services.sim_clock import ensure_sim_clock_started


def test_desktop_run_cancels_stale_open_orders_and_releases_frozen_inventory():
    models_init.init_models()
    run_id = f"RUN-CURRENT-{uuid.uuid4().hex[:8].upper()}"
    old_run_id = f"RUN-OLD-{uuid.uuid4().hex[:8].upper()}"
    account_id = f"stale_seller_{uuid.uuid4().hex[:8]}"
    symbol = f"STL{uuid.uuid4().hex[:4].upper()}"
    old_order_id = f"O-OLD-{uuid.uuid4().hex[:8].upper()}"
    current_order_id = f"O-CUR-{uuid.uuid4().hex[:8].upper()}"

    clk = ensure_sim_clock_started()
    if hasattr(clk, "configure"):
        clk.configure(run_id=run_id)

    session = SessionLocal()
    try:
        account = AccountService(session).get_or_create(account_id, cash=100_000.0)
        pos = AccountService(session).get_position(account, symbol)
        pos.quantity = 10
        pos.frozen_qty = 10
        session.add(
            OrderORM(
                id=old_order_id,
                account_id=account_id,
                symbol=symbol,
                side=OrderSide.SELL,
                type=OrderType.LIMIT,
                tif=TimeInForce.GFD,
                price=10.0,
                orig_price=10.0,
                quantity=7,
                filled=0,
                status=OrderStatus.NEW,
                run_id=old_run_id,
            )
        )
        session.add(
            OrderORM(
                id=current_order_id,
                account_id=account_id,
                symbol=symbol,
                side=OrderSide.SELL,
                type=OrderType.LIMIT,
                tif=TimeInForce.GFD,
                price=10.0,
                orig_price=10.0,
                quantity=3,
                filled=0,
                status=OrderStatus.NEW,
                run_id=run_id,
            )
        )
        session.commit()
    finally:
        session.close()

    result = RuntimeCommandService().cancel_stale_open_orders(active_run_id=run_id)

    assert result["ok"] is True
    assert result["canceled"] == 1

    session = SessionLocal()
    try:
        old_order = session.get(OrderORM, old_order_id)
        current_order = session.get(OrderORM, current_order_id)
        pos = (
            session.query(Position)
            .filter(Position.account_id == account_id, Position.symbol == symbol)
            .one()
        )
        assert old_order.status == OrderStatus.CANCELED
        assert current_order.status == OrderStatus.NEW
        assert pos.frozen_qty == 3
    finally:
        session.close()
        if hasattr(clk, "configure"):
            clk.configure(run_id="")


def test_startup_distribution_repairs_open_instrument_without_retail_positions():
    models_init.init_models()
    suffix = uuid.uuid4().hex[:6].upper()
    symbol = f"IPO{suffix}"
    svc = RuntimeCommandService()

    assert svc.create_instrument(
        symbol=symbol,
        name=f"{symbol}-test",
        price_step=0.01,
        initial_price=5.0,
        float_shares=120,
        market_cap=600.0,
        total_shares=120,
    )

    account_ids = [f"startup_retail_{suffix}_{idx:02d}" for idx in range(4)]
    recent_ms = int(time.time() * 1000)
    session = SessionLocal()
    try:
        for account_id in account_ids:
            session.add(
                AgentBinding(
                    agent_name=account_id,
                    agent_type="RETAIL",
                    account_id=account_id,
                    meta=json.dumps(
                        {
                            "strategy": "liquidity_noise",
                            "status": "RUNNING",
                            "start_time": recent_ms,
                            "last_heartbeat": recent_ms,
                        }
                    ),
                )
            )
            AccountService(session).get_or_create(account_id, cash=100_000.0)
        session.commit()
    finally:
        session.close()

    result = svc.ensure_open_instrument_retail_distributions(sim_day=1)

    assert result["ok"] is True
    applied = [row for row in result["results"] if row.get("symbol") == symbol]
    assert applied and applied[0]["applied"] is True

    session = SessionLocal()
    try:
        positions = (
            session.query(Position)
            .filter(Position.symbol == symbol, Position.quantity > 0)
            .all()
        )
        assert sum(int(row.quantity or 0) for row in positions) == 120
    finally:
        session.close()
