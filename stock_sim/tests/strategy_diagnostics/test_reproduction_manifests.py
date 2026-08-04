from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from strategy_diagnostics.diagnostic_evidence import (
    DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION,
    DiagnosticEvidencePackage,
    calculate_run_evidence_metrics,
)
from strategy_diagnostics.execution_conditions import (
    RequestedExecutionAssumptions,
    resolve_execution_conditions,
)
from strategy_diagnostics.historical_segments import (
    SourceArtifact,
    SourceProvenance,
    SourceSnapshot,
)
from strategy_diagnostics.ptrade_host import (
    PTRADE_IN_PROCESS_HOST_VERSION,
    QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
    QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
    ptrade_manifest_for,
)
from strategy_diagnostics.market_paths import (
    InstrumentState,
    MarketPathNode,
    MaterializedMarketPath,
)
from strategy_diagnostics.reproduction import (
    DIAGNOSTIC_CODE_IDENTITY,
    InMemoryReproductionRepository,
    ReproductionCheck,
    ReproductionManifest,
    ReproductionMismatch,
    ReproductionReport,
    ReproductionService,
)
from strategy_diagnostics.reproduction_storage import (
    SqlReproductionRepository,
)
from strategy_diagnostics.persistence import (
    initialize_diagnostic_persistence,
)
from strategy_diagnostics.strategy_runs import (
    BASELINE_EXECUTION_POLICY_VERSION,
    EquityPoint,
    StrategyRunSnapshot,
    StrategyRunSpecification,
)


def _specification() -> StrategyRunSpecification:
    requested = RequestedExecutionAssumptions(
        commission_bps=Decimal("3"),
        slippage_bps=Decimal("5"),
        max_fill_fraction=Decimal("1"),
        latency_nodes=0,
        allow_partial_fills=True,
    )
    resolved = resolve_execution_conditions(requested, {})
    ptrade = ptrade_manifest_for(
        QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
        QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
    )
    return StrategyRunSpecification(
        recipe_version_id="recipe-version-1",
        recipe_content_hash="a" * 64,
        materialization_hash="b" * 64,
        source_snapshot_id=_source_snapshot().snapshot_id,
        materialization_seed=17,
        transformation_catalog_version="scenario-transformation-catalog.v1",
        transformation_implementation_versions=(),
        market_rule_profile_version="a-share-cash-equity.v1",
        execution_policy_version=BASELINE_EXECUTION_POLICY_VERSION,
        strategy_id=QUENTX_SCENARIO_NATIVE_STRATEGY_ID,
        strategy_version=QUENTX_SCENARIO_NATIVE_STRATEGY_VERSION,
        decision_cadence_minutes=30,
        initial_cash=Decimal("100000"),
        order_shares=1000,
        replica_id="accepted-run:quentx",
        code_identity="strategy-diagnostics.v1",
        ptrade_surface_version=ptrade.surface_version,
        ptrade_manifest_hash=ptrade.content_hash,
        ptrade_host_adapter_version=PTRADE_IN_PROCESS_HOST_VERSION,
        commission_bps=resolved.effective.commission_bps,
        resolved_execution_conditions=resolved,
    )


def _accepted_result() -> dict[str, object]:
    return {
        "orders": [],
        "fills": [],
        "portfolio": {
            "cash": "100000",
            "positions": [],
        },
        "equity_curve": [],
        "metrics": [],
        "evidence": {
            "metric_ids": [],
            "comparison_ids": [],
            "breach_ids": [],
            "breakpoint_ids": [],
            "finding_ids": [],
        },
    }


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_snapshot(
    *,
    artifact_hash: str = "7" * 64,
) -> SourceSnapshot:
    provenance = SourceProvenance(
        provider="fixture-provider",
        dataset="fixture-dataset",
        version="fixture-v1",
        observed_at=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )
    artifacts = (
        SourceArtifact(
            name="fixture-bars",
            content_hash=artifact_hash,
            row_count=2,
        ),
    )
    content_hash = _canonical_hash(
        {
            "provenance": provenance.to_dict(),
            "artifacts": [artifact.to_dict() for artifact in artifacts],
        }
    )
    return SourceSnapshot(
        snapshot_id=f"snapshot_{content_hash[:20]}",
        content_hash=content_hash,
        provenance=provenance,
        artifacts=artifacts,
    )


def _path() -> MaterializedMarketPath:
    start = datetime(2024, 1, 2, 9, 30)
    nodes = tuple(
        MarketPathNode(
            instrument="sh.600000",
            simulation_time=simulation_time,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=1000,
            amount=price * Decimal("1000"),
            reconstructed=True,
        )
        for simulation_time, price in (
            (start, Decimal("10")),
            (start + timedelta(seconds=30), Decimal("11")),
        )
    )
    return MaterializedMarketPath(
        artifact_hash="b" * 64,
        segment_id="segment-1",
        segment_content_hash="9" * 64,
        source_snapshot_id=_source_snapshot().snapshot_id,
        seed=17,
        expander_version="deterministic-30s-expander.v1",
        source_resolution="5m",
        runtime_resolution="30s",
        reconstructed=True,
        numeric_tolerance="0.000001",
        normalization_provenance="fixture-normalization.v1",
        market_rule_profile_version="a-share-cash-equity.v1",
        transformation_catalog_version="scenario-transformation-catalog.v1",
        applied_transformations=(),
        nodes=nodes,
        instrument_states=(
            InstrumentState(
                instrument="sh.600000",
                effective_at=start,
                eligible=True,
                trading_status="trading",
                is_st=False,
                industry="banking",
                decision_adjustment_factor=Decimal("1"),
                decision_adjustment_provenance="fixture-adjustment.v1",
            ),
        ),
    )


def _snapshot(
    specification: StrategyRunSpecification,
    *,
    ending_equity: Decimal,
    run_artifact_hash: str,
) -> StrategyRunSnapshot:
    start = datetime(2024, 1, 2, 9, 30)
    curve = (
        EquityPoint(
            simulation_time=start,
            cash=Decimal("100000"),
            positions_value=Decimal("0"),
            equity=Decimal("100000"),
        ),
        EquityPoint(
            simulation_time=start + timedelta(seconds=30),
            cash=ending_equity,
            positions_value=Decimal("0"),
            equity=ending_equity,
        ),
    )
    return StrategyRunSnapshot(
        run_id=specification.run_id,
        status="completed",
        specification=specification,
        current_simulation_time=curve[-1].simulation_time,
        processed_node_count=2,
        total_node_count=2,
        decision_times=(),
        orders=(),
        fills=(),
        cash=ending_equity,
        positions=(),
        equity_curve=curve,
        ptrade_audit=None,
        failure_code=None,
        failure_message=None,
        run_artifact_hash=run_artifact_hash,
    )


def _service_fixture(
    *,
    tolerance: Decimal,
    reproduced_ending_equity: Decimal,
    replay_error: str | None = None,
    loaded_source_snapshot: SourceSnapshot | None = None,
) -> tuple[ReproductionService, ReproductionManifest]:
    specification = _specification()
    path = _path()
    accepted = _snapshot(
        specification,
        ending_equity=Decimal("100100"),
        run_artifact_hash="c" * 64,
    )
    provisional = ReproductionManifest.create(
        specification=specification,
        run_artifact_hash="c" * 64,
        numeric_tolerance=tolerance,
        case_id="case-1",
        layer="baseline",
        evidence_package_id="diagnostic-evidence-" + "d" * 24,
        evidence_artifact_hash="d" * 64,
        measurement_artifact_hash="e" * 64,
        accepted_result=_accepted_result(),
    )
    metrics = calculate_run_evidence_metrics(
        snapshot=accepted,
        path=path,
        case_id="case-1",
        layer="baseline",
        reproduction_manifest_id=provisional.evidence_reference_id,
    )
    evidence_payload: dict[str, object] = {
        "schema_version": DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION,
        "status": "sealed",
        "campaign_id": "campaign-1",
        "measurement_artifact_hash": "e" * 64,
        "metrics": list(metrics),
        "comparisons": [],
        "guardrail_breaches": [],
        "sensitivity_breakpoints": [],
        "diagnostic_findings": [],
        "reproduction_manifests": [],
    }
    evidence_hash = _canonical_hash(evidence_payload)
    evidence = DiagnosticEvidencePackage.from_payload(
        evidence_payload,
        evidence_hash,
    )
    accepted_result = {
        "orders": accepted.to_dict()["orders"],
        "fills": accepted.to_dict()["fills"],
        "portfolio": accepted.to_dict()["portfolio"],
        "equity_curve": accepted.to_dict()["equity_curve"],
        "metrics": list(metrics),
        "evidence": {
            "metric_ids": sorted(
                str(metric["metric_id"]) for metric in metrics
            ),
            "comparison_ids": [],
            "breach_ids": [],
            "breakpoint_ids": [],
            "finding_ids": [],
        },
    }
    manifest = ReproductionManifest.create(
        specification=specification,
        run_artifact_hash="c" * 64,
        numeric_tolerance=tolerance,
        case_id="case-1",
        layer="baseline",
        evidence_package_id=evidence.evidence_package_id,
        evidence_artifact_hash=evidence.artifact_hash,
        measurement_artifact_hash="e" * 64,
        accepted_result=accepted_result,
    )
    repository = InMemoryReproductionRepository()
    repository.add_manifests((manifest,))
    replayed = _snapshot(
        specification,
        ending_equity=reproduced_ending_equity,
        run_artifact_hash="f" * 64,
    )

    def replay_run(_: StrategyRunSpecification) -> StrategyRunSnapshot:
        if replay_error is not None:
            raise ValueError(replay_error)
        return replayed

    service = ReproductionService(
        run_loader=lambda _: accepted,
        recipe_hash_loader=lambda _: specification.recipe_content_hash,
        path_loader=lambda _: path,
        evidence_loader=lambda _: evidence,
        source_snapshot_loader=lambda _: (
            loaded_source_snapshot or _source_snapshot()
        ),
        replay_run=replay_run,
        code_identity=DIAGNOSTIC_CODE_IDENTITY,
        repository=repository,
    )
    return service, manifest


def test_manifest_pins_complete_dependencies_and_has_canonical_identity() -> None:
    specification = _specification()

    manifest = ReproductionManifest.create(
        specification=specification,
        run_artifact_hash="c" * 64,
        numeric_tolerance=Decimal("0.000001"),
        case_id="case-1",
        layer="baseline",
        evidence_package_id="diagnostic-evidence-" + "d" * 24,
        evidence_artifact_hash="d" * 64,
        measurement_artifact_hash="e" * 64,
        accepted_result=_accepted_result(),
    )

    view = manifest.to_dict()
    pinned = view["strategy_run_specification"]
    assert pinned == specification.to_dict()
    assert {
        "recipe_version_id",
        "recipe_content_hash",
        "source_snapshot_id",
        "materialization_hash",
        "materialization_seed",
        "transformation_catalog_version",
        "transformation_implementation_versions",
        "market_rule_profile_version",
        "execution_policy_version",
        "strategy_id",
        "strategy_version",
        "ptrade_surface_version",
        "ptrade_manifest_hash",
        "ptrade_host_adapter_version",
        "code_identity",
        "engine_version",
    } <= set(pinned)
    assert manifest.manifest_id.startswith("reproduction-manifest-")
    assert view["evidence_reference_id"] == (
        manifest.evidence_reference_id
    )
    assert len(manifest.manifest_content_hash) == 64
    assert ReproductionManifest.from_dict(view) == manifest
    assert ReproductionManifest.create(
        specification=specification,
        run_artifact_hash="c" * 64,
        numeric_tolerance=Decimal("0.000001"),
        case_id="case-1",
        layer="baseline",
        evidence_package_id="diagnostic-evidence-" + "d" * 24,
        evidence_artifact_hash="d" * 64,
        measurement_artifact_hash="e" * 64,
        accepted_result={
            "evidence": _accepted_result()["evidence"],
            "metrics": [],
            "equity_curve": [],
            "portfolio": _accepted_result()["portfolio"],
            "fills": [],
            "orders": [],
        },
    ).manifest_content_hash == manifest.manifest_content_hash


def test_evidence_specific_acceptances_have_distinct_formal_identities() -> None:
    specification = _specification()
    first = ReproductionManifest.create(
        specification=specification,
        run_artifact_hash="c" * 64,
        numeric_tolerance=Decimal("0.000001"),
        case_id="case-1",
        layer="baseline",
        evidence_package_id="diagnostic-evidence-" + "d" * 24,
        evidence_artifact_hash="d" * 64,
        measurement_artifact_hash="e" * 64,
        accepted_result=_accepted_result(),
    )
    second_result = _accepted_result()
    second_result["evidence"] = {
        "metric_ids": [],
        "comparison_ids": [],
        "breach_ids": ["guardrail-breach-fixture"],
        "breakpoint_ids": [],
        "finding_ids": ["diagnostic-finding-fixture"],
    }
    second = ReproductionManifest.create(
        specification=specification,
        run_artifact_hash="c" * 64,
        numeric_tolerance=Decimal("0.000001"),
        case_id="case-1",
        layer="baseline",
        evidence_package_id="diagnostic-evidence-" + "f" * 24,
        evidence_artifact_hash="f" * 64,
        measurement_artifact_hash="1" * 64,
        accepted_result=second_result,
    )
    repository = InMemoryReproductionRepository()

    repository.add_manifests((first, second))

    assert first.evidence_reference_id == second.evidence_reference_id
    assert first.manifest_id != second.manifest_id
    assert first.manifest_content_hash != second.manifest_content_hash
    assert repository.list_manifests(first.evidence_package_id) == (first,)
    assert repository.list_manifests(second.evidence_package_id) == (
        second,
    )


def test_evidence_manifest_batch_is_prevalidated_before_any_write() -> None:
    specification = _specification()
    path = _path()
    accepted = _snapshot(
        specification,
        ending_equity=Decimal("100100"),
        run_artifact_hash="c" * 64,
    )
    provisional = ReproductionManifest.create(
        specification=specification,
        run_artifact_hash="c" * 64,
        numeric_tolerance=Decimal("0.000001"),
        case_id="case-1",
        layer="baseline",
        evidence_package_id="diagnostic-evidence-" + "d" * 24,
        evidence_artifact_hash="d" * 64,
        measurement_artifact_hash="e" * 64,
        accepted_result=_accepted_result(),
    )
    metrics = calculate_run_evidence_metrics(
        snapshot=accepted,
        path=path,
        case_id="case-1",
        layer="baseline",
        reproduction_manifest_id=provisional.evidence_reference_id,
    )
    reference = {
        "reproduction_manifest_id": provisional.evidence_reference_id,
        "strategy_run_specification": specification.to_dict(),
        "run_id": specification.run_id,
        "run_artifact_hash": "c" * 64,
        "numeric_tolerance": "0.000001",
    }
    evidence_payload: dict[str, object] = {
        "schema_version": DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION,
        "status": "sealed",
        "campaign_id": "campaign-atomic-fixture",
        "measurement_artifact_hash": "e" * 64,
        "metrics": list(metrics),
        "comparisons": [],
        "guardrail_breaches": [],
        "sensitivity_breakpoints": [],
        "diagnostic_findings": [],
        "reproduction_manifests": [
            reference,
            {
                **reference,
                "run_id": "invalid-second-run",
            },
        ],
    }
    evidence_hash = _canonical_hash(evidence_payload)
    evidence = DiagnosticEvidencePackage.from_payload(
        evidence_payload,
        evidence_hash,
    )
    repository = InMemoryReproductionRepository()
    service = ReproductionService(
        run_loader=lambda _: accepted,
        recipe_hash_loader=lambda _: specification.recipe_content_hash,
        path_loader=lambda _: path,
        evidence_loader=lambda _: evidence,
        source_snapshot_loader=lambda _: _source_snapshot(),
        replay_run=lambda _: accepted,
        code_identity=DIAGNOSTIC_CODE_IDENTITY,
        repository=repository,
    )

    with pytest.raises(
        ValueError,
        match="run identity mismatch",
    ):
        service.accept_evidence(evidence)

    assert repository.list_manifests(evidence.evidence_package_id) == ()


def test_missing_or_changed_dependencies_fail_with_exact_visible_reasons() -> None:
    specification = _specification()
    manifest = ReproductionManifest.create(
        specification=specification,
        run_artifact_hash="c" * 64,
        numeric_tolerance=Decimal("0.000001"),
        case_id="case-1",
        layer="baseline",
        evidence_package_id="diagnostic-evidence-" + "d" * 24,
        evidence_artifact_hash="d" * 64,
        measurement_artifact_hash="e" * 64,
        accepted_result=_accepted_result(),
    )
    repository = InMemoryReproductionRepository()
    repository.add_manifests((manifest,))
    service = ReproductionService(
        run_loader=lambda _: (_ for _ in ()).throw(KeyError("run")),
        recipe_hash_loader=lambda _: (_ for _ in ()).throw(
            KeyError("recipe")
        ),
        path_loader=lambda _: (_ for _ in ()).throw(KeyError("path")),
        evidence_loader=lambda _: (_ for _ in ()).throw(
            KeyError("evidence")
        ),
        source_snapshot_loader=lambda _: (_ for _ in ()).throw(
            KeyError("source snapshot")
        ),
        replay_run=lambda _: (_ for _ in ()).throw(
            AssertionError("must not replay")
        ),
        code_identity="changed-code.v2",
        repository=repository,
    )

    report = service.reproduce(manifest.manifest_id)

    assert report.status == "reproducibility_invalid"
    assert report.reproduced_run_id is None
    assert {item.code for item in report.mismatches} == {
        "dependency.recipe_missing",
        "dependency.materialization_missing",
        "dependency.source_snapshot_missing",
        "dependency.code_identity_changed",
        "dependency.evidence_missing",
    }
    assert all(item.path and item.message for item in report.mismatches)
    assert service.latest_report(manifest.manifest_id) == report


def test_changed_source_snapshot_fails_without_replay_or_fallback() -> None:
    service, manifest = _service_fixture(
        tolerance=Decimal("0.000001"),
        reproduced_ending_equity=Decimal("100100"),
        loaded_source_snapshot=_source_snapshot(artifact_hash="8" * 64),
    )

    report = service.reproduce(manifest.manifest_id)

    assert report.status == "reproducibility_invalid"
    assert [item.code for item in report.mismatches] == [
        "dependency.source_snapshot_changed"
    ]
    mismatch = report.mismatches[0]
    assert mismatch.path == (
        "strategy_run_specification.source_snapshot_id"
    )
    assert mismatch.expected == manifest.specification.source_snapshot_id
    assert mismatch.actual != mismatch.expected


def test_declared_numeric_tolerance_is_enforced() -> None:
    within_service, within_manifest = _service_fixture(
        tolerance=Decimal("0.001"),
        reproduced_ending_equity=Decimal("100100.0005"),
    )
    outside_service, outside_manifest = _service_fixture(
        tolerance=Decimal("0.0001"),
        reproduced_ending_equity=Decimal("100100.0005"),
    )

    within = within_service.reproduce(within_manifest.manifest_id)
    outside = outside_service.reproduce(outside_manifest.manifest_id)

    assert within.status == "reproduced_within_tolerance"
    assert within.mismatches == ()
    assert any(
        item.status == "within_tolerance" for item in within.checks
    )
    assert outside.status == "reproducibility_invalid"
    assert any(
        item.code == "result.numeric_tolerance_exceeded"
        for item in outside.mismatches
    )


def test_changed_execution_environment_fails_with_exact_visible_reason() -> None:
    service, manifest = _service_fixture(
        tolerance=Decimal("0.000001"),
        reproduced_ending_equity=Decimal("100100"),
        replay_error=(
            "Unsupported pinned PTrade Compatibility Surface version"
        ),
    )

    report = service.reproduce(manifest.manifest_id)

    assert report.status == "reproducibility_invalid"
    assert len(report.mismatches) == 1
    mismatch = report.mismatches[0]
    assert mismatch.code == "dependency.execution_environment"
    assert mismatch.path == "strategy_run"
    assert mismatch.actual == "ValueError"
    assert (
        mismatch.message
        == "Unsupported pinned PTrade Compatibility Surface version"
    )


def test_sql_repository_survives_restart_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    service, manifest = _service_fixture(
        tolerance=Decimal("0.001"),
        reproduced_ending_equity=Decimal("100100.0005"),
    )
    report = service.reproduce(manifest.manifest_id)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'reproduction.db'}",
        future=True,
    )
    migration = initialize_diagnostic_persistence(engine)
    repository = SqlReproductionRepository(engine)

    repository.add_manifests((manifest,))
    repository.save_report(report)
    restarted = SqlReproductionRepository(engine)

    assert (
        migration.current_revision
        == "0020_scenario_lab_commands_and_materialization_handles"
    )
    assert restarted.get_manifest(manifest.manifest_id) == manifest
    assert restarted.list_manifests(manifest.evidence_package_id) == (
        manifest,
    )
    assert restarted.latest_report(manifest.manifest_id) == report

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_reproduction_attempts "
                "SET status = :changed "
                "WHERE attempt_id = :attempt_id"
            ),
            {
                "changed": "reproduced_exactly",
                "attempt_id": report.attempt_id,
            },
        )
    with pytest.raises(ValueError, match="canonical identity"):
        restarted.latest_report(manifest.manifest_id)

    tampered_report = report.to_dict()
    tampered_report["unexpected"] = "must fail closed"
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_reproduction_attempts "
                "SET status = :status, report_json = :report_json "
                "WHERE attempt_id = :attempt_id"
            ),
            {
                "status": report.status,
                "report_json": json.dumps(
                    tampered_report,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "attempt_id": report.attempt_id,
            },
        )
    with pytest.raises(ValueError, match="Report schema mismatch"):
        restarted.latest_report(manifest.manifest_id)

    invalid_status = report.to_dict()
    invalid_status["status"] = "latest"
    with pytest.raises(ValueError, match="Unsupported Reproduction Report"):
        ReproductionReport.from_dict(invalid_status)

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_reproduction_manifests "
                "SET run_id = :changed "
                "WHERE manifest_id = :manifest_id"
            ),
            {
                "changed": "strategy-run-row-drift",
                "manifest_id": manifest.manifest_id,
            },
        )
    with pytest.raises(ValueError, match="identity collision"):
        restarted.add_manifests((manifest,))

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_reproduction_manifests "
                "SET run_id = :run_id, evidence_package_id = :changed "
                "WHERE manifest_id = :manifest_id"
            ),
            {
                "run_id": manifest.run_id,
                "changed": "diagnostic-evidence-row-drift",
                "manifest_id": manifest.manifest_id,
            },
        )
    with pytest.raises(ValueError, match="identity collision"):
        restarted.add_manifests((manifest,))

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_reproduction_manifests "
                "SET evidence_package_id = :evidence_package_id, "
                "schema_version = :changed "
                "WHERE manifest_id = :manifest_id"
            ),
            {
                "evidence_package_id": manifest.evidence_package_id,
                "changed": "reproduction-manifest.v2",
                "manifest_id": manifest.manifest_id,
            },
        )
    with pytest.raises(ValueError, match="identity collision"):
        restarted.add_manifests((manifest,))
    with pytest.raises(ValueError, match="canonical identity"):
        restarted.get_manifest(manifest.manifest_id)

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_reproduction_manifests "
                "SET schema_version = :schema_version, "
                "numeric_tolerance = :changed "
                "WHERE manifest_id = :manifest_id"
            ),
            {
                "schema_version": "reproduction-manifest.v1",
                "changed": "0.1",
                "manifest_id": manifest.manifest_id,
            },
        )
    with pytest.raises(ValueError, match="canonical identity"):
        restarted.get_manifest(manifest.manifest_id)

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_reproduction_manifests "
                "SET numeric_tolerance = :numeric_tolerance, "
                "manifest_content_hash = :changed "
                "WHERE manifest_id = :manifest_id"
            ),
            {
                "numeric_tolerance": "0.001",
                "changed": "0" * 64,
                "manifest_id": manifest.manifest_id,
            },
        )

    with pytest.raises(ValueError, match="canonical identity"):
        restarted.get_manifest(manifest.manifest_id)


def test_sql_latest_report_tracks_a_repeated_identical_attempt(
    tmp_path: Path,
) -> None:
    service, manifest = _service_fixture(
        tolerance=Decimal("0.001"),
        reproduced_ending_equity=Decimal("100100.0005"),
    )
    successful = service.reproduce(manifest.manifest_id)
    failed = ReproductionReport(
        manifest_id=manifest.manifest_id,
        accepted_run_id=manifest.run_id,
        reproduced_run_id=None,
        status="reproducibility_invalid",
        numeric_tolerance=manifest.numeric_tolerance,
        reproduced_run_artifact_hash=None,
        checks=(
            ReproductionCheck(
                category="dependencies",
                status="mismatch",
                message="A pinned dependency changed.",
            ),
        ),
        mismatches=(
            ReproductionMismatch(
                code="dependency.code_identity_changed",
                path="strategy_run_specification.code_identity",
                expected=DIAGNOSTIC_CODE_IDENTITY,
                actual="changed-code.v2",
                message="Pinned diagnostic code identity changed.",
            ),
        ),
    )
    engine = create_engine(
        f"sqlite:///{tmp_path / 'latest-reproduction.db'}",
        future=True,
    )
    initialize_diagnostic_persistence(engine)
    repository = SqlReproductionRepository(engine)
    repository.add_manifests((manifest,))

    repository.save_report(successful)
    repository.save_report(failed)
    assert repository.latest_report(manifest.manifest_id) == failed

    repository.save_report(successful)

    assert repository.latest_report(manifest.manifest_id) == successful


def test_repositories_reject_report_run_or_tolerance_drift(
    tmp_path: Path,
) -> None:
    service, manifest = _service_fixture(
        tolerance=Decimal("0.001"),
        reproduced_ending_equity=Decimal("100100.0005"),
    )
    report = service.reproduce(manifest.manifest_id)
    wrong_run = replace(
        report,
        accepted_run_id="strategy-run-from-another-manifest",
    )
    wrong_tolerance = replace(
        report,
        numeric_tolerance=Decimal("0.1"),
    )
    memory_repository = InMemoryReproductionRepository()
    memory_repository.add_manifests((manifest,))
    engine = create_engine(
        f"sqlite:///{tmp_path / 'report-manifest-contract.db'}",
        future=True,
    )
    initialize_diagnostic_persistence(engine)
    sql_repository = SqlReproductionRepository(engine)
    sql_repository.add_manifests((manifest,))

    for repository in (memory_repository, sql_repository):
        with pytest.raises(
            ValueError,
            match="does not match its Reproduction Manifest",
        ):
            repository.save_report(wrong_run)
        with pytest.raises(
            ValueError,
            match="does not match its Reproduction Manifest",
        ):
            repository.save_report(wrong_tolerance)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO diagnostic_reproduction_attempts ("
                "attempt_id, manifest_id, status, report_json, created_at_utc"
                ") VALUES ("
                ":attempt_id, :manifest_id, :status, :report_json, "
                ":created_at_utc)"
            ),
            {
                "attempt_id": wrong_run.attempt_id,
                "manifest_id": manifest.manifest_id,
                "status": wrong_run.status,
                "report_json": json.dumps(
                    wrong_run.to_dict(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "created_at_utc": "2026-07-23T00:00:00+00:00",
            },
        )
    with pytest.raises(
        ValueError,
        match="does not match its Reproduction Manifest",
    ):
        sql_repository.latest_report(manifest.manifest_id)


def test_sql_manifest_batch_rolls_back_when_a_later_identity_collides(
    tmp_path: Path,
) -> None:
    specification = _specification()
    first = ReproductionManifest.create(
        specification=specification,
        run_artifact_hash="c" * 64,
        numeric_tolerance=Decimal("0.000001"),
        case_id="case-1",
        layer="baseline",
        evidence_package_id="diagnostic-evidence-" + "d" * 24,
        evidence_artifact_hash="d" * 64,
        measurement_artifact_hash="e" * 64,
        accepted_result=_accepted_result(),
    )
    second = ReproductionManifest.create(
        specification=specification,
        run_artifact_hash="c" * 64,
        numeric_tolerance=Decimal("0.000001"),
        case_id="case-1",
        layer="baseline",
        evidence_package_id="diagnostic-evidence-" + "f" * 24,
        evidence_artifact_hash="f" * 64,
        measurement_artifact_hash="1" * 64,
        accepted_result=_accepted_result(),
    )
    engine = create_engine(
        f"sqlite:///{tmp_path / 'atomic-reproduction.db'}",
        future=True,
    )
    initialize_diagnostic_persistence(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO diagnostic_reproduction_manifests ("
                "manifest_id, run_id, evidence_package_id, schema_version, "
                "numeric_tolerance, manifest_content_hash, manifest_json"
                ") VALUES ("
                ":manifest_id, :run_id, :evidence_package_id, "
                ":schema_version, :numeric_tolerance, "
                ":manifest_content_hash, :manifest_json)"
            ),
            {
                "manifest_id": second.manifest_id,
                "run_id": second.run_id,
                "evidence_package_id": second.evidence_package_id,
                "schema_version": "reproduction-manifest.v1",
                "numeric_tolerance": "0.000001",
                "manifest_content_hash": second.manifest_content_hash,
                "manifest_json": "{}",
            },
        )
    repository = SqlReproductionRepository(engine)

    with pytest.raises(ValueError, match="identity collision"):
        repository.add_manifests((first, second))

    with engine.connect() as connection:
        first_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM diagnostic_reproduction_manifests "
                "WHERE manifest_id = :manifest_id"
            ),
            {"manifest_id": first.manifest_id},
        ).scalar_one()
    assert first_count == 0
