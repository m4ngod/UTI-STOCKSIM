from dataclasses import FrozenInstanceError, fields, is_dataclass, replace
from datetime import datetime, timedelta, timezone

import pytest

from app.features import (
    Completeness,
    ApprovedScenarioRecipeId,
    DeterministicFakeEvidenceAndFindingsAdapter,
    EvidenceAvailability,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsFeature,
    EvidenceAndFindingsPresentationState,
    EvidenceComparisonId,
    EvidenceCoverage,
    EvidenceDimension,
    EvidenceRecordId,
    EvidenceAndFindingsSelection,
    EvidenceAndFindingsViewState,
    EVIDENCE_AND_FINDINGS_INTERFACE_VERSION,
    FormalDiagnosticCampaignId,
    Freshness,
    MarketScenarioId,
    ReproductionManifestId,
    StrategyRunId,
    StrategyUnderTestId,
    ViewPhase,
)
from app.app_context import build_app_context
from app.event_bridge import EventBridge


def test_feature_starts_with_an_explicit_immutable_loading_contract():
    feature: EvidenceAndFindingsFeature = (
        DeterministicFakeEvidenceAndFindingsAdapter()
    )
    context = EvidenceAndFindingsContext.no_selection()

    state = feature.snapshot(context)

    assert feature.interface_version == EVIDENCE_AND_FINDINGS_INTERFACE_VERSION
    assert feature.interface_version.render() == "1.0"
    assert isinstance(state, EvidenceAndFindingsViewState)
    assert state.interface_version == feature.interface_version
    assert state.revision == 1
    assert state.observed_at == datetime(2030, 1, 1, tzinfo=timezone.utc)
    assert state.freshness is Freshness.AWAITING_FIRST_STATE
    assert state.age == timedelta(0)
    assert state.freshness_threshold == timedelta(seconds=5)
    assert state.phase is ViewPhase.LOADING
    assert state.presentation is EvidenceAndFindingsPresentationState.LOADING
    assert state.completeness is Completeness.UNKNOWN
    assert state.last_reliable_data is None
    assert state.error is None
    assert isinstance(feature, EvidenceAndFindingsFeature)

    with pytest.raises(FrozenInstanceError):
        state.revision = 2  # type: ignore[misc]

    feature.close()
    feature.close()
    with pytest.raises(RuntimeError, match="closed"):
        feature.snapshot(context)


def _selected_context() -> EvidenceAndFindingsContext:
    return EvidenceAndFindingsContext.for_selection(
        EvidenceAndFindingsSelection(
            campaign_id=FormalDiagnosticCampaignId("FDC-001"),
            run_id=StrategyRunId("RUN-001"),
            strategy_id=StrategyUnderTestId("STRATEGY-MOMENTUM-001"),
            market_scenario_id=MarketScenarioId("SCENARIO-BASELINE"),
            approved_recipe_id=ApprovedScenarioRecipeId("RECIPE-001"),
            reproduction_manifest_id=ReproductionManifestId("RM-001"),
        )
    )


def _assert_no_mutable_or_mapping_values(value: object) -> None:
    assert not isinstance(value, (dict, list, set, bytearray))
    if isinstance(value, tuple):
        for item in value:
            _assert_no_mutable_or_mapping_values(item)
    elif is_dataclass(value):
        for field in fields(value):
            _assert_no_mutable_or_mapping_values(getattr(value, field.name))


def test_completed_script_is_multidimensional_citable_and_reproducible():
    feature = DeterministicFakeEvidenceAndFindingsAdapter()
    context = _selected_context()

    state = feature.advance_to_completed(context)
    data = state.last_reliable_data

    assert state.phase is ViewPhase.READY
    assert state.presentation is EvidenceAndFindingsPresentationState.READY
    assert state.completeness is Completeness.COMPLETE
    assert data is not None
    assert data.selection == context.selection
    assert data.selection.campaign_id.value == "FDC-001"
    assert data.selection.run_id.value == "RUN-001"
    assert data.selection.strategy_id.value == "STRATEGY-MOMENTUM-001"
    assert data.selection.market_scenario_id.value == "SCENARIO-BASELINE"
    assert data.selection.approved_recipe_id.value == "RECIPE-001"
    assert data.selection.reproduction_manifest_id.value == "RM-001"

    evidence = tuple(
        record
        for candidate in data.candidates
        for record in candidate.evidence
    )
    assert {record.coverage for record in evidence} == {
        EvidenceCoverage.BASELINE,
        EvidenceCoverage.ISOLATED_SENSITIVITY,
        EvidenceCoverage.COMPOUND_SCENARIO,
        EvidenceCoverage.QUICK_EXPERIMENT,
    }
    assert {record.dimension for record in evidence} >= {
        EvidenceDimension.RETURN,
        EvidenceDimension.RISK,
        EvidenceDimension.EXECUTION,
        EvidenceDimension.EXPOSURE,
        EvidenceDimension.STABILITY,
        EvidenceDimension.DOMAIN,
    }
    quick = [
        record
        for record in evidence
        if record.coverage is EvidenceCoverage.QUICK_EXPERIMENT
    ]
    assert quick
    assert all(
        record.counts_toward_formal_completeness is False
        for record in quick
    )
    assert all(
        record.availability is EvidenceAvailability.COMPLETE
        for record in evidence
    )

    evidence_ids = {record.identity for record in evidence}
    findings = tuple(
        finding
        for candidate in data.candidates
        for finding in candidate.findings
    )
    assert findings
    assert all(set(finding.evidence_ids) <= evidence_ids for finding in findings)
    comparisons = tuple(
        comparison
        for candidate in data.candidates
        for comparison in candidate.comparisons
    )
    comparison_ids = {comparison.identity for comparison in comparisons}
    assert comparisons
    assert all(
        comparison.reference_evidence_id in evidence_ids
        and comparison.observed_evidence_id in evidence_ids
        for comparison in comparisons
    )
    assert all(
        set(finding.comparison_ids) <= comparison_ids
        for finding in findings
    )
    assert all(finding.comparison_ids for finding in findings)
    assert all(
        (record.comparison_evidence_id is None)
        == (record.comparison_value is None)
        for record in evidence
    )
    assert all(
        record.comparison_evidence_id in evidence_ids
        for record in evidence
        if record.comparison_evidence_id is not None
    )
    assert any(finding.failure_reason for finding in findings)
    assert any(finding.sensitivity_breakpoints for finding in findings)
    assert all(
        set(breakpoint.evidence_ids) <= evidence_ids
        for finding in findings
        for breakpoint in finding.sensitivity_breakpoints
    )

    assumptions = tuple(
        item
        for candidate in data.candidates
        for item in candidate.execution_assumptions
    )
    assert any(
        item.requested_value != item.effective_value
        and item.override_reason
        for item in assumptions
    )
    assert all(
        candidate.provenance.artifact_hashes
        and candidate.provenance.source_run_ids
        and candidate.provenance.runner_version
        and candidate.provenance.build_version
        and candidate.provenance.dependencies
        for candidate in data.candidates
    )
    assert data.read_only_context.orders
    assert data.read_only_context.fills
    _assert_no_mutable_or_mapping_values(state)

    public_members = {
        name
        for name in dir(EvidenceAndFindingsFeature)
        if not name.startswith("_")
    }
    assert public_members == {
        "close",
        "interface_version",
        "snapshot",
        "subscribe",
    }

    feature.close()


def test_candidate_evidence_rejects_duplicate_graph_identities():
    feature = DeterministicFakeEvidenceAndFindingsAdapter()
    completed = feature.advance_to_completed(_selected_context())
    data = completed.last_reliable_data
    assert data is not None
    candidate = data.candidates[0]

    with pytest.raises(ValueError, match="evidence identities must be unique"):
        replace(
            candidate,
            evidence=(
                candidate.evidence[0],
                candidate.evidence[0],
                *candidate.evidence[2:],
            ),
        )
    with pytest.raises(
        ValueError,
        match="comparison identities must be unique",
    ):
        replace(
            candidate,
            comparisons=(
                candidate.comparisons[0],
                candidate.comparisons[0],
                *candidate.comparisons[2:],
            ),
        )
    with pytest.raises(ValueError, match="finding identities must be unique"):
        replace(
            candidate,
            findings=(candidate.findings[0], candidate.findings[0]),
        )
    breakpoint = candidate.findings[0].sensitivity_breakpoints[0]
    duplicate_breakpoints = replace(
        candidate.findings[0],
        sensitivity_breakpoints=(breakpoint, breakpoint),
    )
    with pytest.raises(
        ValueError,
        match="sensitivity breakpoint identities must be unique",
    ):
        replace(
            candidate,
            findings=(duplicate_breakpoints, candidate.findings[1]),
        )

    feature.close()


def test_candidate_evidence_rejects_unpaired_or_dangling_graph_references():
    feature = DeterministicFakeEvidenceAndFindingsAdapter()
    completed = feature.advance_to_completed(_selected_context())
    data = completed.last_reliable_data
    assert data is not None
    candidate = data.candidates[0]
    missing_evidence_id = EvidenceRecordId("E-MISSING")
    missing_comparison_id = EvidenceComparisonId("CMP-MISSING")

    unpaired_evidence = replace(
        candidate.evidence[0],
        comparison_value="-1.0",
    )
    with pytest.raises(
        ValueError,
        match="comparison_evidence_id and comparison_value must be paired",
    ):
        replace(
            candidate,
            evidence=(unpaired_evidence, *candidate.evidence[1:]),
        )

    dangling_evidence = replace(
        candidate.evidence[6],
        comparison_evidence_id=missing_evidence_id,
    )
    with pytest.raises(ValueError, match="comparison_evidence_id"):
        replace(
            candidate,
            evidence=(
                *candidate.evidence[:6],
                dangling_evidence,
                *candidate.evidence[7:],
            ),
        )

    dangling_comparison = replace(
        candidate.comparisons[0],
        reference_evidence_id=missing_evidence_id,
    )
    with pytest.raises(ValueError, match="comparison evidence references"):
        replace(
            candidate,
            comparisons=(
                dangling_comparison,
                *candidate.comparisons[1:],
            ),
        )

    dangling_finding_evidence = replace(
        candidate.findings[0],
        evidence_ids=(missing_evidence_id,),
    )
    with pytest.raises(ValueError, match="[Ff]inding evidence references"):
        replace(
            candidate,
            findings=(
                dangling_finding_evidence,
                *candidate.findings[1:],
            ),
        )

    dangling_finding_comparison = replace(
        candidate.findings[0],
        comparison_ids=(missing_comparison_id,),
    )
    with pytest.raises(ValueError, match="[Ff]inding comparison references"):
        replace(
            candidate,
            findings=(
                dangling_finding_comparison,
                *candidate.findings[1:],
            ),
        )

    breakpoint = candidate.findings[0].sensitivity_breakpoints[0]
    dangling_breakpoint = replace(
        breakpoint,
        evidence_ids=(missing_evidence_id,),
    )
    dangling_breakpoint_finding = replace(
        candidate.findings[0],
        sensitivity_breakpoints=(dangling_breakpoint,),
    )
    with pytest.raises(
        ValueError,
        match="[Ss]ensitivity breakpoint evidence references",
    ):
        replace(
            candidate,
            findings=(
                dangling_breakpoint_finding,
                *candidate.findings[1:],
            ),
        )

    feature.close()


def test_stale_script_requires_prior_reliable_evidence():
    feature = DeterministicFakeEvidenceAndFindingsAdapter()
    context = _selected_context()

    with pytest.raises(ValueError, match="requires prior reliable data"):
        feature.advance_to_stale(context)

    feature.close()


def test_fake_scripts_honest_non_empty_failure_and_incomplete_states():
    feature = DeterministicFakeEvidenceAndFindingsAdapter()
    context = _selected_context()

    completed = feature.advance_to_completed(context)
    stale = feature.advance_to_stale(context)
    disconnected = feature.advance_to_disconnected(context)
    partial = feature.advance_to_partial(context)
    failed = feature.advance_to_failed(context)

    assert completed.presentation is EvidenceAndFindingsPresentationState.READY
    assert stale.freshness is Freshness.STALE
    assert stale.phase is ViewPhase.DEGRADED
    assert stale.last_reliable_data is completed.last_reliable_data
    assert disconnected.freshness is Freshness.DISCONNECTED
    assert disconnected.presentation is (
        EvidenceAndFindingsPresentationState.DISCONNECTED
    )
    assert disconnected.last_reliable_data is completed.last_reliable_data
    assert disconnected.error is not None
    assert partial.presentation is EvidenceAndFindingsPresentationState.READY
    assert partial.phase is ViewPhase.DEGRADED
    assert partial.completeness is Completeness.PARTIAL
    assert partial.error is not None
    partial_evidence = tuple(
        record
        for candidate in partial.last_reliable_data.candidates
        for record in candidate.evidence
    )
    assert {record.availability for record in partial_evidence} >= {
        EvidenceAvailability.PARTIAL,
        EvidenceAvailability.MISSING,
        EvidenceAvailability.UNAVAILABLE,
    }
    assert failed.presentation is EvidenceAndFindingsPresentationState.FAILED
    assert failed.phase is ViewPhase.FAILED
    assert failed.completeness is Completeness.PARTIAL
    assert failed.error is not None
    assert any(
        record.availability is EvidenceAvailability.FAILED
        for candidate in failed.last_reliable_data.candidates
        for record in candidate.evidence
    )
    assert all(
        state.presentation is not EvidenceAndFindingsPresentationState.EMPTY
        for state in (stale, disconnected, partial, failed)
    )

    empty_context = EvidenceAndFindingsContext.no_selection()
    empty = feature.advance_to_empty(empty_context)
    assert empty.presentation is EvidenceAndFindingsPresentationState.EMPTY
    assert empty.completeness is Completeness.EMPTY
    assert empty.last_reliable_data is None
    feature.close()


def test_subscription_delivers_revisions_and_disposes_idempotently():
    feature = DeterministicFakeEvidenceAndFindingsAdapter()
    context = _selected_context()
    delivered: list[EvidenceAndFindingsViewState] = []

    subscription = feature.subscribe(context, delivered.append)
    feature.advance_to_completed(context)
    feature.advance_to_partial(context)

    assert [state.revision for state in delivered] == [1, 2, 3]
    subscription.dispose()
    subscription.dispose()
    feature.advance_to_failed(context)
    assert [state.revision for state in delivered] == [1, 2, 3]
    assert subscription.disposed is True

    second = feature.subscribe(context, lambda _: None)
    feature.close()
    feature.close()
    assert second.disposed is True


def test_app_context_composes_fake_evidence_and_preserves_route_identity(
    tmp_path,
    monkeypatch,
):
    identities = {
        "STOCKSIM_FRONTEND_V2_CAMPAIGN_ID": "FDC-001",
        "STOCKSIM_FRONTEND_V2_RUN_ID": "RUN-001",
        "STOCKSIM_FRONTEND_V2_STRATEGY_ID": "STRATEGY-MOMENTUM-001",
        "STOCKSIM_FRONTEND_V2_MARKET_SCENARIO_ID": "SCENARIO-BASELINE",
        "STOCKSIM_FRONTEND_V2_APPROVED_RECIPE_ID": "RECIPE-001",
        "STOCKSIM_FRONTEND_V2_REPRODUCTION_MANIFEST_ID": "RM-001",
    }
    for name, value in identities.items():
        monkeypatch.setenv(name, value)

    composed = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        event_bridge=EventBridge(subscribe_backend=False),
    )

    assert isinstance(
        composed.evidence_and_findings_feature,
        DeterministicFakeEvidenceAndFindingsAdapter,
    )
    selection = composed.evidence_and_findings_context.selection
    assert selection is not None
    assert selection.campaign_id.value == "FDC-001"
    assert selection.run_id.value == "RUN-001"
    assert selection.strategy_id.value == "STRATEGY-MOMENTUM-001"
    assert selection.market_scenario_id.value == "SCENARIO-BASELINE"
    assert selection.approved_recipe_id.value == "RECIPE-001"
    assert selection.reproduction_manifest_id.value == "RM-001"

    composed.run_monitoring_feature.close()
    composed.evidence_and_findings_feature.close()


def test_partial_route_identity_is_preserved_without_inventing_metadata(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2_CAMPAIGN_ID", "FDC-PARTIAL")
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2_RUN_ID", "RUN-PARTIAL")
    for name in (
        "STOCKSIM_FRONTEND_V2_STRATEGY_ID",
        "STOCKSIM_FRONTEND_V2_MARKET_SCENARIO_ID",
        "STOCKSIM_FRONTEND_V2_APPROVED_RECIPE_ID",
        "STOCKSIM_FRONTEND_V2_REPRODUCTION_MANIFEST_ID",
    ):
        monkeypatch.delenv(name, raising=False)

    composed = build_app_context(
        settings_path=str(tmp_path / "partial-settings.json"),
        run_monitoring_mode="fake",
        event_bridge=EventBridge(subscribe_backend=False),
    )

    selection = composed.evidence_and_findings_context.selection
    assert selection is not None
    assert selection.campaign_id.value == "FDC-PARTIAL"
    assert selection.run_id.value == "RUN-PARTIAL"
    assert selection.strategy_id is None
    assert selection.market_scenario_id is None
    assert selection.approved_recipe_id is None
    assert selection.reproduction_manifest_id is None
    composed.run_monitoring_feature.close()
    composed.evidence_and_findings_feature.close()


def test_production_live_composition_does_not_mount_the_fake_evidence_route(
    tmp_path,
):
    composed = build_app_context(
        settings_path=str(tmp_path / "live-settings.json"),
        run_monitoring_mode="live",
        event_bridge=EventBridge(subscribe_backend=False),
    )

    assert composed.evidence_and_findings_feature is None
    composed.run_monitoring_feature.close()


def test_selection_rejects_swapped_identity_wrappers():
    with pytest.raises(TypeError, match="campaign_id"):
        EvidenceAndFindingsSelection(
            campaign_id=StrategyRunId("RUN-WRONG"),  # type: ignore[arg-type]
            run_id=StrategyRunId("RUN-001"),
            strategy_id=StrategyUnderTestId("STRATEGY-001"),
            market_scenario_id=MarketScenarioId("SCENARIO-001"),
            approved_recipe_id=ApprovedScenarioRecipeId("RECIPE-001"),
            reproduction_manifest_id=ReproductionManifestId("RM-001"),
        )
