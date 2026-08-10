"""Machine-readable inventory of retained Widgets legacy routes for Wave 4."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Final, cast


LEGACY_INVENTORY_SCHEMA_VERSION: Final = "wave4.legacy-route-inventory.v1"
LEGACY_ROUTE_IDS: Final = (
    "diagnostics",
    "account",
    "market",
    "agents",
    "arena",
    "leaderboard",
    "clock",
    "orders",
)

_SOURCE_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_INVENTORY_FIELDS: Final = frozenset(
    {
        "schema_version",
        "inventory_id",
        "source_commit",
        "captured_at",
        "legacy_route_count",
        "widgets_shell_status",
        "deletion_authorized",
        "clean_windows_gate_passed",
        "routes",
    }
)
_ROUTE_FIELDS: Final = frozenset(
    {
        "legacy_route_id",
        "panel_registration",
        "status",
        "stakeholder_exit_record_id",
        "route_rollback_drill_id",
        "atomic_exit_authorized",
    }
)


class LegacyInventoryValidationError(ValueError):
    """Raised when a legacy inventory is incomplete or authorizes deletion."""


def _exact_fields(
    value: Mapping[str, object],
    expected: frozenset[str],
    *,
    location: str,
) -> None:
    missing = sorted(expected.difference(value))
    extra = sorted(set(value).difference(expected))
    if missing:
        raise LegacyInventoryValidationError(
            f"{location} is missing required field(s): {', '.join(missing)}"
        )
    if extra:
        raise LegacyInventoryValidationError(
            f"{location} has unexpected field(s): {', '.join(extra)}"
        )


def _utc_timestamp(value: object, *, location: str) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise LegacyInventoryValidationError(f"{location} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise LegacyInventoryValidationError(
            f"{location} must be a UTC timestamp"
        ) from exc
    if parsed.tzinfo != timezone.utc:
        raise LegacyInventoryValidationError(f"{location} must be a UTC timestamp")


def build_legacy_route_inventory(
    *,
    source_commit: str,
    captured_at: str,
) -> dict[str, object]:
    """Build the current retained inventory without authorizing any route exit."""

    inventory: dict[str, object] = {
        "schema_version": LEGACY_INVENTORY_SCHEMA_VERSION,
        "inventory_id": f"wave4-legacy-inventory-{source_commit[:12]}",
        "source_commit": source_commit,
        "captured_at": captured_at,
        "legacy_route_count": len(LEGACY_ROUTE_IDS),
        "widgets_shell_status": "retained",
        "deletion_authorized": False,
        "clean_windows_gate_passed": False,
        "routes": [
            {
                "legacy_route_id": route_id,
                "panel_registration": route_id,
                "status": "retained",
                "stakeholder_exit_record_id": None,
                "route_rollback_drill_id": None,
                "atomic_exit_authorized": False,
            }
            for route_id in LEGACY_ROUTE_IDS
        ],
    }
    return validate_legacy_route_inventory(inventory)


def validate_legacy_route_inventory(
    payload: Mapping[str, object],
) -> dict[str, object]:
    """Validate exact inventory coverage and the no-deletion invariant."""

    if not isinstance(payload, Mapping):
        raise LegacyInventoryValidationError("inventory must be a JSON object")
    _exact_fields(payload, _INVENTORY_FIELDS, location="inventory")
    if payload["schema_version"] != LEGACY_INVENTORY_SCHEMA_VERSION:
        raise LegacyInventoryValidationError("inventory schema version is unsupported")
    if (
        not isinstance(payload["inventory_id"], str)
        or _SAFE_ID.fullmatch(payload["inventory_id"]) is None
    ):
        raise LegacyInventoryValidationError("inventory_id is invalid")
    if (
        not isinstance(payload["source_commit"], str)
        or _SOURCE_COMMIT.fullmatch(payload["source_commit"]) is None
    ):
        raise LegacyInventoryValidationError("source_commit is invalid")
    _utc_timestamp(payload["captured_at"], location="captured_at")
    if (
        isinstance(payload["legacy_route_count"], bool)
        or payload["legacy_route_count"] != len(LEGACY_ROUTE_IDS)
    ):
        raise LegacyInventoryValidationError("legacy_route_count must equal 8")
    if payload["widgets_shell_status"] != "retained":
        raise LegacyInventoryValidationError("Widgets shell must remain retained")
    if payload["deletion_authorized"] is not False:
        raise LegacyInventoryValidationError("legacy deletion is not authorized")
    if not isinstance(payload["clean_windows_gate_passed"], bool):
        raise LegacyInventoryValidationError(
            "clean_windows_gate_passed must be a boolean"
        )
    raw_routes = payload["routes"]
    if not isinstance(raw_routes, list) or len(raw_routes) != len(LEGACY_ROUTE_IDS):
        raise LegacyInventoryValidationError("routes must contain all 8 legacy routes")
    route_ids: list[str] = []
    for index, raw_route in enumerate(raw_routes):
        if not isinstance(raw_route, Mapping):
            raise LegacyInventoryValidationError(f"routes[{index}] must be an object")
        route = cast(Mapping[str, object], raw_route)
        _exact_fields(route, _ROUTE_FIELDS, location=f"routes[{index}]")
        route_id = route["legacy_route_id"]
        if not isinstance(route_id, str):
            raise LegacyInventoryValidationError(
                f"routes[{index}].legacy_route_id is invalid"
            )
        route_ids.append(route_id)
        if route["panel_registration"] != route_id:
            raise LegacyInventoryValidationError(
                f"routes[{index}] panel registration does not match"
            )
        if route["status"] != "retained":
            raise LegacyInventoryValidationError(
                f"routes[{index}] must remain retained"
            )
        if (
            route["stakeholder_exit_record_id"] is not None
            or route["route_rollback_drill_id"] is not None
            or route["atomic_exit_authorized"] is not False
        ):
            raise LegacyInventoryValidationError(
                f"routes[{index}] may not pre-authorize a legacy exit"
            )
    if tuple(route_ids) != LEGACY_ROUTE_IDS:
        raise LegacyInventoryValidationError(
            "routes must contain the canonical 8 legacy route identities"
        )
    return dict(payload)


def legacy_route_inventory_sha256(payload: Mapping[str, object]) -> str:
    """Return a deterministic SHA-256 identity for a validated inventory."""

    validated = validate_legacy_route_inventory(payload)
    canonical = json.dumps(
        validated,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"
