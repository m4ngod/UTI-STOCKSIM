from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from strategy_diagnostics.diagnostic_evidence import DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION
from strategy_diagnostics.reproduction import REPRODUCTION_MANIFEST_SCHEMA_VERSION

from app.features import (
    ApprovedScenarioRecipeVersionId,
    DiagnosticEvidencePackageId,
    DiagnosticTaskConfigurationContentId,
    DiagnosticTaskId,
    FindingId,
    FormalDiagnosticCampaignId,
    ReproductionManifestId,
    SensitivityBreakpointId,
    StrategyRunId,
    SystemHealthComponentImpactClassification,
    SystemHealthContextResolution,
    SystemHealthContext,
    SystemHealthDiagnosticContext,
    SystemHealthDiagnosticContextVersion,
    SystemHealthDiagnosticScope,
    SystemHealthImpactComponentIdentity,
    SystemHealthOverallClassification,
    DeterministicFakeSystemHealthAdapter,
    TaskHandleId,
    decode_system_health_diagnostic_context,
    encode_system_health_diagnostic_context,
)


def _exact_context() -> SystemHealthDiagnosticContext:
    return SystemHealthDiagnosticContext(
        task_id=DiagnosticTaskId("diagnostic-task-112"),
        task_revision=7,
        configuration_content_id=DiagnosticTaskConfigurationContentId(
            "sha256:" + "1" * 64
        ),
        task_handle_id=TaskHandleId("task-handle-112"),
        campaign_id=FormalDiagnosticCampaignId("campaign-112"),
        campaign_revision=5,
        run_id=StrategyRunId("run-112"),
        evidence_package_id=DiagnosticEvidencePackageId("evidence-112"),
        finding_id=FindingId("finding-112"),
        sensitivity_breakpoint_id=SensitivityBreakpointId("breakpoint-112"),
        reproduction_manifest_id=ReproductionManifestId("manifest-112"),
        approved_recipe_version_ids=(
            ApprovedScenarioRecipeVersionId("recipe-version-112"),
        ),
        evidence_format_version=DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION,
        manifest_format_version=REPRODUCTION_MANIFEST_SCHEMA_VERSION,
    )


def test_diagnostic_context_is_immutable_typed_versioned_and_optional() -> None:
    exact = _exact_context()
    no_current_task = SystemHealthContext()
    selected = SystemHealthContext(diagnostic=exact)

    assert no_current_task.diagnostic is None
    assert no_current_task.version == SystemHealthDiagnosticContextVersion(1, 0)
    assert selected.diagnostic is exact
    assert exact.version == SystemHealthDiagnosticContextVersion(major=1, minor=0)

    with pytest.raises(FrozenInstanceError):
        exact.task_revision = 8  # type: ignore[misc]
    with pytest.raises(TypeError, match="task_id"):
        SystemHealthDiagnosticContext(  # type: ignore[arg-type]
            task_id="diagnostic-task-112",
            task_revision=7,
            configuration_content_id=exact.configuration_content_id,
        )
    with pytest.raises(ValueError, match="campaign_revision"):
        SystemHealthDiagnosticContext(
            task_id=exact.task_id,
            task_revision=7,
            configuration_content_id=exact.configuration_content_id,
            campaign_id=exact.campaign_id,
        )
    with pytest.raises(ValueError, match="campaign_id"):
        SystemHealthDiagnosticContext(
            task_id=exact.task_id,
            task_revision=7,
            configuration_content_id=exact.configuration_content_id,
            run_id=exact.run_id,
        )


def test_diagnostic_context_safe_serialization_preserves_every_identity() -> None:
    exact = _exact_context()

    encoded = encode_system_health_diagnostic_context(exact)
    decoded = decode_system_health_diagnostic_context(encoded)

    assert decoded == exact
    assert "diagnostic-task-112" in encoded
    assert "task-handle-112" in encoded
    assert "campaign-112" in encoded
    assert "run-112" in encoded
    assert "evidence-112" in encoded
    assert "finding-112" in encoded
    assert "breakpoint-112" in encoded
    assert "manifest-112" in encoded
    assert "recipe-version-112" in encoded
    assert "display_name" not in encoded


@pytest.mark.parametrize(
    "payload",
    (
        "{}",
        '{"version":{"major":1,"minor":0},"task_id":"diagnostic-task-112"}',
        (
            '{"version":{"major":2,"minor":0},'
            '"task_id":"diagnostic-task-112","task_revision":1,'
            '"configuration_content_id":"sha256:' + "1" * 64 + '"}'
        ),
        (
            '{"version":{"major":1,"minor":0},'
            '"task_id":"diagnostic-task-112","task_revision":1,'
            '"configuration_content_id":"sha256:' + "1" * 64 + '",'
            '"display_name":"silently substitute me"}'
        ),
    ),
)
def test_diagnostic_context_decoder_fails_closed_for_partial_or_unknown_payloads(
    payload: str,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        decode_system_health_diagnostic_context(payload)


@pytest.mark.parametrize(
    "unsafe_task_id",
    (
        "C:/private/diagnostic-task-112",
        "select * from diagnostic_tasks",
        "DROP TABLE diagnostic_tasks",
        "diagnostic-task-112-secret:value",
        "diagnostic-task-112-password:value",
        "diagnostic-task-112-token=secret",
    ),
)
def test_diagnostic_context_rejects_path_sql_and_secret_identity_text(
    unsafe_task_id: str,
) -> None:
    exact = _exact_context()

    with pytest.raises(ValueError, match="safe redacted identity"):
        SystemHealthDiagnosticContext(
            task_id=DiagnosticTaskId(unsafe_task_id),
            task_revision=exact.task_revision,
            configuration_content_id=exact.configuration_content_id,
        )


def test_fake_projects_no_current_task_and_exact_typed_component_scope() -> None:
    feature = DeterministicFakeSystemHealthAdapter(initially_healthy=True)
    exact = _exact_context()
    try:
        no_current = feature.snapshot(SystemHealthContext())
        selected = feature.snapshot(SystemHealthContext(diagnostic=exact))

        assert no_current.diagnostic_context.resolution is (
            SystemHealthContextResolution.NO_CURRENT_TASK
        )
        assert no_current.diagnostic_context.requested is None
        assert no_current.overall_classification is (
            SystemHealthOverallClassification.HEALTHY
        )
        assert all(
            impact.classification
            is SystemHealthComponentImpactClassification.NOT_APPLICABLE
            for impact in no_current.component_impacts
        )

        assert selected.context.diagnostic is exact
        assert selected.diagnostic_context.requested is exact
        assert selected.diagnostic_context.resolution is (
            SystemHealthContextResolution.EXACT_MATCH
        )
        assert selected.overall_classification is (
            SystemHealthOverallClassification.HEALTHY
        )
        assert tuple(item.component for item in selected.component_impacts) == tuple(
            SystemHealthImpactComponentIdentity
        )
        assert all(item.revision == selected.revision for item in selected.component_impacts)
        persistence = next(
            item
            for item in selected.component_impacts
            if item.component
            is SystemHealthImpactComponentIdentity.DIAGNOSTIC_PERSISTENCE
        )
        assert SystemHealthDiagnosticScope.DIAGNOSTIC_TASK in persistence.affected_scope
        assert SystemHealthDiagnosticScope.TASK_HANDLE in persistence.affected_scope
        assert SystemHealthDiagnosticScope.FORMAL_CAMPAIGN in persistence.affected_scope
        assert SystemHealthDiagnosticScope.STRATEGY_RUN in persistence.affected_scope
        assert SystemHealthDiagnosticScope.DIAGNOSTIC_EVIDENCE in persistence.affected_scope
        assert SystemHealthDiagnosticScope.DIAGNOSTIC_FINDING in persistence.affected_scope
        assert SystemHealthDiagnosticScope.SENSITIVITY_BREAKPOINT in (
            persistence.affected_scope
        )
        assert SystemHealthDiagnosticScope.REPRODUCTION_MANIFEST in (
            persistence.affected_scope
        )
    finally:
        feature.close()


@pytest.mark.parametrize(
    ("advance", "resolution", "overall"),
    (
        (
            "advance_context_to_missing",
            SystemHealthContextResolution.MISSING,
            SystemHealthOverallClassification.CONTEXT_MISSING,
        ),
        (
            "advance_context_to_superseded",
            SystemHealthContextResolution.SUPERSEDED,
            SystemHealthOverallClassification.CONTEXT_SUPERSEDED,
        ),
        (
            "advance_context_to_incompatible",
            SystemHealthContextResolution.INCOMPATIBLE,
            SystemHealthOverallClassification.CONTEXT_INCOMPATIBLE,
        ),
        (
            "advance_context_to_failed",
            SystemHealthContextResolution.FAILED,
            SystemHealthOverallClassification.DIAGNOSTIC_FAILED,
        ),
        (
            "advance_context_to_completed",
            SystemHealthContextResolution.COMPLETED,
            SystemHealthOverallClassification.DIAGNOSTIC_COMPLETED,
        ),
    ),
)
def test_fake_projects_each_safe_context_resolution_explicitly(
    advance: str,
    resolution: SystemHealthContextResolution,
    overall: SystemHealthOverallClassification,
) -> None:
    feature = DeterministicFakeSystemHealthAdapter(initially_healthy=True)
    context = SystemHealthContext(diagnostic=_exact_context())
    try:
        getattr(feature, advance)()
        state = feature.snapshot(context)

        assert state.diagnostic_context.resolution is resolution
        assert state.overall_classification is overall
        assert state.diagnostic_context.terminal is (
            resolution
            in {
                SystemHealthContextResolution.FAILED,
                SystemHealthContextResolution.COMPLETED,
            }
        )
    finally:
        feature.close()


def test_diagnostic_terminal_state_and_system_degradation_remain_distinct() -> None:
    feature = DeterministicFakeSystemHealthAdapter(initially_healthy=True)
    context = SystemHealthContext(diagnostic=_exact_context())
    try:
        exact = feature.snapshot(context)
        feature.advance_to_degraded()
        degraded = feature.snapshot(context)

        assert degraded.revision > exact.revision
        assert degraded.diagnostic_context.resolution is (
            SystemHealthContextResolution.EXACT_MATCH
        )
        assert degraded.overall_classification is (
            SystemHealthOverallClassification.DEGRADED
        )
        assert any(
            item.classification
            is SystemHealthComponentImpactClassification.DEGRADED
            for item in degraded.component_impacts
        )

        feature.advance_context_to_completed()
        completed = feature.snapshot(context)
        feature.advance_to_unavailable()
        completed_with_degradation = feature.snapshot(context)

        assert completed_with_degradation.revision > completed.revision
        assert completed_with_degradation.diagnostic_context.resolution is (
            SystemHealthContextResolution.COMPLETED
        )
        assert completed_with_degradation.diagnostic_context.terminal is True
        assert completed_with_degradation.overall_classification is (
            SystemHealthOverallClassification.DIAGNOSTIC_COMPLETED
        )

        feature.advance_context_to_failed()
        failed = feature.snapshot(context)
        assert failed.overall_classification is (
            SystemHealthOverallClassification.DIAGNOSTIC_FAILED
        )
        assert failed.overall_classification is not (
            SystemHealthOverallClassification.UNAVAILABLE
        )
    finally:
        feature.close()


def test_context_switch_disposes_old_delivery_scope_and_close_suppresses_late_work() -> None:
    feature = DeterministicFakeSystemHealthAdapter(initially_healthy=True)
    first_context = SystemHealthContext(diagnostic=_exact_context())
    second_context = SystemHealthContext(
        diagnostic=SystemHealthDiagnosticContext(
            task_id=DiagnosticTaskId("diagnostic-task-112-second"),
            task_revision=1,
            configuration_content_id=DiagnosticTaskConfigurationContentId(
                "sha256:" + "2" * 64
            ),
        )
    )
    first_observed = []
    second_observed = []
    first = feature.subscribe(first_context, first_observed.append)
    second = feature.subscribe(second_context, second_observed.append)
    first_count = len(first_observed)
    second_count = len(second_observed)

    feature.advance_to_degraded()

    assert len(first_observed) == first_count
    assert len(second_observed) > second_count
    assert all(state.context == first_context for state in first_observed)
    assert all(state.context == second_context for state in second_observed)

    second.dispose()
    delivered_before_dispose = len(second_observed)
    feature.advance_to_healthy()
    assert len(second_observed) == delivered_before_dispose

    first.dispose()
    feature.close()
    feature.close()
    with pytest.raises(RuntimeError, match="closed"):
        feature.snapshot(second_context)


def test_context_format_versions_are_compared_by_the_health_projection() -> None:
    feature = DeterministicFakeSystemHealthAdapter(initially_healthy=True)
    incompatible = SystemHealthContext(
        diagnostic=SystemHealthDiagnosticContext(
            task_id=DiagnosticTaskId("diagnostic-task-format-112"),
            task_revision=1,
            configuration_content_id=DiagnosticTaskConfigurationContentId(
                "sha256:" + "3" * 64
            ),
            evidence_format_version="future-evidence-format-112",
            manifest_format_version="future-manifest-format-112",
        )
    )
    try:
        state = feature.snapshot(incompatible)

        assert state.diagnostic_context.resolution is (
            SystemHealthContextResolution.INCOMPATIBLE
        )
        assert state.overall_classification is (
            SystemHealthOverallClassification.CONTEXT_INCOMPATIBLE
        )
    finally:
        feature.close()
