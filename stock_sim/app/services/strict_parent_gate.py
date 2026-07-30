from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.services.evidence_artifact_writer import EvidenceArtifactWriter

LIVE_RUNTIME_SOURCE = "live_postgresql_runtime"
INVALID_EVIDENCE_SOURCES = {
    "headless_injected",
    "injected",
    "injected_only",
    "injected_summary",
    "manual",
    "manual_override",
}

REQUIRED_PARENT_GATE_EVIDENCE = [
    "experiment_record_completeness",
    "checkpoint_hash",
    "training_world_hashes",
    "evaluation_world_hashes",
    "reward_contract_hash",
    "action_contract_hash",
    "observation_contract_hash",
    "code_version_or_runner_version",
    "lineage_evidence",
    "baseline_artifact",
    "calibration_artifact",
    "hidden_eval_artifact",
    "exploit_test_artifact",
    "paired_sensitivity_artifact",
]


class StrictParentGateV2:
    """Evidence-gated parent eligibility split into parent, promotion, and research claim decisions."""

    def __init__(self, *, artifact_root: str | Path = "output/evidence_artifacts"):
        self._writer = EvidenceArtifactWriter(artifact_root)

    def evaluate(
        self,
        *,
        candidate: dict[str, Any],
        code_identity_hash: str | None,
        sim_version_identity: dict[str, Any] | str | None,
        random_seed_ledger_hash: str | None,
        contract_versions: dict[str, Any] | None,
        reward_hash: str | None = None,
        dependencies: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        candidate_payload = dict(candidate or {})
        required = required_evidence_status(candidate_payload)
        failure_reasons = [name for name in REQUIRED_PARENT_GATE_EVIDENCE if not required.get(name)]
        hidden_rank_ok = bool(candidate_payload.get("hidden_rank_ok"))
        statistical_confidence_ok = bool(candidate_payload.get("statistical_confidence_ok"))
        base_ok = not failure_reasons
        eligibility = {
            "eligible_for_pbt_parent": base_ok,
            "eligible_for_checkpoint_promotion": base_ok and hidden_rank_ok,
            "eligible_for_research_claim": base_ok and statistical_confidence_ok,
        }

        metrics = {
            "schema": "parent_gate_summary_v2",
            "required_evidence_count": len(REQUIRED_PARENT_GATE_EVIDENCE),
            "passed_required_evidence_count": sum(1 for name in REQUIRED_PARENT_GATE_EVIDENCE if required.get(name)),
            "hidden_rank_ok": hidden_rank_ok,
            "statistical_confidence_ok": statistical_confidence_ok,
        }
        return self._writer.write_parent_gate_artifact(
            candidate_id=str(candidate_payload.get("id") or candidate_payload.get("candidate_id") or ""),
            checkpoint_hash=_checkpoint_hash(candidate_payload),
            required=required,
            eligibility=eligibility,
            evidence_hashes=collect_evidence_hashes(candidate_payload),
            failure_reasons=failure_reasons,
            metrics=metrics,
            code_identity_hash=code_identity_hash,
            sim_version_identity=sim_version_identity,
            random_seed_ledger_hash=random_seed_ledger_hash,
            contract_versions=contract_versions,
            reward_hash=reward_hash,
            dependencies=dependencies or [],
        )


def required_evidence_status(candidate: dict[str, Any]) -> dict[str, bool]:
    return {
        "experiment_record_completeness": bool(_path(candidate, "record_completeness.critical_pass")),
        "checkpoint_hash": bool(_checkpoint_hash(candidate)),
        "training_world_hashes": bool(_candidate_training_world_hashes(candidate)),
        "evaluation_world_hashes": bool(_candidate_evaluation_world_hashes(candidate)),
        "reward_contract_hash": bool(_reward_contract_hash(candidate)),
        "action_contract_hash": bool(_action_contract_hash(candidate)),
        "observation_contract_hash": bool(_observation_contract_hash(candidate)),
        "code_version_or_runner_version": bool(_code_version_or_runner_version(candidate)),
        "lineage_evidence": _pass_fail(_path(candidate, "lineage_evidence")),
        "baseline_artifact": _pass_fail(_path(candidate, "baseline_artifact")),
        "calibration_artifact": _pass_fail(_path(candidate, "world.calibration_artifact")),
        "hidden_eval_artifact": _pass_fail(_path(candidate, "hidden_eval_artifact")),
        "exploit_test_artifact": _pass_fail(_path(candidate, "exploit_test_artifact")),
        "paired_sensitivity_artifact": _pass_fail(_path(candidate, "paired_sensitivity_artifact")),
    }


def collect_evidence_hashes(candidate: dict[str, Any]) -> dict[str, str]:
    evidence_paths = {
        "lineage_evidence": "lineage_evidence",
        "baseline_artifact": "baseline_artifact",
        "calibration_artifact": "world.calibration_artifact",
        "hidden_eval_artifact": "hidden_eval_artifact",
        "exploit_test_artifact": "exploit_test_artifact",
        "paired_sensitivity_artifact": "paired_sensitivity_artifact",
    }
    hashes = {}
    checkpoint_hash = _checkpoint_hash(candidate)
    if checkpoint_hash:
        hashes["checkpoint_hash"] = checkpoint_hash
    lineage_values = {
        "training_world_hashes": _candidate_training_world_hashes(candidate),
        "evaluation_world_hashes": _candidate_evaluation_world_hashes(candidate),
        "reward_contract_hash": _reward_contract_hash(candidate),
        "action_contract_hash": _action_contract_hash(candidate),
        "observation_contract_hash": _observation_contract_hash(candidate),
        "code_version_or_runner_version": _code_version_or_runner_version(candidate),
    }
    for name, value in lineage_values.items():
        hashed = _lineage_hash_value(value)
        if hashed:
            hashes[name] = hashed
    for name, path in evidence_paths.items():
        value = _hash_value(_path(candidate, path))
        if value:
            hashes[name] = value
    return hashes


def _path(payload: dict[str, Any], dotted: str) -> Any:
    current: Any = payload
    for part in dotted.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
        if current is None:
            return None
    return current


def _pass_fail(value: Any) -> bool:
    if isinstance(value, dict):
        source = str(value.get("source") or "").strip()
        if source != LIVE_RUNTIME_SOURCE or source in INVALID_EVIDENCE_SOURCES:
            return False
        if not _hash_value(value):
            return False
        return value.get("pass_gate") is True
    source = str(getattr(value, "source", "") or "").strip()
    if source != LIVE_RUNTIME_SOURCE or source in INVALID_EVIDENCE_SOURCES:
        return False
    if not _hash_value(value):
        return False
    return getattr(value, "pass_gate", None) is True


def _checkpoint_hash(candidate: dict[str, Any]) -> str | None:
    for key in ("checkpoint_hash", "hash", "artifact_hash"):
        value = candidate.get(key) if isinstance(candidate, dict) else None
        if value:
            return str(value)
    checkpoint = candidate.get("checkpoint") if isinstance(candidate, dict) else None
    return _hash_value(checkpoint)


def _candidate_training_world_hashes(candidate: dict[str, Any]) -> Any:
    return (
        candidate.get("training_world_hashes")
        or _path(candidate, "checkpoint.training_world_hashes")
        or _path(candidate, "hidden_eval_artifact.metrics.candidate_training_world_hashes")
    )


def _candidate_evaluation_world_hashes(candidate: dict[str, Any]) -> Any:
    return (
        candidate.get("evaluation_world_hashes")
        or candidate.get("hidden_world_hashes")
        or _path(candidate, "hidden_eval_artifact.metrics.hidden_world_hashes")
        or _path(candidate, "paired_sensitivity_artifact.metrics.scenario_world_hashes")
    )


def _reward_contract_hash(candidate: dict[str, Any]) -> Any:
    return (
        candidate.get("reward_contract_hash")
        or candidate.get("reward_hash")
        or _path(candidate, "contract_hashes.reward")
        or _path(candidate, "contract_versions.reward")
    )


def _action_contract_hash(candidate: dict[str, Any]) -> Any:
    return (
        candidate.get("action_contract_hash")
        or _path(candidate, "contract_hashes.action")
        or _path(candidate, "contract_versions.action")
    )


def _observation_contract_hash(candidate: dict[str, Any]) -> Any:
    return (
        candidate.get("observation_contract_hash")
        or _path(candidate, "contract_hashes.observation")
        or _path(candidate, "contract_versions.observation")
    )


def _code_version_or_runner_version(candidate: dict[str, Any]) -> Any:
    return (
        candidate.get("code_version")
        or candidate.get("runner_version")
        or candidate.get("code_identity_hash")
    )


def _hash_value(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("artifact_hash", "lock_hash", "checkpoint_hash", "hash"):
            if value.get(key):
                return str(value.get(key))
    for attr in ("artifact_hash", "lock_hash", "checkpoint_hash", "hash"):
        item = getattr(value, attr, None)
        if item:
            return str(item)
    return None


def _lineage_hash_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        payload = str(value)
    if not payload:
        return None
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "REQUIRED_PARENT_GATE_EVIDENCE",
    "StrictParentGateV2",
    "collect_evidence_hashes",
    "required_evidence_status",
]
