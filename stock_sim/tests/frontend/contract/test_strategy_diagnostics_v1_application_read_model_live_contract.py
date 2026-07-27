from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, text

from app.features import (
    ApplicationReadAvailability,
    ApplicationReadModelVersion,
    DiagnosticEvidencePackageId,
    EvidenceAndFindingsContext,
    FormalDiagnosticCampaignId,
    LiveStrategyDiagnosticsV1ApplicationAdapter,
    ReproductionManifestId,
    StrategyDiagnosticsV1ApplicationReadModel,
    StrategyRunId,
    StrategyUnderTestId,
    V1JourneySelector,
)
from strategy_diagnostics import create_diagnostics_application
from strategy_diagnostics.diagnostic_evidence_storage import (
    JsonDiagnosticEvidenceArtifactStore,
)
from strategy_diagnostics.formal_diagnostic_campaigns import (
    SqlDiagnosticCampaignRepository,
)
from strategy_diagnostics.market_paths import InMemoryMarketPathArtifactStore
from strategy_diagnostics.strategy_runs import (
    SqlStrategyRunRepository,
    _LedgerPosition,
    _StrategyRunState,
)
from tests.strategy_diagnostics.test_diagnostic_evidence import (
    _formal_campaign,
    _profiles,
)

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _persist_formal_v1(database_path: Path, artifact_root: Path):
    engine = create_engine(f"sqlite:///{database_path}", future=True)
    paths = InMemoryMarketPathArtifactStore()
    evidence_store = JsonDiagnosticEvidenceArtifactStore(artifact_root)
    application = create_diagnostics_application(
        artifact_store=paths,
        evidence_artifact_store=evidence_store,
    )
    application.start()
    application.initialize_persistence(engine)

    campaign, executor = _formal_campaign()
    for path in executor.paths.values():
        paths.put(path)
    SqlDiagnosticCampaignRepository(engine).add(campaign)
    run_repository = SqlStrategyRunRepository(engine)
    snapshots = {}
    for case in campaign.cases:
        outcome = case.attempts[-1].campaign
        assert outcome is not None
        for member in outcome.members:
            snapshot = member.snapshot
            assert snapshot is not None
            if snapshot.run_id in snapshots:
                continue
            snapshots[snapshot.run_id] = snapshot
            run_repository.add(
                _StrategyRunState(
                    specification=snapshot.specification,
                    status=snapshot.status,
                    next_node_index=2,
                    decision_times=snapshot.decision_times,
                    orders=snapshot.orders,
                    fills=snapshot.fills,
                    cash=snapshot.cash,
                    positions=tuple(
                        _LedgerPosition(
                            instrument=position.instrument,
                            shares=position.shares,
                            total_cost=(
                                position.average_cost * position.shares
                            ),
                        )
                        for position in snapshot.positions
                    ),
                    equity_curve=snapshot.equity_curve,
                    ptrade_runtime_state=None,
                    ptrade_audit=snapshot.ptrade_audit,
                    current_simulation_time=snapshot.current_simulation_time,
                    failure_code=snapshot.failure_code,
                    failure_message=snapshot.failure_message,
                    run_artifact_hash=snapshot.run_artifact_hash,
                )
            )

    package = application.build_diagnostic_evidence(
        campaign.campaign_id,
        guardrail_profiles=_profiles(),
    )
    manifests = application.reproduction_manifests(package.evidence_package_id)
    selected_manifest = manifests[0]
    selected_run = snapshots[selected_manifest.run_id]
    engine.dispose()

    reopened_engine = create_engine(f"sqlite:///{database_path}", future=True)
    reopened = create_diagnostics_application(
        artifact_store=paths,
        evidence_artifact_store=evidence_store,
    )
    reopened.start()
    migration = reopened.initialize_persistence(reopened_engine)
    assert migration.current_revision == "0012_reproduction_manifests"
    return (
        reopened,
        reopened_engine,
        campaign,
        selected_run,
        package,
        selected_manifest,
    )


def test_live_adapter_reopens_file_backed_v1_and_preserves_exact_identities(
    tmp_path: Path,
) -> None:
    (
        application,
        engine,
        campaign,
        selected_run,
        package,
        manifest,
    ) = _persist_formal_v1(tmp_path / "diagnostics.sqlite3", tmp_path / "artifacts")
    adapter = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
        clock=lambda: NOW,
    )
    assert isinstance(adapter, StrategyDiagnosticsV1ApplicationReadModel)
    selector = V1JourneySelector(
        campaign_id=FormalDiagnosticCampaignId(campaign.campaign_id),
        run_id=StrategyRunId(selected_run.run_id),
        evidence_package_id=DiagnosticEvidencePackageId(
            package.evidence_package_id
        ),
        manifest_id=ReproductionManifestId(manifest.manifest_id),
    )

    resolved = adapter.resolve_journey(selector)
    assert resolved.availability is ApplicationReadAvailability.READY
    assert resolved.value is not None
    assert resolved.value.evidence_package_id == selector.evidence_package_id
    assert (
        resolved.value.evidence_context.selection.reproduction_manifest_id
        == selector.manifest_id
    )

    run = adapter.read_run(resolved.value)
    assert run.availability is ApplicationReadAvailability.READY
    assert run.value is not None
    assert run.value.selection.run_id == selector.run_id
    assert run.value.strategy_id.value == selected_run.specification.strategy_id
    assert run.value.market_scenario_id == resolved.value.campaign_case_id
    assert run.value.reproduction_manifest_id == selector.manifest_id
    assert not run.value.capabilities.can_pause
    assert not run.value.capabilities.can_resume
    assert not run.value.capabilities.can_cancel

    evidence = adapter.read_evidence(resolved.value)
    assert evidence.availability is ApplicationReadAvailability.READY
    assert evidence.value is not None
    assert evidence.value.evidence_package_id == selector.evidence_package_id
    metric_ids = {
        record.identity.value
        for candidate in evidence.value.candidates
        for record in candidate.evidence
    }
    comparison_ids = {
        comparison.identity.value
        for candidate in evidence.value.candidates
        for comparison in candidate.comparisons
    }
    finding_ids = {
        finding.identity.value
        for candidate in evidence.value.candidates
        for finding in candidate.findings
    }
    sealed = package.sealed_payload()
    assert metric_ids == {item["metric_id"] for item in sealed["metrics"]}
    assert comparison_ids == {
        item["comparison_id"] for item in sealed["comparisons"]
    }
    assert finding_ids == {
        item["finding_id"] for item in sealed["diagnostic_findings"]
    }
    engine.dispose()


def test_live_adapter_tokens_are_semantic_and_errors_are_sanitized(
    tmp_path: Path,
) -> None:
    (
        application,
        engine,
        campaign,
        selected_run,
        package,
        manifest,
    ) = _persist_formal_v1(tmp_path / "diagnostics.sqlite3", tmp_path / "artifacts")
    clock_state = [NOW]
    adapter = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
        clock=lambda: clock_state[0],
    )
    selector = V1JourneySelector(
        campaign_id=FormalDiagnosticCampaignId(campaign.campaign_id),
        run_id=StrategyRunId(selected_run.run_id),
        evidence_package_id=DiagnosticEvidencePackageId(
            package.evidence_package_id
        ),
        manifest_id=ReproductionManifestId(manifest.manifest_id),
    )

    first = adapter.resolve_journey(selector)
    assert first.value is not None
    first_run = adapter.read_run(first.value)
    clock_state[0] = NOW + timedelta(days=1)
    second = adapter.resolve_journey(selector)
    assert second.value is not None
    second_run = adapter.read_run(second.value)
    assert first.source_token == second.source_token
    assert first.source_observed_at == NOW
    assert second.source_observed_at == NOW + timedelta(days=1)
    assert first_run.source_token == second_run.source_token
    assert first_run.source_observed_at == NOW
    assert second_run.source_observed_at == NOW + timedelta(days=1)

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_reproduction_manifests "
                "SET manifest_content_hash = :changed "
                "WHERE manifest_id = :manifest_id"
            ),
            {"changed": "0" * 64, "manifest_id": manifest.manifest_id},
        )
    corrupted = adapter.resolve_journey(selector)
    assert corrupted.availability is ApplicationReadAvailability.FAILED
    assert corrupted.error is not None
    assert corrupted.error.code == "strategy_diagnostics_integrity_failed"
    assert not corrupted.error.retryable
    assert "sqlite" not in corrupted.error.message.casefold()
    assert str(tmp_path) not in corrupted.error.message
    assert corrupted.source_token != first.source_token
    engine.dispose()


def test_live_adapter_rejects_forged_resolved_journey_identities(
    tmp_path: Path,
) -> None:
    application, engine, campaign, selected_run, package, manifest = (
        _persist_formal_v1(
            tmp_path / "diagnostics.sqlite3",
            tmp_path / "artifacts",
        )
    )
    adapter = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
        clock=lambda: NOW,
    )
    resolved = adapter.resolve_journey(
        V1JourneySelector(
            campaign_id=FormalDiagnosticCampaignId(campaign.campaign_id),
            run_id=StrategyRunId(selected_run.run_id),
            evidence_package_id=DiagnosticEvidencePackageId(
                package.evidence_package_id
            ),
            manifest_id=ReproductionManifestId(manifest.manifest_id),
        )
    )
    assert resolved.value is not None
    evidence_selection = resolved.value.evidence_context.selection
    assert evidence_selection is not None
    forged = replace(
        resolved.value,
        evidence_context=EvidenceAndFindingsContext.for_selection(
            replace(
                evidence_selection,
                strategy_id=StrategyUnderTestId("forged-strategy"),
            )
        ),
    )

    for result in (adapter.read_run(forged), adapter.read_evidence(forged)):
        assert result.availability is ApplicationReadAvailability.FAILED
        assert result.error is not None
        assert result.error.code == "strategy_diagnostics_identity_mismatch"
        assert not result.error.retryable
    engine.dispose()


def test_live_adapter_treats_missing_sealed_manifest_as_integrity_failure(
    tmp_path: Path,
) -> None:
    application, engine, campaign, selected_run, package, manifest = (
        _persist_formal_v1(
            tmp_path / "diagnostics.sqlite3",
            tmp_path / "artifacts",
        )
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM diagnostic_reproduction_manifests "
                "WHERE manifest_id = :manifest_id"
            ),
            {"manifest_id": manifest.manifest_id},
        )
    adapter = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
        clock=lambda: NOW,
    )
    result = adapter.resolve_journey(
        V1JourneySelector(
            campaign_id=FormalDiagnosticCampaignId(campaign.campaign_id),
            run_id=StrategyRunId(selected_run.run_id),
            evidence_package_id=DiagnosticEvidencePackageId(
                package.evidence_package_id
            ),
        )
    )

    assert result.availability is ApplicationReadAvailability.FAILED
    assert result.error is not None
    assert result.error.code == "strategy_diagnostics_integrity_failed"
    assert not result.error.retryable
    engine.dispose()


def test_live_reads_classify_post_resolution_artifact_corruption_as_integrity(
    tmp_path: Path,
) -> None:
    application, engine, campaign, selected_run, package, manifest = (
        _persist_formal_v1(
            tmp_path / "diagnostics.sqlite3",
            tmp_path / "artifacts",
        )
    )
    adapter = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
        clock=lambda: NOW,
    )
    resolved = adapter.resolve_journey(
        V1JourneySelector(
            campaign_id=FormalDiagnosticCampaignId(campaign.campaign_id),
            run_id=StrategyRunId(selected_run.run_id),
            evidence_package_id=DiagnosticEvidencePackageId(
                package.evidence_package_id
            ),
            manifest_id=ReproductionManifestId(manifest.manifest_id),
        )
    )
    assert resolved.value is not None
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_evidence_packages "
                "SET artifact_hash = :changed "
                "WHERE evidence_package_id = :evidence_package_id"
            ),
            {
                "changed": "d" * 64,
                "evidence_package_id": package.evidence_package_id,
            },
        )

    for result in (
        adapter.read_run(resolved.value),
        adapter.read_evidence(resolved.value),
    ):
        assert result.availability is ApplicationReadAvailability.FAILED
        assert result.error is not None
        assert result.error.code == "strategy_diagnostics_integrity_failed"
        assert not result.error.retryable
    engine.dispose()


def test_live_adapter_fails_closed_for_unknown_schema_and_ambiguity(
    tmp_path: Path,
) -> None:
    (
        application,
        engine,
        campaign,
        selected_run,
        _package,
        _manifest,
    ) = _persist_formal_v1(tmp_path / "diagnostics.sqlite3", tmp_path / "artifacts")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO diagnostic_schema_migrations "
                "(revision, applied_at_utc) VALUES (:revision, :applied)"
            ),
            {
                "revision": "9999_incompatible_major",
                "applied": NOW.isoformat(),
            },
        )
    adapter = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
        clock=lambda: NOW,
    )
    result = adapter.resolve_journey(
        V1JourneySelector(
            campaign_id=FormalDiagnosticCampaignId(campaign.campaign_id),
            run_id=StrategyRunId(selected_run.run_id),
        )
    )
    assert result.availability is ApplicationReadAvailability.FAILED
    assert result.error is not None
    assert result.error.code == "strategy_diagnostics_contract_incompatible"
    assert not result.error.retryable
    engine.dispose()


def test_live_adapter_rejects_implicit_ambiguous_evidence_selection(
    tmp_path: Path,
) -> None:
    (
        application,
        engine,
        campaign,
        selected_run,
        package,
        _manifest,
    ) = _persist_formal_v1(tmp_path / "diagnostics.sqlite3", tmp_path / "artifacts")
    with engine.begin() as connection:
        source = connection.execute(
            text(
                "SELECT campaign_id, schema_version, status, "
                "measurement_artifact_hash, artifact_hash "
                "FROM diagnostic_evidence_packages "
                "WHERE evidence_package_id = :evidence_package_id"
            ),
            {"evidence_package_id": package.evidence_package_id},
        ).mappings().one()
        connection.execute(
            text(
                "INSERT INTO diagnostic_evidence_packages ("
                "evidence_package_id, campaign_id, schema_version, status, "
                "measurement_artifact_hash, artifact_hash"
                ") VALUES ("
                ":evidence_package_id, :campaign_id, :schema_version, :status, "
                ":measurement_artifact_hash, :artifact_hash)"
            ),
            {
                **dict(source),
                "evidence_package_id": "diagnostic-evidence-ambiguous",
                "artifact_hash": "f" * 64,
            },
        )
    adapter = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
        clock=lambda: NOW,
    )
    result = adapter.resolve_journey(
        V1JourneySelector(
            campaign_id=FormalDiagnosticCampaignId(campaign.campaign_id),
            run_id=StrategyRunId(selected_run.run_id),
        )
    )

    assert result.availability is ApplicationReadAvailability.FAILED
    assert result.error is not None
    assert result.error.code == "diagnostic_evidence_selection_ambiguous"
    assert not result.error.retryable
    engine.dispose()


def test_live_adapter_rejects_evidence_artifact_corruption_as_integrity_failure(
    tmp_path: Path,
) -> None:
    (
        application,
        engine,
        campaign,
        selected_run,
        package,
        manifest,
    ) = _persist_formal_v1(tmp_path / "diagnostics.sqlite3", tmp_path / "artifacts")
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_evidence_packages "
                "SET artifact_hash = :changed "
                "WHERE evidence_package_id = :evidence_package_id"
            ),
            {
                "changed": "e" * 64,
                "evidence_package_id": package.evidence_package_id,
            },
        )
    adapter = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
        clock=lambda: NOW,
    )
    result = adapter.resolve_journey(
        V1JourneySelector(
            campaign_id=FormalDiagnosticCampaignId(campaign.campaign_id),
            run_id=StrategyRunId(selected_run.run_id),
            evidence_package_id=DiagnosticEvidencePackageId(
                package.evidence_package_id
            ),
            manifest_id=ReproductionManifestId(manifest.manifest_id),
        )
    )

    assert result.availability is ApplicationReadAvailability.FAILED
    assert result.error is not None
    assert result.error.code == "strategy_diagnostics_integrity_failed"
    assert not result.error.retryable
    engine.dispose()


def test_live_adapter_rejects_incompatible_interface_without_fallback(
    tmp_path: Path,
) -> None:
    (
        application,
        engine,
        campaign,
        selected_run,
        _package,
        _manifest,
    ) = _persist_formal_v1(tmp_path / "diagnostics.sqlite3", tmp_path / "artifacts")
    adapter = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
        clock=lambda: NOW,
        provider_version=ApplicationReadModelVersion(2, 0),
    )

    result = adapter.resolve_journey(
        V1JourneySelector(
            campaign_id=FormalDiagnosticCampaignId(campaign.campaign_id),
            run_id=StrategyRunId(selected_run.run_id),
        )
    )

    assert result.availability is ApplicationReadAvailability.FAILED
    assert result.error is not None
    assert result.error.code == "strategy_diagnostics_contract_incompatible"
    assert not result.error.retryable
    engine.dispose()


def test_live_adapter_converts_transient_application_failure_without_leaking(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (
        application,
        engine,
        campaign,
        selected_run,
        _package,
        _manifest,
    ) = _persist_formal_v1(tmp_path / "diagnostics.sqlite3", tmp_path / "artifacts")
    leaked = f"SELECT secret FROM table at {tmp_path}"

    def fail_read(_campaign_id: str):
        raise RuntimeError(leaked)

    monkeypatch.setattr(application, "diagnostic_campaign_status", fail_read)
    adapter = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
        clock=lambda: NOW,
    )
    result = adapter.resolve_journey(
        V1JourneySelector(
            campaign_id=FormalDiagnosticCampaignId(campaign.campaign_id),
            run_id=StrategyRunId(selected_run.run_id),
        )
    )

    assert result.availability is ApplicationReadAvailability.FAILED
    assert result.error is not None
    assert result.error.code == "strategy_diagnostics_read_failed"
    assert result.error.retryable
    assert leaked not in result.error.message
    assert str(tmp_path) not in result.error.message
    engine.dispose()
