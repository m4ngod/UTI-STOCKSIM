from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
import importlib.util
import json
from pathlib import Path

import pytest

import strategy_diagnostics.ptrade_host as ptrade_host_module
from strategy_diagnostics import InstrumentState, MarketPathNode, ScenarioMarketSnapshot
from strategy_diagnostics.ptrade_host import (
    LIVE_MINUTE_SCENARIO_NATIVE_MANIFEST,
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
    InProcessPTradeStrategyHost,
    PTradeCompatibilityError,
    PTradeHostInvocation,
    PTradePortfolioSnapshot,
    PTradePositionSnapshot,
    PTradeRuntimeState,
    ptrade_manifest_for,
)


def _node(
    instrument: str,
    simulation_time: datetime,
    *,
    price: Decimal,
    volume: int = 10_000,
) -> MarketPathNode:
    return MarketPathNode(
        instrument=instrument,
        simulation_time=simulation_time,
        open=price,
        high=price * Decimal("1.002"),
        low=price * Decimal("0.998"),
        close=price,
        volume=volume,
        amount=price * volume,
        reconstructed=True,
        features=(),
    )


def _intraday_history(
    instrument: str,
    decision_time: datetime,
    *,
    dislocation_rebound: bool,
) -> tuple[MarketPathNode, ...]:
    nodes: list[MarketPathNode] = []
    for index in range(40):
        simulation_time = decision_time - timedelta(seconds=30 * (40 - index))
        if not dislocation_rebound:
            price = Decimal("20")
        elif index < 26:
            price = Decimal("10") - Decimal(index) * Decimal("0.004")
        elif index < 34:
            price = Decimal("9.896") - Decimal(index - 25) * Decimal("0.012")
        else:
            price = Decimal("9.800") + Decimal(index - 33) * Decimal("0.007")
        nodes.append(_node(instrument, simulation_time, price=price))
    return tuple(nodes)


def _invocation(
    *,
    event: str = "initialize",
    runtime_state: object | None = None,
    positions: tuple[PTradePositionSnapshot, ...] = (),
    first_price: str = "9.86",
) -> PTradeHostInvocation:
    decision_time = datetime(2024, 1, 2, 10, 30)
    latest_nodes = (
        _node("sh.600000", decision_time, price=Decimal(first_price)),
        _node("sz.000001", decision_time, price=Decimal("20")),
    )
    instruments = tuple(item.instrument for item in latest_nodes)
    market_history = (
        *_intraday_history(
            instruments[0],
            decision_time,
            dislocation_rebound=True,
        ),
        *_intraday_history(
            instruments[1],
            decision_time,
            dislocation_rebound=False,
        ),
    )
    positions_value = sum(
        (position.market_value for position in positions),
        Decimal("0"),
    )
    return PTradeHostInvocation(
        run_id="live-minute-scenario-native-run",
        strategy_id=LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
        strategy_version=LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
        compatibility_manifest_hash=(
            LIVE_MINUTE_SCENARIO_NATIVE_MANIFEST.content_hash
        ),
        materialization_hash="c" * 64,
        simulation_time=decision_time,
        decision_cadence_minutes=30,
        order_shares=1000,
        random_seed=31,
        market_snapshot=ScenarioMarketSnapshot(
            simulation_time=decision_time,
            eligible_universe=instruments,
            states=tuple(
                InstrumentState(
                    instrument=instrument,
                    effective_at=decision_time - timedelta(days=1),
                    eligible=True,
                    trading_status="trading",
                    is_st=False,
                    industry=industry,
                    decision_adjustment_factor=Decimal("1"),
                    decision_adjustment_provenance="live-minute-fixture.v1",
                )
                for instrument, industry in zip(
                    instruments,
                    ("banking", "technology"),
                    strict=True,
                )
            ),
            latest_nodes=latest_nodes,
        ),
        market_history=market_history,
        portfolio=PTradePortfolioSnapshot(
            available_cash=Decimal("100000"),
            total_value=Decimal("100000") + positions_value,
            positions=positions,
        ),
        event=event,  # type: ignore[arg-type]
        runtime_state=runtime_state,  # type: ignore[arg-type]
    )


def _position(
    instrument: str,
    *,
    average_cost: str,
    market_price: str,
) -> PTradePositionSnapshot:
    amount = 1000
    price = Decimal(market_price)
    return PTradePositionSnapshot(
        instrument=instrument,
        amount=amount,
        closeable_amount=amount,
        average_cost=Decimal(average_cost),
        market_price=price,
        market_value=price * amount,
    )


def test_live_minute_manifest_records_a_distinct_scenario_native_lineage() -> None:
    manifest = ptrade_manifest_for(
        LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
        LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
    )

    assert manifest is LIVE_MINUTE_SCENARIO_NATIVE_MANIFEST
    assert manifest.strategy_module.endswith("live_minute_scenario_native_strategy")
    assert manifest.scheduled_callbacks == ("scheduled_scan",)
    assert manifest.history_units == ("1m",)
    assert "instrument_states" not in manifest.context_fields
    assert manifest.candidate_data_policy == "active-scenario-point-in-time-only"
    assert "ptrade/live_minute_strategy.py" in manifest.strategy_lineage


def test_live_minute_initializes_schedules_and_submits_an_eligible_buy() -> None:
    host = InProcessPTradeStrategyHost()
    initialized = host.invoke(_invocation())
    initialized_state = dict(initialized.runtime_state.strategy_state)

    assert initialized.scheduled_callbacks == (("scheduled_scan", 30),)
    assert initialized_state["live_minute.source_scan_interval_seconds"] == "300"
    assert json.loads(initialized_state["live_minute.config"])["max_positions"] == 5

    decision = host.invoke(
        _invocation(
            event="decision",
            runtime_state=initialized.runtime_state,
        )
    )
    state = dict(decision.runtime_state.strategy_state)

    assert decision.lifecycle_events == ("scheduled:scheduled_scan",)
    assert "get_history:1m:20:close,volume,amount" in decision.market_data_calls
    assert "get_current_data" in decision.market_data_calls
    assert tuple(
        (request.instrument, request.amount) for request in decision.order_requests
    ) == (("sh.600000", 1000),)
    last_scan = json.loads(state["live_minute.last_scan"])
    assert last_scan["candidate_instruments"] == ["sh.600000"]
    assert last_scan["submitted_orders"] == [
        {"amount": 1000, "instrument": "sh.600000", "side": "buy"}
    ]
    ledger = json.loads(state["live_minute.daily_ledger"])
    assert ledger["buy_count"] == 1
    assert ledger["bought_instruments"] == ["sh.600000"]


def test_live_minute_stop_loss_submits_only_a_signed_exit() -> None:
    host = InProcessPTradeStrategyHost()
    position = _position(
        "sh.600000",
        average_cost="10",
        market_price="9.10",
    )
    initialized = host.invoke(
        _invocation(positions=(position,), first_price="9.10")
    )
    decision = host.invoke(
        _invocation(
            event="decision",
            runtime_state=initialized.runtime_state,
            positions=(position,),
            first_price="9.10",
        )
    )

    assert tuple(
        (request.instrument, request.amount) for request in decision.order_requests
    ) == (("sh.600000", -1000),)
    assert all(request.amount < 0 for request in decision.order_requests)
    assert "deferred entries" in decision.log_records[-1].message


@pytest.mark.parametrize(
    "corrupt_ledger",
    (
        None,
        "{not-json",
        (
            '{"bought_instruments":[],"buy_count":0,"scan_count":1,'
            '"trade_date":"2024-01-03"}'
        ),
        (
            '{"bought_instruments":["sh.600000"],"buy_count":0,'
            '"scan_count":1,"trade_date":"2024-01-02"}'
        ),
    ),
)
def test_live_minute_corrupt_or_future_daily_ledger_fails_closed(
    corrupt_ledger: str | None,
) -> None:
    host = InProcessPTradeStrategyHost()
    initialized = host.invoke(_invocation())
    strategy_state = dict(initialized.runtime_state.strategy_state)
    if corrupt_ledger is None:
        strategy_state.pop("live_minute.daily_ledger")
    else:
        strategy_state["live_minute.daily_ledger"] = corrupt_ledger
    corrupt_state = PTradeRuntimeState(
        initialized=True,
        universe=initialized.runtime_state.universe,
        scheduled_callbacks=initialized.runtime_state.scheduled_callbacks,
        strategy_state=tuple(sorted(strategy_state.items())),
    )

    with pytest.raises(ValueError, match="daily risk ledger.*refusing to trade"):
        host.invoke(
            _invocation(
                event="decision",
                runtime_state=corrupt_state,
            )
        )


def test_live_minute_context_has_no_quentx_only_instrument_state_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "strategy_diagnostics.live_minute_context_reflection_probe"
    source_path = tmp_path / "live_minute_context_reflection_probe.py"
    source_path.write_text(
        "def initialize(context):\n"
        "    object.__getattribute__(context, 'instrument_states')\n",
        encoding="utf-8",
    )
    specification = importlib.util.spec_from_file_location(module_name, source_path)
    assert specification is not None
    probe_manifest = replace(
        LIVE_MINUTE_SCENARIO_NATIVE_MANIFEST,
        strategy_module=module_name,
    )
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: specification)
    monkeypatch.setattr(
        ptrade_host_module,
        "ptrade_manifest_for",
        lambda _strategy_id, _strategy_version: probe_manifest,
    )

    with pytest.raises(AttributeError, match="instrument_states"):
        InProcessPTradeStrategyHost().invoke(
            replace(
                _invocation(),
                compatibility_manifest_hash=probe_manifest.content_hash,
            )
        )


def test_live_minute_formal_execution_rejects_external_candidate_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "strategy_diagnostics.live_minute_external_candidate_probe"
    source_path = tmp_path / "live_minute_external_candidate_probe.py"
    source_path.write_text(
        "def initialize(context):\n"
        "    load_legacy_candidate_cache('C:/external/candidates.json')\n",
        encoding="utf-8",
    )
    specification = importlib.util.spec_from_file_location(module_name, source_path)
    assert specification is not None
    probe_manifest = replace(
        LIVE_MINUTE_SCENARIO_NATIVE_MANIFEST,
        strategy_module=module_name,
    )
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: specification)
    monkeypatch.setattr(
        ptrade_host_module,
        "ptrade_manifest_for",
        lambda _strategy_id, _strategy_version: probe_manifest,
    )

    with pytest.raises(
        PTradeCompatibilityError,
        match="Legacy Candidate Cache",
    ):
        InProcessPTradeStrategyHost().invoke(
            replace(
                _invocation(),
                compatibility_manifest_hash=probe_manifest.content_hash,
            )
        )
