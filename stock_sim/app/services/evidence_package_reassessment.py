from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.long_arena_dry_run import LongArenaDryRunRunner
from app.services.series_evidence_aggregate import REQUIRED_SERIES_EVIDENCE


class EvidencePackageReassessmentRunner:
    """Recompute a saved long Arena evidence package under the current strict contract."""

    def __init__(self, *, output_root: str | Path = "output/evidence_artifacts"):
        self.output_root = Path(output_root)

    def reassess_package(
        self,
        package_path: str | Path,
        *,
        dry_run_id: str | None = None,
        created_at: str | None = None,
        min_generation_count: int | None = None,
    ) -> dict[str, Any]:
        package = _load_json(Path(package_path))
        artifact_index = self._artifact_index()
        candidate_evidence = [
            _candidate_from_summary(summary, artifact_index)
            for summary in _candidate_summaries(package)
        ]
        generation_count = _generation_count(package)
        runner = LongArenaDryRunRunner(output_root=self.output_root)
        return runner.run(
            run_series=lambda config, generations: _series_report(package, generation_count),
            candidate_evidence=candidate_evidence,
            dry_run_id=dry_run_id or f"{_safe_part(package.get('dry_run_id') or 'package')}-strict-recomputed",
            generations=generation_count,
            min_generation_count=min_generation_count or _min_generation_count(package) or generation_count,
            created_at=created_at,
        )

    def _artifact_index(self) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        if not self.output_root.exists():
            return index
        for path in self.output_root.rglob("*.json"):
            try:
                payload = _load_json(path)
            except Exception:
                continue
            for key in ("artifact_hash", "lock_hash", "aggregate_hash", "checkpoint_hash", "hash"):
                value = payload.get(key) if isinstance(payload, dict) else None
                if value:
                    item = dict(payload)
                    item.setdefault("artifact_path", str(path))
                    index[str(value)] = item
        return index


def _candidate_summaries(package: dict[str, Any]) -> list[dict[str, Any]]:
    aggregate = package.get("series_evidence_aggregate") if isinstance(package.get("series_evidence_aggregate"), dict) else {}
    summaries = aggregate.get("candidate_summaries") if isinstance(aggregate.get("candidate_summaries"), list) else []
    return [dict(item) for item in summaries if isinstance(item, dict)]


def _candidate_from_summary(summary: dict[str, Any], artifact_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    evidence_hashes = summary.get("evidence_hashes") if isinstance(summary.get("evidence_hashes"), dict) else {}
    candidate = {
        "candidate_id": str(summary.get("candidate_id") or ""),
        "checkpoint_hash": str(summary.get("checkpoint_hash") or ""),
    }
    for name in REQUIRED_SERIES_EVIDENCE:
        evidence_hash = evidence_hashes.get(name)
        candidate[name] = artifact_index.get(str(evidence_hash)) if evidence_hash else None
    return candidate


def _series_report(package: dict[str, Any], generation_count: int) -> dict[str, Any]:
    arena = package.get("arena_series_report") if isinstance(package.get("arena_series_report"), dict) else {}
    return {
        "schema": "strict_recomputed_package_reassessment_v1",
        "series_id": str(arena.get("series_id") or (package.get("dry_run_id") or "strict-recomputed-series")),
        "generation_count": generation_count,
        "reports": [
            {"generation": index + 1, "source_package_hash": package.get("package_hash")}
            for index in range(max(0, generation_count))
        ],
        "runtime_evidence": dict(arena.get("runtime_evidence") or {}),
        "aggregate": dict(arena.get("aggregate") or {}),
    }


def _generation_count(package: dict[str, Any]) -> int:
    run_policy = package.get("run_policy") if isinstance(package.get("run_policy"), dict) else {}
    arena = package.get("arena_series_report") if isinstance(package.get("arena_series_report"), dict) else {}
    for value in (run_policy.get("actual_generation_count"), arena.get("generation_count")):
        try:
            parsed = int(value)
            if parsed > 0:
                return parsed
        except Exception:
            continue
    return 1


def _min_generation_count(package: dict[str, Any]) -> int:
    run_policy = package.get("run_policy") if isinstance(package.get("run_policy"), dict) else {}
    try:
        return max(1, int(run_policy.get("min_generation_count") or 0))
    except Exception:
        return 0


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _safe_part(value: Any) -> str:
    text = str(value or "package").strip() or "package"
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)


__all__ = ["EvidencePackageReassessmentRunner"]
