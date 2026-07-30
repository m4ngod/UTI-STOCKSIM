"""Durable Diagnostic Task creation owned by Strategy Diagnostics."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol, cast

from sqlalchemy import text
from sqlalchemy.engine import Engine, RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

DIAGNOSTIC_TASK_SCHEMA_VERSION = "1.0"


class DiagnosticTaskLifecycle(str, Enum):
    CREATING = "creating"
    DRAFT = "draft"


class DiagnosticTaskHandlePhase(str, Enum):
    QUEUED = "queued"
    COMPLETED = "completed"
    FAILED = "failed"


class DiagnosticTaskCreationDisposition(str, Enum):
    ASYNCHRONOUS_ACCEPTANCE = "asynchronous_acceptance"
    IDEMPOTENT_REPLAY = "idempotent_replay"
    REJECTED = "rejected"


class DiagnosticTaskCreationRejectionReason(str, Enum):
    INVALID_COMMAND = "invalid_command"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    COMMAND_IDENTITY_CONFLICT = "command_identity_conflict"
    PERSISTENCE_FAILURE = "persistence_failure"


@dataclass(frozen=True, slots=True)
class DiagnosticStrategySelection:
    strategy_id: str
    strategy_version: str
    compatibility_manifest_hash: str
    guardrail_profile_id: str
    guardrail_profile_version: str


@dataclass(frozen=True, slots=True)
class DiagnosticCampaignCaseSelection:
    layer: str
    recipe_version_id: str
    recipe_content_hash: str
    market_scenario_id: str
    campaign_case_id: str
    comparison_role: str
    baseline_campaign_case_id: str | None
    execution_policy_values: tuple[tuple[str, str, str, str], ...]


@dataclass(frozen=True, slots=True)
class DiagnosticTaskConfiguration:
    content_identity: str
    strategy_selections: tuple[DiagnosticStrategySelection, ...]
    campaign_case_selections: tuple[DiagnosticCampaignCaseSelection, ...]

    def canonical_payload(self) -> dict[str, object]:
        return {
            "campaign_case_selections": [
                {
                    "baseline_campaign_case_id": item.baseline_campaign_case_id,
                    "campaign_case_id": item.campaign_case_id,
                    "comparison_role": item.comparison_role,
                    "execution_policy_values": [
                        {
                            "name": name,
                            "source": source,
                            "value": value,
                            "version": version,
                        }
                        for name, value, version, source in sorted(
                            item.execution_policy_values
                        )
                    ],
                    "layer": item.layer,
                    "market_scenario_id": item.market_scenario_id,
                    "recipe_content_hash": item.recipe_content_hash,
                    "recipe_version_id": item.recipe_version_id,
                }
                for item in sorted(
                    self.campaign_case_selections,
                    key=lambda candidate: (
                        candidate.layer,
                        candidate.campaign_case_id,
                    ),
                )
            ],
            "strategy_selections": [
                {
                    "compatibility_manifest_hash": (
                        item.compatibility_manifest_hash
                    ),
                    "guardrail_profile_id": item.guardrail_profile_id,
                    "guardrail_profile_version": (
                        item.guardrail_profile_version
                    ),
                    "strategy_id": item.strategy_id,
                    "strategy_version": item.strategy_version,
                }
                for item in sorted(
                    self.strategy_selections,
                    key=lambda candidate: candidate.strategy_id,
                )
            ],
        }

    def calculated_content_identity(self) -> str:
        return _content_identity(self.canonical_payload())

    def to_storage_dict(self) -> dict[str, object]:
        return {
            "content_identity": self.content_identity,
            **self.canonical_payload(),
        }

    @classmethod
    def from_storage_dict(
        cls,
        payload: Mapping[str, object],
    ) -> DiagnosticTaskConfiguration:
        strategies = cast(list[Mapping[str, object]], payload["strategy_selections"])
        cases = cast(
            list[Mapping[str, object]],
            payload["campaign_case_selections"],
        )
        return cls(
            content_identity=str(payload["content_identity"]),
            strategy_selections=tuple(
                DiagnosticStrategySelection(
                    strategy_id=str(item["strategy_id"]),
                    strategy_version=str(item["strategy_version"]),
                    compatibility_manifest_hash=str(
                        item["compatibility_manifest_hash"]
                    ),
                    guardrail_profile_id=str(item["guardrail_profile_id"]),
                    guardrail_profile_version=str(
                        item["guardrail_profile_version"]
                    ),
                )
                for item in strategies
            ),
            campaign_case_selections=tuple(
                DiagnosticCampaignCaseSelection(
                    layer=str(item["layer"]),
                    recipe_version_id=str(item["recipe_version_id"]),
                    recipe_content_hash=str(item["recipe_content_hash"]),
                    market_scenario_id=str(item["market_scenario_id"]),
                    campaign_case_id=str(item["campaign_case_id"]),
                    comparison_role=str(item["comparison_role"]),
                    baseline_campaign_case_id=(
                        None
                        if item.get("baseline_campaign_case_id") is None
                        else str(item["baseline_campaign_case_id"])
                    ),
                    execution_policy_values=tuple(
                        (
                            str(value["name"]),
                            str(value["value"]),
                            str(value["version"]),
                            str(value["source"]),
                        )
                        for value in cast(
                            list[Mapping[str, object]],
                            item["execution_policy_values"],
                        )
                    ),
                )
                for item in cases
            ),
        )


@dataclass(frozen=True, slots=True)
class CreateDiagnosticTaskRequest:
    command_id: str
    idempotency_key: str
    configuration: DiagnosticTaskConfiguration

    def command_content_identity(self) -> str:
        return _content_identity(
            {
                "command_type": "create_diagnostic_task",
                "configuration": self.configuration.to_storage_dict(),
            }
        )


@dataclass(frozen=True, slots=True)
class DiagnosticTaskHandleSnapshot:
    task_handle_id: str
    task_id: str
    phase: DiagnosticTaskHandlePhase
    progress: float
    result_code: str | None
    error_code: str | None
    error_message: str | None
    error_retryable: bool
    cancelable: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DiagnosticTaskSnapshot:
    task_id: str
    revision: int
    lifecycle: DiagnosticTaskLifecycle
    configuration: DiagnosticTaskConfiguration
    task_handles: tuple[DiagnosticTaskHandleSnapshot, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DiagnosticTaskCreationResult:
    disposition: DiagnosticTaskCreationDisposition
    command_id: str
    idempotency_key: str
    message: str
    rejection_reason: DiagnosticTaskCreationRejectionReason | None
    task_handle: DiagnosticTaskHandleSnapshot | None
    current_revision: int | None
    affected_task_id: str | None
    retryable: bool


@dataclass(frozen=True, slots=True)
class DiagnosticTaskCommandRecord:
    command_id: str
    idempotency_key: str
    command_content_id: str
    task_id: str
    task_handle_id: str


@dataclass(frozen=True, slots=True)
class DiagnosticTaskAcceptance:
    created: bool
    record: DiagnosticTaskCommandRecord


class DiagnosticTaskRepository(Protocol):
    def find_command(
        self,
        command_id: str,
        idempotency_key: str,
    ) -> DiagnosticTaskCommandRecord | None: ...

    def accept_creation(
        self,
        *,
        record: DiagnosticTaskCommandRecord,
        command_json: str,
        acceptance_json: str,
        task: DiagnosticTaskSnapshot,
        handle: DiagnosticTaskHandleSnapshot,
    ) -> DiagnosticTaskAcceptance: ...

    def get_task(self, task_id: str) -> DiagnosticTaskSnapshot | None: ...

    def latest_task(self) -> DiagnosticTaskSnapshot | None: ...

    def complete_creation(self, task_id: str, updated_at: datetime) -> None: ...

    def recover_pending(self, updated_at: datetime) -> None: ...


class InMemoryDiagnosticTaskRepository:
    def __init__(self) -> None:
        self._tasks: dict[str, DiagnosticTaskSnapshot] = {}
        self._commands_by_id: dict[str, DiagnosticTaskCommandRecord] = {}
        self._commands_by_key: dict[str, DiagnosticTaskCommandRecord] = {}

    def find_command(
        self,
        command_id: str,
        idempotency_key: str,
    ) -> DiagnosticTaskCommandRecord | None:
        return self._commands_by_id.get(
            command_id
        ) or self._commands_by_key.get(idempotency_key)

    def accept_creation(
        self,
        *,
        record: DiagnosticTaskCommandRecord,
        command_json: str,
        acceptance_json: str,
        task: DiagnosticTaskSnapshot,
        handle: DiagnosticTaskHandleSnapshot,
    ) -> DiagnosticTaskAcceptance:
        del command_json, acceptance_json
        existing = self._commands_by_id.get(record.command_id)
        if existing is None:
            existing = self._commands_by_key.get(record.idempotency_key)
        if existing is not None:
            return DiagnosticTaskAcceptance(created=False, record=existing)
        if task.task_id in self._tasks:
            raise ValueError("Diagnostic Task identity collision")
        self._tasks[task.task_id] = replace(task, task_handles=(handle,))
        self._commands_by_id[record.command_id] = record
        self._commands_by_key[record.idempotency_key] = record
        return DiagnosticTaskAcceptance(created=True, record=record)

    def get_task(self, task_id: str) -> DiagnosticTaskSnapshot | None:
        return self._tasks.get(task_id)

    def latest_task(self) -> DiagnosticTaskSnapshot | None:
        if not self._tasks:
            return None
        return tuple(self._tasks.values())[-1]

    def complete_creation(self, task_id: str, updated_at: datetime) -> None:
        current = self._tasks.get(task_id)
        if current is None:
            raise KeyError(f"Unknown Diagnostic Task {task_id!r}")
        handle = current.task_handles[0]
        if handle.phase is DiagnosticTaskHandlePhase.COMPLETED:
            return
        if handle.phase is not DiagnosticTaskHandlePhase.QUEUED:
            raise ValueError("Terminal Diagnostic TaskHandle cannot regress")
        completed_handle = replace(
            handle,
            phase=DiagnosticTaskHandlePhase.COMPLETED,
            progress=1.0,
            result_code="diagnostic_task_created",
            cancelable=False,
            updated_at=updated_at,
        )
        self._tasks[task_id] = replace(
            current,
            revision=2,
            lifecycle=DiagnosticTaskLifecycle.DRAFT,
            task_handles=(completed_handle,),
            updated_at=updated_at,
        )

    def recover_pending(self, updated_at: datetime) -> None:
        for task_id, task in tuple(self._tasks.items()):
            if (
                task.lifecycle is DiagnosticTaskLifecycle.CREATING
                and task.task_handles
                and task.task_handles[0].phase
                is DiagnosticTaskHandlePhase.QUEUED
            ):
                self.complete_creation(task_id, updated_at)


class SqlDiagnosticTaskRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def find_command(
        self,
        command_id: str,
        idempotency_key: str,
    ) -> DiagnosticTaskCommandRecord | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT command_id, idempotency_key, command_content_id, "
                    "task_id, task_handle_id FROM diagnostic_task_commands "
                    "WHERE command_id = :command_id "
                    "OR idempotency_key = :idempotency_key "
                    "ORDER BY CASE WHEN command_id = :command_id THEN 0 ELSE 1 END "
                    "LIMIT 1"
                ),
                {
                    "command_id": command_id,
                    "idempotency_key": idempotency_key,
                },
            ).mappings().one_or_none()
        return None if row is None else _command_record(row)

    def accept_creation(
        self,
        *,
        record: DiagnosticTaskCommandRecord,
        command_json: str,
        acceptance_json: str,
        task: DiagnosticTaskSnapshot,
        handle: DiagnosticTaskHandleSnapshot,
    ) -> DiagnosticTaskAcceptance:
        try:
            with self._engine.begin() as connection:
                existing_row = connection.execute(
                    text(
                        "SELECT command_id, idempotency_key, command_content_id, "
                        "task_id, task_handle_id FROM diagnostic_task_commands "
                        "WHERE command_id = :command_id "
                        "OR idempotency_key = :idempotency_key "
                        "ORDER BY CASE WHEN command_id = :command_id THEN 0 ELSE 1 END "
                        "LIMIT 1"
                    ),
                    {
                        "command_id": record.command_id,
                        "idempotency_key": record.idempotency_key,
                    },
                ).mappings().one_or_none()
                if existing_row is not None:
                    return DiagnosticTaskAcceptance(
                        created=False,
                        record=_command_record(existing_row),
                    )
                creation_sequence = connection.execute(
                    text(
                        "UPDATE diagnostic_task_sequences "
                        "SET next_value = next_value + 1 "
                        "WHERE sequence_name = 'diagnostic_task_creation' "
                        "RETURNING next_value"
                    )
                ).scalar_one()
                connection.execute(
                    text(
                        "INSERT INTO diagnostic_tasks ("
                        "task_id, creation_sequence, revision, lifecycle, "
                        "schema_version, "
                        "configuration_content_id, configuration_json, "
                        "created_at_utc, updated_at_utc"
                        ") VALUES ("
                        ":task_id, :creation_sequence, :revision, :lifecycle, "
                        ":schema_version, "
                        ":configuration_content_id, :configuration_json, "
                        ":created_at_utc, :updated_at_utc)"
                    ),
                    _task_row(
                        task,
                        creation_sequence=int(creation_sequence),
                    ),
                )
                connection.execute(
                    text(
                        "INSERT INTO diagnostic_task_handles ("
                        "task_handle_id, task_id, phase, progress_value, "
                        "result_code, error_json, cancelable, created_at_utc, "
                        "updated_at_utc"
                        ") VALUES ("
                        ":task_handle_id, :task_id, :phase, :progress_value, "
                        ":result_code, :error_json, :cancelable, :created_at_utc, "
                        ":updated_at_utc)"
                    ),
                    _handle_row(handle),
                )
                connection.execute(
                    text(
                        "INSERT INTO diagnostic_task_commands ("
                        "command_id, idempotency_key, command_type, "
                        "command_content_id, task_id, task_handle_id, "
                        "disposition, command_json, acceptance_json, "
                        "accepted_at_utc"
                        ") VALUES ("
                        ":command_id, :idempotency_key, "
                        "'create_diagnostic_task', :command_content_id, "
                        ":task_id, :task_handle_id, 'asynchronous_acceptance', "
                        ":command_json, :acceptance_json, :accepted_at_utc)"
                    ),
                    {
                        "command_id": record.command_id,
                        "idempotency_key": record.idempotency_key,
                        "command_content_id": record.command_content_id,
                        "task_id": record.task_id,
                        "task_handle_id": record.task_handle_id,
                        "command_json": command_json,
                        "acceptance_json": acceptance_json,
                        "accepted_at_utc": handle.created_at.isoformat(),
                    },
                )
        except IntegrityError:
            existing = self._find_existing(record)
            if existing is None:
                raise
            return DiagnosticTaskAcceptance(created=False, record=existing)
        return DiagnosticTaskAcceptance(created=True, record=record)

    def get_task(self, task_id: str) -> DiagnosticTaskSnapshot | None:
        with self._engine.connect() as connection:
            task_row = connection.execute(
                text(
                    "SELECT task_id, revision, lifecycle, configuration_json, "
                    "configuration_content_id, schema_version, "
                    "created_at_utc, updated_at_utc FROM diagnostic_tasks "
                    "WHERE task_id = :task_id"
                ),
                {"task_id": task_id},
            ).mappings().one_or_none()
            if task_row is None:
                return None
            handle_rows = connection.execute(
                text(
                    "SELECT task_handle_id, task_id, phase, progress_value, "
                    "result_code, error_json, cancelable, created_at_utc, "
                    "updated_at_utc FROM diagnostic_task_handles "
                    "WHERE task_id = :task_id ORDER BY created_at_utc, "
                    "task_handle_id"
                ),
                {"task_id": task_id},
            ).mappings().all()
        return _task_from_rows(task_row, handle_rows)

    def latest_task(self) -> DiagnosticTaskSnapshot | None:
        with self._engine.connect() as connection:
            task_id = connection.execute(
                text(
                    "SELECT task_id FROM diagnostic_tasks "
                    "ORDER BY creation_sequence DESC LIMIT 1"
                )
            ).scalar_one_or_none()
        return None if task_id is None else self.get_task(str(task_id))

    def complete_creation(self, task_id: str, updated_at: datetime) -> None:
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT task_handle_id, phase FROM diagnostic_task_handles "
                    "WHERE task_id = :task_id ORDER BY created_at_utc, "
                    "task_handle_id LIMIT 1"
                ),
                {"task_id": task_id},
            ).mappings().one_or_none()
            if row is None:
                raise KeyError(f"Unknown Diagnostic Task {task_id!r}")
            phase = str(row["phase"])
            task_handle_id = str(row["task_handle_id"])
            if phase == DiagnosticTaskHandlePhase.COMPLETED.value:
                return
            if phase != DiagnosticTaskHandlePhase.QUEUED.value:
                raise ValueError("Terminal Diagnostic TaskHandle cannot regress")
            updated_at_utc = updated_at.isoformat()
            connection.execute(
                text(
                    "UPDATE diagnostic_tasks SET revision = 2, "
                    "lifecycle = :lifecycle, updated_at_utc = :updated_at_utc "
                    "WHERE task_id = :task_id"
                ),
                {
                    "lifecycle": DiagnosticTaskLifecycle.DRAFT.value,
                    "updated_at_utc": updated_at_utc,
                    "task_id": task_id,
                },
            )
            connection.execute(
                text(
                    "UPDATE diagnostic_task_handles SET phase = :phase, "
                    "progress_value = 1.0, "
                    "result_code = 'diagnostic_task_created', "
                    "cancelable = 0, updated_at_utc = :updated_at_utc "
                    "WHERE task_handle_id = :task_handle_id"
                ),
                {
                    "phase": DiagnosticTaskHandlePhase.COMPLETED.value,
                    "updated_at_utc": updated_at_utc,
                    "task_handle_id": task_handle_id,
                },
            )

    def recover_pending(self, updated_at: datetime) -> None:
        with self._engine.connect() as connection:
            task_ids = tuple(
                str(value)
                for value in connection.execute(
                    text(
                        "SELECT t.task_id FROM diagnostic_tasks t "
                        "JOIN diagnostic_task_handles h ON h.task_id = t.task_id "
                        "WHERE t.lifecycle = :lifecycle AND h.phase = :phase"
                    ),
                    {
                        "lifecycle": DiagnosticTaskLifecycle.CREATING.value,
                        "phase": DiagnosticTaskHandlePhase.QUEUED.value,
                    },
                ).scalars()
            )
        for task_id in task_ids:
            self.complete_creation(task_id, updated_at)

    def _find_existing(
        self,
        record: DiagnosticTaskCommandRecord,
    ) -> DiagnosticTaskCommandRecord | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT command_id, idempotency_key, command_content_id, "
                    "task_id, task_handle_id FROM diagnostic_task_commands "
                    "WHERE command_id = :command_id "
                    "OR idempotency_key = :idempotency_key "
                    "ORDER BY CASE WHEN command_id = :command_id THEN 0 ELSE 1 END "
                    "LIMIT 1"
                ),
                {
                    "command_id": record.command_id,
                    "idempotency_key": record.idempotency_key,
                },
            ).mappings().one_or_none()
        return None if row is None else _command_record(row)


class DiagnosticTaskService:
    def __init__(
        self,
        *,
        repository: DiagnosticTaskRepository | None = None,
        clock: Callable[[], datetime] | None = None,
        configuration_validator: Callable[
            [DiagnosticTaskConfiguration],
            bool,
        ],
    ) -> None:
        self._repository = repository or InMemoryDiagnosticTaskRepository()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._configuration_validator = configuration_validator

    def replace_repository(self, repository: DiagnosticTaskRepository) -> None:
        self._repository = repository
        self._repository.recover_pending(_aware(self._clock()))

    def create(
        self,
        request: CreateDiagnosticTaskRequest,
    ) -> DiagnosticTaskCreationResult:
        command_content_id = request.command_content_identity()
        try:
            existing = self._repository.find_command(
                request.command_id,
                request.idempotency_key,
            )
        except (OSError, SQLAlchemyError, ValueError):
            return self._rejected(
                request,
                DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE,
                "Diagnostic Task command history could not be read.",
                retryable=True,
            )
        if existing is not None:
            return self._existing_result(
                request,
                command_content_id,
                existing,
            )
        try:
            valid = self._is_valid(request)
        except (OSError, SQLAlchemyError):
            return self._rejected(
                request,
                DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE,
                "Authoritative Diagnostic Task inputs could not be read.",
                retryable=True,
            )
        if not valid:
            return self._rejected(
                request,
                DiagnosticTaskCreationRejectionReason.INVALID_COMMAND,
                "Diagnostic Task configuration is not authoritative.",
                retryable=False,
            )
        task_id = _stable_identity("diagnostic-task", request.command_id)
        handle_id = _stable_identity(
            "diagnostic-task-handle",
            request.command_id,
        )
        now = _aware(self._clock())
        handle = DiagnosticTaskHandleSnapshot(
            task_handle_id=handle_id,
            task_id=task_id,
            phase=DiagnosticTaskHandlePhase.QUEUED,
            progress=0.0,
            result_code=None,
            error_code=None,
            error_message=None,
            error_retryable=False,
            cancelable=False,
            created_at=now,
            updated_at=now,
        )
        task = DiagnosticTaskSnapshot(
            task_id=task_id,
            revision=1,
            lifecycle=DiagnosticTaskLifecycle.CREATING,
            configuration=request.configuration,
            task_handles=(handle,),
            created_at=now,
            updated_at=now,
        )
        record = DiagnosticTaskCommandRecord(
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            command_content_id=command_content_id,
            task_id=task_id,
            task_handle_id=handle_id,
        )
        try:
            acceptance = self._repository.accept_creation(
                record=record,
                command_json=_canonical_json(
                    {
                        "command_id": request.command_id,
                        "command_type": "create_diagnostic_task",
                        "configuration": (
                            request.configuration.to_storage_dict()
                        ),
                        "idempotency_key": request.idempotency_key,
                    }
                ),
                acceptance_json=_canonical_json(
                    {
                        "disposition": "asynchronous_acceptance",
                        "task_handle_id": handle_id,
                        "task_id": task_id,
                    }
                ),
                task=task,
                handle=handle,
            )
        except (OSError, SQLAlchemyError, ValueError):
            return self._rejected(
                request,
                DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE,
                "Diagnostic Task acceptance could not be persisted atomically.",
                retryable=True,
            )
        if not acceptance.created:
            return self._existing_result(
                request,
                command_content_id,
                acceptance.record,
            )
        try:
            self._repository.complete_creation(task_id, _aware(self._clock()))
        except (OSError, SQLAlchemyError, ValueError):
            # Acceptance is durable. Application restart recovers queued work.
            message = (
                "Diagnostic Task creation accepted; queued completion will "
                "resume when the Application restarts."
            )
        else:
            message = "Diagnostic Task creation accepted."
        return DiagnosticTaskCreationResult(
            disposition=(
                DiagnosticTaskCreationDisposition.ASYNCHRONOUS_ACCEPTANCE
            ),
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            message=message,
            rejection_reason=None,
            task_handle=handle,
            current_revision=1,
            affected_task_id=task_id,
            retryable=False,
        )

    def get(self, task_id: str) -> DiagnosticTaskSnapshot | None:
        return self._repository.get_task(task_id)

    def latest(self) -> DiagnosticTaskSnapshot | None:
        return self._repository.latest_task()

    def _is_valid(self, request: CreateDiagnosticTaskRequest) -> bool:
        return bool(
            request.command_id.strip()
            and request.idempotency_key.strip()
            and request.configuration.content_identity
            == request.configuration.calculated_content_identity()
            and self._configuration_validator(request.configuration)
        )

    def _existing_result(
        self,
        request: CreateDiagnosticTaskRequest,
        command_content_id: str,
        existing: DiagnosticTaskCommandRecord,
    ) -> DiagnosticTaskCreationResult:
        if (
            existing.command_id == request.command_id
            and existing.idempotency_key != request.idempotency_key
        ):
            return self._rejected(
                request,
                DiagnosticTaskCreationRejectionReason.COMMAND_IDENTITY_CONFLICT,
                "Command identity is already bound to another idempotency key.",
                retryable=False,
            )
        if existing.command_content_id != command_content_id:
            reason = (
                DiagnosticTaskCreationRejectionReason.COMMAND_IDENTITY_CONFLICT
                if existing.command_id == request.command_id
                else DiagnosticTaskCreationRejectionReason.IDEMPOTENCY_CONFLICT
            )
            return self._rejected(
                request,
                reason,
                "Command identity or idempotency content does not match.",
                retryable=False,
            )
        try:
            existing_task = self._repository.get_task(existing.task_id)
        except (OSError, SQLAlchemyError, ValueError):
            return self._rejected(
                request,
                DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE,
                "Persisted Diagnostic Task acceptance could not be read.",
                retryable=True,
            )
        if existing_task is None or not existing_task.task_handles:
            return self._rejected(
                request,
                DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE,
                "Persisted Diagnostic Task acceptance is incomplete.",
                retryable=True,
            )
        return DiagnosticTaskCreationResult(
            disposition=DiagnosticTaskCreationDisposition.IDEMPOTENT_REPLAY,
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            message="Existing Diagnostic Task acceptance replayed.",
            rejection_reason=None,
            task_handle=existing_task.task_handles[0],
            current_revision=existing_task.revision,
            affected_task_id=existing.task_id,
            retryable=False,
        )

    @staticmethod
    def _rejected(
        request: CreateDiagnosticTaskRequest,
        reason: DiagnosticTaskCreationRejectionReason,
        message: str,
        *,
        retryable: bool,
    ) -> DiagnosticTaskCreationResult:
        return DiagnosticTaskCreationResult(
            disposition=DiagnosticTaskCreationDisposition.REJECTED,
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            message=message,
            rejection_reason=reason,
            task_handle=None,
            current_revision=None,
            affected_task_id=None,
            retryable=retryable,
        )


def _task_row(
    task: DiagnosticTaskSnapshot,
    *,
    creation_sequence: int,
) -> dict[str, object]:
    return {
        "task_id": task.task_id,
        "creation_sequence": creation_sequence,
        "revision": task.revision,
        "lifecycle": task.lifecycle.value,
        "schema_version": DIAGNOSTIC_TASK_SCHEMA_VERSION,
        "configuration_content_id": task.configuration.content_identity,
        "configuration_json": _canonical_json(
            task.configuration.to_storage_dict()
        ),
        "created_at_utc": task.created_at.isoformat(),
        "updated_at_utc": task.updated_at.isoformat(),
    }


def _handle_row(handle: DiagnosticTaskHandleSnapshot) -> dict[str, object]:
    error_json = (
        None
        if handle.error_code is None
        else _canonical_json(
            {
                "code": handle.error_code,
                "message": handle.error_message,
                "retryable": handle.error_retryable,
            }
        )
    )
    return {
        "task_handle_id": handle.task_handle_id,
        "task_id": handle.task_id,
        "phase": handle.phase.value,
        "progress_value": handle.progress,
        "result_code": handle.result_code,
        "error_json": error_json,
        "cancelable": int(handle.cancelable),
        "created_at_utc": handle.created_at.isoformat(),
        "updated_at_utc": handle.updated_at.isoformat(),
    }


def _task_from_rows(
    task_row: RowMapping,
    handle_rows: Sequence[RowMapping],
) -> DiagnosticTaskSnapshot:
    configuration_payload = json.loads(str(task_row["configuration_json"]))
    if not isinstance(configuration_payload, dict):
        raise TypeError("Diagnostic Task configuration must be a JSON object")
    if str(task_row["schema_version"]) != DIAGNOSTIC_TASK_SCHEMA_VERSION:
        raise ValueError("Incompatible persisted Diagnostic Task schema version")
    configuration = DiagnosticTaskConfiguration.from_storage_dict(
        cast(Mapping[str, object], configuration_payload)
    )
    if (
        configuration.content_identity
        != str(task_row["configuration_content_id"])
        or configuration.content_identity
        != configuration.calculated_content_identity()
    ):
        raise ValueError("Persisted Diagnostic Task configuration is inconsistent")
    return DiagnosticTaskSnapshot(
        task_id=str(task_row["task_id"]),
        revision=int(cast(str | int, task_row["revision"])),
        lifecycle=DiagnosticTaskLifecycle(str(task_row["lifecycle"])),
        configuration=configuration,
        task_handles=tuple(_handle_from_row(row) for row in handle_rows),
        created_at=datetime.fromisoformat(str(task_row["created_at_utc"])),
        updated_at=datetime.fromisoformat(str(task_row["updated_at_utc"])),
    )


def _handle_from_row(
    row: RowMapping,
) -> DiagnosticTaskHandleSnapshot:
    error_code: str | None = None
    error_message: str | None = None
    error_retryable = False
    if row["error_json"] is not None:
        error = json.loads(str(row["error_json"]))
        if not isinstance(error, dict):
            raise ValueError("Diagnostic TaskHandle error must be a JSON object")
        error_code = str(error["code"])
        error_message = str(error["message"])
        error_retryable = bool(error["retryable"])
    return DiagnosticTaskHandleSnapshot(
        task_handle_id=str(row["task_handle_id"]),
        task_id=str(row["task_id"]),
        phase=DiagnosticTaskHandlePhase(str(row["phase"])),
        progress=float(cast(str | float, row["progress_value"])),
        result_code=(
            None if row["result_code"] is None else str(row["result_code"])
        ),
        error_code=error_code,
        error_message=error_message,
        error_retryable=error_retryable,
        cancelable=bool(row["cancelable"]),
        created_at=datetime.fromisoformat(str(row["created_at_utc"])),
        updated_at=datetime.fromisoformat(str(row["updated_at_utc"])),
    )


def _command_record(row: RowMapping) -> DiagnosticTaskCommandRecord:
    return DiagnosticTaskCommandRecord(
        command_id=str(row["command_id"]),
        idempotency_key=str(row["idempotency_key"]),
        command_content_id=str(row["command_content_id"]),
        task_id=str(row["task_id"]),
        task_handle_id=str(row["task_handle_id"]),
    )


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _content_identity(payload: object) -> str:
    encoded = _canonical_json(payload).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _stable_identity(prefix: str, seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


__all__ = [
    "CreateDiagnosticTaskRequest",
    "DiagnosticCampaignCaseSelection",
    "DiagnosticStrategySelection",
    "DiagnosticTaskConfiguration",
    "DiagnosticTaskCreationDisposition",
    "DiagnosticTaskCreationRejectionReason",
    "DiagnosticTaskCreationResult",
    "DiagnosticTaskHandlePhase",
    "DiagnosticTaskHandleSnapshot",
    "DiagnosticTaskLifecycle",
    "DiagnosticTaskService",
    "DiagnosticTaskSnapshot",
    "InMemoryDiagnosticTaskRepository",
    "SqlDiagnosticTaskRepository",
]
