from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from strategy_diagnostics.diagnostic_tasks import (
    ApproveDiagnosticTaskConfigurationRequest,
    CreateDiagnosticTaskRequest,
    DiagnosticCampaignCaseSelection,
    DiagnosticSelectionDependencyBinding,
    DiagnosticStrategySelection,
    DiagnosticTaskConfiguration,
    DiagnosticTaskCreationDisposition,
    DiagnosticTaskCreationRejectionReason,
    DiagnosticTaskLifecycle,
    DiagnosticTaskService,
    InMemoryDiagnosticTaskRepository,
    ReviseDiagnosticTaskConfigurationRequest,
    SqlDiagnosticTaskRepository,
    StartFormalDiagnosticCampaignRequest,
    ValidateDiagnosticTaskConfigurationRequest,
)
from strategy_diagnostics.persistence import initialize_diagnostic_persistence


def _configuration() -> DiagnosticTaskConfiguration:
    candidate = DiagnosticTaskConfiguration(
        content_identity="pending",
        strategy_selections=(
            DiagnosticStrategySelection(
                strategy_id="baseline_equal_weight",
                strategy_version="1.0",
                compatibility_manifest_hash="sha256:baseline-manifest",
                guardrail_profile_id="baseline-guardrail",
                guardrail_profile_version="1.0",
            ),
            DiagnosticStrategySelection(
                strategy_id="momentum_rank_top_n",
                strategy_version="1.0",
                compatibility_manifest_hash="sha256:momentum-manifest",
                guardrail_profile_id="momentum-guardrail",
                guardrail_profile_version="1.0",
            ),
        ),
        campaign_case_selections=(
            DiagnosticCampaignCaseSelection(
                layer="baseline",
                recipe_version_id="recipe@1",
                recipe_content_hash="sha256:recipe",
                market_scenario_id="path-baseline",
                campaign_case_id="case-baseline",
                comparison_role="control",
                baseline_campaign_case_id=None,
                execution_policy_values=(
                    (
                        "commission_bps",
                        "3",
                        "diagnostic-execution.v1",
                        "backend-resolved:requested=3",
                    ),
                ),
            ),
            DiagnosticCampaignCaseSelection(
                layer="isolated_sensitivity",
                recipe_version_id="recipe@1",
                recipe_content_hash="sha256:recipe",
                market_scenario_id="path-isolated",
                campaign_case_id="case-isolated",
                comparison_role="compare_to_baseline",
                baseline_campaign_case_id="case-baseline",
                execution_policy_values=(
                    (
                        "commission_bps",
                        "4",
                        "diagnostic-execution.v1",
                        "backend-resolved:stress;requested=3",
                    ),
                ),
            ),
            DiagnosticCampaignCaseSelection(
                layer="compound",
                recipe_version_id="recipe@1",
                recipe_content_hash="sha256:recipe",
                market_scenario_id="path-compound",
                campaign_case_id="case-compound",
                comparison_role="compare_to_baseline",
                baseline_campaign_case_id="case-baseline",
                execution_policy_values=(
                    (
                        "commission_bps",
                        "5",
                        "diagnostic-execution.v1",
                        "backend-resolved:compound;requested=3",
                    ),
                ),
            ),
        ),
    )
    return replace(
        candidate,
        content_identity=candidate.calculated_content_identity(),
    )


def _binding(version: int = 1) -> DiagnosticSelectionDependencyBinding:
    return DiagnosticSelectionDependencyBinding.create(
        source_identity="diagnostic-setup-selection-context-001",
        strategy_selection_context_id="strategy-selection-context-001",
        scenario_selection_context_id="scenario-selection-context-001",
        canonical_payload_json=(
            "{\"schema_version\":\"diagnostic-selection-dependency.v1\","
            f"\"authority_revision\":{version}}}"
        ),
    )


def _validated_approved_service(
    repository,
    authority: list[DiagnosticSelectionDependencyBinding],
) -> tuple[DiagnosticTaskService, str]:
    service = DiagnosticTaskService(
        repository=repository,
        clock=lambda: datetime(2031, 1, 1, tzinfo=timezone.utc),
        configuration_validator=lambda _configuration: True,
        dependency_binding_provider=lambda _configuration, _expected: authority[0],
    )
    configuration = _configuration()
    created = service.create(
        CreateDiagnosticTaskRequest(
            command_id="create-84",
            idempotency_key="create-key-84",
            configuration=configuration,
        ),
        dependency_binding=authority[0],
    )
    assert created.affected_task_id is not None
    task_id = created.affected_task_id
    task = service.get(task_id)
    assert task is not None
    validated = service.validate_configuration(
        ValidateDiagnosticTaskConfigurationRequest(
            command_id="validate-84",
            idempotency_key="validate-key-84",
            task_id=task_id,
            expected_revision=task.revision,
        )
    )
    assert validated.disposition is not DiagnosticTaskCreationDisposition.REJECTED
    task = service.get(task_id)
    assert task is not None and task.validation is not None
    approved = service.approve_configuration(
        ApproveDiagnosticTaskConfigurationRequest(
            command_id="approve-84",
            idempotency_key="approve-key-84",
            task_id=task_id,
            expected_revision=task.revision,
            validation_id=task.validation.validation_id,
            validation_revision=task.validation.validation_revision,
            validated_revision=task.validation.task_revision,
            configuration_content_id=task.configuration.content_identity,
            actor_id="research-lead-84",
        )
    )
    assert approved.disposition is not DiagnosticTaskCreationDisposition.REJECTED
    return service, task_id


def test_validation_and_approval_bind_the_same_exact_dependency() -> None:
    authority = [_binding()]
    service, task_id = _validated_approved_service(
        InMemoryDiagnosticTaskRepository(), authority
    )

    validation_binding = service.active_dependency_binding(task_id)
    approval_binding = service.active_approval_dependency_binding(task_id)

    assert service.active_setup_dependency_binding(task_id) == authority[0]
    assert validation_binding == authority[0]
    assert approval_binding == authority[0]
    task = service.get(task_id)
    assert task is not None
    assert task.lifecycle is DiagnosticTaskLifecycle.APPROVED
    assert task.validation is not None
    assert task.approval is not None


def test_authority_drift_records_invalidation_and_disables_approval_start() -> None:
    authority = [_binding()]
    service, task_id = _validated_approved_service(
        InMemoryDiagnosticTaskRepository(), authority
    )
    authority[0] = _binding(version=2)

    reconciled = service.get(task_id)

    assert reconciled is not None
    assert reconciled.lifecycle is DiagnosticTaskLifecycle.DRAFT
    assert reconciled.validation is None
    assert reconciled.approval is None
    assert service.active_dependency_binding(task_id) is None
    invalidations = service.dependency_invalidations(task_id)
    assert len(invalidations) == 1
    assert invalidations[0].reason_code == "authoritative_dependency_mismatch"
    assert invalidations[0].expected_binding_hash == _binding().binding_hash
    assert invalidations[0].observed_binding_hash == authority[0].binding_hash

    rejected = service.preflight_start(
        StartFormalDiagnosticCampaignRequest(
            command_id="start-after-drift-84",
            idempotency_key="start-after-drift-key-84",
            task_id=task_id,
            expected_revision=reconciled.revision,
            approved_revision=reconciled.revision,
        )
    )
    assert rejected.disposition is DiagnosticTaskCreationDisposition.REJECTED
    assert rejected.rejection_reason is (
        DiagnosticTaskCreationRejectionReason.STALE_APPROVAL
    )
    assert service.pending_start_requests() == ()


def test_sql_binding_and_invalidation_reopen_without_rewriting_history(
    tmp_path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'issue-84-binding.sqlite'}")
    initialize_diagnostic_persistence(engine)
    authority = [_binding()]
    service, task_id = _validated_approved_service(
        SqlDiagnosticTaskRepository(engine), authority
    )

    reopened = DiagnosticTaskService(
        repository=SqlDiagnosticTaskRepository(engine),
        clock=lambda: datetime(2031, 1, 2, tzinfo=timezone.utc),
        configuration_validator=lambda _configuration: True,
        dependency_binding_provider=lambda _configuration, _expected: authority[0],
    )
    assert reopened.active_dependency_binding(task_id) == authority[0]
    assert reopened.active_setup_dependency_binding(task_id) == authority[0]
    assert reopened.active_approval_dependency_binding(task_id) == authority[0]

    authority[0] = _binding(version=2)
    task = reopened.get(task_id)

    assert task is not None and task.approval is None
    with engine.connect() as connection:
        validation_history = connection.execute(
            text(
                "SELECT COUNT(*) FROM diagnostic_task_validations "
                "WHERE task_id = :task_id"
            ),
            {"task_id": task_id},
        ).scalar_one()
        approval_history = connection.execute(
            text(
                "SELECT COUNT(*) FROM diagnostic_task_approvals "
                "WHERE task_id = :task_id"
            ),
            {"task_id": task_id},
        ).scalar_one()
        invalidation_history = connection.execute(
            text(
                "SELECT COUNT(*) FROM "
                "diagnostic_task_selection_dependency_invalidations "
                "WHERE task_id = :task_id"
            ),
            {"task_id": task_id},
        ).scalar_one()
    assert (validation_history, approval_history, invalidation_history) == (1, 1, 1)


def test_start_performs_its_own_authority_recheck_without_prior_read() -> None:
    authority = [_binding()]
    service, task_id = _validated_approved_service(
        InMemoryDiagnosticTaskRepository(), authority
    )
    task = service.get(task_id)
    assert task is not None
    authority[0] = _binding(version=2)

    rejected = service.preflight_start(
        StartFormalDiagnosticCampaignRequest(
            command_id="start-own-recheck-84",
            idempotency_key="start-own-recheck-key-84",
            task_id=task_id,
            expected_revision=task.revision,
            approved_revision=task.revision,
        )
    )

    assert rejected.disposition is DiagnosticTaskCreationDisposition.REJECTED
    assert rejected.rejection_reason is (
        DiagnosticTaskCreationRejectionReason.STALE_APPROVAL
    )
    assert service.pending_start_requests() == ()
    assert len(service.dependency_invalidations(task_id)) == 1


def test_corrected_exact_selection_can_revise_revalidate_and_reapprove() -> None:
    authority = [_binding()]
    service, task_id = _validated_approved_service(
        InMemoryDiagnosticTaskRepository(), authority
    )
    authority[0] = _binding(version=2)
    stale = service.get(task_id)
    assert stale is not None and stale.approval is None
    original = stale.configuration
    first_case = original.campaign_case_selections[0]
    corrected_case = replace(
        first_case,
        execution_policy_values=(
            (
                "commission_bps",
                "4",
                "diagnostic-execution.v1",
                "backend-resolved:corrected;requested=3",
            ),
        ),
    )
    corrected = replace(
        original,
        content_identity="pending",
        campaign_case_selections=(
            corrected_case,
            *original.campaign_case_selections[1:],
        ),
    )
    corrected = replace(
        corrected,
        content_identity=corrected.calculated_content_identity(),
    )
    revised = service.revise_configuration(
        ReviseDiagnosticTaskConfigurationRequest(
            command_id="revise-corrected-84",
            idempotency_key="revise-corrected-key-84",
            task_id=task_id,
            expected_revision=stale.revision,
            configuration=corrected,
        ),
        dependency_binding=authority[0],
    )
    assert revised.disposition is not DiagnosticTaskCreationDisposition.REJECTED
    current = service.get(task_id)
    assert current is not None
    validated = service.validate_configuration(
        ValidateDiagnosticTaskConfigurationRequest(
            command_id="revalidate-corrected-84",
            idempotency_key="revalidate-corrected-key-84",
            task_id=task_id,
            expected_revision=current.revision,
        )
    )
    assert validated.disposition is not DiagnosticTaskCreationDisposition.REJECTED
    current = service.get(task_id)
    assert current is not None and current.validation is not None
    approved = service.approve_configuration(
        ApproveDiagnosticTaskConfigurationRequest(
            command_id="reapprove-corrected-84",
            idempotency_key="reapprove-corrected-key-84",
            task_id=task_id,
            expected_revision=current.revision,
            validation_id=current.validation.validation_id,
            validation_revision=current.validation.validation_revision,
            validated_revision=current.validation.task_revision,
            configuration_content_id=current.configuration.content_identity,
            actor_id="research-lead-corrected-84",
        )
    )
    assert approved.disposition is not DiagnosticTaskCreationDisposition.REJECTED
    current = service.get(task_id)
    assert current is not None and current.approval is not None
    assert service.active_dependency_binding(task_id) == authority[0]


def test_legacy_caller_without_dependency_provider_remains_compatible() -> None:
    service = DiagnosticTaskService(
        clock=lambda: datetime(2031, 1, 1, tzinfo=timezone.utc),
        configuration_validator=lambda _configuration: True,
    )
    created = service.create(
        CreateDiagnosticTaskRequest(
            command_id="legacy-create-84",
            idempotency_key="legacy-create-key-84",
            configuration=_configuration(),
        )
    )
    assert created.disposition is not DiagnosticTaskCreationDisposition.REJECTED
    assert created.affected_task_id is not None
    task = service.get(created.affected_task_id)
    assert task is not None
    validated = service.validate_configuration(
        ValidateDiagnosticTaskConfigurationRequest(
            command_id="legacy-validate-84",
            idempotency_key="legacy-validate-key-84",
            task_id=task.task_id,
            expected_revision=task.revision,
        )
    )
    assert validated.disposition is not DiagnosticTaskCreationDisposition.REJECTED
    assert service.active_dependency_binding(task.task_id) is None
