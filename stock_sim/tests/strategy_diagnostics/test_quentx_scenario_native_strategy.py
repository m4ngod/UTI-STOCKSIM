from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest

import strategy_diagnostics.ptrade_host as ptrade_host_module
import strategy_diagnostics.quentx_scenario_native_strategy as quentx_strategy
from strategy_diagnostics import InstrumentState, MarketPathNode, ScenarioMarketSnapshot
from strategy_diagnostics.ptrade_host import (
    QUENTX_SCENARIO_NATIVE_MANIFEST,
    QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
    QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
    InProcessPTradeStrategyHost,
    PTradeCompatibilityError,
    PTradeHostInvocation,
    PTradePortfolioSnapshot,
    PTradePositionSnapshot,
    PTradeRuntimeState,
    SubprocessPTradeStrategyHost,
    ptrade_manifest_for,
)


def _node(
    instrument: str,
    simulation_time: datetime,
    *,
    price: str,
    rank: int,
    candidate_score: str,
    relative_strength: str,
    relative_liquidity: str = "0.2",
    sector_return: str = "0.03",
    sector_breadth: str = "0.8",
    market_breadth: str = "0.7",
    volume: int = 10_000,
) -> MarketPathNode:
    value = Decimal(price)
    return MarketPathNode(
        instrument=instrument,
        simulation_time=simulation_time,
        open=value,
        high=value * Decimal("1.01"),
        low=value * Decimal("0.99"),
        close=value,
        volume=volume,
        amount=value * volume,
        reconstructed=True,
        features=(
            ("candidate_rank", Decimal(rank)),
            ("candidate_score", Decimal(candidate_score)),
            ("relative_strength", Decimal(relative_strength)),
            ("relative_liquidity", Decimal(relative_liquidity)),
            ("sector_return", Decimal(sector_return)),
            ("sector_breadth", Decimal(sector_breadth)),
            ("market_breadth", Decimal(market_breadth)),
        ),
    )


def _history(
    current: MarketPathNode,
    *,
    start_price: str,
    bars: int = 320,
) -> tuple[MarketPathNode, ...]:
    start = Decimal(start_price)
    prior_close = current.close * Decimal("0.995")
    daily_bars = 65
    daily_step = (prior_close - start) / Decimal(daily_bars - 1)
    result: list[MarketPathNode] = []
    for index in range(daily_bars):
        price = start + daily_step * index
        simulation_time = (
            current.simulation_time - timedelta(days=daily_bars - index)
        ).replace(hour=15, minute=0, second=0, microsecond=0)
        volume = 16_000 if index % 4 == 1 else 8_000
        result.append(
            replace(
                current,
                simulation_time=simulation_time,
                open=price * Decimal("0.995"),
                high=price * Decimal("1.01"),
                low=price * Decimal("0.99"),
                close=price,
                volume=volume,
                amount=price * volume,
                features=(),
            )
        )
    step = (current.close - prior_close) / Decimal(max(1, bars - 1))
    for index in range(bars):
        price = prior_close + step * index
        legacy_group = index // 10
        volume = 16_000 if legacy_group % 4 == 0 else 8_000
        simulation_time = current.simulation_time - timedelta(
            seconds=30 * (bars - index - 1)
        )
        result.append(
            replace(
                current,
                simulation_time=simulation_time,
                open=price,
                high=price * Decimal("1.01"),
                low=price * Decimal("0.99"),
                close=price,
                volume=volume,
                amount=price * volume,
                features=(),
            )
        )
    return tuple(result)


def _state(
    instrument: str,
    simulation_time: datetime,
    *,
    industry: str,
    is_st: bool = False,
    trading_status: str = "trading",
) -> InstrumentState:
    return InstrumentState(
        instrument=instrument,
        effective_at=simulation_time - timedelta(days=1),
        eligible=True,
        trading_status=trading_status,
        is_st=is_st,
        industry=industry,
        decision_adjustment_factor=Decimal("1"),
        decision_adjustment_provenance="quentx-scenario-fixture.v1",
    )


def _invocation(
    latest_nodes: tuple[MarketPathNode, ...],
    *,
    history_starts: dict[str, str] | None = None,
    positions: tuple[PTradePositionSnapshot, ...] = (),
    available_cash: str = "100000",
    event: str = "initialize",
    runtime_state: PTradeRuntimeState | None = None,
) -> PTradeHostInvocation:
    simulation_time = latest_nodes[0].simulation_time
    industries = ("banking", "technology", "industry", "consumer")
    states = tuple(
        _state(
            node.instrument,
            simulation_time,
            industry=industries[index % len(industries)],
        )
        for index, node in enumerate(latest_nodes)
    )
    starts = history_starts or {
        node.instrument: str(node.close * Decimal("0.96"))
        for node in latest_nodes
    }
    market_history = tuple(
        history_node
        for node in latest_nodes
        for history_node in _history(
            node,
            start_price=starts[node.instrument],
        )
    )
    positions_value = sum(
        (position.market_value for position in positions),
        Decimal("0"),
    )
    return PTradeHostInvocation(
        run_id="quentx-scenario-native-run",
        strategy_id=QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
        strategy_version=QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
        compatibility_manifest_hash=QUENTX_SCENARIO_NATIVE_MANIFEST.content_hash,
        materialization_hash="a" * 64,
        simulation_time=simulation_time,
        decision_cadence_minutes=30,
        order_shares=100,
        random_seed=29,
        market_snapshot=ScenarioMarketSnapshot(
            simulation_time=simulation_time,
            eligible_universe=tuple(node.instrument for node in latest_nodes),
            states=states,
            latest_nodes=latest_nodes,
        ),
        market_history=market_history,
        portfolio=PTradePortfolioSnapshot(
            available_cash=Decimal(available_cash),
            total_value=Decimal(available_cash) + positions_value,
            positions=positions,
        ),
        event=event,  # type: ignore[arg-type]
        runtime_state=runtime_state,
    )


def _position(
    instrument: str,
    *,
    amount: int = 100,
    closeable_amount: int = 100,
    average_cost: str = "100",
    market_price: str = "100",
) -> PTradePositionSnapshot:
    price = Decimal(market_price)
    return PTradePositionSnapshot(
        instrument=instrument,
        amount=amount,
        closeable_amount=closeable_amount,
        average_cost=Decimal(average_cost),
        market_price=price,
        market_value=price * amount,
    )


def _metrics(
    *,
    ret3: str = "0.01",
    ret5: str = "0.03",
    ret10: str = "0.06",
    box_width: str = "0.20",
) -> quentx_strategy._StructuralMetrics:
    return quentx_strategy._StructuralMetrics(
        state="institutional_mainline_trend_pullback",
        ret3=Decimal(ret3),
        ret5=Decimal(ret5),
        ret10=Decimal(ret10),
        ret20=Decimal("0.08"),
        close_position=Decimal("0.7"),
        day_close_position=Decimal("0.7"),
        late_close_position=Decimal("0.7"),
        long_relative_position=Decimal("0.7"),
        volume_ratio=Decimal("1"),
        ma20_slope=Decimal("0.05"),
        ma60_slope=Decimal("0.02"),
        ma20_vs_ma60=Decimal("0.04"),
        close_vs_ma20=Decimal("0.03"),
        box_width=Decimal(box_width),
        accumulation=Decimal("0.8"),
        volume_consistency=Decimal("0.8"),
        distribution_risk=Decimal("0.1"),
        smoothness=Decimal("0.8"),
        atr14=Decimal("1"),
        defense_price=Decimal("90"),
        structural_score=Decimal("0.9"),
        amount=Decimal("1000000"),
        source_price=Decimal("100"),
    )


def test_quentx_manifest_records_scenario_native_lineage() -> None:
    manifest = ptrade_manifest_for(
        QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
        QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
    )

    assert manifest is QUENTX_SCENARIO_NATIVE_MANIFEST
    assert manifest.strategy_module.endswith("quentx_scenario_native_strategy")
    assert manifest.scheduled_callbacks == ("scheduled_scan",)
    assert "instrument_states" in manifest.context_fields
    assert manifest.candidate_data_policy == "active-scenario-point-in-time-only"
    assert "QuentX5_2_3_retest_soft_promoted_v20260721" in manifest.strategy_lineage


def test_quentx_reproduces_the_frozen_legacy_a_aggregation_contract() -> None:
    start = datetime(2024, 1, 1, 9, 31)
    rows = tuple(
        {
            "simulation_time": start + timedelta(minutes=index),
            "open": Decimal(index + 1),
            "high": Decimal(index + 1) + Decimal("0.5"),
            "low": Decimal(index + 1) - Decimal("0.5"),
            "close": Decimal(index + 1),
            "volume": Decimal("10"),
            "amount": Decimal("100"),
        }
        for index in range(480)
    )

    aggregated = quentx_strategy._legacy_a_five_minute_bars(rows)

    assert len(aggregated) == 64
    assert aggregated[0] == {
        "simulation_time": start + timedelta(minutes=164),
        "open": Decimal("161"),
        "high": Decimal("165.5"),
        "low": Decimal("160.5"),
        "close": Decimal("165"),
        "volume": Decimal("50"),
        "amount": Decimal("500"),
    }
    assert aggregated[-1]["simulation_time"] == start + timedelta(minutes=479)
    assert aggregated[-1]["open"] == Decimal("476")
    assert aggregated[-1]["close"] == Decimal("480")


def test_quentx_preserves_the_legacy_a_incomplete_tail_group() -> None:
    rows = tuple(
        {
            "simulation_time": datetime(2024, 1, 1, 9, 31)
            + timedelta(minutes=index),
            "open": Decimal(index + 1),
            "high": Decimal(index + 1),
            "low": Decimal(index + 1),
            "close": Decimal(index + 1),
            "volume": Decimal("1"),
            "amount": Decimal("1"),
        }
        for index in range(7)
    )

    aggregated = quentx_strategy._legacy_a_five_minute_bars(rows)

    assert len(aggregated) == 2
    assert aggregated[-1]["open"] == Decimal("6")
    assert aggregated[-1]["close"] == Decimal("7")
    assert aggregated[-1]["volume"] == Decimal("2")


def test_quentx_523_low_volume_retest_keeps_hard_and_soft_paths_distinct() -> None:
    hard = quentx_strategy._low_volume_retest_assessment(
        state="institutional_mainline_post_breakout_retest",
        volume_ratio=Decimal("0.8"),
        current_price=Decimal("9.9"),
        defense_price=Decimal("10"),
        smoothness=Decimal("0.8"),
        day_close_position=Decimal("0.8"),
        late_close_position=Decimal("0.8"),
    )
    soft = quentx_strategy._low_volume_retest_assessment(
        state="institutional_mainline_post_breakout_retest",
        volume_ratio=Decimal("0.8"),
        current_price=Decimal("10.1"),
        defense_price=Decimal("10"),
        smoothness=Decimal("0.50"),
        day_close_position=Decimal("0.40"),
        late_close_position=Decimal("0.35"),
    )

    assert hard == (True, ())
    assert soft == (
        False,
        ("structure_not_smooth", "day_demand_weak", "late_demand_weak"),
    )
    assert quentx_strategy._entry_position_scale(
        market_state="neutral",
        industry_ret20=Decimal("0.05"),
        retest_soft_reasons=soft[1],
    ) == Decimal("0.50")


def test_quentx_keeps_overheat_penalties_and_industry_concentration_limits() -> None:
    synchronized_overheat = _metrics(ret3="0.06", ret5="0.07")
    extended = _metrics(ret3="0.12", ret5="0.30", box_width="0.36")
    ordinary_sector = quentx_strategy._SectorContext(
        industry="banking",
        ret5=Decimal("0.04"),
        ret20=Decimal("0.08"),
        breadth20=Decimal("0.60"),
        amount_share=Decimal("0.20"),
        persistence=Decimal("0.80"),
        mainline_score=Decimal("0.85"),
    )
    candidate = quentx_strategy._Candidate(
        instrument="sh.600000",
        industry="banking",
        state="institutional_mainline_trend_pullback",
        price=Decimal("10"),
        score=Decimal("0.9"),
        structural_score=Decimal("0.9"),
        behavior_score=Decimal("0.8"),
        durability=Decimal("0.8"),
        defense_price=Decimal("9"),
        position_scale=Decimal("1"),
        sector=ordinary_sector,
    )

    assert quentx_strategy._entry_overextension_penalty(
        synchronized_overheat
    ) == Decimal("0.06")
    assert quentx_strategy._entry_overextension_penalty(extended) == Decimal(
        "0.44"
    )
    assert quentx_strategy._industry_position_limit(candidate) == 2
    fully_confirmed = replace(
        candidate,
        sector=replace(
            ordinary_sector,
            breadth20=Decimal("0.70"),
            persistence=Decimal("0.95"),
            mainline_score=Decimal("0.90"),
        ),
    )
    assert quentx_strategy._industry_position_limit(fully_confirmed) == 3


def test_quentx_initializes_and_schedules_through_the_host() -> None:
    now = datetime(2024, 1, 2, 10, 0)
    invocation = _invocation(
        (
            _node(
                "sh.600000",
                now,
                price="10",
                rank=1,
                candidate_score="0.08",
                relative_strength="0.04",
            ),
        )
    )

    result = InProcessPTradeStrategyHost().invoke(invocation)

    assert result.lifecycle_events == ("initialize",)
    assert result.scheduled_callbacks == (("scheduled_scan", 30),)
    assert [(item.call, item.value) for item in result.configuration_requests] == [
        ("set_slippage", Decimal("5")),
        ("set_commission", Decimal("3")),
    ]
    assert result.runtime_state.universe == ("sh.600000",)
    assert dict(result.runtime_state.strategy_state)["quentx.candidate_source"] == (
        "active_scenario"
    )


def test_quentx_generates_filters_and_ranks_candidates_from_the_active_scenario() -> None:
    now = datetime(2024, 1, 2, 10, 0)
    latest = (
        _node(
            "sh.600000",
            now,
            price="100",
            rank=1,
            candidate_score="0.09",
            relative_strength="0.05",
            sector_breadth="0.85",
        ),
        _node(
            "sz.000001",
            now,
            price="200",
            rank=2,
            candidate_score="-0.03",
            relative_strength="-0.04",
            sector_breadth="0.30",
        ),
    )
    host = InProcessPTradeStrategyHost()
    initialized = host.invoke(_invocation(latest))

    decision = host.invoke(
        _invocation(
            latest,
            event="decision",
            runtime_state=initialized.runtime_state,
            history_starts={"sh.600000": "65", "sz.000001": "210"},
        )
    )

    order_pairs = [(item.instrument, item.amount) for item in decision.order_requests]
    debug_state = dict(decision.runtime_state.strategy_state)
    assert order_pairs == [("sh.600000", 100)], (
        debug_state.get("quentx.last_candidate_rejections"),
        debug_state.get("quentx.last_history_shape"),
        debug_state.get("quentx.last_ranked_candidates"),
    )
    assert set(decision.runtime_state.universe) == {"sh.600000", "sz.000001"}
    assert "get_current_data" in decision.market_data_calls
    assert any(call.startswith("get_history:1m:480") for call in decision.market_data_calls)
    assert any(call.startswith("get_history:1d:180") for call in decision.market_data_calls)
    strategy_state = dict(decision.runtime_state.strategy_state)
    assert "sh.600000" in strategy_state["quentx.last_ranked_candidates"]
    assert "sz.000001" not in strategy_state["quentx.last_ranked_candidates"]
    assert strategy_state["quentx.history_contract"] == (
        "180x1d-state+480x1m->legacy-a->last64x5m-confirmation"
    )


def test_quentx_production_host_preserves_runtime_state_across_processes() -> None:
    now = datetime(2024, 1, 2, 10, 0)
    latest = (
        _node(
            "sh.600000",
            now,
            price="100",
            rank=1,
            candidate_score="0.09",
            relative_strength="0.05",
            sector_breadth="0.85",
        ),
    )
    host = SubprocessPTradeStrategyHost()

    initialized = host.invoke(_invocation(latest))
    decision = host.invoke(
        _invocation(
            latest,
            event="decision",
            runtime_state=initialized.runtime_state,
            history_starts={"sh.600000": "65"},
        )
    )

    assert initialized.process_id != os.getpid()
    assert decision.process_id != os.getpid()
    assert decision.runtime_state.initialized is True
    assert dict(decision.runtime_state.strategy_state)[
        "quentx.candidate_source"
    ] == "active_scenario"
    assert [(item.instrument, item.amount) for item in decision.order_requests] == [
        ("sh.600000", 100)
    ]


def test_quentx_daily_state_machine_refuses_intraday_only_history() -> None:
    now = datetime(2024, 1, 2, 10, 0)
    latest = (
        _node(
            "sh.600000",
            now,
            price="100",
            rank=1,
            candidate_score="0.09",
            relative_strength="0.05",
            sector_breadth="0.85",
        ),
    )
    host = InProcessPTradeStrategyHost()
    initialized = host.invoke(_invocation(latest))
    invocation = _invocation(
        latest,
        event="decision",
        runtime_state=initialized.runtime_state,
        history_starts={"sh.600000": "65"},
    )
    intraday_only = replace(
        invocation,
        market_history=tuple(
            node
            for node in invocation.market_history
            if node.simulation_time.date() == now.date()
        ),
    )

    decision = host.invoke(intraday_only)

    assert decision.order_requests == ()
    state = dict(decision.runtime_state.strategy_state)
    assert state["quentx.last_candidate_rejections"] == (
        '{"insufficient_completed_daily_history":1}'
    )
    assert '"completed_daily":0' in state["quentx.last_history_shape"]


def test_quentx_daily_loss_guard_blocks_new_entries() -> None:
    now = datetime(2024, 1, 2, 10, 0)
    latest = (
        _node(
            "sh.600000",
            now,
            price="100",
            rank=1,
            candidate_score="0.09",
            relative_strength="0.05",
            sector_breadth="0.85",
        ),
    )
    host = InProcessPTradeStrategyHost()
    initialized = host.invoke(_invocation(latest, available_cash="100000"))

    decision = host.invoke(
        _invocation(
            latest,
            available_cash="94000",
            event="decision",
            runtime_state=initialized.runtime_state,
            history_starts={"sh.600000": "85"},
        )
    )

    assert decision.order_requests == ()
    assert any("5% daily loss guard" in item.message for item in decision.log_records)


def test_quentx_daily_loss_guard_blocks_full_portfolio_rotation_buys() -> None:
    now = datetime(2024, 1, 2, 10, 0)
    latest = (
        _node("sh.600000", now, price="100", rank=4, candidate_score="-0.08", relative_strength="-0.07"),
        _node("sz.000001", now, price="100", rank=2, candidate_score="0.02", relative_strength="0.01"),
        _node("sh.600001", now, price="100", rank=3, candidate_score="0.01", relative_strength="0.01"),
        _node("sz.000002", now, price="100", rank=1, candidate_score="0.12", relative_strength="0.08", sector_breadth="0.90"),
    )
    positions = (
        _position("sh.600000"),
        _position("sz.000001"),
        _position("sh.600001"),
    )
    host = InProcessPTradeStrategyHost()
    initialized = host.invoke(
        _invocation(latest, positions=positions, available_cash="10000")
    )

    decision = host.invoke(
        _invocation(
            latest,
            positions=positions,
            available_cash="7000",
            event="decision",
            runtime_state=initialized.runtime_state,
            history_starts={
                "sh.600000": "95",
                "sz.000001": "99",
                "sh.600001": "99",
                "sz.000002": "65",
            },
        )
    )

    assert decision.order_requests == ()
    assert any("5% daily loss guard" in item.message for item in decision.log_records)


def test_quentx_early_failure_risk_submits_a_signed_exit_order() -> None:
    now = datetime(2024, 1, 2, 10, 0)
    latest = (
        _node(
            "sh.600000",
            now,
            price="91",
            rank=1,
            candidate_score="0.01",
            relative_strength="-0.02",
        ),
    )
    position = _position(
        "sh.600000",
        average_cost="100",
        market_price="91",
    )
    host = InProcessPTradeStrategyHost()
    initialized = host.invoke(
        _invocation(latest, positions=(position,), available_cash="0")
    )

    decision = host.invoke(
        _invocation(
            latest,
            positions=(position,),
            available_cash="0",
            event="decision",
            runtime_state=initialized.runtime_state,
            history_starts={"sh.600000": "100"},
        )
    )

    assert [(item.instrument, item.amount) for item in decision.order_requests] == [
        ("sh.600000", -100)
    ]
    assert any("early_failure_8pct" in item.message for item in decision.log_records)


def test_partial_risk_exit_does_not_release_a_portfolio_slot_or_full_cash() -> None:
    now = datetime(2024, 1, 2, 10, 0)
    latest = (
        _node("sh.600000", now, price="91", rank=4, candidate_score="-0.08", relative_strength="-0.07"),
        _node("sz.000001", now, price="100", rank=2, candidate_score="0.02", relative_strength="0.01"),
        _node("sh.600001", now, price="100", rank=3, candidate_score="0.01", relative_strength="0.01"),
        _node("sz.000002", now, price="100", rank=1, candidate_score="0.12", relative_strength="0.08", sector_breadth="0.90"),
    )
    positions = (
        _position("sh.600000", amount=200, closeable_amount=100, average_cost="100", market_price="91"),
        _position("sz.000001"),
        _position("sh.600001"),
    )
    host = InProcessPTradeStrategyHost()
    initialized = host.invoke(
        _invocation(latest, positions=positions, available_cash="0")
    )

    decision = host.invoke(
        _invocation(
            latest,
            positions=positions,
            available_cash="0",
            event="decision",
            runtime_state=initialized.runtime_state,
            history_starts={
                "sh.600000": "100",
                "sz.000001": "99",
                "sh.600001": "99",
                "sz.000002": "80",
            },
        )
    )

    assert [(item.instrument, item.amount) for item in decision.order_requests] == [
        ("sh.600000", -100)
    ]


def test_quentx_rotates_a_weak_holding_into_a_superior_scenario_candidate() -> None:
    now = datetime(2024, 1, 2, 10, 0)
    latest = (
        _node(
            "sh.600000",
            now,
            price="100",
            rank=4,
            candidate_score="-0.08",
            relative_strength="-0.07",
            sector_breadth="0.30",
        ),
        _node(
            "sz.000002",
            now,
            price="100",
            rank=1,
            candidate_score="0.12",
            relative_strength="0.08",
            sector_breadth="0.90",
        ),
        _node(
            "sz.000001",
            now,
            price="100",
            rank=2,
            candidate_score="0.02",
            relative_strength="0.01",
        ),
        _node(
            "sh.600001",
            now,
            price="100",
            rank=3,
            candidate_score="0.01",
            relative_strength="0.01",
        ),
    )
    positions = (
        _position("sh.600000", amount=200, closeable_amount=200),
        _position("sz.000001", amount=200, closeable_amount=200),
        _position("sh.600001", amount=200, closeable_amount=200),
    )
    host = InProcessPTradeStrategyHost()
    initialized = host.invoke(
        _invocation(latest, positions=positions, available_cash="0")
    )
    strategy_state = dict(initialized.runtime_state.strategy_state)
    strategy_state["quentx.entry_defense.sh.600000"] = "104"
    strategy_state["quentx.entry.sh.600000.day"] = (
        now.date() - timedelta(days=45)
    ).isoformat()
    runtime_state = replace(
        initialized.runtime_state,
        strategy_state=tuple(sorted(strategy_state.items())),
    )
    history_starts = {
        "sh.600000": "95",
        "sz.000001": "99",
        "sh.600001": "99",
        "sz.000002": "65",
    }
    immature_state = dict(strategy_state)
    immature_state["quentx.entry.sh.600000.day"] = (
        now.date() - timedelta(days=10)
    ).isoformat()
    immature = host.invoke(
        _invocation(
            latest,
            positions=positions,
            available_cash="0",
            event="decision",
            runtime_state=replace(
                runtime_state,
                strategy_state=tuple(sorted(immature_state.items())),
            ),
            history_starts=history_starts,
        )
    )
    assert immature.order_requests == ()

    cooldown_state = dict(strategy_state)
    cooldown_state["quentx.last_rotation_day"] = (
        now.date() - timedelta(days=29)
    ).isoformat()
    cooldown = host.invoke(
        _invocation(
            latest,
            positions=positions,
            available_cash="0",
            event="decision",
            runtime_state=replace(
                runtime_state,
                strategy_state=tuple(sorted(cooldown_state.items())),
            ),
            history_starts=history_starts,
        )
    )
    assert cooldown.order_requests == ()

    decision = host.invoke(
        _invocation(
            latest,
            positions=positions,
            available_cash="0",
            event="decision",
            runtime_state=runtime_state,
            history_starts=history_starts,
        )
    )

    assert [(item.instrument, item.amount) for item in decision.order_requests] == [
        ("sh.600000", -200),
    ]
    assert any(
        "sell_then_reassess_next_session" in item.message
        for item in decision.log_records
    )


@pytest.mark.parametrize(
    "forbidden_call",
    (
        "open",
        "__import__",
        "load_external_market_path",
        "load_legacy_candidate_cache",
    ),
)
def test_formal_host_rejects_external_or_legacy_candidate_access(
    forbidden_call: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2024, 1, 2, 10, 0)
    invocation = _invocation(
        (
            _node(
                "sh.600000",
                now,
                price="10",
                rank=1,
                candidate_score="0.08",
                relative_strength="0.04",
            ),
        )
    )
    strategy_module = ModuleType("formal_data_access_probe")

    def initialize(_context: object) -> None:
        forbidden = getattr(strategy_module, forbidden_call)
        forbidden("C:/external-real-market/candidates.csv")

    setattr(strategy_module, "initialize", initialize)
    monkeypatch.setattr(
        ptrade_host_module,
        "_load_strategy_module",
        lambda _manifest: strategy_module,
    )

    with pytest.raises(
        PTradeCompatibilityError,
        match=r"ptrade_surface\.v1.*formal Scenario Data World",
    ):
        InProcessPTradeStrategyHost().invoke(invocation)


@pytest.mark.parametrize(
    "probe_source",
    (
        "reader = open\n"
        "def initialize(context):\n"
        "    reader('C:/external-real-market/candidates.csv')\n",
        "reader = open\n"
        "reader('C:/external-real-market/candidates.csv')\n"
        "def initialize(context):\n"
        "    pass\n",
    ),
)
def test_formal_host_blocks_builtin_aliases_before_real_module_execution(
    probe_source: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2024, 1, 2, 10, 0)
    invocation = _invocation(
        (
            _node(
                "sh.600000",
                now,
                price="10",
                rank=1,
                candidate_score="0.08",
                relative_strength="0.04",
            ),
        )
    )
    module_name = "strategy_diagnostics.formal_alias_probe"
    source_path = tmp_path / "formal_alias_probe.py"
    source_path.write_text(probe_source, encoding="utf-8")
    specification = importlib.util.spec_from_file_location(
        module_name,
        source_path,
    )
    assert specification is not None
    probe_manifest = replace(
        QUENTX_SCENARIO_NATIVE_MANIFEST,
        strategy_module=module_name,
    )
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda _name: specification,
    )
    monkeypatch.setattr(
        ptrade_host_module,
        "ptrade_manifest_for",
        lambda _strategy_id, _strategy_version: probe_manifest,
    )

    with pytest.raises(
        PTradeCompatibilityError,
        match=r"ptrade_surface\.v1.*formal Scenario Data World",
    ):
        InProcessPTradeStrategyHost().invoke(
            replace(
                invocation,
                compatibility_manifest_hash=probe_manifest.content_hash,
            )
        )
