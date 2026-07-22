from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from strategy_diagnostics.execution_conditions import (
    RequestedExecutionAssumptions,
    resolve_execution_conditions,
)
from strategy_diagnostics.ptrade_host import (
    LIVE_MINUTE_SCENARIO_NATIVE_MANIFEST,
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
    PTRADE_SUBPROCESS_HOST_VERSION,
    PTradeRunAudit,
    QUENTX_SCENARIO_NATIVE_MANIFEST,
    QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
    QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
)
from strategy_diagnostics.strategy_campaigns import (
    BaselineCampaignRunner,
    BaselineCampaignSpecification,
)
from strategy_diagnostics.strategy_runs import (
    EquityPoint,
    StrategyOrder,
    StrategyRunSnapshot,
    StrategyRunSpecification,
)


def _run_specification(
    *,
    strategy_id: str,
    strategy_version: str,
    manifest_hash: str,
    replica_id: str,
) -> StrategyRunSpecification:
    resolved = resolve_execution_conditions(
        RequestedExecutionAssumptions(
            commission_bps=Decimal("3"),
            slippage_bps=Decimal("5"),
            max_fill_fraction=Decimal("1"),
            latency_nodes=0,
            allow_partial_fills=True,
        ),
        {},
    )
    return StrategyRunSpecification(
        recipe_version_id="recipe-version-baseline",
        recipe_content_hash="a" * 64,
        materialization_hash="b" * 64,
        source_snapshot_id="source-snapshot-baseline",
        materialization_seed=17,
        transformation_catalog_version="scenario-transformation-catalog.v1",
        transformation_implementation_versions=(),
        market_rule_profile_version="a-share-cash-equity.v1",
        execution_policy_version="anchored-standard-execution.v2",
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        decision_cadence_minutes=30,
        initial_cash=Decimal("100000"),
        order_shares=1000,
        replica_id=replica_id,
        code_identity="strategy-diagnostics.v1",
        ptrade_manifest_hash=manifest_hash,
        ptrade_host_adapter_version=PTRADE_SUBPROCESS_HOST_VERSION,
        commission_bps=resolved.effective.commission_bps,
        resolved_execution_conditions=resolved,
    )


def _campaign_specification() -> BaselineCampaignSpecification:
    return BaselineCampaignSpecification(
        campaign_replica_id="baseline-campaign-1",
        strategy_runs=(
            _run_specification(
                strategy_id=QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
                strategy_version=QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
                manifest_hash=QUENTX_SCENARIO_NATIVE_MANIFEST.content_hash,
                replica_id="baseline-campaign-1-quentx",
            ),
            _run_specification(
                strategy_id=LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
                strategy_version=LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
                manifest_hash=LIVE_MINUTE_SCENARIO_NATIVE_MANIFEST.content_hash,
                replica_id="baseline-campaign-1-live-minute",
            ),
        ),
    )


def _snapshot(
    specification: StrategyRunSpecification,
    *,
    status: str = "completed",
    equities: tuple[str, ...] = ("100000", "100100", "99900"),
    failure_message: str | None = None,
) -> StrategyRunSnapshot:
    resolved = specification.resolved_execution_conditions
    if resolved is None:
        raise AssertionError("campaign fixture requires resolved execution conditions")
    start = datetime(2024, 1, 2, 9, 30)
    curve = tuple(
        EquityPoint(
            simulation_time=start + timedelta(seconds=30 * index),
            cash=Decimal(value),
            positions_value=Decimal("0"),
            equity=Decimal(value),
        )
        for index, value in enumerate(equities)
    )
    return StrategyRunSnapshot(
        run_id=specification.run_id,
        status=status,  # type: ignore[arg-type]
        specification=specification,
        current_simulation_time=curve[-1].simulation_time if curve else None,
        processed_node_count=len(curve),
        total_node_count=3,
        decision_times=(start,),
        orders=(),
        fills=(),
        cash=curve[-1].cash if curve else specification.initial_cash,
        positions=(),
        equity_curve=curve,
        ptrade_audit=PTradeRunAudit(
            surface_version=specification.ptrade_surface_version,
            manifest_hash=specification.ptrade_manifest_hash,
            execution_resolution=resolved,
            strategy_id=specification.strategy_id,
            strategy_version=specification.strategy_version,
            host_adapter_versions=(PTRADE_SUBPROCESS_HOST_VERSION,),
        ),
        failure_code="RuntimeError" if failure_message else None,
        failure_message=failure_message,
        run_artifact_hash="c" * 64 if status == "completed" else None,
    )


class _RecordingEngine:
    def __init__(self, snapshots: tuple[StrategyRunSnapshot, ...]) -> None:
        self._snapshots = {item.run_id: item for item in snapshots}
        self.calls: list[tuple[str, str]] = []

    def start(self, specification: StrategyRunSpecification) -> StrategyRunSnapshot:
        self.calls.append(("start", specification.run_id))
        return replace(
            self._snapshots[specification.run_id],
            status="running",
            processed_node_count=0,
            current_simulation_time=None,
            equity_curve=(),
            failure_code=None,
            failure_message=None,
            run_artifact_hash=None,
        )

    def run_to_completion(
        self,
        run_id: str,
        *,
        nodes_per_batch: int = 10_000,
    ) -> StrategyRunSnapshot:
        assert nodes_per_batch > 0
        self.calls.append(("complete", run_id))
        return self._snapshots[run_id]


def test_campaign_runs_two_isolated_replicas_sequentially_and_overlays_curves() -> None:
    specification = _campaign_specification()
    first = replace(
        _snapshot(specification.strategy_runs[0]),
        orders=(
            StrategyOrder(
                order_id="quentx-private-order",
                instrument="sh.600000",
                shares=1000,
                decision_time=datetime(2024, 1, 2, 9, 30),
                activation_time=datetime(2024, 1, 2, 9, 30, 30),
                status="filled",
                accepted_shares=1000,
            ),
        ),
    )
    second = _snapshot(
        specification.strategy_runs[1],
        equities=("100000", "99950", "100200"),
    )
    engine = _RecordingEngine((first, second))

    campaign = BaselineCampaignRunner(engine).run(specification)
    view = campaign.to_dict()

    assert engine.calls == [
        ("start", first.run_id),
        ("complete", first.run_id),
        ("start", second.run_id),
        ("complete", second.run_id),
    ]
    assert campaign.status == "completed"
    assert view["completeness"] == {
        "completed_count": 2,
        "total_count": 2,
        "label": "2/2 complete",
        "is_complete": True,
    }
    assert view["pinned_conditions"]["materialization_hash"] == "b" * 64
    assert view["pinned_conditions"]["random_source"] == (
        "materialization_seed+decision_index.v1"
    )
    assert view["pinned_conditions"]["market_rule_profile_version"] == (
        "a-share-cash-equity.v1"
    )
    assert view["pinned_conditions"]["execution_policy_version"] == (
        "anchored-standard-execution.v2"
    )
    assert view["shared_market_nodes"]["identical_observed_timeline"] is True
    assert view["shared_market_nodes"]["observed_node_count"] == 3
    assert view["members"][0]["orders"]
    assert view["members"][1]["orders"] == []
    assert view["isolation"] == {
        "execution_order": "sequential",
        "verification_status": "verified",
        "fresh_subprocess_per_callback": True,
        "unique_run_ids": True,
        "unique_replica_ids": True,
        "private_state_by_run_id": [first.run_id, second.run_id],
        "isolated_surfaces": [
            "strategy_process",
            "strategy_globals",
            "strategy_cache",
            "orders",
            "fills",
            "account",
            "failure",
        ],
    }
    assert [item["strategy_id"] for item in view["equity_overlay"]] == [
        QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
        LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
    ]
    assert view["drawdown_overlay"][0]["points"] == [
        {"simulation_time": "2024-01-02T09:30:00", "drawdown": "0"},
        {"simulation_time": "2024-01-02T09:30:30", "drawdown": "0"},
        {
            "simulation_time": "2024-01-02T09:31:00",
            "drawdown": "0.001998001998001998001998001998",
        },
    ]


def test_campaign_contains_one_strategy_failure_and_still_runs_the_other_replica() -> None:
    specification = _campaign_specification()
    first = _snapshot(
        specification.strategy_runs[0],
        status="failed",
        equities=("100000",),
        failure_message="strategy callback failed",
    )
    second = _snapshot(specification.strategy_runs[1])
    engine = _RecordingEngine((first, second))

    campaign = BaselineCampaignRunner(engine).run(specification)
    view = campaign.to_dict()

    assert campaign.status == "incomplete"
    assert view["completeness"] == {
        "completed_count": 1,
        "total_count": 2,
        "label": "1/2 complete",
        "is_complete": False,
    }
    assert [call[0] for call in engine.calls] == [
        "start",
        "complete",
        "start",
        "complete",
    ]
    assert view["members"][0]["failure"]["message"] == "strategy callback failed"
    assert view["members"][1]["status"] == "completed"


def test_campaign_does_not_claim_isolation_without_member_host_audits() -> None:
    specification = _campaign_specification()
    first = replace(
        _snapshot(specification.strategy_runs[0]),
        ptrade_audit=None,
    )
    second = _snapshot(specification.strategy_runs[1])

    campaign = BaselineCampaignRunner(_RecordingEngine((first, second))).run(
        specification
    )
    isolation = campaign.to_dict()["isolation"]

    assert campaign.status == "incomplete"
    assert isolation["verification_status"] == "unverified"
    assert isolation["fresh_subprocess_per_callback"] is False
    assert isolation["isolated_surfaces"] == []


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("materialization_hash", "d" * 64, "materialization hash"),
        ("materialization_seed", 18, "controlled random source"),
        ("market_rule_profile_version", "other-profile.v1", "Market Rule Profile"),
        ("execution_policy_version", "other-policy.v1", "Execution Policy"),
        ("replica_id", "baseline-campaign-1-quentx", "replica ids"),
    ),
)
def test_campaign_rejects_non_comparable_or_reused_replica_inputs(
    field: str,
    value: object,
    message: str,
) -> None:
    specification = _campaign_specification()
    changed = replace(specification.strategy_runs[1], **{field: value})

    with pytest.raises(ValueError, match=message):
        BaselineCampaignSpecification(
            campaign_replica_id="baseline-campaign-invalid",
            strategy_runs=(specification.strategy_runs[0], changed),
        )


def test_campaign_requires_the_production_subprocess_host_for_global_isolation() -> None:
    specification = _campaign_specification()
    changed = replace(
        specification.strategy_runs[1],
        ptrade_host_adapter_version="ptrade-in-process-host.v1",
    )

    with pytest.raises(ValueError, match="subprocess isolation"):
        BaselineCampaignSpecification(
            campaign_replica_id="baseline-campaign-invalid-host",
            strategy_runs=(specification.strategy_runs[0], changed),
        )
