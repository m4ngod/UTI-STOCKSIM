"""Read-only identity snapshot for a supported Wave 3/Wave 4 data copy."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Final, cast

from sqlalchemy import Engine, text

from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
    reopen_completed_wave2_release_fixture,
)
from stock_sim.release.wave4_rollback_evidence import READABLE_ARTIFACT_KINDS


_ORDER_STATE_QUERY: Final = (
    "SELECT order_id, run_id, instrument, shares, decision_time, "
    "activation_time, status, rejection_reason "
    "FROM diagnostic_run_orders ORDER BY order_id"
)


@dataclass(frozen=True, slots=True)
class SupportedDataCopySnapshot:
    durable_identities: dict[str, tuple[str, ...]]
    task_handle_identities: tuple[str, ...]
    order_state_sha256: str
    order_count: int
    clean_exit: bool


def _order_state_identity(engine: Engine) -> tuple[str, int]:
    """Hash all simulated order rows without returning their payload."""

    with engine.connect() as connection:
        rows = tuple(
            dict(row)
            for row in connection.execute(text(_ORDER_STATE_QUERY)).mappings()
        )
    canonical = json.dumps(
        rows,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}", len(rows)


def read_supported_data_copy(
    *,
    bundle_root: Path,
    campaign_id: str,
    evidence_package_id: str,
    selected_manifest_id: str,
    diagnostic_task_id: str,
) -> SupportedDataCopySnapshot:
    """Read accepted identities through the public application boundary."""

    fixture = reopen_completed_wave2_release_fixture(
        bundle_root=bundle_root,
        campaign_id=campaign_id,
        evidence_package_id=evidence_package_id,
        selected_manifest_id=selected_manifest_id,
    )
    try:
        task = fixture.application.get_diagnostic_task(diagnostic_task_id)
        if task is None or task.task_id != diagnostic_task_id:
            raise RuntimeError("accepted Diagnostic Task identity did not reopen")
        sealed_payload = fixture.evidence_package.sealed_payload()
        raw_findings = sealed_payload.get("diagnostic_findings")
        if not isinstance(raw_findings, list) or not raw_findings:
            raise RuntimeError("accepted Finding identities did not reopen")
        finding_identities = tuple(
            sorted(
                str(cast(dict[str, object], item)["finding_id"])
                for item in raw_findings
                if isinstance(item, dict)
            )
        )
        if not finding_identities or len(finding_identities) != len(raw_findings):
            raise RuntimeError("accepted Finding identities are incomplete")
        identities = {
            "Strategy": (fixture.selected_run.specification.strategy_id,),
            "Recipe": (fixture.selected_run.specification.recipe_version_id,),
            "Task": (task.task_id,),
            "Campaign": (fixture.campaign.campaign_id,),
            "Run": (fixture.selected_run.run_id,),
            "Evidence": (fixture.evidence_package.evidence_package_id,),
            "Finding": finding_identities,
            "Manifest": (fixture.selected_manifest.manifest_id,),
        }
        if tuple(identities) != READABLE_ARTIFACT_KINDS:
            raise RuntimeError("rollback artifact identity coverage is incomplete")
        task_handles = tuple(
            handle.task_handle_id for handle in task.task_handles
        )
        if not task_handles or len(task_handles) != len(set(task_handles)):
            raise RuntimeError("TaskHandle identities are missing or duplicated")
        order_state_sha256, order_count = _order_state_identity(fixture.engine)
    finally:
        fixture.close()
    if not fixture.closed:
        raise RuntimeError("supported data-copy reader did not cleanly exit")
    return SupportedDataCopySnapshot(
        durable_identities=identities,
        task_handle_identities=task_handles,
        order_state_sha256=order_state_sha256,
        order_count=order_count,
        clean_exit=True,
    )
