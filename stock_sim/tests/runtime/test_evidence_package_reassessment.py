import hashlib
import json
from pathlib import Path

from app.services.evidence_package_reassessment import EvidencePackageReassessmentRunner
from app.services.series_evidence_aggregate import REQUIRED_SERIES_EVIDENCE


def _hash(payload):
    clean = {
        key: value
        for key, value in payload.items()
        if key not in {"artifact_hash", "lock_hash", "aggregate_hash", "artifact_path", "record_path", "package_path"}
    }
    encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _artifact(kind: str, *, strict: bool) -> dict:
    payload = {
        "artifact_kind": kind,
        "runner_version": "v0",
        "pass_fail": True,
        "failure_reasons": [],
    }
    if strict:
        payload.update(
            {
                "source": "live_postgresql_runtime",
                "source_run_ids": [f"run-{kind}"],
                "pass_gate": True,
            }
        )
    payload["artifact_hash"] = _hash(payload)
    return payload


def _lock(*, strict: bool) -> dict:
    payload = {
        "record_kind": "research_acceptance_lock_v2",
        "status": "open",
        "is_research_accepted": True,
        "failure_reasons": [],
    }
    if strict:
        payload.update(
            {
                "source": "live_postgresql_runtime",
                "source_run_ids": ["run-lock"],
                "runner_version": "v2",
                "pass_gate": True,
            }
        )
    payload["lock_hash"] = _hash(payload)
    return payload


def _package(path: Path, evidence_hashes: dict[str, str]):
    payload = {
        "record_kind": "long_arena_dry_run_package_v1",
        "dry_run_id": "legacy-package",
        "package_hash": "p" * 64,
        "run_policy": {
            "actual_generation_count": 3,
            "min_generation_count": 3,
        },
        "arena_series_report": {
            "series_id": "legacy-series",
            "generation_count": 3,
            "runtime_evidence": {"source": "live_postgresql_runtime"},
        },
        "series_evidence_aggregate": {
            "candidate_summaries": [
                {
                    "candidate_id": "MODEL_LEGACY",
                    "checkpoint_hash": "k" * 64,
                    "evidence_hashes": evidence_hashes,
                }
            ]
        },
    }
    _write_json(path, payload)
    return path


def _materialize_artifacts(output_root: Path, *, strict: bool) -> dict[str, str]:
    hashes = {}
    for name in REQUIRED_SERIES_EVIDENCE:
        if name == "research_acceptance_lock":
            artifact = _lock(strict=strict)
            hashes[name] = artifact["lock_hash"]
            _write_json(output_root / name / "lock.json", artifact)
            continue
        artifact = _artifact(f"{name}_v1", strict=strict)
        if name == "parent_gate_artifact" and strict:
            artifact.update(
                {
                    "eligible_for_pbt_parent": True,
                    "eligible_for_research_claim": True,
                }
            )
            artifact["artifact_hash"] = _hash(artifact)
        hashes[name] = artifact["artifact_hash"]
        _write_json(output_root / name / f"{name}.json", artifact)
    return hashes


def test_reassessment_recomputes_legacy_all_pass_as_no_go(tmp_path):
    output_root = tmp_path / "evidence_artifacts"
    package_path = _package(tmp_path / "legacy-package.json", _materialize_artifacts(output_root, strict=False))

    result = EvidencePackageReassessmentRunner(output_root=output_root).reassess_package(
        package_path,
        dry_run_id="legacy-package-strict-recomputed",
        created_at="2026-05-07T00:00:00Z",
    )

    summary = result["series_evidence_aggregate"]["candidate_summaries"][0]
    assert result["status"] == "complete"
    assert result["go_no_go"] == "no_go"
    assert set(summary["failed_evidence"]) == set(REQUIRED_SERIES_EVIDENCE)
    assert Path(result["package_path"]).exists()


def test_reassessment_preserves_go_for_strict_live_artifacts(tmp_path):
    output_root = tmp_path / "evidence_artifacts"
    package_path = _package(tmp_path / "strict-package.json", _materialize_artifacts(output_root, strict=True))

    result = EvidencePackageReassessmentRunner(output_root=output_root).reassess_package(
        package_path,
        dry_run_id="strict-package-recomputed",
        created_at="2026-05-07T00:00:00Z",
    )

    summary = result["series_evidence_aggregate"]["candidate_summaries"][0]
    assert result["status"] == "complete"
    assert result["go_no_go"] == "go"
    assert summary["overall_status"] == "pass"
    assert summary["parent_eligible"] is True
    assert summary["research_accepted"] is True
