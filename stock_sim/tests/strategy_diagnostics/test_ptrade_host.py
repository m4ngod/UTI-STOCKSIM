from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
import importlib.util
import json
import os
from pathlib import Path
import random
import sys
from types import ModuleType

import pytest

from strategy_diagnostics import InstrumentState, MarketPathNode, ScenarioMarketSnapshot
import strategy_diagnostics.ptrade_host as ptrade_host_module
from strategy_diagnostics.ptrade_host import (
    LIVE_MINUTE_SCENARIO_NATIVE_MANIFEST,
    PTRADE_SUBPROCESS_HOST_VERSION,
    PTRADE_SURFACE_VERSION,
    InProcessPTradeStrategyHost,
    PTradeCompatibilityError,
    PTradeHostInvocation,
    PTradeHostProcessError,
    PTradePortfolioSnapshot,
    PTradePositionSnapshot,
    QUENTX_SCENARIO_NATIVE_MANIFEST,
    REFERENCE_PTRADE_COMPATIBILITY_MANIFEST,
    SubprocessPTradeStrategyHost,
)


class _StaticWorkerTransport:
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text

    def exchange(
        self,
        request_text: str,
        *,
        python_executable: str,
        timeout_seconds: float,
    ) -> str:
        assert request_text
        assert python_executable
        assert timeout_seconds > 0
        return self._response_text


def _subprocess_host_with_response(
    response_text: str,
) -> SubprocessPTradeStrategyHost:
    return SubprocessPTradeStrategyHost(
        transport=_StaticWorkerTransport(response_text)
    )


def _market_node(
    instrument: str,
    simulation_time: datetime,
    *,
    price: str,
    rank: int,
) -> MarketPathNode:
    value = Decimal(price)
    return MarketPathNode(
        instrument=instrument,
        simulation_time=simulation_time,
        open=value,
        high=value,
        low=value,
        close=value,
        volume=10_000,
        amount=value * 10_000,
        reconstructed=True,
        features=(
            ("candidate_rank", Decimal(rank)),
            ("candidate_score", Decimal(3 - rank)),
        ),
    )


def _invocation() -> PTradeHostInvocation:
    earlier = datetime(2024, 1, 2, 9, 59, 30)
    decision_time = datetime(2024, 1, 2, 10, 0)
    instruments = ("sh.600000", "sz.000001")
    latest_nodes = (
        _market_node(instruments[0], decision_time, price="10", rank=1),
        _market_node(instruments[1], decision_time, price="20", rank=2),
    )
    states = tuple(
        InstrumentState(
            instrument=instrument,
            effective_at=datetime(2024, 1, 2, 9, 30),
            eligible=True,
            trading_status="trading",
            is_st=False,
            industry=industry,
            decision_adjustment_factor=Decimal("1"),
            decision_adjustment_provenance="ptrade-host-fixture.v1",
        )
        for instrument, industry in zip(
            instruments,
            ("banking", "technology"),
            strict=True,
        )
    )
    return PTradeHostInvocation(
        run_id="strategy-run-ptrade-reference",
        strategy_id="anchored-ranked-candidate-reference",
        strategy_version="anchored-ranked-candidate-reference.v1",
        compatibility_manifest_hash=(
            REFERENCE_PTRADE_COMPATIBILITY_MANIFEST.content_hash
        ),
        materialization_hash="a" * 64,
        simulation_time=decision_time,
        decision_cadence_minutes=30,
        order_shares=100,
        random_seed=17,
        market_snapshot=ScenarioMarketSnapshot(
            simulation_time=decision_time,
            eligible_universe=instruments,
            states=states,
            latest_nodes=latest_nodes,
        ),
        market_history=tuple(
            _market_node(instrument, at_time, price=price, rank=rank)
            for at_time in (earlier, decision_time)
            for instrument, price, rank in (
                (instruments[0], "10", 1),
                (instruments[1], "20", 2),
            )
        ),
        portfolio=PTradePortfolioSnapshot(
            available_cash=Decimal("100000"),
            total_value=Decimal("100000"),
            positions=(),
        ),
    )


def test_ptrade_surface_manifest_is_versioned_and_fails_unknown_calls() -> None:
    manifest = REFERENCE_PTRADE_COMPATIBILITY_MANIFEST

    assert manifest.surface_version == PTRADE_SURFACE_VERSION == "ptrade_surface.v1"
    assert set(manifest.lifecycle_callbacks) == {"initialize", "handle_data"}
    assert {
        "run_daily",
        "set_universe",
        "get_history",
        "get_current_data",
        "set_slippage",
        "set_commission",
        "order",
        "log.info",
        "log.warning",
        "log.error",
    } <= set(manifest.supported_calls)
    assert {
        "current_dt",
        "portfolio",
        "state",
    } <= set(manifest.context_fields)
    assert {
        "available_cash",
        "total_value",
        "positions",
    } <= set(manifest.portfolio_fields)
    assert len(manifest.content_hash) == 64
    assert manifest.history_units == ("30s",)
    assert QUENTX_SCENARIO_NATIVE_MANIFEST.history_units == ("1m", "1d")
    assert LIVE_MINUTE_SCENARIO_NATIVE_MANIFEST.history_units == ("1m",)
    manifest.require_call("get_history")

    with pytest.raises(
        PTradeCompatibilityError,
        match=r"ptrade_surface\.v1.*get_fundamentals",
    ):
        manifest.require_call("get_fundamentals")


def test_reference_manifest_hides_undeclared_context_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy_module = ModuleType("reference_context_capability_probe")

    def initialize(context: object) -> None:
        getattr(context, "instrument_states")

    setattr(strategy_module, "initialize", initialize)
    monkeypatch.setattr(
        ptrade_host_module,
        "_load_strategy_module",
        lambda _manifest: strategy_module,
    )

    with pytest.raises(
        PTradeCompatibilityError,
        match=r"ptrade_surface\.v1.*context\.instrument_states",
    ):
        InProcessPTradeStrategyHost().invoke(_invocation())


def test_real_loader_context_reflection_cannot_recover_undeclared_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "strategy_diagnostics.reference_context_reflection_probe"
    source_path = tmp_path / "reference_context_reflection_probe.py"
    source_path.write_text(
        "def initialize(context):\n"
        "    object.__getattribute__(context, 'instrument_states')\n",
        encoding="utf-8",
    )
    specification = importlib.util.spec_from_file_location(
        module_name,
        source_path,
    )
    assert specification is not None
    probe_manifest = replace(
        REFERENCE_PTRADE_COMPATIBILITY_MANIFEST,
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
    invocation = replace(
        _invocation(),
        compatibility_manifest_hash=probe_manifest.content_hash,
    )

    with pytest.raises(AttributeError, match="instrument_states"):
        InProcessPTradeStrategyHost().invoke(invocation)


def test_registered_strategy_loader_uses_packaged_auditable_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = QUENTX_SCENARIO_NATIVE_MANIFEST.strategy_module
    compiled_origin = tmp_path / "compiled-module.pyd"
    specification = importlib.util.spec_from_file_location(
        module_name,
        compiled_origin,
    )
    assert specification is not None
    source_path = (
        tmp_path
        / "strategy_diagnostics"
        / "formal_sources"
        / "quentx_scenario_native_strategy.py.txt"
    )
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        Path(ptrade_host_module.__file__)
        .with_name("quentx_scenario_native_strategy.py")
        .read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda _name: specification,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [str(tmp_path / "UTI-Frontend-V2.exe")],
    )

    module = ptrade_host_module._load_strategy_module(
        QUENTX_SCENARIO_NATIVE_MANIFEST
    )

    assert (
        module.STRATEGY_LINEAGE
        == "QuentX5_2_3_retest_soft_promoted_v20260721"
    )


def test_strategy_loader_audits_source_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "strategy_diagnostics.formal_strategy_audit_probe"
    source_path = tmp_path / "formal_strategy_audit_probe.py"
    source_path.write_text(
        "open('external-market-path.parquet')\n",
        encoding="utf-8",
    )
    specification = importlib.util.spec_from_file_location(
        module_name,
        source_path,
    )
    assert specification is not None
    manifest = replace(
        REFERENCE_PTRADE_COMPATIBILITY_MANIFEST,
        strategy_module=module_name,
    )
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda _name: specification,
    )

    with pytest.raises(
        PTradeCompatibilityError,
        match=r"external_market_path",
    ):
        ptrade_host_module._load_strategy_module(manifest)


def test_registered_packaged_strategy_rejects_ast_clean_source_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = QUENTX_SCENARIO_NATIVE_MANIFEST.strategy_module
    compiled_origin = tmp_path / "compiled-module.pyd"
    specification = importlib.util.spec_from_file_location(
        module_name,
        compiled_origin,
    )
    assert specification is not None
    source_path = (
        tmp_path
        / "strategy_diagnostics"
        / "formal_sources"
        / "quentx_scenario_native_strategy.py.txt"
    )
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "SOURCE_KIND = 'ast-clean-but-tampered'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda _name: specification,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [str(tmp_path / "UTI-Frontend-V2.exe")],
    )

    with pytest.raises(
        PTradeCompatibilityError,
        match=r"source integrity mismatch",
    ):
        ptrade_host_module._load_strategy_module(
            QUENTX_SCENARIO_NATIVE_MANIFEST
        )


def test_reference_manifest_rejects_undeclared_history_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy_module = ModuleType("reference_history_capability_probe")

    def initialize(_context: object) -> None:
        history_reader = getattr(strategy_module, "get_history")
        history_reader(count=1, unit="1m", fields=("close",))

    setattr(strategy_module, "initialize", initialize)
    monkeypatch.setattr(
        ptrade_host_module,
        "_load_strategy_module",
        lambda _manifest: strategy_module,
    )

    with pytest.raises(
        PTradeCompatibilityError,
        match=r"ptrade_surface\.v1.*get_history.*declared units are 30s",
    ):
        InProcessPTradeStrategyHost().invoke(_invocation())


def test_in_process_host_runs_reference_lifecycle_and_signed_share_order() -> None:
    invocation = _invocation()
    host = InProcessPTradeStrategyHost()

    first = host.invoke(invocation)

    assert first.host_adapter_version == "ptrade-in-process-host.v1"
    assert first.lifecycle_events == ("initialize", "scheduled:rebalance")
    assert first.scheduled_callbacks == (("rebalance", 30),)
    assert [item.to_dict() for item in first.configuration_requests] == [
        {"call": "set_slippage", "value": "0"},
        {"call": "set_commission", "value": "3"},
    ]
    assert [item.to_dict() for item in first.order_requests] == [
        {"instrument": "sh.600000", "amount": 100}
    ]
    assert first.market_data_calls == (
        "get_history:30s:2:close,volume",
        "get_current_data",
    )
    assert first.runtime_state.initialized is True
    assert first.runtime_state.strategy_state == (("submitted", "true"),)
    assert first.log_records[0].message.startswith("Reference PTrade strategy initialized")

    later_time = datetime(2024, 1, 2, 10, 30)
    later_nodes = tuple(
        replace(node, simulation_time=later_time) for node in invocation.market_snapshot.latest_nodes
    )
    second = host.invoke(
        replace(
            invocation,
            simulation_time=later_time,
            market_snapshot=replace(
                invocation.market_snapshot,
                simulation_time=later_time,
                latest_nodes=later_nodes,
            ),
            market_history=invocation.market_history + later_nodes,
            portfolio=PTradePortfolioSnapshot(
                available_cash=Decimal("98995"),
                total_value=Decimal("99995"),
                positions=(
                    PTradePositionSnapshot(
                        instrument="sh.600000",
                        amount=100,
                        closeable_amount=0,
                        average_cost=Decimal("10.05"),
                        market_price=Decimal("10"),
                        market_value=Decimal("1000"),
                    ),
                ),
            ),
            runtime_state=first.runtime_state,
        )
    )

    assert second.lifecycle_events == ("scheduled:rebalance",)
    assert second.configuration_requests == ()
    assert second.order_requests == ()
    assert second.runtime_state == first.runtime_state

    handled = host.invoke(
        replace(
            invocation,
            event="handle_data",
            runtime_state=first.runtime_state,
        )
    )
    assert handled.lifecycle_events == ("handle_data",)
    assert handled.order_requests == ()
    assert handled.log_records[-1].message.endswith("callback completed.")
    assert "strategy_diagnostics.reference_ptrade_strategy" not in sys.modules


def test_subprocess_host_isolates_random_globals_logs_and_failures() -> None:
    invocation = _invocation()
    host = SubprocessPTradeStrategyHost()
    parent_random_state = random.getstate()

    first = host.invoke(invocation)
    second = host.invoke(invocation)

    assert first.host_adapter_version == "ptrade-subprocess-host.v1"
    assert first.process_id != os.getpid()
    assert second.process_id != os.getpid()
    assert first.worker_global_counter == second.worker_global_counter == 2
    assert first.random_probe == second.random_probe
    assert random.getstate() == parent_random_state
    assert first.log_records == second.log_records
    assert "strategy_diagnostics.ptrade_host_worker" not in sys.modules

    with pytest.raises(
        PTradeCompatibilityError,
        match=r"ptrade_surface\.v1.*unsupported-reference",
    ):
        host.invoke(replace(invocation, strategy_id="unsupported-reference"))

    recovered = host.invoke(invocation)
    assert recovered.order_requests == first.order_requests
    assert recovered.worker_global_counter == 2

    invalid_nodes = tuple(
        replace(node, features=())
        for node in invocation.market_snapshot.latest_nodes
    )
    with pytest.raises(PTradeHostProcessError, match=r"ValueError.*candidate ranking"):
        host.invoke(
            replace(
                invocation,
                market_snapshot=replace(
                    invocation.market_snapshot,
                    latest_nodes=invalid_nodes,
                ),
                market_history=tuple(
                    replace(node, features=())
                    for node in invocation.market_history
                ),
            )
        )

    assert host.invoke(invocation).order_requests == first.order_requests


def test_runtime_rebinds_expanding_and_empty_point_in_time_universes() -> None:
    invocation = _invocation()
    first_instrument = invocation.market_snapshot.eligible_universe[0]
    first_snapshot = replace(
        invocation.market_snapshot,
        eligible_universe=(first_instrument,),
        states=tuple(
            item
            for item in invocation.market_snapshot.states
            if item.instrument == first_instrument
        ),
        latest_nodes=tuple(
            item
            for item in invocation.market_snapshot.latest_nodes
            if item.instrument == first_instrument
        ),
    )
    first_invocation = replace(
        invocation,
        event="initialize",
        market_snapshot=first_snapshot,
        market_history=tuple(
            item
            for item in invocation.market_history
            if item.instrument == first_instrument
        ),
    )
    host = InProcessPTradeStrategyHost()

    initialized = host.invoke(first_invocation)
    expanded = host.invoke(
        replace(
            invocation,
            runtime_state=initialized.runtime_state,
        )
    )
    empty = host.invoke(
        replace(
            invocation,
            event="decision",
            market_snapshot=ScenarioMarketSnapshot(
                simulation_time=invocation.simulation_time,
                eligible_universe=(),
                states=(),
                latest_nodes=(),
            ),
            market_history=(),
            runtime_state=expanded.runtime_state,
        )
    )

    assert initialized.runtime_state.universe == (first_instrument,)
    assert expanded.runtime_state.universe == (
        "sh.600000",
        "sz.000001",
    )
    assert empty.runtime_state.universe == ()
    assert empty.order_requests == ()


@pytest.mark.parametrize(
    "response_text",
    (
        "[]",
        '{"protocol_version":"ptrade-subprocess-json.v1","ok":"false"}',
        '{"protocol_version":"wrong","ok":true,"result":{}}',
    ),
)
def test_subprocess_response_schema_fails_closed(response_text: str) -> None:
    with pytest.raises(PTradeHostProcessError):
        _subprocess_host_with_response(response_text).invoke(_invocation())


def test_subprocess_response_rejects_malformed_nested_result_fields() -> None:
    result_payload = InProcessPTradeStrategyHost().invoke(_invocation()).to_dict()
    result_payload["lifecycle_events"] = "initialize"
    response_text = json.dumps(
        {
            "protocol_version": "ptrade-subprocess-json.v1",
            "ok": True,
            "result": result_payload,
        }
    )

    with pytest.raises(PTradeHostProcessError, match="host contract"):
        _subprocess_host_with_response(response_text).invoke(_invocation())


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    (
        ("surface_version", "ptrade_surface.v0"),
        ("manifest_hash", "0" * 64),
        ("host_adapter_version", "ptrade-subprocess-host.v0"),
    ),
)
def test_subprocess_response_rejects_worker_identity_mismatch(
    field: str,
    wrong_value: str,
) -> None:
    result = replace(
        InProcessPTradeStrategyHost().invoke(_invocation()),
        host_adapter_version=PTRADE_SUBPROCESS_HOST_VERSION,
    ).to_dict()
    result[field] = wrong_value
    response_text = json.dumps(
        {
            "protocol_version": "ptrade-subprocess-json.v1",
            "ok": True,
            "result": result,
        }
    )

    with pytest.raises(PTradeHostProcessError, match="identity"):
        _subprocess_host_with_response(response_text).invoke(_invocation())


def test_unknown_log_facade_call_is_a_versioned_compatibility_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy_module = ModuleType("unsupported_log_strategy")

    def initialize(_context: object) -> None:
        strategy_module.log.debug("unsupported")

    strategy_module.initialize = initialize
    monkeypatch.setattr(
        ptrade_host_module,
        "_load_strategy_module",
        lambda _manifest: strategy_module,
    )

    with pytest.raises(
        PTradeCompatibilityError,
        match=r"ptrade_surface\.v1.*log\.debug",
    ):
        InProcessPTradeStrategyHost().invoke(
            replace(_invocation(), event="initialize")
        )


def test_subprocess_transport_wraps_start_and_timeout_failures() -> None:
    invocation = _invocation()
    missing = SubprocessPTradeStrategyHost(
        python_executable="Z:\\missing-python-for-ptrade-host.exe"
    )
    with pytest.raises(PTradeHostProcessError, match="could not be started"):
        missing.invoke(invocation)

    timed_out = SubprocessPTradeStrategyHost(timeout_seconds=0.000001)
    with pytest.raises(PTradeHostProcessError, match="timeout"):
        timed_out.invoke(invocation)


def test_subprocess_transport_uses_explicit_frozen_worker_arguments(
    monkeypatch,
) -> None:
    observed: dict[str, object] = {}

    def complete(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return ptrade_host_module.subprocess.CompletedProcess(
            command,
            0,
            stdout="{}",
            stderr="",
        )

    monkeypatch.setattr(ptrade_host_module.subprocess, "run", complete)
    transport = ptrade_host_module._IsolatedSubprocessPTradeWorkerTransport(
        worker_arguments=("--ptrade-host-worker",)
    )

    response = transport.exchange(
        "{}",
        python_executable=r"C:\Release\UTI-Frontend-V2.exe",
        timeout_seconds=5,
    )

    assert response == "{}"
    assert observed["command"] == [
        r"C:\Release\UTI-Frontend-V2.exe",
        "--ptrade-host-worker",
    ]


def test_subprocess_host_rejects_a_string_as_worker_arguments() -> None:
    with pytest.raises(
        ValueError,
        match="sequence of non-empty strings",
    ):
        SubprocessPTradeStrategyHost(
            worker_arguments="--ptrade-host-worker",
        )
