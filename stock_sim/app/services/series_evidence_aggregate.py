from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any


REQUIRED_SERIES_EVIDENCE = [
    "baseline_artifact",
    "calibration_artifact",
    "hidden_eval_artifact",
    "exploit_test_artifact",
    "paired_sensitivity_artifact",
    "parent_gate_artifact",
    "research_acceptance_lock",
]

LIVE_RUNTIME_SOURCE = "live_postgresql_runtime"
INVALID_EVIDENCE_SOURCES = {
    "headless_injected",
    "injected",
    "injected_only",
    "injected_summary",
    "manual",
    "manual_override",
}
HASH_KEYS = {"artifact_hash", "lock_hash", "aggregate_hash"}
PATH_KEYS = {"artifact_path", "record_path", "package_path"}


class SeriesEvidenceAggregate:
    """Aggregate candidate evidence into pass/fail/missing/not_available series status."""

    def __init__(self, *, output_root: str | Path = "output/evidence_artifacts"):
        self.output_root = Path(output_root)

    def aggregate(
        self,
        *,
        series_id: str,
        candidates: list[dict[str, Any]],
        created_at: str | None = None,
    ) -> dict[str, Any]:
        candidate_summaries = [_candidate_evidence_summary(item) for item in (candidates or [])]
        status_counts: Counter[str] = Counter()
        evidence_status_counts: dict[str, Counter[str]] = {
            name: Counter() for name in REQUIRED_SERIES_EVIDENCE
        }
        for summary in candidate_summaries:
            for name, status in summary["evidence_status"].items():
                status_counts.update([status])
                evidence_status_counts[name].update([status])

        blocking_candidates = [
            item["candidate_id"]
            for item in candidate_summaries
            if item["overall_status"] != "pass"
        ]
        aggregate_record = {
            "record_kind": "series_evidence_aggregate_v1",
            "schema_version": "1",
            "created_at": created_at or _utc_now(),
            "series_id": str(series_id or ""),
            "candidate_count": len(candidate_summaries),
            "required_evidence": list(REQUIRED_SERIES_EVIDENCE),
            "candidate_summaries": candidate_summaries,
            "status_counts": dict(status_counts),
            "evidence_status_counts": {
                name: dict(counter)
                for name, counter in evidence_status_counts.items()
            },
            "blocking_candidates": blocking_candidates,
            "go_no_go": "go" if candidate_summaries and not blocking_candidates else "no_go",
            "failure_reasons": _aggregate_failure_reasons(candidate_summaries),
        }
        aggregate_record["aggregate_hash"] = _aggregate_hash(aggregate_record)
        path = self._record_path(aggregate_record)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json_dumps(aggregate_record), encoding="utf-8")
        return {**aggregate_record, "record_path": str(path)}

    def _record_path(self, record: dict[str, Any]) -> Path:
        series_id = _safe_path_part(record.get("series_id") or "series")
        aggregate_hash = str(record.get("aggregate_hash") or _aggregate_hash(record))
        return self.output_root / "series_evidence_aggregate_v1" / f"{series_id}-{aggregate_hash[:16]}.json"


def _candidate_evidence_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    payload = dict(candidate or {})
    evidence_details = {
        name: _evidence_detail(name, payload.get(name))
        for name in REQUIRED_SERIES_EVIDENCE
    }
    evidence_status = {name: detail["status"] for name, detail in evidence_details.items()}
    evidence_hashes = {
        name: detail["artifact_hash"]
        for name in REQUIRED_SERIES_EVIDENCE
        for detail in [evidence_details[name]]
        if detail.get("artifact_hash")
    }
    failed = [name for name, status in evidence_status.items() if status == "fail"]
    missing = [name for name, status in evidence_status.items() if status == "missing"]
    not_available = [name for name, status in evidence_status.items() if status == "not_available"]
    overall_status = "pass" if not failed and not missing and not not_available else "fail"
    parent_gate = payload.get("parent_gate_artifact") if isinstance(payload.get("parent_gate_artifact"), dict) else {}
    research_lock = payload.get("research_acceptance_lock") if isinstance(payload.get("research_acceptance_lock"), dict) else {}
    return {
        "candidate_id": str(payload.get("candidate_id") or payload.get("id") or ""),
        "checkpoint_hash": str(payload.get("checkpoint_hash") or _evidence_hash(payload.get("checkpoint")) or ""),
        "evidence_status": evidence_status,
        "evidence_details": evidence_details,
        "evidence_hashes": evidence_hashes,
        "failed_evidence": failed,
        "missing_evidence": missing,
        "not_available_evidence": not_available,
        "parent_eligible": (
            evidence_status.get("parent_gate_artifact") == "pass"
            and bool(parent_gate.get("eligible_for_pbt_parent"))
        ),
        "research_claim_eligible": (
            evidence_status.get("parent_gate_artifact") == "pass"
            and bool(parent_gate.get("eligible_for_research_claim"))
        ),
        "research_accepted": (
            evidence_status.get("research_acceptance_lock") == "pass"
            and bool(research_lock.get("is_research_accepted"))
        ),
        "overall_status": overall_status,
    }


def _evidence_status(value: Any) -> str:
    return _evidence_detail("evidence", value)["status"]


def _evidence_detail(name: str, value: Any) -> dict[str, Any]:
    if value is None:
        return _detail(
            name=name,
            status="missing",
            failure_type="missing_artifact",
            next_action=_next_action(name, "missing_artifact"),
        )
    if not isinstance(value, dict):
        value = {
            "status": getattr(value, "status", None),
            "pass_gate": getattr(value, "pass_gate", None),
            "pass_fail": getattr(value, "pass_fail", None),
            "artifact_hash": getattr(value, "artifact_hash", None),
            "source": getattr(value, "source", None),
            "runner_version": getattr(value, "runner_version", None),
        }

    explicit = str(value.get("status") or "").strip().lower()
    artifact_hash = _evidence_hash(value)
    base = {
        "artifact_hash": artifact_hash,
        "runner_version": value.get("runner_version"),
        "source_run_ids": list(value.get("source_run_ids") or []),
        "source": value.get("source"),
        "pass_gate": value.get("pass_gate"),
    }
    if explicit in {"missing", "not_available"} or value.get("available") is False:
        status = explicit if explicit in {"missing", "not_available"} else "not_available"
        failure_type = _failure_type(value, status)
        return _detail(
            name=name,
            status=status,
            failure_type=failure_type,
            blocking_metrics=_blocking_metrics(value),
            next_action=_next_action(name, failure_type),
            validation_reasons=[],
            **base,
        )

    validation_reasons = _strict_validation_reasons(value, artifact_hash)
    failure_type = _failure_type(value, validation_reasons[0] if validation_reasons else "none")
    if value.get("pass_gate") is True and not validation_reasons:
        return _detail(
            name=name,
            status="pass",
            failure_type="none",
            blocking_metrics=[],
            next_action="No action required.",
            validation_reasons=[],
            **base,
        )
    if failure_type == "none":
        failure_type = _failure_type(value, "pass_gate_false")
    return _detail(
        name=name,
        status="fail",
        failure_type=failure_type,
        blocking_metrics=_blocking_metrics(value) + validation_reasons,
        next_action=_next_action(name, failure_type),
        validation_reasons=validation_reasons,
        **base,
    )


def _detail(
    *,
    name: str,
    status: str,
    failure_type: str,
    blocking_metrics: list[str] | None = None,
    next_action: str | None = None,
    artifact_hash: str | None = None,
    runner_version: Any = None,
    source_run_ids: list[Any] | None = None,
    source: Any = None,
    pass_gate: Any = None,
    validation_reasons: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "evidence_name": name,
        "status": status,
        "failure_type": failure_type,
        "blocking_metrics": [str(item) for item in (blocking_metrics or [])],
        "next_action": next_action or _next_action(name, failure_type),
        "artifact_hash": artifact_hash,
        "runner_version": runner_version,
        "source_run_ids": [str(item) for item in (source_run_ids or [])],
        "source": source,
        "pass_gate": pass_gate,
        "validation_reasons": [str(item) for item in (validation_reasons or [])],
    }


def _strict_validation_reasons(value: dict[str, Any], artifact_hash: str | None) -> list[str]:
    reasons: list[str] = []
    source = str(value.get("source") or "").strip()
    if not source:
        reasons.append("missing_live_runtime_source")
    elif source in INVALID_EVIDENCE_SOURCES:
        reasons.append("invalid_source")
    elif source != LIVE_RUNTIME_SOURCE:
        reasons.append("non_live_runtime_source")
    if not str(value.get("runner_version") or "").strip():
        reasons.append("missing_runner_version")
    if not artifact_hash:
        reasons.append("missing_artifact_hash")
    elif not _hash_matches(value, artifact_hash):
        reasons.append("hash_mismatch")
    if "pass_gate" not in value:
        reasons.append("missing_pass_gate")
    return _dedupe(reasons)


def _hash_matches(value: dict[str, Any], artifact_hash: str) -> bool:
    key = _hash_key(value)
    if not key:
        return False
    payload = {
        item_key: item_value
        for item_key, item_value in value.items()
        if item_key not in HASH_KEYS and item_key not in PATH_KEYS
    }
    expected = _canonical_sha256(payload)
    return expected == artifact_hash


def _hash_key(value: dict[str, Any]) -> str | None:
    for key in ("artifact_hash", "lock_hash", "aggregate_hash"):
        if value.get(key):
            return key
    return None


def _failure_type(value: dict[str, Any], reason: str) -> str:
    explicit = str(value.get("failure_type") or "").strip()
    if explicit and explicit != "none":
        return explicit
    text = str(reason or "").lower()
    if "source" in text:
        return "invalid_source"
    if "hash" in text:
        return "hash_validation_failed"
    if "pass_gate" in text:
        return "gate_not_passed"
    if "missing" in text:
        return "missing_metric"
    if "underperform" in text or "baseline" in text:
        return "underperform_baseline"
    if "severe" in text or "exploit" in text:
        return "severe_flag"
    if "parent" in text or "upstream" in text or "locked" in text:
        return "upstream_blocked"
    return "none" if text == "none" else "gate_not_passed"


def _blocking_metrics(value: dict[str, Any]) -> list[str]:
    metrics: list[str] = []
    for key in (
        "blocking_metrics",
        "missing_metrics",
        "failed_metrics",
        "severe_flags",
        "blocking_sections",
        "failure_reasons",
        "missing_required_baseline_kinds",
    ):
        item = value.get(key)
        if isinstance(item, list):
            metrics.extend(str(entry) for entry in item)
        elif item:
            metrics.append(str(item))
    return _dedupe(metrics)


def _next_action(name: str, failure_type: str) -> str:
    mapping = {
        "calibration_artifact": "Add target band or fix missing runtime metric source.",
        "hidden_eval_artifact": "Candidate underperformed TWAP/VWAP/AC-lite; keep fail and improve candidate/reward/action space.",
        "exploit_test_artifact": "Complete missing probe metrics: timestamp, mark-to-market, order-boundary, fee-accounting, fill-rule, clock-boundary.",
        "paired_sensitivity_artifact": "Run base/high_fee/high_impact/low_liquidity paired worlds with same seed.",
        "parent_gate_artifact": "Upstream evidence still blocking; do not override.",
        "research_acceptance_lock": "Blocking sections non-empty; keep locked.",
        "baseline_artifact": "Complete live baseline suite and preserve strong baselines.",
    }
    if failure_type == "missing_artifact":
        return f"Generate {name} from live PostgreSQL/runtime evidence."
    return mapping.get(name, "Recompute artifact from live PostgreSQL/runtime facts.")


def _evidence_hash(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("artifact_hash", "lock_hash", "aggregate_hash", "checkpoint_hash", "hash"):
            if value.get(key):
                return str(value.get(key))
    for attr in ("artifact_hash", "lock_hash", "aggregate_hash", "checkpoint_hash", "hash"):
        item = getattr(value, attr, None)
        if item:
            return str(item)
    return None


def _aggregate_failure_reasons(candidate_summaries: list[dict[str, Any]]) -> list[str]:
    if not candidate_summaries:
        return ["missing_series_candidates"]
    reasons = []
    for item in candidate_summaries:
        candidate_id = item.get("candidate_id") or "candidate"
        for name in item.get("failed_evidence") or []:
            reasons.append(f"{candidate_id}:{name}:fail")
        for name in item.get("missing_evidence") or []:
            reasons.append(f"{candidate_id}:{name}:missing")
        for name in item.get("not_available_evidence") or []:
            reasons.append(f"{candidate_id}:{name}:not_available")
    return reasons


def _aggregate_hash(record: dict[str, Any]) -> str:
    payload = {key: value for key, value in record.items() if key not in {"aggregate_hash", "record_path"}}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"


def _safe_path_part(value: Any) -> str:
    text = str(value or "series").strip() or "series"
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


__all__ = [
    "LIVE_RUNTIME_SOURCE",
    "REQUIRED_SERIES_EVIDENCE",
    "SeriesEvidenceAggregate",
]
