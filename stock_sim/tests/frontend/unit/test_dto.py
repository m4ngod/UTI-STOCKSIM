from app.core_dto import (
    AccountDTO,
    PositionDTO,
    SnapshotDTO,
    TradeDTO,
    AgentMetaDTO,
    LeaderboardRowDTO,
    ClockStateDTO,
    AgentVersionDTO,
)
from pydantic import ValidationError
import pytest


def test_account_dto_round_trip():
    acc = AccountDTO(
        account_id="acc1",
        cash=100000.0,
        frozen_cash=500.0,
        positions=[
            PositionDTO(symbol="AAA", quantity=10, frozen_qty=0, avg_price=12.3, borrowed_qty=0),
            PositionDTO(symbol="BBB", quantity=5, frozen_qty=1, avg_price=8.0, borrowed_qty=0, pnl_unreal=1.5),
        ],
        realized_pnl=100.5,
        unrealized_pnl=5.2,
        equity=100105.7,
        utilization=0.25,
        snapshot_id="snap-1",
        sim_day="2025-09-08",
    )
    data = acc.dict()
    acc2 = AccountDTO(**data)
    assert acc2.equity == acc.equity
    assert len(acc2.positions) == 2


def test_account_negative_equity_validation():
    with pytest.raises(ValidationError):
        AccountDTO(
            account_id="acc2",
            cash=1000.0,
            frozen_cash=0.0,
            positions=[],
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            equity=-1.0,
            utilization=0.1,
            snapshot_id="snap-2",
            sim_day="2025-09-08",
        )


def test_market_and_trade_dto():
    snap = SnapshotDTO(
        symbol="AAA",
        last=12.5,
        bid_levels=[(12.4, 100)],
        ask_levels=[(12.6, 200)],
        volume=1000,
        turnover=12500.0,
        ts=1725792000000,
        snapshot_id="s1",
    )
    trade = TradeDTO(symbol="AAA", price=12.5, qty=50, side="buy", ts=1725792000500)
    assert snap.symbol == trade.symbol
    assert trade.qty == 50


def test_agent_leaderboard_clock_version():
    agent = AgentMetaDTO(
        agent_id="ag1",
        name="Agent One",
        type="Retail",
        status="RUNNING",
        start_time=1725792000000,
        last_heartbeat=1725792000500,
        params_version=1,
    )
    row = LeaderboardRowDTO(
        agent_id="ag1",
        return_pct=0.12,
        annualized=0.25,
        sharpe=1.5,
        max_drawdown=0.05,
        win_rate=0.55,
        equity=101200.0,
        rank=1,
        rank_delta=0,
    )
    clock = ClockStateDTO(status="RUNNING", sim_day="2025-09-08", speed=10.0, ts=1725792001000)
    ver = AgentVersionDTO(version=1, created_at=1725792000000, author="tester", diff_json={"lr": 0.001})

    assert agent.agent_id == row.agent_id
    assert row.rank == 1
    assert clock.status == "RUNNING"
    assert ver.version == 1
