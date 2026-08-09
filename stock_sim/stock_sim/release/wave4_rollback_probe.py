"""Source-level probes for the Issue #117 reversible rollback seam.

These probes never claim an installed-binary gate.  They exercise the retained
Widgets source entry and authoritative application reopen on a supported data
copy, returning only stable identities and hashes rather than data payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import cast

from stock_sim.release.frontend_widgets_rollback_entry import (
    READ_ONLY_ROLLBACK_PANELS,
    main as widgets_rollback_main,
)
from stock_sim.release.wave4_supported_data_copy import (
    read_supported_data_copy,
)


@dataclass(frozen=True, slots=True)
class CandidateAuthoritativeRecoveryProbe:
    durable_identities: dict[str, tuple[str, ...]]
    task_handle_identities: tuple[str, ...]
    order_state_sha256: str
    order_count: int
    clean_exit: bool


@dataclass(frozen=True, slots=True)
class RetainedWidgetsSourceProbe:
    source_commit: str
    opened_panels: tuple[str, ...]
    placeholder_panels: tuple[str, ...]
    manual_trading_action_count: int
    supported_data_copy_verified: bool
    durable_identities: dict[str, tuple[str, ...]]
    task_handle_identities: tuple[str, ...]
    order_state_sha256: str
    order_count: int
    report_sha256: str
    clean_exit: bool


def run_candidate_authoritative_recovery_probe(
    *,
    bundle_root: Path,
    campaign_id: str,
    evidence_package_id: str,
    selected_manifest_id: str,
    diagnostic_task_id: str,
) -> CandidateAuthoritativeRecoveryProbe:
    """Reopen accepted identities through the public application boundary."""

    snapshot = read_supported_data_copy(
        bundle_root=bundle_root,
        campaign_id=campaign_id,
        evidence_package_id=evidence_package_id,
        selected_manifest_id=selected_manifest_id,
        diagnostic_task_id=diagnostic_task_id,
    )
    return CandidateAuthoritativeRecoveryProbe(
        durable_identities=snapshot.durable_identities,
        task_handle_identities=snapshot.task_handle_identities,
        order_state_sha256=snapshot.order_state_sha256,
        order_count=snapshot.order_count,
        clean_exit=snapshot.clean_exit,
    )


def run_retained_widgets_source_probe(
    *,
    report_directory: Path,
    source_commit: str,
    bundle_root: Path,
    campaign_id: str,
    evidence_package_id: str,
    selected_manifest_id: str,
    diagnostic_task_id: str,
) -> RetainedWidgetsSourceProbe:
    """Run the real retained Widgets source entry without claiming a binary gate."""

    exit_code = widgets_rollback_main(
        (
            "--smoke-report-dir",
            str(report_directory),
            "--source-commit",
            source_commit,
            "--supported-data-copy",
            str(bundle_root),
            "--campaign-id",
            campaign_id,
            "--evidence-package-id",
            evidence_package_id,
            "--selected-manifest-id",
            selected_manifest_id,
            "--diagnostic-task-id",
            diagnostic_task_id,
        )
    )
    report_path = report_directory / "smoke-report.json"
    try:
        report_bytes = report_path.read_bytes()
        raw_report = json.loads(report_bytes.decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise RuntimeError("retained Widgets source report is unreadable") from exc
    if not isinstance(raw_report, dict):
        raise RuntimeError("retained Widgets source report is invalid")
    report = cast(dict[str, object], raw_report)
    raw_opened_panels = report.get("opened_panels")
    raw_placeholder_panels = report.get("placeholder_panels")
    if not isinstance(raw_opened_panels, list) or not isinstance(
        raw_placeholder_panels, list
    ):
        raise RuntimeError("retained Widgets panel evidence is invalid")
    opened_panels = tuple(str(value) for value in raw_opened_panels)
    placeholder_panels = tuple(
        str(value) for value in raw_placeholder_panels
    )
    manual_action_count = report.get("manual_trading_action_count")
    copy_verified = report.get("supported_data_copy_verified") is True
    raw_identities = report.get("durable_identities")
    raw_task_handles = report.get("task_handle_identities")
    order_state_sha256 = report.get("order_state_sha256")
    order_count = report.get("order_count")
    clean_exit = exit_code == 0 and report.get("clean_exit") is True
    if report.get("source_commit") != source_commit:
        raise RuntimeError("retained Widgets source commit identity changed")
    if set(opened_panels) != set(READ_ONLY_ROLLBACK_PANELS):
        raise RuntimeError("retained Widgets did not open every legacy panel")
    if placeholder_panels:
        raise RuntimeError("retained Widgets used a placeholder panel")
    if (
        isinstance(manual_action_count, bool)
        or not isinstance(manual_action_count, int)
        or manual_action_count != 0
    ):
        raise RuntimeError("retained Widgets exposed a manual-trading action")
    if not clean_exit:
        raise RuntimeError("retained Widgets source probe did not cleanly exit")
    if not copy_verified or not isinstance(raw_identities, dict):
        raise RuntimeError("retained Widgets did not read the supported data copy")
    durable_identities = {
        str(kind): tuple(str(identity) for identity in cast(list[object], values))
        for kind, values in raw_identities.items()
        if isinstance(values, list)
    }
    if len(durable_identities) != len(raw_identities):
        raise RuntimeError("retained Widgets artifact identities are invalid")
    if not isinstance(raw_task_handles, list) or not raw_task_handles:
        raise RuntimeError("retained Widgets TaskHandle identities are invalid")
    if not isinstance(order_state_sha256, str):
        raise RuntimeError("retained Widgets order-state hash is invalid")
    if isinstance(order_count, bool) or not isinstance(order_count, int):
        raise RuntimeError("retained Widgets order count is invalid")
    return RetainedWidgetsSourceProbe(
        source_commit=source_commit,
        opened_panels=opened_panels,
        placeholder_panels=placeholder_panels,
        manual_trading_action_count=manual_action_count,
        supported_data_copy_verified=True,
        durable_identities=durable_identities,
        task_handle_identities=tuple(str(value) for value in raw_task_handles),
        order_state_sha256=order_state_sha256,
        order_count=order_count,
        report_sha256=f"sha256:{hashlib.sha256(report_bytes).hexdigest()}",
        clean_exit=True,
    )
