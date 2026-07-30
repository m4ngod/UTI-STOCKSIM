from __future__ import annotations

import time
import uuid

from stock_sim.persistence import models_init
from stock_sim.persistence.models_imports import SessionLocal
from stock_sim.persistence.models_agent_binding import AgentBinding
from stock_sim.persistence.models_position import Position
from stock_sim.services.account_service import AccountService
from stock_sim.services.ipo_retail_distribution import allocate_ipo_retail_distribution
from stock_sim.services.runtime_command_service import RuntimeCommandService


def test_ipo_distribution_allocates_to_all_retail_bindings():
    models_init.init_models()
    symbol = f"IPOA{uuid.uuid4().hex[:4].upper()}"
    svc = RuntimeCommandService()

    assert svc.create_instrument(
        symbol=symbol,
        name=f"{symbol}-test",
        price_step=0.01,
        initial_price=10.0,
        float_shares=400,
        market_cap=4000.0,
        total_shares=400,
    )

    active_accounts = [f"active_retail_{idx:02d}" for idx in range(4)]
    stale_accounts = [f"stale_retail_{idx:02d}" for idx in range(2)]

    for account_id in active_accounts + stale_accounts:
        svc.bootstrap_agent_account(
            account_id=account_id,
            initial_cash=100_000.0,
            agent_type="Retail",
            strategy="liquidity_noise",
        )

    recent_ms = int(time.time() * 1000)
    stale_ms = recent_ms - (30 * 60 * 1000)
    for account_id in active_accounts:
        svc.update_agent_binding_meta(
            account_id,
            status="RUNNING",
            start_time=recent_ms,
            last_heartbeat=recent_ms,
        )
    for account_id in stale_accounts:
        svc.update_agent_binding_meta(
            account_id,
            status="STOPPED",
            start_time=stale_ms,
            last_heartbeat=stale_ms,
        )

    result = allocate_ipo_retail_distribution(symbol, sim_day=1)

    assert result["applied"] is True
    assert result["cohort_scope"] == "all-retail-bindings"
    assert result["recipients"] == len(active_accounts + stale_accounts)

    session = SessionLocal()
    try:
        rows = (
            session.query(Position)
            .filter(Position.symbol == symbol, Position.quantity > 0)
            .order_by(Position.account_id.asc())
            .all()
        )
        assert [row.account_id for row in rows] == sorted(active_accounts + stale_accounts)
        assert sum(int(row.quantity or 0) for row in rows) == 400
    finally:
        session.close()


def test_ipo_distribution_rebalances_underallocated_untraded_symbol_to_active_cohort():
    models_init.init_models()
    symbol = f"IPOR{uuid.uuid4().hex[:4].upper()}"
    svc = RuntimeCommandService()

    assert svc.create_instrument(
        symbol=symbol,
        name=f"{symbol}-test",
        price_step=0.01,
        initial_price=5.0,
        float_shares=1200,
        market_cap=6000.0,
        total_shares=1200,
    )

    recent_ms = int(time.time() * 1000)
    account_ids = [f"active_rebalance_{symbol}_{idx:02d}" for idx in range(20)]
    session = SessionLocal()
    try:
        accounts = AccountService(session)
        for account_id in account_ids:
            session.add(
                AgentBinding(
                    agent_name=account_id,
                    agent_type="RETAIL",
                    account_id=account_id,
                    meta=f'{{"status":"RUNNING","start_time":{recent_ms},"last_heartbeat":{recent_ms}}}',
                )
            )
            acc = accounts.get_or_create(account_id, cash=100_000.0)
            if account_ids.index(account_id) < 4:
                pos = accounts.get_position(acc, symbol)
                pos.quantity = 300
                pos.avg_price = 5.0
        session.commit()
    finally:
        session.close()

    result = allocate_ipo_retail_distribution(symbol, sim_day=2)

    assert result["applied"] is True
    assert result["existing_recipients"] == 4
    assert result["target_recipients"] == len(account_ids)

    session = SessionLocal()
    try:
        rows = (
            session.query(Position)
            .filter(Position.symbol == symbol, Position.quantity > 0)
            .all()
        )
        assert len(rows) == len(account_ids)
        assert sum(int(row.quantity or 0) for row in rows) == 1200
    finally:
        session.close()
