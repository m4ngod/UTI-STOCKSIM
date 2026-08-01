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
    PAUSED = "paused"
    RESUMING = "resuming"
    CANCELING = "canceling"
    CANCELED = "canceled"
    FAILED = "failed"
    COMPLETED = "completed"


class DiagnosticEvidenceHandoffState(str, Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    FAILED = "failed"
    AVAILABLE = "available"


class DiagnosticLifecycleTargetKind(str, Enum):
    DIAGNOSTIC_TASK = "diagnostic_task"
    FORMAL_DIAGNOSTIC_CAMPAIGN = "formal_diagnostic_campaign"
    CAMPAIGN_NODE = "campaign_node"


class DiagnosticLifecycleOperation(str, Enum):
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"


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
class ChangeDiagnosticLifecycleRequest:
    command_id: str
    idempotency_key: str
    operation: DiagnosticLifecycleOperation
    target_kind: DiagnosticLifecycleTargetKind
    target_id: str
    expected_revision: int

    def command_content_identity(self) -> str:
        return _content_identity(
            {
                "command_type": f"{self.operation.value}_diagnostic_target",
                "expected_revision": self.expected_revision,
                "target_id": self.target_id,
                "target_kind": self.target_kind.value,
            }
        )


@dataclass(frozen=True, slots=True)
class RetryFailedCampaignNodeRequest:
    command_id: str
    idempotency_key: str
    task_id: str
    campaign_node_id: str
    failed_attempt_id: str
    expected_revision: int

    def command_content_identity(self) -> str:
        return _content_identity(
            {
                "campaign_node_id": self.campaign_node_id,
                "command_type": "retry_failed_campaign_node",
                "expected_revision": self.expected_revision,
                "failed_attempt_id": self.failed_attempt_id,
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
    reproduction_manifest_id: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id.strip() or not self.strategy_id.strip():
            raise ValueError("Campaign Run and Strategy identities are required")
        if (
            self.reproduction_manifest_id is not None
            and not self.reproduction_manifest_id.strip()
        ):
            raise ValueError("Reproduction Manifest identity cannot be blank")

    def to_storage_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "strategy_id": self.strategy_id,
            "reproduction_manifest_id": self.reproduction_manifest_id,
        }


@dataclass(frozen=True, slots=True)
class DiagnosticCampaignAttemptHandoffSnapshot:
    attempt_id: str
    runs: tuple[DiagnosticCampaignRunHandoffSnapshot, ...]
    attempt_number: int = 1
    lifecycle: DiagnosticTaskLifecycle = DiagnosticTaskLifecycle.COMPLETED
    predecessor_attempt_id: str | None = None
    task_handle_id: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None

    def __post_init__(self) -> None:
        if not self.attempt_id.strip():
            raise ValueError("Campaign attempt identity is required")
        if self.attempt_number < 1:
            raise ValueError("Campaign attempt number must be positive")
        if self.predecessor_attempt_id == self.attempt_id:
            raise ValueError("Campaign attempt cannot be its own predecessor")
        if self.task_handle_id is not None and not self.task_handle_id.strip():
            raise ValueError("Campaign attempt TaskHandle identity is required")
        if self.lifecycle is DiagnosticTaskLifecycle.FAILED:
            if not (self.failure_code or "").strip():
                raise ValueError("Failed Campaign attempt requires a failure code")
        elif self.failure_code is not None or self.failure_message is not None:
            raise ValueError("Only a failed Campaign attempt can expose failure")
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
            "attempt_number": self.attempt_number,
            "failure_code": self.failure_code,
            "failure_message": self.failure_message,
            "lifecycle": self.lifecycle.value,
            "predecessor_attempt_id": self.predecessor_attempt_id,
            "runs": [item.to_storage_dict() for item in self.runs],
            "task_handle_id": self.task_handle_id,
        }


@dataclass(frozen=True, slots=True)
class DiagnosticCampaignNodeHandoffSnapshot:
    campaign_node_id: str
    campaign_case_id: str
    selected_campaign_case_id: str
    market_scenario_id: str
    attempts: tuple[DiagnosticCampaignAttemptHandoffSnapshot, ...]
    active_attempt_id: str | None
    revision: int = 1
    lifecycle: DiagnosticTaskLifecycle = DiagnosticTaskLifecycle.QUEUED

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
        for index, attempt in enumerate(self.attempts, start=1):
            if attempt.attempt_number != index:
                raise ValueError("Campaign node attempt numbers must be contiguous")
            expected_predecessor = (
                None if index == 1 else self.attempts[index - 2].attempt_id
            )
            if attempt.predecessor_attempt_id != expected_predecessor:
                raise ValueError(
                    "Campaign node attempt predecessor history must be contiguous"
                )
        if (
            self.active_attempt_id is not None
            and self.active_attempt_id not in attempt_ids
        ):
            raise ValueError("Active Campaign attempt must be present in history")
        if self.revision < 1:
            raise ValueError("Campaign node revision must be positive")

    def to_storage_dict(self) -> dict[str, object]:
        return {
            "active_attempt_id": self.active_attempt_id,
            "attempts": [
                attempt.to_storage_dict() for attempt in self.attempts
            ],
            "campaign_case_id": self.campaign_case_id,
            "campaign_node_id": self.campaign_node_id,
            "market_scenario_id": self.market_scenario_id,
            "revision": self.revision,
            "selected_campaign_case_id": self.selected_campaign_case_id,
            "lifecycle": self.lifecycle.value,
        }


@dataclass(frozen=True, slots=True)
class DiagnosticTaskCampaignHandoffSnapshot:
    campaign_id: str
    campaign_nodes: tuple[DiagnosticCampaignNodeHandoffSnapshot, ...]
    campaign_revision: int = 1
    campaign_lifecycle: DiagnosticTaskLifecycle = (
        DiagnosticTaskLifecycle.RUNNING
    )
    evidence_package_id: str | None = None
    reproduction_manifest_id: str | None = None
    evidence_state: DiagnosticEvidenceHandoffState = (
        DiagnosticEvidenceHandoffState.PENDING
    )
    evidence_error_code: str | None = None
    evidence_error_message: str | None = None

    def __post_init__(self) -> None:
        if not self.campaign_id.strip():
            raise ValueError("Formal Diagnostic Campaign identity is required")
        if self.campaign_revision < 1:
            raise ValueError("Formal Diagnostic Campaign revision must be positive")
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
        accepted_manifest_ids = tuple(
            run.reproduction_manifest_id
            for node in self.campaign_nodes
            for attempt in node.attempts
            if attempt.attempt_id == node.active_attempt_id
            for run in attempt.runs
        )
        historical_manifest_ids = tuple(
            run.reproduction_manifest_id
            for node in self.campaign_nodes
            for attempt in node.attempts
            if attempt.attempt_id != node.active_attempt_id
            for run in attempt.runs
        )
        if len(set(attempt_ids)) != len(attempt_ids):
            raise ValueError("Campaign attempt identities must be globally unique")
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("Strategy Run identities must be globally unique")
        evidence_present = self.evidence_package_id is not None
        manifest_present = self.reproduction_manifest_id is not None
        error_present = self.evidence_error_code is not None
        if (
            not error_present
            and evidence_present != manifest_present
        ):
            raise ValueError(
                "Evidence Package and Reproduction Manifest identities "
                "must become available together"
            )
        if self.evidence_state is DiagnosticEvidenceHandoffState.PENDING:
            inferred_state = (
                DiagnosticEvidenceHandoffState.AVAILABLE
                if evidence_present and manifest_present and not error_present
                else (
                    DiagnosticEvidenceHandoffState.PARTIAL
                    if evidence_present and not manifest_present and error_present
                    else (
                        DiagnosticEvidenceHandoffState.FAILED
                        if not evidence_present
                        and not manifest_present
                        and error_present
                        else self.evidence_state
                    )
                )
            )
            object.__setattr__(self, "evidence_state", inferred_state)
        if (
            self.evidence_package_id is not None
            and not self.evidence_package_id.strip()
        ):
            raise ValueError("Evidence Package identity cannot be blank")
        if (
            self.reproduction_manifest_id is not None
            and not self.reproduction_manifest_id.strip()
        ):
            raise ValueError("Reproduction Manifest identity cannot be blank")
        if (
            self.evidence_error_code is not None
            and not self.evidence_error_code.strip()
        ):
            raise ValueError("Evidence handoff error code cannot be blank")
        if (
            self.evidence_error_message is not None
            and not self.evidence_error_message.strip()
        ):
            raise ValueError("Evidence handoff error message cannot be blank")
        if error_present != (self.evidence_error_message is not None):
            raise ValueError(
                "Evidence handoff error code and message must be present together"
            )
        if (
            self.evidence_state is not DiagnosticEvidenceHandoffState.PENDING
            and self.campaign_lifecycle is not DiagnosticTaskLifecycle.COMPLETED
        ):
            raise ValueError(
                "Terminal evidence handoff requires a completed Formal Campaign"
            )
        if self.evidence_state is DiagnosticEvidenceHandoffState.PENDING:
            if evidence_present or manifest_present or error_present:
                raise ValueError(
                    "Pending evidence handoff cannot expose identities or errors"
                )
        elif self.evidence_state is DiagnosticEvidenceHandoffState.FAILED:
            if evidence_present or manifest_present or not error_present:
                raise ValueError(
                    "Failed evidence handoff requires only a structured error"
                )
        elif self.evidence_state is DiagnosticEvidenceHandoffState.PARTIAL:
            if not evidence_present or manifest_present or not error_present:
                raise ValueError(
                    "Partial evidence handoff requires a sealed Evidence "
                    "Package and structured error without a Manifest"
                )
        elif self.evidence_state is DiagnosticEvidenceHandoffState.AVAILABLE:
            if not evidence_present or not manifest_present or error_present:
                raise ValueError(
                    "Available evidence handoff requires Package and Manifest "
                    "identities without an error"
                )
            if (
                not accepted_manifest_ids
                or any(
                    manifest_id is None
                    for manifest_id in accepted_manifest_ids
                )
                or len(set(accepted_manifest_ids))
                != len(accepted_manifest_ids)
                or self.reproduction_manifest_id
                not in accepted_manifest_ids
                or any(
                    manifest_id is not None
                    for manifest_id in historical_manifest_ids
                )
            ):
                raise ValueError(
                    "Evidence handoff requires one unique Reproduction "
                    "Manifest identity for every accepted Strategy Run "
                    "without rewriting historical attempts"
                )
        if (
            self.evidence_state
            is not DiagnosticEvidenceHandoffState.AVAILABLE
            and any(
                manifest_id is not None
                for manifest_id in (
                    *accepted_manifest_ids,
                    *historical_manifest_ids,
                )
            )
        ):
            raise ValueError(
                "Run Manifest identities require available evidence"
            )

    def to_storage_dict(self) -> dict[str, object]:
        return {
            "campaign_id": self.campaign_id,
            "campaign_lifecycle": self.campaign_lifecycle.value,
            "campaign_revision": self.campaign_revision,
            "campaign_nodes": [
                node.to_storage_dict() for node in self.campaign_nodes
            ],
            "evidence_package_id": self.evidence_package_id,
            "evidence_error_code": self.evidence_error_code,
            "evidence_error_message": self.evidence_error_message,
            "evidence_state": self.evidence_state.value,
            "reproduction_manifest_id": self.reproduction_manifest_id,
        }

    @classmethod
    def from_storage_dict(
        cls,
        payload: Mapping[str, object],
    ) -> DiagnosticTaskCampaignHandoffSnapshot:
        node_payloads = cast(
            list[Mapping[str, object]],
            payload["campaign_nodes"],
        )
        return cls(
            campaign_id=str(payload["campaign_id"]),
            campaign_revision=int(
                cast(str | int, payload.get("campaign_revision", 1))
            ),
            campaign_lifecycle=DiagnosticTaskLifecycle(
                str(payload.get("campaign_lifecycle", "running"))
            ),
            evidence_package_id=(
                None
                if payload.get("evidence_package_id") is None
                else str(payload["evidence_package_id"])
            ),
            evidence_state=DiagnosticEvidenceHandoffState(
                str(
                    payload.get(
                        "evidence_state",
                        (
                            "available"
                            if payload.get("evidence_package_id") is not None
                            and payload.get("reproduction_manifest_id")
                            is not None
                            else "pending"
                        ),
                    )
                )
            ),
            evidence_error_code=(
                None
                if payload.get("evidence_error_code") is None
                else str(payload["evidence_error_code"])
            ),
            evidence_error_message=(
                None
                if payload.get("evidence_error_message") is None
                else str(payload["evidence_error_message"])
            ),
            reproduction_manifest_id=(
                None
                if payload.get("reproduction_manifest_id") is None
                else str(payload["reproduction_manifest_id"])
            ),
            campaign_nodes=tuple(
                DiagnosticCampaignNodeHandoffSnapshot(
                    campaign_node_id=str(node["campaign_node_id"]),
                    campaign_case_id=str(node["campaign_case_id"]),
                    selected_campaign_case_id=str(
                        node["selected_campaign_case_id"]
                    ),
                    market_scenario_id=str(node["market_scenario_id"]),
                    attempts=_attempts_from_storage(
                        cast(
                            list[Mapping[str, object]],
                            node["attempts"],
                        ),
                        final_lifecycle=DiagnosticTaskLifecycle(
                            str(
                                node.get(
                                    "lifecycle",
                                    (
                                        "completed"
                                        if cast(
                                            list[Mapping[str, object]],
                                            node["attempts"],
                                        )
                                        else "queued"
                                    ),
                                )
                            )
                        ),
                    ),
                    active_attempt_id=(
                        None
                        if node.get("active_attempt_id") is None
                        else str(node["active_attempt_id"])
                    ),
                    revision=int(
                        cast(str | int, node.get("revision", 1))
                    ),
                    lifecycle=DiagnosticTaskLifecycle(
                        str(
                            node.get(
                                "lifecycle",
                                (
                                    "completed"
                                    if cast(
                                        list[Mapping[str, object]],
                                        node["attempts"],
                                    )
                                    else "queued"
                                ),
                            )
                        )
                    ),
                )
                for node in node_payloads
            ),
        )


@dataclass(frozen=True, slots=True)
class DiagnosticLifecycleTargetSnapshot:
    target_kind: DiagnosticLifecycleTargetKind
    target_id: str
    task_id: str
    revision: int
    lifecycle: DiagnosticTaskLifecycle

    def __post_init__(self) -> None:
        if not self.target_id.strip() or not self.task_id.strip():
            raise ValueError("Diagnostic lifecycle target identities are required")
        if self.revision < 1:
            raise ValueError("Diagnostic lifecycle target revision must be positive")


@dataclass(frozen=True, slots=True)
class _DiagnosticCampaignProgressMerge:
    handoff: DiagnosticTaskCampaignHandoffSnapshot
    target_updates: tuple[
        tuple[
            DiagnosticLifecycleTargetSnapshot,
            DiagnosticLifecycleTargetSnapshot,
        ],
        ...,
    ]
    task_lifecycle: DiagnosticTaskLifecycle
    changed: bool


@dataclass(frozen=True, slots=True)
class _DiagnosticRetryCompletionMerge:
    handoff: DiagnosticTaskCampaignHandoffSnapshot
    attempt: DiagnosticCampaignAttemptHandoffSnapshot
    task_revision: int
    task_lifecycle: DiagnosticTaskLifecycle
    target_updates: tuple[
        tuple[
            DiagnosticLifecycleTargetSnapshot,
            DiagnosticLifecycleTargetSnapshot,
        ],
        ...,
    ]


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
    affected_campaign_node_id: str | None = None
    affected_campaign_attempt_id: str | None = None


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

    def pending_retry_requests(
        self,
    ) -> tuple[RetryFailedCampaignNodeRequest, ...]: ...

    def get_lifecycle_target(
        self,
        target_kind: DiagnosticLifecycleTargetKind,
        target_id: str,
    ) -> DiagnosticLifecycleTargetSnapshot | None: ...

    def pending_lifecycle_requests(
        self,
    ) -> tuple[ChangeDiagnosticLifecycleRequest, ...]: ...

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

    def accept_failed_node_retry(
        self,
        *,
        record: DiagnosticTaskMutationCommandRecord,
        command_json: str,
        task: DiagnosticTaskSnapshot,
        queued_handle: DiagnosticTaskHandleSnapshot,
        expected_node: DiagnosticLifecycleTargetSnapshot,
        queued_handoff: DiagnosticTaskCampaignHandoffSnapshot,
    ) -> bool: ...

    def complete_failed_node_retry(
        self,
        task_handle_id: str,
        continuation_claim_id: str,
        handoff: DiagnosticTaskCampaignHandoffSnapshot,
        updated_at: datetime,
    ) -> None: ...

    def accept_lifecycle(
        self,
        *,
        record: DiagnosticTaskMutationCommandRecord,
        command_json: str,
        task_handle: DiagnosticTaskHandleSnapshot,
        target: DiagnosticLifecycleTargetSnapshot,
        task_revision: int,
        accepted_lifecycle: DiagnosticTaskLifecycle,
    ) -> bool: ...

    def complete_lifecycle(
        self,
        task_handle_id: str,
        operation: DiagnosticLifecycleOperation,
        target: DiagnosticLifecycleTargetSnapshot,
        final_lifecycle: DiagnosticTaskLifecycle,
        updated_at: datetime,
    ) -> None: ...

    def sync_campaign_progress(
        self,
        handoff: DiagnosticTaskCampaignHandoffSnapshot,
        updated_at: datetime,
    ) -> None: ...

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
        self._pending_retry_requests: dict[
            str,
            RetryFailedCampaignNodeRequest,
        ] = {}
        self._start_continuation_claims: dict[str, str] = {}
        self._lifecycle_targets: dict[
            tuple[DiagnosticLifecycleTargetKind, str],
            DiagnosticLifecycleTargetSnapshot,
        ] = {}
        self._pending_lifecycle_requests: dict[
            str,
            ChangeDiagnosticLifecycleRequest,
        ] = {}

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
        task = self._tasks.get(task_id)
        return None if task is None else self._with_lifecycle_targets(task)

    def latest_task(self) -> DiagnosticTaskSnapshot | None:
        if not self._tasks:
            return None
        return self._with_lifecycle_targets(tuple(self._tasks.values())[-1])

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

    def pending_retry_requests(
        self,
    ) -> tuple[RetryFailedCampaignNodeRequest, ...]:
        return tuple(
            request
            for handle_id, request in self._pending_retry_requests.items()
            if any(
                handle.task_handle_id == handle_id
                and handle.phase is DiagnosticTaskHandlePhase.QUEUED
                for task in self._tasks.values()
                for handle in task.task_handles
            )
        )

    def get_lifecycle_target(
        self,
        target_kind: DiagnosticLifecycleTargetKind,
        target_id: str,
    ) -> DiagnosticLifecycleTargetSnapshot | None:
        return self._lifecycle_targets.get((target_kind, target_id))

    def pending_lifecycle_requests(
        self,
    ) -> tuple[ChangeDiagnosticLifecycleRequest, ...]:
        return tuple(
            request
            for handle_id, request in self._pending_lifecycle_requests.items()
            if any(
                handle.task_handle_id == handle_id
                and handle.phase is DiagnosticTaskHandlePhase.QUEUED
                for task in self._tasks.values()
                for handle in task.task_handles
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

    def accept_failed_node_retry(
        self,
        *,
        record: DiagnosticTaskMutationCommandRecord,
        command_json: str,
        task: DiagnosticTaskSnapshot,
        queued_handle: DiagnosticTaskHandleSnapshot,
        expected_node: DiagnosticLifecycleTargetSnapshot,
        queued_handoff: DiagnosticTaskCampaignHandoffSnapshot,
    ) -> bool:
        if (
            self.find_mutation_command(
                record.command_id,
                record.idempotency_key,
            )
            is not None
        ):
            return False
        payload = json.loads(command_json)
        if not isinstance(payload, dict):
            raise TypeError("Persisted failed-node retry command must be an object")
        pending_request = RetryFailedCampaignNodeRequest(
            command_id=str(payload["command_id"]),
            idempotency_key=str(payload["idempotency_key"]),
            task_id=str(payload["task_id"]),
            campaign_node_id=str(payload["campaign_node_id"]),
            failed_attempt_id=str(payload["failed_attempt_id"]),
            expected_revision=int(cast(str | int, payload["expected_revision"])),
        )
        current = self._tasks.get(record.task_id)
        current_node = self.get_lifecycle_target(
            DiagnosticLifecycleTargetKind.CAMPAIGN_NODE,
            expected_node.target_id,
        )
        if (
            current is None
            or current.campaign_handoff is None
            or current_node != expected_node
            or expected_node.lifecycle is not DiagnosticTaskLifecycle.FAILED
            or task.revision != current.revision + 1
            or task.campaign_handoff != queued_handoff
        ):
            return False
        queued_node = next(
            (
                node
                for node in queued_handoff.campaign_nodes
                if node.campaign_node_id == expected_node.target_id
            ),
            None,
        )
        if (
            queued_node is None
            or queued_node.revision != expected_node.revision + 1
            or queued_node.lifecycle is not DiagnosticTaskLifecycle.QUEUED
            or not queued_node.attempts
            or queued_node.attempts[-1].task_handle_id
            != queued_handle.task_handle_id
        ):
            return False
        task_parent = self.get_lifecycle_target(
            DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK,
            task.task_id,
        )
        campaign_parent = self.get_lifecycle_target(
            DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN,
            queued_handoff.campaign_id,
        )
        if (
            task_parent is None
            or campaign_parent is None
            or task_parent.revision != current.revision
            or campaign_parent.revision
            != current.campaign_handoff.campaign_revision
            or current.lifecycle
            is not current.campaign_handoff.campaign_lifecycle
            or current.lifecycle
            not in {
                DiagnosticTaskLifecycle.RUNNING,
                DiagnosticTaskLifecycle.FAILED,
            }
            or task_parent.lifecycle is not current.lifecycle
            or campaign_parent.lifecycle is not current.lifecycle
            or queued_handoff.campaign_revision
            != current.campaign_handoff.campaign_revision + 1
        ):
            return False
        self._tasks[task.task_id] = replace(
            task,
            task_handles=(*current.task_handles, queued_handle),
        )
        self._lifecycle_targets[
            (
                DiagnosticLifecycleTargetKind.CAMPAIGN_NODE,
                expected_node.target_id,
            )
        ] = replace(
            expected_node,
            revision=queued_node.revision,
            lifecycle=DiagnosticTaskLifecycle.QUEUED,
        )
        self._lifecycle_targets[
            (
                DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK,
                task.task_id,
            )
        ] = replace(
            task_parent,
            revision=task.revision,
            lifecycle=DiagnosticTaskLifecycle.RUNNING,
        )
        self._lifecycle_targets[
            (
                DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN,
                queued_handoff.campaign_id,
            )
        ] = replace(
            campaign_parent,
            revision=queued_handoff.campaign_revision,
            lifecycle=DiagnosticTaskLifecycle.RUNNING,
        )
        self._store_mutation(record)
        self._pending_retry_requests[queued_handle.task_handle_id] = pending_request
        return True

    def complete_failed_node_retry(
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
            if handle.phase in {
                DiagnosticTaskHandlePhase.COMPLETED,
                DiagnosticTaskHandlePhase.FAILED,
            }:
                return
            if (
                self._start_continuation_claims.get(task_handle_id)
                != continuation_claim_id
            ):
                raise ValueError(
                    "Failed-node retry continuation is not owned by this claim"
            )
            if task.campaign_handoff is None:
                raise ValueError("Diagnostic Task Campaign handoff is unavailable")
            targets = tuple(
                target
                for target in self._lifecycle_targets.values()
                if target.task_id == task_id
            )
            reconciliation = _reconcile_retry_completion(
                task.campaign_handoff,
                handoff,
                task_handle_id,
                task_revision=task.revision,
                task_lifecycle=task.lifecycle,
                targets=targets,
            )
            terminal_handle = _retry_terminal_handle(
                handle,
                reconciliation.attempt,
                updated_at,
            )
            if any(
                self._lifecycle_targets.get(
                    (before.target_kind, before.target_id)
                )
                != before
                for before, _after in reconciliation.target_updates
            ):
                raise ValueError(
                    "Failed-node retry lifecycle changed concurrently"
                )
            self._tasks[task_id] = replace(
                task,
                revision=reconciliation.task_revision,
                lifecycle=reconciliation.task_lifecycle,
                task_handles=tuple(
                    terminal_handle
                    if candidate.task_handle_id == task_handle_id
                    else candidate
                    for candidate in task.task_handles
                ),
                campaign_handoff=reconciliation.handoff,
                updated_at=updated_at,
            )
            for _before, after in reconciliation.target_updates:
                self._lifecycle_targets[
                    (after.target_kind, after.target_id)
                ] = after
            self._pending_retry_requests.pop(task_handle_id, None)
            self._start_continuation_claims.pop(task_handle_id, None)
            return
        raise KeyError(
            f"Unknown failed-node retry Diagnostic TaskHandle {task_handle_id!r}"
        )

    def accept_lifecycle(
        self,
        *,
        record: DiagnosticTaskMutationCommandRecord,
        command_json: str,
        task_handle: DiagnosticTaskHandleSnapshot,
        target: DiagnosticLifecycleTargetSnapshot,
        task_revision: int,
        accepted_lifecycle: DiagnosticTaskLifecycle,
    ) -> bool:
        if (
            self.find_mutation_command(
                record.command_id,
                record.idempotency_key,
            )
            is not None
        ):
            return False
        current_target = self.get_lifecycle_target(
            target.target_kind,
            target.target_id,
        )
        task = self._tasks.get(target.task_id)
        if (
            current_target != target
            or task is None
            or task.revision != task_revision
        ):
            return False
        accepted_target = replace(
            target,
            revision=target.revision + 1,
            lifecycle=accepted_lifecycle,
        )
        self._lifecycle_targets[
            (target.target_kind, target.target_id)
        ] = accepted_target
        self._mirror_parent_lifecycle(
            accepted_target,
            lifecycle=accepted_lifecycle,
            increment_revision=True,
        )
        task_lifecycle = (
            accepted_lifecycle
            if target.target_kind
            in {
                DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK,
                DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN,
            }
            else task.lifecycle
        )
        task = self._with_superseded_lifecycle_handles(
            task,
            target,
            task_handle.updated_at,
        )
        self._tasks[target.task_id] = replace(
            task,
            revision=task.revision + 1,
            lifecycle=task_lifecycle,
            task_handles=(*task.task_handles, task_handle),
            updated_at=task_handle.updated_at,
        )
        self._store_mutation(record)
        payload = json.loads(command_json)
        if not isinstance(payload, dict):
            raise TypeError("Lifecycle command payload must be an object")
        self._pending_lifecycle_requests[task_handle.task_handle_id] = (
            ChangeDiagnosticLifecycleRequest(
                command_id=str(payload["command_id"]),
                idempotency_key=str(payload["idempotency_key"]),
                operation=DiagnosticLifecycleOperation(
                    str(payload["operation"])
                ),
                target_kind=DiagnosticLifecycleTargetKind(
                    str(payload["target_kind"])
                ),
                target_id=str(payload["target_id"]),
                expected_revision=int(
                    cast(str | int, payload["expected_revision"])
                ),
            )
        )
        return True

    def complete_lifecycle(
        self,
        task_handle_id: str,
        operation: DiagnosticLifecycleOperation,
        target: DiagnosticLifecycleTargetSnapshot,
        final_lifecycle: DiagnosticTaskLifecycle,
        updated_at: datetime,
    ) -> None:
        task = self._tasks.get(target.task_id)
        if task is None:
            raise KeyError(f"Unknown Diagnostic Task {target.task_id!r}")
        handle = next(
            (
                candidate
                for candidate in task.task_handles
                if candidate.task_handle_id == task_handle_id
            ),
            None,
        )
        if handle is None:
            raise KeyError(
                f"Unknown lifecycle Diagnostic TaskHandle {task_handle_id!r}"
            )
        if handle.phase is DiagnosticTaskHandlePhase.COMPLETED:
            return
        current_target = self.get_lifecycle_target(
            target.target_kind,
            target.target_id,
        )
        if (
            handle.phase is not DiagnosticTaskHandlePhase.QUEUED
            or current_target is None
            or current_target.revision != target.revision + 1
        ):
            raise ValueError("Diagnostic lifecycle completion changed concurrently")
        completed_target = replace(
            current_target,
            lifecycle=final_lifecycle,
        )
        self._lifecycle_targets[
            (target.target_kind, target.target_id)
        ] = completed_target
        self._mirror_parent_lifecycle(
            completed_target,
            lifecycle=final_lifecycle,
            increment_revision=False,
        )
        if (
            operation is DiagnosticLifecycleOperation.CANCEL
            and target.target_kind
            in {
                DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK,
                DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN,
            }
        ):
            self._cancel_child_nodes(target.task_id)
        completed_handle = replace(
            handle,
            phase=DiagnosticTaskHandlePhase.COMPLETED,
            progress=1.0,
            result_code=_lifecycle_result_code(
                operation,
                target.target_kind,
            ),
            cancelable=False,
            updated_at=updated_at,
        )
        task_lifecycle = (
            final_lifecycle
            if target.target_kind
            in {
                DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK,
                DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN,
            }
            else task.lifecycle
        )
        self._tasks[target.task_id] = replace(
            task,
            lifecycle=task_lifecycle,
            task_handles=tuple(
                completed_handle
                if candidate.task_handle_id == task_handle_id
                else candidate
                for candidate in task.task_handles
            ),
            updated_at=updated_at,
        )
        self._pending_lifecycle_requests.pop(task_handle_id, None)

    def sync_campaign_progress(
        self,
        handoff: DiagnosticTaskCampaignHandoffSnapshot,
        updated_at: datetime,
    ) -> None:
        campaign_target = self.get_lifecycle_target(
            DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN,
            handoff.campaign_id,
        )
        if campaign_target is None:
            return
        task = self._tasks.get(campaign_target.task_id)
        if task is None or task.campaign_handoff is None:
            raise ValueError("Linked Diagnostic Task Campaign is unavailable")
        targets = tuple(
            target
            for target in self._lifecycle_targets.values()
            if target.task_id == task.task_id
        )
        merged = _merge_diagnostic_campaign_progress(
            task.campaign_handoff,
            handoff,
            targets,
        )
        if not merged.changed:
            return
        for before, after in merged.target_updates:
            key = (before.target_kind, before.target_id)
            if self._lifecycle_targets.get(key) != before:
                raise ValueError(
                    "Diagnostic lifecycle target changed concurrently"
                )
            self._lifecycle_targets[key] = after
        self._tasks[task.task_id] = replace(
            task,
            revision=task.revision + 1,
            lifecycle=merged.task_lifecycle,
            campaign_handoff=merged.handoff,
            updated_at=updated_at,
        )

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
            task_target = DiagnosticLifecycleTargetSnapshot(
                target_kind=DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK,
                target_id=task_id,
                task_id=task_id,
                revision=task.revision,
                lifecycle=DiagnosticTaskLifecycle.RUNNING,
            )
            campaign_target = DiagnosticLifecycleTargetSnapshot(
                target_kind=(
                    DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN
                ),
                target_id=handoff.campaign_id,
                task_id=task_id,
                revision=handoff.campaign_revision,
                lifecycle=handoff.campaign_lifecycle,
            )
            self._lifecycle_targets[
                (task_target.target_kind, task_target.target_id)
            ] = task_target
            self._lifecycle_targets[
                (campaign_target.target_kind, campaign_target.target_id)
            ] = campaign_target
            for node in handoff.campaign_nodes:
                node_target = DiagnosticLifecycleTargetSnapshot(
                    target_kind=DiagnosticLifecycleTargetKind.CAMPAIGN_NODE,
                    target_id=node.campaign_node_id,
                    task_id=task_id,
                    revision=node.revision,
                    lifecycle=node.lifecycle,
                )
                self._lifecycle_targets[
                    (node_target.target_kind, node_target.target_id)
                ] = node_target
            self._pending_start_requests.pop(task_handle_id, None)
            self._start_continuation_claims.pop(task_handle_id, None)
            return
        raise KeyError(
            f"Unknown Campaign start Diagnostic TaskHandle {task_handle_id!r}"
        )

    def _with_lifecycle_targets(
        self,
        task: DiagnosticTaskSnapshot,
    ) -> DiagnosticTaskSnapshot:
        handoff = task.campaign_handoff
        if handoff is None:
            return task
        campaign = self.get_lifecycle_target(
            DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN,
            handoff.campaign_id,
        )
        nodes = tuple(
            replace(
                node,
                revision=(
                    target.revision
                    if (
                        target := self.get_lifecycle_target(
                            DiagnosticLifecycleTargetKind.CAMPAIGN_NODE,
                            node.campaign_node_id,
                        )
                    )
                    is not None
                    else node.revision
                ),
                lifecycle=(
                    target.lifecycle
                    if target is not None
                    else node.lifecycle
                ),
            )
            for node in handoff.campaign_nodes
        )
        return replace(
            task,
            campaign_handoff=replace(
                handoff,
                campaign_revision=(
                    handoff.campaign_revision
                    if campaign is None
                    else campaign.revision
                ),
                campaign_lifecycle=(
                    handoff.campaign_lifecycle
                    if campaign is None
                    else campaign.lifecycle
                ),
                campaign_nodes=nodes,
            ),
        )

    def _mirror_parent_lifecycle(
        self,
        target: DiagnosticLifecycleTargetSnapshot,
        *,
        lifecycle: DiagnosticTaskLifecycle,
        increment_revision: bool,
    ) -> None:
        if target.target_kind is DiagnosticLifecycleTargetKind.CAMPAIGN_NODE:
            if increment_revision:
                for key, parent in tuple(
                    self._lifecycle_targets.items()
                ):
                    if (
                        parent.task_id == target.task_id
                        and parent.target_kind
                        in {
                            DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK,
                            (
                                DiagnosticLifecycleTargetKind
                                .FORMAL_DIAGNOSTIC_CAMPAIGN
                            ),
                        }
                    ):
                        self._lifecycle_targets[key] = replace(
                            parent,
                            revision=parent.revision + 1,
                        )
            return
        mirror_kind = (
            DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN
            if target.target_kind
            is DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK
            else DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK
        )
        mirror = next(
            (
                candidate
                for (kind, _identity), candidate
                in self._lifecycle_targets.items()
                if kind is mirror_kind
                and candidate.task_id == target.task_id
            ),
            None,
        )
        if mirror is None:
            return
        self._lifecycle_targets[
            (mirror.target_kind, mirror.target_id)
        ] = replace(
            mirror,
            revision=(
                mirror.revision + 1
                if increment_revision
                else mirror.revision
            ),
            lifecycle=lifecycle,
        )

    def _cancel_child_nodes(self, task_id: str) -> None:
        for key, target in tuple(self._lifecycle_targets.items()):
            if (
                target.task_id == task_id
                and target.target_kind
                is DiagnosticLifecycleTargetKind.CAMPAIGN_NODE
                and target.lifecycle
                not in {
                    DiagnosticTaskLifecycle.CANCELED,
                    DiagnosticTaskLifecycle.COMPLETED,
                    DiagnosticTaskLifecycle.FAILED,
                }
            ):
                self._lifecycle_targets[key] = replace(
                    target,
                    revision=target.revision + 1,
                    lifecycle=DiagnosticTaskLifecycle.CANCELED,
                )

    def _with_superseded_lifecycle_handles(
        self,
        task: DiagnosticTaskSnapshot,
        target: DiagnosticLifecycleTargetSnapshot,
        updated_at: datetime,
    ) -> DiagnosticTaskSnapshot:
        superseded: dict[str, DiagnosticLifecycleOperation] = {}
        for handle_id, request in tuple(
            self._pending_lifecycle_requests.items()
        ):
            if (
                request.target_kind is target.target_kind
                and request.target_id == target.target_id
            ):
                superseded[handle_id] = request.operation
                self._pending_lifecycle_requests.pop(handle_id, None)
        if not superseded:
            return task
        return replace(
            task,
            task_handles=tuple(
                replace(
                    handle,
                    phase=DiagnosticTaskHandlePhase.COMPLETED,
                    progress=1.0,
                    result_code=_lifecycle_superseded_result_code(
                        superseded[handle.task_handle_id],
                        target.target_kind,
                    ),
                    cancelable=False,
                    updated_at=updated_at,
                )
                if handle.task_handle_id in superseded
                and handle.phase is DiagnosticTaskHandlePhase.QUEUED
                else handle
                for handle in task.task_handles
            ),
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
            lifecycle_target_rows = connection.execute(
                text(
                    "SELECT target_kind, target_id, task_id, revision, "
                    "lifecycle, updated_at_utc "
                    "FROM diagnostic_lifecycle_targets "
                    "WHERE task_id = :task_id "
                    "ORDER BY target_kind, target_id"
                ),
                {"task_id": task_id},
            ).mappings().all()
        return _task_from_rows(
            task_row,
            handle_rows,
            validation_row=validation_row,
            approval_row=approval_row,
            handoff_row=handoff_row,
            lifecycle_target_rows=lifecycle_target_rows,
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

    def pending_retry_requests(
        self,
    ) -> tuple[RetryFailedCampaignNodeRequest, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT m.command_json "
                    "FROM diagnostic_task_mutation_commands m "
                    "JOIN diagnostic_task_handles h "
                    "ON h.task_handle_id = m.task_handle_id "
                    "WHERE m.command_type = 'retry_failed_campaign_node' "
                    "AND h.phase = :handle_phase "
                    "ORDER BY m.accepted_at_utc, m.command_id"
                ),
                {"handle_phase": DiagnosticTaskHandlePhase.QUEUED.value},
            ).mappings()
            requests: list[RetryFailedCampaignNodeRequest] = []
            for row in rows:
                payload = json.loads(str(row["command_json"]))
                if not isinstance(payload, dict):
                    raise TypeError(
                        "Persisted failed-node retry command must be an object"
                    )
                requests.append(
                    RetryFailedCampaignNodeRequest(
                        command_id=str(payload["command_id"]),
                        idempotency_key=str(payload["idempotency_key"]),
                        task_id=str(payload["task_id"]),
                        campaign_node_id=str(payload["campaign_node_id"]),
                        failed_attempt_id=str(payload["failed_attempt_id"]),
                        expected_revision=int(
                            cast(str | int, payload["expected_revision"])
                        ),
                    )
                )
        return tuple(requests)

    def get_lifecycle_target(
        self,
        target_kind: DiagnosticLifecycleTargetKind,
        target_id: str,
    ) -> DiagnosticLifecycleTargetSnapshot | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT target_kind, target_id, task_id, revision, "
                    "lifecycle FROM diagnostic_lifecycle_targets "
                    "WHERE target_kind = :target_kind "
                    "AND target_id = :target_id"
                ),
                {
                    "target_kind": target_kind.value,
                    "target_id": target_id,
                },
            ).mappings().one_or_none()
        return None if row is None else _lifecycle_target_from_row(row)

    def pending_lifecycle_requests(
        self,
    ) -> tuple[ChangeDiagnosticLifecycleRequest, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT m.command_json "
                    "FROM diagnostic_task_mutation_commands m "
                    "JOIN diagnostic_task_handles h "
                    "ON h.task_handle_id = m.task_handle_id "
                    "WHERE m.command_type IN ("
                    "'pause_diagnostic_target', "
                    "'resume_diagnostic_target', "
                    "'cancel_diagnostic_target') "
                    "AND h.phase = :handle_phase "
                    "ORDER BY m.accepted_at_utc, m.command_id"
                ),
                {
                    "handle_phase": DiagnosticTaskHandlePhase.QUEUED.value,
                },
            ).mappings()
            requests = []
            for row in rows:
                payload = json.loads(str(row["command_json"]))
                if not isinstance(payload, dict):
                    raise TypeError(
                        "Persisted lifecycle command must be an object"
                    )
                requests.append(
                    ChangeDiagnosticLifecycleRequest(
                        command_id=str(payload["command_id"]),
                        idempotency_key=str(payload["idempotency_key"]),
                        operation=DiagnosticLifecycleOperation(
                            str(payload["operation"])
                        ),
                        target_kind=DiagnosticLifecycleTargetKind(
                            str(payload["target_kind"])
                        ),
                        target_id=str(payload["target_id"]),
                        expected_revision=int(
                            cast(str | int, payload["expected_revision"])
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
        return bool(claimed.rowcount == 1)

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

    def accept_failed_node_retry(
        self,
        *,
        record: DiagnosticTaskMutationCommandRecord,
        command_json: str,
        task: DiagnosticTaskSnapshot,
        queued_handle: DiagnosticTaskHandleSnapshot,
        expected_node: DiagnosticLifecycleTargetSnapshot,
        queued_handoff: DiagnosticTaskCampaignHandoffSnapshot,
    ) -> bool:
        queued_node = next(
            (
                node
                for node in queued_handoff.campaign_nodes
                if node.campaign_node_id == expected_node.target_id
            ),
            None,
        )
        if queued_node is None:
            return False
        with self._engine.begin() as connection:
            current_handoff_row = connection.execute(
                text(
                    "SELECT handoff_json FROM diagnostic_task_campaign_handoffs "
                    "WHERE task_id = :task_id AND campaign_id = :campaign_id"
                ),
                {
                    "task_id": task.task_id,
                    "campaign_id": queued_handoff.campaign_id,
                },
            ).mappings().one_or_none()
            if current_handoff_row is None:
                return False
            current_handoff = (
                DiagnosticTaskCampaignHandoffSnapshot.from_storage_dict(
                    cast(
                        Mapping[str, object],
                        json.loads(str(current_handoff_row["handoff_json"])),
                    )
                )
            )
            if current_handoff.campaign_lifecycle not in {
                DiagnosticTaskLifecycle.RUNNING,
                DiagnosticTaskLifecycle.FAILED,
            }:
                return False
            updated_task = connection.execute(
                text(
                    "UPDATE diagnostic_tasks SET revision = :revision, "
                    "lifecycle = :lifecycle, updated_at_utc = :updated_at_utc "
                    "WHERE task_id = :task_id "
                    "AND revision = :expected_revision "
                    "AND lifecycle = :expected_lifecycle"
                ),
                {
                    "revision": task.revision,
                    "lifecycle": task.lifecycle.value,
                    "updated_at_utc": task.updated_at.isoformat(),
                    "task_id": task.task_id,
                    "expected_revision": task.revision - 1,
                    "expected_lifecycle": (
                        current_handoff.campaign_lifecycle.value
                    ),
                },
            )
            if updated_task.rowcount != 1:
                return False
            updated_node = connection.execute(
                text(
                    "UPDATE diagnostic_lifecycle_targets "
                    "SET revision = :revision, lifecycle = :lifecycle, "
                    "updated_at_utc = :updated_at_utc "
                    "WHERE target_kind = :target_kind "
                    "AND target_id = :target_id "
                    "AND task_id = :task_id "
                    "AND revision = :expected_revision "
                    "AND lifecycle = :expected_lifecycle"
                ),
                {
                    "revision": queued_node.revision,
                    "lifecycle": queued_node.lifecycle.value,
                    "updated_at_utc": task.updated_at.isoformat(),
                    "target_kind": (
                        DiagnosticLifecycleTargetKind.CAMPAIGN_NODE.value
                    ),
                    "target_id": expected_node.target_id,
                    "task_id": task.task_id,
                    "expected_revision": expected_node.revision,
                    "expected_lifecycle": expected_node.lifecycle.value,
                },
            )
            if updated_node.rowcount != 1:
                raise ValueError(
                    "Failed-node retry Campaign node changed concurrently"
                )
            for target_kind, target_id, revision, expected_revision in (
                (
                    DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK,
                    task.task_id,
                    task.revision,
                    task.revision - 1,
                ),
                (
                    DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN,
                    queued_handoff.campaign_id,
                    queued_handoff.campaign_revision,
                    queued_handoff.campaign_revision - 1,
                ),
            ):
                updated_parent = connection.execute(
                    text(
                        "UPDATE diagnostic_lifecycle_targets "
                        "SET revision = :revision, lifecycle = :lifecycle, "
                        "updated_at_utc = :updated_at_utc "
                        "WHERE target_kind = :target_kind "
                        "AND target_id = :target_id "
                        "AND task_id = :task_id "
                        "AND revision = :expected_revision "
                        "AND lifecycle = :expected_lifecycle"
                    ),
                    {
                        "revision": revision,
                        "lifecycle": DiagnosticTaskLifecycle.RUNNING.value,
                        "updated_at_utc": task.updated_at.isoformat(),
                        "target_kind": target_kind.value,
                        "target_id": target_id,
                        "task_id": task.task_id,
                        "expected_revision": expected_revision,
                        "expected_lifecycle": (
                            current_handoff.campaign_lifecycle.value
                        ),
                    },
                )
                if updated_parent.rowcount != 1:
                    raise ValueError(
                        "Failed-node retry parent lifecycle changed concurrently"
                    )
            updated_handoff = connection.execute(
                text(
                    "UPDATE diagnostic_task_campaign_handoffs "
                    "SET handoff_json = :handoff_json, "
                    "updated_at_utc = :updated_at_utc "
                    "WHERE task_id = :task_id "
                    "AND campaign_id = :campaign_id "
                    "AND handoff_json = :expected_handoff_json"
                ),
                {
                    "handoff_json": _canonical_json(
                        queued_handoff.to_storage_dict()
                    ),
                    "updated_at_utc": task.updated_at.isoformat(),
                    "task_id": task.task_id,
                    "campaign_id": queued_handoff.campaign_id,
                    "expected_handoff_json": str(
                        current_handoff_row["handoff_json"]
                    ),
                },
            )
            if updated_handoff.rowcount != 1:
                raise ValueError(
                    "Failed-node retry Campaign handoff changed concurrently"
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
            self._insert_mutation_command(
                connection,
                record=record,
                command_json=command_json,
            )
        return True

    def complete_failed_node_retry(
        self,
        task_handle_id: str,
        continuation_claim_id: str,
        handoff: DiagnosticTaskCampaignHandoffSnapshot,
        updated_at: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT h.phase, h.task_id, h.start_continuation_claim_id, "
                    "t.revision AS task_revision, "
                    "t.lifecycle AS task_lifecycle, d.handoff_json "
                    "FROM diagnostic_task_handles h "
                    "JOIN diagnostic_tasks t ON t.task_id = h.task_id "
                    "JOIN diagnostic_task_campaign_handoffs d "
                    "ON d.task_id = h.task_id "
                    "WHERE h.task_handle_id = :task_handle_id"
                ),
                {"task_handle_id": task_handle_id},
            ).mappings().one_or_none()
            if row is None:
                raise KeyError(
                    "Unknown failed-node retry Diagnostic TaskHandle "
                    f"{task_handle_id!r}"
                )
            phase = DiagnosticTaskHandlePhase(str(row["phase"]))
            if phase in {
                DiagnosticTaskHandlePhase.COMPLETED,
                DiagnosticTaskHandlePhase.FAILED,
            }:
                return
            if str(row["start_continuation_claim_id"]) != continuation_claim_id:
                raise ValueError(
                    "Failed-node retry continuation is not owned by this claim"
                )
            current = DiagnosticTaskCampaignHandoffSnapshot.from_storage_dict(
                cast(
                    Mapping[str, object],
                    json.loads(str(row["handoff_json"])),
                )
            )
            target_rows = connection.execute(
                text(
                    "SELECT target_kind, target_id, task_id, revision, "
                    "lifecycle FROM diagnostic_lifecycle_targets "
                    "WHERE task_id = :task_id"
                ),
                {"task_id": str(row["task_id"])},
            ).mappings()
            targets = tuple(
                _lifecycle_target_from_row(target_row)
                for target_row in target_rows
            )
            reconciliation = _reconcile_retry_completion(
                current,
                handoff,
                task_handle_id,
                task_revision=int(
                    cast(str | int, row["task_revision"])
                ),
                task_lifecycle=DiagnosticTaskLifecycle(
                    str(row["task_lifecycle"])
                ),
                targets=targets,
            )
            terminal = _retry_terminal_handle(
                DiagnosticTaskHandleSnapshot(
                    task_handle_id=task_handle_id,
                    task_id=str(row["task_id"]),
                    phase=DiagnosticTaskHandlePhase.QUEUED,
                    progress=0.0,
                    result_code=None,
                    error_code=None,
                    error_message=None,
                    error_retryable=False,
                    cancelable=False,
                    created_at=updated_at,
                    updated_at=updated_at,
                ),
                reconciliation.attempt,
                updated_at,
            )
            updated_handoff = connection.execute(
                text(
                    "UPDATE diagnostic_task_campaign_handoffs "
                    "SET handoff_json = :handoff_json, "
                    "updated_at_utc = :updated_at_utc "
                    "WHERE task_id = :task_id "
                    "AND campaign_id = :campaign_id "
                    "AND handoff_json = :expected_handoff_json"
                ),
                {
                    "handoff_json": _canonical_json(
                        reconciliation.handoff.to_storage_dict()
                    ),
                    "updated_at_utc": updated_at.isoformat(),
                    "task_id": str(row["task_id"]),
                    "campaign_id": reconciliation.handoff.campaign_id,
                    "expected_handoff_json": str(row["handoff_json"]),
                },
            )
            if updated_handoff.rowcount != 1:
                raise ValueError(
                    "Failed-node retry Campaign handoff changed concurrently"
                )
            updated_handle = connection.execute(
                text(
                    "UPDATE diagnostic_task_handles SET phase = :phase, "
                    "progress_value = 1.0, result_code = :result_code, "
                    "error_json = :error_json, cancelable = 0, "
                    "updated_at_utc = :updated_at_utc, "
                    "start_continuation_claim_id = NULL, "
                    "start_continuation_claimed_at_utc = NULL "
                    "WHERE task_handle_id = :task_handle_id "
                    "AND phase = :expected_phase "
                    "AND start_continuation_claim_id = "
                    ":continuation_claim_id"
                ),
                {
                    "phase": terminal.phase.value,
                    "result_code": terminal.result_code,
                    "error_json": _handle_row(terminal)["error_json"],
                    "updated_at_utc": updated_at.isoformat(),
                    "task_handle_id": task_handle_id,
                    "expected_phase": DiagnosticTaskHandlePhase.QUEUED.value,
                    "continuation_claim_id": continuation_claim_id,
                },
            )
            if updated_handle.rowcount != 1:
                raise ValueError(
                    "Failed-node retry TaskHandle changed concurrently"
                )
            updated_task = connection.execute(
                text(
                    "UPDATE diagnostic_tasks SET revision = :revision, "
                    "lifecycle = :lifecycle, updated_at_utc = :updated_at_utc "
                    "WHERE task_id = :task_id "
                    "AND revision = :expected_revision "
                    "AND lifecycle = :expected_lifecycle"
                ),
                {
                    "revision": reconciliation.task_revision,
                    "lifecycle": reconciliation.task_lifecycle.value,
                    "updated_at_utc": updated_at.isoformat(),
                    "task_id": str(row["task_id"]),
                    "expected_revision": int(
                        cast(str | int, row["task_revision"])
                    ),
                    "expected_lifecycle": str(row["task_lifecycle"]),
                },
            )
            if updated_task.rowcount != 1:
                raise ValueError(
                    "Failed-node retry Diagnostic Task changed concurrently"
                )
            for before, after in reconciliation.target_updates:
                updated_target = connection.execute(
                    text(
                        "UPDATE diagnostic_lifecycle_targets "
                        "SET revision = :revision, lifecycle = :lifecycle, "
                        "updated_at_utc = :updated_at_utc "
                        "WHERE target_kind = :target_kind "
                        "AND target_id = :target_id "
                        "AND task_id = :task_id "
                        "AND revision = :expected_revision "
                        "AND lifecycle = :expected_lifecycle"
                    ),
                    {
                        "revision": after.revision,
                        "lifecycle": after.lifecycle.value,
                        "updated_at_utc": updated_at.isoformat(),
                        "target_kind": before.target_kind.value,
                        "target_id": before.target_id,
                        "task_id": str(row["task_id"]),
                        "expected_revision": before.revision,
                        "expected_lifecycle": before.lifecycle.value,
                    },
                )
                if updated_target.rowcount != 1:
                    raise ValueError(
                        "Failed-node retry lifecycle target changed concurrently"
                    )

    def accept_lifecycle(
        self,
        *,
        record: DiagnosticTaskMutationCommandRecord,
        command_json: str,
        task_handle: DiagnosticTaskHandleSnapshot,
        target: DiagnosticLifecycleTargetSnapshot,
        task_revision: int,
        accepted_lifecycle: DiagnosticTaskLifecycle,
    ) -> bool:
        with self._engine.begin() as connection:
            updated_target = connection.execute(
                text(
                    "UPDATE diagnostic_lifecycle_targets "
                    "SET revision = :revision, lifecycle = :lifecycle, "
                    "updated_at_utc = :updated_at_utc "
                    "WHERE target_kind = :target_kind "
                    "AND target_id = :target_id "
                    "AND task_id = :task_id "
                    "AND revision = :expected_revision "
                    "AND lifecycle = :expected_lifecycle"
                ),
                {
                    "revision": target.revision + 1,
                    "lifecycle": accepted_lifecycle.value,
                    "updated_at_utc": task_handle.updated_at.isoformat(),
                    "target_kind": target.target_kind.value,
                    "target_id": target.target_id,
                    "task_id": target.task_id,
                    "expected_revision": target.revision,
                    "expected_lifecycle": target.lifecycle.value,
                },
            )
            if updated_target.rowcount != 1:
                return False
            task_lifecycle = (
                accepted_lifecycle.value
                if target.target_kind
                in {
                    DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK,
                    DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN,
                }
                else None
            )
            updated_task = connection.execute(
                text(
                    "UPDATE diagnostic_tasks "
                    "SET revision = revision + 1, "
                    "lifecycle = COALESCE(:lifecycle, lifecycle), "
                    "updated_at_utc = :updated_at_utc "
                    "WHERE task_id = :task_id "
                    "AND revision = :expected_task_revision"
                ),
                {
                    "lifecycle": task_lifecycle,
                    "updated_at_utc": task_handle.updated_at.isoformat(),
                    "task_id": target.task_id,
                    "expected_task_revision": task_revision,
                },
            )
            if updated_task.rowcount != 1:
                raise ValueError(
                    "Diagnostic Task lifecycle changed concurrently"
                )
            if target.target_kind is not (
                DiagnosticLifecycleTargetKind.CAMPAIGN_NODE
            ):
                mirror_kind = (
                    DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN
                    if target.target_kind
                    is DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK
                    else DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK
                )
                mirrored = connection.execute(
                    text(
                        "UPDATE diagnostic_lifecycle_targets "
                        "SET revision = revision + 1, "
                        "lifecycle = :lifecycle, "
                        "updated_at_utc = :updated_at_utc "
                        "WHERE target_kind = :target_kind "
                        "AND task_id = :task_id"
                    ),
                    {
                        "lifecycle": accepted_lifecycle.value,
                        "updated_at_utc": task_handle.updated_at.isoformat(),
                        "target_kind": mirror_kind.value,
                        "task_id": target.task_id,
                    },
                )
                if mirrored.rowcount != 1:
                    raise ValueError(
                        "Diagnostic lifecycle parent mirror is unavailable"
                    )
            else:
                advanced_parents = connection.execute(
                    text(
                        "UPDATE diagnostic_lifecycle_targets "
                        "SET revision = revision + 1, "
                        "updated_at_utc = :updated_at_utc "
                        "WHERE task_id = :task_id "
                        "AND target_kind IN (:task_kind, :campaign_kind)"
                    ),
                    {
                        "updated_at_utc": task_handle.updated_at.isoformat(),
                        "task_id": target.task_id,
                        "task_kind": (
                            DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK.value
                        ),
                        "campaign_kind": (
                            DiagnosticLifecycleTargetKind
                            .FORMAL_DIAGNOSTIC_CAMPAIGN.value
                        ),
                    },
                )
                if advanced_parents.rowcount != 2:
                    raise ValueError(
                        "Diagnostic lifecycle parent revisions are unavailable"
                    )
            self._supersede_pending_lifecycle_handles(
                connection,
                target,
                task_handle.updated_at,
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
                _handle_row(task_handle),
            )
            self._insert_mutation_command(
                connection,
                record=record,
                command_json=command_json,
            )
        return True

    def complete_lifecycle(
        self,
        task_handle_id: str,
        operation: DiagnosticLifecycleOperation,
        target: DiagnosticLifecycleTargetSnapshot,
        final_lifecycle: DiagnosticTaskLifecycle,
        updated_at: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            handle_row = connection.execute(
                text(
                    "SELECT phase, task_id FROM diagnostic_task_handles "
                    "WHERE task_handle_id = :task_handle_id"
                ),
                {"task_handle_id": task_handle_id},
            ).mappings().one_or_none()
            if handle_row is None:
                raise KeyError(
                    f"Unknown lifecycle TaskHandle {task_handle_id!r}"
                )
            phase = DiagnosticTaskHandlePhase(str(handle_row["phase"]))
            if phase is DiagnosticTaskHandlePhase.COMPLETED:
                return
            if phase is not DiagnosticTaskHandlePhase.QUEUED:
                raise ValueError("Terminal Diagnostic TaskHandle cannot regress")
            updated_target = connection.execute(
                text(
                    "UPDATE diagnostic_lifecycle_targets "
                    "SET lifecycle = :lifecycle, "
                    "updated_at_utc = :updated_at_utc "
                    "WHERE target_kind = :target_kind "
                    "AND target_id = :target_id "
                    "AND task_id = :task_id "
                    "AND revision = :revision"
                ),
                {
                    "lifecycle": final_lifecycle.value,
                    "updated_at_utc": updated_at.isoformat(),
                    "target_kind": target.target_kind.value,
                    "target_id": target.target_id,
                    "task_id": target.task_id,
                    "revision": target.revision + 1,
                },
            )
            if updated_target.rowcount != 1:
                raise ValueError(
                    "Diagnostic lifecycle target changed concurrently"
                )
            if target.target_kind is not (
                DiagnosticLifecycleTargetKind.CAMPAIGN_NODE
            ):
                mirror_kind = (
                    DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN
                    if target.target_kind
                    is DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK
                    else DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK
                )
                connection.execute(
                    text(
                        "UPDATE diagnostic_lifecycle_targets "
                        "SET lifecycle = :lifecycle, "
                        "updated_at_utc = :updated_at_utc "
                        "WHERE target_kind = :target_kind "
                        "AND task_id = :task_id"
                    ),
                    {
                        "lifecycle": final_lifecycle.value,
                        "updated_at_utc": updated_at.isoformat(),
                        "target_kind": mirror_kind.value,
                        "task_id": target.task_id,
                    },
                )
                connection.execute(
                    text(
                        "UPDATE diagnostic_tasks SET lifecycle = :lifecycle, "
                        "updated_at_utc = :updated_at_utc "
                        "WHERE task_id = :task_id"
                    ),
                    {
                        "lifecycle": final_lifecycle.value,
                        "updated_at_utc": updated_at.isoformat(),
                        "task_id": target.task_id,
                    },
                )
            if (
                operation is DiagnosticLifecycleOperation.CANCEL
                and target.target_kind
                in {
                    DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK,
                    DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN,
                }
            ):
                connection.execute(
                    text(
                        "UPDATE diagnostic_lifecycle_targets "
                        "SET revision = revision + 1, "
                        "lifecycle = :lifecycle, "
                        "updated_at_utc = :updated_at_utc "
                        "WHERE target_kind = :target_kind "
                        "AND task_id = :task_id "
                        "AND lifecycle NOT IN ("
                        ":completed, :canceled, :failed)"
                    ),
                    {
                        "lifecycle": DiagnosticTaskLifecycle.CANCELED.value,
                        "updated_at_utc": updated_at.isoformat(),
                        "target_kind": (
                            DiagnosticLifecycleTargetKind.CAMPAIGN_NODE.value
                        ),
                        "task_id": target.task_id,
                        "completed": DiagnosticTaskLifecycle.COMPLETED.value,
                        "canceled": DiagnosticTaskLifecycle.CANCELED.value,
                        "failed": DiagnosticTaskLifecycle.FAILED.value,
                    },
                )
            completed_handle = connection.execute(
                text(
                    "UPDATE diagnostic_task_handles SET phase = :phase, "
                    "progress_value = 1.0, result_code = :result_code, "
                    "cancelable = 0, updated_at_utc = :updated_at_utc "
                    "WHERE task_handle_id = :task_handle_id "
                    "AND phase = :expected_phase"
                ),
                {
                    "phase": DiagnosticTaskHandlePhase.COMPLETED.value,
                    "result_code": _lifecycle_result_code(
                        operation,
                        target.target_kind,
                    ),
                    "updated_at_utc": updated_at.isoformat(),
                    "task_handle_id": task_handle_id,
                    "expected_phase": DiagnosticTaskHandlePhase.QUEUED.value,
                },
            )
            if completed_handle.rowcount != 1:
                raise ValueError(
                    "Diagnostic lifecycle TaskHandle changed concurrently"
                )

    def sync_campaign_progress(
        self,
        handoff: DiagnosticTaskCampaignHandoffSnapshot,
        updated_at: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            handoff_row = connection.execute(
                text(
                    "SELECT h.task_id, h.campaign_id, h.handoff_json, "
                    "t.revision AS task_revision "
                    "FROM diagnostic_task_campaign_handoffs h "
                    "JOIN diagnostic_tasks t ON t.task_id = h.task_id "
                    "WHERE h.campaign_id = :campaign_id"
                ),
                {"campaign_id": handoff.campaign_id},
            ).mappings().one_or_none()
            if handoff_row is None:
                return
            current_handoff = _campaign_handoff_from_row(handoff_row)
            target_rows = connection.execute(
                text(
                    "SELECT target_kind, target_id, task_id, revision, "
                    "lifecycle FROM diagnostic_lifecycle_targets "
                    "WHERE task_id = :task_id"
                ),
                {"task_id": str(handoff_row["task_id"])},
            ).mappings()
            targets = tuple(
                _lifecycle_target_from_row(row) for row in target_rows
            )
            merged = _merge_diagnostic_campaign_progress(
                current_handoff,
                handoff,
                targets,
            )
            if not merged.changed:
                return
            for before, after in merged.target_updates:
                updated_target = connection.execute(
                    text(
                        "UPDATE diagnostic_lifecycle_targets "
                        "SET revision = :revision, lifecycle = :lifecycle, "
                        "updated_at_utc = :updated_at_utc "
                        "WHERE target_kind = :target_kind "
                        "AND target_id = :target_id "
                        "AND task_id = :task_id "
                        "AND revision = :expected_revision "
                        "AND lifecycle = :expected_lifecycle"
                    ),
                    {
                        "revision": after.revision,
                        "lifecycle": after.lifecycle.value,
                        "updated_at_utc": updated_at.isoformat(),
                        "target_kind": before.target_kind.value,
                        "target_id": before.target_id,
                        "task_id": before.task_id,
                        "expected_revision": before.revision,
                        "expected_lifecycle": before.lifecycle.value,
                    },
                )
                if updated_target.rowcount != 1:
                    raise ValueError(
                        "Diagnostic lifecycle target changed concurrently"
                    )
            updated_task = connection.execute(
                text(
                    "UPDATE diagnostic_tasks "
                    "SET revision = revision + 1, lifecycle = :lifecycle, "
                    "updated_at_utc = :updated_at_utc "
                    "WHERE task_id = :task_id "
                    "AND revision = :expected_revision"
                ),
                {
                    "lifecycle": merged.task_lifecycle.value,
                    "updated_at_utc": updated_at.isoformat(),
                    "task_id": str(handoff_row["task_id"]),
                    "expected_revision": int(
                        cast(str | int, handoff_row["task_revision"])
                    ),
                },
            )
            if updated_task.rowcount != 1:
                raise ValueError(
                    "Diagnostic Task Campaign progress changed concurrently"
                )
            updated_handoff = connection.execute(
                text(
                    "UPDATE diagnostic_task_campaign_handoffs "
                    "SET handoff_json = :handoff_json, "
                    "updated_at_utc = :updated_at_utc "
                    "WHERE task_id = :task_id "
                    "AND campaign_id = :campaign_id "
                    "AND handoff_json = :expected_handoff_json"
                ),
                {
                    "handoff_json": _canonical_json(
                        merged.handoff.to_storage_dict()
                    ),
                    "updated_at_utc": updated_at.isoformat(),
                    "task_id": str(handoff_row["task_id"]),
                    "campaign_id": handoff.campaign_id,
                    "expected_handoff_json": str(
                        handoff_row["handoff_json"]
                    ),
                },
            )
            if updated_handoff.rowcount != 1:
                raise ValueError(
                    "Diagnostic Task Campaign handoff changed concurrently"
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
            lifecycle_rows: list[Mapping[str, object]] = [
                {
                    "target_kind": (
                        DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK.value
                    ),
                    "target_id": task_id,
                    "task_id": task_id,
                    "revision": int(
                        connection.execute(
                            text(
                                "SELECT revision FROM diagnostic_tasks "
                                "WHERE task_id = :task_id"
                            ),
                            {"task_id": task_id},
                        ).scalar_one()
                    ),
                    "lifecycle": DiagnosticTaskLifecycle.RUNNING.value,
                    "updated_at_utc": updated_at_utc,
                },
                {
                    "target_kind": (
                        DiagnosticLifecycleTargetKind
                        .FORMAL_DIAGNOSTIC_CAMPAIGN.value
                    ),
                    "target_id": handoff.campaign_id,
                    "task_id": task_id,
                    "revision": handoff.campaign_revision,
                    "lifecycle": handoff.campaign_lifecycle.value,
                    "updated_at_utc": updated_at_utc,
                },
                *[
                    {
                        "target_kind": (
                            DiagnosticLifecycleTargetKind.CAMPAIGN_NODE.value
                        ),
                        "target_id": node.campaign_node_id,
                        "task_id": task_id,
                        "revision": node.revision,
                        "lifecycle": node.lifecycle.value,
                        "updated_at_utc": updated_at_utc,
                    }
                    for node in handoff.campaign_nodes
                ],
            ]
            connection.execute(
                text(
                    "INSERT INTO diagnostic_lifecycle_targets ("
                    "target_kind, target_id, task_id, revision, lifecycle, "
                    "updated_at_utc) VALUES ("
                    ":target_kind, :target_id, :task_id, :revision, "
                    ":lifecycle, :updated_at_utc)"
                ),
                lifecycle_rows,
            )

    @staticmethod
    def _supersede_pending_lifecycle_handles(
        connection: Connection,
        target: DiagnosticLifecycleTargetSnapshot,
        updated_at: datetime,
    ) -> None:
        rows = connection.execute(
            text(
                "SELECT m.task_handle_id, m.command_json "
                "FROM diagnostic_task_mutation_commands m "
                "JOIN diagnostic_task_handles h "
                "ON h.task_handle_id = m.task_handle_id "
                "WHERE m.task_id = :task_id "
                "AND m.command_type IN ("
                "'pause_diagnostic_target', "
                "'resume_diagnostic_target', "
                "'cancel_diagnostic_target') "
                "AND h.phase = :phase"
            ),
            {
                "task_id": target.task_id,
                "phase": DiagnosticTaskHandlePhase.QUEUED.value,
            },
        ).mappings()
        for row in rows:
            payload = json.loads(str(row["command_json"]))
            if not isinstance(payload, dict):
                raise TypeError(
                    "Persisted lifecycle command must be an object"
                )
            if (
                str(payload["target_kind"]) != target.target_kind.value
                or str(payload["target_id"]) != target.target_id
            ):
                continue
            operation = DiagnosticLifecycleOperation(
                str(payload["operation"])
            )
            superseded = connection.execute(
                text(
                    "UPDATE diagnostic_task_handles "
                    "SET phase = :phase, progress_value = 1.0, "
                    "result_code = :result_code, cancelable = 0, "
                    "updated_at_utc = :updated_at_utc "
                    "WHERE task_handle_id = :task_handle_id "
                    "AND phase = :expected_phase"
                ),
                {
                    "phase": DiagnosticTaskHandlePhase.COMPLETED.value,
                    "result_code": _lifecycle_superseded_result_code(
                        operation,
                        target.target_kind,
                    ),
                    "updated_at_utc": updated_at.isoformat(),
                    "task_handle_id": str(row["task_handle_id"]),
                    "expected_phase": (
                        DiagnosticTaskHandlePhase.QUEUED.value
                    ),
                },
            )
            if superseded.rowcount != 1:
                raise ValueError(
                    "Pending lifecycle TaskHandle changed concurrently"
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

    def lifecycle_target(
        self,
        target_kind: DiagnosticLifecycleTargetKind,
        target_id: str,
    ) -> DiagnosticLifecycleTargetSnapshot | None:
        return self._repository.get_lifecycle_target(
            target_kind,
            target_id,
        )

    def sync_campaign_progress(
        self,
        handoff: DiagnosticTaskCampaignHandoffSnapshot,
    ) -> None:
        self._repository.sync_campaign_progress(
            handoff,
            _aware(self._clock()),
        )

    def pending_start_requests(
        self,
    ) -> tuple[StartFormalDiagnosticCampaignRequest, ...]:
        return self._repository.pending_start_requests()

    def pending_retry_requests(
        self,
    ) -> tuple[RetryFailedCampaignNodeRequest, ...]:
        return self._repository.pending_retry_requests()

    def pending_lifecycle_requests(
        self,
    ) -> tuple[ChangeDiagnosticLifecycleRequest, ...]:
        return self._repository.pending_lifecycle_requests()

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

    def retry_failed_campaign_node(
        self,
        request: RetryFailedCampaignNodeRequest,
    ) -> DiagnosticTaskCommandResult:
        if (
            not request.command_id.strip()
            or not request.idempotency_key.strip()
            or not request.task_id.strip()
            or not request.campaign_node_id.strip()
            or not request.failed_attempt_id.strip()
            or request.expected_revision < 1
        ):
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.INVALID_COMMAND,
                message=(
                    "Retry requires command, task, failed node and failed "
                    "attempt identities plus a positive exact node revision."
                ),
                current_revision=None,
            )
        command_content_id = request.command_content_identity()
        existing = self._find_existing_mutation(
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            command_content_id=command_content_id,
            task_id=request.task_id,
            target_kind=DiagnosticLifecycleTargetKind.CAMPAIGN_NODE,
            target_id=request.campaign_node_id,
        )
        if existing is not None:
            if existing.disposition is DiagnosticTaskCreationDisposition.REJECTED:
                return existing
            return replace(
                existing,
                affected_campaign_attempt_id=_retry_attempt_identity_from_task(
                    self._repository.get_task(request.task_id),
                    request.campaign_node_id,
                    existing.task_handle,
                ),
            )
        current = self._read_task_for_command(
            request.command_id,
            request.idempotency_key,
            request.task_id,
        )
        if isinstance(current, DiagnosticTaskCreationResult):
            return current
        handoff = current.campaign_handoff
        node = (
            None
            if handoff is None
            else next(
                (
                    candidate
                    for candidate in handoff.campaign_nodes
                    if candidate.campaign_node_id
                    == request.campaign_node_id
                ),
                None,
            )
        )
        try:
            node_target = self._repository.get_lifecycle_target(
                DiagnosticLifecycleTargetKind.CAMPAIGN_NODE,
                request.campaign_node_id,
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            node_target = None
            read_failed = True
        else:
            read_failed = False
        if handoff is None or node is None or node_target is None:
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=(
                    DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE
                    if read_failed
                    else DiagnosticTaskCreationRejectionReason.INVALID_COMMAND
                ),
                message=(
                    "Failed Campaign node could not be read."
                    if read_failed
                    else "Failed Campaign node target is unavailable."
                ),
                current_revision=None,
                retryable=read_failed,
            )
        if (
            node_target.task_id != request.task_id
            or node_target.revision != node.revision
        ):
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.INVALID_COMMAND,
                message="Campaign node does not belong to this Diagnostic Task.",
                current_revision=node_target.revision,
            )
        if node_target.revision != request.expected_revision:
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=(
                    DiagnosticTaskCreationRejectionReason.STALE_EXPECTED_REVISION
                ),
                message="Expected Campaign node revision is stale.",
                current_revision=node_target.revision,
            )
        if (
            current.lifecycle is not handoff.campaign_lifecycle
            or current.lifecycle
            not in {
                DiagnosticTaskLifecycle.RUNNING,
                DiagnosticTaskLifecycle.FAILED,
            }
        ):
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=(
                    DiagnosticTaskCreationRejectionReason.UNAVAILABLE_INPUT
                ),
                message=(
                    "Failed Campaign node retry is unavailable while the "
                    "parent Campaign is not running or failed."
                ),
                current_revision=node_target.revision,
            )
        failed_attempt = (
            None
            if not node.attempts
            else node.attempts[-1]
        )
        if (
            node_target.lifecycle is not DiagnosticTaskLifecycle.FAILED
            or node.lifecycle is not DiagnosticTaskLifecycle.FAILED
            or node.active_attempt_id != request.failed_attempt_id
            or failed_attempt is None
            or failed_attempt.attempt_id != request.failed_attempt_id
            or failed_attempt.lifecycle is not DiagnosticTaskLifecycle.FAILED
        ):
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.UNAVAILABLE_INPUT,
                message=(
                    "Only the exact active failed Campaign node attempt can "
                    "be retried."
                ),
                current_revision=node_target.revision,
            )
        now = _aware(self._clock())
        handle_id = _stable_identity(
            "diagnostic-task-failed-node-retry-handle",
            request.command_id,
        )
        attempt_number = len(node.attempts) + 1
        attempt_id = (
            f"{handoff.campaign_id}:{node.selected_campaign_case_id}:"
            f"attempt-{attempt_number}"
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
        queued_attempt = DiagnosticCampaignAttemptHandoffSnapshot(
            attempt_id=attempt_id,
            runs=(),
            attempt_number=attempt_number,
            lifecycle=DiagnosticTaskLifecycle.QUEUED,
            predecessor_attempt_id=failed_attempt.attempt_id,
            task_handle_id=handle_id,
        )
        queued_node = replace(
            node,
            attempts=(*node.attempts, queued_attempt),
            active_attempt_id=attempt_id,
            revision=node.revision + 1,
            lifecycle=DiagnosticTaskLifecycle.QUEUED,
        )
        queued_handoff = replace(
            handoff,
            campaign_revision=handoff.campaign_revision + 1,
            campaign_lifecycle=DiagnosticTaskLifecycle.RUNNING,
            campaign_nodes=tuple(
                queued_node
                if candidate.campaign_node_id == node.campaign_node_id
                else candidate
                for candidate in handoff.campaign_nodes
            ),
        )
        queued_task = replace(
            current,
            revision=current.revision + 1,
            lifecycle=DiagnosticTaskLifecycle.RUNNING,
            campaign_handoff=queued_handoff,
            updated_at=now,
        )
        record = DiagnosticTaskMutationCommandRecord(
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            command_type="retry_failed_campaign_node",
            command_content_id=command_content_id,
            task_id=request.task_id,
            task_handle_id=handle_id,
            disposition=(
                DiagnosticTaskCreationDisposition.ASYNCHRONOUS_ACCEPTANCE
            ),
            message="Failed Campaign node retry accepted.",
            current_revision=queued_node.revision,
        )
        command_json = _canonical_json(
            {
                "campaign_node_id": request.campaign_node_id,
                "command_id": request.command_id,
                "command_type": record.command_type,
                "expected_revision": request.expected_revision,
                "failed_attempt_id": request.failed_attempt_id,
                "idempotency_key": request.idempotency_key,
                "task_id": request.task_id,
            }
        )
        try:
            accepted = self._repository.accept_failed_node_retry(
                record=record,
                command_json=command_json,
                task=queued_task,
                queued_handle=queued_handle,
                expected_node=node_target,
                queued_handoff=queued_handoff,
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            replay = self._find_existing_mutation(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                command_content_id=command_content_id,
                task_id=request.task_id,
                target_kind=DiagnosticLifecycleTargetKind.CAMPAIGN_NODE,
                target_id=request.campaign_node_id,
            )
            if replay is not None:
                return replace(
                    replay,
                    affected_campaign_attempt_id=attempt_id,
                )
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE,
                message=(
                    "Retry attempt, TaskHandle, and command could not be "
                    "persisted atomically."
                ),
                current_revision=node.revision,
                retryable=True,
            )
        if not accepted:
            replay = self._find_existing_mutation(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                command_content_id=command_content_id,
                task_id=request.task_id,
                target_kind=DiagnosticLifecycleTargetKind.CAMPAIGN_NODE,
                target_id=request.campaign_node_id,
            )
            if replay is not None:
                return replace(
                    replay,
                    affected_campaign_attempt_id=attempt_id,
                )
            latest = self._repository.get_lifecycle_target(
                DiagnosticLifecycleTargetKind.CAMPAIGN_NODE,
                request.campaign_node_id,
            )
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=request.task_id,
                reason=(
                    DiagnosticTaskCreationRejectionReason.STALE_EXPECTED_REVISION
                ),
                message="Expected Campaign node revision is stale.",
                current_revision=(
                    node.revision if latest is None else latest.revision
                ),
            )
        return replace(
            self._mutation_result(record, task_handle=queued_handle),
            affected_campaign_id=handoff.campaign_id,
            affected_campaign_node_id=node.campaign_node_id,
            affected_campaign_attempt_id=attempt_id,
        )

    def complete_failed_node_retry(
        self,
        task_handle_id: str,
        continuation_claim_id: str,
        handoff: DiagnosticTaskCampaignHandoffSnapshot,
    ) -> None:
        self._repository.complete_failed_node_retry(
            task_handle_id,
            continuation_claim_id,
            handoff,
            _aware(self._clock()),
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

    def change_lifecycle(
        self,
        request: ChangeDiagnosticLifecycleRequest,
    ) -> DiagnosticTaskCommandResult:
        if (
            not request.command_id.strip()
            or not request.idempotency_key.strip()
            or not request.target_id.strip()
            or request.expected_revision < 1
        ):
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=(
                    request.target_id
                    if request.target_kind
                    is DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK
                    else ""
                ),
                reason=DiagnosticTaskCreationRejectionReason.INVALID_COMMAND,
                message=(
                    "Lifecycle command identity, target identity, and a "
                    "positive exact target revision are required."
                ),
                current_revision=None,
            )
        try:
            target = self._repository.get_lifecycle_target(
                request.target_kind,
                request.target_id,
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            target = None
            read_failed = True
        else:
            read_failed = False
        if target is None:
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=(
                    request.target_id
                    if request.target_kind
                    is DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK
                    else ""
                ),
                reason=(
                    DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE
                    if read_failed
                    else DiagnosticTaskCreationRejectionReason.INVALID_COMMAND
                ),
                message=(
                    "Diagnostic lifecycle target could not be read."
                    if read_failed
                    else "Diagnostic lifecycle target is unavailable."
                ),
                current_revision=None,
                retryable=read_failed,
            )
        command_content_id = request.command_content_identity()
        existing = self._find_existing_mutation(
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            command_content_id=command_content_id,
            task_id=target.task_id,
            target_kind=request.target_kind,
            target_id=request.target_id,
        )
        if existing is not None:
            return self._continue_lifecycle_replay(request, target, existing)
        try:
            task = self._repository.get_task(target.task_id)
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            task = None
            task_read_failed = True
        else:
            task_read_failed = False
        if task is None:
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=target.task_id,
                reason=(
                    DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE
                    if task_read_failed
                    else DiagnosticTaskCreationRejectionReason.INVALID_COMMAND
                ),
                message=(
                    "Diagnostic Task lifecycle context could not be read."
                    if task_read_failed
                    else "Diagnostic Task lifecycle context is unavailable."
                ),
                current_revision=target.revision,
                retryable=task_read_failed,
            )
        if target.revision != request.expected_revision:
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=target.task_id,
                reason=(
                    DiagnosticTaskCreationRejectionReason.STALE_EXPECTED_REVISION
                ),
                message="Expected lifecycle target revision is stale.",
                current_revision=target.revision,
            )
        if not self._lifecycle_transition_is_allowed(
            request.operation,
            target,
            task,
        ):
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=target.task_id,
                reason=DiagnosticTaskCreationRejectionReason.INVALID_COMMAND,
                message=(
                    f"{request.operation.value.capitalize()} is not legal "
                    "for the target's authoritative lifecycle."
                ),
                current_revision=target.revision,
            )
        accepted_lifecycle, final_lifecycle = (
            self._lifecycle_transition_states(request.operation)
        )
        now = _aware(self._clock())
        handle_id = _stable_identity(
            f"diagnostic-{request.operation.value}-handle",
            request.command_id,
        )
        queued_handle = DiagnosticTaskHandleSnapshot(
            task_handle_id=handle_id,
            task_id=target.task_id,
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
        record = DiagnosticTaskMutationCommandRecord(
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            command_type=f"{request.operation.value}_diagnostic_target",
            command_content_id=command_content_id,
            task_id=target.task_id,
            task_handle_id=handle_id,
            disposition=(
                DiagnosticTaskCreationDisposition.ASYNCHRONOUS_ACCEPTANCE
            ),
            message=(
                f"Diagnostic lifecycle {request.operation.value} accepted."
            ),
            current_revision=target.revision + 1,
        )
        try:
            accepted = self._repository.accept_lifecycle(
                record=record,
                command_json=_canonical_json(
                    {
                        "command_id": request.command_id,
                        "command_type": record.command_type,
                        "expected_revision": request.expected_revision,
                        "idempotency_key": request.idempotency_key,
                        "operation": request.operation.value,
                        "target_id": request.target_id,
                        "target_kind": request.target_kind.value,
                    }
                ),
                task_handle=queued_handle,
                target=target,
                task_revision=task.revision,
                accepted_lifecycle=accepted_lifecycle,
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            replay = self._find_existing_mutation(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                command_content_id=command_content_id,
                task_id=target.task_id,
                target_kind=request.target_kind,
                target_id=request.target_id,
            )
            if replay is not None:
                return self._continue_lifecycle_replay(
                    request,
                    target,
                    replay,
                )
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=target.task_id,
                reason=DiagnosticTaskCreationRejectionReason.PERSISTENCE_FAILURE,
                message=(
                    "Lifecycle command and TaskHandle could not be persisted "
                    "atomically."
                ),
                current_revision=target.revision,
                retryable=True,
            )
        if not accepted:
            replay = self._find_existing_mutation(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                command_content_id=command_content_id,
                task_id=target.task_id,
                target_kind=request.target_kind,
                target_id=request.target_id,
            )
            if replay is not None:
                return self._continue_lifecycle_replay(
                    request,
                    target,
                    replay,
                )
            latest = self._repository.get_lifecycle_target(
                request.target_kind,
                request.target_id,
            )
            return self._mutation_rejected(
                command_id=request.command_id,
                idempotency_key=request.idempotency_key,
                task_id=target.task_id,
                reason=(
                    DiagnosticTaskCreationRejectionReason.STALE_EXPECTED_REVISION
                ),
                message="Expected lifecycle target revision is stale.",
                current_revision=(
                    target.revision if latest is None else latest.revision
                ),
            )
        try:
            self._repository.complete_lifecycle(
                handle_id,
                request.operation,
                target,
                final_lifecycle,
                _aware(self._clock()),
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            message = (
                f"Diagnostic lifecycle {request.operation.value} accepted; "
                "queued completion will resume when the Application restarts."
            )
            return replace(
                self._lifecycle_mutation_result(
                    record,
                    request,
                    queued_handle,
                ),
                message=message,
            )
        return self._lifecycle_mutation_result(
            record,
            request,
            queued_handle,
        )

    def _continue_lifecycle_replay(
        self,
        request: ChangeDiagnosticLifecycleRequest,
        target: DiagnosticLifecycleTargetSnapshot,
        existing: DiagnosticTaskCommandResult,
    ) -> DiagnosticTaskCommandResult:
        handle = existing.task_handle
        if (
            existing.disposition
            is not DiagnosticTaskCreationDisposition.IDEMPOTENT_REPLAY
            or handle is None
            or handle.phase is not DiagnosticTaskHandlePhase.QUEUED
        ):
            return existing
        accepted_target = self._repository.get_lifecycle_target(
            request.target_kind,
            request.target_id,
        )
        if accepted_target is None:
            return existing
        _accepted_lifecycle, final_lifecycle = (
            self._lifecycle_transition_states(request.operation)
        )
        original_target = replace(
            accepted_target,
            revision=request.expected_revision,
        )
        try:
            self._repository.complete_lifecycle(
                handle.task_handle_id,
                request.operation,
                original_target,
                final_lifecycle,
                _aware(self._clock()),
            )
        except (KeyError, OSError, SQLAlchemyError, TypeError, ValueError):
            return existing
        replay = self._find_existing_mutation(
            command_id=request.command_id,
            idempotency_key=request.idempotency_key,
            command_content_id=request.command_content_identity(),
            task_id=target.task_id,
            target_kind=request.target_kind,
            target_id=request.target_id,
        )
        return existing if replay is None else replay

    @staticmethod
    def _lifecycle_transition_states(
        operation: DiagnosticLifecycleOperation,
    ) -> tuple[DiagnosticTaskLifecycle, DiagnosticTaskLifecycle]:
        if operation is DiagnosticLifecycleOperation.PAUSE:
            return (
                DiagnosticTaskLifecycle.PAUSED,
                DiagnosticTaskLifecycle.PAUSED,
            )
        if operation is DiagnosticLifecycleOperation.RESUME:
            return (
                DiagnosticTaskLifecycle.RESUMING,
                DiagnosticTaskLifecycle.RUNNING,
            )
        return (
            DiagnosticTaskLifecycle.CANCELING,
            DiagnosticTaskLifecycle.CANCELED,
        )

    @staticmethod
    def _lifecycle_transition_is_allowed(
        operation: DiagnosticLifecycleOperation,
        target: DiagnosticLifecycleTargetSnapshot,
        task: DiagnosticTaskSnapshot,
    ) -> bool:
        if task.campaign_handoff is None:
            return False
        if (
            target.target_kind
            is DiagnosticLifecycleTargetKind.CAMPAIGN_NODE
            and operation
            in {
                DiagnosticLifecycleOperation.PAUSE,
                DiagnosticLifecycleOperation.RESUME,
            }
            and task.lifecycle is not DiagnosticTaskLifecycle.RUNNING
        ):
            return False
        allowed = {
            DiagnosticLifecycleOperation.PAUSE: {
                DiagnosticTaskLifecycle.QUEUED,
                DiagnosticTaskLifecycle.RUNNING,
            },
            DiagnosticLifecycleOperation.RESUME: {
                DiagnosticTaskLifecycle.PAUSED,
            },
            DiagnosticLifecycleOperation.CANCEL: {
                DiagnosticTaskLifecycle.QUEUED,
                DiagnosticTaskLifecycle.RUNNING,
                DiagnosticTaskLifecycle.PAUSED,
                DiagnosticTaskLifecycle.RESUMING,
            },
        }
        return target.lifecycle in allowed[operation]

    @staticmethod
    def _lifecycle_mutation_result(
        record: DiagnosticTaskMutationCommandRecord,
        request: ChangeDiagnosticLifecycleRequest,
        task_handle: DiagnosticTaskHandleSnapshot,
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
            affected_campaign_id=(
                request.target_id
                if request.target_kind
                is DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN
                else None
            ),
            affected_campaign_node_id=(
                request.target_id
                if request.target_kind
                is DiagnosticLifecycleTargetKind.CAMPAIGN_NODE
                else None
            ),
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
        target_kind: DiagnosticLifecycleTargetKind | None = None,
        target_id: str | None = None,
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
            current_revision=(
                existing.current_revision
                if target_kind is not None
                else task.revision
            ),
            affected_task_id=task.task_id,
            retryable=False,
            affected_campaign_id=(
                target_id
                if target_kind
                is DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN
                else (
                    None
                    if task.campaign_handoff is None
                    else task.campaign_handoff.campaign_id
                )
            ),
            affected_campaign_node_id=(
                target_id
                if target_kind is DiagnosticLifecycleTargetKind.CAMPAIGN_NODE
                else None
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
    lifecycle_target_rows: Sequence[RowMapping] = (),
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
    lifecycle_targets = tuple(
        _lifecycle_target_from_row(row)
        for row in lifecycle_target_rows
    )
    if campaign_handoff is not None and lifecycle_targets:
        campaign_target = next(
            (
                target
                for target in lifecycle_targets
                if target.target_kind
                is DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN
                and target.target_id == campaign_handoff.campaign_id
            ),
            None,
        )
        nodes_by_id = {
            target.target_id: target
            for target in lifecycle_targets
            if target.target_kind
            is DiagnosticLifecycleTargetKind.CAMPAIGN_NODE
        }
        campaign_handoff = replace(
            campaign_handoff,
            campaign_revision=(
                campaign_handoff.campaign_revision
                if campaign_target is None
                else campaign_target.revision
            ),
            campaign_lifecycle=(
                campaign_handoff.campaign_lifecycle
                if campaign_target is None
                else campaign_target.lifecycle
            ),
            campaign_nodes=tuple(
                replace(
                    node,
                    revision=(
                        nodes_by_id[node.campaign_node_id].revision
                        if node.campaign_node_id in nodes_by_id
                        else node.revision
                    ),
                    lifecycle=(
                        nodes_by_id[node.campaign_node_id].lifecycle
                        if node.campaign_node_id in nodes_by_id
                        else node.lifecycle
                    ),
                )
                for node in campaign_handoff.campaign_nodes
            ),
        )
    if revision < 1 or any(handle.task_id != task_id for handle in handles):
        raise ValueError("Persisted Diagnostic Task identity is inconsistent")
    if validation is not None and (
        validation.task_id != task_id
        or validation.task_revision > revision
        or (
            campaign_handoff is None
            and validation.task_revision != revision
        )
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
        or approval.task_revision > revision
        or (
            campaign_handoff is None
            and approval.task_revision != revision
        )
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
            lifecycle
            in {
                DiagnosticTaskLifecycle.RUNNING,
                DiagnosticTaskLifecycle.PAUSED,
                DiagnosticTaskLifecycle.RESUMING,
                DiagnosticTaskLifecycle.CANCELING,
                DiagnosticTaskLifecycle.CANCELED,
                DiagnosticTaskLifecycle.FAILED,
                DiagnosticTaskLifecycle.COMPLETED,
            }
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


def _attempts_from_storage(
    payloads: list[Mapping[str, object]],
    *,
    final_lifecycle: DiagnosticTaskLifecycle,
) -> tuple[DiagnosticCampaignAttemptHandoffSnapshot, ...]:
    attempts: list[DiagnosticCampaignAttemptHandoffSnapshot] = []
    for index, attempt in enumerate(payloads, start=1):
        failure_code = (
            None
            if attempt.get("failure_code") is None
            else str(attempt["failure_code"])
        )
        failure_message = (
            None
            if attempt.get("failure_message") is None
            else str(attempt["failure_message"])
        )
        lifecycle_value = attempt.get("lifecycle")
        lifecycle = (
            DiagnosticTaskLifecycle(str(lifecycle_value))
            if lifecycle_value is not None
            else (
                final_lifecycle
                if index == len(payloads)
                and final_lifecycle
                in {
                    DiagnosticTaskLifecycle.COMPLETED,
                    DiagnosticTaskLifecycle.FAILED,
                }
                else DiagnosticTaskLifecycle.COMPLETED
            )
        )
        if lifecycle is DiagnosticTaskLifecycle.FAILED and failure_code is None:
            failure_code = "IncompleteCampaign"
            failure_message = (
                failure_message or "Campaign result is incomplete"
            )
        attempts.append(
            DiagnosticCampaignAttemptHandoffSnapshot(
                attempt_id=str(attempt["attempt_id"]),
                runs=tuple(
                    DiagnosticCampaignRunHandoffSnapshot(
                        run_id=str(run["run_id"]),
                        strategy_id=str(run["strategy_id"]),
                        reproduction_manifest_id=(
                            None
                            if run.get("reproduction_manifest_id") is None
                            else str(run["reproduction_manifest_id"])
                        ),
                    )
                    for run in cast(
                        list[Mapping[str, object]],
                        attempt["runs"],
                    )
                ),
                attempt_number=int(
                    cast(str | int, attempt.get("attempt_number", index))
                ),
                lifecycle=lifecycle,
                predecessor_attempt_id=(
                    attempts[-1].attempt_id
                    if attempt.get("predecessor_attempt_id") is None
                    and attempts
                    else (
                        None
                        if attempt.get("predecessor_attempt_id") is None
                        else str(attempt["predecessor_attempt_id"])
                    )
                ),
                task_handle_id=(
                    None
                    if attempt.get("task_handle_id") is None
                    else str(attempt["task_handle_id"])
                ),
                failure_code=failure_code,
                failure_message=failure_message,
            )
        )
    return tuple(attempts)


def _retry_attempt_identity_from_task(
    task: DiagnosticTaskSnapshot | None,
    campaign_node_id: str,
    handle: DiagnosticTaskHandleSnapshot | None,
) -> str | None:
    if task is None or task.campaign_handoff is None or handle is None:
        return None
    node = next(
        (
            candidate
            for candidate in task.campaign_handoff.campaign_nodes
            if candidate.campaign_node_id == campaign_node_id
        ),
        None,
    )
    if node is None:
        return None
    attempt = next(
        (
            candidate
            for candidate in node.attempts
            if candidate.task_handle_id == handle.task_handle_id
        ),
        None,
    )
    return None if attempt is None else attempt.attempt_id


def _retry_terminal_handle(
    handle: DiagnosticTaskHandleSnapshot,
    attempt: DiagnosticCampaignAttemptHandoffSnapshot,
    updated_at: datetime,
) -> DiagnosticTaskHandleSnapshot:
    if attempt.lifecycle is DiagnosticTaskLifecycle.COMPLETED:
        return replace(
            handle,
            phase=DiagnosticTaskHandlePhase.COMPLETED,
            progress=1.0,
            result_code="failed_campaign_node_retry_completed",
            error_code=None,
            error_message=None,
            error_retryable=False,
            cancelable=False,
            updated_at=updated_at,
        )
    if attempt.lifecycle is DiagnosticTaskLifecycle.FAILED:
        return replace(
            handle,
            phase=DiagnosticTaskHandlePhase.FAILED,
            progress=1.0,
            result_code=None,
            error_code=attempt.failure_code,
            error_message=attempt.failure_message,
            error_retryable=True,
            cancelable=False,
            updated_at=updated_at,
        )
    raise ValueError("Failed-node retry must complete with a terminal attempt")


def _attempt_history_prefix_matches(
    current: tuple[DiagnosticCampaignAttemptHandoffSnapshot, ...],
    incoming: tuple[DiagnosticCampaignAttemptHandoffSnapshot, ...],
) -> bool:
    return len(current) == len(incoming) and all(
        (
            incoming_attempt.task_handle_id
            in {None, current_attempt.task_handle_id}
            and replace(current_attempt, task_handle_id=None, runs=())
            == replace(incoming_attempt, task_handle_id=None, runs=())
            and len(current_attempt.runs) == len(incoming_attempt.runs)
            and all(
                current_run.run_id == incoming_run.run_id
                and current_run.strategy_id == incoming_run.strategy_id
                and current_run.reproduction_manifest_id
                in {None, incoming_run.reproduction_manifest_id}
                for current_run, incoming_run in zip(
                    current_attempt.runs,
                    incoming_attempt.runs,
                    strict=True,
                )
            )
        )
        for current_attempt, incoming_attempt in zip(
            current,
            incoming,
            strict=True,
        )
    )


def _extend_attempt_history_preserving_bindings(
    current: tuple[DiagnosticCampaignAttemptHandoffSnapshot, ...],
    incoming: tuple[DiagnosticCampaignAttemptHandoffSnapshot, ...],
) -> tuple[DiagnosticCampaignAttemptHandoffSnapshot, ...]:
    if len(incoming) < len(current) or not _attempt_history_prefix_matches(
        current,
        incoming[: len(current)],
    ):
        raise ValueError(
            "Formal Diagnostic Campaign attempt history cannot regress"
        )
    enriched = tuple(
        replace(
            current_attempt,
            runs=tuple(
                replace(
                    current_run,
                    reproduction_manifest_id=(
                        incoming_run.reproduction_manifest_id
                    ),
                )
                for current_run, incoming_run in zip(
                    current_attempt.runs,
                    incoming_attempt.runs,
                    strict=True,
                )
            ),
        )
        for current_attempt, incoming_attempt in zip(
            current,
            incoming[: len(current)],
            strict=True,
        )
    )
    return (*enriched, *incoming[len(current) :])


def _complete_retry_handoff(
    current: DiagnosticTaskCampaignHandoffSnapshot,
    incoming: DiagnosticTaskCampaignHandoffSnapshot,
    task_handle_id: str,
) -> tuple[
    DiagnosticTaskCampaignHandoffSnapshot,
    DiagnosticCampaignAttemptHandoffSnapshot,
]:
    if current.campaign_id != incoming.campaign_id:
        raise ValueError("Formal Diagnostic Campaign identity cannot change")
    if tuple(node.campaign_node_id for node in current.campaign_nodes) != tuple(
        node.campaign_node_id for node in incoming.campaign_nodes
    ):
        raise ValueError("Formal Diagnostic Campaign nodes cannot change")
    merged_nodes: list[DiagnosticCampaignNodeHandoffSnapshot] = []
    completed_attempt: DiagnosticCampaignAttemptHandoffSnapshot | None = None
    for current_node, incoming_node in zip(
        current.campaign_nodes,
        incoming.campaign_nodes,
        strict=True,
    ):
        if (
            current_node.campaign_case_id != incoming_node.campaign_case_id
            or current_node.selected_campaign_case_id
            != incoming_node.selected_campaign_case_id
            or current_node.market_scenario_id
            != incoming_node.market_scenario_id
        ):
            raise ValueError(
                "Formal Diagnostic Campaign node identity cannot change"
            )
        placeholder = next(
            (
                attempt
                for attempt in current_node.attempts
                if attempt.task_handle_id == task_handle_id
            ),
            None,
        )
        if placeholder is None:
            if (
                len(incoming_node.attempts) != len(current_node.attempts)
                or not _attempt_history_prefix_matches(
                    current_node.attempts,
                    incoming_node.attempts,
                )
            ):
                raise ValueError(
                    "Unrelated Campaign attempt history cannot change during retry"
                )
            merged_nodes.append(current_node)
            continue
        if (
            placeholder is not current_node.attempts[-1]
            or placeholder.lifecycle is not DiagnosticTaskLifecycle.QUEUED
            or len(incoming_node.attempts) != len(current_node.attempts)
            or not _attempt_history_prefix_matches(
                current_node.attempts[:-1],
                incoming_node.attempts[:-1],
            )
        ):
            raise ValueError(
                "Failed-node retry attempt history cannot regress or fork"
            )
        terminal = incoming_node.attempts[-1]
        if (
            terminal.attempt_id != placeholder.attempt_id
            or terminal.attempt_number != placeholder.attempt_number
            or terminal.lifecycle
            not in {
                DiagnosticTaskLifecycle.COMPLETED,
                DiagnosticTaskLifecycle.FAILED,
            }
        ):
            raise ValueError(
                "Failed-node retry must complete the accepted attempt identity"
            )
        completed_attempt = replace(
            terminal,
            predecessor_attempt_id=placeholder.predecessor_attempt_id,
            task_handle_id=task_handle_id,
        )
        merged_nodes.append(
            replace(
                current_node,
                attempts=(*current_node.attempts[:-1], completed_attempt),
                active_attempt_id=completed_attempt.attempt_id,
                revision=current_node.revision + 1,
                lifecycle=completed_attempt.lifecycle,
            )
        )
    if completed_attempt is None:
        raise ValueError(
            "Failed-node retry TaskHandle is not bound to an accepted attempt"
        )
    active_lifecycles = {
        DiagnosticTaskLifecycle.QUEUED,
        DiagnosticTaskLifecycle.RUNNING,
        DiagnosticTaskLifecycle.PAUSED,
        DiagnosticTaskLifecycle.RESUMING,
        DiagnosticTaskLifecycle.CANCELING,
    }
    node_lifecycles = tuple(node.lifecycle for node in merged_nodes)
    if any(lifecycle in active_lifecycles for lifecycle in node_lifecycles):
        campaign_lifecycle = DiagnosticTaskLifecycle.RUNNING
    elif DiagnosticTaskLifecycle.CANCELED in node_lifecycles:
        campaign_lifecycle = DiagnosticTaskLifecycle.CANCELED
    elif DiagnosticTaskLifecycle.FAILED in node_lifecycles:
        campaign_lifecycle = DiagnosticTaskLifecycle.FAILED
    else:
        campaign_lifecycle = DiagnosticTaskLifecycle.COMPLETED
    return (
        replace(
            current,
            campaign_revision=current.campaign_revision + 1,
            campaign_lifecycle=campaign_lifecycle,
            campaign_nodes=tuple(merged_nodes),
        ),
        completed_attempt,
    )


def _reconcile_retry_completion(
    current: DiagnosticTaskCampaignHandoffSnapshot,
    incoming: DiagnosticTaskCampaignHandoffSnapshot,
    task_handle_id: str,
    *,
    task_revision: int,
    task_lifecycle: DiagnosticTaskLifecycle,
    targets: tuple[DiagnosticLifecycleTargetSnapshot, ...],
) -> _DiagnosticRetryCompletionMerge:
    merged, attempt = _complete_retry_handoff(
        current,
        incoming,
        task_handle_id,
    )
    targets_by_key = {
        (target.target_kind, target.target_id): target
        for target in targets
    }
    task_target = next(
        (
            target
            for target in targets
            if target.target_kind
            is DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK
        ),
        None,
    )
    campaign_target = targets_by_key.get(
        (
            DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN,
            current.campaign_id,
        )
    )
    if task_target is None or campaign_target is None:
        raise ValueError(
            "Failed-node retry parent lifecycle is unavailable"
        )
    if (
        task_target.target_id != task_target.task_id
        or task_target.task_id != campaign_target.task_id
        or task_target.revision != task_revision
        or task_target.lifecycle is not task_lifecycle
        or campaign_target.lifecycle is not task_target.lifecycle
    ):
        raise ValueError(
            "Failed-node retry parent lifecycle is inconsistent"
        )
    parent_lifecycle = (
        merged.campaign_lifecycle
        if task_target.lifecycle is DiagnosticTaskLifecycle.RUNNING
        else task_target.lifecycle
    )
    updated_task_target = replace(
        task_target,
        revision=task_target.revision + 1,
        lifecycle=parent_lifecycle,
    )
    updated_campaign_target = replace(
        campaign_target,
        revision=campaign_target.revision + 1,
        lifecycle=parent_lifecycle,
    )
    target_updates: list[
        tuple[
            DiagnosticLifecycleTargetSnapshot,
            DiagnosticLifecycleTargetSnapshot,
        ]
    ] = [
        (task_target, updated_task_target),
        (campaign_target, updated_campaign_target),
    ]
    merged_nodes: list[DiagnosticCampaignNodeHandoffSnapshot] = []
    retry_target_found = False
    for node in merged.campaign_nodes:
        target = targets_by_key.get(
            (
                DiagnosticLifecycleTargetKind.CAMPAIGN_NODE,
                node.campaign_node_id,
            )
        )
        if target is None or target.task_id != task_target.task_id:
            raise ValueError(
                "Failed-node retry lifecycle node is unavailable"
            )
        owns_retry_attempt = any(
            candidate.task_handle_id == task_handle_id
            for candidate in node.attempts
        )
        if owns_retry_attempt:
            if retry_target_found:
                raise ValueError(
                    "Failed-node retry TaskHandle is bound to multiple nodes"
                )
            retry_target_found = True
            updated_target = replace(
                target,
                revision=target.revision + 1,
                lifecycle=(
                    attempt.lifecycle
                    if target.lifecycle is DiagnosticTaskLifecycle.QUEUED
                    else target.lifecycle
                ),
            )
            target_updates.append((target, updated_target))
            merged_nodes.append(
                replace(
                    node,
                    revision=updated_target.revision,
                    lifecycle=updated_target.lifecycle,
                )
            )
            continue
        merged_nodes.append(
            replace(
                node,
                revision=target.revision,
                lifecycle=target.lifecycle,
            )
        )
    if not retry_target_found:
        raise ValueError(
            "Failed-node retry TaskHandle is not bound to a lifecycle node"
        )
    return _DiagnosticRetryCompletionMerge(
        handoff=replace(
            merged,
            campaign_revision=updated_campaign_target.revision,
            campaign_lifecycle=parent_lifecycle,
            campaign_nodes=tuple(merged_nodes),
        ),
        attempt=attempt,
        task_revision=updated_task_target.revision,
        task_lifecycle=parent_lifecycle,
        target_updates=tuple(target_updates),
    )


def _merge_diagnostic_campaign_progress(
    current: DiagnosticTaskCampaignHandoffSnapshot,
    incoming: DiagnosticTaskCampaignHandoffSnapshot,
    targets: tuple[DiagnosticLifecycleTargetSnapshot, ...],
) -> _DiagnosticCampaignProgressMerge:
    if current.campaign_id != incoming.campaign_id:
        raise ValueError("Formal Diagnostic Campaign identity cannot change")
    current_evidence = (
        current.evidence_state,
        current.evidence_package_id,
        current.reproduction_manifest_id,
        current.evidence_error_code,
        current.evidence_error_message,
    )
    incoming_evidence = (
        incoming.evidence_state,
        incoming.evidence_package_id,
        incoming.reproduction_manifest_id,
        incoming.evidence_error_code,
        incoming.evidence_error_message,
    )
    if (
        current.evidence_state is not DiagnosticEvidenceHandoffState.PENDING
        and incoming_evidence != current_evidence
    ):
        raise ValueError("Terminal Diagnostic Evidence handoff cannot change")
    evidence_changed = incoming_evidence != current_evidence
    current_node_ids = tuple(
        node.campaign_node_id for node in current.campaign_nodes
    )
    incoming_node_ids = tuple(
        node.campaign_node_id for node in incoming.campaign_nodes
    )
    if current_node_ids != incoming_node_ids:
        raise ValueError("Formal Diagnostic Campaign nodes cannot change")
    targets_by_key = {
        (target.target_kind, target.target_id): target
        for target in targets
    }
    node_updates: list[
        tuple[
            DiagnosticLifecycleTargetSnapshot,
            DiagnosticLifecycleTargetSnapshot,
        ]
    ] = []
    merged_nodes: list[DiagnosticCampaignNodeHandoffSnapshot] = []
    progressed = False
    for current_node, incoming_node in zip(
        current.campaign_nodes,
        incoming.campaign_nodes,
        strict=True,
    ):
        if (
            current_node.campaign_case_id
            != incoming_node.campaign_case_id
            or current_node.selected_campaign_case_id
            != incoming_node.selected_campaign_case_id
            or current_node.market_scenario_id
            != incoming_node.market_scenario_id
        ):
            raise ValueError(
                "Formal Diagnostic Campaign node identity cannot change"
            )
        merged_attempts = _extend_attempt_history_preserving_bindings(
            current_node.attempts,
            incoming_node.attempts,
        )
        target = targets_by_key.get(
            (
                DiagnosticLifecycleTargetKind.CAMPAIGN_NODE,
                current_node.campaign_node_id,
            )
        )
        if target is None:
            raise ValueError(
                "Formal Diagnostic Campaign lifecycle node is unavailable"
            )
        attempts_changed = (
            merged_attempts != current_node.attempts
            or incoming_node.active_attempt_id
            != current_node.active_attempt_id
        )
        updated_target = target
        execution_terminal = (
            bool(incoming_node.attempts)
            and incoming_node.lifecycle
            in {
                DiagnosticTaskLifecycle.COMPLETED,
                DiagnosticTaskLifecycle.FAILED,
            }
        )
        if attempts_changed and not execution_terminal:
            raise ValueError(
                "Campaign node execution must produce a terminal result"
            )
        if (
            execution_terminal
            and target.lifecycle
            in {
                DiagnosticTaskLifecycle.QUEUED,
                DiagnosticTaskLifecycle.RUNNING,
                DiagnosticTaskLifecycle.RESUMING,
            }
        ):
            updated_target = replace(
                target,
                revision=target.revision + 1,
                lifecycle=incoming_node.lifecycle,
            )
            node_updates.append((target, updated_target))
        if attempts_changed or updated_target != target:
            progressed = True
        merged_nodes.append(
            replace(
                incoming_node,
                attempts=merged_attempts,
                revision=updated_target.revision,
                lifecycle=updated_target.lifecycle,
            )
        )
    campaign_target = targets_by_key.get(
        (
            DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN,
            current.campaign_id,
        )
    )
    task_target = next(
        (
            target
            for target in targets
            if target.target_kind
            is DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK
        ),
        None,
    )
    if campaign_target is None or task_target is None:
        raise ValueError(
            "Formal Diagnostic Campaign parent lifecycle is unavailable"
        )
    if campaign_target.lifecycle is not task_target.lifecycle:
        raise ValueError(
            "Formal Diagnostic Campaign parent lifecycle is inconsistent"
        )
    terminal = {
        DiagnosticTaskLifecycle.CANCELED,
        DiagnosticTaskLifecycle.COMPLETED,
        DiagnosticTaskLifecycle.FAILED,
    }
    node_lifecycles = tuple(node.lifecycle for node in merged_nodes)
    aggregate_lifecycle: DiagnosticTaskLifecycle
    if campaign_target.lifecycle is not DiagnosticTaskLifecycle.RUNNING:
        aggregate_lifecycle = campaign_target.lifecycle
    elif all(lifecycle in terminal for lifecycle in node_lifecycles):
        if DiagnosticTaskLifecycle.CANCELED in node_lifecycles:
            aggregate_lifecycle = DiagnosticTaskLifecycle.CANCELED
        elif DiagnosticTaskLifecycle.FAILED in node_lifecycles:
            aggregate_lifecycle = DiagnosticTaskLifecycle.FAILED
        else:
            aggregate_lifecycle = DiagnosticTaskLifecycle.COMPLETED
    else:
        aggregate_lifecycle = DiagnosticTaskLifecycle.RUNNING
    if (
        not progressed
        and not evidence_changed
        and aggregate_lifecycle is campaign_target.lifecycle
    ):
        return _DiagnosticCampaignProgressMerge(
            handoff=current,
            target_updates=(),
            task_lifecycle=task_target.lifecycle,
            changed=False,
        )
    updated_campaign_target = replace(
        campaign_target,
        revision=campaign_target.revision + 1,
        lifecycle=aggregate_lifecycle,
    )
    updated_task_target = replace(
        task_target,
        revision=task_target.revision + 1,
        lifecycle=aggregate_lifecycle,
    )
    return _DiagnosticCampaignProgressMerge(
        handoff=replace(
            incoming,
            campaign_revision=updated_campaign_target.revision,
            campaign_lifecycle=aggregate_lifecycle,
            campaign_nodes=tuple(merged_nodes),
        ),
        target_updates=(
            *node_updates,
            (campaign_target, updated_campaign_target),
            (task_target, updated_task_target),
        ),
        task_lifecycle=aggregate_lifecycle,
        changed=True,
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


def _lifecycle_target_from_row(
    row: RowMapping,
) -> DiagnosticLifecycleTargetSnapshot:
    return DiagnosticLifecycleTargetSnapshot(
        target_kind=DiagnosticLifecycleTargetKind(str(row["target_kind"])),
        target_id=str(row["target_id"]),
        task_id=str(row["task_id"]),
        revision=int(cast(str | int, row["revision"])),
        lifecycle=DiagnosticTaskLifecycle(str(row["lifecycle"])),
    )


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


def _lifecycle_result_code(
    operation: DiagnosticLifecycleOperation,
    target_kind: DiagnosticLifecycleTargetKind,
) -> str:
    target_name = {
        DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK: "diagnostic_task",
        DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN: (
            "formal_diagnostic_campaign"
        ),
        DiagnosticLifecycleTargetKind.CAMPAIGN_NODE: "campaign_node",
    }[target_kind]
    completed_operation = {
        DiagnosticLifecycleOperation.PAUSE: "paused",
        DiagnosticLifecycleOperation.RESUME: "resumed",
        DiagnosticLifecycleOperation.CANCEL: "canceled",
    }[operation]
    return f"{target_name}_{completed_operation}"


def _lifecycle_superseded_result_code(
    operation: DiagnosticLifecycleOperation,
    target_kind: DiagnosticLifecycleTargetKind,
) -> str:
    target_name = {
        DiagnosticLifecycleTargetKind.DIAGNOSTIC_TASK: "diagnostic_task",
        DiagnosticLifecycleTargetKind.FORMAL_DIAGNOSTIC_CAMPAIGN: (
            "formal_diagnostic_campaign"
        ),
        DiagnosticLifecycleTargetKind.CAMPAIGN_NODE: "campaign_node",
    }[target_kind]
    return f"{target_name}_{operation.value}_superseded"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


__all__ = [
    "ApproveDiagnosticTaskConfigurationRequest",
    "ChangeDiagnosticLifecycleRequest",
    "CreateDiagnosticTaskRequest",
    "DiagnosticCampaignAttemptHandoffSnapshot",
    "DiagnosticCampaignCaseSelection",
    "DiagnosticCampaignNodeHandoffSnapshot",
    "DiagnosticCampaignRunHandoffSnapshot",
    "DiagnosticEvidenceHandoffState",
    "DiagnosticLifecycleOperation",
    "DiagnosticLifecycleTargetKind",
    "DiagnosticLifecycleTargetSnapshot",
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
    "RetryFailedCampaignNodeRequest",
    "ReviseDiagnosticTaskConfigurationRequest",
    "SqlDiagnosticTaskRepository",
    "StartFormalDiagnosticCampaignRequest",
    "ValidateDiagnosticTaskConfigurationRequest",
]
