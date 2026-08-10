"""Validation contract for the Wave 4 candidate/Widgets rollback drill."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Final, cast

from strategy_diagnostics.persistence import DIAGNOSTIC_SCHEMA_REVISION


ROLLBACK_DRILL_SCHEMA_VERSION: Final = "wave4.rollback-drill-evidence.v1"
ROLLBACK_DRILL_JSON_SCHEMA_PATH: Final = Path(__file__).with_name(
    "wave4_rollback_drill_evidence.schema.json"
)
ROLLBACK_STAGE_SEQUENCE: Final = (
    "wave4-candidate",
    "retained-widgets",
    "wave4-candidate-recovered",
)
READABLE_ARTIFACT_KINDS: Final = (
    "Strategy",
    "Recipe",
    "Task",
    "Campaign",
    "Run",
    "Evidence",
    "Finding",
    "Manifest",
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}\Z")
_SOURCE_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TOP_LEVEL_FIELDS: Final = frozenset(
    {
        "schema_version",
        "drill_id",
        "started_at",
        "completed_at",
        "execution_mode",
        "installed_binary_gate_verified",
        "candidate_artifact",
        "retained_widgets_artifact",
        "supported_data_copy_sha256",
        "stage_sequence",
        "stages",
        "persistence_migration",
        "bookmark_migration",
        "task_handle_continuity",
        "duplicate_identity_count",
    }
)
_ARTIFACT_FIELDS: Final = frozenset(
    {
        "kind",
        "source_commit",
        "dependency_lock_sha256",
        "artifact_sha256",
        "package_id",
        "build_id",
    }
)
_STAGE_FIELDS: Final = frozenset(
    {
        "stage",
        "started_at",
        "completed_at",
        "verification_surface",
        "clean_exit",
        "readable_artifacts",
        "durable_identities",
        "task_handle_identities",
        "order_state_sha256",
    }
)
_PERSISTENCE_FIELDS: Final = frozenset(
    {
        "fresh_initialization_revision",
        "copied_wave3_source_revision",
        "upgraded_revision",
        "deterministic",
        "idempotent",
        "additive",
        "retained_widgets_compatible",
        "order_mutation_count",
    }
)
_BOOKMARK_FIELDS: Final = frozenset(
    {
        "source_schema_version",
        "target_schema_version",
        "deterministic",
        "idempotent",
        "exact_durable_identities_preserved",
    }
)


class RollbackEvidenceValidationError(ValueError):
    """Raised when a rollback drill is incomplete, unsafe, or irreproducible."""


def _mapping(value: object, *, location: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise RollbackEvidenceValidationError(f"{location} must be an object")
    return value


def _list(value: object, *, location: str) -> list[object]:
    if not isinstance(value, list):
        raise RollbackEvidenceValidationError(f"{location} must be an array")
    return value


def _exact_fields(
    value: Mapping[str, object],
    expected: frozenset[str],
    *,
    location: str,
) -> None:
    missing = sorted(expected.difference(value))
    extra = sorted(set(value).difference(expected))
    if missing:
        raise RollbackEvidenceValidationError(
            f"{location} is missing required field(s): {', '.join(missing)}"
        )
    if extra:
        raise RollbackEvidenceValidationError(
            f"{location} has unexpected field(s): {', '.join(extra)}"
        )


def _string(
    value: object,
    *,
    location: str,
    pattern: re.Pattern[str] = _SAFE_ID,
) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        label = "SHA-256" if pattern is _SHA256 else "identity"
        raise RollbackEvidenceValidationError(f"{location} has an invalid {label}")
    return value


def _boolean(value: object, *, location: str) -> bool:
    if not isinstance(value, bool):
        raise RollbackEvidenceValidationError(f"{location} must be a boolean")
    return value


def _count(value: object, *, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RollbackEvidenceValidationError(
            f"{location} must be a non-negative integer"
        )
    return value


def _timestamp(value: object, *, location: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise RollbackEvidenceValidationError(f"{location} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise RollbackEvidenceValidationError(
            f"{location} must be a UTC timestamp"
        ) from exc
    if parsed.tzinfo != timezone.utc:
        raise RollbackEvidenceValidationError(
            f"{location} must be a UTC timestamp"
        )
    return parsed


def _artifact(
    value: object,
    *,
    expected_kind: str,
    location: str,
) -> Mapping[str, object]:
    artifact = _mapping(value, location=location)
    _exact_fields(artifact, _ARTIFACT_FIELDS, location=location)
    if artifact["kind"] != expected_kind:
        raise RollbackEvidenceValidationError(f"{location}.kind is invalid")
    _string(
        artifact["source_commit"],
        location=f"{location}.source_commit",
        pattern=_SOURCE_COMMIT,
    )
    _string(
        artifact["dependency_lock_sha256"],
        location=f"{location}.dependency_lock_sha256",
        pattern=_SHA256,
    )
    _string(
        artifact["artifact_sha256"],
        location=f"{location}.artifact_sha256",
        pattern=_SHA256,
    )
    _string(artifact["package_id"], location=f"{location}.package_id")
    _string(artifact["build_id"], location=f"{location}.build_id")
    return artifact


def _identity_map(value: object, *, location: str) -> dict[str, tuple[str, ...]]:
    identities = _mapping(value, location=location)
    if set(identities) != set(READABLE_ARTIFACT_KINDS):
        raise RollbackEvidenceValidationError(
            f"{location} must contain the exact readable artifact kinds"
        )
    normalized: dict[str, tuple[str, ...]] = {}
    flattened: list[str] = []
    for kind in READABLE_ARTIFACT_KINDS:
        raw_values = _list(identities[kind], location=f"{location}.{kind}")
        if not raw_values:
            raise RollbackEvidenceValidationError(
                f"{location}.{kind} must contain at least one durable identity"
            )
        values = tuple(
            _string(item, location=f"{location}.{kind}[{index}]")
            for index, item in enumerate(raw_values)
        )
        if len(values) != len(set(values)):
            raise RollbackEvidenceValidationError(
                f"{location}.{kind} contains a duplicate identity"
            )
        normalized[kind] = values
        flattened.extend(values)
    if len(flattened) != len(set(flattened)):
        raise RollbackEvidenceValidationError(
            f"{location} contains a duplicate identity across artifact kinds"
        )
    return normalized


def validate_rollback_drill_evidence(
    payload: Mapping[str, object],
) -> dict[str, object]:
    """Validate a reversible same-source drill without performing rollback."""

    evidence = _mapping(payload, location="evidence")
    _exact_fields(evidence, _TOP_LEVEL_FIELDS, location="evidence")
    if evidence["schema_version"] != ROLLBACK_DRILL_SCHEMA_VERSION:
        raise RollbackEvidenceValidationError(
            "rollback evidence schema is unsupported"
        )
    _string(evidence["drill_id"], location="evidence.drill_id")
    started_at = _timestamp(
        evidence["started_at"], location="evidence.started_at"
    )
    completed_at = _timestamp(
        evidence["completed_at"], location="evidence.completed_at"
    )
    if completed_at < started_at:
        raise RollbackEvidenceValidationError("rollback drill time range is invalid")
    execution_mode = evidence["execution_mode"]
    if execution_mode not in {"supported-data-copy", "installed-binary"}:
        raise RollbackEvidenceValidationError("execution_mode is invalid")
    binary_verified = _boolean(
        evidence["installed_binary_gate_verified"],
        location="evidence.installed_binary_gate_verified",
    )
    if execution_mode == "supported-data-copy" and binary_verified:
        raise RollbackEvidenceValidationError(
            "supported-data-copy evidence cannot claim the installed binary gate"
        )
    if execution_mode == "installed-binary" and not binary_verified:
        raise RollbackEvidenceValidationError(
            "installed-binary evidence must verify the binary gate"
        )

    candidate = _artifact(
        evidence["candidate_artifact"],
        expected_kind="wave4-candidate",
        location="evidence.candidate_artifact",
    )
    widgets = _artifact(
        evidence["retained_widgets_artifact"],
        expected_kind="retained-widgets",
        location="evidence.retained_widgets_artifact",
    )
    if candidate["source_commit"] != widgets["source_commit"]:
        raise RollbackEvidenceValidationError(
            "candidate and retained Widgets must use the same source commit"
        )
    if candidate["dependency_lock_sha256"] != widgets["dependency_lock_sha256"]:
        raise RollbackEvidenceValidationError(
            "candidate and retained Widgets must use the same dependency lock"
        )
    _string(
        evidence["supported_data_copy_sha256"],
        location="evidence.supported_data_copy_sha256",
        pattern=_SHA256,
    )

    raw_sequence = _list(
        evidence["stage_sequence"], location="evidence.stage_sequence"
    )
    if tuple(raw_sequence) != ROLLBACK_STAGE_SEQUENCE:
        raise RollbackEvidenceValidationError("rollback stage sequence is invalid")
    raw_stages = _list(evidence["stages"], location="evidence.stages")
    if len(raw_stages) != len(ROLLBACK_STAGE_SEQUENCE):
        raise RollbackEvidenceValidationError("rollback stages are incomplete")
    identity_graphs: list[dict[str, tuple[str, ...]]] = []
    task_handle_graphs: list[tuple[str, ...]] = []
    order_state_hashes: list[str] = []
    supported_surfaces = (
        "qml-source-smoke",
        "widgets-source-smoke",
        "application-authoritative-reopen",
    )
    installed_surfaces = (
        "installed-wave4-binary",
        "installed-widgets-binary",
        "installed-wave4-binary",
    )
    expected_surfaces = (
        supported_surfaces
        if execution_mode == "supported-data-copy"
        else installed_surfaces
    )
    previous_completed_at = started_at
    for index, (raw_stage, expected_stage) in enumerate(
        zip(raw_stages, ROLLBACK_STAGE_SEQUENCE, strict=True)
    ):
        location = f"evidence.stages[{index}]"
        stage = _mapping(raw_stage, location=location)
        _exact_fields(stage, _STAGE_FIELDS, location=location)
        if stage["stage"] != expected_stage:
            raise RollbackEvidenceValidationError("rollback stage sequence is invalid")
        if stage["verification_surface"] != expected_surfaces[index]:
            raise RollbackEvidenceValidationError(
                f"{location}.verification_surface is invalid for execution_mode"
            )
        stage_started_at = _timestamp(
            stage["started_at"], location=f"{location}.started_at"
        )
        stage_completed_at = _timestamp(
            stage["completed_at"], location=f"{location}.completed_at"
        )
        if (
            stage_started_at < previous_completed_at
            or stage_completed_at < stage_started_at
            or stage_completed_at > completed_at
        ):
            raise RollbackEvidenceValidationError(
                "rollback stage time range is invalid"
            )
        previous_completed_at = stage_completed_at
        if not _boolean(stage["clean_exit"], location=f"{location}.clean_exit"):
            raise RollbackEvidenceValidationError(
                f"{location} did not complete a clean exit"
            )
        readable = _list(
            stage["readable_artifacts"], location=f"{location}.readable_artifacts"
        )
        if tuple(readable) != READABLE_ARTIFACT_KINDS:
            raise RollbackEvidenceValidationError(
                f"{location} must contain the exact readable artifact kinds"
            )
        identity_graphs.append(
            _identity_map(
                stage["durable_identities"],
                location=f"{location}.durable_identities",
            )
        )
        raw_handles = _list(
            stage["task_handle_identities"],
            location=f"{location}.task_handle_identities",
        )
        handles = tuple(
            _string(item, location=f"{location}.task_handle_identities[{handle_index}]")
            for handle_index, item in enumerate(raw_handles)
        )
        if not handles or len(handles) != len(set(handles)):
            raise RollbackEvidenceValidationError(
                f"{location} contains a missing or duplicate TaskHandle identity"
            )
        task_handle_graphs.append(handles)
        order_state_hashes.append(
            _string(
                stage["order_state_sha256"],
                location=f"{location}.order_state_sha256",
                pattern=_SHA256,
            )
        )
    if any(graph != identity_graphs[0] for graph in identity_graphs[1:]) or any(
        graph != task_handle_graphs[0] for graph in task_handle_graphs[1:]
    ):
        raise RollbackEvidenceValidationError(
            "durable identity graph changed across the rollback drill"
        )
    measured_order_mutation_count = sum(
        value != order_state_hashes[0] for value in order_state_hashes[1:]
    )

    persistence = _mapping(
        evidence["persistence_migration"], location="evidence.persistence_migration"
    )
    _exact_fields(
        persistence,
        _PERSISTENCE_FIELDS,
        location="evidence.persistence_migration",
    )
    for field in (
        "fresh_initialization_revision",
        "copied_wave3_source_revision",
        "upgraded_revision",
    ):
        _string(persistence[field], location=f"evidence.persistence_migration.{field}")
    if (
        persistence["fresh_initialization_revision"] != DIAGNOSTIC_SCHEMA_REVISION
        or persistence["upgraded_revision"] != DIAGNOSTIC_SCHEMA_REVISION
    ):
        raise RollbackEvidenceValidationError(
            "persistence migration did not reach the current schema revision"
        )
    for field in (
        "deterministic",
        "idempotent",
        "additive",
        "retained_widgets_compatible",
    ):
        if not _boolean(
            persistence[field], location=f"evidence.persistence_migration.{field}"
        ):
            raise RollbackEvidenceValidationError(
                f"persistence migration must prove {field}"
            )
    reported_order_mutation_count = _count(
        persistence["order_mutation_count"],
        location="evidence.persistence_migration.order_mutation_count",
    )
    if reported_order_mutation_count != measured_order_mutation_count:
        raise RollbackEvidenceValidationError(
            "order_mutation_count does not match measured order state"
        )
    if measured_order_mutation_count != 0:
        raise RollbackEvidenceValidationError(
            "migration and rollback must not mutate orders"
        )

    bookmark = _mapping(
        evidence["bookmark_migration"], location="evidence.bookmark_migration"
    )
    _exact_fields(bookmark, _BOOKMARK_FIELDS, location="evidence.bookmark_migration")
    if (
        bookmark["source_schema_version"] != "1.0"
        or bookmark["target_schema_version"] != "2.0"
    ):
        raise RollbackEvidenceValidationError("bookmark migration version is invalid")
    for field in ("deterministic", "idempotent", "exact_durable_identities_preserved"):
        if not _boolean(
            bookmark[field],
            location=f"evidence.bookmark_migration.{field}",
        ):
            raise RollbackEvidenceValidationError(
                f"bookmark migration must prove {field}"
            )
    if not _boolean(
        evidence["task_handle_continuity"],
        location="evidence.task_handle_continuity",
    ):
        raise RollbackEvidenceValidationError("TaskHandle continuity was not preserved")
    if _count(
        evidence["duplicate_identity_count"],
        location="evidence.duplicate_identity_count",
    ) != 0:
        raise RollbackEvidenceValidationError(
            "rollback drill observed a duplicate identity"
        )
    return dict(payload)
