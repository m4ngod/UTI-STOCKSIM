from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any


REQUIRED_RESEARCH_EVIDENCE_HASHES = [
    "checkpoint_hash",
    "lineage_evidence",
    "baseline_artifact",
    "calibration_artifact",
    "hidden_eval_artifact",
    "exploit_test_artifact",
    "paired_sensitivity_artifact",
]

LIVE_RUNTIME_SOURCE = "live_postgresql_runtime"
MAX_OPEN_ACCEPTANCE_LEVEL = "level_1_engineering_acceptance"
ACCEPTANCE_LEVELS = {
    "level_1_engineering_acceptance",
    "level_2_sim_research_acceptance",
    "level_3_transfer_acceptance",
}


class ResearchAcceptanceLockV2:
    """Lock research claims unless parent-gate evidence allows research use."""

    def __init__(self, *, output_root: str | Path = "output/evidence_artifacts"):
        self.output_root = Path(output_root)

    def evaluate(
        self,
        *,
        candidate_id: str,
        claim_text: str,
        parent_gate_artifact: dict[str, Any],
        acceptance_level: str = MAX_OPEN_ACCEPTANCE_LEVEL,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        gate = dict(parent_gate_artifact or {})
        evidence_hashes = dict(gate.get("evidence_hashes") or {})
        required = dict(gate.get("required") or {})
        missing_hashes = [
            name
            for name in REQUIRED_RESEARCH_EVIDENCE_HASHES
            if not evidence_hashes.get(name)
        ]
        required_failures = [
            str(name)
            for name, passed in required.items()
            if passed is not True
        ]
        failure_reasons = []
        if not str(candidate_id or "").strip():
            failure_reasons.append("missing_candidate_id")
        if not str(claim_text or "").strip():
            failure_reasons.append("missing_research_claim_text")
        if gate.get("artifact_kind") != "parent_gate_artifact_v2":
            failure_reasons.append("missing_parent_gate_artifact_v2")
        level = str(acceptance_level or "").strip()
        parent_gate_passed = gate.get("pass_gate") is True
        if not parent_gate_passed:
            failure_reasons.append("parent_gate_artifact_not_passed")
        requires_research_claim = level != MAX_OPEN_ACCEPTANCE_LEVEL
        if parent_gate_passed and requires_research_claim and not gate.get("eligible_for_research_claim"):
            failure_reasons.append("parent_gate_research_claim_not_eligible")
        if str(gate.get("source") or "") != LIVE_RUNTIME_SOURCE:
            failure_reasons.append("parent_gate_not_live_runtime_source")
        if not gate.get("artifact_hash"):
            failure_reasons.append("missing_parent_gate_artifact_hash")
        if level not in ACCEPTANCE_LEVELS:
            failure_reasons.append("unknown_acceptance_level")
        elif level != MAX_OPEN_ACCEPTANCE_LEVEL:
            failure_reasons.append(f"acceptance_level_not_supported:{level}")
        if required_failures:
            failure_reasons.extend(f"required_evidence_failed:{name}" for name in required_failures)
        if missing_hashes:
            failure_reasons.extend(f"missing_evidence_hash:{name}" for name in missing_hashes)
        failure_reasons = _dedupe(failure_reasons)

        record = {
            "record_kind": "research_acceptance_lock_v2",
            "schema_version": "2",
            "created_at": created_at or _utc_now(),
            "candidate_id": str(candidate_id or ""),
            "claim_text": str(claim_text or ""),
            "acceptance_level": level,
            "source": LIVE_RUNTIME_SOURCE,
            "source_run_ids": list(gate.get("source_run_ids") or []),
            "runner_name": "research_acceptance_lock_v2",
            "runner_version": "v2",
            "parent_gate_artifact_id": gate.get("artifact_id"),
            "parent_gate_artifact_hash": gate.get("artifact_hash"),
            "parent_gate_pass_gate": gate.get("pass_gate") is True,
            "eligible_for_research_claim": bool(gate.get("eligible_for_research_claim")),
            "required_evidence": required,
            "required_evidence_hashes": {
                name: evidence_hashes.get(name)
                for name in REQUIRED_RESEARCH_EVIDENCE_HASHES
            },
            "status": "open" if not failure_reasons else "locked",
            "is_research_accepted": not failure_reasons,
            "pass_gate": not failure_reasons,
            "failure_type": "none" if not failure_reasons else "upstream_blocked",
            "blocking_sections": list(failure_reasons),
            "next_action": "No action required." if not failure_reasons else "Blocking sections non-empty; keep locked.",
            "failure_reasons": failure_reasons,
        }
        record["lock_hash"] = _lock_hash(record)
        path = self._record_path(record)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json_dumps(record), encoding="utf-8")
        return {**record, "record_path": str(path)}

    def _record_path(self, record: dict[str, Any]) -> Path:
        lock_hash = str(record.get("lock_hash") or _lock_hash(record))
        candidate_id = _safe_path_part(record.get("candidate_id") or "candidate")
        return self.output_root / "research_acceptance_lock_v2" / f"{candidate_id}-{lock_hash[:16]}.json"


def _lock_hash(record: dict[str, Any]) -> str:
    payload = {key: value for key, value in record.items() if key not in {"lock_hash", "record_path"}}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n"


def _safe_path_part(value: Any) -> str:
    text = str(value or "candidate").strip() or "candidate"
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
    "ACCEPTANCE_LEVELS",
    "MAX_OPEN_ACCEPTANCE_LEVEL",
    "REQUIRED_RESEARCH_EVIDENCE_HASHES",
    "ResearchAcceptanceLockV2",
]
