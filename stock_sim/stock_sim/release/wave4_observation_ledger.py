"""Wave 4 daily observation-ledger contracts.

The ledger is deliberately passive release evidence.  This module validates and
qualifies observations; it never publishes packages, migrates data, rolls back
an installation, or deletes a legacy route.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Final, cast


DAILY_LEDGER_SCHEMA_VERSION: Final = "wave4.daily-observation-ledger.v1"
METRIC_SET_ID: Final = "wave4.formal-observation.v1"
DAILY_LEDGER_JSON_SCHEMA_PATH: Final = Path(__file__).with_name(
    "wave4_daily_observation_ledger.schema.json"
)
REQUIRED_FEATURE_ROUTES: Final = (
    "strategy_library",
    "scenario_lab",
    "diagnostic_tasks",
    "run_monitoring",
    "evidence_and_findings",
    "system_health",
)
EXPECTED_CHECKPOINT_IDS: Final = (
    "install",
    "upgrade",
    "launch",
    "six-route-probe",
    "clean-exit",
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SOURCE_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_OBSERVATION_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_RESULTS: Final = frozenset({"passed", "failed", "not_observed"})
_PROHIBITED_FIELD_NAMES: Final = frozenset(
    {
        "credential",
        "credentials",
        "api_key",
        "authorization",
        "cookie",
        "database_dsn",
        "token",
        "access_token",
        "refresh_token",
        "database_url",
        "database_path",
        "dsn",
        "password",
        "secret",
        "connection_string",
        "sql",
        "arbitrary_command",
        "shell_command",
        "raw_traceback",
        "traceback",
        "market_payload",
        "account_payload",
        "order_payload",
        "fill_payload",
        "email",
        "phone",
        "address",
        "personal_name",
        "private_data",
        "user_id",
        "username",
        "ip_address",
        "hostname",
    }
)
_SECRET_VALUE_PATTERNS: Final = (
    re.compile(r"gh[opusr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?:sk-(?:proj-)?|sk_live_|glpat-)[A-Za-z0-9_-]{16,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{16,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~-]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|sqlite|duckdb)://"),
    re.compile(r"(?i)\b[A-Z]:\\"),
    re.compile(r"(?:^|\s)(?:/home/|/Users/|\\\\)[^\s]+"),
    re.compile(r"(?i)Traceback \(most recent call last\)"),
    re.compile(
        r"(?is)\b(?:select|insert|update|delete|drop|alter|create)\s+.+"
        r"\b(?:from|into|table|set)\b"
    ),
    re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    re.compile(r"(?i)\b(?:powershell|pwsh|cmd\.exe|bash)\b.*(?:-command|-c)\b"),
)

_TOP_LEVEL_FIELDS: Final = frozenset(
    {
        "schema_version",
        "metric_set_id",
        "ledger_id",
        "observation_date",
        "recorded_at",
        "calendar_timezone",
        "artifacts",
        "release",
        "collection",
        "lifecycle",
        "routes",
        "continuity",
        "delivery",
        "health",
        "route_incidents",
        "probe",
        "migration_integrity",
        "severity",
        "policy",
        "legacy_inventory",
        "product_rollback_forced",
    }
)
_ARTIFACTS_FIELDS: Final = frozenset({"candidate", "retained_widgets"})
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
_RELEASE_FIELDS: Final = frozenset(
    {"channel", "release_gates_passed", "package_published", "published_at"}
)
_COLLECTION_FIELDS: Final = frozenset(
    {"expected_checkpoint_ids", "observed_checkpoint_ids"}
)
_LIFECYCLE_FIELDS: Final = frozenset(
    {
        "install",
        "upgrade",
        "launch",
        "clean_exit",
        "crash_count",
        "unhandled_error_count",
    }
)
_ROUTE_FIELDS: Final = frozenset(
    {"route", "activation", "restore", "focus_restore", "typed_context_resolution"}
)
_CONTINUITY_FIELDS: Final = frozenset(
    {
        "task_handle_continuity",
        "duplicate_prevention",
        "durable_identity_continuity",
        "reopen_accepted_identities",
        "context_compatibility_failure_count",
        "manifest_compatibility_failure_count",
    }
)
_DELIVERY_FIELDS: Final = frozenset(
    {
        "disconnect_count",
        "stale_count",
        "fallback_count",
        "recovery_outcome",
        "max_recovery_latency_ms",
        "rejected_old_generation_count",
        "rejected_duplicate_count",
        "rejected_lower_revision_count",
        "incorrectly_accepted_old_generation_count",
        "incorrectly_accepted_duplicate_count",
        "incorrectly_accepted_lower_revision_count",
    }
)
_HEALTH_FIELDS: Final = frozenset({"queue", "cache", "persistence", "system_health"})
_HEALTH_COMPONENT_FIELDS: Final = frozenset(
    {"degradation_count", "max_degradation_duration_ms"}
)
_ROUTE_INCIDENT_FIELDS: Final = frozenset(
    {
        "route",
        "legacy_fallback_count",
        "legacy_fallback_forced",
        "forced_rollback",
        "v2_route_caused_fallback",
        "incident_code",
    }
)
_PROBE_FIELDS: Final = frozenset(
    {
        "probe_id",
        "scheduled",
        "six_route_passed",
        "renderer_lane",
        "graphics_api",
        "stall_probe_passed",
        "stall_over_50ms_count",
        "max_stall_ms",
    }
)
_MIGRATION_INTEGRITY_FIELDS: Final = frozenset(
    {"data_loss", "corruption", "destructive_migration"}
)
_SEVERITY_FIELDS: Final = frozenset(
    {"unresolved_sev1_count", "unresolved_sev2_count"}
)
_POLICY_FIELDS: Final = frozenset(
    {
        "security_violation_count",
        "redaction_violation_count",
        "webengine_included",
        "manual_trading_exposed",
    }
)
_LEGACY_INVENTORY_FIELDS: Final = frozenset(
    {"inventory_id", "inventory_sha256", "legacy_route_count"}
)


class LedgerValidationError(ValueError):
    """Raised when an observation ledger is malformed or unsafe."""


class ObservationWindowError(ValueError):
    """Raised when ledgers cannot belong to one immutable observation window."""


class LedgerCollectionError(ValueError):
    """Raised when a validated ledger cannot be collected safely."""


class ResetReason(str, Enum):
    """Stable machine identities for the Issue #117 reset conditions."""

    UNRESOLVED_SEV1 = "unresolved_sev1"
    UNRESOLVED_SEV2 = "unresolved_sev2"
    FORCED_PRODUCT_ROLLBACK = "forced_product_rollback"
    FORCED_ROUTE_ROLLBACK = "forced_route_rollback"
    DATA_LOSS = "data_loss"
    CORRUPTION = "corruption"
    DESTRUCTIVE_MIGRATION = "destructive_migration"
    TYPED_IDENTITY_CONTINUITY_VIOLATION = "typed_identity_continuity_violation"
    DUPLICATE_DIAGNOSTIC_WORK = "duplicate_diagnostic_work"
    INCORRECTLY_ACCEPTED_OLD_GENERATION = "incorrectly_accepted_old_generation"
    INCORRECTLY_ACCEPTED_DUPLICATE = "incorrectly_accepted_duplicate"
    INCORRECTLY_ACCEPTED_LOWER_REVISION = "incorrectly_accepted_lower_revision"
    ACCEPTED_IDENTITY_REOPEN_FAILURE = "accepted_identity_reopen_failure"
    MANUAL_TRADING_EXPOSURE = "manual_trading_exposure"
    WEBENGINE_INCLUSION = "webengine_inclusion"
    SECURITY_BREACH = "security_breach"
    REDACTION_BREACH = "redaction_breach"
    V2_ROUTE_FORCED_LEGACY_FALLBACK = "v2_route_forced_legacy_fallback"


@dataclass(frozen=True, slots=True)
class DailyLedgerAssessment:
    ledger_id: str
    observation_date: str
    source_commit: str
    dependency_lock_sha256: str
    renderer_lane: str
    complete: bool
    qualifying: bool
    reset_reasons: tuple[ResetReason, ...]
    disqualifications: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResetEvent:
    ledger_id: str
    observation_date: str
    reasons: tuple[ResetReason, ...]


@dataclass(frozen=True, slots=True)
class WindowInterruption:
    ledger_id: str
    observation_date: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ObservationWindowAssessment:
    required_consecutive_days: int
    current_consecutive_days: int
    window_start_date: str | None
    window_end_date: str | None
    renderer_lanes: tuple[str, ...]
    fourteen_day_requirement_satisfied: bool
    reset_events: tuple[ResetEvent, ...]
    interruptions: tuple[WindowInterruption, ...]


@dataclass(frozen=True, slots=True)
class CollectedDailyLedger:
    path: Path
    sha256: str
    assessment: DailyLedgerAssessment


def _audit_payload_safety(value: object, *, location: str = "ledger") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            if not isinstance(raw_key, str):
                raise LedgerValidationError(f"{location} contains a non-string field")
            normalized_key = raw_key.casefold()
            if normalized_key in _PROHIBITED_FIELD_NAMES:
                raise LedgerValidationError(
                    f"{location}.{raw_key} is a prohibited ledger field"
                )
            _audit_payload_safety(child, location=f"{location}.{raw_key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _audit_payload_safety(child, location=f"{location}[{index}]")
        return
    if isinstance(value, str) and any(
        pattern.search(value) is not None for pattern in _SECRET_VALUE_PATTERNS
    ):
        raise LedgerValidationError(f"{location} contains a secret-like value")


def _require_exact_fields(
    value: Mapping[str, object],
    expected: frozenset[str],
    *,
    location: str,
) -> None:
    missing = sorted(expected.difference(value))
    if missing:
        raise LedgerValidationError(
            f"{location} is missing required field(s): {', '.join(missing)}"
        )
    extra = sorted(set(value).difference(expected))
    if extra:
        raise LedgerValidationError(
            f"{location} has unexpected field(s): {', '.join(extra)}"
        )


def _require_mapping(value: object, *, location: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise LedgerValidationError(f"{location} must be a JSON object")
    return value


def _require_list(value: object, *, location: str) -> list[object]:
    if not isinstance(value, list):
        raise LedgerValidationError(f"{location} must be a JSON array")
    return value


def _require_string(
    value: object,
    *,
    location: str,
    pattern: re.Pattern[str] = _SAFE_ID,
) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise LedgerValidationError(f"{location} has an invalid value")
    return value


def _require_choice(
    value: object,
    choices: frozenset[str],
    *,
    location: str,
) -> str:
    if not isinstance(value, str) or value not in choices:
        raise LedgerValidationError(
            f"{location} must be one of: {', '.join(sorted(choices))}"
        )
    return value


def _require_bool(value: object, *, location: str) -> bool:
    if not isinstance(value, bool):
        raise LedgerValidationError(f"{location} must be a boolean")
    return value


def _require_non_negative_int(value: object, *, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LedgerValidationError(f"{location} must be a non-negative integer")
    return value


def _require_utc_timestamp(value: object, *, location: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise LedgerValidationError(f"{location} must be an ISO-8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise LedgerValidationError(
            f"{location} must be an ISO-8601 UTC timestamp"
        ) from exc
    if parsed.tzinfo != timezone.utc:
        raise LedgerValidationError(f"{location} must be an ISO-8601 UTC timestamp")
    return parsed


def _validate_artifact(value: object, *, location: str) -> Mapping[str, object]:
    artifact = _require_mapping(value, location=location)
    _require_exact_fields(artifact, _ARTIFACT_FIELDS, location=location)
    _require_choice(
        artifact["kind"],
        frozenset({"wave4-candidate", "retained-widgets"}),
        location=f"{location}.kind",
    )
    _require_string(
        artifact["source_commit"],
        location=f"{location}.source_commit",
        pattern=_SOURCE_COMMIT,
    )
    for field in ("dependency_lock_sha256", "artifact_sha256"):
        _require_string(
            artifact[field],
            location=f"{location}.{field}",
            pattern=_SHA256,
        )
    for field in ("package_id", "build_id"):
        _require_string(artifact[field], location=f"{location}.{field}")
    return artifact


def _validate_result_fields(
    value: Mapping[str, object],
    fields: tuple[str, ...],
    *,
    location: str,
) -> None:
    for field in fields:
        _require_choice(value[field], _RESULTS, location=f"{location}.{field}")


def _validate_route_records(
    value: object,
    *,
    location: str,
    incident: bool,
) -> None:
    records = _require_list(value, location=location)
    if len(records) != len(REQUIRED_FEATURE_ROUTES):
        raise LedgerValidationError(
            f"{location} must contain the exact six Feature routes"
        )
    observed_routes: list[str] = []
    for index, raw_record in enumerate(records):
        record_location = f"{location}[{index}]"
        record = _require_mapping(raw_record, location=record_location)
        fields = _ROUTE_INCIDENT_FIELDS if incident else _ROUTE_FIELDS
        _require_exact_fields(record, fields, location=record_location)
        route = _require_string(record["route"], location=f"{record_location}.route")
        observed_routes.append(route)
        if incident:
            _require_non_negative_int(
                record["legacy_fallback_count"],
                location=f"{record_location}.legacy_fallback_count",
            )
            _require_bool(
                record["legacy_fallback_forced"],
                location=f"{record_location}.legacy_fallback_forced",
            )
            _require_bool(
                record["forced_rollback"],
                location=f"{record_location}.forced_rollback",
            )
            _require_bool(
                record["v2_route_caused_fallback"],
                location=f"{record_location}.v2_route_caused_fallback",
            )
            incident_code = record["incident_code"]
            if incident_code is not None:
                _require_string(
                    incident_code,
                    location=f"{record_location}.incident_code",
                )
        else:
            _validate_result_fields(
                record,
                (
                    "activation",
                    "restore",
                    "focus_restore",
                    "typed_context_resolution",
                ),
                location=record_location,
            )
    if tuple(observed_routes) != REQUIRED_FEATURE_ROUTES:
        raise LedgerValidationError(
            f"{location} must contain the exact six Feature routes"
        )


def _validate_checkpoint_ids(value: object, *, location: str) -> tuple[str, ...]:
    raw_values = _require_list(value, location=location)
    values = tuple(
        _require_string(item, location=f"{location}[{index}]")
        for index, item in enumerate(raw_values)
    )
    if len(values) != len(set(values)):
        raise LedgerValidationError(
            f"{location} must not contain duplicate identities"
        )
    return values


def validate_daily_observation_ledger(
    payload: Mapping[str, object],
) -> dict[str, object]:
    """Validate and return a shallow canonical copy of one daily ledger."""

    if not isinstance(payload, Mapping):
        raise LedgerValidationError("ledger must be a JSON object")
    _audit_payload_safety(payload)
    _require_exact_fields(payload, _TOP_LEVEL_FIELDS, location="ledger")

    if payload["schema_version"] != DAILY_LEDGER_SCHEMA_VERSION:
        raise LedgerValidationError("ledger.schema_version is unsupported")
    if payload["metric_set_id"] != METRIC_SET_ID:
        raise LedgerValidationError("ledger.metric_set_id is unsupported")
    _require_string(payload["ledger_id"], location="ledger.ledger_id")
    observation_date = _require_string(
        payload["observation_date"],
        location="ledger.observation_date",
        pattern=_OBSERVATION_DATE,
    )
    try:
        parsed_observation_date = datetime.strptime(
            observation_date, "%Y-%m-%d"
        ).date()
    except ValueError as exc:
        raise LedgerValidationError(
            "ledger.observation_date is not a valid date"
        ) from exc
    recorded_at = _require_utc_timestamp(
        payload["recorded_at"], location="ledger.recorded_at"
    )
    if recorded_at.date() != parsed_observation_date:
        raise LedgerValidationError(
            "ledger.observation_date must match the UTC recorded_at date"
        )
    if payload["calendar_timezone"] != "UTC":
        raise LedgerValidationError("ledger.calendar_timezone must be UTC")

    artifacts = _require_mapping(payload["artifacts"], location="ledger.artifacts")
    _require_exact_fields(artifacts, _ARTIFACTS_FIELDS, location="ledger.artifacts")
    candidate = _validate_artifact(
        artifacts["candidate"], location="ledger.artifacts.candidate"
    )
    widgets = _validate_artifact(
        artifacts["retained_widgets"], location="ledger.artifacts.retained_widgets"
    )
    if candidate["kind"] != "wave4-candidate":
        raise LedgerValidationError("candidate artifact kind must be wave4-candidate")
    if widgets["kind"] != "retained-widgets":
        raise LedgerValidationError("retained Widgets artifact kind is invalid")
    if candidate["source_commit"] != widgets["source_commit"]:
        raise LedgerValidationError(
            "candidate and retained Widgets must use the same source commit"
        )
    if candidate["dependency_lock_sha256"] != widgets["dependency_lock_sha256"]:
        raise LedgerValidationError(
            "candidate and retained Widgets must use the same dependency lock"
        )

    release = _require_mapping(payload["release"], location="ledger.release")
    _require_exact_fields(release, _RELEASE_FIELDS, location="ledger.release")
    _require_choice(
        release["channel"],
        frozenset({"formal", "rc", "development", "prerelease"}),
        location="ledger.release.channel",
    )
    _require_bool(
        release["release_gates_passed"],
        location="ledger.release.release_gates_passed",
    )
    _require_bool(
        release["package_published"], location="ledger.release.package_published"
    )
    if release["published_at"] is not None:
        _require_utc_timestamp(
            release["published_at"], location="ledger.release.published_at"
        )

    collection = _require_mapping(
        payload["collection"], location="ledger.collection"
    )
    _require_exact_fields(collection, _COLLECTION_FIELDS, location="ledger.collection")
    expected_checkpoints = _validate_checkpoint_ids(
        collection["expected_checkpoint_ids"],
        location="ledger.collection.expected_checkpoint_ids",
    )
    if expected_checkpoints != EXPECTED_CHECKPOINT_IDS:
        raise LedgerValidationError(
            "ledger.collection.expected_checkpoint_ids must use the fixed metric set"
        )
    observed_checkpoints = _validate_checkpoint_ids(
        collection["observed_checkpoint_ids"],
        location="ledger.collection.observed_checkpoint_ids",
    )
    if not set(observed_checkpoints).issubset(expected_checkpoints):
        raise LedgerValidationError(
            "ledger.collection.observed_checkpoint_ids contains an unknown identity"
        )

    lifecycle = _require_mapping(payload["lifecycle"], location="ledger.lifecycle")
    _require_exact_fields(lifecycle, _LIFECYCLE_FIELDS, location="ledger.lifecycle")
    _validate_result_fields(
        lifecycle,
        ("install", "upgrade", "launch", "clean_exit"),
        location="ledger.lifecycle",
    )
    for field in ("crash_count", "unhandled_error_count"):
        _require_non_negative_int(
            lifecycle[field], location=f"ledger.lifecycle.{field}"
        )

    _validate_route_records(payload["routes"], location="ledger.routes", incident=False)

    continuity = _require_mapping(
        payload["continuity"], location="ledger.continuity"
    )
    _require_exact_fields(continuity, _CONTINUITY_FIELDS, location="ledger.continuity")
    _validate_result_fields(
        continuity,
        (
            "task_handle_continuity",
            "duplicate_prevention",
            "durable_identity_continuity",
            "reopen_accepted_identities",
        ),
        location="ledger.continuity",
    )
    for field in (
        "context_compatibility_failure_count",
        "manifest_compatibility_failure_count",
    ):
        _require_non_negative_int(
            continuity[field], location=f"ledger.continuity.{field}"
        )

    delivery = _require_mapping(payload["delivery"], location="ledger.delivery")
    _require_exact_fields(delivery, _DELIVERY_FIELDS, location="ledger.delivery")
    _require_choice(
        delivery["recovery_outcome"],
        _RESULTS,
        location="ledger.delivery.recovery_outcome",
    )
    for field in _DELIVERY_FIELDS.difference({"recovery_outcome"}):
        _require_non_negative_int(
            delivery[field], location=f"ledger.delivery.{field}"
        )

    health = _require_mapping(payload["health"], location="ledger.health")
    _require_exact_fields(health, _HEALTH_FIELDS, location="ledger.health")
    for component_name in sorted(_HEALTH_FIELDS):
        component = _require_mapping(
            health[component_name], location=f"ledger.health.{component_name}"
        )
        _require_exact_fields(
            component,
            _HEALTH_COMPONENT_FIELDS,
            location=f"ledger.health.{component_name}",
        )
        for field in _HEALTH_COMPONENT_FIELDS:
            _require_non_negative_int(
                component[field], location=f"ledger.health.{component_name}.{field}"
            )

    _validate_route_records(
        payload["route_incidents"],
        location="ledger.route_incidents",
        incident=True,
    )

    probe = _require_mapping(payload["probe"], location="ledger.probe")
    _require_exact_fields(probe, _PROBE_FIELDS, location="ledger.probe")
    _require_string(probe["probe_id"], location="ledger.probe.probe_id")
    for field in ("scheduled", "six_route_passed", "stall_probe_passed"):
        _require_bool(probe[field], location=f"ledger.probe.{field}")
    _require_choice(
        probe["renderer_lane"],
        frozenset({"hardware", "software"}),
        location="ledger.probe.renderer_lane",
    )
    _require_choice(
        probe["graphics_api"],
        frozenset({"Direct3D11", "Software"}),
        location="ledger.probe.graphics_api",
    )
    if (
        probe["renderer_lane"] == "hardware"
        and probe["graphics_api"] != "Direct3D11"
    ) or (
        probe["renderer_lane"] == "software"
        and probe["graphics_api"] != "Software"
    ):
        raise LedgerValidationError("ledger.probe renderer lane/API identity mismatch")
    for field in ("stall_over_50ms_count", "max_stall_ms"):
        _require_non_negative_int(
            probe[field], location=f"ledger.probe.{field}"
        )

    migration = _require_mapping(
        payload["migration_integrity"], location="ledger.migration_integrity"
    )
    _require_exact_fields(
        migration,
        _MIGRATION_INTEGRITY_FIELDS,
        location="ledger.migration_integrity",
    )
    for field in _MIGRATION_INTEGRITY_FIELDS:
        _require_bool(migration[field], location=f"ledger.migration_integrity.{field}")

    severity = _require_mapping(payload["severity"], location="ledger.severity")
    _require_exact_fields(severity, _SEVERITY_FIELDS, location="ledger.severity")
    for field in _SEVERITY_FIELDS:
        _require_non_negative_int(severity[field], location=f"ledger.severity.{field}")

    policy = _require_mapping(payload["policy"], location="ledger.policy")
    _require_exact_fields(policy, _POLICY_FIELDS, location="ledger.policy")
    for field in ("security_violation_count", "redaction_violation_count"):
        _require_non_negative_int(policy[field], location=f"ledger.policy.{field}")
    for field in ("webengine_included", "manual_trading_exposed"):
        _require_bool(policy[field], location=f"ledger.policy.{field}")

    legacy_inventory = _require_mapping(
        payload["legacy_inventory"], location="ledger.legacy_inventory"
    )
    _require_exact_fields(
        legacy_inventory,
        _LEGACY_INVENTORY_FIELDS,
        location="ledger.legacy_inventory",
    )
    _require_string(
        legacy_inventory["inventory_id"],
        location="ledger.legacy_inventory.inventory_id",
    )
    _require_string(
        legacy_inventory["inventory_sha256"],
        location="ledger.legacy_inventory.inventory_sha256",
        pattern=_SHA256,
    )
    legacy_route_count = _require_non_negative_int(
        legacy_inventory["legacy_route_count"],
        location="ledger.legacy_inventory.legacy_route_count",
    )
    if legacy_route_count != 8:
        raise LedgerValidationError(
            "ledger.legacy_inventory.legacy_route_count must equal 8"
        )
    _require_bool(
        payload["product_rollback_forced"],
        location="ledger.product_rollback_forced",
    )
    return dict(payload)


def _mapping(value: object) -> Mapping[str, object]:
    """Narrow a value already checked by the public validator."""

    return cast(Mapping[str, object], value)


def _record_list(value: object) -> list[Mapping[str, object]]:
    """Narrow a route list already checked by the public validator."""

    return cast(list[Mapping[str, object]], value)


def assess_daily_observation_ledger(
    payload: Mapping[str, object],
) -> DailyLedgerAssessment:
    """Validate one daily ledger and derive completeness and qualification."""

    ledger = validate_daily_observation_ledger(payload)
    artifacts = _mapping(ledger["artifacts"])
    candidate = _mapping(artifacts["candidate"])
    release = _mapping(ledger["release"])
    collection = _mapping(ledger["collection"])
    lifecycle = _mapping(ledger["lifecycle"])
    routes = _record_list(ledger["routes"])
    continuity = _mapping(ledger["continuity"])
    delivery = _mapping(ledger["delivery"])
    health = _mapping(ledger["health"])
    route_incidents = _record_list(ledger["route_incidents"])
    probe = _mapping(ledger["probe"])
    migration = _mapping(ledger["migration_integrity"])
    severity = _mapping(ledger["severity"])
    policy = _mapping(ledger["policy"])

    observed_checkpoints = tuple(
        cast(list[str], collection["observed_checkpoint_ids"])
    )
    result_values = [
        lifecycle[field]
        for field in ("install", "upgrade", "launch", "clean_exit")
    ]
    result_values.extend(
        route[field]
        for route in routes
        for field in (
            "activation",
            "restore",
            "focus_restore",
            "typed_context_resolution",
        )
    )
    result_values.extend(
        continuity[field]
        for field in (
            "task_handle_continuity",
            "duplicate_prevention",
            "durable_identity_continuity",
            "reopen_accepted_identities",
        )
    )
    result_values.append(delivery["recovery_outcome"])
    complete = (
        observed_checkpoints == EXPECTED_CHECKPOINT_IDS
        and all(result != "not_observed" for result in result_values)
    )

    reset_reasons: list[ResetReason] = []
    if cast(int, severity["unresolved_sev1_count"]) > 0:
        reset_reasons.append(ResetReason.UNRESOLVED_SEV1)
    if cast(int, severity["unresolved_sev2_count"]) > 0:
        reset_reasons.append(ResetReason.UNRESOLVED_SEV2)
    if cast(bool, ledger["product_rollback_forced"]):
        reset_reasons.append(ResetReason.FORCED_PRODUCT_ROLLBACK)
    if any(cast(bool, incident["forced_rollback"]) for incident in route_incidents):
        reset_reasons.append(ResetReason.FORCED_ROUTE_ROLLBACK)
    if cast(bool, migration["data_loss"]):
        reset_reasons.append(ResetReason.DATA_LOSS)
    if cast(bool, migration["corruption"]):
        reset_reasons.append(ResetReason.CORRUPTION)
    if cast(bool, migration["destructive_migration"]):
        reset_reasons.append(ResetReason.DESTRUCTIVE_MIGRATION)
    typed_route_failure = any(
        route["typed_context_resolution"] == "failed" for route in routes
    )
    if (
        continuity["durable_identity_continuity"] == "failed"
        or continuity["task_handle_continuity"] == "failed"
        or typed_route_failure
    ):
        reset_reasons.append(ResetReason.TYPED_IDENTITY_CONTINUITY_VIOLATION)
    if continuity["duplicate_prevention"] == "failed":
        reset_reasons.append(ResetReason.DUPLICATE_DIAGNOSTIC_WORK)
    for field, reason in (
        (
            "incorrectly_accepted_old_generation_count",
            ResetReason.INCORRECTLY_ACCEPTED_OLD_GENERATION,
        ),
        (
            "incorrectly_accepted_duplicate_count",
            ResetReason.INCORRECTLY_ACCEPTED_DUPLICATE,
        ),
        (
            "incorrectly_accepted_lower_revision_count",
            ResetReason.INCORRECTLY_ACCEPTED_LOWER_REVISION,
        ),
    ):
        if cast(int, delivery[field]) > 0:
            reset_reasons.append(reason)
    if continuity["reopen_accepted_identities"] == "failed":
        reset_reasons.append(ResetReason.ACCEPTED_IDENTITY_REOPEN_FAILURE)
    if cast(bool, policy["manual_trading_exposed"]):
        reset_reasons.append(ResetReason.MANUAL_TRADING_EXPOSURE)
    if cast(bool, policy["webengine_included"]):
        reset_reasons.append(ResetReason.WEBENGINE_INCLUSION)
    if cast(int, policy["security_violation_count"]) > 0:
        reset_reasons.append(ResetReason.SECURITY_BREACH)
    if cast(int, policy["redaction_violation_count"]) > 0:
        reset_reasons.append(ResetReason.REDACTION_BREACH)
    if any(
        cast(bool, incident["v2_route_caused_fallback"])
        and cast(bool, incident["legacy_fallback_forced"])
        and cast(int, incident["legacy_fallback_count"]) > 0
        for incident in route_incidents
    ):
        reset_reasons.append(ResetReason.V2_ROUTE_FORCED_LEGACY_FALLBACK)

    disqualifications: list[str] = []

    def disqualify(condition: bool, identity: str) -> None:
        if condition:
            disqualifications.append(identity)

    disqualify(not complete, "incomplete_daily_collection")
    disqualify(release["channel"] != "formal", "non_formal_release_channel")
    disqualify(
        not cast(bool, release["release_gates_passed"]),
        "release_gates_not_passed",
    )
    disqualify(
        not cast(bool, release["package_published"])
        or release["published_at"] is None,
        "formal_package_not_published",
    )
    if release["published_at"] is not None:
        published_at = _require_utc_timestamp(
            release["published_at"], location="ledger.release.published_at"
        )
        recorded_at = _require_utc_timestamp(
            ledger["recorded_at"], location="ledger.recorded_at"
        )
        disqualify(
            published_at > recorded_at,
            "observation_precedes_formal_publication",
        )
    disqualify(
        any(result != "passed" for result in result_values),
        "failed_observation",
    )
    disqualify(
        cast(int, lifecycle["crash_count"]) > 0,
        "crash_observed",
    )
    disqualify(
        cast(int, lifecycle["unhandled_error_count"]) > 0,
        "unhandled_error_observed",
    )
    disqualify(
        cast(int, continuity["context_compatibility_failure_count"]) > 0,
        "context_compatibility_failure",
    )
    disqualify(
        cast(int, continuity["manifest_compatibility_failure_count"]) > 0,
        "manifest_compatibility_failure",
    )
    disqualify(
        cast(int, delivery["fallback_count"]) > 0,
        "delivery_fallback_observed",
    )
    disqualify(
        any(
            cast(int, _mapping(component)["degradation_count"]) > 0
            for component in health.values()
        ),
        "health_degradation_observed",
    )
    disqualify(
        any(
            cast(int, incident["legacy_fallback_count"]) > 0
            for incident in route_incidents
        ),
        "route_legacy_fallback_observed",
    )
    disqualify(
        not cast(bool, probe["scheduled"]),
        "scheduled_probe_not_run",
    )
    disqualify(
        not cast(bool, probe["six_route_passed"]),
        "six_route_probe_failed",
    )
    disqualify(
        not cast(bool, probe["stall_probe_passed"])
        or cast(int, probe["stall_over_50ms_count"]) > 0
        or cast(int, probe["max_stall_ms"]) > 50,
        "stall_probe_failed",
    )
    disqualify(bool(reset_reasons), "reset_condition_observed")

    return DailyLedgerAssessment(
        ledger_id=cast(str, ledger["ledger_id"]),
        observation_date=cast(str, ledger["observation_date"]),
        source_commit=cast(str, candidate["source_commit"]),
        dependency_lock_sha256=cast(
            str, candidate["dependency_lock_sha256"]
        ),
        renderer_lane=cast(str, probe["renderer_lane"]),
        complete=complete,
        qualifying=not disqualifications,
        reset_reasons=tuple(reset_reasons),
        disqualifications=tuple(disqualifications),
    )


def _window_identity(ledger: Mapping[str, object]) -> tuple[object, ...]:
    artifacts = _mapping(ledger["artifacts"])
    candidate = _mapping(artifacts["candidate"])
    widgets = _mapping(artifacts["retained_widgets"])
    legacy_inventory = _mapping(ledger["legacy_inventory"])
    return (
        ledger["schema_version"],
        ledger["metric_set_id"],
        candidate["source_commit"],
        candidate["dependency_lock_sha256"],
        candidate["artifact_sha256"],
        candidate["package_id"],
        candidate["build_id"],
        widgets["source_commit"],
        widgets["dependency_lock_sha256"],
        widgets["artifact_sha256"],
        widgets["package_id"],
        widgets["build_id"],
        legacy_inventory["inventory_id"],
        legacy_inventory["inventory_sha256"],
        legacy_inventory["legacy_route_count"],
    )


def calculate_observation_window(
    payloads: Sequence[Mapping[str, object]],
) -> ObservationWindowAssessment:
    """Calculate a passive consecutive-day requirement for one formal build.

    Satisfying the returned requirement does not publish a release, authorize a
    legacy-route exit, or delete any code.  A caller must calculate a new window
    when the fixed schema, metrics, build, packages, dependency lock, or legacy
    inventory identity changes.
    """

    required_consecutive_days = 14

    validated = [validate_daily_observation_ledger(payload) for payload in payloads]
    validated.sort(key=lambda ledger: cast(str, ledger["observation_date"]))
    dates = [cast(str, ledger["observation_date"]) for ledger in validated]
    if len(dates) != len(set(dates)):
        raise ObservationWindowError(
            "an observation window may contain only one ledger per UTC date"
        )

    active_identity: tuple[object, ...] | None = None
    streak: list[DailyLedgerAssessment] = []
    last_qualifying_date: datetime | None = None
    reset_events: list[ResetEvent] = []
    interruptions: list[WindowInterruption] = []

    for ledger in validated:
        assessment = assess_daily_observation_ledger(ledger)
        identity = _window_identity(ledger)
        if active_identity is None and assessment.qualifying:
            active_identity = identity
        elif active_identity is not None and identity != active_identity:
            raise ObservationWindowError(
                "active-window metric or artifact identity changed"
            )

        if assessment.reset_reasons:
            reset_events.append(
                ResetEvent(
                    ledger_id=assessment.ledger_id,
                    observation_date=assessment.observation_date,
                    reasons=assessment.reset_reasons,
                )
            )
            streak = []
            last_qualifying_date = None
            continue

        if not assessment.qualifying:
            interruptions.append(
                WindowInterruption(
                    ledger_id=assessment.ledger_id,
                    observation_date=assessment.observation_date,
                    reasons=assessment.disqualifications,
                )
            )
            streak = []
            last_qualifying_date = None
            continue

        current_date = datetime.strptime(
            assessment.observation_date, "%Y-%m-%d"
        )
        if (
            last_qualifying_date is not None
            and (current_date - last_qualifying_date).days != 1
        ):
            interruptions.append(
                WindowInterruption(
                    ledger_id=assessment.ledger_id,
                    observation_date=assessment.observation_date,
                    reasons=("missing_consecutive_calendar_day",),
                )
            )
            streak = []
        streak.append(assessment)
        last_qualifying_date = current_date

    renderer_lanes = tuple(
        lane
        for lane in ("hardware", "software")
        if any(day.renderer_lane == lane for day in streak)
    )
    has_renderer_coverage = renderer_lanes == ("hardware", "software")
    requirement_satisfied = (
        len(streak) >= required_consecutive_days and has_renderer_coverage
    )
    return ObservationWindowAssessment(
        required_consecutive_days=required_consecutive_days,
        current_consecutive_days=len(streak),
        window_start_date=streak[0].observation_date if streak else None,
        window_end_date=streak[-1].observation_date if streak else None,
        renderer_lanes=renderer_lanes,
        fourteen_day_requirement_satisfied=requirement_satisfied,
        reset_events=tuple(reset_events),
        interruptions=tuple(interruptions),
    )


def canonical_daily_observation_ledger_bytes(
    payload: Mapping[str, object],
) -> bytes:
    """Return canonical UTF-8 JSON bytes for a validated ledger."""

    validated = validate_daily_observation_ledger(payload)
    return (
        json.dumps(
            validated,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def collect_daily_observation_ledger(
    payload: Mapping[str, object],
    *,
    output_directory: Path,
    require_qualifying: bool = False,
) -> CollectedDailyLedger:
    """Validate and collect a ledger without overwriting differing evidence."""

    assessment = assess_daily_observation_ledger(payload)
    if require_qualifying and not assessment.qualifying:
        raise LedgerCollectionError(
            "daily ledger does not qualify for the formal observation window"
        )
    canonical = canonical_daily_observation_ledger_bytes(payload)
    digest = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    output_directory.mkdir(parents=True, exist_ok=True)
    filename_digest = hashlib.sha256(assessment.ledger_id.encode("utf-8")).hexdigest()
    path = output_directory / f"ledger-{filename_digest}.json"
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise LedgerCollectionError("existing daily ledger is unreadable") from exc
        if existing != canonical:
            raise LedgerCollectionError(
                "daily ledger identity already exists with different content"
            )
        return CollectedDailyLedger(path=path, sha256=digest, assessment=assessment)
    try:
        with path.open("xb") as stream:
            stream.write(canonical)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise LedgerCollectionError("raced daily ledger is unreadable") from exc
        if existing != canonical:
            raise LedgerCollectionError(
                "daily ledger identity already exists with different content"
            )
    except OSError as exc:
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        raise LedgerCollectionError("daily ledger could not be collected") from exc
    return CollectedDailyLedger(path=path, sha256=digest, assessment=assessment)
