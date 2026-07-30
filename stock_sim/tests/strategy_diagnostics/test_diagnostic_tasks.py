from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from strategy_diagnostics.diagnostic_tasks import (
    CreateDiagnosticTaskRequest,
    DiagnosticCampaignCaseSelection,
    DiagnosticStrategySelection,
    DiagnosticTaskConfiguration,
    DiagnosticTaskCreationDisposition,
    DiagnosticTaskCreationRejectionReason,
    DiagnosticTaskHandlePhase,
    DiagnosticTaskLifecycle,
    DiagnosticTaskService,
    SqlDiagnosticTaskRepository,
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
