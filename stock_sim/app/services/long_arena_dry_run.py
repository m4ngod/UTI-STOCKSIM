from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Callable
import uuid

from app.services.evidence_board_service import build_evidence_board
from app.services.series_evidence_aggregate import SeriesEvidenceAggregate


class LongArenaDryRunRunner:
    """Run/package a multi-generation Arena dry run with evidence status."""

    def __init__(self, *, output_root: str | Path = "output/evidence_artifacts"):
        self.output_root = Path(output_root)

    def run(
        self,
        *,
        run_series: Callable[..., dict[str, Any]],
        config: dict[str, Any] | None = None,
        candidate_evidence: list[dict[str, Any]] | None = None,
        dry_run_id: str | None = None,
        generations: int = 3,
        min_generation_count: int = 2,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        requested_generations = max(1, int(generations or 1))
        min_required_generations = max(1, int(min_generation_count or 1))
        run_started_at = created_at or _utc_now()
        series_report = dict(run_series(config or {}, generations=requested_generations))
        series_id = str(series_report.get("series_id") or dry_run_id or f"arena-series-{uuid.uuid4().hex[:8]}")
        aggregate = SeriesEvidenceAggregate(output_root=self.output_root).aggregate(
            series_id=series_id,
            candidates=list(candidate_evidence or []),
            created_at=run_started_at,
        )
        evidence_board = build_evidence_board(aggregate)
        package = self._build_package(
            dry_run_id=dry_run_id or f"long-arena-dry-run-{uuid.uuid4().hex[:8]}",
            created_at=run_started_at,
            requested_generations=requested_generations,
            min_generation_count=min_required_generations,
            series_report=series_report,
            series_evidence_aggregate=aggregate,
            evidence_board=evidence_board,
        )
        path = self._package_path(package)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json_dumps(package), encoding="utf-8")
        return {**package, "package_path": str(path)}

    def _build_package(
        self,
        *,
        dry_run_id: str,
        created_at: str,
        requested_generations: int,
        min_generation_count: int,
        series_report: dict[str, Any],
        series_evidence_aggregate: dict[str, Any],
        evidence_board: dict[str, Any],
    ) -> dict[str, Any]:
        generation_count = _generation_count(series_report)
        gate_review = _gate_review(series_evidence_aggregate)
        package_complete = _package_complete(
            generation_count=generation_count,
            min_generation_count=min_generation_count,
            aggregate=series_evidence_aggregate,
        )
        package = {
            "record_kind": "long_arena_dry_run_package_v1",
            "schema_version": "1",
            "created_at": created_at,
            "dry_run_id": str(dry_run_id or ""),
            "source_task": "Task 101: Long Arena Dry Run",
            "run_policy": {
                "requested_generations": requested_generations,
                "min_generation_count": min_generation_count,
                "actual_generation_count": generation_count,
            },
            "arena_series_report": _series_report_summary(series_report),
            "series_evidence_aggregate": _strip_paths(series_evidence_aggregate),
            "evidence_board": evidence_board,
            "gate_review": gate_review,
            "status": "complete" if package_complete else "incomplete",
            "go_no_go": "go" if package_complete and gate_review["parent_eligible_candidate_count"] > 0 else "no_go",
            "failure_reasons": _failure_reasons(
                generation_count=generation_count,
                min_generation_count=min_generation_count,
                aggregate=series_evidence_aggregate,
                gate_review=gate_review,
            ),
        }
        package["package_hash"] = _package_hash(package)
        return package

    def _package_path(self, package: dict[str, Any]) -> Path:
        dry_run_id = _safe_path_part(package.get("dry_run_id") or "long-arena-dry-run")
        package_hash = str(package.get("package_hash") or _package_hash(package))
        return self.output_root / "long_arena_dry_run_package_v1" / f"{dry_run_id}-{package_hash[:16]}.json"


def _series_report_summary(report: dict[str, Any]) -> dict[str, Any]:
    reports = report.get("reports") if isinstance(report.get("reports"), list) else []
    summary = {
        "schema": report.get("schema"),
        "series_id": report.get("series_id"),
        "generation_count": _generation_count(report),
        "report_path": report.get("report_path"),
        "report_hash": _payload_hash(report),
        "generation_report_hashes": [_payload_hash(item) for item in reports if isinstance(item, dict)],
        "aggregate": report.get("aggregate") if isinstance(report.get("aggregate"), dict) else {},
    }
    if isinstance(report.get("runtime_evidence"), dict):
        summary["runtime_evidence"] = dict(report.get("runtime_evidence") or {})
    return summary


def _generation_count(report: dict[str, Any]) -> int:
    raw = report.get("generation_count")
    try:
        if int(raw) > 0:
            return int(raw)
    except Exception:
        pass
    generations = report.get("generations") if isinstance(report.get("generations"), list) else []
    reports = report.get("reports") if isinstance(report.get("reports"), list) else []
    return max(len(generations), len(reports))


def _package_complete(*, generation_count: int, min_generation_count: int, aggregate: dict[str, Any]) -> bool:
    status_counts = aggregate.get("status_counts") if isinstance(aggregate.get("status_counts"), dict) else {}
    return (
        generation_count >= min_generation_count
        and int(aggregate.get("candidate_count") or 0) > 0
        and int(status_counts.get("missing") or 0) == 0
        and int(status_counts.get("not_available") or 0) == 0
    )


def _gate_review(aggregate: dict[str, Any]) -> dict[str, Any]:
    summaries = aggregate.get("candidate_summaries") if isinstance(aggregate.get("candidate_summaries"), list) else []
    parent_eligible = [
        str(item.get("candidate_id") or "")
        for item in summaries
        if isinstance(item, dict) and item.get("parent_eligible")
    ]
    research_accepted = [
        str(item.get("candidate_id") or "")
        for item in summaries
        if isinstance(item, dict) and item.get("research_accepted")
    ]
    failed = [
        str(item.get("candidate_id") or "")
        for item in summaries
        if isinstance(item, dict) and item.get("overall_status") != "pass"
    ]
    return {
        "candidate_count": len(summaries),
        "parent_eligible_candidates": parent_eligible,
        "parent_eligible_candidate_count": len(parent_eligible),
        "research_accepted_candidates": research_accepted,
        "research_accepted_candidate_count": len(research_accepted),
        "blocked_candidates": failed,
    }


def _failure_reasons(
    *,
    generation_count: int,
    min_generation_count: int,
    aggregate: dict[str, Any],
    gate_review: dict[str, Any],
) -> list[str]:
    reasons = []
    if generation_count < min_generation_count:
        reasons.append("long_arena_generation_count_below_minimum")
    if int(aggregate.get("candidate_count") or 0) <= 0:
        reasons.append("missing_series_candidates")
    status_counts = aggregate.get("status_counts") if isinstance(aggregate.get("status_counts"), dict) else {}
    if int(status_counts.get("fail") or 0) > 0:
        reasons.append("evidence_package_has_failed_evidence")
    if int(status_counts.get("missing") or 0) > 0:
        reasons.append("evidence_package_has_missing_evidence")
    if int(status_counts.get("not_available") or 0) > 0:
        reasons.append("evidence_package_has_not_available_evidence")
    if gate_review.get("parent_eligible_candidate_count") == 0:
        reasons.append("no_candidate_passed_parent_gate")
    reasons.extend(str(item) for item in aggregate.get("failure_reasons") or [])
    return _dedupe(reasons)


def _strip_paths(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in {"record_path", "package_path"}}


def _package_hash(package: dict[str, Any]) -> str:
    payload = {key: value for key, value in package.items() if key not in {"package_hash", "package_path"}}
    return _payload_hash(payload)


def _payload_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"


def _safe_path_part(value: Any) -> str:
    text = str(value or "long-arena-dry-run").strip() or "long-arena-dry-run"
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


__all__ = ["LongArenaDryRunRunner"]
