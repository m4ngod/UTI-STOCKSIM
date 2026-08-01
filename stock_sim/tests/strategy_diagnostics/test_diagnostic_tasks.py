from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from strategy_diagnostics.diagnostic_tasks import (
    ApproveDiagnosticTaskConfigurationRequest,
    CreateDiagnosticTaskRequest,
    DiagnosticCampaignCaseSelection,
    DiagnosticStrategySelection,
    DiagnosticTaskConfiguration,
    DiagnosticTaskCreationDisposition,
    DiagnosticTaskCreationRejectionReason,
    DiagnosticTaskHandlePhase,
    DiagnosticTaskLifecycle,
    DiagnosticTaskService,
    InMemoryDiagnosticTaskRepository,
    ReviseDiagnosticTaskConfigurationRequest,
    SqlDiagnosticTaskRepository,
    ValidateDiagnosticTaskConfigurationRequest,
)
from strategy_diagnostics.persistence import initialize_diagnostic_persistence


def _configuration(
    *,
    strategy_version: str = "1.0",
) -> DiagnosticTaskConfiguration:
    candidate = DiagnosticTaskConfiguration(
        content_identity="pending",
        strategy_selections=(
            DiagnosticStrategySelection(
                strategy_id="strategy-57",
                strategy_version=strategy_version,
                compatibility_manifest_hash="sha256:manifest-57",
                guardrail_profile_id="guardrail-57",
                guardrail_profile_version="1.0",
            ),
        ),
        campaign_case_selections=(
            DiagnosticCampaignCaseSelection(
                layer="baseline",
                recipe_version_id="recipe-57@1",
                recipe_content_hash="sha256:recipe-57",
                market_scenario_id="sha256:scenario-57",
                campaign_case_id="case-57",
                comparison_role="control",
                baseline_campaign_case_id=None,
                execution_policy_values=(
                    (
                        "allow_partial_fills",
                        "true",
                        "1.0",
                        "Approved Scenario Recipe",
                    ),
                ),
            ),
        ),
    )
    return replace(
        candidate,
        content_identity=candidate.calculated_content_identity(),
    )


def _request(
    configuration: DiagnosticTaskConfiguration,
    *,
    command_id: str = "command-57",
    idempotency_key: str = "idempotency-57",
) -> CreateDiagnosticTaskRequest:
    return CreateDiagnosticTaskRequest(
        command_id=command_id,
        idempotency_key=idempotency_key,
        configuration=configuration,
    )


def test_command_identity_and_idempotency_replay_one_durable_task() -> None:
    service = DiagnosticTaskService(
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        configuration_validator=lambda _configuration: True,
    )
    configuration = _configuration()

    accepted = service.create(_request(configuration))
    same_command = service.create(
        _request(
            configuration,
        )
    )
    same_key = service.create(
        _request(
            configuration,
            command_id="different-command-same-key",
        )
    )
    independent = service.create(
        _request(
            configuration,
            command_id="independent-command",
            idempotency_key="independent-key",
        )
    )
    cross_bound = service.create(
        _request(
            configuration,
            command_id="command-57",
            idempotency_key="independent-key",
        )
    )
    conflicting_command = service.create(
        _request(
            _configuration(strategy_version="2.0"),
            idempotency_key="different-key-conflicting-command",
        )
    )

    assert (
        accepted.disposition
        is DiagnosticTaskCreationDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    assert same_command.disposition is (
        DiagnosticTaskCreationDisposition.IDEMPOTENT_REPLAY
    )
    assert same_command.affected_task_id == accepted.affected_task_id
    assert same_key.disposition is (
        DiagnosticTaskCreationDisposition.IDEMPOTENT_REPLAY
    )
    assert independent.disposition is (
        DiagnosticTaskCreationDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    assert cross_bound.rejection_reason is (
        DiagnosticTaskCreationRejectionReason.COMMAND_IDENTITY_CONFLICT
    )
    assert conflicting_command.rejection_reason is (
        DiagnosticTaskCreationRejectionReason.COMMAND_IDENTITY_CONFLICT
    )
    assert accepted.affected_task_id is not None
    snapshot = service.get(accepted.affected_task_id)
    assert snapshot is not None
    assert snapshot.revision == 2
    assert snapshot.lifecycle is DiagnosticTaskLifecycle.DRAFT
    assert snapshot.task_handles[0].phase is (
        DiagnosticTaskHandlePhase.COMPLETED
    )


def test_application_restart_recovers_a_durable_queued_acceptance(
    tmp_path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'diagnostic-task-recovery.db'}",
        future=True,
    )
    initialize_diagnostic_persistence(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER reject_diagnostic_task_completion "
            "BEFORE UPDATE ON diagnostic_task_handles "
            "WHEN NEW.phase = 'completed' "
            "BEGIN SELECT RAISE(FAIL, 'injected completion failure'); END"
        )
    service = DiagnosticTaskService(
        repository=SqlDiagnosticTaskRepository(engine),
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        configuration_validator=lambda _configuration: True,
    )

    accepted = service.create(_request(_configuration()))

    assert accepted.disposition is (
        DiagnosticTaskCreationDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    assert accepted.affected_task_id is not None
    pending = service.get(accepted.affected_task_id)
    assert pending is not None
    assert pending.revision == 1
    assert pending.lifecycle is DiagnosticTaskLifecycle.CREATING
    assert pending.task_handles[0].phase is DiagnosticTaskHandlePhase.QUEUED
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DROP TRIGGER reject_diagnostic_task_completion"
        )

    restarted = DiagnosticTaskService(
        clock=lambda: datetime(2030, 1, 2, tzinfo=timezone.utc),
        configuration_validator=lambda _configuration: True,
    )
    restarted.replace_repository(SqlDiagnosticTaskRepository(engine))
    recovered = restarted.get(accepted.affected_task_id)

    assert recovered is not None
    assert recovered.revision == 2
    assert recovered.lifecycle is DiagnosticTaskLifecycle.DRAFT
    assert recovered.task_handles[0].phase is (
        DiagnosticTaskHandlePhase.COMPLETED
    )
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_tasks")
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_task_commands")
        ).scalar_one() == 1
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_task_handles")
        ).scalar_one() == 1


def test_persisted_task_rejects_an_incompatible_row_schema(tmp_path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'diagnostic-task-schema.db'}",
        future=True,
    )
    initialize_diagnostic_persistence(engine)
    service = DiagnosticTaskService(
        repository=SqlDiagnosticTaskRepository(engine),
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        configuration_validator=lambda _configuration: True,
    )
    accepted = service.create(_request(_configuration()))
    assert accepted.affected_task_id is not None
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_tasks SET schema_version = 'future.99' "
                "WHERE task_id = :task_id"
            ),
            {"task_id": accepted.affected_task_id},
        )

    with pytest.raises(
        ValueError,
        match="Incompatible persisted Diagnostic Task schema version",
    ):
        service.get(accepted.affected_task_id)


def test_sql_latest_task_uses_persisted_creation_order_when_clocks_tie(
    tmp_path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'diagnostic-task-order.db'}",
        future=True,
    )
    initialize_diagnostic_persistence(engine)
    service = DiagnosticTaskService(
        repository=SqlDiagnosticTaskRepository(engine),
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        configuration_validator=lambda _configuration: True,
    )
    first = service.create(
        _request(
            _configuration(),
            command_id="command-b",
            idempotency_key="key-b",
        )
    )
    second = service.create(
        _request(
            _configuration(),
            command_id="command-a",
            idempotency_key="key-a",
        )
    )

    latest = service.latest()

    assert first.affected_task_id != second.affected_task_id
    assert second.affected_task_id is not None
    assert latest is not None
    assert latest.task_id == second.affected_task_id


def test_authoritative_validator_storage_failure_is_typed_and_retryable() -> None:
    def unavailable_validator(
        _configuration: DiagnosticTaskConfiguration,
    ) -> bool:
        raise SQLAlchemyError("authoritative inventory unavailable")

    service = DiagnosticTaskService(
        configuration_validator=unavailable_validator,
    )

    result = service.create(_request(_configuration()))

    assert result.disposition is DiagnosticTaskCreationDisposition.REJECTED
    assert result.rejection_reason is (
        DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE
    )
    assert result.retryable is True
    assert result.task_handle is None


def test_approval_requires_exact_validation_identity_and_revision() -> None:
    service = DiagnosticTaskService(
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        configuration_validator=lambda _configuration: True,
        configuration_validation=lambda _configuration: (),
        validation_policy_provider=lambda _configuration: (
            "diagnostic-task-validation.v1",
        ),
    )
    created = service.create(_request(_configuration()))
    assert created.affected_task_id is not None
    task_id = created.affected_task_id
    revised_configuration = _configuration(strategy_version="2.0")
    revised = service.revise_configuration(
        ReviseDiagnosticTaskConfigurationRequest(
            command_id="revise-command-58",
            idempotency_key="revise-key-58",
            task_id=task_id,
            expected_revision=2,
            configuration=revised_configuration,
        )
    )
    assert revised.current_revision == 3
    validation_result = service.validate_configuration(
        ValidateDiagnosticTaskConfigurationRequest(
            command_id="validate-command-58",
            idempotency_key="validate-key-58",
            task_id=task_id,
            expected_revision=3,
        )
    )
    assert validation_result.disposition is (
        DiagnosticTaskCreationDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    validated = service.get(task_id)
    assert validated is not None
    assert validated.validation is not None

    stale = service.approve_configuration(
        ApproveDiagnosticTaskConfigurationRequest(
            command_id="stale-approve-command-58",
            idempotency_key="stale-approve-key-58",
            task_id=task_id,
            expected_revision=3,
            validation_id="stale-validation-58",
            validation_revision=validated.validation.validation_revision,
            validated_revision=3,
            configuration_content_id=revised_configuration.content_identity,
            actor_id="research-owner",
        )
    )

    assert stale.rejection_reason is (
        DiagnosticTaskCreationRejectionReason.STALE_VALIDATION
    )
    assert stale.current_revision == 3
    assert service.get(task_id).approval is None
    exact_request = ApproveDiagnosticTaskConfigurationRequest(
        command_id="approve-command-58",
        idempotency_key="approve-key-58",
        task_id=task_id,
        expected_revision=3,
        validation_id=validated.validation.validation_id,
        validation_revision=validated.validation.validation_revision,
        validated_revision=3,
        configuration_content_id=revised_configuration.content_identity,
        actor_id="research-owner",
    )
    exact = service.approve_configuration(exact_request)
    replay = service.approve_configuration(exact_request)

    assert exact.disposition is (
        DiagnosticTaskCreationDisposition.SYNCHRONOUS_COMPLETION
    )
    assert replay.disposition is (
        DiagnosticTaskCreationDisposition.IDEMPOTENT_REPLAY
    )
    approved = service.get(task_id)
    assert approved is not None
    assert approved.approval is not None
    assert approved.approval.validation_id == validated.validation.validation_id
    assert (
        approved.approval.validation_revision
        == validated.validation.validation_revision
    )
    stale_approval = service.approve_configuration(
        replace(
            exact_request,
            command_id="second-approve-command-58",
            idempotency_key="second-approve-key-58",
        )
    )
    assert stale_approval.rejection_reason is (
        DiagnosticTaskCreationRejectionReason.STALE_APPROVAL
    )
    assert service.get(task_id).approval == approved.approval


def test_validation_persistence_failure_rolls_back_all_side_effects(
    tmp_path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'diagnostic-task-validation-rollback.db'}",
        future=True,
    )
    initialize_diagnostic_persistence(engine)
    service = DiagnosticTaskService(
        repository=SqlDiagnosticTaskRepository(engine),
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        configuration_validator=lambda _configuration: True,
        configuration_validation=lambda _configuration: (),
        validation_policy_provider=lambda _configuration: (
            "diagnostic-task-validation.v1",
        ),
    )
    created = service.create(_request(_configuration()))
    assert created.affected_task_id is not None
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER reject_diagnostic_task_validation_command "
            "BEFORE INSERT ON diagnostic_task_mutation_commands "
            "WHEN NEW.command_type = "
            "'validate_diagnostic_task_configuration' "
            "BEGIN SELECT RAISE(FAIL, 'injected validation failure'); END"
        )

    failed = service.validate_configuration(
        ValidateDiagnosticTaskConfigurationRequest(
            command_id="validate-rollback-command-58",
            idempotency_key="validate-rollback-key-58",
            task_id=created.affected_task_id,
            expected_revision=2,
        )
    )

    assert failed.rejection_reason is (
        DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE
    )
    assert failed.current_revision == 2
    assert failed.retryable
    current = service.get(created.affected_task_id)
    assert current is not None
    assert current.revision == 2
    assert current.lifecycle is DiagnosticTaskLifecycle.DRAFT
    assert current.validation is None
    assert len(current.task_handles) == 1
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_task_validations")
        ).scalar_one() == 0
        assert connection.execute(
            text(
                "SELECT COUNT(*) "
                "FROM diagnostic_task_mutation_commands"
            )
        ).scalar_one() == 0


def test_persisted_validation_must_match_current_task_revision(
    tmp_path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'diagnostic-task-validation-integrity.db'}",
        future=True,
    )
    initialize_diagnostic_persistence(engine)
    service = DiagnosticTaskService(
        repository=SqlDiagnosticTaskRepository(engine),
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        configuration_validator=lambda _configuration: True,
        configuration_validation=lambda _configuration: (),
        validation_policy_provider=lambda _configuration: (
            "diagnostic-task-validation.v1",
        ),
    )
    created = service.create(_request(_configuration()))
    assert created.affected_task_id is not None
    validated = service.validate_configuration(
        ValidateDiagnosticTaskConfigurationRequest(
            command_id="validate-integrity-command-58",
            idempotency_key="validate-integrity-key-58",
            task_id=created.affected_task_id,
            expected_revision=2,
        )
    )
    assert validated.disposition is (
        DiagnosticTaskCreationDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_task_validations "
                "SET task_revision = 999 "
                "WHERE task_id = :task_id"
            ),
            {"task_id": created.affected_task_id},
        )

    with pytest.raises(
        ValueError,
        match="Persisted Diagnostic Task validation is inconsistent",
    ):
        service.get(created.affected_task_id)


def test_validation_acceptance_keeps_a_durable_queued_handle_until_recovery(
    tmp_path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'diagnostic-task-validation-recovery.db'}",
        future=True,
    )
    initialize_diagnostic_persistence(engine)
    repository = SqlDiagnosticTaskRepository(engine)
    service = DiagnosticTaskService(
        repository=repository,
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        configuration_validator=lambda _configuration: True,
        configuration_validation=lambda _configuration: (),
        validation_policy_provider=lambda _configuration: (
            "diagnostic-task-validation.v1",
        ),
    )
    created = service.create(_request(_configuration()))
    assert created.affected_task_id is not None
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER reject_diagnostic_task_validation_completion "
            "BEFORE UPDATE ON diagnostic_task_handles "
            "WHEN NEW.result_code LIKE "
            "'diagnostic_task_configuration_%' "
            "BEGIN SELECT RAISE(FAIL, 'injected validation completion failure'); "
            "END"
        )

    accepted = service.validate_configuration(
        ValidateDiagnosticTaskConfigurationRequest(
            command_id="validate-recovery-command-58",
            idempotency_key="validate-recovery-key-58",
            task_id=created.affected_task_id,
            expected_revision=2,
        )
    )

    assert accepted.disposition is (
        DiagnosticTaskCreationDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    pending = service.get(created.affected_task_id)
    assert pending is not None
    assert pending.validation is not None
    validation_handle = next(
        handle
        for handle in pending.task_handles
        if handle.task_handle_id == pending.validation.task_handle_id
    )
    assert validation_handle.phase is DiagnosticTaskHandlePhase.QUEUED
    pending_approval = service.approve_configuration(
        ApproveDiagnosticTaskConfigurationRequest(
            command_id="pending-approval-command-58",
            idempotency_key="pending-approval-key-58",
            task_id=created.affected_task_id,
            expected_revision=2,
            validation_id=pending.validation.validation_id,
            validation_revision=(
                pending.validation.validation_revision
            ),
            validated_revision=2,
            configuration_content_id=(
                pending.configuration.content_identity
            ),
            actor_id="research-owner",
        )
    )
    assert pending_approval.rejection_reason is (
        DiagnosticTaskCreationRejectionReason.VALIDATION_PENDING
    )
    assert pending_approval.retryable
    assert service.get(created.affected_task_id).approval is None
    replacement = service.validate_configuration(
        ValidateDiagnosticTaskConfigurationRequest(
            command_id="replacement-recovery-command-58",
            idempotency_key="replacement-recovery-key-58",
            task_id=created.affected_task_id,
            expected_revision=2,
        )
    )
    assert replacement.disposition is (
        DiagnosticTaskCreationDisposition.ASYNCHRONOUS_ACCEPTANCE
    )
    replaced = service.get(created.affected_task_id)
    assert replaced is not None
    validation_handles = tuple(
        handle
        for handle in replaced.task_handles
        if handle.result_code is None
        and handle.phase is DiagnosticTaskHandlePhase.QUEUED
    )
    assert len(validation_handles) == 2
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DROP TRIGGER reject_diagnostic_task_validation_completion"
        )

    restarted = DiagnosticTaskService(
        clock=lambda: datetime(2030, 1, 2, tzinfo=timezone.utc),
        configuration_validator=lambda _configuration: True,
        configuration_validation=lambda _configuration: (),
        validation_policy_provider=lambda _configuration: (
            "diagnostic-task-validation.v1",
        ),
    )
    restarted.replace_repository(SqlDiagnosticTaskRepository(engine))
    recovered = restarted.get(created.affected_task_id)

    assert recovered is not None
    assert recovered.validation is not None
    recovered_handles = tuple(
        handle
        for handle in recovered.task_handles
        if handle.task_handle_id
        in {item.task_handle_id for item in validation_handles}
    )
    assert len(recovered_handles) == 2
    assert all(
        handle.phase is DiagnosticTaskHandlePhase.COMPLETED
        for handle in recovered_handles
    )
    assert {
        handle.result_code for handle in recovered_handles
    } == {
        "diagnostic_task_configuration_valid"
    }
    exact_validation = recovered.validation
    approved = restarted.approve_configuration(
        ApproveDiagnosticTaskConfigurationRequest(
            command_id="recovered-approval-command-58",
            idempotency_key="recovered-approval-key-58",
            task_id=created.affected_task_id,
            expected_revision=2,
            validation_id=exact_validation.validation_id,
            validation_revision=exact_validation.validation_revision,
            validated_revision=2,
            configuration_content_id=(
                recovered.configuration.content_identity
            ),
            actor_id="research-owner",
        )
    )
    assert approved.disposition is (
        DiagnosticTaskCreationDisposition.SYNCHRONOUS_COMPLETION
    )


def test_shared_command_ledger_rolls_back_cross_table_identity_race(
    tmp_path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'diagnostic-task-command-ledger.db'}",
        future=True,
    )
    initialize_diagnostic_persistence(engine)
    repository = SqlDiagnosticTaskRepository(engine)
    service = DiagnosticTaskService(
        repository=repository,
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        configuration_validator=lambda _configuration: True,
    )
    created = service.create(_request(_configuration()))
    assert created.affected_task_id is not None

    class InterleavingRevisionRepository:
        def __init__(self) -> None:
            self.interleaved = False

        def __getattr__(self, name: str):
            return getattr(repository, name)

        def accept_revision(self, **kwargs) -> bool:
            if not self.interleaved:
                self.interleaved = True
                competing = service.create(
                    _request(
                        _configuration(),
                        command_id="shared-race-command-58",
                        idempotency_key="shared-race-key-58",
                    )
                )
                assert competing.disposition is (
                    DiagnosticTaskCreationDisposition.ASYNCHRONOUS_ACCEPTANCE
                )
            return repository.accept_revision(**kwargs)

    racing_service = DiagnosticTaskService(
        repository=InterleavingRevisionRepository(),
        clock=lambda: datetime(2030, 1, 2, tzinfo=timezone.utc),
        configuration_validator=lambda _configuration: True,
    )
    result = racing_service.revise_configuration(
        ReviseDiagnosticTaskConfigurationRequest(
            command_id="shared-race-command-58",
            idempotency_key="shared-race-key-58",
            task_id=created.affected_task_id,
            expected_revision=2,
            configuration=_configuration(strategy_version="2.0"),
        )
    )

    assert result.rejection_reason is (
        DiagnosticTaskCreationRejectionReason.COMMAND_IDENTITY_CONFLICT
    )
    unchanged = service.get(created.affected_task_id)
    assert unchanged is not None
    assert unchanged.revision == 2
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM diagnostic_task_command_identities "
                "WHERE command_id = 'shared-race-command-58'"
            )
        ).scalar_one() == 1
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM diagnostic_task_mutation_commands "
                "WHERE command_id = 'shared-race-command-58'"
            )
        ).scalar_one() == 0


def test_approval_cas_rejects_validation_replaced_after_authoritative_read(
    tmp_path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'diagnostic-task-approval-cas.db'}",
        future=True,
    )
    initialize_diagnostic_persistence(engine)
    repository = SqlDiagnosticTaskRepository(engine)
    service = DiagnosticTaskService(
        repository=repository,
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc),
        configuration_validator=lambda _configuration: True,
        configuration_validation=lambda _configuration: (),
        validation_policy_provider=lambda _configuration: (
            "diagnostic-task-validation.v1",
        ),
    )
    created = service.create(_request(_configuration()))
    assert created.affected_task_id is not None
    service.validate_configuration(
        ValidateDiagnosticTaskConfigurationRequest(
            command_id="first-validation-command-58",
            idempotency_key="first-validation-key-58",
            task_id=created.affected_task_id,
            expected_revision=2,
        )
    )
    first_validated = service.get(created.affected_task_id)
    assert first_validated is not None
    assert first_validated.validation is not None

    class InterleavingApprovalRepository:
        def __init__(self) -> None:
            self.interleaved = False

        def __getattr__(self, name: str):
            return getattr(repository, name)

        def accept_approval(self, **kwargs) -> bool:
            if not self.interleaved:
                self.interleaved = True
                replacement = service.validate_configuration(
                    ValidateDiagnosticTaskConfigurationRequest(
                        command_id="replacement-validation-command-58",
                        idempotency_key="replacement-validation-key-58",
                        task_id=created.affected_task_id,
                        expected_revision=2,
                    )
                )
                assert replacement.disposition is (
                    DiagnosticTaskCreationDisposition.ASYNCHRONOUS_ACCEPTANCE
                )
            return repository.accept_approval(**kwargs)

    racing_service = DiagnosticTaskService(
        repository=InterleavingApprovalRepository(),
        clock=lambda: datetime(2030, 1, 2, tzinfo=timezone.utc),
        configuration_validator=lambda _configuration: True,
        configuration_validation=lambda _configuration: (),
        validation_policy_provider=lambda _configuration: (
            "diagnostic-task-validation.v1",
        ),
    )
    approval = racing_service.approve_configuration(
        ApproveDiagnosticTaskConfigurationRequest(
            command_id="approval-race-command-58",
            idempotency_key="approval-race-key-58",
            task_id=created.affected_task_id,
            expected_revision=2,
            validation_id=first_validated.validation.validation_id,
            validation_revision=(
                first_validated.validation.validation_revision
            ),
            validated_revision=2,
            configuration_content_id=(
                first_validated.configuration.content_identity
            ),
            actor_id="research-owner",
        )
    )

    assert approval.rejection_reason is (
        DiagnosticTaskCreationRejectionReason.STALE_VALIDATION
    )
    current = service.get(created.affected_task_id)
    assert current is not None
    assert current.approval is None
    assert current.validation is not None
    assert (
        current.validation.validation_id
        != first_validated.validation.validation_id
    )


def test_failed_cas_reread_returns_structured_persistence_failure() -> None:
    class FailingRereadRepository(InMemoryDiagnosticTaskRepository):
        fail_reread = False

        def accept_revision(self, **kwargs) -> bool:
            self.fail_reread = True
            return False

        def get_task(self, task_id: str):
            if self.fail_reread:
                raise SQLAlchemyError("injected authoritative reread failure")
            return super().get_task(task_id)

    repository = FailingRereadRepository()
    service = DiagnosticTaskService(
        repository=repository,
        configuration_validator=lambda _configuration: True,
    )
    created = service.create(_request(_configuration()))
    assert created.affected_task_id is not None

    result = service.revise_configuration(
        ReviseDiagnosticTaskConfigurationRequest(
            command_id="failed-cas-command-58",
            idempotency_key="failed-cas-key-58",
            task_id=created.affected_task_id,
            expected_revision=2,
            configuration=_configuration(strategy_version="2.0"),
        )
    )

    assert result.rejection_reason is (
        DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE
    )
    assert result.retryable


@pytest.mark.parametrize(
    "command_name",
    ("revise", "validate", "approve"),
)
def test_empty_mutation_identity_rejects_before_repository_read(
    command_name: str,
) -> None:
    class NoReadRepository(InMemoryDiagnosticTaskRepository):
        def find_mutation_command(
            self,
            command_id: str,
            idempotency_key: str,
        ):
            raise AssertionError("command history must not be read")

        def get_task(self, task_id: str):
            raise AssertionError("task must not be read")

    service = DiagnosticTaskService(
        repository=NoReadRepository(),
        configuration_validator=lambda _configuration: True,
    )
    if command_name == "revise":
        result = service.revise_configuration(
            ReviseDiagnosticTaskConfigurationRequest(
                command_id="",
                idempotency_key="key-58",
                task_id="task-58",
                expected_revision=2,
                configuration=_configuration(),
            )
        )
    elif command_name == "validate":
        result = service.validate_configuration(
            ValidateDiagnosticTaskConfigurationRequest(
                command_id="",
                idempotency_key="key-58",
                task_id="task-58",
                expected_revision=2,
            )
        )
    else:
        result = service.approve_configuration(
            ApproveDiagnosticTaskConfigurationRequest(
                command_id="",
                idempotency_key="key-58",
                task_id="task-58",
                expected_revision=2,
                validation_id="validation-58",
                validation_revision=1,
                validated_revision=2,
                configuration_content_id="configuration-58",
                actor_id="research-owner",
            )
        )

    assert result.rejection_reason is (
        DiagnosticTaskCreationRejectionReason.INVALID_COMMAND
    )
