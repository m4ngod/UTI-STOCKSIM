from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from strategy_diagnostics import create_initial_transformation_catalog
from strategy_diagnostics.execution_conditions import (
    RequestedExecutionAssumptions,
    resolve_execution_conditions,
)
from strategy_diagnostics.formal_diagnostic_campaigns import (
    CampaignTransformation,
    DiagnosticCampaignCase,
    DiagnosticCampaignRunner,
    DiagnosticCampaignSnapshot,
    DiagnosticCampaignSpecification,
    SqlDiagnosticCampaignRepository,
)
from strategy_diagnostics.isolated_sensitivity_sets import (
    ISOLATED_SENSITIVITY_FAMILIES,
    IsolatedSensitivitySetSpecification,
    SensitivityCampaignCase,
    SensitivitySweepDefinition,
)
from strategy_diagnostics.persistence import initialize_diagnostic_persistence
from strategy_diagnostics.ptrade_host import PTRADE_SUBPROCESS_HOST_VERSION
from strategy_diagnostics.strategy_campaigns import (
    BaselineCampaignSnapshot,
    BaselineCampaignSpecification,
    CampaignMemberResult,
)
from strategy_diagnostics.strategy_runs import StrategyRunSpecification


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
        recipe_content_hash=f"recipe-hash-{family}-{level}",
        materialization_hash=f"path-{family}-{level}",
        historical_segment_id="segment-1",
        historical_segment_content_hash="segment-content-1",
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
        sensitivity_set_replica_id="isolated-layer-1",
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
    layer = (
        "baseline"
        if not transformations
        else "compound"
        if len(transformations) > 1
        else "isolated"
    )
    return DiagnosticCampaignCase(
        recipe_version_id=f"recipe-{layer}",
        recipe_content_hash=f"recipe-hash-{layer}",
        materialization_hash=f"path-{layer}",
        historical_segment_id="segment-1",
        historical_segment_content_hash="segment-content-1",
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


def test_complete_three_layer_selection_has_explicit_formal_comparisons() -> None:
    baseline = _campaign_case()
    compound = _campaign_case(
        _transformation("trend-regime", 1),
        _transformation("volatility", 2),
    )
    isolated = _isolated_specification()

    specification = DiagnosticCampaignSpecification(
        campaign_replica_id="formal-campaign-1",
        baseline_case=baseline,
        isolated_sensitivity_set=isolated,
        compound_cases=(compound,),
        initial_cash=Decimal("100000"),
        order_shares=1000,
    )

    assert specification.campaign_type == "formal_diagnostic_campaign"
    view = specification.to_dict()
    assert view["schema_version"] == "diagnostic-campaign.v1"
    assert view["layers"] == {
        "baseline": {"present": True, "case_count": 1},
        "isolated_sensitivity": {"present": True, "case_count": 12},
        "compound": {"present": True, "case_count": 1},
    }
    relationships = view["comparison_relationships"]
    assert len(relationships) == 13
    compound_relationship = relationships[-1]
    assert compound_relationship == {
        "kind": "compound-vs-baseline-and-isolated",
        "subject_case_id": compound.case_id,
        "control_case_ids": [
            baseline.case_id,
            *[
                case.case_id
                for case in isolated.ordered_cases
                if case.transformation_family in {"trend-regime", "volatility"}
            ],
        ],
    }


def test_compound_only_selection_is_a_non_attributive_quick_experiment() -> None:
    compound = _campaign_case(
        _transformation("trend-regime", 1),
        _transformation("volatility", 2),
    )

    specification = DiagnosticCampaignSpecification(
        campaign_replica_id="quick-experiment-1",
        baseline_case=None,
        isolated_sensitivity_set=None,
        compound_cases=(compound,),
        initial_cash=Decimal("100000"),
        order_shares=1000,
    )

    assert specification.campaign_type == "quick_experiment"
    assert specification.to_dict()["formal_attribution"] == {
        "eligible": False,
        "claim_status": "not_permitted",
        "missing_layers": ["baseline", "isolated_sensitivity"],
    }


@pytest.mark.parametrize(
    ("initial_cash", "order_shares", "message"),
    (
        (Decimal("200000"), 1000, "initial cash"),
        (Decimal("100000"), 2000, "order shares"),
    ),
)
def test_formal_campaign_rejects_isolated_control_mismatch(
    initial_cash: Decimal,
    order_shares: int,
    message: str,
) -> None:
    compound = _campaign_case(
        _transformation("trend-regime", 1),
        _transformation("volatility", 2),
    )

    with pytest.raises(ValueError, match=message):
        DiagnosticCampaignSpecification(
            campaign_replica_id="formal-control-mismatch",
            baseline_case=_campaign_case(),
            isolated_sensitivity_set=_isolated_specification(),
            compound_cases=(compound,),
            initial_cash=initial_cash,
            order_shares=order_shares,
        )


class _CampaignOutcome:
    def __init__(self, case_id: str, attempt_number: int) -> None:
        self.campaign_id = f"result-{case_id}-attempt-{attempt_number}"
        self.status = "completed"

    def to_dict(self) -> dict[str, object]:
        return {
            "campaign_id": self.campaign_id,
            "status": self.status,
            "members": [
                {"strategy_id": "quentx", "status": "completed"},
                {"strategy_id": "live-minute", "status": "completed"},
            ],
        }


class _RecordingCampaignExecutor:
    def __init__(self, fail_once_case_id: str | None = None) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self._fail_once_case_id = fail_once_case_id

    def __call__(
        self,
        specification: DiagnosticCampaignSpecification,
        layer: str,
        case: object,
        attempt_number: int,
        nodes_per_batch: int,
    ) -> _CampaignOutcome:
        case_id = str(getattr(case, "case_id"))
        assert specification.campaign_type == "formal_diagnostic_campaign"
        assert nodes_per_batch > 0
        self.calls.append((layer, case_id, attempt_number))
        if case_id == self._fail_once_case_id and attempt_number == 1:
            raise RuntimeError("fixture compound failure")
        return _CampaignOutcome(case_id, attempt_number)


def _failed_baseline_campaign(
    case: DiagnosticCampaignCase,
) -> BaselineCampaignSnapshot:
    resolved = resolve_execution_conditions(_REQUESTED_EXECUTION, {})

    def run_specification(
        *,
        strategy_id: str,
        replica_id: str,
    ) -> StrategyRunSpecification:
        return StrategyRunSpecification(
            recipe_version_id=case.recipe_version_id,
            recipe_content_hash=case.recipe_content_hash,
            materialization_hash=case.materialization_hash,
            source_snapshot_id=case.source_snapshot_id,
            materialization_seed=case.materialization_seed,
            transformation_catalog_version=(
                case.transformation_catalog_version
            ),
            transformation_implementation_versions=tuple(
                item.transformation_implementation_version
                for item in case.transformations
            ),
            market_rule_profile_version=case.market_rule_profile_version,
            execution_policy_version="anchored-standard-execution.v2",
            strategy_id=strategy_id,
            strategy_version=f"{strategy_id}.v1",
            decision_cadence_minutes=case.decision_cadence_minutes,
            initial_cash=Decimal("100000"),
            order_shares=1000,
            replica_id=replica_id,
            code_identity="strategy-diagnostics.v1",
            ptrade_manifest_hash=f"{strategy_id}-manifest",
            ptrade_host_adapter_version=PTRADE_SUBPROCESS_HOST_VERSION,
            commission_bps=resolved.effective.commission_bps,
            resolved_execution_conditions=resolved,
        )

    quentx = run_specification(
        strategy_id="quentx",
        replica_id="failed-campaign-quentx",
    )
    live_minute = run_specification(
        strategy_id="live-minute",
        replica_id="failed-campaign-live-minute",
    )
    specification = BaselineCampaignSpecification(
        campaign_replica_id="real-failed-baseline-campaign",
        strategy_runs=(quentx, live_minute),
    )
    return BaselineCampaignSnapshot(
        specification=specification,
        members=(
            CampaignMemberResult(
                specification=quentx,
                snapshot=None,
                failure_code="StrategyRuntimeError",
                failure_message="QuentX callback failed",
            ),
            CampaignMemberResult(
                specification=live_minute,
                snapshot=None,
                failure_code="TimeoutError",
                failure_message="Live-minute subprocess timed out",
            ),
        ),
    )


class _RealFailedCampaignExecutor:
    def __call__(
        self,
        specification: DiagnosticCampaignSpecification,
        layer: str,
        case: object,
        attempt_number: int,
        nodes_per_batch: int,
    ) -> BaselineCampaignSnapshot:
        assert layer == "compound"
        assert attempt_number == 1
        assert nodes_per_batch > 0
        assert specification.campaign_type == "quick_experiment"
        assert isinstance(case, DiagnosticCampaignCase)
        return _failed_baseline_campaign(case)


def test_runner_advances_all_layers_sequentially_and_supports_attribution() -> None:
    baseline = _campaign_case()
    compound = _campaign_case(
        _transformation("trend-regime", 1),
        _transformation("volatility", 2),
    )
    isolated = _isolated_specification()
    specification = DiagnosticCampaignSpecification(
        campaign_replica_id="formal-campaign-run-1",
        baseline_case=baseline,
        isolated_sensitivity_set=isolated,
        compound_cases=(compound,),
        initial_cash=Decimal("100000"),
        order_shares=1000,
    )
    executor = _RecordingCampaignExecutor()
    runner = DiagnosticCampaignRunner(executor)

    planned = runner.plan(specification)
    assert planned.to_dict()["layers"] == {
        "baseline": {
            "status": "planned",
            "completed_count": 0,
            "incomplete_count": 0,
            "pending_count": 1,
            "total_count": 1,
        },
        "isolated_sensitivity": {
            "status": "planned",
            "completed_count": 0,
            "incomplete_count": 0,
            "pending_count": 12,
            "total_count": 12,
        },
        "compound": {
            "status": "planned",
            "completed_count": 0,
            "incomplete_count": 0,
            "pending_count": 1,
            "total_count": 1,
        },
    }

    after_baseline = runner.advance(planned.campaign_id)
    assert executor.calls == [("baseline", baseline.case_id, 1)]
    assert after_baseline.to_dict()["layers"]["baseline"]["status"] == "completed"

    completed = runner.resume(planned.campaign_id)

    assert completed.status == "completed"
    assert [layer for layer, _, _ in executor.calls] == [
        "baseline",
        *(["isolated_sensitivity"] * 12),
        "compound",
    ]
    view = completed.to_dict()
    assert view["formal_attribution"] == {
        "eligible": True,
        "claim_status": "supported",
        "missing_layers": [],
    }
    assert view["compound_case_outcomes"] == [
        {
            "case_id": compound.case_id,
            "status": "completed",
            "attempt_number": 1,
            "campaign_id": f"result-{compound.case_id}-attempt-1",
            "members": [
                {"strategy_id": "quentx", "status": "completed"},
                {"strategy_id": "live-minute", "status": "completed"},
            ],
        }
    ]


def test_partial_failure_is_auditable_resumable_and_retryable() -> None:
    baseline = _campaign_case()
    compound = _campaign_case(
        _transformation("trend-regime", 1),
        _transformation("volatility", 2),
    )
    specification = DiagnosticCampaignSpecification(
        campaign_replica_id="formal-campaign-retry-1",
        baseline_case=baseline,
        isolated_sensitivity_set=_isolated_specification(),
        compound_cases=(compound,),
        initial_cash=Decimal("100000"),
        order_shares=1000,
    )
    executor = _RecordingCampaignExecutor(
        fail_once_case_id=compound.case_id
    )
    runner = DiagnosticCampaignRunner(executor)
    planned = runner.plan(specification)

    incomplete = runner.resume(planned.campaign_id)

    assert incomplete.status == "incomplete"
    assert incomplete.to_dict()["formal_attribution"]["claim_status"] == (
        "pending_completion"
    )
    assert incomplete.to_dict()["failures"] == [
        {
            "case_id": compound.case_id,
            "layer": "compound",
            "attempt_number": 1,
            "code": "RuntimeError",
            "message": "fixture compound failure",
        }
    ]

    completed = runner.retry_case(
        planned.campaign_id,
        compound.case_id,
    )

    assert completed.status == "completed"
    compound_progress = completed.to_dict()["cases"][-1]
    assert compound_progress["status"] == "completed"
    assert [
        attempt["attempt_number"]
        for attempt in compound_progress["attempts"]
    ] == [1, 2]
    assert completed.to_dict()["formal_attribution"]["claim_status"] == "supported"


def test_real_campaign_member_failures_remain_visible_and_identifiable() -> None:
    compound = _campaign_case(
        _transformation("trend-regime", 1),
        _transformation("volatility", 2),
    )
    specification = DiagnosticCampaignSpecification(
        campaign_replica_id="quick-real-failure-1",
        baseline_case=None,
        isolated_sensitivity_set=None,
        compound_cases=(compound,),
        initial_cash=Decimal("100000"),
        order_shares=1000,
    )
    runner = DiagnosticCampaignRunner(_RealFailedCampaignExecutor())

    incomplete = runner.resume(runner.plan(specification).campaign_id)

    assert incomplete.status == "incomplete"
    campaign = incomplete.cases[0].attempts[0].campaign
    assert isinstance(campaign, BaselineCampaignSnapshot)
    failures = incomplete.to_dict()["failures"]
    assert failures == [
        {
            "case_id": compound.case_id,
            "layer": "compound",
            "attempt_number": 1,
            "strategy_id": "quentx",
            "run_id": campaign.members[0].specification.run_id,
            "code": "StrategyRuntimeError",
            "message": "QuentX callback failed",
        },
        {
            "case_id": compound.case_id,
            "layer": "compound",
            "attempt_number": 1,
            "strategy_id": "live-minute",
            "run_id": campaign.members[1].specification.run_id,
            "code": "TimeoutError",
            "message": "Live-minute subprocess timed out",
        },
    ]
    restored = DiagnosticCampaignSnapshot.from_storage_dict(
        incomplete.to_storage_dict()
    )
    assert restored.to_dict()["failures"] == failures


def test_partial_campaign_resumes_after_repository_restart(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'formal-campaign.db'}")
    migration = initialize_diagnostic_persistence(engine)
    assert migration.current_revision == "0011_diagnostic_evidence"
    compound = _campaign_case(
        _transformation("trend-regime", 1),
        _transformation("volatility", 2),
    )
    specification = DiagnosticCampaignSpecification(
        campaign_replica_id="formal-campaign-restart-1",
        baseline_case=_campaign_case(),
        isolated_sensitivity_set=_isolated_specification(),
        compound_cases=(compound,),
        initial_cash=Decimal("100000"),
        order_shares=1000,
    )
    first = DiagnosticCampaignRunner(
        _RecordingCampaignExecutor(fail_once_case_id=compound.case_id),
        repository=SqlDiagnosticCampaignRepository(engine),
    )
    planned = first.plan(specification)
    incomplete = first.resume(planned.campaign_id)
    assert incomplete.status == "incomplete"

    with engine.connect() as connection:
        stored_json = connection.execute(
            text(
                "SELECT snapshot_json FROM diagnostic_campaigns "
                "WHERE campaign_id = :campaign_id"
            ),
            {"campaign_id": planned.campaign_id},
        ).scalar_one()
    stored = json.loads(stored_json)
    assert stored["schema_version"] == "diagnostic-campaign.v1"

    restarted = DiagnosticCampaignRunner(
        _RecordingCampaignExecutor(),
        repository=SqlDiagnosticCampaignRepository(engine),
    )
    restored = restarted.get(planned.campaign_id)
    assert restored.to_dict() == incomplete.to_dict()

    completed = restarted.retry_case(
        planned.campaign_id,
        compound.case_id,
    )

    assert completed.status == "completed"
    assert [
        attempt["attempt_number"]
        for attempt in completed.to_dict()["cases"][-1]["attempts"]
    ] == [1, 2]
