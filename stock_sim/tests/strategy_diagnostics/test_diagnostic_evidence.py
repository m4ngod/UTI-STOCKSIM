from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from strategy_diagnostics.diagnostic_evidence import (
    DiagnosticEvidenceBuilder,
    DiagnosticFindingExplanation,
    GuardrailThreshold,
    StrategyGuardrailProfile,
)
from strategy_diagnostics.diagnostic_evidence_storage import (
    InMemoryDiagnosticEvidenceArtifactStore,
    JsonDiagnosticEvidenceArtifactStore,
    SqlDiagnosticEvidenceRepository,
)
from strategy_diagnostics.execution import ExecutionFeeBreakdown
from strategy_diagnostics.execution_conditions import (
    RequestedExecutionAssumptions,
    resolve_execution_conditions,
)
from strategy_diagnostics.formal_diagnostic_campaigns import (
    CampaignTransformation,
    DiagnosticCampaignCase,
    DiagnosticCampaignRunner,
    DiagnosticCampaignSpecification,
)
from strategy_diagnostics.isolated_sensitivity_sets import (
    ISOLATED_SENSITIVITY_FAMILIES,
    IsolatedSensitivitySetSpecification,
    SensitivityCampaignCase,
    SensitivitySweepDefinition,
)
from strategy_diagnostics.market_paths import (
    InstrumentState,
    MarketPathNode,
    MaterializedMarketPath,
)
from strategy_diagnostics.persistence import initialize_diagnostic_persistence
from strategy_diagnostics.ptrade_host import (
    PTRADE_SUBPROCESS_HOST_VERSION,
    PTradeRunAudit,
)
from strategy_diagnostics.strategy_campaigns import (
    BaselineCampaignSnapshot,
    BaselineCampaignSpecification,
    CampaignMemberResult,
)
from strategy_diagnostics.strategy_runs import (
    EquityPoint,
    PortfolioPosition,
    PrivateFill,
    StrategyOrder,
    StrategyRunSnapshot,
    StrategyRunSpecification,
)
from strategy_diagnostics import create_initial_transformation_catalog


_TRANSFORMATION_IDS = {
    "trend-regime": "trend-regime.v1",
    "volatility": "volatility-scaling.v1",
    "shock-recovery": "shock-recovery.v1",
    "market-structure": "market-structure.v1",
    "liquidity": "liquidity-stress.v1",
    "execution-stress": "execution-stress.v1",
}
_REQUESTED_EXECUTION = RequestedExecutionAssumptions(
    commission_bps=Decimal("3"),
    slippage_bps=Decimal("5"),
    max_fill_fraction=Decimal("1"),
    latency_nodes=0,
    allow_partial_fills=True,
)
_START = datetime(2024, 1, 2, 9, 30)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _transformation(
    family: str,
    level: int,
) -> CampaignTransformation:
    transformation_id = _TRANSFORMATION_IDS[family]
    entry = create_initial_transformation_catalog().get_entry(transformation_id)
    return CampaignTransformation(
        transformation_id=transformation_id,
        transformation_family=family,
        transformation_implementation_version=entry.implementation_version,
        transformation_parameters=(("level", str(level)),),
    )


def _sensitivity_case(
    family: str,
    level: int,
) -> SensitivityCampaignCase:
    transformation = _transformation(family, level)
    return SensitivityCampaignCase(
        recipe_version_id=f"recipe-{family}-{level}",
        recipe_content_hash=_hash(f"recipe-{family}-{level}"),
        materialization_hash=_hash(f"path-{family}-{level}"),
        historical_segment_id="segment-1",
        historical_segment_content_hash=_hash("segment-content-1"),
        source_snapshot_id="snapshot-1",
        materialization_seed=17,
        expander_version="deterministic-30s-expander.v1",
        source_resolution="5m",
        runtime_resolution="30s",
        numeric_tolerance="0.000001",
        normalization_provenance="fixture-normalization.v1",
        transformation_catalog_version="scenario-transformation-catalog.v1",
        transformation_id=transformation.transformation_id,
        transformation_family=transformation.transformation_family,
        transformation_implementation_version=(
            transformation.transformation_implementation_version
        ),
        transformation_parameters=transformation.transformation_parameters,
        market_rule_profile_version="a-share-cash-equity.v1",
        decision_cadence_minutes=30,
        requested_execution_conditions=_REQUESTED_EXECUTION,
    )


def _isolated_specification() -> IsolatedSensitivitySetSpecification:
    return IsolatedSensitivitySetSpecification(
        sensitivity_set_replica_id="evidence-isolated-layer",
        sweeps=tuple(
            SensitivitySweepDefinition(
                transformation_family=family,
                transformation_id=_TRANSFORMATION_IDS[family],
                transformation_implementation_version=(
                    create_initial_transformation_catalog()
                    .get_entry(_TRANSFORMATION_IDS[family])
                    .implementation_version
                ),
                levels=(
                    _sensitivity_case(family, 1),
                    _sensitivity_case(family, 2),
                ),
            )
            for family in ISOLATED_SENSITIVITY_FAMILIES
        ),
        initial_cash=Decimal("100000"),
        order_shares=1000,
    )


def _campaign_case(
    *transformations: CampaignTransformation,
) -> DiagnosticCampaignCase:
    label = (
        "baseline"
        if not transformations
        else "-".join(
            f"{item.transformation_family}-{dict(item.transformation_parameters)['level']}"
            for item in transformations
        )
    )
    return DiagnosticCampaignCase(
        recipe_version_id=f"recipe-{label}",
        recipe_content_hash=_hash(f"recipe-{label}"),
        materialization_hash=_hash(f"path-{label}"),
        historical_segment_id="segment-1",
        historical_segment_content_hash=_hash("segment-content-1"),
        source_snapshot_id="snapshot-1",
        materialization_seed=17,
        expander_version="deterministic-30s-expander.v1",
        source_resolution="5m",
        runtime_resolution="30s",
        numeric_tolerance="0.000001",
        normalization_provenance="fixture-normalization.v1",
        transformation_catalog_version="scenario-transformation-catalog.v1",
        transformations=tuple(transformations),
        market_rule_profile_version="a-share-cash-equity.v1",
        decision_cadence_minutes=30,
        requested_execution_conditions=_REQUESTED_EXECUTION,
    )


def _strategy_run_specification(
    case: DiagnosticCampaignCase | SensitivityCampaignCase,
    *,
    strategy_id: str,
    strategy_version: str,
    replica_id: str,
) -> StrategyRunSpecification:
    transformations = (
        case.transformations
        if isinstance(case, DiagnosticCampaignCase)
        else (
            CampaignTransformation(
                transformation_id=case.transformation_id,
                transformation_family=case.transformation_family,
                transformation_implementation_version=(
                    case.transformation_implementation_version
                ),
                transformation_parameters=case.transformation_parameters,
            ),
        )
    )
    resolved = resolve_execution_conditions(_REQUESTED_EXECUTION, {})
    return StrategyRunSpecification(
        recipe_version_id=case.recipe_version_id,
        recipe_content_hash=case.recipe_content_hash,
        materialization_hash=case.materialization_hash,
        source_snapshot_id=case.source_snapshot_id,
        materialization_seed=case.materialization_seed,
        transformation_catalog_version=case.transformation_catalog_version,
        transformation_implementation_versions=tuple(
            item.transformation_implementation_version
            for item in transformations
        ),
        market_rule_profile_version=case.market_rule_profile_version,
        execution_policy_version="anchored-standard-execution.v2",
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        decision_cadence_minutes=case.decision_cadence_minutes,
        initial_cash=Decimal("100000"),
        order_shares=1000,
        replica_id=replica_id,
        code_identity="strategy-diagnostics.v1",
        ptrade_manifest_hash=_hash(f"manifest-{strategy_id}"),
        ptrade_host_adapter_version=PTRADE_SUBPROCESS_HOST_VERSION,
        commission_bps=resolved.effective.commission_bps,
        resolved_execution_conditions=resolved,
    )


def _ending_equity(
    case: DiagnosticCampaignCase | SensitivityCampaignCase,
    strategy_id: str,
) -> Decimal:
    if isinstance(case, SensitivityCampaignCase):
        level = int(dict(case.transformation_parameters)["level"])
        if case.transformation_family == "trend-regime":
            if strategy_id == "quentx":
                return Decimal("115000") if level == 1 else Decimal("90000")
            return Decimal("104000") if level == 1 else Decimal("101000")
        return Decimal("112000") - Decimal(level * 1000)
    if case.layer == "baseline":
        return (
            Decimal("121000")
            if strategy_id == "quentx"
            else Decimal("105000")
        )
    return (
        Decimal("80000")
        if strategy_id == "quentx"
        else Decimal("105000")
    )


def _strategy_snapshot(
    case: DiagnosticCampaignCase | SensitivityCampaignCase,
    specification: StrategyRunSpecification,
) -> StrategyRunSnapshot:
    ending = _ending_equity(case, specification.strategy_id)
    middle = (
        Decimal("110000")
        if ending >= Decimal("100000")
        else Decimal("95000")
    )
    equities = (Decimal("100000"), middle, ending)
    curve = tuple(
        EquityPoint(
            simulation_time=_START + timedelta(seconds=30 * index),
            cash=(equity if index < 2 else ending / Decimal("4")),
            positions_value=(
                Decimal("0")
                if index < 2
                else ending * Decimal("0.75")
            ),
            equity=equity,
        )
        for index, equity in enumerate(equities)
    )
    partial_order = StrategyOrder(
        order_id=f"{specification.run_id}:partial",
        instrument="sh.600000",
        shares=200,
        decision_time=_START,
        activation_time=_START + timedelta(seconds=30),
        status="partially_filled",
        accepted_shares=100,
        unfilled_shares=100,
        execution_price=Decimal("10"),
        reference_price=Decimal("9.9"),
        slippage_bps=Decimal("10.101010101"),
    )
    rejected_order = StrategyOrder(
        order_id=f"{specification.run_id}:rejected",
        instrument="sz.000001",
        shares=100,
        decision_time=_START,
        activation_time=_START + timedelta(seconds=30),
        status="rejected",
        accepted_shares=0,
        unfilled_shares=100,
        reason_code="cash.insufficient",
        reason_message="fixture rejection",
        rejection_reason="cash.insufficient",
    )
    fill = PrivateFill(
        fill_id=f"{partial_order.order_id}:fill",
        order_id=partial_order.order_id,
        instrument=partial_order.instrument,
        shares=100,
        price=Decimal("10"),
        reference_price=Decimal("9.9"),
        slippage_bps=Decimal("10.101010101"),
        gross_value=Decimal("1000"),
        simulation_time=_START + timedelta(seconds=30),
        fees=ExecutionFeeBreakdown(
            commission=Decimal("5"),
            transfer_fee=Decimal("1"),
            stamp_duty=Decimal("0"),
        ),
        cash_change=Decimal("-1006"),
        execution_erosion=Decimal("16"),
    )
    positions = (
        PortfolioPosition(
            instrument="sh.600000",
            shares=100,
            sellable_shares=100,
            average_cost=Decimal("10"),
            market_price=ending / Decimal("200"),
            market_value=ending / Decimal("2"),
            unrealized_pnl=Decimal("0"),
        ),
        PortfolioPosition(
            instrument="sz.000001",
            shares=100,
            sellable_shares=100,
            average_cost=Decimal("10"),
            market_price=ending / Decimal("400"),
            market_value=ending / Decimal("4"),
            unrealized_pnl=Decimal("0"),
        ),
    )
    resolved = specification.resolved_execution_conditions
    assert resolved is not None
    return StrategyRunSnapshot(
        run_id=specification.run_id,
        status="completed",
        specification=specification,
        current_simulation_time=curve[-1].simulation_time,
        processed_node_count=len(curve),
        total_node_count=len(curve),
        decision_times=(_START,),
        orders=(partial_order, rejected_order),
        fills=(fill,),
        cash=ending / Decimal("4"),
        positions=positions,
        equity_curve=curve,
        ptrade_audit=PTradeRunAudit(
            surface_version=specification.ptrade_surface_version,
            manifest_hash=specification.ptrade_manifest_hash,
            execution_resolution=resolved,
            strategy_id=specification.strategy_id,
            strategy_version=specification.strategy_version,
            host_adapter_versions=(PTRADE_SUBPROCESS_HOST_VERSION,),
        ),
        failure_code=None,
        failure_message=None,
        run_artifact_hash=_hash(specification.run_id),
    )


def _materialized_path(
    case: DiagnosticCampaignCase | SensitivityCampaignCase,
) -> MaterializedMarketPath:
    nodes = tuple(
        MarketPathNode(
            instrument=instrument,
            simulation_time=simulation_time,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=1000,
            amount=price * Decimal("1000"),
            reconstructed=True,
        )
        for instrument, prices in (
            ("sh.600000", (Decimal("10"), Decimal("11"))),
            ("sz.000001", (Decimal("20"), Decimal("22"))),
        )
        for simulation_time, price in zip(
            (_START, _START + timedelta(seconds=30)),
            prices,
            strict=True,
        )
    )
    return MaterializedMarketPath(
        artifact_hash=case.materialization_hash,
        segment_id=case.historical_segment_id,
        segment_content_hash=case.historical_segment_content_hash,
        source_snapshot_id=case.source_snapshot_id,
        seed=case.materialization_seed,
        expander_version=case.expander_version,
        source_resolution=case.source_resolution,
        runtime_resolution=case.runtime_resolution,
        reconstructed=True,
        numeric_tolerance=case.numeric_tolerance,
        normalization_provenance=case.normalization_provenance,
        market_rule_profile_version=case.market_rule_profile_version,
        transformation_catalog_version=case.transformation_catalog_version,
        applied_transformations=(),
        nodes=nodes,
        instrument_states=(
            InstrumentState(
                instrument="sh.600000",
                effective_at=_START,
                eligible=True,
                trading_status="trading",
                is_st=False,
                industry="banking",
                decision_adjustment_factor=Decimal("1"),
                decision_adjustment_provenance="fixture-adjustment.v1",
            ),
            InstrumentState(
                instrument="sz.000001",
                effective_at=_START,
                eligible=True,
                trading_status="trading",
                is_st=False,
                industry="technology",
                decision_adjustment_factor=Decimal("1"),
                decision_adjustment_provenance="fixture-adjustment.v1",
            ),
            InstrumentState(
                instrument="sz.000001",
                effective_at=_START + timedelta(days=1),
                eligible=True,
                trading_status="trading",
                is_st=False,
                industry="banking",
                decision_adjustment_factor=Decimal("1"),
                decision_adjustment_provenance="future-fixture-adjustment.v1",
            ),
        ),
    )


class _CompletedCampaignFixture:
    def __init__(self) -> None:
        self.paths: dict[str, MaterializedMarketPath] = {}

    def __call__(
        self,
        specification: DiagnosticCampaignSpecification,
        layer: str,
        case: DiagnosticCampaignCase | SensitivityCampaignCase,
        attempt_number: int,
        nodes_per_batch: int,
    ) -> BaselineCampaignSnapshot:
        assert specification.campaign_type == "formal_diagnostic_campaign"
        assert attempt_number == 1
        assert nodes_per_batch > 0
        self.paths[case.materialization_hash] = _materialized_path(case)
        quentx = _strategy_run_specification(
            case,
            strategy_id="quentx",
            strategy_version="quentx.v1",
            replica_id=f"{case.case_id}:quentx",
        )
        live_minute = _strategy_run_specification(
            case,
            strategy_id="live-minute",
            strategy_version="live-minute.v1",
            replica_id=f"{case.case_id}:live-minute",
        )
        campaign_specification = BaselineCampaignSpecification(
            campaign_replica_id=(
                f"{specification.campaign_replica_id}:{layer}:"
                f"{case.case_id}:attempt-1"
            ),
            strategy_runs=(quentx, live_minute),
        )
        return BaselineCampaignSnapshot(
            specification=campaign_specification,
            members=(
                CampaignMemberResult(
                    specification=quentx,
                    snapshot=_strategy_snapshot(case, quentx),
                ),
                CampaignMemberResult(
                    specification=live_minute,
                    snapshot=_strategy_snapshot(case, live_minute),
                ),
            ),
        )


def _formal_campaign(
    isolated_specification: IsolatedSensitivitySetSpecification | None = None,
) -> tuple[
    object,
    _CompletedCampaignFixture,
]:
    compound = _campaign_case(
        _transformation("trend-regime", 2),
        _transformation("volatility", 2),
    )
    specification = DiagnosticCampaignSpecification(
        campaign_replica_id="formal-evidence-campaign",
        baseline_case=_campaign_case(),
        isolated_sensitivity_set=(
            isolated_specification or _isolated_specification()
        ),
        compound_cases=(compound,),
        initial_cash=Decimal("100000"),
        order_shares=1000,
    )
    executor = _CompletedCampaignFixture()
    runner = DiagnosticCampaignRunner(executor)
    completed = runner.resume(runner.plan(specification).campaign_id)
    assert completed.status == "completed"
    return completed, executor


def _profiles() -> tuple[StrategyGuardrailProfile, ...]:
    return (
        StrategyGuardrailProfile(
            strategy_id="quentx",
            strategy_version="quentx.v1",
            profile_version="balanced-diagnostics.v1",
            thresholds=(
                GuardrailThreshold(
                    metric_name="total_return",
                    operator="less_than",
                    value=Decimal("-0.05"),
                ),
                GuardrailThreshold(
                    metric_name="maximum_drawdown",
                    operator="greater_than",
                    value=Decimal("0.20"),
                ),
                GuardrailThreshold(
                    metric_name="execution_erosion_bps",
                    operator="greater_than",
                    value=Decimal("50"),
                ),
            ),
        ),
        StrategyGuardrailProfile(
            strategy_id="live-minute",
            strategy_version="live-minute.v1",
            profile_version="capital-preservation.v1",
            thresholds=(
                GuardrailThreshold(
                    metric_name="total_return",
                    operator="less_than",
                    value=Decimal("-0.03"),
                ),
                GuardrailThreshold(
                    metric_name="maximum_drawdown",
                    operator="greater_than",
                    value=Decimal("0.15"),
                ),
            ),
        ),
    )


def _builder(
    artifact_store: InMemoryDiagnosticEvidenceArtifactStore | None = None,
) -> tuple[DiagnosticEvidenceBuilder, object]:
    campaign, executor = _formal_campaign()
    builder = DiagnosticEvidenceBuilder(
        campaign_loader=lambda campaign_id: (
            campaign
            if campaign_id == campaign.campaign_id
            else (_ for _ in ()).throw(KeyError(campaign_id))
        ),
        path_loader=lambda artifact_hash: executor.paths[artifact_hash],
        artifact_store=artifact_store
        or InMemoryDiagnosticEvidenceArtifactStore(),
    )
    return builder, campaign


def _metric_map(package: object, *, case_id: str, strategy_id: str) -> dict[str, str]:
    view = package.to_dict()
    return {
        str(metric["name"]): str(metric["value"])
        for metric in view["metrics"]
        if metric["case_id"] == case_id
        and metric["strategy_id"] == strategy_id
    }


def _assert_forbidden_keys_absent(value: object) -> None:
    if isinstance(value, dict):
        assert not {
            "score",
            "composite_score",
            "universal_score",
            "ranking",
            "rank",
        }.intersection(value)
        for child in value.values():
            _assert_forbidden_keys_absent(child)
    elif isinstance(value, list):
        for child in value:
            _assert_forbidden_keys_absent(child)


def test_builder_seals_hand_calculable_multidimensional_evidence_without_score() -> None:
    artifact_store = InMemoryDiagnosticEvidenceArtifactStore()
    builder, campaign = _builder(artifact_store)

    package = builder.build(campaign.campaign_id, _profiles())

    view = package.to_dict()
    assert view["schema_version"] == "diagnostic-evidence.v1"
    assert view["status"] == "sealed"
    assert len(str(view["artifact_hash"])) == 64
    assert len(str(view["measurement_artifact_hash"])) == 64
    assert view["campaign_id"] == campaign.campaign_id
    assert view["campaign_type"] == "formal_diagnostic_campaign"
    assert view["evidence_families"] == [
        "return_and_risk",
        "trading_behavior",
        "execution_erosion",
        "environmental_sensitivity",
    ]
    baseline_case_id = campaign.specification.baseline_case.case_id
    metrics = _metric_map(
        package,
        case_id=baseline_case_id,
        strategy_id="quentx",
    )
    assert metrics["total_return"] == "0.21"
    assert metrics["net_return"] == "0.21"
    assert metrics["gross_return_before_execution_erosion"] == "0.21016"
    assert metrics["benchmark_return"] == "0.1"
    assert metrics["benchmark_relative_return"] == "0.11"
    assert metrics["maximum_drawdown"] == "0"
    assert metrics["maximum_recovery_duration_minutes"] == "0"
    assert metrics["return_volatility"] == "0"
    assert metrics["instrument_concentration"] == "0.6666666666666666666666666667"
    assert metrics["industry_concentration"] == "0.6666666666666666666666666667"
    assert metrics["trade_count"] == "1"
    assert metrics["average_holding_duration_minutes"] == "0.5"
    assert metrics["fill_count"] == "1"
    assert metrics["partial_fill_count"] == "1"
    assert metrics["rejection_count"] == "1"
    assert metrics["total_fees"] == "6"
    assert metrics["execution_erosion"] == "16"
    assert metrics["fill_rate"] == "0.3333333333333333333333333333"
    assert artifact_store.get(str(view["artifact_hash"])) == package.sealed_payload()
    assert builder.build(campaign.campaign_id, _profiles()).artifact_hash == (
        package.artifact_hash
    )
    assert builder.build(
        campaign.campaign_id,
        tuple(reversed(_profiles())),
    ).artifact_hash == package.artifact_hash
    reversed_threshold_profiles = tuple(
        StrategyGuardrailProfile(
            strategy_id=profile.strategy_id,
            strategy_version=profile.strategy_version,
            profile_version=profile.profile_version,
            thresholds=tuple(reversed(profile.thresholds)),
        )
        for profile in _profiles()
    )
    assert [
        profile.profile_id for profile in reversed_threshold_profiles
    ] == [profile.profile_id for profile in _profiles()]
    assert builder.build(
        campaign.campaign_id,
        reversed_threshold_profiles,
    ).artifact_hash == package.artifact_hash
    _assert_forbidden_keys_absent(view)


def test_guardrail_breakpoint_and_findings_cite_the_sealed_chain() -> None:
    builder, campaign = _builder()

    package = builder.build(campaign.campaign_id, _profiles())
    view = package.to_dict()

    breakpoint = next(
        item
        for item in view["sensitivity_breakpoints"]
        if item["strategy_id"] == "quentx"
        and item["transformation_family"] == "trend-regime"
        and item["metric_name"] == "total_return"
    )
    assert breakpoint["kind"] == "guardrail_crossing"
    assert breakpoint["bounded_interval"] == {
        "lower_case_id": (
            campaign.specification.isolated_sensitivity_set.sweeps[0]
            .levels[0]
            .case_id
        ),
        "lower_parameters": {"level": "1"},
        "upper_case_id": (
            campaign.specification.isolated_sensitivity_set.sweeps[0]
            .levels[1]
            .case_id
        ),
        "upper_parameters": {"level": "2"},
    }
    assert breakpoint["threshold"]["value"] == "-0.05"
    assert breakpoint["metric_ids"]
    assert breakpoint["run_ids"]
    assert breakpoint["comparison_ids"]
    assert breakpoint["guardrail_profile_id"]
    assert breakpoint["measurement_artifact_hash"] == view[
        "measurement_artifact_hash"
    ]

    assert view["diagnostic_findings"]
    assert {
        finding["kind"] for finding in view["diagnostic_findings"]
    } == {"profit_source", "weakness", "robustness"}
    for finding in view["diagnostic_findings"]:
        assert finding["kind"] in {"profit_source", "weakness", "robustness"}
        assert finding["strategy_id"]
        assert finding["strategy_version"]
        assert finding["case_ids"]
        assert finding["run_ids"]
        assert finding["comparison_ids"]
        assert finding["metric_ids"]
        assert finding["guardrail_profile_id"]
        assert finding["threshold_ids"]
        assert finding["reproduction_manifest_ids"]
        assert finding["measurement_artifact_hash"] == view[
            "measurement_artifact_hash"
        ]


def test_cross_strategy_comparisons_and_findings_trace_both_runs() -> None:
    builder, campaign = _builder()

    view = builder.build(campaign.campaign_id, _profiles()).to_dict()

    baseline_case_id = campaign.specification.baseline_case.case_id
    comparison = next(
        item
        for item in view["comparisons"]
        if item["kind"] == "cross-strategy"
        and item["case_id"] == baseline_case_id
        and item["metric_name"] == "total_return"
    )
    assert comparison["subject_strategy_id"] == "live-minute"
    assert comparison["control_strategy_id"] == "quentx"
    assert comparison["subject_case_id"] == baseline_case_id
    assert comparison["control_case_id"] == baseline_case_id
    assert comparison["delta"] == "-0.16"
    assert comparison["subject_run_id"] != comparison["control_run_id"]
    assert comparison["subject_run_artifact_hash"]
    assert comparison["control_run_artifact_hash"]
    assert comparison["subject_reproduction_manifest_id"]
    assert comparison["control_reproduction_manifest_id"]
    cross_strategy_comparison_ids = {
        item["comparison_id"]
        for item in view["comparisons"]
        if item["kind"] == "cross-strategy"
    }
    assert any(
        cross_strategy_comparison_ids.intersection(
            finding["comparison_ids"]
        )
        and "cross-strategy" in finding["statement"]
        for finding in view["diagnostic_findings"]
    )


def test_cross_strategy_relative_return_does_not_mask_guardrail_breaches() -> None:
    builder, campaign = _builder()
    unsafe_profiles = tuple(
        StrategyGuardrailProfile(
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            profile_version=f"{strategy_id}-unsafe-cross-check.v1",
            thresholds=(
                GuardrailThreshold(
                    metric_name="total_return",
                    operator="less_than",
                    value=Decimal("0.50"),
                ),
            ),
        )
        for strategy_id, strategy_version in (
            ("quentx", "quentx.v1"),
            ("live-minute", "live-minute.v1"),
        )
    )

    view = builder.build(campaign.campaign_id, unsafe_profiles).to_dict()

    assert any(
        comparison["kind"] == "cross-strategy"
        for comparison in view["comparisons"]
    )
    assert not any(
        "cross-strategy" in finding["statement"]
        and finding["kind"] == "robustness"
        for finding in view["diagnostic_findings"]
    )


def test_sensitivity_curve_and_package_identity_ignore_input_level_order() -> None:
    canonical = _isolated_specification()
    reversed_input = IsolatedSensitivitySetSpecification(
        sensitivity_set_replica_id=canonical.sensitivity_set_replica_id,
        sweeps=tuple(
            SensitivitySweepDefinition(
                transformation_family=sweep.transformation_family,
                transformation_id=sweep.transformation_id,
                transformation_implementation_version=(
                    sweep.transformation_implementation_version
                ),
                levels=tuple(reversed(sweep.levels)),
            )
            for sweep in reversed(canonical.sweeps)
        ),
        initial_cash=canonical.initial_cash,
        order_shares=canonical.order_shares,
    )
    canonical_campaign, canonical_executor = _formal_campaign(canonical)
    reversed_campaign, reversed_executor = _formal_campaign(reversed_input)
    canonical_builder = DiagnosticEvidenceBuilder(
        campaign_loader=lambda _: canonical_campaign,
        path_loader=lambda artifact_hash: canonical_executor.paths[
            artifact_hash
        ],
        artifact_store=InMemoryDiagnosticEvidenceArtifactStore(),
    )
    reversed_builder = DiagnosticEvidenceBuilder(
        campaign_loader=lambda _: reversed_campaign,
        path_loader=lambda artifact_hash: reversed_executor.paths[
            artifact_hash
        ],
        artifact_store=InMemoryDiagnosticEvidenceArtifactStore(),
    )

    canonical_package = canonical_builder.build(
        canonical_campaign.campaign_id,
        _profiles(),
    )
    reversed_package = reversed_builder.build(
        reversed_campaign.campaign_id,
        _profiles(),
    )

    assert reversed_campaign.campaign_id == canonical_campaign.campaign_id
    assert reversed_package.artifact_hash == canonical_package.artifact_hash
    assert (
        reversed_package.to_dict()["sensitivity_curves"]
        == canonical_package.to_dict()["sensitivity_curves"]
    )


def test_numeric_sweep_axis_orders_breakpoint_bounds_by_decimal_value() -> None:
    isolated = _isolated_specification()
    execution_sweep = next(
        sweep
        for sweep in isolated.sweeps
        if sweep.transformation_family == "execution-stress"
    )
    numeric_execution_sweep = SensitivitySweepDefinition(
        transformation_family=execution_sweep.transformation_family,
        transformation_id=execution_sweep.transformation_id,
        transformation_implementation_version=(
            execution_sweep.transformation_implementation_version
        ),
        levels=(
            _sensitivity_case("execution-stress", 100),
            _sensitivity_case("execution-stress", 25),
        ),
    )
    numeric_isolated = IsolatedSensitivitySetSpecification(
        sensitivity_set_replica_id=isolated.sensitivity_set_replica_id,
        sweeps=tuple(
            numeric_execution_sweep
            if sweep.transformation_family == "execution-stress"
            else sweep
            for sweep in isolated.sweeps
        ),
        initial_cash=isolated.initial_cash,
        order_shares=isolated.order_shares,
    )
    campaign, executor = _formal_campaign(numeric_isolated)
    builder = DiagnosticEvidenceBuilder(
        campaign_loader=lambda _: campaign,
        path_loader=lambda artifact_hash: executor.paths[artifact_hash],
        artifact_store=InMemoryDiagnosticEvidenceArtifactStore(),
    )
    profiles = tuple(
        StrategyGuardrailProfile(
            strategy_id=profile.strategy_id,
            strategy_version=profile.strategy_version,
            profile_version=f"{profile.profile_version}-numeric-axis",
            thresholds=(
                GuardrailThreshold(
                    metric_name="total_return",
                    operator="less_than",
                    value=Decimal("-0.50"),
                ),
            ),
        )
        for profile in _profiles()
    )

    view = builder.build(campaign.campaign_id, profiles).to_dict()

    breakpoint = next(
        item
        for item in view["sensitivity_breakpoints"]
        if item["strategy_id"] == "quentx"
        and item["transformation_family"] == "execution-stress"
        and item["metric_name"] == "total_return"
    )
    assert breakpoint["sweep_axis"] == {
        "parameter_name": "level",
        "value_type": "decimal",
        "order": "ascending",
    }
    assert breakpoint["bounded_interval"]["lower_parameters"] == {
        "level": "25"
    }
    assert breakpoint["bounded_interval"]["upper_parameters"] == {
        "level": "100"
    }


def test_multi_parameter_sweep_reports_observed_level_not_false_bounds() -> None:
    isolated = _isolated_specification()
    trend_sweep = next(
        sweep
        for sweep in isolated.sweeps
        if sweep.transformation_family == "trend-regime"
    )
    multi_parameter_trend = SensitivitySweepDefinition(
        transformation_family=trend_sweep.transformation_family,
        transformation_id=trend_sweep.transformation_id,
        transformation_implementation_version=(
            trend_sweep.transformation_implementation_version
        ),
        levels=(
            replace(
                trend_sweep.levels[0],
                transformation_parameters=(
                    ("level", "1"),
                    ("phase", "early"),
                ),
            ),
            replace(
                trend_sweep.levels[1],
                transformation_parameters=(
                    ("level", "2"),
                    ("phase", "late"),
                ),
            ),
        ),
    )
    multi_parameter_isolated = IsolatedSensitivitySetSpecification(
        sensitivity_set_replica_id=isolated.sensitivity_set_replica_id,
        sweeps=tuple(
            multi_parameter_trend
            if sweep.transformation_family == "trend-regime"
            else sweep
            for sweep in isolated.sweeps
        ),
        initial_cash=isolated.initial_cash,
        order_shares=isolated.order_shares,
    )
    campaign, executor = _formal_campaign(multi_parameter_isolated)
    builder = DiagnosticEvidenceBuilder(
        campaign_loader=lambda _: campaign,
        path_loader=lambda artifact_hash: executor.paths[artifact_hash],
        artifact_store=InMemoryDiagnosticEvidenceArtifactStore(),
    )

    view = builder.build(campaign.campaign_id, _profiles()).to_dict()

    breakpoint = next(
        item
        for item in view["sensitivity_breakpoints"]
        if item["strategy_id"] == "quentx"
        and item["transformation_family"] == "trend-regime"
        and item["metric_name"] == "total_return"
    )
    assert breakpoint["sweep_axis"] is None
    assert breakpoint["bounded_interval"] is None
    assert breakpoint["observed_level"]["parameters"] == {
        "level": "2",
        "phase": "late",
    }


def test_builder_rejects_quick_and_incomplete_campaigns() -> None:
    compound = _campaign_case(
        _transformation("trend-regime", 2),
        _transformation("volatility", 2),
    )
    quick_specification = DiagnosticCampaignSpecification(
        campaign_replica_id="quick-evidence-rejected",
        baseline_case=None,
        isolated_sensitivity_set=None,
        compound_cases=(compound,),
        initial_cash=Decimal("100000"),
        order_shares=1000,
    )
    quick_executor = _CompletedCampaignFixture()
    quick_runner = DiagnosticCampaignRunner(quick_executor)
    quick = quick_runner.resume(quick_runner.plan(quick_specification).campaign_id)
    formal, formal_executor = _formal_campaign()
    incomplete = DiagnosticCampaignRunner(
        formal_executor
    ).plan(formal.specification)
    campaigns = {
        quick.campaign_id: quick,
        incomplete.campaign_id: incomplete,
    }
    builder = DiagnosticEvidenceBuilder(
        campaign_loader=lambda campaign_id: campaigns[campaign_id],
        path_loader=lambda artifact_hash: quick_executor.paths.get(
            artifact_hash,
            formal_executor.paths[artifact_hash],
        ),
        artifact_store=InMemoryDiagnosticEvidenceArtifactStore(),
    )

    with pytest.raises(ValueError, match="Formal Diagnostic Campaign"):
        builder.build(quick.campaign_id, _profiles())
    with pytest.raises(ValueError, match="completed"):
        builder.build(incomplete.campaign_id, _profiles())


class _RecordingExplanationProvider:
    def __init__(self, *, unknown_reference: bool = False) -> None:
        self.unknown_reference = unknown_reference
        self.received_finding_ids: tuple[str, ...] = ()

    def explain(
        self,
        request: object,
    ) -> tuple[DiagnosticFindingExplanation, ...]:
        findings = getattr(request, "findings")
        self.received_finding_ids = tuple(
            str(item["finding_id"]) for item in findings
        )
        finding_id = (
            "unknown-finding"
            if self.unknown_reference
            else self.received_finding_ids[0]
        )
        return (
            DiagnosticFindingExplanation(
                finding_id=finding_id,
                text="Plain-language explanation of the sealed finding.",
            ),
        )


def test_optional_explanation_can_only_reference_sealed_findings() -> None:
    builder, campaign = _builder()
    package = builder.build(campaign.campaign_id, _profiles())
    provider = _RecordingExplanationProvider()

    bundle = builder.explain(package.evidence_package_id, provider)

    assert provider.received_finding_ids
    assert bundle.evidence_package_id == package.evidence_package_id
    assert bundle.evidence_artifact_hash == package.artifact_hash
    assert bundle.explanations[0].finding_id in provider.received_finding_ids
    assert builder.get(package.evidence_package_id).to_dict() == package.to_dict()

    with pytest.raises(ValueError, match="sealed Diagnostic Finding"):
        builder.explain(
            package.evidence_package_id,
            _RecordingExplanationProvider(unknown_reference=True),
        )


def test_sql_index_and_json_artifacts_restore_a_sealed_package(
    tmp_path: Path,
) -> None:
    campaign, executor = _formal_campaign()
    engine = create_engine(f"sqlite:///{tmp_path / 'evidence.db'}")
    report = initialize_diagnostic_persistence(engine)
    assert (
        report.current_revision
        == "0017_diagnostic_lifecycle_targets"
    )
    artifacts = JsonDiagnosticEvidenceArtifactStore(
        tmp_path / "evidence-artifacts"
    )
    first = DiagnosticEvidenceBuilder(
        campaign_loader=lambda campaign_id: campaign,
        path_loader=lambda artifact_hash: executor.paths[artifact_hash],
        artifact_store=artifacts,
        repository=SqlDiagnosticEvidenceRepository(engine, artifacts),
    )
    package = first.build(campaign.campaign_id, _profiles())

    restarted_repository = SqlDiagnosticEvidenceRepository(
        engine,
        artifacts,
    )
    restarted = DiagnosticEvidenceBuilder(
        campaign_loader=lambda campaign_id: campaign,
        path_loader=lambda artifact_hash: executor.paths[artifact_hash],
        artifact_store=artifacts,
        repository=restarted_repository,
    )

    assert restarted.get(package.evidence_package_id).to_dict() == package.to_dict()
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_evidence_packages "
                "SET measurement_artifact_hash = :hash "
                "WHERE evidence_package_id = :evidence_package_id"
            ),
            {
                "hash": "c" * 64,
                "evidence_package_id": package.evidence_package_id,
            },
        )
    with pytest.raises(ValueError, match="index"):
        restarted.get(package.evidence_package_id)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_evidence_packages "
                "SET measurement_artifact_hash = :hash "
                "WHERE evidence_package_id = :evidence_package_id"
            ),
            {
                "hash": package.to_dict()["measurement_artifact_hash"],
                "evidence_package_id": package.evidence_package_id,
            },
        )
    measurement_hash = str(
        package.to_dict()["measurement_artifact_hash"]
    )
    measurement_payload = artifacts.get(measurement_hash)
    measurement_path = (
        tmp_path
        / "evidence-artifacts"
        / f"{measurement_hash}.json"
    )
    measurement_path.unlink()
    with pytest.raises(
        KeyError,
        match="Unknown Diagnostic Evidence artifact",
    ):
        restarted_repository.get(package.evidence_package_id)
    assert artifacts.put(measurement_payload) == measurement_hash
    artifact_path = (
        tmp_path
        / "evidence-artifacts"
        / f"{package.artifact_hash}.json"
    )
    artifact_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="hash verification"):
        artifacts.get(package.artifact_hash)


def test_sql_repository_rejects_missing_artifacts_before_write_or_idempotency(
    tmp_path: Path,
) -> None:
    campaign, executor = _formal_campaign()
    artifacts = JsonDiagnosticEvidenceArtifactStore(
        tmp_path / "evidence-artifacts"
    )
    package = DiagnosticEvidenceBuilder(
        campaign_loader=lambda _: campaign,
        path_loader=lambda artifact_hash: executor.paths[artifact_hash],
        artifact_store=artifacts,
    ).build(campaign.campaign_id, _profiles())
    engine = create_engine(f"sqlite:///{tmp_path / 'evidence.db'}")
    initialize_diagnostic_persistence(engine)
    repository = SqlDiagnosticEvidenceRepository(engine, artifacts)
    measurement_hash = str(
        package.to_dict()["measurement_artifact_hash"]
    )
    measurement_payload = artifacts.get(measurement_hash)
    measurement_path = (
        tmp_path
        / "evidence-artifacts"
        / f"{measurement_hash}.json"
    )
    measurement_path.unlink()

    with pytest.raises(
        KeyError,
        match="Unknown Diagnostic Evidence artifact",
    ):
        repository.add(package)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_evidence_packages")
        ).scalar_one() == 0

    assert artifacts.put(measurement_payload) == measurement_hash
    repository.add(package)
    measurement_path.unlink()

    with pytest.raises(
        KeyError,
        match="Unknown Diagnostic Evidence artifact",
    ):
        repository.add(package)
