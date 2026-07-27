from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from strategy_diagnostics.execution_conditions import RequestedExecutionAssumptions
from strategy_diagnostics import create_initial_transformation_catalog
from strategy_diagnostics.execution_conditions import resolve_execution_conditions
from strategy_diagnostics.isolated_sensitivity_sets import (
    ISOLATED_SENSITIVITY_FAMILIES,
    IsolatedSensitivitySetRunner,
    IsolatedSensitivitySetSnapshot,
    IsolatedSensitivitySetSpecification,
    SensitivityCampaignCase,
    SensitivitySweepDefinition,
    SqlIsolatedSensitivitySetRepository,
)
from strategy_diagnostics.persistence import initialize_diagnostic_persistence
from strategy_diagnostics.ptrade_host import (
    LIVE_MINUTE_SCENARIO_NATIVE_MANIFEST,
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
    LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
    PTRADE_SUBPROCESS_HOST_VERSION,
    QUENTX_SCENARIO_NATIVE_MANIFEST,
    QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
    QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
)
from strategy_diagnostics.strategy_campaigns import BaselineCampaignSpecification
from strategy_diagnostics.strategy_runs import (
    BASELINE_EXECUTION_POLICY_VERSION,
    StrategyRunSpecification,
)


def _case(
    family: str,
    level: int,
    *,
    seed: int = 17,
    source_snapshot_id: str = "source-snapshot-1",
) -> SensitivityCampaignCase:
    transformation_id = {
        "trend-regime": "trend-regime.v1",
        "volatility": "volatility-scaling.v1",
        "shock-recovery": "shock-recovery.v1",
        "market-structure": "market-structure.v1",
        "liquidity": "liquidity-stress.v1",
        "execution-stress": "execution-stress.v1",
    }[family]
    catalog_entry = create_initial_transformation_catalog().get_entry(
        transformation_id
    )
    assert catalog_entry.family == family
    parameters_by_family: dict[str, tuple[tuple[str, str], ...]] = {
        "trend-regime": (
            ("direction", "bullish" if level == 1 else "bearish"),
            ("strength", "0.25" if level == 1 else "0.75"),
        ),
        "volatility": (("multiplier", "0.75" if level == 1 else "1.5"),),
        "shock-recovery": (
            ("direction", "bearish"),
            ("gap_fraction", "0.01" if level == 1 else "0.02"),
            ("persistence_duration_bars", "1"),
            ("recovery_duration_bars", "2"),
            ("shock_duration_bars", "2"),
            ("shock_fraction", "0.03" if level == 1 else "0.05"),
        ),
        "market-structure": (
            ("breadth_target", "0.3" if level == 1 else "0.7"),
            ("dispersion_fraction", "0.03" if level == 1 else "0.06"),
            ("sector_concentration", "0.3" if level == 1 else "0.8"),
        ),
        "liquidity": (
            ("cross_sectional_concentration", "0.2" if level == 1 else "0.8"),
            ("volume_multiplier", "0.5" if level == 1 else "1.5"),
        ),
        "execution-stress": (
            ("slippage_bps", "25" if level == 1 else "100"),
        ),
    }
    return SensitivityCampaignCase(
        recipe_version_id=f"recipe-{family}-{level}",
        recipe_content_hash=f"recipe-hash-{family}-{level}",
        materialization_hash=f"path-hash-{family}-{level}",
        historical_segment_id="segment-1",
        historical_segment_content_hash="segment-content-1",
        source_snapshot_id=source_snapshot_id,
        materialization_seed=seed,
        expander_version="deterministic-30s-expander.v1",
        source_resolution="5m",
        runtime_resolution="30s",
        numeric_tolerance="0.000001",
        normalization_provenance="fixture-normalization.v1",
        transformation_catalog_version="scenario-transformation-catalog.v1",
        transformation_id=transformation_id,
        transformation_family=family,
        transformation_implementation_version=(
            catalog_entry.implementation_version
        ),
        transformation_parameters=parameters_by_family[family],
        market_rule_profile_version="a-share-cash-equity.v1",
        decision_cadence_minutes=30,
        requested_execution_conditions=RequestedExecutionAssumptions(
            commission_bps=Decimal("3"),
            slippage_bps=Decimal("5"),
            max_fill_fraction=Decimal("1"),
            latency_nodes=0,
            allow_partial_fills=True,
        ),
    )


def _sweeps(
    cases: tuple[SensitivityCampaignCase, ...],
) -> tuple[SensitivitySweepDefinition, ...]:
    return tuple(
        SensitivitySweepDefinition(
            transformation_family=family,
            transformation_id=family_cases[0].transformation_id,
            transformation_implementation_version=(
                family_cases[0].transformation_implementation_version
            ),
            levels=family_cases,
        )
        for family in ISOLATED_SENSITIVITY_FAMILIES
        if (
            family_cases := tuple(
                case for case in cases if case.transformation_family == family
            )
        )
    )


def _specification() -> IsolatedSensitivitySetSpecification:
    cases = tuple(
        _case(family, level)
        for family in reversed(ISOLATED_SENSITIVITY_FAMILIES)
        for level in (2, 1)
    )
    return IsolatedSensitivitySetSpecification(
        sensitivity_set_replica_id="sensitivity-set-1",
        sweeps=_sweeps(cases),
        initial_cash=Decimal("100000"),
        order_shares=1000,
    )


class _Campaign:
    def __init__(
        self,
        specification: IsolatedSensitivitySetSpecification,
        case: SensitivityCampaignCase,
        attempt_number: int,
        *,
        completed: bool,
    ) -> None:
        self.status = "completed" if completed else "incomplete"
        self.campaign_id = f"campaign-{case.case_id}-{attempt_number}"
        self._case = case
        self._set_specification = specification
        self._attempt_number = attempt_number
        self._campaign_replica_id = (
            f"{specification.sensitivity_set_replica_id}:"
            f"{case.case_id}:attempt-{attempt_number}"
        )

    def to_dict(self) -> dict[str, object]:
        members = []
        strategies = (
            (
                QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
                QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
                QUENTX_SCENARIO_NATIVE_MANIFEST,
                "quentx",
            ),
            (
                LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_ID,
                LIVE_MINUTE_SCENARIO_NATIVE_STRATEGY_VERSION,
                LIVE_MINUTE_SCENARIO_NATIVE_MANIFEST,
                "live-minute",
            ),
        )
        run_specifications: list[StrategyRunSpecification] = []
        for index, (
            strategy,
            strategy_version,
            manifest,
            replica_suffix,
        ) in enumerate(
            strategies,
            start=1,
        ):
            status = "completed" if self.status == "completed" else (
                "failed" if index == 1 else "completed"
            )
            resolved = resolve_execution_conditions(
                self._case.requested_execution_conditions,
                (
                    dict(self._case.transformation_parameters)
                    if self._case.transformation_family == "execution-stress"
                    else {}
                ),
            )
            run_specification = StrategyRunSpecification(
                recipe_version_id=self._case.recipe_version_id,
                recipe_content_hash=self._case.recipe_content_hash,
                materialization_hash=self._case.materialization_hash,
                source_snapshot_id=self._case.source_snapshot_id,
                materialization_seed=self._case.materialization_seed,
                transformation_catalog_version=(
                    self._case.transformation_catalog_version
                ),
                transformation_implementation_versions=(
                    f"{self._case.transformation_id}@"
                    f"{self._case.transformation_implementation_version}",
                ),
                market_rule_profile_version=(
                    self._case.market_rule_profile_version
                ),
                execution_policy_version=BASELINE_EXECUTION_POLICY_VERSION,
                strategy_id=strategy,
                strategy_version=strategy_version,
                decision_cadence_minutes=self._case.decision_cadence_minutes,
                initial_cash=self._set_specification.initial_cash,
                order_shares=self._set_specification.order_shares,
                replica_id=f"{self._campaign_replica_id}:{replica_suffix}",
                code_identity="strategy-diagnostics.v1",
                ptrade_manifest_hash=manifest.content_hash,
                ptrade_host_adapter_version=PTRADE_SUBPROCESS_HOST_VERSION,
                commission_bps=resolved.effective.commission_bps,
                resolved_execution_conditions=resolved,
            )
            run_specifications.append(run_specification)
            member_specification = run_specification.to_dict()
            members.append(
                {
                    "strategy_id": strategy,
                    "strategy_version": strategy_version,
                    "run_id": run_specification.run_id,
                    "replica_id": (
                        f"{self._campaign_replica_id}:{replica_suffix}"
                    ),
                    "materialization_hash": self._case.materialization_hash,
                    "specification": member_specification,
                    "status": status,
                    "equity_curve": (
                        [
                            {"simulation_time": "2024-01-02T09:30:00", "equity": "100000"},
                            {
                                "simulation_time": "2024-01-02T15:00:00",
                                "equity": str(100000 + self._attempt_number * 100 + index),
                            },
                        ]
                        if status == "completed"
                        else []
                    ),
                }
            )
        campaign_specification = BaselineCampaignSpecification(
            campaign_replica_id=self._campaign_replica_id,
            strategy_runs=(run_specifications[0], run_specifications[1]),
        )
        self.campaign_id = campaign_specification.campaign_id
        return {
            "campaign_id": self.campaign_id,
            "campaign_replica_id": self._campaign_replica_id,
            "status": self.status,
            "completeness": {
                "completed_count": 2 if self.status == "completed" else 1,
                "total_count": 2,
                "is_complete": self.status == "completed",
            },
            "shared_market_nodes": {
                "identical_observed_timeline": self.status == "completed",
            },
            "isolation": {
                "verification_status": (
                    "verified" if self.status == "completed" else "unverified"
                ),
                "fresh_subprocess_per_callback": self.status == "completed",
            },
            "members": members,
        }


class _RecordingExecutor:
    def __init__(self, fail_once_case_id: str | None = None) -> None:
        self.calls: list[tuple[str, int]] = []
        self._fail_once_case_id = fail_once_case_id

    def __call__(
        self,
        specification: IsolatedSensitivitySetSpecification,
        case: SensitivityCampaignCase,
        attempt_number: int,
        nodes_per_batch: int,
    ) -> _Campaign:
        assert specification.initial_cash == Decimal("100000")
        assert nodes_per_batch > 0
        self.calls.append((case.case_id, attempt_number))
        completed = not (
            case.case_id == self._fail_once_case_id and attempt_number == 1
        )
        return _Campaign(
            specification,
            case,
            attempt_number,
            completed=completed,
        )


def test_set_requires_two_bounded_cases_for_every_registered_family() -> None:
    specification = _specification()

    assert tuple(case.transformation_family for case in specification.ordered_cases)[::2] == (
        ISOLATED_SENSITIVITY_FAMILIES
    )
    assert len({case.case_id for case in specification.cases}) == 12
    assert specification.to_dict()["execution_order"] == "sequential"
    assert len(specification.to_dict()["sweeps"]) == 6
    assert len(specification.to_dict()["cases"]) == 12
    assert specification.to_dict()["pinned_comparison_inputs"][
        "controlled_random_source"
    ] == "materialization_seed+decision_index.v1"
    catalog = create_initial_transformation_catalog()
    for sweep in specification.sweeps:
        entry = catalog.get_entry(sweep.transformation_id)
        assert entry.family == sweep.transformation_family
        assert entry.implementation_version == (
            sweep.transformation_implementation_version
        )

    with pytest.raises(ValueError, match="execution-stress"):
        IsolatedSensitivitySetSpecification(
            sensitivity_set_replica_id=specification.sensitivity_set_replica_id,
            sweeps=tuple(
                sweep
                for sweep in specification.sweeps
                if sweep.transformation_family != "execution-stress"
            ),
            initial_cash=specification.initial_cash,
            order_shares=specification.order_shares,
        )


def test_set_rejects_changed_comparable_inputs_and_duplicate_levels() -> None:
    specification = _specification()
    changed = replace(specification.cases[-1], materialization_seed=18)
    with pytest.raises(ValueError, match="materialization seed"):
        IsolatedSensitivitySetSpecification(
            sensitivity_set_replica_id="changed-seed",
            sweeps=_sweeps(specification.cases[:-1] + (changed,)),
            initial_cash=Decimal("100000"),
            order_shares=1000,
        )

    duplicated = replace(
        specification.cases[-1],
        transformation_parameters=specification.cases[-2].transformation_parameters,
    )
    with pytest.raises(ValueError, match="unique parameters"):
        IsolatedSensitivitySetSpecification(
            sensitivity_set_replica_id="duplicate-level",
            sweeps=_sweeps(specification.cases[:-1] + (duplicated,)),
            initial_cash=Decimal("100000"),
            order_shares=1000,
        )

    mixed_implementation = replace(
        specification.cases[1],
        transformation_implementation_version="mixed-implementation.v2",
    )
    with pytest.raises(ValueError, match="declared family"):
        _sweeps(
            (specification.cases[0], mixed_implementation)
            + specification.cases[2:]
        )


def test_runner_is_deterministic_partial_visible_and_resumable() -> None:
    specification = _specification()
    executor = _RecordingExecutor()
    runner = IsolatedSensitivitySetRunner(executor)

    planned = runner.plan(specification)
    partial = runner.advance(planned.sensitivity_set_id, max_cases=2)
    resumed = runner.resume(planned.sensitivity_set_id)

    assert planned.status == "planned"
    assert partial.status == "partial"
    assert partial.completed_count == 2
    assert partial.pending_count == 10
    assert resumed.status == "completed"
    assert [case_id for case_id, _ in executor.calls] == [
        case.case_id for case in specification.ordered_cases
    ]
    assert all(attempt == 1 for _, attempt in executor.calls)


def test_incomplete_case_stays_visible_and_can_be_retried_with_traceable_curves() -> None:
    specification = _specification()
    failed_case = specification.ordered_cases[0]
    executor = _RecordingExecutor(fail_once_case_id=failed_case.case_id)
    runner = IsolatedSensitivitySetRunner(executor)
    planned = runner.plan(specification)

    incomplete = runner.resume(planned.sensitivity_set_id)
    failed_view = next(
        item
        for item in incomplete.to_dict()["cases"]
        if item["case_id"] == failed_case.case_id
    )
    assert incomplete.status == "incomplete"
    assert failed_view["status"] == "incomplete"
    assert failed_view["attempts"][0]["attempt_number"] == 1

    completed = runner.retry_case(
        planned.sensitivity_set_id,
        failed_case.case_id,
    )
    point = completed.to_dict()["sensitivity_curves"][0]["points"][0]

    assert completed.status == "completed"
    assert point["case_id"] == failed_case.case_id
    assert point["attempt_number"] == 2
    assert point["campaign_id"].startswith("baseline-campaign-")
    assert point["run_id"].startswith("strategy-run-")
    assert point["recipe_version_id"] == failed_case.recipe_version_id
    assert point["materialization_hash"] == failed_case.materialization_hash
    assert point["parameters"] == dict(failed_case.transformation_parameters)
    assert point["final_equity"]
    assert point["max_drawdown"] == "0"


def test_runner_rejects_a_campaign_result_from_another_case() -> None:
    specification = _specification()
    wrong_case = specification.ordered_cases[1]

    def wrong_executor(
        set_specification: IsolatedSensitivitySetSpecification,
        _case_to_run: SensitivityCampaignCase,
        attempt_number: int,
        _nodes_per_batch: int,
    ) -> _Campaign:
        return _Campaign(
            set_specification,
            wrong_case,
            attempt_number,
            completed=True,
        )

    runner = IsolatedSensitivitySetRunner(wrong_executor)
    planned = runner.plan(specification)
    result = runner.advance(planned.sensitivity_set_id)
    first_case = result.to_dict()["cases"][0]

    assert first_case["status"] == "incomplete"
    assert "assigned case" in first_case["attempts"][0]["failure"]["message"]
    assert result.to_dict()["sensitivity_curves"] == []


def test_runner_rejects_completed_status_without_two_complete_members() -> None:
    specification = _specification()

    class _InconsistentCampaign(_Campaign):
        def to_dict(self) -> dict[str, object]:
            view = super().to_dict()
            members = view["members"]
            assert isinstance(members, list)
            members[0]["status"] = "failed"
            return view

    def inconsistent_executor(
        set_specification: IsolatedSensitivitySetSpecification,
        case: SensitivityCampaignCase,
        attempt_number: int,
        _nodes_per_batch: int,
    ) -> _Campaign:
        return _InconsistentCampaign(
            set_specification,
            case,
            attempt_number,
            completed=True,
        )

    runner = IsolatedSensitivitySetRunner(inconsistent_executor)
    planned = runner.plan(specification)
    result = runner.advance(planned.sensitivity_set_id)
    attempt = result.to_dict()["cases"][0]["attempts"][0]

    assert result.cases[0].status == "incomplete"
    assert "complete, comparable, isolated" in attempt["failure"]["message"]


def test_invalid_retry_controls_do_not_pollute_attempt_history() -> None:
    specification = _specification()
    failed_case = specification.ordered_cases[0]
    runner = IsolatedSensitivitySetRunner(
        _RecordingExecutor(fail_once_case_id=failed_case.case_id)
    )
    planned = runner.plan(specification)
    incomplete = runner.advance(planned.sensitivity_set_id)

    with pytest.raises(ValueError, match="nodes per batch"):
        runner.retry_case(
            planned.sensitivity_set_id,
            failed_case.case_id,
            nodes_per_batch=0,
        )
    with pytest.raises(ValueError, match="max cases"):
        runner.resume(planned.sensitivity_set_id, max_cases=0)

    retained = runner.get(planned.sensitivity_set_id)
    assert len(retained.cases[0].attempts) == 1


def test_partial_set_and_attempts_resume_after_repository_restart(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sensitivity.db'}",
        future=True,
    )
    initialize_diagnostic_persistence(engine)
    specification = _specification()
    first_executor = _RecordingExecutor()
    first_runner = IsolatedSensitivitySetRunner(
        first_executor,
        repository=SqlIsolatedSensitivitySetRepository(engine),
    )
    planned = first_runner.plan(specification)
    partial = first_runner.advance(planned.sensitivity_set_id, max_cases=2)

    restarted_executor = _RecordingExecutor()
    restarted_repository = SqlIsolatedSensitivitySetRepository(engine)
    restarted_runner = IsolatedSensitivitySetRunner(
        restarted_executor,
        repository=restarted_repository,
    )
    restored = restarted_runner.get(planned.sensitivity_set_id)
    retained_view = restored.to_dict()
    mutated_view = restored.to_dict()
    mutated_view["cases"][0]["attempts"][0]["members"][0]["equity_curve"][0][
        "equity"
    ] = "forged-equity"
    assert restored.to_dict() == retained_view
    restarted_repository.save(restored)
    reloaded = restarted_repository.get(planned.sensitivity_set_id)
    assert reloaded is not None
    assert reloaded.to_dict() == retained_view
    resumed = restarted_runner.advance(
        planned.sensitivity_set_id,
        max_cases=1,
    )

    assert partial.status == "partial"
    assert restored.to_dict() == partial.to_dict()
    assert restored.completed_count == 2
    assert len(restored.cases[0].attempts) == 1
    assert resumed.completed_count == 3
    assert restarted_executor.calls == [
        (specification.ordered_cases[2].case_id, 1)
    ]


def test_sql_restart_rejects_corrupted_campaign_case_assignment(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'corrupted-sensitivity.db'}",
        future=True,
    )
    initialize_diagnostic_persistence(engine)
    specification = _specification()
    repository = SqlIsolatedSensitivitySetRepository(engine)
    runner = IsolatedSensitivitySetRunner(
        _RecordingExecutor(),
        repository=repository,
    )
    planned = runner.plan(specification)
    runner.advance(planned.sensitivity_set_id)

    with engine.begin() as connection:
        snapshot_json = connection.execute(
            text(
                "SELECT snapshot_json FROM diagnostic_isolated_sensitivity_sets "
                "WHERE sensitivity_set_id = :sensitivity_set_id"
            ),
            {"sensitivity_set_id": planned.sensitivity_set_id},
        ).scalar_one()
        payload = json.loads(str(snapshot_json))
        payload["case_attempts"][0]["attempts"][0][
            "campaign_replica_id"
        ] = "wrong-case-replica"
        connection.execute(
            text(
                "UPDATE diagnostic_isolated_sensitivity_sets "
                "SET snapshot_json = :snapshot_json "
                "WHERE sensitivity_set_id = :sensitivity_set_id"
            ),
            {
                "snapshot_json": json.dumps(payload, sort_keys=True),
                "sensitivity_set_id": planned.sensitivity_set_id,
            },
        )

    with pytest.raises(ValueError, match="assigned case"):
        SqlIsolatedSensitivitySetRepository(engine).get(
            planned.sensitivity_set_id
        )


def test_sql_restart_rejects_rehashed_but_misassigned_pinned_run_inputs(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'rehashed-wrong-input.db'}",
        future=True,
    )
    initialize_diagnostic_persistence(engine)
    specification = _specification()
    runner = IsolatedSensitivitySetRunner(
        _RecordingExecutor(),
        repository=SqlIsolatedSensitivitySetRepository(engine),
    )
    planned = runner.plan(specification)
    runner.advance(planned.sensitivity_set_id)

    with engine.begin() as connection:
        snapshot_json = connection.execute(
            text(
                "SELECT snapshot_json FROM diagnostic_isolated_sensitivity_sets "
                "WHERE sensitivity_set_id = :sensitivity_set_id"
            ),
            {"sensitivity_set_id": planned.sensitivity_set_id},
        ).scalar_one()
        payload = json.loads(str(snapshot_json))
        attempt = payload["case_attempts"][0]["attempts"][0]
        rehashed_specs = []
        for member in attempt["members"]:
            member["specification"]["materialization_seed"] = 999
            rehashed = StrategyRunSpecification.from_pinned_dict(
                member["specification"]
            )
            member["run_id"] = rehashed.run_id
            rehashed_specs.append(rehashed)
        attempt["campaign_id"] = BaselineCampaignSpecification(
            campaign_replica_id=attempt["campaign_replica_id"],
            strategy_runs=(rehashed_specs[0], rehashed_specs[1]),
        ).campaign_id
        connection.execute(
            text(
                "UPDATE diagnostic_isolated_sensitivity_sets "
                "SET snapshot_json = :snapshot_json "
                "WHERE sensitivity_set_id = :sensitivity_set_id"
            ),
            {
                "snapshot_json": json.dumps(payload, sort_keys=True),
                "sensitivity_set_id": planned.sensitivity_set_id,
            },
        )

    with pytest.raises(ValueError, match="belongs to another case"):
        SqlIsolatedSensitivitySetRepository(engine).get(
            planned.sensitivity_set_id
        )


@pytest.mark.parametrize(
    ("corruption", "message"),
    (
        ("replica-pairing", "belongs to another case"),
        ("member-order", "canonical representative strategy order"),
    ),
)
def test_sql_restart_rejects_rehashed_noncanonical_member_assignment(
    tmp_path: Path,
    corruption: str,
    message: str,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / f'rehashed-{corruption}.db'}",
        future=True,
    )
    initialize_diagnostic_persistence(engine)
    specification = _specification()
    runner = IsolatedSensitivitySetRunner(
        _RecordingExecutor(),
        repository=SqlIsolatedSensitivitySetRepository(engine),
    )
    planned = runner.plan(specification)
    runner.advance(planned.sensitivity_set_id)

    with engine.begin() as connection:
        snapshot_json = connection.execute(
            text(
                "SELECT snapshot_json FROM diagnostic_isolated_sensitivity_sets "
                "WHERE sensitivity_set_id = :sensitivity_set_id"
            ),
            {"sensitivity_set_id": planned.sensitivity_set_id},
        ).scalar_one()
        payload = json.loads(str(snapshot_json))
        attempt = payload["case_attempts"][0]["attempts"][0]
        members = attempt["members"]
        if corruption == "replica-pairing":
            members[0]["replica_id"], members[1]["replica_id"] = (
                members[1]["replica_id"],
                members[0]["replica_id"],
            )
            for member in members:
                member["specification"]["replica_id"] = member["replica_id"]
        else:
            members.reverse()
        rehashed_specs = []
        for member in members:
            rehashed = StrategyRunSpecification.from_pinned_dict(
                member["specification"]
            )
            member["run_id"] = rehashed.run_id
            rehashed_specs.append(rehashed)
        attempt["campaign_id"] = BaselineCampaignSpecification(
            campaign_replica_id=attempt["campaign_replica_id"],
            strategy_runs=(rehashed_specs[0], rehashed_specs[1]),
        ).campaign_id
        connection.execute(
            text(
                "UPDATE diagnostic_isolated_sensitivity_sets "
                "SET snapshot_json = :snapshot_json "
                "WHERE sensitivity_set_id = :sensitivity_set_id"
            ),
            {
                "snapshot_json": json.dumps(payload, sort_keys=True),
                "sensitivity_set_id": planned.sensitivity_set_id,
            },
        )

    with pytest.raises(ValueError, match=message):
        SqlIsolatedSensitivitySetRepository(engine).get(
            planned.sensitivity_set_id
        )


def test_sql_restart_rejects_forged_completed_status(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'forged-completion.db'}",
        future=True,
    )
    initialize_diagnostic_persistence(engine)
    specification = _specification()
    failed_case = specification.ordered_cases[0]
    runner = IsolatedSensitivitySetRunner(
        _RecordingExecutor(fail_once_case_id=failed_case.case_id),
        repository=SqlIsolatedSensitivitySetRepository(engine),
    )
    planned = runner.plan(specification)
    runner.advance(planned.sensitivity_set_id)

    with engine.begin() as connection:
        snapshot_json = connection.execute(
            text(
                "SELECT snapshot_json FROM diagnostic_isolated_sensitivity_sets "
                "WHERE sensitivity_set_id = :sensitivity_set_id"
            ),
            {"sensitivity_set_id": planned.sensitivity_set_id},
        ).scalar_one()
        payload = json.loads(str(snapshot_json))
        payload["case_attempts"][0]["attempts"][0]["status"] = "completed"
        connection.execute(
            text(
                "UPDATE diagnostic_isolated_sensitivity_sets "
                "SET snapshot_json = :snapshot_json "
                "WHERE sensitivity_set_id = :sensitivity_set_id"
            ),
            {
                "snapshot_json": json.dumps(payload, sort_keys=True),
                "sensitivity_set_id": planned.sensitivity_set_id,
            },
        )

    with pytest.raises(ValueError, match="complete, comparable, isolated"):
        SqlIsolatedSensitivitySetRepository(engine).get(
            planned.sensitivity_set_id
        )


@pytest.mark.parametrize(
    ("identity", "message"),
    (
        ("campaign", "campaign identity is not canonical"),
        ("run", "run identity is not canonical"),
    ),
)
def test_sql_restart_rejects_forged_trace_identities(
    tmp_path: Path,
    identity: str,
    message: str,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / f'forged-{identity}.db'}",
        future=True,
    )
    initialize_diagnostic_persistence(engine)
    specification = _specification()
    runner = IsolatedSensitivitySetRunner(
        _RecordingExecutor(),
        repository=SqlIsolatedSensitivitySetRepository(engine),
    )
    planned = runner.plan(specification)
    runner.advance(planned.sensitivity_set_id)

    with engine.begin() as connection:
        snapshot_json = connection.execute(
            text(
                "SELECT snapshot_json FROM diagnostic_isolated_sensitivity_sets "
                "WHERE sensitivity_set_id = :sensitivity_set_id"
            ),
            {"sensitivity_set_id": planned.sensitivity_set_id},
        ).scalar_one()
        payload = json.loads(str(snapshot_json))
        attempt = payload["case_attempts"][0]["attempts"][0]
        if identity == "campaign":
            attempt["campaign_id"] = "forged-campaign"
        else:
            attempt["members"][0]["run_id"] = "forged-run"
        connection.execute(
            text(
                "UPDATE diagnostic_isolated_sensitivity_sets "
                "SET snapshot_json = :snapshot_json "
                "WHERE sensitivity_set_id = :sensitivity_set_id"
            ),
            {
                "snapshot_json": json.dumps(payload, sort_keys=True),
                "sensitivity_set_id": planned.sensitivity_set_id,
            },
        )

    with pytest.raises(ValueError, match=message):
        SqlIsolatedSensitivitySetRepository(engine).get(
            planned.sensitivity_set_id
        )


def test_snapshot_hydration_rejects_duplicate_case_records() -> None:
    specification = _specification()
    runner = IsolatedSensitivitySetRunner(_RecordingExecutor())
    planned = runner.plan(specification)
    storage = planned.to_storage_dict()
    case_attempts = storage["case_attempts"]
    assert isinstance(case_attempts, list)
    case_attempts.append(dict(case_attempts[0]))

    with pytest.raises(ValueError, match="duplicate cases"):
        IsolatedSensitivitySetSnapshot.from_storage_dict(storage)
