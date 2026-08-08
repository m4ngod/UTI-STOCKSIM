from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone

from app.event_bridge import EventBridge
from app.features import (
    ApprovedScenarioRecipeVersionId,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    DiagnosticEvidencePackageId,
    DeterministicFakeSystemHealthAdapter,
    FindingId,
    LiveStrategyDiagnosticsV1ApplicationAdapter,
    LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter,
    LiveSystemHealthAdapter,
    ReproductionManifestId,
    StartFormalDiagnosticCampaign,
    StrategyRunId,
    SystemHealthContext,
    SystemHealthContextResolution,
    SystemHealthDiagnosticContext,
    SystemHealthDiagnosticContextVersion,
    SystemHealthOverallClassification,
    SystemHealthViewState,
    V1JourneySelector,
)
from app.features.strategy_diagnostics_v1_read_model import (
    ApplicationReadAvailability,
    ApplicationReadError,
    ApplicationReadErrorCode,
    ApplicationReadResult,
)
from strategy_diagnostics.diagnostic_evidence import DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION
from strategy_diagnostics.diagnostic_evidence_storage import (
    JsonDiagnosticEvidenceArtifactStore,
)
from strategy_diagnostics.reproduction import REPRODUCTION_MANIFEST_SCHEMA_VERSION
from tests.frontend.contract.test_diagnostic_task_campaign_start_live_contract import (
    _approved_formal_task,
    _formal_live_stack,
)
from tests.frontend.contract.test_diagnostic_task_revision_approval_live_contract import (
    _read_task,
)
from tests.frontend.contract.test_diagnostic_task_failed_node_retry_live_contract import (
    _FailFirstDecisionPTradeHost,
)
from tests.frontend.contract.test_system_health_diagnostic_context_contract import (
    _exact_context,
)


NOW = datetime(2030, 1, 2, tzinfo=timezone.utc)


def _assert_live_fake_contextual_conformance(
    feature,
    *,
    exact: SystemHealthDiagnosticContext,
    missing: SystemHealthDiagnosticContext,
    superseded: SystemHealthDiagnosticContext,
    incompatible: SystemHealthDiagnosticContext,
    prepare: Callable[[str], None] | None = None,
):
    cases = (
        (
            "no_current_task",
            SystemHealthContext(),
            SystemHealthContextResolution.NO_CURRENT_TASK,
        ),
        (
            "exact_match",
            SystemHealthContext(diagnostic=exact),
            SystemHealthContextResolution.EXACT_MATCH,
        ),
        (
            "missing",
            SystemHealthContext(diagnostic=missing),
            SystemHealthContextResolution.MISSING,
        ),
        (
            "superseded",
            SystemHealthContext(diagnostic=superseded),
            SystemHealthContextResolution.SUPERSEDED,
        ),
        (
            "incompatible",
            SystemHealthContext(diagnostic=incompatible),
            SystemHealthContextResolution.INCOMPATIBLE,
        ),
        (
            "outer_incompatible",
            SystemHealthContext(
                version=SystemHealthDiagnosticContextVersion(2, 0),
            ),
            SystemHealthContextResolution.INCOMPATIBLE,
        ),
    )
    states = []
    for case, context, expected in cases:
        if prepare is not None:
            prepare(case)
        state = feature.snapshot(context)
        assert state.context == context
        assert state.diagnostic_context.requested == context.diagnostic
        assert state.diagnostic_context.resolution is expected
        assert all(item.revision == state.revision for item in state.component_impacts)
        states.append(state)
    assert tuple(item.revision for item in states) == tuple(
        sorted(item.revision for item in states)
    )
    assert len({item.revision for item in states}) == len(states)
    return tuple(states)


def _assert_terminal_context(
    feature,
    context: SystemHealthDiagnosticContext,
    *,
    resolution: SystemHealthContextResolution,
    overall: SystemHealthOverallClassification,
) -> SystemHealthViewState:
    state = feature.snapshot(SystemHealthContext(diagnostic=context))
    assert state.diagnostic_context.requested == context
    assert state.diagnostic_context.resolution is resolution
    assert state.diagnostic_context.terminal is True
    assert state.overall_classification is overall
    return state


def test_live_adapter_resolves_real_persisted_task_campaign_and_run_exactly(
    tmp_path,
) -> None:
    (
        _source,
        _artifact_store,
        engine,
        application,
        diagnostic_tasks_application,
        task_feature,
    ) = _formal_live_stack(tmp_path)
    approved = _approved_formal_task(task_feature)
    accepted = task_feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("system-health-start-112"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "system-health-start-idempotency-112"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert accepted.task_handle is not None
    running = _read_task(task_feature, approved.task_id)
    attempt = next(
        attempt
        for node in running.handoff.campaign_nodes
        for attempt in node.attempts
        if attempt.runs
    )
    run_id = attempt.runs[0].run_id
    exact = SystemHealthDiagnosticContext(
        task_id=running.task_id,
        task_revision=running.revision,
        configuration_content_id=running.configuration.content_identity,
        task_handle_id=accepted.task_handle.identity,
        campaign_id=running.handoff.campaign_id,
        campaign_revision=running.handoff.campaign_revision,
        run_id=run_id,
        approved_recipe_version_ids=tuple(
            item.recipe_version_id
            for item in running.configuration.campaign_case_selections
        ),
    )
    bridge = EventBridge(subscribe_backend=False)
    read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
        clock=lambda: NOW,
    )
    feature = LiveSystemHealthAdapter(
        application_health=LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
            application,
            clock=lambda: NOW,
        ),
        diagnostic_tasks_application=diagnostic_tasks_application,
        application_read_model=read_model,
        event_bridge=bridge,
        clock=lambda: NOW,
        sampling_interval=None,
    )
    try:
        states = _assert_live_fake_contextual_conformance(
            feature,
            exact=exact,
            missing=replace(exact, run_id=StrategyRunId("missing-run-112")),
            superseded=replace(
                exact,
                approved_recipe_version_ids=(
                    ApprovedScenarioRecipeVersionId("superseded-recipe-112"),
                ),
            ),
            incompatible=replace(
                exact,
                version=SystemHealthDiagnosticContextVersion(2, 0),
            ),
        )
        matched = states[1]
        assert matched.diagnostic_context.requested is exact
        assert matched.diagnostic_context.observed_task_revision == running.revision
        assert matched.diagnostic_context.observed_campaign_revision == (
            running.handoff.campaign_revision
        )
    finally:
        feature.close()
        task_feature.close()
        bridge.stop()
        engine.dispose()


def test_deterministic_fake_uses_the_same_contextual_conformance_body() -> None:
    feature = DeterministicFakeSystemHealthAdapter(initially_healthy=True)
    exact = _exact_context()
    transitions = {
        "no_current_task": feature.advance_context_to_exact,
        "exact_match": feature.advance_context_to_exact,
        "missing": feature.advance_context_to_missing,
        "superseded": feature.advance_context_to_superseded,
        "incompatible": feature.advance_context_to_exact,
        "outer_incompatible": feature.advance_context_to_exact,
    }
    try:
        _assert_live_fake_contextual_conformance(
            feature,
            exact=exact,
            missing=replace(exact, run_id=StrategyRunId("missing-run-112")),
            superseded=replace(
                exact,
                approved_recipe_version_ids=(
                    ApprovedScenarioRecipeVersionId("superseded-recipe-112"),
                ),
            ),
            incompatible=replace(
                exact,
                version=SystemHealthDiagnosticContextVersion(2, 0),
            ),
            prepare=lambda case: transitions[case](),
        )
    finally:
        feature.close()


def test_deterministic_fake_uses_the_same_terminal_context_body() -> None:
    feature = DeterministicFakeSystemHealthAdapter(initially_healthy=True)
    exact = _exact_context()
    try:
        feature.advance_context_to_completed()
        _assert_terminal_context(
            feature,
            exact,
            resolution=SystemHealthContextResolution.COMPLETED,
            overall=SystemHealthOverallClassification.DIAGNOSTIC_COMPLETED,
        )
        feature.advance_context_to_failed()
        _assert_terminal_context(
            feature,
            exact,
            resolution=SystemHealthContextResolution.FAILED,
            overall=SystemHealthOverallClassification.DIAGNOSTIC_FAILED,
        )
    finally:
        feature.close()


def test_live_adapter_preserves_completed_full_identity_graph_and_manifest_lineage(
    tmp_path,
    monkeypatch,
) -> None:
    evidence_store = JsonDiagnosticEvidenceArtifactStore(tmp_path / "evidence")
    (
        _source,
        _artifact_store,
        engine,
        application,
        diagnostic_tasks_application,
        task_feature,
    ) = _formal_live_stack(
        tmp_path,
        evidence_artifact_store=evidence_store,
    )
    approved = _approved_formal_task(task_feature)
    accepted = task_feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("system-health-complete-start-112"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "system-health-complete-idempotency-112"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    assert accepted.affected_campaign_id is not None
    application.resume_diagnostic_campaign(accepted.affected_campaign_id.value)
    task_result = diagnostic_tasks_application.read_diagnostic_task(approved.task_id)
    assert task_result.task is not None
    completed = task_result.task
    assert completed.campaign_handoff is not None
    handoff = completed.campaign_handoff
    assert handoff.evidence_package_id is not None
    assert handoff.reproduction_manifest_id is not None
    read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
        clock=lambda: NOW,
    )
    exact_graph = None
    for selected_run in (
        run
        for node in handoff.campaign_nodes
        for attempt in node.attempts
        for run in attempt.runs
        if run.reproduction_manifest_id is not None
    ):
        resolved = read_model.resolve_journey(
            V1JourneySelector(
                campaign_id=handoff.campaign_id,
                run_id=selected_run.run_id,
                evidence_package_id=handoff.evidence_package_id,
                manifest_id=selected_run.reproduction_manifest_id,
            )
        )
        if resolved.value is None:
            continue
        evidence_result = read_model.read_evidence(resolved.value)
        if evidence_result.value is None:
            continue
        finding = next(
            (
                finding
                for candidate in evidence_result.value.candidates
                for finding in candidate.findings
            ),
            None,
        )
        if finding is not None:
            exact_graph = (selected_run, finding)
            break
    assert exact_graph is not None
    selected_run, finding = exact_graph
    breakpoint = next(iter(finding.sensitivity_breakpoints), None)
    full = SystemHealthDiagnosticContext(
        task_id=completed.task_id,
        task_revision=completed.revision,
        configuration_content_id=completed.configuration.content_identity,
        task_handle_id=accepted.task_handle.identity,
        campaign_id=handoff.campaign_id,
        campaign_revision=handoff.campaign_revision,
        run_id=selected_run.run_id,
        evidence_package_id=handoff.evidence_package_id,
        finding_id=finding.identity,
        sensitivity_breakpoint_id=(None if breakpoint is None else breakpoint.identity),
        reproduction_manifest_id=selected_run.reproduction_manifest_id,
        approved_recipe_version_ids=tuple(
            item.recipe_version_id
            for item in completed.configuration.campaign_case_selections
        ),
        evidence_format_version=DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION,
        manifest_format_version=REPRODUCTION_MANIFEST_SCHEMA_VERSION,
    )
    bridge = EventBridge(subscribe_backend=False)
    feature = LiveSystemHealthAdapter(
        application_health=LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
            application,
            clock=lambda: NOW,
            current_manifest_format_provider=(
                lambda: REPRODUCTION_MANIFEST_SCHEMA_VERSION
            ),
        ),
        diagnostic_tasks_application=diagnostic_tasks_application,
        application_read_model=read_model,
        event_bridge=bridge,
        clock=lambda: NOW,
        sampling_interval=None,
    )
    try:
        terminal = _assert_terminal_context(
            feature,
            full,
            resolution=SystemHealthContextResolution.COMPLETED,
            overall=SystemHealthOverallClassification.DIAGNOSTIC_COMPLETED,
        )
        original_read_evidence = read_model.read_evidence
        monkeypatch.setattr(
            read_model,
            "read_evidence",
            lambda _journey: ApplicationReadResult(
                availability=ApplicationReadAvailability.PENDING,
                source_token=None,
                source_observed_at=None,
                value=None,
                error=ApplicationReadError(
                    code=ApplicationReadErrorCode.EVIDENCE_PENDING,
                    message="Evidence projection is still settling",
                    retryable=True,
                ),
            ),
        )
        completed_during_pending_evidence = _assert_terminal_context(
            feature,
            full,
            resolution=SystemHealthContextResolution.COMPLETED,
            overall=SystemHealthOverallClassification.DIAGNOSTIC_COMPLETED,
        )
        monkeypatch.setattr(read_model, "read_evidence", original_read_evidence)
        missing_finding = feature.snapshot(
            SystemHealthContext(
                diagnostic=replace(
                    full,
                    finding_id=FindingId("missing-finding-112"),
                    sensitivity_breakpoint_id=None,
                )
            )
        )
        superseded_manifest = feature.snapshot(
            SystemHealthContext(
                diagnostic=replace(
                    full,
                    reproduction_manifest_id=ReproductionManifestId(
                        "superseded-manifest-112"
                    ),
                )
            )
        )

        assert missing_finding.diagnostic_context.resolution is (
            SystemHealthContextResolution.MISSING
        )
        assert superseded_manifest.diagnostic_context.resolution is (
            SystemHealthContextResolution.SUPERSEDED
        )
        assert terminal.revision < completed_during_pending_evidence.revision
        assert completed_during_pending_evidence.revision < missing_finding.revision
        assert missing_finding.revision < superseded_manifest.revision
    finally:
        feature.close()
        task_feature.close()
        bridge.stop()
        engine.dispose()


def test_live_adapter_keeps_failed_campaign_node_distinct_from_system_health(
    tmp_path,
) -> None:
    (
        _source,
        _artifact_store,
        engine,
        application,
        diagnostic_tasks_application,
        task_feature,
    ) = _formal_live_stack(
        tmp_path,
        ptrade_host=_FailFirstDecisionPTradeHost(),
    )
    approved = _approved_formal_task(task_feature)
    accepted = task_feature.start_formal_diagnostic_campaign(
        StartFormalDiagnosticCampaign(
            command_id=DiagnosticCommandId("system-health-failed-start-112"),
            idempotency_key=DiagnosticCommandIdempotencyKey(
                "system-health-failed-idempotency-112"
            ),
            task_id=approved.task_id,
            expected_revision=approved.revision,
            approved_revision=approved.revision,
        )
    )
    failed_result = diagnostic_tasks_application.read_diagnostic_task(approved.task_id)
    assert failed_result.task is not None
    failed_task = failed_result.task
    assert failed_task.campaign_handoff is not None
    handoff = failed_task.campaign_handoff
    failed_attempt = next(
        attempt
        for node in handoff.campaign_nodes
        for attempt in node.attempts
        if attempt.failure is not None
    )
    failed_run = failed_attempt.runs[0]
    context = SystemHealthDiagnosticContext(
        task_id=failed_task.task_id,
        task_revision=failed_task.revision,
        configuration_content_id=failed_task.configuration.content_identity,
        task_handle_id=accepted.task_handle.identity,
        campaign_id=handoff.campaign_id,
        campaign_revision=handoff.campaign_revision,
        run_id=failed_run.run_id,
        evidence_package_id=DiagnosticEvidencePackageId(
            "failed-campaign-evidence-not-produced-112"
        ),
        finding_id=FindingId("failed-campaign-finding-not-produced-112"),
        approved_recipe_version_ids=tuple(
            item.recipe_version_id
            for item in failed_task.configuration.campaign_case_selections
        ),
    )
    bridge = EventBridge(subscribe_backend=False)
    read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
        clock=lambda: NOW,
    )
    feature = LiveSystemHealthAdapter(
        application_health=LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
            application,
            clock=lambda: NOW,
        ),
        diagnostic_tasks_application=diagnostic_tasks_application,
        application_read_model=read_model,
        event_bridge=bridge,
        clock=lambda: NOW,
        sampling_interval=None,
    )
    try:
        state = _assert_terminal_context(
            feature,
            context,
            resolution=SystemHealthContextResolution.FAILED,
            overall=SystemHealthOverallClassification.DIAGNOSTIC_FAILED,
        )
        assert state.diagnostic_context.explanation == "The selected diagnostic has failed."
    finally:
        feature.close()
        task_feature.close()
        bridge.stop()
        engine.dispose()
