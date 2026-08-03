from __future__ import annotations

import inspect
from dataclasses import fields
from typing import get_type_hints

import pytest

from app.features import (
    ACTIVE_FEATURE_INTERFACES,
    DIAGNOSTIC_TASKS_INTERFACE_VERSION,
    ApproveDiagnosticTaskConfiguration,
    ApprovedScenarioRecipeVersionId,
    CampaignAttemptId,
    CampaignCaseId,
    CampaignNodeId,
    CampaignNodeTarget,
    CancelDiagnosticTarget,
    CreateDiagnosticTask,
    DiagnosticActorId,
    DiagnosticCampaignAttemptHandoff,
    DiagnosticCampaignCaseSelection,
    DiagnosticCampaignCaseSelectionReference,
    DiagnosticCampaignLayer,
    DiagnosticCampaignNodeHandoff,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    DiagnosticComparisonRole,
    DiagnosticEvidencePackageId,
    DiagnosticTaskConfiguration,
    DiagnosticTaskConfigurationContentId,
    DiagnosticTaskHandoff,
    DiagnosticTaskId,
    DiagnosticTaskLifecycle,
    DiagnosticTasksCommandResult,
    DiagnosticTasksFeature,
    DiagnosticTasksPresentationState,
    DiagnosticTasksViewState,
    DiagnosticTaskTarget,
    DiagnosticTaskValidationCode,
    DiagnosticTaskValidationFinding,
    DiagnosticTaskValidationId,
    DiagnosticTaskValidationSeverity,
    FeatureModuleName,
    FormalDiagnosticCampaignId,
    FormalDiagnosticCampaignTarget,
    MaterializedMarketScenarioId,
    PauseDiagnosticTarget,
    ReproductionManifestId,
    ResumeDiagnosticTarget,
    RetryFailedCampaignNode,
    ReviseDiagnosticTaskConfiguration,
    StartFormalDiagnosticCampaign,
    ValidateDiagnosticTaskConfiguration,
)


def test_diagnostic_tasks_feature_activates_the_exact_versioned_operation_surface() -> None:
    assert DIAGNOSTIC_TASKS_INTERFACE_VERSION.render() == "1.0"
    assert tuple(
        (descriptor.name, descriptor.version.render())
        for descriptor in ACTIVE_FEATURE_INTERFACES
    ) == (
        (FeatureModuleName.STRATEGY_LIBRARY, "1.0"),
        (FeatureModuleName.DIAGNOSTIC_TASKS, "1.0"),
        (FeatureModuleName.RUN_MONITORING, "1.2"),
        (FeatureModuleName.EVIDENCE_AND_FINDINGS, "1.1"),
    )

    operations = {
        name
        for name, member in inspect.getmembers(
            DiagnosticTasksFeature,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    assert operations == {
        "approve_configuration",
        "cancel_diagnostic_target",
        "close",
        "create_diagnostic_task",
        "pause_diagnostic_target",
        "resume_diagnostic_target",
        "retry_failed_campaign_node",
        "revise_configuration",
        "snapshot",
        "start_formal_diagnostic_campaign",
        "subscribe",
        "validate_configuration",
    }

    command_types = {
        name: get_type_hints(getattr(DiagnosticTasksFeature, name))["command"]
        for name in operations
        if name not in {"close", "snapshot", "subscribe"}
    }
    assert command_types == {
        "approve_configuration": ApproveDiagnosticTaskConfiguration,
        "cancel_diagnostic_target": CancelDiagnosticTarget,
        "create_diagnostic_task": CreateDiagnosticTask,
        "pause_diagnostic_target": PauseDiagnosticTarget,
        "resume_diagnostic_target": ResumeDiagnosticTarget,
        "retry_failed_campaign_node": RetryFailedCampaignNode,
        "revise_configuration": ReviseDiagnosticTaskConfiguration,
        "start_formal_diagnostic_campaign": StartFormalDiagnosticCampaign,
        "validate_configuration": ValidateDiagnosticTaskConfiguration,
    }


def test_diagnostic_tasks_1_0_freezes_complete_state_and_result_shapes() -> None:
    assert {item.value for item in DiagnosticTasksPresentationState} == {
        "loading",
        "empty",
        "ready",
        "degraded",
        "failed",
        "input_unavailable",
    }
    assert {item.value for item in DiagnosticTaskLifecycle} == {
        "creating",
        "draft",
        "validating",
        "awaiting_approval",
        "approved",
        "queued",
        "running",
        "paused",
        "resuming",
        "canceling",
        "canceled",
        "failed",
        "completed",
    }
    assert {field.name for field in fields(DiagnosticTasksViewState)} == {
        "interface_version",
        "revision",
        "observed_at",
        "last_reliable_at",
        "freshness",
        "age",
        "freshness_threshold",
        "source",
        "context",
        "phase",
        "presentation",
        "completeness",
        "last_reliable_inventory",
        "task",
        "capabilities",
        "blocking_reasons",
        "reproduction_manifest_availability",
        "reproduction_manifest_id",
        "error",
    }
    assert {field.name for field in fields(DiagnosticTaskConfiguration)} == {
        "content_identity",
        "strategy_selections",
        "campaign_case_selections",
    }
    assert {field.name for field in fields(DiagnosticTasksCommandResult)} == {
        "disposition",
        "command_id",
        "idempotency_key",
        "message",
        "rejection_reason",
        "task_handle",
        "current_revision",
        "affected_task_id",
        "affected_campaign_id",
        "affected_campaign_node_id",
        "affected_campaign_attempt_id",
        "retryable",
        "correlation_id",
    }
    assert {
        field.name for field in fields(DiagnosticCampaignAttemptHandoff)
    } == {
        "attempt_id",
        "runs",
        "attempt_number",
        "lifecycle",
        "predecessor_attempt_id",
        "task_handle_id",
        "failure",
    }


def test_existing_target_commands_freeze_expected_revision_and_nominal_targets() -> None:
    command_id = DiagnosticCommandId("command-56")
    idempotency_key = DiagnosticCommandIdempotencyKey("idempotency-56")
    task_id = DiagnosticTaskId("diagnostic-task-56")

    approval = ApproveDiagnosticTaskConfiguration(
        command_id=command_id,
        idempotency_key=idempotency_key,
        task_id=task_id,
        expected_revision=3,
        validation_id=DiagnosticTaskValidationId("validation-56"),
        validation_revision=1,
        validated_revision=2,
        configuration_content_id=DiagnosticTaskConfigurationContentId(
            "sha256:configuration-56"
        ),
        actor_id=DiagnosticActorId("research-owner"),
    )

    assert approval.expected_revision == 3
    assert approval.validated_revision == 2
    targets = (
        DiagnosticTaskTarget(task_id),
        FormalDiagnosticCampaignTarget(
            FormalDiagnosticCampaignId("formal-diagnostic-campaign-56")
        ),
        CampaignNodeTarget(CampaignNodeId("campaign-node-56")),
    )
    for target in targets:
        pause = PauseDiagnosticTarget(
            command_id=command_id,
            idempotency_key=idempotency_key,
            target=target,
            expected_revision=1,
        )
        assert pause.target is target


def test_configuration_cases_and_handoff_keep_all_authoritative_identities_linked() -> None:
    baseline_case = CampaignCaseId("campaign-case-baseline-56")
    scenario_id = MaterializedMarketScenarioId("market-scenario-baseline-56")
    selection = DiagnosticCampaignCaseSelection(
        layer=DiagnosticCampaignLayer.BASELINE,
        recipe_version_id=ApprovedScenarioRecipeVersionId("recipe-baseline-56@1"),
        recipe_content_hash="sha256:recipe-baseline-56",
        market_scenario_id=scenario_id,
        campaign_case_id=baseline_case,
        comparison_role=DiagnosticComparisonRole.CONTROL,
        baseline_campaign_case_id=None,
        execution_policy_values=(),
    )
    configuration = DiagnosticTaskConfiguration(
        content_identity=DiagnosticTaskConfigurationContentId(
            "sha256:configuration-56"
        ),
        strategy_selections=(),
        campaign_case_selections=(selection,),
    )

    assert {field.name for field in fields(DiagnosticTaskConfiguration)} == {
        "content_identity",
        "strategy_selections",
        "campaign_case_selections",
    }
    assert configuration.campaign_case_selections == (selection,)

    node = DiagnosticCampaignNodeHandoff(
        campaign_node_id=CampaignNodeId("campaign-node-56"),
        campaign_case_id=baseline_case,
        selected_campaign_case_id=baseline_case,
        market_scenario_id=scenario_id,
        attempts=(
            DiagnosticCampaignAttemptHandoff(
                attempt_id=CampaignAttemptId("campaign-attempt-56"),
                runs=(),
            ),
        ),
        active_attempt_id=CampaignAttemptId("campaign-attempt-56"),
    )
    handoff = DiagnosticTaskHandoff(
        campaign_id=FormalDiagnosticCampaignId("formal-campaign-56"),
        selected_cases=(selection,),
        campaign_nodes=(node,),
        evidence_package_id=None,
        reproduction_manifest_id=None,
    )

    assert handoff.selected_cases[0].campaign_case_id == baseline_case
    assert handoff.campaign_nodes[0].market_scenario_id == scenario_id
    assert handoff.ready_for_run_monitoring is False
    assert handoff.ready_for_evidence_and_findings is False


def test_validation_findings_freeze_typed_safe_remediation_metadata() -> None:
    reference = DiagnosticCampaignCaseSelectionReference(
        campaign_case_id=CampaignCaseId("campaign-case-56"),
    )
    finding = DiagnosticTaskValidationFinding(
        reference=reference,
        severity=DiagnosticTaskValidationSeverity.ERROR,
        code=DiagnosticTaskValidationCode("scenario_revision_mismatch"),
        safe_explanation="The selected immutable scenario no longer matches.",
        retryable=False,
        requires_different_input=True,
    )

    assert finding.reference is reference
    assert finding.severity is DiagnosticTaskValidationSeverity.ERROR
    assert finding.code.value == "scenario_revision_mismatch"
    assert finding.requires_different_input is True


def test_handoff_rejects_broken_attempt_and_selected_case_identity_graphs() -> None:
    case_id = CampaignCaseId("campaign-case-56")
    scenario_id = MaterializedMarketScenarioId("market-scenario-56")
    node_id = CampaignNodeId("campaign-node-56")
    attempt_id = CampaignAttemptId("campaign-attempt-56")

    with pytest.raises(ValueError, match="Active Campaign attempt"):
        DiagnosticCampaignNodeHandoff(
            campaign_node_id=node_id,
            campaign_case_id=case_id,
            selected_campaign_case_id=case_id,
            market_scenario_id=scenario_id,
            attempts=(),
            active_attempt_id=attempt_id,
        )

    node = DiagnosticCampaignNodeHandoff(
        campaign_node_id=node_id,
        campaign_case_id=case_id,
        selected_campaign_case_id=case_id,
        market_scenario_id=scenario_id,
        attempts=(
            DiagnosticCampaignAttemptHandoff(
                attempt_id=attempt_id,
                runs=(),
            ),
        ),
        active_attempt_id=attempt_id,
    )
    with pytest.raises(ValueError, match="selected Campaign Case"):
        DiagnosticTaskHandoff(
            campaign_id=FormalDiagnosticCampaignId("formal-campaign-56"),
            selected_cases=(),
            campaign_nodes=(node,),
            evidence_package_id=None,
            reproduction_manifest_id=None,
        )
    with pytest.raises(ValueError, match="must become available together"):
        DiagnosticTaskHandoff(
            campaign_id=FormalDiagnosticCampaignId("formal-campaign-56"),
            selected_cases=(),
            campaign_nodes=(),
            evidence_package_id=DiagnosticEvidencePackageId(
                "evidence-package-56"
            ),
            reproduction_manifest_id=None,
        )
    with pytest.raises(ValueError, match="Strategy Run"):
        DiagnosticTaskHandoff(
            campaign_id=FormalDiagnosticCampaignId("formal-campaign-56"),
            selected_cases=(),
            campaign_nodes=(),
            evidence_package_id=DiagnosticEvidencePackageId(
                "evidence-package-56"
            ),
            reproduction_manifest_id=ReproductionManifestId(
                "reproduction-manifest-56"
            ),
        )
