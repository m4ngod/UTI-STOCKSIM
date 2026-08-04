"""Durable Scenario Lab Draft commands and exact validation dependency truth."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from threading import RLock
from typing import Literal, Protocol, cast

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .historical_segments import HistoricalMarketSegment
from .recipes import (
    AIRecipeAuthoringResult,
    ApprovedScenarioRecipeVersion,
    RecipeValidationIssue,
    RecipeValidationResult,
    RecipeWorkbench,
    ScenarioRecipeDraft,
    ScenarioRecipeV1,
    legacy_scenario_recipe_approval_identity,
)


ScenarioLabAuthoringMode = Literal["manual", "ai_assisted"]
ScenarioLabCommandDisposition = Literal["accepted", "conflict", "rejected"]
ScenarioRecipeApprovalAuthorityState = Literal[
    "current",
    "outdated",
    "incompatible",
    "unavailable",
]


def _canonical_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


def canonical_json(value: object) -> str:
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _identity(prefix: str, value: str) -> str:
    return prefix + hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ScenarioRecipeDraftRevisionRecord:
    draft: ScenarioRecipeDraft
    revision: int
    predecessor_draft_id: str | None
    authoring_mode: ScenarioLabAuthoringMode
    assistant_attempt_id: str | None
    accepted_command_id: str


@dataclass(frozen=True, slots=True)
class ScenarioRecipeValidationDependencyRecord:
    historical_segment_id: str
    historical_segment_content_hash: str
    source_snapshot_id: str
    source_snapshot_content_hash: str
    recipe_schema_identity: str
    recipe_schema_hash: str
    transformation_catalog_version: str
    transformation_catalog_hash: str
    transformation_implementation_identities: tuple[str, ...]
    data_policy: str
    causality_rule_identities: tuple[str, ...]
    market_rule_profile_version: str
    market_rule_profile_hash: str
    compatibility_observations: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True, slots=True)
class ScenarioRecipeValidationRecord:
    validation_id: str
    draft_revision: int
    result: RecipeValidationResult
    dependencies: ScenarioRecipeValidationDependencyRecord
    accepted_command_id: str


@dataclass(frozen=True, slots=True)
class ScenarioRecipeApprovalRecord:
    approval_id: str
    version: ApprovedScenarioRecipeVersion
    draft: ScenarioRecipeDraftRevisionRecord
    validation: ScenarioRecipeValidationRecord | None
    authority_state: ScenarioRecipeApprovalAuthorityState
    authority_message: str
    can_materialize: bool


@dataclass(frozen=True, slots=True)
class ScenarioLabAuthoringCommandRecord:
    command_id: str
    idempotency_identity: str
    canonical_content_identity: str
    operation: str
    disposition: str
    message: str
    expected_source_revision: str
    expected_source_generation: int
    result_kind: str | None
    result_identity: str | None
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class ScenarioLabAuthoringResult:
    disposition: ScenarioLabCommandDisposition
    message: str
    command: ScenarioLabAuthoringCommandRecord | None = None
    draft: ScenarioRecipeDraftRevisionRecord | None = None
    validation: ScenarioRecipeValidationRecord | None = None
    approval: ScenarioRecipeApprovalRecord | None = None
    authoritative_draft_revision: int | None = None


class ScenarioLabAuthoringRepository(Protocol):
    def claim_command(
        self, record: ScenarioLabAuthoringCommandRecord
    ) -> ScenarioLabAuthoringCommandRecord: ...

    def reject_command(
        self,
        command_id: str,
        *,
        message: str,
        result_kind: str,
        result_identity: str,
        completed_at: datetime,
    ) -> ScenarioLabAuthoringCommandRecord: ...

    def complete_command(
        self,
        command_id: str,
        *,
        result_kind: str,
        result_identity: str,
        completed_at: datetime,
    ) -> ScenarioLabAuthoringCommandRecord: ...

    def get_command_by_idempotency(
        self, identity: str
    ) -> ScenarioLabAuthoringCommandRecord | None: ...

    def get_command(
        self, command_id: str
    ) -> ScenarioLabAuthoringCommandRecord | None: ...

    def get_draft_by_accepted_command(
        self, command_id: str
    ) -> ScenarioRecipeDraftRevisionRecord | None: ...

    def get_validation_by_accepted_command(
        self, command_id: str
    ) -> ScenarioRecipeValidationRecord | None: ...

    def add_draft_revision(
        self, record: ScenarioRecipeDraftRevisionRecord
    ) -> ScenarioRecipeDraftRevisionRecord: ...

    def get_draft_revision(
        self, draft_id: str
    ) -> ScenarioRecipeDraftRevisionRecord | None: ...

    def list_draft_revisions(
        self,
    ) -> tuple[ScenarioRecipeDraftRevisionRecord, ...]: ...

    def current_recipe_revision(self, recipe_id: str) -> int: ...

    def add_validation(
        self, record: ScenarioRecipeValidationRecord
    ) -> ScenarioRecipeValidationRecord: ...

    def get_validation(
        self, validation_id: str
    ) -> ScenarioRecipeValidationRecord | None: ...

    def list_validations(self) -> tuple[ScenarioRecipeValidationRecord, ...]: ...


class InMemoryScenarioLabAuthoringRepository:
    def __init__(self) -> None:
        self._commands: dict[str, ScenarioLabAuthoringCommandRecord] = {}
        self._command_by_idempotency: dict[str, str] = {}
        self._drafts: dict[str, ScenarioRecipeDraftRevisionRecord] = {}
        self._validations: dict[str, ScenarioRecipeValidationRecord] = {}

    def claim_command(
        self, record: ScenarioLabAuthoringCommandRecord
    ) -> ScenarioLabAuthoringCommandRecord:
        existing = self.get_command_by_idempotency(record.idempotency_identity)
        if existing is not None:
            return existing
        identity_collision = self._commands.get(record.command_id)
        if identity_collision is not None and identity_collision != record:
            raise ValueError("immutable Scenario Lab command identity collision")
        self._commands[record.command_id] = record
        self._command_by_idempotency[record.idempotency_identity] = record.command_id
        return record

    def complete_command(
        self,
        command_id: str,
        *,
        result_kind: str,
        result_identity: str,
        completed_at: datetime,
    ) -> ScenarioLabAuthoringCommandRecord:
        current = self._commands[command_id]
        completed = replace(
            current,
            disposition="accepted",
            message="Scenario Lab command completed.",
            result_kind=result_kind,
            result_identity=result_identity,
            completed_at=completed_at,
        )
        self._commands[command_id] = completed
        return completed

    def reject_command(
        self,
        command_id: str,
        *,
        message: str,
        result_kind: str,
        result_identity: str,
        completed_at: datetime,
    ) -> ScenarioLabAuthoringCommandRecord:
        current = self._commands[command_id]
        rejected = replace(
            current,
            disposition="rejected",
            message=message,
            result_kind=result_kind,
            result_identity=result_identity,
            completed_at=completed_at,
        )
        self._commands[command_id] = rejected
        return rejected

    def get_command_by_idempotency(
        self, identity: str
    ) -> ScenarioLabAuthoringCommandRecord | None:
        command_id = self._command_by_idempotency.get(identity)
        return None if command_id is None else self._commands[command_id]

    def get_command(
        self, command_id: str
    ) -> ScenarioLabAuthoringCommandRecord | None:
        return self._commands.get(command_id)

    def add_draft_revision(
        self, record: ScenarioRecipeDraftRevisionRecord
    ) -> ScenarioRecipeDraftRevisionRecord:
        existing = self._drafts.get(record.draft.draft_id)
        if existing is not None and existing != record:
            raise ValueError("immutable Scenario Recipe Draft revision collision")
        if existing is None and any(
            item.draft.recipe_id == record.draft.recipe_id
            and item.revision == record.revision
            for item in self._drafts.values()
        ):
            raise ValueError("Scenario Recipe Draft revision already exists")
        self._drafts[record.draft.draft_id] = record
        return record

    def get_draft_revision(
        self, draft_id: str
    ) -> ScenarioRecipeDraftRevisionRecord | None:
        return self._drafts.get(draft_id)

    def get_draft_by_accepted_command(
        self, command_id: str
    ) -> ScenarioRecipeDraftRevisionRecord | None:
        return next(
            (
                item
                for item in self._drafts.values()
                if item.accepted_command_id == command_id
            ),
            None,
        )

    def list_draft_revisions(
        self,
    ) -> tuple[ScenarioRecipeDraftRevisionRecord, ...]:
        return tuple(
            sorted(
                self._drafts.values(),
                key=lambda item: (item.draft.recipe_id, item.revision),
            )
        )

    def current_recipe_revision(self, recipe_id: str) -> int:
        return max(
            (
                item.revision
                for item in self._drafts.values()
                if item.draft.recipe_id == recipe_id
            ),
            default=0,
        )

    def add_validation(
        self, record: ScenarioRecipeValidationRecord
    ) -> ScenarioRecipeValidationRecord:
        existing = self._validations.get(record.validation_id)
        if existing is not None and existing != record:
            raise ValueError("immutable Scenario Recipe validation collision")
        self._validations[record.validation_id] = record
        return record

    def get_validation(
        self, validation_id: str
    ) -> ScenarioRecipeValidationRecord | None:
        return self._validations.get(validation_id)

    def get_validation_by_accepted_command(
        self, command_id: str
    ) -> ScenarioRecipeValidationRecord | None:
        return next(
            (
                item
                for item in self._validations.values()
                if item.accepted_command_id == command_id
            ),
            None,
        )

    def list_validations(self) -> tuple[ScenarioRecipeValidationRecord, ...]:
        return tuple(
            sorted(
                self._validations.values(),
                key=lambda item: (item.result.validated_at, item.validation_id),
            )
        )


class SqlScenarioLabAuthoringRepository:
    def __init__(self, engine: Engine, recipe_workbench: RecipeWorkbench) -> None:
        self._engine = engine
        self._recipe_workbench = recipe_workbench

    def claim_command(
        self, record: ScenarioLabAuthoringCommandRecord
    ) -> ScenarioLabAuthoringCommandRecord:
        with self._engine.begin() as connection:
            existing = connection.execute(
                text(
                    "SELECT command_id FROM diagnostic_scenario_lab_commands "
                    "WHERE idempotency_identity = :identity"
                ),
                {"identity": record.idempotency_identity},
            ).scalar_one_or_none()
            if existing is None:
                connection.execute(
                    text(
                        "INSERT INTO diagnostic_scenario_lab_commands ("
                        "command_id, idempotency_identity, "
                        "canonical_content_identity, operation, disposition, "
                        "message, expected_source_revision, "
                        "expected_source_generation, result_kind, result_identity, "
                        "result_json, created_at_utc, completed_at_utc) VALUES ("
                        ":command_id, :idempotency_identity, :content_identity, "
                        ":operation, :disposition, :message, :source_revision, "
                        ":source_generation, NULL, NULL, NULL, :created_at, NULL)"
                    ),
                    {
                        "command_id": record.command_id,
                        "idempotency_identity": record.idempotency_identity,
                        "content_identity": record.canonical_content_identity,
                        "operation": record.operation,
                        "disposition": record.disposition,
                        "message": record.message,
                        "source_revision": record.expected_source_revision,
                        "source_generation": record.expected_source_generation,
                        "created_at": record.created_at.isoformat(),
                    },
                )
                return record
        loaded = self.get_command_by_idempotency(record.idempotency_identity)
        if loaded is None:
            raise ValueError("Scenario Lab command claim disappeared")
        return loaded

    def complete_command(
        self,
        command_id: str,
        *,
        result_kind: str,
        result_identity: str,
        completed_at: datetime,
    ) -> ScenarioLabAuthoringCommandRecord:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE diagnostic_scenario_lab_commands SET "
                    "disposition = 'accepted', "
                    "message = 'Scenario Lab command completed.', "
                    "result_kind = :result_kind, "
                    "result_identity = :result_identity, "
                    "completed_at_utc = :completed_at "
                    "WHERE command_id = :command_id"
                ),
                {
                    "result_kind": result_kind,
                    "result_identity": result_identity,
                    "completed_at": completed_at.isoformat(),
                    "command_id": command_id,
                },
            )
        loaded = self.get_command(command_id)
        if loaded is None:
            raise ValueError("Scenario Lab command completion disappeared")
        return loaded

    def reject_command(
        self,
        command_id: str,
        *,
        message: str,
        result_kind: str,
        result_identity: str,
        completed_at: datetime,
    ) -> ScenarioLabAuthoringCommandRecord:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE diagnostic_scenario_lab_commands SET "
                    "disposition = 'rejected', message = :message, "
                    "result_kind = :result_kind, "
                    "result_identity = :result_identity, "
                    "completed_at_utc = :completed_at "
                    "WHERE command_id = :command_id"
                ),
                {
                    "message": message,
                    "result_kind": result_kind,
                    "result_identity": result_identity,
                    "completed_at": completed_at.isoformat(),
                    "command_id": command_id,
                },
            )
        loaded = self.get_command(command_id)
        if loaded is None:
            raise ValueError("Scenario Lab command rejection disappeared")
        return loaded

    def get_command(
        self, command_id: str
    ) -> ScenarioLabAuthoringCommandRecord | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT command_id, idempotency_identity, "
                    "canonical_content_identity, operation, disposition, message, "
                    "expected_source_revision, expected_source_generation, "
                    "result_kind, result_identity, created_at_utc, completed_at_utc "
                    "FROM diagnostic_scenario_lab_commands "
                    "WHERE command_id = :command_id"
                ),
                {"command_id": command_id},
            ).mappings().one_or_none()
        if row is None:
            return None
        return _command_from_row(row)

    def get_command_by_idempotency(
        self, identity: str
    ) -> ScenarioLabAuthoringCommandRecord | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT command_id, idempotency_identity, "
                    "canonical_content_identity, operation, disposition, message, "
                    "expected_source_revision, expected_source_generation, "
                    "result_kind, result_identity, created_at_utc, completed_at_utc "
                    "FROM diagnostic_scenario_lab_commands "
                    "WHERE idempotency_identity = :identity"
                ),
                {"identity": identity},
            ).mappings().one_or_none()
        return None if row is None else _command_from_row(row)

    def add_draft_revision(
        self, record: ScenarioRecipeDraftRevisionRecord
    ) -> ScenarioRecipeDraftRevisionRecord:
        values = {
            "draft_id": record.draft.draft_id,
            "recipe_id": record.draft.recipe_id,
            "revision": record.revision,
            "predecessor_draft_id": record.predecessor_draft_id,
            "based_on_version_id": record.draft.based_on_version_id,
            "authoring_mode": record.authoring_mode,
            "assistant_attempt_id": record.assistant_attempt_id,
            "accepted_command_id": record.accepted_command_id,
            "created_at": record.draft.created_at.isoformat(),
        }
        with self._engine.begin() as connection:
            existing = connection.execute(
                text(
                    "SELECT draft_id FROM diagnostic_recipe_draft_revisions "
                    "WHERE draft_id = :draft_id"
                ),
                values,
            ).scalar_one_or_none()
            if existing is None:
                connection.execute(
                    text(
                        "INSERT INTO diagnostic_recipe_draft_revisions ("
                        "draft_id, recipe_id, revision, predecessor_draft_id, "
                        "based_on_version_id, authoring_mode, assistant_attempt_id, "
                        "accepted_command_id, created_at_utc) VALUES ("
                        ":draft_id, :recipe_id, :revision, :predecessor_draft_id, "
                        ":based_on_version_id, :authoring_mode, "
                        ":assistant_attempt_id, :accepted_command_id, :created_at)"
                    ),
                    values,
                )
        loaded = self.get_draft_revision(record.draft.draft_id)
        if loaded != record:
            raise ValueError("immutable Scenario Recipe Draft revision collision")
        return record

    def get_draft_revision(
        self, draft_id: str
    ) -> ScenarioRecipeDraftRevisionRecord | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT draft_id, revision, predecessor_draft_id, "
                    "authoring_mode, assistant_attempt_id, accepted_command_id "
                    "FROM diagnostic_recipe_draft_revisions "
                    "WHERE draft_id = :draft_id"
                ),
                {"draft_id": draft_id},
            ).mappings().one_or_none()
        if row is None:
            return None
        draft = self._recipe_workbench.get_draft(str(row["draft_id"]))
        mode = str(row["authoring_mode"])
        if mode == "legacy":
            mode = "manual"
        if mode not in {"manual", "ai_assisted"}:
            raise ValueError("Stored Scenario Recipe authoring mode is invalid")
        return ScenarioRecipeDraftRevisionRecord(
            draft=draft,
            revision=int(row["revision"]),
            predecessor_draft_id=(
                str(row["predecessor_draft_id"])
                if row["predecessor_draft_id"] is not None
                else None
            ),
            authoring_mode=cast(ScenarioLabAuthoringMode, mode),
            assistant_attempt_id=(
                str(row["assistant_attempt_id"])
                if row["assistant_attempt_id"] is not None
                else None
            ),
            accepted_command_id=(
                str(row["accepted_command_id"])
                if row["accepted_command_id"] is not None
                else "legacy"
            ),
        )

    def get_draft_by_accepted_command(
        self, command_id: str
    ) -> ScenarioRecipeDraftRevisionRecord | None:
        with self._engine.connect() as connection:
            draft_id = connection.execute(
                text(
                    "SELECT draft_id FROM diagnostic_recipe_draft_revisions "
                    "WHERE accepted_command_id = :command_id"
                ),
                {"command_id": command_id},
            ).scalar_one_or_none()
        return (
            None
            if draft_id is None
            else self.get_draft_revision(str(draft_id))
        )

    def list_draft_revisions(
        self,
    ) -> tuple[ScenarioRecipeDraftRevisionRecord, ...]:
        with self._engine.connect() as connection:
            identities = tuple(
                connection.execute(
                    text(
                        "SELECT draft_id FROM diagnostic_recipe_draft_revisions "
                        "ORDER BY recipe_id, revision"
                    )
                ).scalars()
            )
        records = tuple(self.get_draft_revision(str(item)) for item in identities)
        if any(item is None for item in records):
            raise ValueError("Scenario Recipe Draft lineage disappeared during read")
        return cast(tuple[ScenarioRecipeDraftRevisionRecord, ...], records)

    def current_recipe_revision(self, recipe_id: str) -> int:
        with self._engine.connect() as connection:
            value = connection.execute(
                text(
                    "SELECT COALESCE(MAX(revision), 0) "
                    "FROM diagnostic_recipe_draft_revisions "
                    "WHERE recipe_id = :recipe_id"
                ),
                {"recipe_id": recipe_id},
            ).scalar_one()
        return int(value)

    def add_validation(
        self, record: ScenarioRecipeValidationRecord
    ) -> ScenarioRecipeValidationRecord:
        result = record.result
        findings_json = canonical_json(
            tuple(item.to_dict() for item in result.issues)
        )
        recipe_json = (
            result.validated_recipe.canonical_json()
            if result.validated_recipe is not None
            else None
        )
        dependency = record.dependencies
        history_values = {
            "validation_id": record.validation_id,
            "draft_id": result.draft_id,
            "draft_revision": record.draft_revision,
            "payload_hash": result.payload_hash,
            "is_valid": int(result.is_valid),
            "findings_json": findings_json,
            "recipe_content_hash": result.recipe_content_hash,
            "validated_recipe_json": recipe_json,
            "validated_at": result.validated_at.isoformat(),
            "accepted_command_id": record.accepted_command_id,
        }
        dependency_values = {
            "validation_id": record.validation_id,
            "historical_segment_id": dependency.historical_segment_id,
            "historical_segment_content_hash": (
                dependency.historical_segment_content_hash
            ),
            "source_snapshot_id": dependency.source_snapshot_id,
            "source_snapshot_content_hash": dependency.source_snapshot_content_hash,
            "recipe_schema_identity": dependency.recipe_schema_identity,
            "recipe_schema_hash": dependency.recipe_schema_hash,
            "transformation_catalog_version": (
                dependency.transformation_catalog_version
            ),
            "transformation_catalog_hash": dependency.transformation_catalog_hash,
            "transformation_implementations_json": canonical_json(
                dependency.transformation_implementation_identities
            ),
            "data_policy": dependency.data_policy,
            "causality_rules_json": canonical_json(
                dependency.causality_rule_identities
            ),
            "market_rule_profile_version": dependency.market_rule_profile_version,
            "market_rule_profile_hash": dependency.market_rule_profile_hash,
            "compatibility_observations_json": canonical_json(
                dependency.compatibility_observations
            ),
        }
        with self._engine.begin() as connection:
            existing = connection.execute(
                text(
                    "SELECT validation_id FROM diagnostic_recipe_validation_history "
                    "WHERE validation_id = :validation_id"
                ),
                history_values,
            ).scalar_one_or_none()
            if existing is None:
                connection.execute(
                    text(
                        "INSERT INTO diagnostic_recipe_validation_history ("
                        "validation_id, draft_id, draft_revision, payload_hash, "
                        "is_valid, findings_json, recipe_content_hash, "
                        "validated_recipe_json, validated_at_utc, "
                        "accepted_command_id) VALUES ("
                        ":validation_id, :draft_id, :draft_revision, "
                        ":payload_hash, :is_valid, :findings_json, "
                        ":recipe_content_hash, :validated_recipe_json, "
                        ":validated_at, :accepted_command_id)"
                    ),
                    history_values,
                )
                connection.execute(
                    text(
                        "INSERT INTO diagnostic_recipe_validation_dependencies ("
                        "validation_id, historical_segment_id, "
                        "historical_segment_content_hash, source_snapshot_id, "
                        "source_snapshot_content_hash, recipe_schema_identity, "
                        "recipe_schema_hash, transformation_catalog_version, "
                        "transformation_catalog_hash, "
                        "transformation_implementations_json, data_policy, "
                        "causality_rules_json, market_rule_profile_version, "
                        "market_rule_profile_hash, compatibility_observations_json) "
                        "VALUES (:validation_id, :historical_segment_id, "
                        ":historical_segment_content_hash, :source_snapshot_id, "
                        ":source_snapshot_content_hash, :recipe_schema_identity, "
                        ":recipe_schema_hash, :transformation_catalog_version, "
                        ":transformation_catalog_hash, "
                        ":transformation_implementations_json, :data_policy, "
                        ":causality_rules_json, :market_rule_profile_version, "
                        ":market_rule_profile_hash, "
                        ":compatibility_observations_json)"
                    ),
                    dependency_values,
                )
        loaded = self.get_validation(record.validation_id)
        if loaded != record:
            raise ValueError("immutable Scenario Recipe validation collision")
        return record

    def get_validation(
        self, validation_id: str
    ) -> ScenarioRecipeValidationRecord | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT h.validation_id, h.draft_id, h.draft_revision, "
                    "h.payload_hash, h.is_valid, h.findings_json, "
                    "h.recipe_content_hash, h.validated_recipe_json, "
                    "h.validated_at_utc, h.accepted_command_id, "
                    "d.historical_segment_id, "
                    "d.historical_segment_content_hash, d.source_snapshot_id, "
                    "d.source_snapshot_content_hash, d.recipe_schema_identity, "
                    "d.recipe_schema_hash, d.transformation_catalog_version, "
                    "d.transformation_catalog_hash, "
                    "d.transformation_implementations_json, d.data_policy, "
                    "d.causality_rules_json, d.market_rule_profile_version, "
                    "d.market_rule_profile_hash, d.compatibility_observations_json "
                    "FROM diagnostic_recipe_validation_history h "
                    "JOIN diagnostic_recipe_validation_dependencies d "
                    "ON d.validation_id = h.validation_id "
                    "WHERE h.validation_id = :validation_id"
                ),
                {"validation_id": validation_id},
            ).mappings().one_or_none()
        if row is None:
            return None
        raw_findings = json.loads(str(row["findings_json"]))
        if not isinstance(raw_findings, list):
            raise ValueError("Stored Recipe validation findings are invalid")
        result = RecipeValidationResult(
            draft_id=str(row["draft_id"]),
            payload_hash=str(row["payload_hash"]),
            is_valid=bool(row["is_valid"]),
            issues=tuple(
                RecipeValidationIssue(
                    path=str(item["path"]),
                    rule=str(item["rule"]),
                    message=str(item["message"]),
                    correction=str(item["correction"]),
                )
                for item in raw_findings
            ),
            recipe_content_hash=(
                str(row["recipe_content_hash"])
                if row["recipe_content_hash"] is not None
                else None
            ),
            validated_at=datetime.fromisoformat(str(row["validated_at_utc"])),
            validated_recipe=(
                ScenarioRecipeV1.parse_raw(str(row["validated_recipe_json"]))
                if row["validated_recipe_json"] is not None
                else None
            ),
        )
        return ScenarioRecipeValidationRecord(
            validation_id=str(row["validation_id"]),
            draft_revision=int(row["draft_revision"]),
            result=result,
            dependencies=_dependencies_from_row(row),
            accepted_command_id=str(row["accepted_command_id"]),
        )

    def get_validation_by_accepted_command(
        self, command_id: str
    ) -> ScenarioRecipeValidationRecord | None:
        with self._engine.connect() as connection:
            validation_id = connection.execute(
                text(
                    "SELECT validation_id "
                    "FROM diagnostic_recipe_validation_history "
                    "WHERE accepted_command_id = :command_id"
                ),
                {"command_id": command_id},
            ).scalar_one_or_none()
        return (
            None
            if validation_id is None
            else self.get_validation(str(validation_id))
        )

    def list_validations(self) -> tuple[ScenarioRecipeValidationRecord, ...]:
        with self._engine.connect() as connection:
            identities = tuple(
                connection.execute(
                    text(
                        "SELECT validation_id "
                        "FROM diagnostic_recipe_validation_history "
                        "WHERE accepted_command_id IS NOT NULL "
                        "ORDER BY validated_at_utc, validation_id"
                    )
                ).scalars()
            )
        records = tuple(self.get_validation(str(item)) for item in identities)
        if any(item is None for item in records):
            raise ValueError("Recipe validation history disappeared during read")
        return cast(tuple[ScenarioRecipeValidationRecord, ...], records)


class ScenarioLabAuthoringService:
    def __init__(
        self,
        *,
        recipe_workbench: RecipeWorkbench,
        admitted_segments: Callable[[], Iterable[HistoricalMarketSegment]],
        dependency_provider: Callable[
            [ScenarioRecipeDraft, RecipeValidationResult],
            ScenarioRecipeValidationDependencyRecord,
        ],
        repository: ScenarioLabAuthoringRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._recipe_workbench = recipe_workbench
        self._admitted_segments = admitted_segments
        self._dependency_provider = dependency_provider
        self._repository = repository or InMemoryScenarioLabAuthoringRepository()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()

    def replace_repository(self, repository: ScenarioLabAuthoringRepository) -> None:
        with self._lock:
            self._repository = repository

    def author_draft_with_ai(
        self,
        *,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        expected_source_revision: str,
        expected_source_generation: int,
        intent: str,
        author: str,
        author_with_ai: Callable[[str, str, str], AIRecipeAuthoringResult],
    ) -> ScenarioLabAuthoringResult:
        """Claim first, then bind exactly one durable audited AI attempt."""

        with self._lock:
            replay = self._replay_or_conflict(
                command_id,
                idempotency_identity,
                canonical_content_identity,
                "create_recipe_draft",
            )
            if replay is not None:
                return replay
            command = self._repository.claim_command(
                _pending_command(
                    command_id=command_id,
                    idempotency_identity=idempotency_identity,
                    canonical_content_identity=canonical_content_identity,
                    operation="create_recipe_draft",
                    expected_source_revision=expected_source_revision,
                    expected_source_generation=expected_source_generation,
                    created_at=self._now(),
                )
            )
            attempt_id = _identity(
                "ai_recipe_attempt_",
                command.command_id,
            )
            try:
                audit = self._recipe_workbench.get_ai_audit(attempt_id)
            except ValueError:
                authored = author_with_ai(intent, author, attempt_id)
            else:
                if (
                    audit.attempt.intent != intent
                    or audit.attempt.author != author
                ):
                    raise ValueError(
                        "Audited AI attempt does not match the claimed command"
                    )
                draft = (
                    None
                    if audit.attempt.draft_id is None
                    else self._recipe_workbench.get_draft(
                        audit.attempt.draft_id
                    )
                )
                authored = AIRecipeAuthoringResult(
                    attempt=audit.attempt,
                    draft=draft,
                    validation=audit.validation,
                )
            if authored.draft is None:
                message = (
                    "The audited AI Recipe Assistant produced no typed Draft "
                    f"({authored.status})."
                )
                rejected = self._repository.reject_command(
                    command.command_id,
                    message=message,
                    result_kind="ai_authoring_attempt",
                    result_identity=authored.attempt.attempt_id,
                    completed_at=self._now(),
                )
                return ScenarioLabAuthoringResult(
                    disposition="rejected",
                    message=rejected.message,
                    command=rejected,
                )
            record = self._repository.add_draft_revision(
                ScenarioRecipeDraftRevisionRecord(
                    draft=authored.draft,
                    revision=1,
                    predecessor_draft_id=None,
                    authoring_mode="ai_assisted",
                    assistant_attempt_id=authored.attempt.attempt_id,
                    accepted_command_id=command.command_id,
                )
            )
            completed = self._repository.complete_command(
                command.command_id,
                result_kind="recipe_draft",
                result_identity=authored.draft.draft_id,
                completed_at=self._now(),
            )
            return ScenarioLabAuthoringResult(
                disposition="accepted",
                message=completed.message,
                command=completed,
                draft=record,
                authoritative_draft_revision=1,
            )

    def create_draft(
        self,
        *,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        expected_source_revision: str,
        expected_source_generation: int,
        payload: Mapping[str, object],
        author: str,
        authoring_mode: ScenarioLabAuthoringMode,
        assistant_attempt_id: str | None,
        existing_draft: ScenarioRecipeDraft | None = None,
    ) -> ScenarioLabAuthoringResult:
        with self._lock:
            replay = self._replay_or_conflict(
                command_id,
                idempotency_identity,
                canonical_content_identity,
                "create_recipe_draft",
            )
            if replay is not None:
                return replay
            now = self._now()
            command = self._repository.claim_command(
                _pending_command(
                    command_id=command_id,
                    idempotency_identity=idempotency_identity,
                    canonical_content_identity=canonical_content_identity,
                    operation="create_recipe_draft",
                    expected_source_revision=expected_source_revision,
                    expected_source_generation=expected_source_generation,
                    created_at=now,
                )
            )
            if existing_draft is None:
                draft_id = _identity("recipe_draft_", command.command_id)
                recipe_id = _identity(
                    "recipe_", "recipe|" + command.command_id
                )
                draft = self._recipe_workbench.create_draft(
                    payload,
                    author=author,
                    recipe_id=recipe_id,
                    draft_id=draft_id,
                    created_at=command.created_at,
                )
            else:
                if existing_draft.author != author:
                    raise ValueError(
                        "Audited Scenario Recipe Draft author mismatch"
                    )
                expected_payload_hash = hashlib.sha256(
                    canonical_json(payload).encode("utf-8")
                ).hexdigest()
                if existing_draft.payload_hash != expected_payload_hash:
                    raise ValueError(
                        "Audited Scenario Recipe Draft payload mismatch"
                    )
                draft = existing_draft
            record = self._repository.add_draft_revision(
                ScenarioRecipeDraftRevisionRecord(
                    draft=draft,
                    revision=1,
                    predecessor_draft_id=None,
                    authoring_mode=authoring_mode,
                    assistant_attempt_id=assistant_attempt_id,
                    accepted_command_id=command.command_id,
                )
            )
            completed = self._repository.complete_command(
                command.command_id,
                result_kind="recipe_draft",
                result_identity=draft.draft_id,
                completed_at=self._now(),
            )
            return ScenarioLabAuthoringResult(
                disposition="accepted",
                message=completed.message,
                command=completed,
                draft=record,
                authoritative_draft_revision=1,
            )

    def revise_draft(
        self,
        *,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        expected_source_revision: str,
        expected_source_generation: int,
        predecessor_draft_id: str,
        expected_draft_revision: int,
        payload: Mapping[str, object],
        author: str,
        based_on_version_id: str | None,
    ) -> ScenarioLabAuthoringResult:
        with self._lock:
            replay = self._replay_or_conflict(
                command_id,
                idempotency_identity,
                canonical_content_identity,
                "revise_recipe_draft",
            )
            if replay is not None:
                return replay
            predecessor = self._repository.get_draft_revision(
                predecessor_draft_id
            )
            if predecessor is None:
                return ScenarioLabAuthoringResult(
                    disposition="rejected",
                    message="The predecessor Scenario Recipe Draft is unavailable.",
                )
            current_revision = self._repository.current_recipe_revision(
                predecessor.draft.recipe_id
            )
            if (
                predecessor.revision != current_revision
                or expected_draft_revision != current_revision
            ):
                return ScenarioLabAuthoringResult(
                    disposition="conflict",
                    message="The expected Scenario Recipe Draft revision is stale.",
                    authoritative_draft_revision=current_revision,
                )
            if based_on_version_id is not None:
                based_on_version = next(
                    (
                        item
                        for item in self._recipe_workbench.list_approved_versions()
                        if item.version_id == based_on_version_id
                    ),
                    None,
                )
                if (
                    based_on_version is None
                    or based_on_version.recipe_id != predecessor.draft.recipe_id
                    or (
                        based_on_version.validation_result.draft_id
                        != predecessor.draft.draft_id
                        and predecessor.draft.based_on_version_id
                        != based_on_version.version_id
                    )
                ):
                    return ScenarioLabAuthoringResult(
                        disposition="rejected",
                        message=(
                            "The based-on Approved Recipe Version must exist and "
                            "belong to the exact predecessor Recipe Draft."
                        ),
                        authoritative_draft_revision=current_revision,
                    )
            now = self._now()
            command = self._repository.claim_command(
                _pending_command(
                    command_id=command_id,
                    idempotency_identity=idempotency_identity,
                    canonical_content_identity=canonical_content_identity,
                    operation="revise_recipe_draft",
                    expected_source_revision=expected_source_revision,
                    expected_source_generation=expected_source_generation,
                    created_at=now,
                )
            )
            draft_id = _identity("recipe_draft_", command.command_id)
            draft = self._recipe_workbench.create_draft(
                payload,
                author=author,
                recipe_id=predecessor.draft.recipe_id,
                based_on_version_id=(
                    based_on_version_id
                    or predecessor.draft.based_on_version_id
                ),
                draft_id=draft_id,
                created_at=command.created_at,
            )
            record = self._repository.add_draft_revision(
                ScenarioRecipeDraftRevisionRecord(
                    draft=draft,
                    revision=current_revision + 1,
                    predecessor_draft_id=predecessor.draft.draft_id,
                    authoring_mode="manual",
                    assistant_attempt_id=None,
                    accepted_command_id=command.command_id,
                )
            )
            completed = self._repository.complete_command(
                command.command_id,
                result_kind="recipe_draft",
                result_identity=draft.draft_id,
                completed_at=self._now(),
            )
            return ScenarioLabAuthoringResult(
                disposition="accepted",
                message=completed.message,
                command=completed,
                draft=record,
                authoritative_draft_revision=record.revision,
            )

    def validate_draft(
        self,
        *,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        expected_source_revision: str,
        expected_source_generation: int,
        draft_id: str,
        expected_draft_revision: int,
        expected_payload_hash: str,
    ) -> ScenarioLabAuthoringResult:
        with self._lock:
            replay = self._replay_or_conflict(
                command_id,
                idempotency_identity,
                canonical_content_identity,
                "validate_recipe_draft",
            )
            if replay is not None:
                return replay
            draft = self._repository.get_draft_revision(draft_id)
            if draft is None:
                return ScenarioLabAuthoringResult(
                    disposition="rejected",
                    message="The Scenario Recipe Draft is unavailable.",
                )
            current_revision = self._repository.current_recipe_revision(
                draft.draft.recipe_id
            )
            if (
                draft.revision != expected_draft_revision
                or current_revision != expected_draft_revision
                or draft.draft.payload_hash != expected_payload_hash
            ):
                return ScenarioLabAuthoringResult(
                    disposition="conflict",
                    message="The expected Scenario Recipe Draft facts are stale.",
                    authoritative_draft_revision=current_revision,
                )
            admitted_segments = tuple(self._admitted_segments())
            requested_segment_id = str(
                draft.draft.payload.get("historical_segment_id") or ""
            )
            if requested_segment_id not in {
                item.segment_id for item in admitted_segments
            }:
                return ScenarioLabAuthoringResult(
                    disposition="rejected",
                    message=(
                        "The exact Historical Market Segment dependency is not "
                        "admitted and cannot be bound for validation."
                    ),
                    authoritative_draft_revision=current_revision,
                )
            now = self._now()
            command = self._repository.claim_command(
                _pending_command(
                    command_id=command_id,
                    idempotency_identity=idempotency_identity,
                    canonical_content_identity=canonical_content_identity,
                    operation="validate_recipe_draft",
                    expected_source_revision=expected_source_revision,
                    expected_source_generation=expected_source_generation,
                    created_at=now,
                )
            )
            result = self._recipe_workbench.validate_draft(
                draft_id,
                admitted_segments=admitted_segments,
                validated_at=command.created_at,
            )
            validation_id = _identity(
                "recipe_validation_", command.command_id
            )
            record = self._repository.add_validation(
                ScenarioRecipeValidationRecord(
                    validation_id=validation_id,
                    draft_revision=draft.revision,
                    result=result,
                    dependencies=self._dependency_provider(draft.draft, result),
                    accepted_command_id=command.command_id,
                )
            )
            completed = self._repository.complete_command(
                command.command_id,
                result_kind="recipe_validation",
                result_identity=validation_id,
                completed_at=self._now(),
            )
            return ScenarioLabAuthoringResult(
                disposition="accepted",
                message=completed.message,
                command=completed,
                validation=record,
                authoritative_draft_revision=draft.revision,
            )

    def approve_recipe(
        self,
        *,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        expected_source_revision: str,
        expected_source_generation: int,
        draft_id: str,
        expected_draft_revision: int,
        expected_payload_hash: str,
        validation_id: str,
        actor: str,
    ) -> ScenarioLabAuthoringResult:
        """Approve only one exact current validation and preserve replay truth."""

        with self._lock:
            replay = self._replay_or_conflict(
                command_id,
                idempotency_identity,
                canonical_content_identity,
                "approve_recipe",
            )
            if replay is not None:
                return replay
            draft = self._repository.get_draft_revision(draft_id)
            if draft is None:
                return ScenarioLabAuthoringResult(
                    disposition="rejected",
                    message="The Scenario Recipe Draft is unavailable.",
                )
            current_revision = self._repository.current_recipe_revision(
                draft.draft.recipe_id
            )
            if (
                draft.revision != expected_draft_revision
                or current_revision != expected_draft_revision
                or draft.draft.payload_hash != expected_payload_hash
            ):
                return ScenarioLabAuthoringResult(
                    disposition="conflict",
                    message="The expected Scenario Recipe Draft facts are stale.",
                    authoritative_draft_revision=current_revision,
                )
            validation = self._repository.get_validation(validation_id)
            if (
                validation is None
                or validation.result.draft_id != draft_id
                or validation.draft_revision != expected_draft_revision
                or validation.result.payload_hash != expected_payload_hash
                or not validation.result.is_valid
                or validation.result.validated_recipe is None
                or validation.result.recipe_content_hash is None
            ):
                return ScenarioLabAuthoringResult(
                    disposition="rejected",
                    message=(
                        "Approval requires the exact successful validation for "
                        "the current immutable Draft revision and payload hash."
                    ),
                    authoritative_draft_revision=current_revision,
                )
            try:
                current_dependencies = self._dependency_provider(
                    draft.draft,
                    validation.result,
                )
            except ValueError:
                return ScenarioLabAuthoringResult(
                    disposition="rejected",
                    message=(
                        "The exact validation dependencies are unavailable; "
                        "historical validation remains readable but cannot approve."
                    ),
                    authoritative_draft_revision=current_revision,
                )
            if current_dependencies != validation.dependencies:
                return ScenarioLabAuthoringResult(
                    disposition="rejected",
                    message=(
                        "The exact validation dependencies changed; reread and "
                        "revalidate before approval."
                    ),
                    authoritative_draft_revision=current_revision,
                )
            command = self._repository.claim_command(
                _pending_command(
                    command_id=command_id,
                    idempotency_identity=idempotency_identity,
                    canonical_content_identity=canonical_content_identity,
                    operation="approve_recipe",
                    expected_source_revision=expected_source_revision,
                    expected_source_generation=expected_source_generation,
                    created_at=self._now(),
                )
            )
            existing_versions = tuple(
                item
                for item in self._recipe_workbench.list_approved_versions()
                if item.validation_result.draft_id == draft_id
            )
            if len(existing_versions) > 1:
                raise RuntimeError(
                    "Scenario Recipe Draft has multiple immutable approvals"
                )
            if existing_versions:
                version = existing_versions[0]
                if (
                    version.approval_actor != actor
                    or version.validation_identity != validation_id
                    or version.approval_command_identity != command.command_id
                ):
                    message = (
                        "The Scenario Recipe Draft already belongs to a "
                        "different immutable approval."
                    )
                    rejected = self._repository.reject_command(
                        command.command_id,
                        message=message,
                        result_kind="approval_rejection",
                        result_identity=draft_id,
                        completed_at=self._now(),
                    )
                    return ScenarioLabAuthoringResult(
                        disposition="rejected",
                        message=rejected.message,
                        command=rejected,
                        authoritative_draft_revision=current_revision,
                    )
            else:
                version = self._recipe_workbench.approve_draft(
                    draft_id,
                    actor=actor,
                    validation_identity=validation_id,
                    command_identity=command.command_id,
                )
            approval = self._approval_record(version)
            if approval is None:
                raise RuntimeError(
                    "Typed Scenario Recipe approval evidence is unavailable"
                )
            completed = self._repository.complete_command(
                command.command_id,
                result_kind="approved_recipe_version",
                result_identity=version.version_id,
                completed_at=self._now(),
            )
            return ScenarioLabAuthoringResult(
                disposition="accepted",
                message=completed.message,
                command=completed,
                approval=approval,
                authoritative_draft_revision=draft.revision,
            )

    def list_drafts(self) -> tuple[ScenarioRecipeDraftRevisionRecord, ...]:
        with self._lock:
            return self._repository.list_draft_revisions()

    def list_validations(self) -> tuple[ScenarioRecipeValidationRecord, ...]:
        with self._lock:
            return self._repository.list_validations()

    def list_approvals(self) -> tuple[ScenarioRecipeApprovalRecord, ...]:
        with self._lock:
            return tuple(
                self._approval_record(version)
                for version in self._recipe_workbench.list_approved_versions()
            )

    def replay(
        self,
        *,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        operation: str,
    ) -> ScenarioLabAuthoringResult | None:
        """Return an accepted replay or content conflict before freshness checks."""

        with self._lock:
            return self._replay_or_conflict(
                command_id,
                idempotency_identity,
                canonical_content_identity,
                operation,
            )

    def _replay_or_conflict(
        self,
        command_id: str,
        idempotency_identity: str,
        canonical_content_identity: str,
        operation: str,
    ) -> ScenarioLabAuthoringResult | None:
        existing = self._repository.get_command_by_idempotency(
            idempotency_identity
        )
        if existing is None:
            command_collision = self._repository.get_command(command_id)
            if command_collision is None:
                return None
            return ScenarioLabAuthoringResult(
                disposition="conflict",
                message=(
                    "The command identity is already bound to a different "
                    "idempotency identity."
                ),
            )
        if (
            existing.canonical_content_identity != canonical_content_identity
            or existing.operation != operation
        ):
            return ScenarioLabAuthoringResult(
                disposition="conflict",
                message=(
                    "The idempotency identity is already bound to different "
                    "canonical content."
                ),
            )
        if existing.result_kind is None:
            if operation in {"create_recipe_draft", "revise_recipe_draft"}:
                recovered_draft = (
                    self._repository.get_draft_by_accepted_command(
                        existing.command_id
                    )
                )
                if recovered_draft is not None:
                    completed = self._repository.complete_command(
                        existing.command_id,
                        result_kind="recipe_draft",
                        result_identity=recovered_draft.draft.draft_id,
                        completed_at=self._now(),
                    )
                    return ScenarioLabAuthoringResult(
                        disposition="accepted",
                        message=completed.message,
                        command=completed,
                        draft=recovered_draft,
                        authoritative_draft_revision=recovered_draft.revision,
                    )
            elif operation == "validate_recipe_draft":
                recovered_validation = (
                    self._repository.get_validation_by_accepted_command(
                        existing.command_id
                    )
                )
                if recovered_validation is not None:
                    completed = self._repository.complete_command(
                        existing.command_id,
                        result_kind="recipe_validation",
                        result_identity=recovered_validation.validation_id,
                        completed_at=self._now(),
                    )
                    return ScenarioLabAuthoringResult(
                        disposition="accepted",
                        message=completed.message,
                        command=completed,
                        validation=recovered_validation,
                        authoritative_draft_revision=(
                            recovered_validation.draft_revision
                        ),
                    )
            elif operation == "approve_recipe":
                recovered_versions = tuple(
                    item
                    for item in self._recipe_workbench.list_approved_versions()
                    if item.approval_command_identity == existing.command_id
                )
                if len(recovered_versions) > 1:
                    raise RuntimeError(
                        "Scenario Lab approval command has multiple results"
                    )
                if recovered_versions:
                    recovered_approval = self._approval_record(
                        recovered_versions[0]
                    )
                    if recovered_approval.validation is None:
                        raise RuntimeError(
                            "Recovered Scenario Recipe approval is incomplete"
                        )
                    completed = self._repository.complete_command(
                        existing.command_id,
                        result_kind="approved_recipe_version",
                        result_identity=recovered_versions[0].version_id,
                        completed_at=self._now(),
                    )
                    return ScenarioLabAuthoringResult(
                        disposition="accepted",
                        message=completed.message,
                        command=completed,
                        approval=recovered_approval,
                        authoritative_draft_revision=(
                            recovered_approval.validation.draft_revision
                        ),
                    )
            return None
        if existing.result_kind == "recipe_draft":
            draft = self._repository.get_draft_revision(
                str(existing.result_identity)
            )
            return ScenarioLabAuthoringResult(
                disposition="accepted",
                message=existing.message,
                command=existing,
                draft=draft,
                authoritative_draft_revision=(
                    None if draft is None else draft.revision
                ),
            )
        if existing.result_kind == "recipe_validation":
            validation = self._repository.get_validation(
                str(existing.result_identity)
            )
            return ScenarioLabAuthoringResult(
                disposition="accepted",
                message=existing.message,
                command=existing,
                validation=validation,
                authoritative_draft_revision=(
                    None
                    if validation is None
                    else validation.draft_revision
                ),
            )
        if existing.result_kind == "approved_recipe_version":
            version = self._recipe_workbench.get_version(
                str(existing.result_identity)
            )
            approval = self._approval_record(version)
            if approval.validation is None:
                raise RuntimeError(
                    "Stored Scenario Recipe approval result is incomplete"
                )
            return ScenarioLabAuthoringResult(
                disposition="accepted",
                message=existing.message,
                command=existing,
                approval=approval,
                authoritative_draft_revision=approval.validation.draft_revision,
            )
        if existing.result_kind == "approval_rejection":
            if existing.disposition != "rejected":
                raise RuntimeError(
                    "Stored Scenario Recipe approval rejection is not terminal"
                )
            rejected_draft = self._repository.get_draft_revision(
                str(existing.result_identity)
            )
            return ScenarioLabAuthoringResult(
                disposition="rejected",
                message=existing.message,
                command=existing,
                authoritative_draft_revision=(
                    None if rejected_draft is None else rejected_draft.revision
                ),
            )
        if existing.result_kind == "ai_authoring_attempt":
            if existing.disposition != "rejected":
                raise RuntimeError(
                    "Stored AI authoring terminal result is not rejected"
                )
            return ScenarioLabAuthoringResult(
                disposition="rejected",
                message=existing.message,
                command=existing,
            )
        raise RuntimeError("Stored Scenario Lab command result kind is invalid")

    def _approval_record(
        self,
        version: ApprovedScenarioRecipeVersion,
    ) -> ScenarioRecipeApprovalRecord:
        approval_id = version.approval_id
        validation_identity = version.validation_identity
        command_identity = version.approval_command_identity
        exact_bindings = (
            approval_id is not None,
            validation_identity is not None,
            command_identity is not None,
        )
        if any(exact_bindings) and not all(exact_bindings):
            raise ValueError(
                "Approved Scenario Recipe exact binding is incomplete"
            )
        if not any(exact_bindings):
            legacy_draft = self._recipe_workbench.get_draft(
                version.validation_result.draft_id
            )
            return ScenarioRecipeApprovalRecord(
                approval_id=legacy_scenario_recipe_approval_identity(
                    version_id=version.version_id,
                    actor=version.approval_actor,
                    approved_at=version.approved_at,
                ),
                version=version,
                draft=ScenarioRecipeDraftRevisionRecord(
                    draft=legacy_draft,
                    revision=version.version_number,
                    predecessor_draft_id=None,
                    authoring_mode="manual",
                    assistant_attempt_id=None,
                    accepted_command_id=(
                        "legacy-unbound-approval:" + version.version_id
                    ),
                ),
                validation=None,
                authority_state="unavailable",
                authority_message=(
                    "Historical approval predates exact Scenario Lab command and "
                    "dependency bindings; immutable truth remains readable but "
                    "cannot gain materialization authority."
                ),
                can_materialize=False,
            )
        if approval_id is None or validation_identity is None:
            raise RuntimeError("Exact Scenario Recipe approval binding disappeared")
        validation = self._repository.get_validation(validation_identity)
        if validation is None:
            raise ValueError(
                "Approved Scenario Recipe exact validation history is unavailable"
            )
        if validation.result != version.validation_result:
            raise ValueError(
                "Approved Scenario Recipe validation snapshot mismatch"
            )
        draft = self._repository.get_draft_revision(
            version.validation_result.draft_id
        )
        if draft is None:
            raise ValueError(
                "Approved Scenario Recipe Draft lineage is unavailable"
            )
        try:
            current_dependencies = self._dependency_provider(
                draft.draft,
                validation.result,
            )
        except ValueError:
            authority_state: ScenarioRecipeApprovalAuthorityState = "unavailable"
            authority_message = (
                "One or more exact approval dependencies are unavailable."
            )
        else:
            incompatible = any(
                state == "incompatible"
                for _subject, state, _explanation in (
                    current_dependencies.compatibility_observations
                )
            )
            if incompatible:
                authority_state = "incompatible"
                authority_message = (
                    "Current dependency compatibility is incompatible with approval."
                )
            elif current_dependencies != validation.dependencies:
                authority_state = "outdated"
                authority_message = (
                    "Approval dependencies changed; historical truth is retained."
                )
            else:
                authority_state = "current"
                authority_message = (
                    "Approval is bound to the current exact dependency identities."
                )
        return ScenarioRecipeApprovalRecord(
            approval_id=approval_id,
            version=version,
            draft=draft,
            validation=validation,
            authority_state=authority_state,
            authority_message=authority_message,
            can_materialize=authority_state == "current",
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Scenario Lab command clock must be timezone-aware")
        return value


def _pending_command(
    *,
    command_id: str,
    idempotency_identity: str,
    canonical_content_identity: str,
    operation: str,
    expected_source_revision: str,
    expected_source_generation: int,
    created_at: datetime,
) -> ScenarioLabAuthoringCommandRecord:
    return ScenarioLabAuthoringCommandRecord(
        command_id=command_id,
        idempotency_identity=idempotency_identity,
        canonical_content_identity=canonical_content_identity,
        operation=operation,
        disposition="pending",
        message="Scenario Lab command accepted for durable execution.",
        expected_source_revision=expected_source_revision,
        expected_source_generation=expected_source_generation,
        result_kind=None,
        result_identity=None,
        created_at=created_at,
        completed_at=None,
    )


def _command_from_row(
    row: Mapping[str, object],
) -> ScenarioLabAuthoringCommandRecord:
    return ScenarioLabAuthoringCommandRecord(
        command_id=str(row["command_id"]),
        idempotency_identity=str(row["idempotency_identity"]),
        canonical_content_identity=str(row["canonical_content_identity"]),
        operation=str(row["operation"]),
        disposition=str(row["disposition"]),
        message=str(row["message"]),
        expected_source_revision=str(row["expected_source_revision"]),
        expected_source_generation=int(
            str(row["expected_source_generation"])
        ),
        result_kind=(
            str(row["result_kind"])
            if row["result_kind"] is not None
            else None
        ),
        result_identity=(
            str(row["result_identity"])
            if row["result_identity"] is not None
            else None
        ),
        created_at=datetime.fromisoformat(str(row["created_at_utc"])),
        completed_at=(
            datetime.fromisoformat(str(row["completed_at_utc"]))
            if row["completed_at_utc"] is not None
            else None
        ),
    )


def _dependencies_from_row(
    row: Mapping[str, object],
) -> ScenarioRecipeValidationDependencyRecord:
    implementations = json.loads(
        str(row["transformation_implementations_json"])
    )
    causality = json.loads(str(row["causality_rules_json"]))
    observations = json.loads(str(row["compatibility_observations_json"]))
    if (
        not isinstance(implementations, list)
        or not isinstance(causality, list)
        or not isinstance(observations, list)
    ):
        raise ValueError("Stored Recipe validation dependency payload is invalid")
    return ScenarioRecipeValidationDependencyRecord(
        historical_segment_id=str(row["historical_segment_id"]),
        historical_segment_content_hash=str(
            row["historical_segment_content_hash"]
        ),
        source_snapshot_id=str(row["source_snapshot_id"]),
        source_snapshot_content_hash=str(row["source_snapshot_content_hash"]),
        recipe_schema_identity=str(row["recipe_schema_identity"]),
        recipe_schema_hash=str(row["recipe_schema_hash"]),
        transformation_catalog_version=str(
            row["transformation_catalog_version"]
        ),
        transformation_catalog_hash=str(row["transformation_catalog_hash"]),
        transformation_implementation_identities=tuple(
            str(item) for item in implementations
        ),
        data_policy=str(row["data_policy"]),
        causality_rule_identities=tuple(str(item) for item in causality),
        market_rule_profile_version=str(row["market_rule_profile_version"]),
        market_rule_profile_hash=str(row["market_rule_profile_hash"]),
        compatibility_observations=tuple(
            (str(item[0]), str(item[1]), str(item[2]))
            for item in observations
        ),
    )


__all__ = [
    "InMemoryScenarioLabAuthoringRepository",
    "ScenarioLabAuthoringResult",
    "ScenarioLabAuthoringService",
    "ScenarioRecipeApprovalAuthorityState",
    "ScenarioRecipeApprovalRecord",
    "ScenarioRecipeDraftRevisionRecord",
    "ScenarioRecipeValidationDependencyRecord",
    "ScenarioRecipeValidationRecord",
    "SqlScenarioLabAuthoringRepository",
    "canonical_json",
]
