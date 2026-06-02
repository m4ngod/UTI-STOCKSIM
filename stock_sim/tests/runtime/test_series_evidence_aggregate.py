import hashlib
import json
from pathlib import Path

from app.services.series_evidence_aggregate import REQUIRED_SERIES_EVIDENCE, SeriesEvidenceAggregate


def _artifact(kind, passed=True):
    payload = {
        "artifact_kind": kind,
        "source": "live_postgresql_runtime",
        "source_run_ids": [f"run-{kind}"],
        "runner_version": "v0",
        "pass_gate": passed,
        "pass_fail": passed,
        "failure_reasons": [] if passed else ["underperform_baseline"],
    }
    payload["artifact_hash"] = _hash(payload)
    return payload


def _lock(passed=True):
    payload = {
        "record_kind": "research_acceptance_lock_v2",
        "status": "open" if passed else "locked",
        "source": "live_postgresql_runtime",
        "source_run_ids": ["run-lock"],
        "runner_version": "v2",
        "pass_gate": passed,
        "is_research_accepted": passed,
        "failure_reasons": [] if passed else ["blocking_sections_non_empty"],
    }
    payload["lock_hash"] = _hash(payload)
    return payload


def _hash(payload):
    clean = {
        key: value
        for key, value in payload.items()
        if key not in {"artifact_hash", "lock_hash", "aggregate_hash", "artifact_path", "record_path", "package_path"}
    }
    encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _candidate(candidate_id="MODEL_A", **overrides):
    parent_gate = _artifact("parent_gate_artifact_v2", True)
    parent_gate.update(
        {
            "eligible_for_pbt_parent": True,
            "eligible_for_research_claim": True,
        }
    )
    parent_gate["artifact_hash"] = _hash(parent_gate)
    data = {
        "candidate_id": candidate_id,
        "checkpoint_hash": "k" * 64,
        "baseline_artifact": _artifact("baseline_artifact_v1"),
        "calibration_artifact": _artifact("calibration_artifact_v1"),
        "hidden_eval_artifact": _artifact("hidden_eval_artifact_v1"),
        "exploit_test_artifact": _artifact("exploit_test_artifact_v1"),
        "paired_sensitivity_artifact": _artifact("paired_sensitivity_artifact_v1"),
        "parent_gate_artifact": parent_gate,
        "research_acceptance_lock": {
            **_lock(True),
        },
    }
    data.update(overrides)
    return data


def test_series_evidence_aggregate_go_when_all_required_evidence_passes(tmp_path):
    record = SeriesEvidenceAggregate(output_root=tmp_path).aggregate(
        series_id="SERIES_A",
        candidates=[_candidate()],
        created_at="2026-05-05T00:00:00Z",
    )

    summary = record["candidate_summaries"][0]
    assert record["record_kind"] == "series_evidence_aggregate_v1"
    assert record["go_no_go"] == "go"
    assert record["required_evidence"] == REQUIRED_SERIES_EVIDENCE
    assert record["status_counts"]["pass"] == len(REQUIRED_SERIES_EVIDENCE)
    assert summary["overall_status"] == "pass"
    assert summary["parent_eligible"] is True
    assert summary["research_accepted"] is True
    assert len(record["aggregate_hash"]) == 64
    assert Path(record["record_path"]).exists()


def test_series_evidence_aggregate_counts_fail_missing_and_not_available(tmp_path):
    record = SeriesEvidenceAggregate(output_root=tmp_path).aggregate(
        series_id="SERIES_B",
        candidates=[
            _candidate(
                "MODEL_B",
                hidden_eval_artifact=_artifact("hidden_eval_artifact_v1", passed=False),
                exploit_test_artifact=None,
                paired_sensitivity_artifact={"status": "not_available", "reason": "paired_runner_not_run"},
            )
        ],
    )

    summary = record["candidate_summaries"][0]
    assert record["go_no_go"] == "no_go"
    assert record["status_counts"]["fail"] >= 1
    assert record["status_counts"]["missing"] >= 1
    assert record["status_counts"]["not_available"] >= 1
    assert summary["failed_evidence"] == ["hidden_eval_artifact"]
    assert summary["missing_evidence"] == ["exploit_test_artifact"]
    assert summary["not_available_evidence"] == ["paired_sensitivity_artifact"]
    assert "MODEL_B:hidden_eval_artifact:fail" in record["failure_reasons"]
    assert "MODEL_B:exploit_test_artifact:missing" in record["failure_reasons"]
    assert "MODEL_B:paired_sensitivity_artifact:not_available" in record["failure_reasons"]


def test_series_evidence_aggregate_recomputes_from_artifact_pass_gate(tmp_path):
    manual = _artifact("hidden_eval_artifact_v1", passed=True)
    manual["source"] = "manual"
    manual["artifact_hash"] = _hash(manual)
    claimed_pass = _artifact("exploit_test_artifact_v1", passed=True)
    claimed_pass["pass_gate"] = False
    claimed_pass["pass_fail"] = True
    claimed_pass["failure_reasons"] = ["missing_probe_metrics"]
    claimed_pass["artifact_hash"] = _hash(claimed_pass)

    record = SeriesEvidenceAggregate(output_root=tmp_path).aggregate(
        series_id="SERIES_STRICT",
        candidates=[
            _candidate(
                "MODEL_STRICT",
                hidden_eval_artifact=manual,
                exploit_test_artifact=claimed_pass,
            )
        ],
    )

    summary = record["candidate_summaries"][0]
    assert record["go_no_go"] == "no_go"
    assert summary["evidence_status"]["hidden_eval_artifact"] == "fail"
    assert summary["evidence_details"]["hidden_eval_artifact"]["failure_type"] == "invalid_source"
    assert summary["evidence_status"]["exploit_test_artifact"] == "fail"
    assert "missing_probe_metrics" in summary["evidence_details"]["exploit_test_artifact"]["blocking_metrics"]


def test_series_evidence_aggregate_rejects_legacy_full_pass_without_strict_fields(tmp_path):
    legacy = {
        "artifact_kind": "legacy_artifact_v1",
        "runner_version": "v0",
        "pass_fail": True,
        "failure_reasons": [],
    }
    legacy["artifact_hash"] = _hash(legacy)

    record = SeriesEvidenceAggregate(output_root=tmp_path).aggregate(
        series_id="SERIES_LEGACY_FULL_PASS",
        candidates=[
            _candidate(
                "MODEL_LEGACY",
                baseline_artifact=dict(legacy),
                calibration_artifact=dict(legacy),
                hidden_eval_artifact=dict(legacy),
                exploit_test_artifact=dict(legacy),
                paired_sensitivity_artifact=dict(legacy),
                parent_gate_artifact={**dict(legacy), "eligible_for_pbt_parent": True},
                research_acceptance_lock={**dict(legacy), "is_research_accepted": True},
            )
        ],
    )

    summary = record["candidate_summaries"][0]
    assert record["go_no_go"] == "no_go"
    assert summary["overall_status"] == "fail"
    assert set(summary["failed_evidence"]) == set(REQUIRED_SERIES_EVIDENCE)
    assert summary["parent_eligible"] is False
    assert summary["research_accepted"] is False
    for detail in summary["evidence_details"].values():
        assert detail["status"] == "fail"
        assert detail["failure_type"] in {"invalid_source", "hash_validation_failed"}
        assert "missing_live_runtime_source" in detail["validation_reasons"]
        assert "missing_pass_gate" in detail["validation_reasons"]


def test_series_evidence_aggregate_blocks_hash_mismatch(tmp_path):
    artifact = _artifact("calibration_artifact_v1", passed=True)
    artifact["artifact_hash"] = "0" * 64

    record = SeriesEvidenceAggregate(output_root=tmp_path).aggregate(
        series_id="SERIES_HASH",
        candidates=[_candidate("MODEL_HASH", calibration_artifact=artifact)],
    )

    detail = record["candidate_summaries"][0]["evidence_details"]["calibration_artifact"]
    assert detail["status"] == "fail"
    assert detail["failure_type"] == "hash_validation_failed"
    assert "hash_mismatch" in detail["validation_reasons"]


def test_series_evidence_aggregate_blocks_empty_series(tmp_path):
    record = SeriesEvidenceAggregate(output_root=tmp_path).aggregate(series_id="EMPTY", candidates=[])

    assert record["go_no_go"] == "no_go"
    assert record["candidate_count"] == 0
    assert record["failure_reasons"] == ["missing_series_candidates"]
