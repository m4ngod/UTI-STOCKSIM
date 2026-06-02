from __future__ import annotations

from typing import Any


BOARD_EVIDENCE_COLUMNS = [
    "baseline",
    "calibration",
    "hidden",
    "exploit",
    "fee_impact_sensitivity",
    "parent_eligible",
    "research_claim_eligible",
]


def build_evidence_board(series_evidence_aggregate: dict[str, Any] | None) -> dict[str, Any]:
    aggregate = series_evidence_aggregate if isinstance(series_evidence_aggregate, dict) else {}
    candidate_summaries = list(aggregate.get("candidate_summaries") or [])
    rows = [_board_row(item) for item in candidate_summaries if isinstance(item, dict)]
    status_counts = dict(aggregate.get("status_counts") or {})
    return {
        "schema": "evidence_board_view_v1",
        "status": "available" if rows else "not_available",
        "reason": None if rows else "series_evidence_aggregate_not_available",
        "go_no_go": aggregate.get("go_no_go") or "not_available",
        "candidate_count": len(rows),
        "columns": list(BOARD_EVIDENCE_COLUMNS),
        "rows": rows,
        "status_counts": status_counts,
        "blocking_candidates": list(aggregate.get("blocking_candidates") or []),
        "not_available_debt": _not_available_debt(rows),
    }


def _board_row(summary: dict[str, Any]) -> dict[str, Any]:
    evidence = summary.get("evidence_status") if isinstance(summary.get("evidence_status"), dict) else {}
    details = summary.get("evidence_details") if isinstance(summary.get("evidence_details"), dict) else {}
    row = {
        "candidate_id": str(summary.get("candidate_id") or ""),
        "checkpoint_hash": str(summary.get("checkpoint_hash") or ""),
        "return_rank": summary.get("return_rank"),
        "baseline": _status(evidence.get("baseline_artifact")),
        "calibration": _status(evidence.get("calibration_artifact")),
        "hidden": _status(evidence.get("hidden_eval_artifact")),
        "exploit": _status(evidence.get("exploit_test_artifact")),
        "fee_impact_sensitivity": _status(evidence.get("paired_sensitivity_artifact")),
        "parent_eligible": "pass" if summary.get("parent_eligible") else "fail",
        "research_claim_eligible": "pass" if summary.get("research_claim_eligible") else "fail",
        "research_accepted": "pass" if summary.get("research_accepted") else "fail",
        "overall_status": _status(summary.get("overall_status")),
        "failed_evidence": list(summary.get("failed_evidence") or []),
        "missing_evidence": list(summary.get("missing_evidence") or []),
        "not_available_evidence": list(summary.get("not_available_evidence") or []),
        "evidence_details": details,
        "failure_details": _failure_details(details),
    }
    row["blocking_reason_count"] = (
        len(row["failed_evidence"])
        + len(row["missing_evidence"])
        + len(row["not_available_evidence"])
        + (0 if row["parent_eligible"] == "pass" else 1)
        + (0 if row["research_claim_eligible"] == "pass" else 1)
    )
    return row


def _failure_details(details: dict[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for name, detail in details.items():
        if not isinstance(detail, dict):
            continue
        if _status(detail.get("status")) == "pass":
            continue
        failures.append(
            {
                "evidence": str(name),
                "status": _status(detail.get("status")),
                "failure_type": str(detail.get("failure_type") or "unknown"),
                "blocking_metrics": list(detail.get("blocking_metrics") or []),
                "next_action": str(detail.get("next_action") or ""),
                "artifact_hash": detail.get("artifact_hash"),
                "runner_version": detail.get("runner_version"),
                "source_run_ids": list(detail.get("source_run_ids") or []),
                "source": detail.get("source"),
            }
        )
    return failures


def _not_available_debt(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    debt = []
    for row in rows:
        for name in row.get("not_available_evidence") or []:
            debt.append(
                {
                    "candidate_id": row.get("candidate_id"),
                    "evidence": str(name),
                    "status": "not_available",
                    "owner": "evidence_runner",
                    "required_input": _required_input(name),
                    "blocking_reason": f"{name}_not_available",
                    "planned_task_id": _planned_task_id(name),
                    "replacement_artifact_kind": _replacement_artifact_kind(name),
                }
            )
    return debt


def _status(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"pass", "fail", "missing", "not_available", "warning"}:
        return text
    if text in {"true", "available", "present", "complete", "open"}:
        return "pass"
    if text in {"false", "locked", "rejected"}:
        return "fail"
    return "missing"


def _required_input(evidence: str) -> str:
    mapping = {
        "baseline_artifact": "baseline_artifact_v1",
        "calibration_artifact": "calibration_artifact_v1",
        "hidden_eval_artifact": "hidden_eval_artifact_v1",
        "exploit_test_artifact": "exploit_test_artifact_v1",
        "paired_sensitivity_artifact": "paired_sensitivity_artifact_v1",
        "parent_gate_artifact": "parent_gate_artifact_v2",
        "research_acceptance_lock": "research_acceptance_lock_v2",
    }
    return mapping.get(evidence, "evidence_artifact")


def _planned_task_id(evidence: str) -> str:
    mapping = {
        "baseline_artifact": "89",
        "calibration_artifact": "88",
        "hidden_eval_artifact": "93",
        "exploit_test_artifact": "95",
        "paired_sensitivity_artifact": "94",
        "parent_gate_artifact": "96",
        "research_acceptance_lock": "97",
    }
    return mapping.get(evidence, "98")


def _replacement_artifact_kind(evidence: str) -> str:
    return _required_input(evidence)


__all__ = ["BOARD_EVIDENCE_COLUMNS", "build_evidence_board"]
