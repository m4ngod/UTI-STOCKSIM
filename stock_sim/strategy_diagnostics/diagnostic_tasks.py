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
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

DIAGNOSTIC_TASK_SCHEMA_VERSION = "1.0"


class DiagnosticTaskLifecycle(str, Enum):
    CREATING = "creating"
    DRAFT = "draft"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    QUEUED = "queued"
    RUNNING = "running"


class DiagnosticTaskHandlePhase(str, Enum):
    QUEUED = "queued"
    COMPLETED = "completed"
    FAILED = "failed"


class DiagnosticTaskCreationDisposition(str, Enum):
    SYNCHRONOUS_COMPLETION = "synchronous_completion"
    ASYNCHRONOUS_ACCEPTANCE = "asynchronous_acceptance"
    IDEMPOTENT_REPLAY = "idempotent_replay"
    REJECTED = "rejected"


class DiagnosticTaskCreationRejectionReason(str, Enum):
    INVALID_COMMAND = "invalid_command"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    COMMAND_IDENTITY_CONFLICT = "command_identity_conflict"
    PERSISTENCE_FAILURE = "persistence_failure"
    STALE_EXPECTED_REVISION = "stale_expected_revision"
    STALE_VALIDATION = "stale_validation"
    STALE_APPROVAL = "stale_approval"
    VALIDATION_PENDING = "validation_pending"
    VALIDATION_FAILED = "validation_failed"
    UNAVAILABLE_INPUT = "unavailable_input"


class DiagnosticTaskValidationState(str, Enum):
    VALID = "valid"
    INVALID = "invalid"


class DiagnosticTaskValidationSeverity(str, Enum):
    INFORMATION = "information"
    WARNING = "warning"
    ERROR = "error"


class DiagnosticTaskValidationReferenceKind(str, Enum):
    CONFIGURATION = "configuration"
    STRATEGY = "strategy"
    CAMPAIGN_CASE = "campaign_case"


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
class ReviseDiagnosticTaskConfigurationRequest:
    command_id: str
    idempotency_key: str
    task_id: str
    expected_revision: int
    configuration: DiagnosticTaskConfiguration

    def command_content_identity(self) -> str:
        return _content_identity(
            {
                "command_type": "revise_diagnostic_task_configuration",
                "configuration": self.configuration.to_storage_dict(),
                "expected_revision": self.expected_revision,
                "task_id": self.task_id,
            }
        )


@dataclass(frozen=True, slots=True)
class ValidateDiagnosticTaskConfigurationRequest:
    command_id: str
    idempotency_key: str
    task_id: str
    expected_revision: int

    def command_content_identity(self) -> str:
        return _content_identity(
            {
                "command_type": "validate_diagnostic_task_configuration",
                "expected_revision": self.expected_revision,
                "task_id": self.task_id,
            }
        )


@dataclass(frozen=True, slots=True)
class ApproveDiagnosticTaskConfigurationRequest:
    command_id: str
    idempotency_key: str
    task_id: str
    expected_revision: int
    validation_id: str
    validation_revision: int
    validated_revision: int
    configuration_content_id: str
    actor_id: str

    def command_content_identity(self) -> str:
        return _content_identity(
            {
                "actor_id": self.actor_id,
                "command_type": "approve_diagnostic_task_configuration",
                "configuration_content_id": self.configuration_content_id,
                "expected_revision": self.expected_revision,
                "task_id": self.task_id,
                "validation_id": self.validation_id,
                "validation_revision": self.validation_revision,
                "validated_revision": self.validated_revision,
            }
        )


@dataclass(frozen=True, slots=True)
class StartFormalDiagnosticCampaignRequest:
    command_id: str
    idempotency_key: str
    task_id: str
    expected_revision: int
    approved_revision: int

    def command_content_identity(self) -> str:
        return _content_identity(
            {
                "approved_revision": self.approved_revision,
                "command_type": "start_formal_diagnostic_campaign",
                "expected_revision": self.expected_revision,
                "task_id": self.task_id,
            }
        )


@dataclass(frozen=True, slots=True)
class DiagnosticTaskValidationFinding:
    reference_kind: DiagnosticTaskValidationReferenceKind
    reference_identity: str
    severity: DiagnosticTaskValidationSeverity
    code: str
    safe_explanation: str
    retryable: bool
    requires_different_input: bool


@dataclass(frozen=True, slots=True)
class DiagnosticTaskValidationSnapshot:
    validation_id: str
    validation_revision: int
    task_id: str
    task_revision: int
    configuration_content_id: str
    state: DiagnosticTaskValidationState
    findings: tuple[DiagnosticTaskValidationFinding, ...]
    policy_identities: tuple[str, ...]
    task_handle_id: str
    validated_at: datetime


@dataclass(frozen=True, slots=True)
class DiagnosticTaskApprovalSnapshot:
    approval_id: str
    task_id: str
    task_revision: int
    configuration_content_id: str
    validation_id: str
    validation_revision: int
    actor_id: str
    policy_identities: tuple[str, ...]
    approved_at: datetime


@dataclass(frozen=True, slots=True)
class DiagnosticCampaignRunHandoffSnapshot:
    run_id: str
    strategy_id: str

    def __post_init__(self) -> None:
        if not self.run_id.strip() or not self.strategy_id.strip():
            raise ValueError("Campaign Run and Strategy identities are required")

    def to_storage_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "strategy_id": self.strategy_id,
        }


@dataclass(frozen=True, slots=True)
class DiagnosticCampaignAttemptHandoffSnapshot:
    attempt_id: str
    runs: tuple[DiagnosticCampaignRunHandoffSnapshot, ...]

    def __post_init__(self) -> None:
        if not self.attempt_id.strip():
            raise ValueError("Campaign attempt identity is required")
        if len(set(self.run_ids)) != len(self.run_ids):
            raise ValueError("Campaign attempt run identities must be unique")
        strategy_ids = tuple(item.strategy_id for item in self.runs)
        if len(set(strategy_ids)) != len(strategy_ids):
            raise ValueError(
                "Campaign attempt Strategy identities must be unique"
            )

    @property
    def run_ids(self) -> tuple[str, ...]:
        return tuple(item.run_id for item in self.runs)

    def to_storage_dict(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "runs": [item.to_storage_dict() for item in self.runs],
        }


@dataclass(frozen=True, slots=True)
class DiagnosticCampaignNodeHandoffSnapshot:
    campaign_node_id: str
    campaign_case_id: str
    selected_campaign_case_id: str
    market_scenario_id: str
    attempts: tuple[DiagnosticCampaignAttemptHandoffSnapshot, ...]
    active_attempt_id: str | None

    def __post_init__(self) -> None:
        identities = (
            self.campaign_node_id,
            self.campaign_case_id,
            self.selected_campaign_case_id,
            self.market_scenario_id,
        )
        if any(not identity.strip() for identity in identities):
            raise ValueError("Campaign node handoff identities are required")
        attempt_ids = tuple(item.attempt_id for item in self.attempts)
        if len(set(attempt_ids)) != len(attempt_ids):
            raise ValueError("Campaign node attempt identities must be unique")
        if (
            self.active_attempt_id is not None
            and self.active_attempt_id not in attempt_ids
        ):
            raise ValueError("Active Campaign attempt must be present in history")

    def to_storage_dict(self) -> dict[str, object]:
        return {
            "active_attempt_id": self.active_attempt_id,
            "attempts": [
                attempt.to_storage_dict() for attempt in self.attempts
            ],
            "campaign_case_id": self.campaign_case_id,
            "campaign_node_id": self.campaign_node_id,
            "market_scenario_id": self.market_scenario_id,
            "selected_campaign_case_id": self.selected_campaign_case_id,
        }


@dataclass(frozen=True, slots=True)
class DiagnosticTaskCampaignHandoffSnapshot:
    campaign_id: str
    campaign_nodes: tuple[DiagnosticCampaignNodeHandoffSnapshot, ...]

    def __post_init__(self) -> None:
        if not self.campaign_id.strip():
            raise ValueError("Formal Diagnostic Campaign identity is required")
        node_ids = tuple(item.campaign_node_id for item in self.campaign_nodes)
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("Campaign node identities must be unique")
        attempt_ids = tuple(
            attempt.attempt_id
            for node in self.campaign_nodes
            for attempt in node.attempts
        )
        run_ids = tuple(
            run_id
            for node in self.campaign_nodes
            for attempt in node.attempts
            for run_id in attempt.run_ids
        )
        if len(set(attempt_ids)) != len(attempt_ids):
            raise ValueError("Campaign attempt identities must be globally unique")
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("Strategy Run identities must be globally unique")

    def to_storage_dict(self) -> dict[str, object]:
        return {
            "campaign_id": self.campaign_id,
            "campaign_nodes": [
                node.to_storage_dict() for node in self.campaign_nodes
            ],
        }

    @classmethod
    def from_storage_dict(
        cls,
        payload: Mapping[str, object],
    ) -> "DiagnosticTaskCampaignHandoffSnapshot":
        node_payloads = cast(
            list[Mapping[str, object]],
            payload["campaign_nodes"],
        )
        return cls(
            campaign_id=str(payload["campaign_id"]),
            campaign_nodes=tuple(
                DiagnosticCampaignNodeHandoffSnapshot(
                    campaign_node_id=str(node["campaign_node_id"]),
                    campaign_case_id=str(node["campaign_case_id"]),
                    selected_campaign_case_id=str(
                        node["selected_campaign_case_id"]
                    ),
                    market_scenario_id=str(node["market_scenario_id"]),
                    attempts=tuple(
                        DiagnosticCampaignAttemptHandoffSnapshot(
                            attempt_id=str(attempt["attempt_id"]),
                            runs=tuple(
                                DiagnosticCampaignRunHandoffSnapshot(
                                    run_id=str(run["run_id"]),
                                    strategy_id=str(run["strategy_id"]),
                                )
                                for run in cast(
                                    list[Mapping[str, object]],
                                    attempt["runs"],
                                )
                            ),
                        )
                        for attempt in cast(
                            list[Mapping[str, object]],
                            node["attempts"],
                        )
                    ),
                    active_attempt_id=(
                        None
                        if node.get("active_attempt_id") is None
                        else str(node["active_attempt_id"])
                    ),
                )
                for node in node_payloads
            ),
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
    validation: DiagnosticTaskValidationSnapshot | None = None
    approval: DiagnosticTaskApprovalSnapshot | None = None
    campaign_handoff: DiagnosticTaskCampaignHandoffSnapshot | None = None


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
    affected_campaign_id: str | None = None


DiagnosticTaskCommandResult = DiagnosticTaskCreationResult


@dataclass(frozen=True, slots=True)
class DiagnosticTaskCommandRecord:
    command_id: str
    idempotency_key: str
    command_content_id: str
    task_id: str
    task_handle_id: str | None


@dataclass(frozen=True, slots=True)
class DiagnosticTaskMutationCommandRecord:
    command_id: str
    idempotency_key: str
    command_type: str
    command_content_id: str
    task_id: str
    task_handle_id: str | None
    disposition: DiagnosticTaskCreationDisposition
    message: str
    current_revision: int


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

    def find_mutation_command(
        self,
        command_id: str,
        idempotency_key: str,
    ) -> DiagnosticTaskMutationCommandRecord | None: ...

    def pending_start_requests(
        self,
    ) -> tuple[StartFormalDiagnosticCampaignRequest, ...]: ...

    def accept_revision(
        self,
        *,
        record: DiagnosticTaskMutationCommandRecord,
        command_json: str,
        task: DiagnosticTaskSnapshot,
        expected_revision: int,
    ) -> bool: ...

    def accept_validation(
        self,
        *,
        record: DiagnosticTaskMutationCommandRecord,
        command_json: str,
        task: DiagnosticTaskSnapshot,
        validation: DiagnosticTaskValidationSnapshot,
        queued_handle: DiagnosticTaskHandleSnapshot,
        expected_revision: int,
    ) -> bool: ...

    def complete_validation(
        self,
        task_handle_id: str,
        updated_at: datetime,
    ) -> None: ...

    def accept_approval(
        self,
        *,
        record: DiagnosticTaskMutationCommandRecord,
        command_json: str,
        task: DiagnosticTaskSnapshot,
        approval: DiagnosticTaskApprovalSnapshot,
        expected_revision: int,
    ) -> bool: ...

    def accept_start(
        self,
        *,
        record: DiagnosticTaskMutationCommandRecord,
        command_json: str,
        task: DiagnosticTaskSnapshot,
        queued_handle: DiagnosticTaskHandleSnapshot,
        expected_revision: int,
    ) -> bool: ...

    def claim_start_continuation(
        self,
        task_handle_id: str,
        continuation_claim_id: str,
        claimed_at: datetime,
    ) -> bool: ...

    def release_start_continuation(
        self,
        task_handle_id: str,
        continuation_claim_id: str,
    ) -> None: ...

    def reset_start_continuation_claims(self) -> None: ...

    def complete_start(
        self,
        task_handle_id: str,
        continuation_claim_id: str,
        handoff: DiagnosticTaskCampaignHandoffSnapshot,
        updated_at: datetime,
    ) -> None: ...


class InMemoryDiagnosticTaskRepository:
    def __init__(self) -> None:
        self._tasks: dict[str, DiagnosticTaskSnapshot] = {}
        self._validations_by_handle: dict[
            str,
            DiagnosticTaskValidationSnapshot,
        ] = {}
        self._commands_by_id: dict[str, DiagnosticTaskCommandRecord] = {}
        self._commands_by_key: dict[str, DiagnosticTaskCommandRecord] = {}
        self._mutation_commands_by_id: dict[
            str,
            DiagnosticTaskMutationCommandRecord,
        ] = {}
        self._mutation_commands_by_key: dict[
            str,
            DiagnosticTaskMutationCommandRecord,
        ] = {}
        self._pending_start_requests: dict[
            str,
            StartFormalDiagnosticCampaignRequest,
        ] = {}
        self._start_continuation_claims: dict[str, str] = {}

    def find_command(
        self,
        command_id: str,
        idempotency_key: str,
    ) -> DiagnosticTaskCommandRecord | None:
        existing = self._commands_by_id.get(
            command_id
        ) or self._commands_by_key.get(idempotency_key)
        if existing is not None:
            return existing
        mutation = self._mutation_commands_by_id.get(
            command_id
        ) or self._mutation_commands_by_key.get(idempotency_key)
        if mutation is None:
            return None
        return DiagnosticTaskCommandRecord(
            command_id=mutation.command_id,
            idempotency_key=mutation.idempotency_key,
            command_content_id=mutation.command_content_id,
            task_id=mutation.task_id,
            task_handle_id=mutation.task_handle_id,
        )

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
        existing = self.find_command(
            record.command_id,
            record.idempotency_key,
        )
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
        for task in tuple(self._tasks.values()):
            for handle in task.task_handles:
                if (
                    handle.task_handle_id in self._validations_by_handle
                    and handle.phase is DiagnosticTaskHandlePhase.QUEUED
                ):
                    self.complete_validation(
                        handle.task_handle_id,
                        updated_at,
                    )

    def find_mutation_command(
        self,
        command_id: str,
        idempotency_key: str,
    ) -> DiagnosticTaskMutationCommandRecord | None:
        existing = self._mutation_commands_by_id.get(
            command_id
        ) or self._mutation_commands_by_key.get(idempotency_key)
        if existing is not None:
            return existing
        creation = self._commands_by_id.get(
            command_id
        ) or self._commands_by_key.get(idempotency_key)
        if creation is None:
            return None
        return DiagnosticTaskMutationCommandRecord(
            command_id=creation.command_id,
            idempotency_key=creation.idempotency_key,
            command_type="create_diagnostic_task",
            command_content_id=creation.command_content_id,
            task_id=creation.task_id,
            task_handle_id=creation.task_handle_id,
            disposition=(
                DiagnosticTaskCreationDisposition.ASYNCHRONOUS_ACCEPTANCE
            ),
            message="Diagnostic Task creation accepted.",
            current_revision=self._tasks[creation.task_id].revision,
        )

    def pending_start_requests(
        self,
    ) -> tuple[StartFormalDiagnosticCampaignRequest, ...]:
        return tuple(
            request
            for handle_id, request in self._pending_start_requests.items()
            if (
                (task := self._tasks.get(request.task_id)) is not None
                and task.lifecycle is DiagnosticTaskLifecycle.QUEUED
                and any(
                    handle.task_handle_id == handle_id
                    and handle.phase is DiagnosticTaskHandlePhase.QUEUED
                    for handle in task.task_handles
                )
            )
        )

    def accept_revision(
        self,
        *,
        record: DiagnosticTaskMutationCommandRecord,
        command_json: str,
        task: DiagnosticTaskSnapshot,
        expected_revision: int,
    ) -> bool:
        del command_json
        if (
            self.find_mutation_command(
                record.command_id,
                record.idempotency_key,
            )
            is not None
        ):
            return False
        current = self._tasks.get(task.task_id)
        if (
            current is None
            or current.revision != expected_revision
            or current.lifecycle
            not in {
                DiagnosticTaskLifecycle.DRAFT,
                DiagnosticTaskLifecycle.AWAITING_APPROVAL,
                DiagnosticTaskLifecycle.APPROVED,
            }
            or current.campaign_handoff is not None
        ):
            return False
        self._tasks[task.task_id] = task
        self._store_mutation(record)
        return True

    def accept_validation(
        self,
        *,
        record: DiagnosticTaskMutationCommandRecord,
        command_json: str,
        task: DiagnosticTaskSnapshot,
        validation: DiagnosticTaskValidationSnapshot,
        queued_handle: DiagnosticTaskHandleSnapshot,
        expected_revision: int,
    ) -> bool:
        del command_json
        if (
            self.find_mutation_command(
                record.command_id,
                record.idempotency_key,
            )
            is not None
        ):
            return False
        current = self._tasks.get(task.task_id)
        if (
            current is None
            or current.revision != expected_revision
            or current.lifecycle
            not in {
                DiagnosticTaskLifecycle.DRAFT,
                DiagnosticTaskLifecycle.AWAITING_APPROVAL,
                DiagnosticTaskLifecycle.APPROVED,
            }
            or current.campaign_handoff is not None
        ):
            return False
        self._tasks[task.task_id] = replace(
            task,
            validation=validation,
            task_handles=(*task.task_handles, queued_handle),
        )
        self._validations_by_handle[queued_handle.task_handle_id] = validation
        self._store_mutation(record)
        return True

    def complete_validation(
        self,
        task_handle_id: str,
        updated_at: datetime,
    ) -> None:
        for task_id, task in tuple(self._tasks.items()):
            handle = next(
                (
                    candidate
                    for candidate in task.task_handles
                    if candidate.task_handle_id == task_handle_id
                ),
                None,
            )
            if handle is None:
                continue
            if handle.phase is DiagnosticTaskHandlePhase.COMPLETED:
                return
            if handle.phase is not DiagnosticTaskHandlePhase.QUEUED:
                raise ValueError("Terminal Diagnostic TaskHandle cannot regress")
            validation = self._validations_by_handle.get(task_handle_id)
            if validation is None:
                raise ValueError(
                    "Validation TaskHandle is not bound to a validation"
                )
            completed_handle = replace(
                handle,
                phase=DiagnosticTaskHandlePhase.COMPLETED,
                progress=1.0,
                result_code=(
                    "diagnostic_task_configuration_valid"
                    if validation.state is DiagnosticTaskValidationState.VALID
                    else "diagnostic_task_configuration_invalid"
                ),
                updated_at=updated_at,
            )
            self._tasks[task_id] = replace(
                task,
                task_handles=tuple(
                    completed_handle
                    if candidate.task_handle_id == task_handle_id
                    else candidate
                    for candidate in task.task_handles
                ),
                updated_at=updated_at,
            )
            return
        raise KeyError(
            f"Unknown validation Diagnostic TaskHandle {task_handle_id!r}"
        )

    def accept_approval(
        self,
        *,
        record: DiagnosticTaskMutationCommandRecord,
        command_json: str,
        task: DiagnosticTaskSnapshot,
        approval: DiagnosticTaskApprovalSnapshot,
        expected_revision: int,
    ) -> bool:
        del command_json
        if (
            self.find_mutation_command(
                record.command_id,
                record.idempotency_key,
            )
            is not None
        ):
            return False
        current = self._tasks.get(task.task_id)
        if (
            current is None
            or current.revision != expected_revision
            or current.lifecycle is not DiagnosticTaskLifecycle.AWAITING_APPROVAL
            or current.validation is None
            or current.validation.validation_id != approval.validation_id
            or current.validation.validation_revision
            != approval.validation_revision
            or current.validation.task_revision != approval.task_revision
            or current.validation.configuration_content_id
            != approval.configuration_content_id
            or current.validation.state is not DiagnosticTaskValidationState.VALID
            or not any(
                handle.task_handle_id
                == current.validation.task_handle_id
                and handle.phase is DiagnosticTaskHandlePhase.COMPLETED
                and handle.result_code
                == "diagnostic_task_configuration_valid"
                for handle in current.task_handles
            )
        ):
            return False
        self._tasks[task.task_id] = replace(task, approval=approval)
        self._store_mutation(record)
        return True

    def accept_start(
        self,
        *,
        record: DiagnosticTaskMutationCommandRecord,
        command_json: str,
        task: DiagnosticTaskSnapshot,
        queued_handle: DiagnosticTaskHandleSnapshot,
        expected_revision: int,
    ) -> bool:
        del command_json
        if (
            self.find_mutation_command(
                record.command_id,
                record.idempotency_key,
            )
            is not None
        ):
            return False
        current = self._tasks.get(task.task_id)
        if (
            current is None
            or current.revision != expected_revision
            or current.lifecycle is not DiagnosticTaskLifecycle.APPROVED
            or current.approval is None
            or current.approval.task_revision != expected_revision
            or current.campaign_handoff is not None
        ):
            return False
        self._tasks[task.task_id] = replace(
            task,
            task_handles=(*task.task_handles, queued_handle),
        )
        self._store_mutation(record)
        self._pending_start_requests[queued_handle.task_handle_id] = (
            StartFormalDiagnosticCampaignRequest(
                command_id=record.command_id,
                idempotency_key=record.idempotency_key,
                task_id=record.task_id,
                expected_revision=expected_revision,
                approved_revision=expected_revision,
            )
        )
        return True

    def claim_start_continuation(
        self,
        task_handle_id: str,
        continuation_claim_id: str,
        claimed_at: datetime,
    ) -> bool:
        del claimed_at
        queued = any(
            handle.task_handle_id == task_handle_id
            and handle.phase is DiagnosticTaskHandlePhase.QUEUED
            for task in self._tasks.values()
            for handle in task.task_handles
        )
        if not queued:
            return False
        existing = self._start_continuation_claims.setdefault(
            task_handle_id,
            continuation_claim_id,
        )
        return existing == continuation_claim_id

    def release_start_continuation(
        self,
        task_handle_id: str,
        continuation_claim_id: str,
    ) -> None:
        if (
            self._start_continuation_claims.get(task_handle_id)
            == continuation_claim_id
        ):
            self._start_continuation_claims.pop(task_handle_id, None)

    def reset_start_continuation_claims(self) -> None:
        self._start_continuation_claims.clear()

    def complete_start(
        self,
        task_handle_id: str,
        continuation_claim_id: str,
        handoff: DiagnosticTaskCampaignHandoffSnapshot,
        updated_at: datetime,
    ) -> None:
        for task_id, task in tuple(self._tasks.items()):
            handle = next(
                (
                    candidate
                    for candidate in task.task_handles
                    if candidate.task_handle_id == task_handle_id
                ),
                None,
            )
            if handle is None:
                continue
            if (
                handle.phase is DiagnosticTaskHandlePhase.COMPLETED
                and task.campaign_handoff == handoff
            ):
                return
            if (
                self._start_continuation_claims.get(task_handle_id)
                != continuation_claim_id
            ):
                raise ValueError(
                    "Campaign start continuation is not owned by this claim"
                )
            if handle.phase is not DiagnosticTaskHandlePhase.QUEUED:
                raise ValueError("Terminal Diagnostic TaskHandle cannot regress")
            completed = replace(
                handle,
                phase=DiagnosticTaskHandlePhase.COMPLETED,
                progress=1.0,
                result_code="formal_diagnostic_campaign_started",
                cancelable=False,
                updated_at=updated_at,
            )
            self._tasks[task_id] = replace(
                task,
                lifecycle=DiagnosticTaskLifecycle.RUNNING,
                task_handles=tuple(
                    completed
                    if candidate.task_handle_id == task_handle_id
                    else candidate
                    for candidate in task.task_handles
                ),
                campaign_handoff=handoff,
                updated_at=updated_at,
            )
            self._pending_start_requests.pop(task_handle_id, None)
            self._start_continuation_claims.pop(task_handle_id, None)
            return
        raise KeyError(
            f"Unknown Campaign start Diagnostic TaskHandle {task_handle_id!r}"
        )

    def _store_mutation(
        self,
        record: DiagnosticTaskMutationCommandRecord,
    ) -> None:
        self._mutation_commands_by_id[record.command_id] = record
        self._mutation_commands_by_key[record.idempotency_key] = record


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
                    "task_id, task_handle_id FROM ("
                    "SELECT command_id, idempotency_key, command_content_id, "
                    "task_id, task_handle_id FROM diagnostic_task_commands "
                    "UNION ALL "
                    "SELECT command_id, idempotency_key, command_content_id, "
                    "task_id, task_handle_id "
                    "FROM diagnostic_task_mutation_commands"
                    ") command_history "
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
                self._reserve_command_identity(
                    connection,
                    command_id=record.command_id,
                    idempotency_key=record.idempotency_key,
                    command_type="create_diagnostic_task",
                    command_content_id=record.command_content_id,
                    task_id=record.task_id,
                    task_handle_id=record.task_handle_id,
                )
                connection.execute(
                    text(
                        "INSERT INTO diagnostic_task_configuration_revisions ("
                        "task_id, revision, configuration_content_id, "
                        "configuration_json, accepted_command_id, created_at_utc"
                        ") VALUES ("
                        ":task_id, :revision, :configuration_content_id, "
                        ":configuration_json, :accepted_command_id, "
                        ":created_at_utc)"
                    ),
                    {
                        "task_id": task.task_id,
                        "revision": task.revision,
                        "configuration_content_id": (
                            task.configuration.content_identity
                        ),
                        "configuration_json": _canonical_json(
                            task.configuration.to_storage_dict()
                        ),
                        "accepted_command_id": record.command_id,
                        "created_at_utc": task.created_at.isoformat(),
                    },
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
            validation_row = connection.execute(
                text(
                    "SELECT validation_id, validation_revision, task_id, "
                    "task_revision, configuration_content_id, state, "
                    "findings_json, policy_identities_json, task_handle_id, "
                    "validated_at_utc FROM diagnostic_task_validations "
                    "WHERE task_id = :task_id AND invalidated_at_utc IS NULL "
                    "ORDER BY validated_at_utc DESC, validation_id DESC LIMIT 1"
                ),
                {"task_id": task_id},
            ).mappings().one_or_none()
            approval_row = connection.execute(
                text(
                    "SELECT approval_id, task_id, task_revision, "
                    "configuration_content_id, validation_id, "
                    "validation_revision, actor_id, policy_identities_json, "
                    "approved_at_utc FROM diagnostic_task_approvals "
                    "WHERE task_id = :task_id AND invalidated_at_utc IS NULL "
                    "ORDER BY approved_at_utc DESC, approval_id DESC LIMIT 1"
                ),
                {"task_id": task_id},
            ).mappings().one_or_none()
            handoff_row = connection.execute(
                text(
                    "SELECT task_id, campaign_id, handoff_json, "
                    "updated_at_utc "
                    "FROM diagnostic_task_campaign_handoffs "
                    "WHERE task_id = :task_id"
                ),
                {"task_id": task_id},
            ).mappings().one_or_none()
        return _task_from_rows(
            task_row,
            handle_rows,
            validation_row=validation_row,
            approval_row=approval_row,
            handoff_row=handoff_row,
        )

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
            connection.execute(
                text(
                    "INSERT INTO diagnostic_task_configuration_revisions ("
                    "task_id, revision, configuration_content_id, "
                    "configuration_json, accepted_command_id, created_at_utc"
                    ") SELECT task_id, revision, configuration_content_id, "
                    "configuration_json, NULL, updated_at_utc "
                    "FROM diagnostic_tasks WHERE task_id = :task_id "
                    "AND NOT EXISTS ("
                    "SELECT 1 FROM diagnostic_task_configuration_revisions r "
                    "WHERE r.task_id = :task_id AND r.revision = 2)"
                ),
                {"task_id": task_id},
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
            validation_handle_ids = tuple(
                str(value)
                for value in connection.execute(
                    text(
                        "SELECT h.task_handle_id "
                        "FROM diagnostic_task_handles h "
                        "JOIN diagnostic_task_validations v "
                        "ON v.task_handle_id = h.task_handle_id "
                        "WHERE h.phase = :phase"
                    ),
                    {"phase": DiagnosticTaskHandlePhase.QUEUED.value},
                ).scalars()
            )
        for task_id in task_ids:
            self.complete_creation(task_id, updated_at)
        for task_handle_id in validation_handle_ids:
            self.complete_validation(task_handle_id, updated_at)

    def find_mutation_command(
        self,
        command_id: str,
        idempotency_key: str,
    ) -> DiagnosticTaskMutationCommandRecord | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT command_id, idempotency_key, command_type, "
                    "command_content_id, task_id, task_handle_id, disposition, "
                    "message, current_revision FROM ("
                    "SELECT command_id, idempotency_key, command_type, "
                    "command_content_id, task_id, task_handle_id, disposition, "
                    "message, current_revision "
                    "FROM diagnostic_task_mutation_commands "
                    "UNION ALL "
                    "SELECT c.command_id, c.idempotency_key, c.command_type, "
                    "c.command_content_id, c.task_id, c.task_handle_id, "
                    "c.disposition, 'Diagnostic Task creation accepted.' "
                    "AS message, t.revision AS current_revision "
                    "FROM diagnostic_task_commands c "
                    "JOIN diagnostic_tasks t ON t.task_id = c.task_id"
                    ") command_history "
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
        return None if row is None else _mutation_command_record(row)

    def pending_start_requests(
        self,
    ) -> tuple[StartFormalDiagnosticCampaignRequest, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT m.command_json "
                    "FROM diagnostic_task_mutation_commands m "
                    "JOIN diagnostic_tasks t ON t.task_id = m.task_id "
                    "JOIN diagnostic_task_handles h "
                    "ON h.task_handle_id = m.task_handle_id "
                    "WHERE m.command_type = "
                    "'start_formal_diagnostic_campaign' "
                    "AND t.lifecycle = :task_lifecycle "
                    "AND h.phase = :handle_phase "
                    "AND NOT EXISTS ("
                    "SELECT 1 FROM diagnostic_task_campaign_handoffs d "
                    "WHERE d.task_id = t.task_id) "
                    "ORDER BY m.accepted_at_utc, m.command_id"
                ),
                {
                    "task_lifecycle": DiagnosticTaskLifecycle.QUEUED.value,
                    "handle_phase": DiagnosticTaskHandlePhase.QUEUED.value,
                },
            ).mappings()
            requests: list[StartFormalDiagnosticCampaignRequest] = []
            for row in rows:
                payload = json.loads(str(row["command_json"]))
                if not isinstance(payload, dict):
                    raise TypeError(
                        "Persisted Campaign start command must be an object"
                    )
                requests.append(
                    StartFormalDiagnosticCampaignRequest(
                        command_id=str(payload["command_id"]),
                        idempotency_key=str(payload["idempotency_key"]),
                        task_id=str(payload["task_id"]),
                        expected_revision=int(
                            cast(str | int, payload["expected_revision"])
                        ),
                        approved_revision=int(
                            cast(str | int, payload["approved_revision"])
                        ),
                    )
                )
        return tuple(requests)

    def accept_revision(
        self,
        *,
        record: DiagnosticTaskMutationCommandRecord,
        command_json: str,
        task: DiagnosticTaskSnapshot,
        expected_revision: int,
    ) -> bool:
        with self._engine.begin() as connection:
            updated = connection.execute(
                text(
                    "UPDATE diagnostic_tasks SET revision = :revision, "
                    "lifecycle = :lifecycle, "
                    "configuration_content_id = :configuration_content_id, "
                    "configuration_json = :configuration_json, "
                    "updated_at_utc = :updated_at_utc "
                    "WHERE task_id = :task_id "
                    "AND revision = :expected_revision "
                    "AND lifecycle IN ("
                    ":draft_lifecycle, :awaiting_lifecycle, "
                    ":approved_lifecycle) "
                    "AND NOT EXISTS ("
                    "SELECT 1 FROM diagnostic_task_campaign_handoffs h "
                    "WHERE h.task_id = :task_id)"
                ),
                {
                    "revision": task.revision,
                    "lifecycle": task.lifecycle.value,
                    "configuration_content_id": (
                        task.configuration.content_identity
                    ),
                    "configuration_json": _canonical_json(
                        task.configuration.to_storage_dict()
                    ),
                    "updated_at_utc": task.updated_at.isoformat(),
                    "task_id": task.task_id,
                    "expected_revision": expected_revision,
                    "draft_lifecycle": DiagnosticTaskLifecycle.DRAFT.value,
                    "awaiting_lifecycle": (
                        DiagnosticTaskLifecycle.AWAITING_APPROVAL.value
                    ),
                    "approved_lifecycle": (
                        DiagnosticTaskLifecycle.APPROVED.value
                    ),
                },
            )
            if updated.rowcount != 1:
                return False
            connection.execute(
                text(
                    "UPDATE diagnostic_task_validations "
                    "SET invalidated_at_utc = :invalidated_at_utc "
                    "WHERE task_id = :task_id AND invalidated_at_utc IS NULL"
                ),
                {
                    "invalidated_at_utc": task.updated_at.isoformat(),
                    "task_id": task.task_id,
                },
            )
            connection.execute(
                text(
                    "UPDATE diagnostic_task_approvals "
                    "SET invalidated_at_utc = :invalidated_at_utc "
                    "WHERE task_id = :task_id AND invalidated_at_utc IS NULL"
                ),
                {
                    "invalidated_at_utc": task.updated_at.isoformat(),
                    "task_id": task.task_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO diagnostic_task_configuration_revisions ("
                    "task_id, revision, configuration_content_id, "
                    "configuration_json, accepted_command_id, created_at_utc"
                    ") VALUES ("
                    ":task_id, :revision, :configuration_content_id, "
                    ":configuration_json, :accepted_command_id, :created_at_utc)"
                ),
                {
                    "task_id": task.task_id,
                    "revision": task.revision,
                    "configuration_content_id": (
                        task.configuration.content_identity
                    ),
                    "configuration_json": _canonical_json(
                        task.configuration.to_storage_dict()
                    ),
                    "accepted_command_id": record.command_id,
                    "created_at_utc": task.updated_at.isoformat(),
                },
            )
            self._insert_mutation_command(
                connection,
                record=record,
                command_json=command_json,
            )
        return True

    def accept_validation(
        self,
        *,
        record: DiagnosticTaskMutationCommandRecord,
        command_json: str,
        task: DiagnosticTaskSnapshot,
        validation: DiagnosticTaskValidationSnapshot,
        queued_handle: DiagnosticTaskHandleSnapshot,
        expected_revision: int,
    ) -> bool:
        with self._engine.begin() as connection:
            updated = connection.execute(
                text(
                    "UPDATE diagnostic_tasks SET lifecycle = :lifecycle, "
                    "updated_at_utc = :updated_at_utc "
                    "WHERE task_id = :task_id "
                    "AND revision = :expected_revision "
                    "AND lifecycle IN ("
                    ":draft_lifecycle, :awaiting_lifecycle, "
                    ":approved_lifecycle) "
                    "AND NOT EXISTS ("
                    "SELECT 1 FROM diagnostic_task_campaign_handoffs h "
                    "WHERE h.task_id = :task_id)"
                ),
                {
                    "lifecycle": task.lifecycle.value,
                    "updated_at_utc": task.updated_at.isoformat(),
                    "task_id": task.task_id,
                    "expected_revision": expected_revision,
                    "draft_lifecycle": DiagnosticTaskLifecycle.DRAFT.value,
                    "awaiting_lifecycle": (
                        DiagnosticTaskLifecycle.AWAITING_APPROVAL.value
                    ),
                    "approved_lifecycle": (
                        DiagnosticTaskLifecycle.APPROVED.value
                    ),
                },
            )
            if updated.rowcount != 1:
                return False
            connection.execute(
                text(
                    "UPDATE diagnostic_task_validations "
                    "SET invalidated_at_utc = :invalidated_at_utc "
                    "WHERE task_id = :task_id AND invalidated_at_utc IS NULL"
                ),
                {
                    "invalidated_at_utc": validation.validated_at.isoformat(),
                    "task_id": task.task_id,
                },
            )
            connection.execute(
                text(
                    "UPDATE diagnostic_task_approvals "
                    "SET invalidated_at_utc = :invalidated_at_utc "
                    "WHERE task_id = :task_id AND invalidated_at_utc IS NULL"
                ),
                {
                    "invalidated_at_utc": validation.validated_at.isoformat(),
                    "task_id": task.task_id,
                },
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
                _handle_row(queued_handle),
            )
            connection.execute(
                text(
                    "INSERT INTO diagnostic_task_validations ("
                    "validation_id, validation_revision, task_id, task_revision, "
                    "configuration_content_id, state, findings_json, "
                    "policy_identities_json, task_handle_id, validated_at_utc, "
                    "invalidated_at_utc"
                    ") VALUES ("
                    ":validation_id, :validation_revision, :task_id, "
                    ":task_revision, :configuration_content_id, :state, "
                    ":findings_json, :policy_identities_json, :task_handle_id, "
                    ":validated_at_utc, NULL)"
                ),
                _validation_row(validation),
            )
            self._insert_mutation_command(
                connection,
                record=record,
                command_json=command_json,
            )
        return True

    def complete_validation(
        self,
        task_handle_id: str,
        updated_at: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT h.phase, h.task_id, v.state "
                    "FROM diagnostic_task_handles h "
                    "JOIN diagnostic_task_validations v "
                    "ON v.task_handle_id = h.task_handle_id "
                    "WHERE h.task_handle_id = :task_handle_id"
                ),
                {"task_handle_id": task_handle_id},
            ).mappings().one_or_none()
            if row is None:
                raise KeyError(
                    "Unknown active validation Diagnostic TaskHandle "
                    f"{task_handle_id!r}"
                )
            phase = str(row["phase"])
            if phase == DiagnosticTaskHandlePhase.COMPLETED.value:
                return
            if phase != DiagnosticTaskHandlePhase.QUEUED.value:
                raise ValueError("Terminal Diagnostic TaskHandle cannot regress")
            state = DiagnosticTaskValidationState(str(row["state"]))
            updated_at_utc = updated_at.isoformat()
            updated = connection.execute(
                text(
                    "UPDATE diagnostic_task_handles SET phase = :phase, "
                    "progress_value = 1.0, result_code = :result_code, "
                    "cancelable = 0, updated_at_utc = :updated_at_utc "
                    "WHERE task_handle_id = :task_handle_id "
                    "AND phase = :expected_phase"
                ),
                {
                    "phase": DiagnosticTaskHandlePhase.COMPLETED.value,
                    "result_code": (
                        "diagnostic_task_configuration_valid"
                        if state is DiagnosticTaskValidationState.VALID
                        else "diagnostic_task_configuration_invalid"
                    ),
                    "updated_at_utc": updated_at_utc,
                    "task_handle_id": task_handle_id,
                    "expected_phase": DiagnosticTaskHandlePhase.QUEUED.value,
                },
            )
            if updated.rowcount != 1:
                raise ValueError(
                    "Validation Diagnostic TaskHandle changed concurrently"
                )
            connection.execute(
                text(
                    "UPDATE diagnostic_tasks SET updated_at_utc = :updated_at_utc "
                    "WHERE task_id = :task_id"
                ),
                {
                    "updated_at_utc": updated_at_utc,
                    "task_id": str(row["task_id"]),
                },
            )

    def accept_approval(
        self,
        *,
        record: DiagnosticTaskMutationCommandRecord,
        command_json: str,
        task: DiagnosticTaskSnapshot,
        approval: DiagnosticTaskApprovalSnapshot,
        expected_revision: int,
    ) -> bool:
        with self._engine.begin() as connection:
            updated = connection.execute(
                text(
                    "UPDATE diagnostic_tasks SET lifecycle = :lifecycle, "
                    "updated_at_utc = :updated_at_utc "
                    "WHERE task_id = :task_id "
                    "AND revision = :expected_revision "
                    "AND lifecycle = :expected_lifecycle "
                    "AND EXISTS ("
                    "SELECT 1 FROM diagnostic_task_validations v "
                    "WHERE v.validation_id = :validation_id "
                    "AND v.validation_revision = :validation_revision "
                    "AND v.task_id = :task_id "
                    "AND v.task_revision = :expected_revision "
                    "AND v.configuration_content_id = "
                    ":configuration_content_id "
                    "AND v.state = :validation_state "
                    "AND v.invalidated_at_utc IS NULL "
                    "AND EXISTS ("
                    "SELECT 1 FROM diagnostic_task_handles h "
                    "WHERE h.task_handle_id = v.task_handle_id "
                    "AND h.phase = :validation_handle_phase "
                    "AND h.result_code = :validation_result_code))"
                ),
                {
                    "lifecycle": task.lifecycle.value,
                    "updated_at_utc": task.updated_at.isoformat(),
                    "task_id": task.task_id,
                    "expected_revision": expected_revision,
                    "expected_lifecycle": (
                        DiagnosticTaskLifecycle.AWAITING_APPROVAL.value
                    ),
                    "validation_id": approval.validation_id,
                    "validation_revision": approval.validation_revision,
                    "configuration_content_id": (
                        approval.configuration_content_id
                    ),
                    "validation_state": (
                        DiagnosticTaskValidationState.VALID.value
                    ),
                    "validation_handle_phase": (
                        DiagnosticTaskHandlePhase.COMPLETED.value
                    ),
                    "validation_result_code": (
                        "diagnostic_task_configuration_valid"
                    ),
                },
            )
            if updated.rowcount != 1:
                return False
            connection.execute(
                text(
                    "INSERT INTO diagnostic_task_approvals ("
                    "approval_id, task_id, task_revision, "
                    "configuration_content_id, validation_id, "
                    "validation_revision, actor_id, policy_identities_json, "
                    "approved_at_utc, invalidated_at_utc"
                    ") VALUES ("
                    ":approval_id, :task_id, :task_revision, "
                    ":configuration_content_id, :validation_id, "
                    ":validation_revision, :actor_id, "
                    ":policy_identities_json, :approved_at_utc, NULL)"
                ),
                _approval_row(approval),
            )
            self._insert_mutation_command(
                connection,
                record=record,
                command_json=command_json,
            )
        return True

    def accept_start(
        self,
        *,
        record: DiagnosticTaskMutationCommandRecord,
        command_json: str,
        task: DiagnosticTaskSnapshot,
        queued_handle: DiagnosticTaskHandleSnapshot,
        expected_revision: int,
    ) -> bool:
        with self._engine.begin() as connection:
            updated = connection.execute(
                text(
                    "UPDATE diagnostic_tasks SET lifecycle = :lifecycle, "
                    "updated_at_utc = :updated_at_utc "
                    "WHERE task_id = :task_id "
                    "AND revision = :expected_revision "
                    "AND lifecycle = :expected_lifecycle "
                    "AND NOT EXISTS ("
                    "SELECT 1 FROM diagnostic_task_campaign_handoffs h "
                    "WHERE h.task_id = :task_id"
                    ") AND EXISTS ("
                    "SELECT 1 FROM diagnostic_task_approvals a "
                    "WHERE a.task_id = :task_id "
                    "AND a.task_revision = :expected_revision "
                    "AND a.invalidated_at_utc IS NULL)"
                ),
                {
                    "lifecycle": task.lifecycle.value,
                    "updated_at_utc": task.updated_at.isoformat(),
                    "task_id": task.task_id,
                    "expected_revision": expected_revision,
                    "expected_lifecycle": (
                        DiagnosticTaskLifecycle.APPROVED.value
                    ),
                },
            )
            if updated.rowcount != 1:
                return False
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
                _handle_row(queued_handle),
            )
            self._insert_mutation_command(
                connection,
                record=record,
                command_json=command_json,
            )
        return True

    def claim_start_continuation(
        self,
        task_handle_id: str,
        continuation_claim_id: str,
        claimed_at: datetime,
    ) -> bool:
        with self._engine.begin() as connection:
            claimed = connection.execute(
                text(
                    "UPDATE diagnostic_task_handles "
                    "SET start_continuation_claim_id = "
                    ":continuation_claim_id, "
                    "start_continuation_claimed_at_utc = :claimed_at_utc "
                    "WHERE task_handle_id = :task_handle_id "
                    "AND phase = :expected_phase "
                    "AND start_continuation_claim_id IS NULL"
                ),
                {
                    "continuation_claim_id": continuation_claim_id,
                    "claimed_at_utc": claimed_at.isoformat(),
                    "task_handle_id": task_handle_id,
                    "expected_phase": DiagnosticTaskHandlePhase.QUEUED.value,
                },
            )
        return claimed.rowcount == 1

    def release_start_continuation(
        self,
        task_handle_id: str,
        continuation_claim_id: str,
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE diagnostic_task_handles "
                    "SET start_continuation_claim_id = NULL, "
                    "start_continuation_claimed_at_utc = NULL "
                    "WHERE task_handle_id = :task_handle_id "
                    "AND phase = :expected_phase "
                    "AND start_continuation_claim_id = "
                    ":continuation_claim_id"
                ),
                {
                    "task_handle_id": task_handle_id,
                    "expected_phase": DiagnosticTaskHandlePhase.QUEUED.value,
                    "continuation_claim_id": continuation_claim_id,
                },
            )

    def reset_start_continuation_claims(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE diagnostic_task_handles "
                    "SET start_continuation_claim_id = NULL, "
                    "start_continuation_claimed_at_utc = NULL "
                    "WHERE phase = :expected_phase "
                    "AND start_continuation_claim_id IS NOT NULL"
                ),
                {
                    "expected_phase": DiagnosticTaskHandlePhase.QUEUED.value,
                },
            )

    def complete_start(
        self,
        task_handle_id: str,
        continuation_claim_id: str,
        handoff: DiagnosticTaskCampaignHandoffSnapshot,
        updated_at: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT h.phase, h.task_id, t.lifecycle, "
                    "h.start_continuation_claim_id "
                    "FROM diagnostic_task_handles h "
                    "JOIN diagnostic_tasks t ON t.task_id = h.task_id "
                    "WHERE h.task_handle_id = :task_handle_id"
                ),
                {"task_handle_id": task_handle_id},
            ).mappings().one_or_none()
            if row is None:
                raise KeyError(
                    "Unknown Campaign start Diagnostic TaskHandle "
                    f"{task_handle_id!r}"
                )
            task_id = str(row["task_id"])
            phase = DiagnosticTaskHandlePhase(str(row["phase"]))
            existing = connection.execute(
                text(
                    "SELECT campaign_id, handoff_json "
                    "FROM diagnostic_task_campaign_handoffs "
                    "WHERE task_id = :task_id"
                ),
                {"task_id": task_id},
            ).mappings().one_or_none()
            handoff_json = _canonical_json(handoff.to_storage_dict())
            if phase is DiagnosticTaskHandlePhase.COMPLETED:
                if (
                    existing is not None
                    and str(existing["campaign_id"]) == handoff.campaign_id
                    and str(existing["handoff_json"]) == handoff_json
                ):
                    return
                raise ValueError(
                    "Completed Campaign start handoff cannot be replaced"
                )
            if (
                str(row["start_continuation_claim_id"])
                != continuation_claim_id
            ):
                raise ValueError(
                    "Campaign start continuation is not owned by this claim"
                )
            if phase is not DiagnosticTaskHandlePhase.QUEUED:
                raise ValueError("Terminal Diagnostic TaskHandle cannot regress")
            if existing is not None:
                raise ValueError("Diagnostic Task already has a Campaign handoff")
            updated_at_utc = updated_at.isoformat()
            connection.execute(
                text(
                    "INSERT INTO diagnostic_task_campaign_handoffs ("
                    "task_id, campaign_id, handoff_json, updated_at_utc"
                    ") VALUES ("
                    ":task_id, :campaign_id, :handoff_json, :updated_at_utc)"
                ),
                {
                    "task_id": task_id,
                    "campaign_id": handoff.campaign_id,
                    "handoff_json": handoff_json,
                    "updated_at_utc": updated_at_utc,
                },
            )
            updated_handle = connection.execute(
                text(
                    "UPDATE diagnostic_task_handles SET phase = :phase, "
                    "progress_value = 1.0, result_code = :result_code, "
                    "cancelable = 0, updated_at_utc = :updated_at_utc, "
                    "start_continuation_claim_id = NULL, "
                    "start_continuation_claimed_at_utc = NULL "
                    "WHERE task_handle_id = :task_handle_id "
                    "AND phase = :expected_phase "
                    "AND start_continuation_claim_id = "
                    ":continuation_claim_id"
                ),
                {
                    "phase": DiagnosticTaskHandlePhase.COMPLETED.value,
                    "result_code": "formal_diagnostic_campaign_started",
                    "updated_at_utc": updated_at_utc,
                    "task_handle_id": task_handle_id,
                    "expected_phase": DiagnosticTaskHandlePhase.QUEUED.value,
                    "continuation_claim_id": continuation_claim_id,
                },
            )
            if updated_handle.rowcount != 1:
                raise ValueError(
                    "Campaign start Diagnostic TaskHandle changed concurrently"
                )
            updated_task = connection.execute(
                text(
                    "UPDATE diagnostic_tasks SET lifecycle = :lifecycle, "
                    "updated_at_utc = :updated_at_utc "
                    "WHERE task_id = :task_id "
                    "AND lifecycle = :expected_lifecycle"
                ),
                {
                    "lifecycle": DiagnosticTaskLifecycle.RUNNING.value,
                    "updated_at_utc": updated_at_utc,
                    "task_id": task_id,
                    "expected_lifecycle": DiagnosticTaskLifecycle.QUEUED.value,
                },
            )
            if updated_task.rowcount != 1:
                raise ValueError(
                    "Campaign start Diagnostic Task changed concurrently"
                )

    @staticmethod
    def _insert_mutation_command(
        connection: Connection,
        *,
        record: DiagnosticTaskMutationCommandRecord,
        command_json: str,
    ) -> None:
        SqlDiagnosticTaskRepository._reserve_command_identity(
            connection,
            command_id=record.command_id,
            idempotency_key=record.idempotency_key,
            command_type=record.command_type,
            command_content_id=record.command_content_id,
            task_id=record.task_id,
            task_handle_id=record.task_handle_id,
        )
        connection.execute(
            text(
                "INSERT INTO diagnostic_task_mutation_commands ("
                "command_id, idempotency_key, command_type, "
                "command_content_id, task_id, task_handle_id, disposition, "
                "message, current_revision, command_json, result_json, "
                "accepted_at_utc"
                ") VALUES ("
                ":command_id, :idempotency_key, :command_type, "
                ":command_content_id, :task_id, :task_handle_id, "
                ":disposition, :message, :current_revision, :command_json, "
                ":result_json, :accepted_at_utc)"
            ),
            {
                "command_id": record.command_id,
                "idempotency_key": record.idempotency_key,
                "command_type": record.command_type,
                "command_content_id": record.command_content_id,
                "task_id": record.task_id,
                "task_handle_id": record.task_handle_id,
                "disposition": record.disposition.value,
                "message": record.message,
                "current_revision": record.current_revision,
                "command_json": command_json,
                "result_json": _canonical_json(
                    {
                        "current_revision": record.current_revision,
                        "disposition": record.disposition.value,
                        "message": record.message,
                        "task_handle_id": record.task_handle_id,
                        "task_id": record.task_id,
                    }
                ),
                "accepted_at_utc": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    def _reserve_command_identity(
        connection: Connection,
        *,
        command_id: str,
        idempotency_key: str,
        command_type: str,
        command_content_id: str,
        task_id: str,
        task_handle_id: str | None,
    ) -> None:
        connection.execute(
            text(
                "INSERT INTO diagnostic_task_command_identities ("
                "command_id, idempotency_key, command_type, "
                "command_content_id, task_id, task_handle_id"
                ") VALUES ("
                ":command_id, :idempotency_key, :command_type, "
                ":command_content_id, :task_id, :task_handle_id)"
            ),
            {
                "command_id": command_id,
                "idempotency_key": idempotency_key,
                "command_type": command_type,
                "command_content_id": command_content_id,
                "task_id": task_id,
                "task_handle_id": task_handle_id,
            },
        )

    def _find_existing(
        self,
        record: DiagnosticTaskCommandRecord,
    ) -> DiagnosticTaskCommandRecord | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT command_id, idempotency_key, command_content_id, "
                    "task_id, task_handle_id FROM ("
                    "SELECT command_id, idempotency_key, command_content_id, "
                    "task_id, task_handle_id FROM diagnostic_task_commands "
                    "UNION ALL "
                    "SELECT command_id, idempotency_key, command_content_id, "
                    "task_id, task_handle_id "
                    "FROM diagnostic_task_mutation_commands"
                    ") command_history "
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
        configuration_validation: Callable[
            [DiagnosticTaskConfiguration],
            tuple[DiagnosticTaskValidationFinding, ...],
        ]
        | None = None,
        validation_policy_provider: Callable[
            [DiagnosticTaskConfiguration],
            tuple[str, ...],
        ]
        | None = None,
    ) -> None:
        self._repository = repository or InMemoryDiagnosticTaskRepository()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._configuration_validator = configuration_validator
        self._configuration_validation = (
            configuration_validation or self._default_validation
        )
        self._validation_policy_provider = (
            validation_policy_provider
            or (lambda _configuration: ("diagnostic-task-validation.v1",))
        )

    def replace_repository(self, repository: DiagnosticTaskRepository) -> None:
        self._repository = repository
        self._repository.reset_start_continuation_claims()
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
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
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
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
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
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
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
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
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

    def pending_start_requests(
        self,
    ) -> tuple[StartFormalDiagnosticCampaignRequest, ...]:
        return self._repository.pending_start_requests()

    def claim_start_continuation(
        self,
        task_handle_id: str,
        continuation_claim_id: str,
    ) -> bool:
        return self._repository.claim_start_continuation(
            task_handle_id,
            continuation_claim_id,
            _aware(self._clock()),
        )

    def release_start_continuation(
        self,
        task_handle_id: str,
        continuation_claim_id: str,
    ) -> None:
        self._repository.release_start_continuation(
            task_handle_id,
            continuation_claim_id,
        )

    def revise_configuration(
        self,
        request: ReviseDiagnosticTaskConfigurationRequest,
    ) -> DiagnosticTaskCommandResult:
        if (
            not request.command_id.strip()
            or not request.idempotency_key.strip()
        ):
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.INVALID_COMMAND,
                message="Command identity and idempotency key are required.",
                current_revision=None,
            )
        command_content_id = request.command_content_identity()
        existing = self._find_existing_mutation(
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            command_content_id=command_content_id,
            task_id=request.task_id,
        )
        if existing is not None:
            return existing
        current = self._read_task_for_command(
            request.command_id,
            request.idempotency_key,
            request.task_id,
        )
        if isinstance(current, DiagnosticTaskCreationResult):
            return current
        if current.revision != request.expected_revision:
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=(
                    DiagnosticTaskCreationRejectionReason.STALE_EXPECTED_REVISION
                ),
                message="Expected revision is stale.",
                current_revision=current.revision,
            )
        locked = self._started_configuration_mutation_rejection(
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            current=current,
        )
        if locked is not None:
            return locked
        if (
            not request.command_id.strip()
            or not request.idempotency_key.strip()
            or request.configuration.content_identity
            != request.configuration.calculated_content_identity()
            or request.configuration == current.configuration
        ):
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.INVALID_COMMAND,
                message="Diagnostic Task correction is invalid.",
                current_revision=current.revision,
            )
        try:
            authoritative = self._configuration_validator(
                request.configuration
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.UNAVAILABLE_INPUT,
                message="Authoritative correction inputs are unavailable.",
                current_revision=current.revision,
                retryable=True,
            )
        if not authoritative:
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.INVALID_COMMAND,
                message="Diagnostic Task correction is not authoritative.",
                current_revision=current.revision,
            )
        now = _aware(self._clock())
        revised = replace(
            current,
            revision=current.revision + 1,
            lifecycle=DiagnosticTaskLifecycle.DRAFT,
            configuration=request.configuration,
            updated_at=now,
            validation=None,
            approval=None,
        )
        record = DiagnosticTaskMutationCommandRecord(
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            command_type="revise_diagnostic_task_configuration",
            command_content_id=command_content_id,
            task_id=request.task_id,
            task_handle_id=None,
            disposition=(
                DiagnosticTaskCreationDisposition.SYNCHRONOUS_COMPLETION
            ),
            message="Diagnostic Task configuration revised.",
            current_revision=revised.revision,
        )
        try:
            accepted = self._repository.accept_revision(
                record=record,
                command_json=_canonical_json(
                    {
                        "command_id": request.command_id,
                        "command_type": record.command_type,
                        "configuration": (
                            request.configuration.to_storage_dict()
                        ),
                        "expected_revision": request.expected_revision,
                        "idempotency_key": request.idempotency_key,
                        "task_id": request.task_id,
                    }
                ),
                task=revised,
                expected_revision=request.expected_revision,
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            existing_after_failure = self._find_existing_mutation(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                command_content_id=command_content_id,
                task_id=request.task_id,
            )
            if existing_after_failure is not None:
                return existing_after_failure
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE,
                message="Diagnostic Task correction could not be persisted.",
                current_revision=current.revision,
                retryable=True,
            )
        if not accepted:
            existing_after_failure = self._find_existing_mutation(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                command_content_id=command_content_id,
                task_id=request.task_id,
            )
            if existing_after_failure is not None:
                return existing_after_failure
            latest = self._read_task_for_command(
                request.command_id,
                request.idempotency_key,
                request.task_id,
            )
            if isinstance(latest, DiagnosticTaskCreationResult):
                return latest
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=(
                    DiagnosticTaskCreationRejectionReason.STALE_EXPECTED_REVISION
                ),
                message="Expected revision is stale.",
                current_revision=latest.revision,
            )
        return self._mutation_result(record)

    def validate_configuration(
        self,
        request: ValidateDiagnosticTaskConfigurationRequest,
    ) -> DiagnosticTaskCommandResult:
        if (
            not request.command_id.strip()
            or not request.idempotency_key.strip()
        ):
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.INVALID_COMMAND,
                message="Command identity and idempotency key are required.",
                current_revision=None,
            )
        command_content_id = request.command_content_identity()
        existing = self._find_existing_mutation(
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            command_content_id=command_content_id,
            task_id=request.task_id,
        )
        if existing is not None:
            return existing
        current = self._read_task_for_command(
            request.command_id,
            request.idempotency_key,
            request.task_id,
        )
        if isinstance(current, DiagnosticTaskCreationResult):
            return current
        if current.revision != request.expected_revision:
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=(
                    DiagnosticTaskCreationRejectionReason.STALE_EXPECTED_REVISION
                ),
                message="Expected revision is stale.",
                current_revision=current.revision,
            )
        locked = self._started_configuration_mutation_rejection(
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            current=current,
        )
        if locked is not None:
            return locked
        try:
            findings = self._configuration_validation(
                current.configuration
            )
            policies = tuple(
                sorted(
                    set(
                        self._validation_policy_provider(
                            current.configuration
                        )
                    )
                )
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.UNAVAILABLE_INPUT,
                message="Diagnostic Task validation inputs are unavailable.",
                current_revision=current.revision,
                retryable=True,
            )
        if not policies:
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.UNAVAILABLE_INPUT,
                message="Diagnostic Task validation policy is unavailable.",
                current_revision=current.revision,
            )
        now = _aware(self._clock())
        validation_id = _stable_identity(
            "diagnostic-task-validation",
            request.command_id,
        )
        handle_id = _stable_identity(
            "diagnostic-task-validation-handle",
            request.command_id,
        )
        state = (
            DiagnosticTaskValidationState.INVALID
            if any(
                finding.severity
                is DiagnosticTaskValidationSeverity.ERROR
                for finding in findings
            )
            else DiagnosticTaskValidationState.VALID
        )
        queued_handle = DiagnosticTaskHandleSnapshot(
            task_handle_id=handle_id,
            task_id=request.task_id,
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
        validation = DiagnosticTaskValidationSnapshot(
            validation_id=validation_id,
            validation_revision=1,
            task_id=request.task_id,
            task_revision=current.revision,
            configuration_content_id=(
                current.configuration.content_identity
            ),
            state=state,
            findings=findings,
            policy_identities=policies,
            task_handle_id=handle_id,
            validated_at=now,
        )
        validated_task = replace(
            current,
            lifecycle=(
                DiagnosticTaskLifecycle.AWAITING_APPROVAL
                if state is DiagnosticTaskValidationState.VALID
                else DiagnosticTaskLifecycle.DRAFT
            ),
            updated_at=now,
            validation=validation,
            approval=None,
        )
        record = DiagnosticTaskMutationCommandRecord(
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            command_type="validate_diagnostic_task_configuration",
            command_content_id=command_content_id,
            task_id=request.task_id,
            task_handle_id=handle_id,
            disposition=(
                DiagnosticTaskCreationDisposition.ASYNCHRONOUS_ACCEPTANCE
            ),
            message="Diagnostic Task validation accepted.",
            current_revision=current.revision,
        )
        try:
            accepted = self._repository.accept_validation(
                record=record,
                command_json=_canonical_json(
                    {
                        "command_id": request.command_id,
                        "command_type": record.command_type,
                        "expected_revision": request.expected_revision,
                        "idempotency_key": request.idempotency_key,
                        "task_id": request.task_id,
                    }
                ),
                task=validated_task,
                validation=validation,
                queued_handle=queued_handle,
                expected_revision=request.expected_revision,
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            existing_after_failure = self._find_existing_mutation(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                command_content_id=command_content_id,
                task_id=request.task_id,
            )
            if existing_after_failure is not None:
                return existing_after_failure
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE,
                message="Diagnostic Task validation could not be persisted.",
                current_revision=current.revision,
                retryable=True,
            )
        if not accepted:
            existing_after_failure = self._find_existing_mutation(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                command_content_id=command_content_id,
                task_id=request.task_id,
            )
            if existing_after_failure is not None:
                return existing_after_failure
            latest = self._read_task_for_command(
                request.command_id,
                request.idempotency_key,
                request.task_id,
            )
            if isinstance(latest, DiagnosticTaskCreationResult):
                return latest
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=(
                    DiagnosticTaskCreationRejectionReason.STALE_EXPECTED_REVISION
                ),
                message="Expected revision is stale.",
                current_revision=latest.revision,
            )
        try:
            self._repository.complete_validation(
                handle_id,
                _aware(self._clock()),
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            # Acceptance and its queued TaskHandle are durable. Application
            # restart recovers the terminal completion without reaccepting.
            pass
        return self._mutation_result(record, task_handle=queued_handle)

    def approve_configuration(
        self,
        request: ApproveDiagnosticTaskConfigurationRequest,
    ) -> DiagnosticTaskCommandResult:
        if (
            not request.command_id.strip()
            or not request.idempotency_key.strip()
        ):
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.INVALID_COMMAND,
                message="Command identity and idempotency key are required.",
                current_revision=None,
            )
        command_content_id = request.command_content_identity()
        existing = self._find_existing_mutation(
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            command_content_id=command_content_id,
            task_id=request.task_id,
        )
        if existing is not None:
            return existing
        current = self._read_task_for_command(
            request.command_id,
            request.idempotency_key,
            request.task_id,
        )
        if isinstance(current, DiagnosticTaskCreationResult):
            return current
        if current.revision != request.expected_revision:
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=(
                    DiagnosticTaskCreationRejectionReason.STALE_EXPECTED_REVISION
                ),
                message="Expected revision is stale.",
                current_revision=current.revision,
            )
        locked = self._started_configuration_mutation_rejection(
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            current=current,
        )
        if locked is not None:
            return locked
        validation = current.validation
        if (
            validation is None
            or validation.validation_id != request.validation_id
            or validation.validation_revision != request.validation_revision
            or validation.task_revision != request.validated_revision
            or validation.configuration_content_id
            != request.configuration_content_id
            or request.validated_revision != current.revision
            or request.configuration_content_id
            != current.configuration.content_identity
        ):
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.STALE_VALIDATION,
                message="Approval requires the exact current validation.",
                current_revision=current.revision,
            )
        validation_handle = next(
            (
                handle
                for handle in current.task_handles
                if handle.task_handle_id == validation.task_handle_id
            ),
            None,
        )
        if (
            validation_handle is not None
            and validation_handle.phase is DiagnosticTaskHandlePhase.QUEUED
        ):
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=(
                    DiagnosticTaskCreationRejectionReason.VALIDATION_PENDING
                ),
                message="Validation completion is still pending.",
                current_revision=current.revision,
                retryable=True,
            )
        if (
            validation_handle is None
            or validation_handle.phase
            is not DiagnosticTaskHandlePhase.COMPLETED
            or (
                validation.state is DiagnosticTaskValidationState.VALID
                and validation_handle.result_code
                != "diagnostic_task_configuration_valid"
            )
        ):
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.STALE_VALIDATION,
                message="Validation TaskHandle is not a completed exact result.",
                current_revision=current.revision,
            )
        if validation.state is not DiagnosticTaskValidationState.VALID:
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.VALIDATION_FAILED,
                message="Only a successfully validated revision can be approved.",
                current_revision=current.revision,
            )
        if current.approval is not None:
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.STALE_APPROVAL,
                message="The current validation is already approved.",
                current_revision=current.revision,
            )
        if not request.actor_id.strip():
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.INVALID_COMMAND,
                message="Approval actor identity is required.",
                current_revision=current.revision,
            )
        now = _aware(self._clock())
        approval = DiagnosticTaskApprovalSnapshot(
            approval_id=_stable_identity(
                "diagnostic-task-approval",
                request.command_id,
            ),
            task_id=request.task_id,
            task_revision=current.revision,
            configuration_content_id=(
                current.configuration.content_identity
            ),
            validation_id=validation.validation_id,
            validation_revision=validation.validation_revision,
            actor_id=request.actor_id,
            policy_identities=validation.policy_identities,
            approved_at=now,
        )
        approved_task = replace(
            current,
            lifecycle=DiagnosticTaskLifecycle.APPROVED,
            updated_at=now,
            approval=approval,
        )
        record = DiagnosticTaskMutationCommandRecord(
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            command_type="approve_diagnostic_task_configuration",
            command_content_id=command_content_id,
            task_id=request.task_id,
            task_handle_id=None,
            disposition=(
                DiagnosticTaskCreationDisposition.SYNCHRONOUS_COMPLETION
            ),
            message="Diagnostic Task configuration approved.",
            current_revision=current.revision,
        )
        try:
            accepted = self._repository.accept_approval(
                record=record,
                command_json=_canonical_json(
                    {
                        "actor_id": request.actor_id,
                        "command_id": request.command_id,
                        "command_type": record.command_type,
                        "configuration_content_id": (
                            request.configuration_content_id
                        ),
                        "expected_revision": request.expected_revision,
                        "idempotency_key": request.idempotency_key,
                        "task_id": request.task_id,
                        "validation_id": request.validation_id,
                        "validation_revision": request.validation_revision,
                        "validated_revision": request.validated_revision,
                    }
                ),
                task=approved_task,
                approval=approval,
                expected_revision=request.expected_revision,
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            existing_after_failure = self._find_existing_mutation(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                command_content_id=command_content_id,
                task_id=request.task_id,
            )
            if existing_after_failure is not None:
                return existing_after_failure
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE,
                message="Diagnostic Task approval could not be persisted.",
                current_revision=current.revision,
                retryable=True,
            )
        if not accepted:
            existing_after_failure = self._find_existing_mutation(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                command_content_id=command_content_id,
                task_id=request.task_id,
            )
            if existing_after_failure is not None:
                return existing_after_failure
            latest = self._read_task_for_command(
                request.command_id,
                request.idempotency_key,
                request.task_id,
            )
            if isinstance(latest, DiagnosticTaskCreationResult):
                return latest
            stale_approval = (
                latest.revision == request.expected_revision
                and latest.approval is not None
            )
            stale_validation = (
                latest.revision == request.expected_revision
                and (
                    latest.validation is None
                    or latest.validation.validation_id
                    != request.validation_id
                    or latest.validation.validation_revision
                    != request.validation_revision
                    or latest.validation.task_revision
                    != request.validated_revision
                    or latest.validation.configuration_content_id
                    != request.configuration_content_id
                    or latest.validation.state
                    is not DiagnosticTaskValidationState.VALID
                )
            )
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=(
                    DiagnosticTaskCreationRejectionReason.STALE_APPROVAL
                    if stale_approval
                    else (
                        DiagnosticTaskCreationRejectionReason.STALE_VALIDATION
                        if stale_validation
                        else (
                            DiagnosticTaskCreationRejectionReason.STALE_EXPECTED_REVISION
                        )
                    )
                ),
                message=(
                    "The current validation is already approved."
                    if stale_approval
                    else (
                        "Approval requires the exact current validation."
                        if stale_validation
                        else "Expected revision is stale."
                    )
                ),
                current_revision=latest.revision,
            )
        return self._mutation_result(record)

    def preflight_start(
        self,
        request: StartFormalDiagnosticCampaignRequest,
    ) -> DiagnosticTaskSnapshot | DiagnosticTaskCommandResult:
        if (
            not request.command_id.strip()
            or not request.idempotency_key.strip()
            or request.expected_revision < 1
            or request.approved_revision < 1
        ):
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.INVALID_COMMAND,
                message=(
                    "Command identity and positive exact revisions are required."
                ),
                current_revision=None,
            )
        command_content_id = request.command_content_identity()
        existing = self._find_existing_mutation(
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            command_content_id=command_content_id,
            task_id=request.task_id,
        )
        if existing is not None:
            return existing
        current = self._read_task_for_command(
            request.command_id,
            request.idempotency_key,
            request.task_id,
        )
        if isinstance(current, DiagnosticTaskCreationResult):
            return current
        if current.revision != request.expected_revision:
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=(
                    DiagnosticTaskCreationRejectionReason.STALE_EXPECTED_REVISION
                ),
                message="Expected revision is stale.",
                current_revision=current.revision,
            )
        approval = current.approval
        if (
            approval is None
            or current.lifecycle is not DiagnosticTaskLifecycle.APPROVED
            or request.approved_revision != current.revision
            or approval.task_revision != request.approved_revision
            or approval.configuration_content_id
            != current.configuration.content_identity
        ):
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.STALE_APPROVAL,
                message="Campaign start requires the exact current approval.",
                current_revision=current.revision,
            )
        layers = tuple(
            selection.layer
            for selection in current.configuration.campaign_case_selections
        )
        formal_shape = (
            layers.count("baseline") == 1
            and layers.count("isolated_sensitivity") >= 12
            and layers.count("compound") >= 1
        )
        try:
            authoritative = self._configuration_validator(
                current.configuration
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            authoritative = False
        if not formal_shape or not authoritative:
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.UNAVAILABLE_INPUT,
                message=(
                    "A complete authoritative Formal Diagnostic Campaign "
                    "configuration is required."
                ),
                current_revision=current.revision,
            )
        return current

    def accept_start(
        self,
        request: StartFormalDiagnosticCampaignRequest,
    ) -> DiagnosticTaskCommandResult:
        preflight = self.preflight_start(request)
        if isinstance(preflight, DiagnosticTaskCreationResult):
            return preflight
        current = preflight
        now = _aware(self._clock())
        handle_id = _stable_identity(
            "diagnostic-task-campaign-start-handle",
            request.command_id,
        )
        queued_handle = DiagnosticTaskHandleSnapshot(
            task_handle_id=handle_id,
            task_id=request.task_id,
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
        queued_task = replace(
            current,
            lifecycle=DiagnosticTaskLifecycle.QUEUED,
            updated_at=now,
        )
        record = DiagnosticTaskMutationCommandRecord(
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            command_type="start_formal_diagnostic_campaign",
            command_content_id=request.command_content_identity(),
            task_id=request.task_id,
            task_handle_id=handle_id,
            disposition=(
                DiagnosticTaskCreationDisposition.ASYNCHRONOUS_ACCEPTANCE
            ),
            message="Formal Diagnostic Campaign start accepted.",
            current_revision=current.revision,
        )
        try:
            accepted = self._repository.accept_start(
                record=record,
                command_json=_canonical_json(
                    {
                        "approved_revision": request.approved_revision,
                        "command_id": request.command_id,
                        "command_type": record.command_type,
                        "expected_revision": request.expected_revision,
                        "idempotency_key": request.idempotency_key,
                        "task_id": request.task_id,
                    }
                ),
                task=queued_task,
                queued_handle=queued_handle,
                expected_revision=request.expected_revision,
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            replay = self._find_existing_mutation(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                command_content_id=request.command_content_identity(),
                task_id=request.task_id,
            )
            if replay is not None:
                return replay
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE,
                message=(
                    "Campaign start command and TaskHandle could not be "
                    "persisted atomically."
                ),
                current_revision=current.revision,
                retryable=True,
            )
        if not accepted:
            replay = self._find_existing_mutation(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                command_content_id=request.command_content_identity(),
                task_id=request.task_id,
            )
            if replay is not None:
                return replay
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.STALE_APPROVAL,
                message="Campaign start requires the exact current approval.",
                current_revision=current.revision,
            )
        return self._mutation_result(
            record,
            task_handle=queued_handle,
        )

    def reject_start_unavailable(
        self,
        request: StartFormalDiagnosticCampaignRequest,
        *,
        message: str,
        retryable: bool = False,
    ) -> DiagnosticTaskCommandResult:
        try:
            current = self._repository.get_task(request.task_id)
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            current = None
        return self._mutation_rejected(
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            task_id=request.task_id,
            reason=DiagnosticTaskCreationRejectionReason.UNAVAILABLE_INPUT,
            message=message,
            current_revision=(
                None if current is None else current.revision
            ),
            retryable=retryable,
        )

    def complete_start(
        self,
        task_handle_id: str,
        continuation_claim_id: str,
        handoff: DiagnosticTaskCampaignHandoffSnapshot,
    ) -> None:
        self._repository.complete_start(
            task_handle_id,
            continuation_claim_id,
            handoff,
            _aware(self._clock()),
        )

    def _started_configuration_mutation_rejection(
        self,
        *,
        command_id: str,
        idempotency_key: str,
        current: DiagnosticTaskSnapshot,
    ) -> DiagnosticTaskCommandResult | None:
        if (
            current.lifecycle
            not in {
                DiagnosticTaskLifecycle.QUEUED,
                DiagnosticTaskLifecycle.RUNNING,
            }
            and current.campaign_handoff is None
        ):
            return None
        return self._mutation_rejected(
            command_id=command_id,
            idempotency_key=idempotency_key,
            task_id=current.task_id,
            reason=DiagnosticTaskCreationRejectionReason.INVALID_COMMAND,
            message=(
                "A Campaign-started Diagnostic Task configuration is immutable."
            ),
            current_revision=current.revision,
        )

    def _find_existing_mutation(
        self,
        *,
        command_id: str,
        idempotency_key: str,
        command_content_id: str,
        task_id: str,
    ) -> DiagnosticTaskCommandResult | None:
        try:
            existing = self._repository.find_mutation_command(
                command_id,
                idempotency_key,
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            return self._mutation_rejected(
                command_id=command_id,
                idempotency_key=idempotency_key,
                task_id=task_id,
                reason=DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE,
                message="Diagnostic Task command history could not be read.",
                current_revision=None,
                retryable=True,
            )
        if existing is None:
            return None
        if (
            existing.command_id == command_id
            and existing.idempotency_key != idempotency_key
        ):
            return self._mutation_rejected(
                command_id=command_id,
                idempotency_key=idempotency_key,
                task_id=task_id,
                reason=(
                    DiagnosticTaskCreationRejectionReason.COMMAND_IDENTITY_CONFLICT
                ),
                message="Command identity is bound to another idempotency key.",
                current_revision=existing.current_revision,
            )
        if (
            existing.command_content_id != command_content_id
            or existing.task_id != task_id
        ):
            return self._mutation_rejected(
                command_id=command_id,
                idempotency_key=idempotency_key,
                task_id=task_id,
                reason=(
                    DiagnosticTaskCreationRejectionReason.COMMAND_IDENTITY_CONFLICT
                    if existing.command_id == command_id
                    else DiagnosticTaskCreationRejectionReason.IDEMPOTENCY_CONFLICT
                ),
                message="Command identity or idempotency content does not match.",
                current_revision=existing.current_revision,
            )
        try:
            task = self._repository.get_task(existing.task_id)
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            return self._mutation_rejected(
                command_id=command_id,
                idempotency_key=idempotency_key,
                task_id=task_id,
                reason=DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE,
                message="Persisted Diagnostic Task command could not be read.",
                current_revision=existing.current_revision,
                retryable=True,
            )
        if task is None:
            return self._mutation_rejected(
                command_id=command_id,
                idempotency_key=idempotency_key,
                task_id=task_id,
                reason=DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE,
                message="Persisted Diagnostic Task command is incomplete.",
                current_revision=None,
                retryable=True,
            )
        handle = next(
            (
                item
                for item in task.task_handles
                if item.task_handle_id == existing.task_handle_id
            ),
            None,
        )
        return DiagnosticTaskCreationResult(
            disposition=DiagnosticTaskCreationDisposition.IDEMPOTENT_REPLAY,
            command_id=command_id,
            idempotency_key=idempotency_key,
            message=existing.message,
            rejection_reason=None,
            task_handle=handle,
            current_revision=task.revision,
            affected_task_id=task.task_id,
            retryable=False,
            affected_campaign_id=(
                None
                if task.campaign_handoff is None
                else task.campaign_handoff.campaign_id
            ),
        )

    def _read_task_for_command(
        self,
        command_id: str,
        idempotency_key: str,
        task_id: str,
    ) -> DiagnosticTaskSnapshot | DiagnosticTaskCommandResult:
        try:
            task = self._repository.get_task(task_id)
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            return self._mutation_rejected(
                command_id=command_id,
                idempotency_key=idempotency_key,
                task_id=task_id,
                reason=DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE,
                message="Diagnostic Task could not be read.",
                current_revision=None,
                retryable=True,
            )
        if task is None:
            return self._mutation_rejected(
                command_id=command_id,
                idempotency_key=idempotency_key,
                task_id=task_id,
                reason=DiagnosticTaskCreationRejectionReason.INVALID_COMMAND,
                message="Diagnostic Task identity is unavailable.",
                current_revision=None,
            )
        return task

    @staticmethod
    def _mutation_result(
        record: DiagnosticTaskMutationCommandRecord,
        *,
        task_handle: DiagnosticTaskHandleSnapshot | None = None,
    ) -> DiagnosticTaskCommandResult:
        return DiagnosticTaskCreationResult(
            disposition=record.disposition,
            command_id=record.command_id,
            idempotency_key=record.idempotency_key,
            message=record.message,
            rejection_reason=None,
            task_handle=task_handle,
            current_revision=record.current_revision,
            affected_task_id=record.task_id,
            retryable=False,
        )

    @staticmethod
    def _mutation_rejected(
        *,
        command_id: str,
        idempotency_key: str,
        task_id: str,
        reason: DiagnosticTaskCreationRejectionReason,
        message: str,
        current_revision: int | None,
        retryable: bool = False,
    ) -> DiagnosticTaskCommandResult:
        return DiagnosticTaskCreationResult(
            disposition=DiagnosticTaskCreationDisposition.REJECTED,
            command_id=command_id,
            idempotency_key=idempotency_key,
            message=message,
            rejection_reason=reason,
            task_handle=None,
            current_revision=current_revision,
            affected_task_id=task_id,
            retryable=retryable,
        )

    def _default_validation(
        self,
        configuration: DiagnosticTaskConfiguration,
    ) -> tuple[DiagnosticTaskValidationFinding, ...]:
        if self._configuration_validator(configuration):
            return ()
        return (
            DiagnosticTaskValidationFinding(
                reference_kind=(
                    DiagnosticTaskValidationReferenceKind.CONFIGURATION
                ),
                reference_identity=configuration.content_identity,
                severity=DiagnosticTaskValidationSeverity.ERROR,
                code="configuration.authoritative_integrity",
                safe_explanation=(
                    "The configuration no longer matches authoritative inputs."
                ),
                retryable=False,
                requires_different_input=True,
            ),
        )

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
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
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


def _validation_row(
    validation: DiagnosticTaskValidationSnapshot,
) -> dict[str, object]:
    return {
        "validation_id": validation.validation_id,
        "validation_revision": validation.validation_revision,
        "task_id": validation.task_id,
        "task_revision": validation.task_revision,
        "configuration_content_id": validation.configuration_content_id,
        "state": validation.state.value,
        "findings_json": _canonical_json(
            [
                {
                    "code": finding.code,
                    "reference_identity": finding.reference_identity,
                    "reference_kind": finding.reference_kind.value,
                    "requires_different_input": (
                        finding.requires_different_input
                    ),
                    "retryable": finding.retryable,
                    "safe_explanation": finding.safe_explanation,
                    "severity": finding.severity.value,
                }
                for finding in validation.findings
            ]
        ),
        "policy_identities_json": _canonical_json(
            list(validation.policy_identities)
        ),
        "task_handle_id": validation.task_handle_id,
        "validated_at_utc": validation.validated_at.isoformat(),
    }


def _approval_row(
    approval: DiagnosticTaskApprovalSnapshot,
) -> dict[str, object]:
    return {
        "approval_id": approval.approval_id,
        "task_id": approval.task_id,
        "task_revision": approval.task_revision,
        "configuration_content_id": approval.configuration_content_id,
        "validation_id": approval.validation_id,
        "validation_revision": approval.validation_revision,
        "actor_id": approval.actor_id,
        "policy_identities_json": _canonical_json(
            list(approval.policy_identities)
        ),
        "approved_at_utc": approval.approved_at.isoformat(),
    }


def _task_from_rows(
    task_row: RowMapping,
    handle_rows: Sequence[RowMapping],
    *,
    validation_row: RowMapping | None = None,
    approval_row: RowMapping | None = None,
    handoff_row: RowMapping | None = None,
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
    task_id = str(task_row["task_id"])
    revision = int(cast(str | int, task_row["revision"]))
    lifecycle = DiagnosticTaskLifecycle(str(task_row["lifecycle"]))
    handles = tuple(_handle_from_row(row) for row in handle_rows)
    validation = (
        None
        if validation_row is None
        else _validation_from_row(validation_row)
    )
    approval = (
        None if approval_row is None else _approval_from_row(approval_row)
    )
    campaign_handoff = (
        None
        if handoff_row is None
        else _campaign_handoff_from_row(handoff_row)
    )
    if revision < 1 or any(handle.task_id != task_id for handle in handles):
        raise ValueError("Persisted Diagnostic Task identity is inconsistent")
    if validation is not None and (
        validation.task_id != task_id
        or validation.task_revision != revision
        or validation.configuration_content_id
        != configuration.content_identity
        or validation.task_handle_id
        not in {handle.task_handle_id for handle in handles}
    ):
        raise ValueError(
            "Persisted Diagnostic Task validation is inconsistent"
        )
    if approval is not None and (
        validation is None
        or validation.state is not DiagnosticTaskValidationState.VALID
        or approval.task_id != task_id
        or approval.task_revision != revision
        or approval.configuration_content_id
        != configuration.content_identity
        or approval.validation_id != validation.validation_id
        or approval.validation_revision != validation.validation_revision
        or approval.policy_identities != validation.policy_identities
    ):
        raise ValueError(
            "Persisted Diagnostic Task approval is inconsistent"
        )
    lifecycle_consistent = (
        (
            lifecycle
            in {
                DiagnosticTaskLifecycle.CREATING,
                DiagnosticTaskLifecycle.DRAFT,
            }
            and approval is None
            and (
                validation is None
                or validation.state is DiagnosticTaskValidationState.INVALID
            )
        )
        or (
            lifecycle is DiagnosticTaskLifecycle.AWAITING_APPROVAL
            and validation is not None
            and validation.state is DiagnosticTaskValidationState.VALID
            and approval is None
        )
        or (
            lifecycle
            in {
                DiagnosticTaskLifecycle.APPROVED,
                DiagnosticTaskLifecycle.QUEUED,
            }
            and approval is not None
            and campaign_handoff is None
        )
        or (
            lifecycle is DiagnosticTaskLifecycle.RUNNING
            and approval is not None
            and campaign_handoff is not None
        )
    )
    if not lifecycle_consistent:
        raise ValueError(
            "Persisted Diagnostic Task lifecycle is inconsistent"
        )
    return DiagnosticTaskSnapshot(
        task_id=task_id,
        revision=revision,
        lifecycle=lifecycle,
        configuration=configuration,
        task_handles=handles,
        created_at=datetime.fromisoformat(str(task_row["created_at_utc"])),
        updated_at=datetime.fromisoformat(str(task_row["updated_at_utc"])),
        validation=validation,
        approval=approval,
        campaign_handoff=campaign_handoff,
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


def _campaign_handoff_from_row(
    row: RowMapping,
) -> DiagnosticTaskCampaignHandoffSnapshot:
    payload = json.loads(str(row["handoff_json"]))
    if not isinstance(payload, Mapping):
        raise ValueError("Diagnostic Task Campaign handoff must be an object")
    handoff = DiagnosticTaskCampaignHandoffSnapshot.from_storage_dict(
        cast(Mapping[str, object], payload)
    )
    if (
        handoff.campaign_id != str(row["campaign_id"])
        or not str(row["task_id"]).strip()
    ):
        raise ValueError(
            "Persisted Diagnostic Task Campaign handoff is inconsistent"
        )
    return handoff


def _command_record(row: RowMapping) -> DiagnosticTaskCommandRecord:
    return DiagnosticTaskCommandRecord(
        command_id=str(row["command_id"]),
        idempotency_key=str(row["idempotency_key"]),
        command_content_id=str(row["command_content_id"]),
        task_id=str(row["task_id"]),
        task_handle_id=(
            None
            if row["task_handle_id"] is None
            else str(row["task_handle_id"])
        ),
    )


def _mutation_command_record(
    row: RowMapping,
) -> DiagnosticTaskMutationCommandRecord:
    return DiagnosticTaskMutationCommandRecord(
        command_id=str(row["command_id"]),
        idempotency_key=str(row["idempotency_key"]),
        command_type=str(row["command_type"]),
        command_content_id=str(row["command_content_id"]),
        task_id=str(row["task_id"]),
        task_handle_id=(
            None
            if row["task_handle_id"] is None
            else str(row["task_handle_id"])
        ),
        disposition=DiagnosticTaskCreationDisposition(
            str(row["disposition"])
        ),
        message=str(row["message"]),
        current_revision=int(cast(str | int, row["current_revision"])),
    )


def _validation_from_row(
    row: RowMapping,
) -> DiagnosticTaskValidationSnapshot:
    findings_payload = json.loads(str(row["findings_json"]))
    policies_payload = json.loads(str(row["policy_identities_json"]))
    if not isinstance(findings_payload, list) or not isinstance(
        policies_payload,
        list,
    ):
        raise TypeError("Diagnostic Task validation schema mismatch")
    if any(
        not isinstance(item, Mapping)
        or set(item) != {
            "code",
            "reference_identity",
            "reference_kind",
            "requires_different_input",
            "retryable",
            "safe_explanation",
            "severity",
        }
        or not isinstance(item["requires_different_input"], bool)
        or not isinstance(item["retryable"], bool)
        or any(
            not isinstance(item[key], str) or not item[key].strip()
            for key in (
                "code",
                "reference_identity",
                "reference_kind",
                "safe_explanation",
                "severity",
            )
        )
        for item in findings_payload
    ) or any(
        not isinstance(item, str) or not item.strip()
        for item in policies_payload
    ):
        raise ValueError("Diagnostic Task validation schema mismatch")
    findings = tuple(
        DiagnosticTaskValidationFinding(
            reference_kind=DiagnosticTaskValidationReferenceKind(
                str(item["reference_kind"])
            ),
            reference_identity=str(item["reference_identity"]),
            severity=DiagnosticTaskValidationSeverity(
                str(item["severity"])
            ),
            code=str(item["code"]),
            safe_explanation=str(item["safe_explanation"]),
            retryable=bool(item["retryable"]),
            requires_different_input=bool(
                item["requires_different_input"]
            ),
        )
        for item in cast(list[Mapping[str, object]], findings_payload)
    )
    return DiagnosticTaskValidationSnapshot(
        validation_id=str(row["validation_id"]),
        validation_revision=int(
            cast(str | int, row["validation_revision"])
        ),
        task_id=str(row["task_id"]),
        task_revision=int(cast(str | int, row["task_revision"])),
        configuration_content_id=str(row["configuration_content_id"]),
        state=DiagnosticTaskValidationState(str(row["state"])),
        findings=findings,
        policy_identities=tuple(str(item) for item in policies_payload),
        task_handle_id=str(row["task_handle_id"]),
        validated_at=datetime.fromisoformat(str(row["validated_at_utc"])),
    )


def _approval_from_row(
    row: RowMapping,
) -> DiagnosticTaskApprovalSnapshot:
    policies_payload = json.loads(str(row["policy_identities_json"]))
    if not isinstance(policies_payload, list) or any(
        not isinstance(item, str) or not item.strip()
        for item in policies_payload
    ):
        raise ValueError("Diagnostic Task approval schema mismatch")
    return DiagnosticTaskApprovalSnapshot(
        approval_id=str(row["approval_id"]),
        task_id=str(row["task_id"]),
        task_revision=int(cast(str | int, row["task_revision"])),
        configuration_content_id=str(row["configuration_content_id"]),
        validation_id=str(row["validation_id"]),
        validation_revision=int(
            cast(str | int, row["validation_revision"])
        ),
        actor_id=str(row["actor_id"]),
        policy_identities=tuple(str(item) for item in policies_payload),
        approved_at=datetime.fromisoformat(str(row["approved_at_utc"])),
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
    "ApproveDiagnosticTaskConfigurationRequest",
    "CreateDiagnosticTaskRequest",
    "DiagnosticCampaignAttemptHandoffSnapshot",
    "DiagnosticCampaignCaseSelection",
    "DiagnosticCampaignNodeHandoffSnapshot",
    "DiagnosticCampaignRunHandoffSnapshot",
    "DiagnosticStrategySelection",
    "DiagnosticTaskApprovalSnapshot",
    "DiagnosticTaskCampaignHandoffSnapshot",
    "DiagnosticTaskCommandResult",
    "DiagnosticTaskConfiguration",
    "DiagnosticTaskCreationDisposition",
    "DiagnosticTaskCreationRejectionReason",
    "DiagnosticTaskCreationResult",
    "DiagnosticTaskHandlePhase",
    "DiagnosticTaskHandleSnapshot",
    "DiagnosticTaskLifecycle",
    "DiagnosticTaskService",
    "DiagnosticTaskSnapshot",
    "DiagnosticTaskValidationFinding",
    "DiagnosticTaskValidationReferenceKind",
    "DiagnosticTaskValidationSeverity",
    "DiagnosticTaskValidationSnapshot",
    "DiagnosticTaskValidationState",
    "InMemoryDiagnosticTaskRepository",
    "ReviseDiagnosticTaskConfigurationRequest",
    "SqlDiagnosticTaskRepository",
    "StartFormalDiagnosticCampaignRequest",
    "ValidateDiagnosticTaskConfigurationRequest",
]
