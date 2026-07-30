from __future__ import annotations

import inspect
from collections import deque
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timezone
from typing import Any, TypeVar, get_args, get_origin, get_type_hints

import pytest

from app.features import (
    ACTIVE_FEATURE_INTERFACES,
    APPLICATION_READ_MODEL_INTERFACE_VERSION,
    EVIDENCE_AND_FINDINGS_INTERFACE_VERSION,
    ApplicationReadAvailability,
    ApplicationReadError,
    ApplicationReadErrorCode,
    ApplicationReadModelVersion,
    ApplicationReadResult,
    ApprovedScenarioRecipeId,
    CandidateEvidence,
    DependencyProvenance,
    DiagnosticCandidateId,
    DiagnosticEvidencePackageId,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsData,
    EvidenceAndFindingsSelection,
    EvidenceComparison,
    EvidenceComparisonId,
    EvidenceCoverage,
    EvidenceDimension,
    EvidenceProvenance,
    EvidenceRecord,
    EvidenceRecordId,
    FormalDiagnosticCampaignId,
    MarketScenarioId,
    ReadOnlyEvidenceContext,
    ReproductionManifestId,
    ResolvedV1Journey,
    RunMonitoringContext,
    RunMonitoringSelection,
    SourceRevisionToken,
    StrategyDiagnosticsV1ApplicationReadModel,
    StrategyRunId,
    StrategyUnderTestId,
    V1JourneySelector,
)
from app.features.evidence_and_findings import EvidenceAvailability

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _record(identity: str) -> EvidenceRecord:
    return EvidenceRecord(
        identity=EvidenceRecordId(identity),
        coverage=EvidenceCoverage.BASELINE,
        dimension=EvidenceDimension.RETURN,
        label=identity,
        value="1",
        comparison_evidence_id=None,
        comparison_value=None,
        unit="ratio",
        availability=EvidenceAvailability.COMPLETE,
        interpretation="Persisted V1 evidence.",
    )


def test_application_read_model_contract_is_exact_typed_and_frozen() -> None:
    assert APPLICATION_READ_MODEL_INTERFACE_VERSION == ApplicationReadModelVersion(1, 0)
    assert EVIDENCE_AND_FINDINGS_INTERFACE_VERSION.render() == "1.1"
    assert tuple(item.name.value for item in ACTIVE_FEATURE_INTERFACES) == (
        "RunMonitoringFeature",
        "EvidenceAndFindingsFeature",
    )

    selector = V1JourneySelector(
        campaign_id=FormalDiagnosticCampaignId("campaign-1"),
        run_id=StrategyRunId("run-1"),
    )
    with pytest.raises(FrozenInstanceError):
        selector.run_id = StrategyRunId("run-2")  # type: ignore[misc]

    protocol_members = {
        name
        for name, value in inspect.getmembers(
            StrategyDiagnosticsV1ApplicationReadModel
        )
        if (
            name == "interface_version"
            or inspect.isfunction(value)
            and not name.startswith("_")
        )
    }
    assert protocol_members == {
        "interface_version",
        "resolve_journey",
        "read_run",
        "read_evidence",
    }
    assert not any(
        name.startswith(("get_", "list_"))
        for name in protocol_members
    )

    public_graph = _transitive_public_interface_graph()
    assert Any not in public_graph
    assert dict not in public_graph
    assert Mapping not in public_graph
    for public_type in public_graph:
        module = getattr(public_type, "__module__", "")
        name = getattr(public_type, "__name__", "")
        assert not module.startswith(
            (
                "strategy_diagnostics",
                "sqlalchemy",
                "PySide6",
                "_thread",
                "asyncio",
                "concurrent",
                "multiprocessing",
                "queue",
                "threading",
            )
        )
        assert name != "EventBridge"
        assert "Repository" not in name


def _transitive_public_interface_graph() -> set[object]:
    pending: deque[object] = deque()
    for name, member in inspect.getmembers(
        StrategyDiagnosticsV1ApplicationReadModel
    ):
        if name.startswith("_"):
            continue
        if isinstance(member, property) and member.fget is not None:
            pending.extend(get_type_hints(member.fget).values())
        elif inspect.isfunction(member):
            pending.extend(get_type_hints(member).values())

    visited: set[object] = set()
    while pending:
        public_type = pending.popleft()
        if public_type in visited:
            continue
        visited.add(public_type)
        origin = get_origin(public_type)
        if origin is not None:
            pending.append(origin)
            pending.extend(get_args(public_type))
            continue
        if isinstance(public_type, TypeVar):
            if public_type.__bound__ is not None:
                pending.append(public_type.__bound__)
            pending.extend(public_type.__constraints__)
            continue
        if (
            inspect.isclass(public_type)
            and getattr(public_type, "__module__", "").startswith("app.features")
        ):
            pending.extend(get_type_hints(public_type).values())
    return visited


def test_application_read_result_requires_coherent_typed_state() -> None:
    error = ApplicationReadError(
        code=ApplicationReadErrorCode.READ_FAILED,
        message="The diagnostics source could not be read.",
        retryable=True,
    )
    assert get_type_hints(ApplicationReadError)["code"] is ApplicationReadErrorCode
    with pytest.raises(TypeError, match="ApplicationReadErrorCode"):
        ApplicationReadError(
            code="strategy_diagnostics_read_failed",  # type: ignore[arg-type]
            message="Untyped error codes must fail closed.",
            retryable=True,
        )
    result = ApplicationReadResult[ResolvedV1Journey](
        availability=ApplicationReadAvailability.FAILED,
        source_token=SourceRevisionToken("a" * 64),
        source_observed_at=NOW,
        value=None,
        error=error,
    )
    assert result.error == error

    with pytest.raises(ValueError, match="timezone-aware"):
        ApplicationReadResult[ResolvedV1Journey](
            availability=ApplicationReadAvailability.FAILED,
            source_token=SourceRevisionToken("b" * 64),
            source_observed_at=datetime(2030, 1, 1),  # noqa: DTZ001
            value=None,
            error=error,
        )


def test_evidence_1_1_preserves_package_identity_and_multiple_edges() -> None:
    control_a = _record("metric-control-a")
    control_b = _record("metric-control-b")
    observed = _record("metric-observed")
    comparisons = (
        EvidenceComparison(
            identity=EvidenceComparisonId("comparison-a"),
            label="A to observed",
            reference_evidence_id=control_a.identity,
            observed_evidence_id=observed.identity,
            interpretation="First persisted V1 edge.",
        ),
        EvidenceComparison(
            identity=EvidenceComparisonId("comparison-b"),
            label="B to observed",
            reference_evidence_id=control_b.identity,
            observed_evidence_id=observed.identity,
            interpretation="Second persisted V1 edge.",
        ),
    )
    candidate = CandidateEvidence(
        identity=DiagnosticCandidateId("strategy@1"),
        label="strategy 1",
        evidence=(control_a, control_b, observed),
        comparisons=comparisons,
        findings=(),
        execution_assumptions=(),
        provenance=EvidenceProvenance(
            artifact_hashes=("sha256:" + "a" * 64,),
            source_run_ids=(StrategyRunId("run-1"),),
            runner_version="strategy-diagnostics-v1",
            build_version="test",
            dependencies=(
                DependencyProvenance(
                    name="manifest",
                    version="1",
                    artifact_hash="sha256:" + "b" * 64,
                ),
            ),
        ),
    )
    selection = EvidenceAndFindingsSelection(
        campaign_id=FormalDiagnosticCampaignId("campaign-1"),
        run_id=StrategyRunId("run-1"),
        strategy_id=StrategyUnderTestId("strategy"),
        market_scenario_id=MarketScenarioId("case-1"),
        approved_recipe_id=ApprovedScenarioRecipeId("recipe-1"),
        reproduction_manifest_id=ReproductionManifestId("manifest-1"),
    )
    data = EvidenceAndFindingsData(
        evidence_package_id=DiagnosticEvidencePackageId("package-1"),
        selection=selection,
        candidates=(candidate,),
        read_only_context=ReadOnlyEvidenceContext(
            market=(),
            account=(),
            positions=(),
            orders=(),
            fills=(),
        ),
    )

    assert data.evidence_package_id.value == "package-1"
    assert len(data.candidates[0].comparisons) == 2
    assert {
        comparison.reference_evidence_id
        for comparison in data.candidates[0].comparisons
    } == {control_a.identity, control_b.identity}


def test_resolved_journey_contains_only_typed_frontend_contexts() -> None:
    selection = RunMonitoringSelection(
        campaign_id=FormalDiagnosticCampaignId("campaign-1"),
        run_id=StrategyRunId("run-1"),
    )
    evidence_selection = EvidenceAndFindingsSelection(
        campaign_id=selection.campaign_id,
        run_id=selection.run_id,
        strategy_id=StrategyUnderTestId("strategy"),
        market_scenario_id=MarketScenarioId("case-1"),
        approved_recipe_id=ApprovedScenarioRecipeId("recipe-1"),
        reproduction_manifest_id=ReproductionManifestId("manifest-1"),
    )
    journey = ResolvedV1Journey(
        run_context=RunMonitoringContext.for_run(selection),
        evidence_context=EvidenceAndFindingsContext.for_selection(
            evidence_selection
        ),
        evidence_package_id=DiagnosticEvidencePackageId("package-1"),
        campaign_case_id=MarketScenarioId("case-1"),
        campaign_layer=EvidenceCoverage.BASELINE,
    )

    assert tuple(field.name for field in fields(journey)) == (
        "run_context",
        "evidence_context",
        "evidence_package_id",
        "campaign_case_id",
        "campaign_layer",
    )
    assert journey.evidence_context.selection == evidence_selection
