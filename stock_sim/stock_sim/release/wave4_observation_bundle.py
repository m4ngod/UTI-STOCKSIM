"""Cross-validator for Issue #117 ledger, rollback, and legacy evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from stock_sim.release.wave4_legacy_inventory import (
    legacy_route_inventory_sha256,
    validate_legacy_route_inventory,
)
from stock_sim.release.wave4_observation_ledger import (
    DailyLedgerAssessment,
    assess_daily_observation_ledger,
    validate_daily_observation_ledger,
)
from stock_sim.release.wave4_rollback_evidence import (
    validate_rollback_drill_evidence,
)


class ObservationBundleValidationError(ValueError):
    """Raised when individually valid Issue #117 evidence does not agree."""


@dataclass(frozen=True, slots=True)
class ObservationBundleAssessment:
    daily_assessments: tuple[DailyLedgerAssessment, ...]
    rollback_execution_mode: str
    installed_binary_gate_verified: bool
    legacy_route_count: int


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value)


def _artifact_identity(value: object) -> tuple[object, ...]:
    artifact = _mapping(value)
    return (
        artifact["kind"],
        artifact["source_commit"],
        artifact["dependency_lock_sha256"],
        artifact["artifact_sha256"],
        artifact["package_id"],
        artifact["build_id"],
    )


def validate_observation_bundle(
    *,
    daily_ledgers: list[Mapping[str, object]],
    rollback_evidence: Mapping[str, object],
    legacy_inventory: Mapping[str, object],
) -> ObservationBundleAssessment:
    """Cross-check all passive #117 evidence without executing remediation."""

    if not daily_ledgers:
        raise ObservationBundleValidationError(
            "observation bundle requires at least one daily ledger"
        )
    rollback = validate_rollback_drill_evidence(rollback_evidence)
    inventory = validate_legacy_route_inventory(legacy_inventory)
    inventory_sha256 = legacy_route_inventory_sha256(inventory)
    candidate_identity = _artifact_identity(rollback["candidate_artifact"])
    widgets_identity = _artifact_identity(rollback["retained_widgets_artifact"])
    inventory_source_commit = inventory["source_commit"]
    if candidate_identity[1] != inventory_source_commit:
        raise ObservationBundleValidationError(
            "legacy inventory source does not match rollback artifacts"
        )

    assessments: list[DailyLedgerAssessment] = []
    for payload in daily_ledgers:
        ledger = validate_daily_observation_ledger(payload)
        artifacts = _mapping(ledger["artifacts"])
        if _artifact_identity(artifacts["candidate"]) != candidate_identity:
            raise ObservationBundleValidationError(
                "daily ledger candidate artifact does not match rollback evidence"
            )
        if _artifact_identity(artifacts["retained_widgets"]) != widgets_identity:
            raise ObservationBundleValidationError(
                "daily ledger retained Widgets artifact does not match "
                "rollback evidence"
            )
        inventory_reference = _mapping(ledger["legacy_inventory"])
        if (
            inventory_reference["inventory_id"] != inventory["inventory_id"]
            or inventory_reference["inventory_sha256"] != inventory_sha256
            or inventory_reference["legacy_route_count"]
            != inventory["legacy_route_count"]
        ):
            raise ObservationBundleValidationError(
                "daily ledger legacy inventory reference does not match"
            )
        assessments.append(assess_daily_observation_ledger(ledger))

    return ObservationBundleAssessment(
        daily_assessments=tuple(assessments),
        rollback_execution_mode=cast(str, rollback["execution_mode"]),
        installed_binary_gate_verified=cast(
            bool, rollback["installed_binary_gate_verified"]
        ),
        legacy_route_count=cast(int, inventory["legacy_route_count"]),
    )
