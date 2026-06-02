import hashlib
import json
from pathlib import Path

from app.services.long_arena_dry_run import LongArenaDryRunRunner


def _artifact(kind, passed=True):
    payload = {
        "artifact_kind": kind,
        "source": "live_postgresql_runtime",
        "source_run_ids": [f"run-{kind}"],
        "runner_version": "v0",
        "pass_gate": passed,
        "pass_fail": passed,
        "failure_reasons": [] if passed else ["gate_not_passed"],
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


def _parent_gate(passed=True):
    payload = _artifact("parent_gate_artifact_v2", passed)
    payload.update(
        {
            "eligible_for_pbt_parent": passed,
            "eligible_for_research_claim": passed,
        }
    )
    payload["artifact_hash"] = _hash(payload)
    return payload


def _hash(payload):
    clean = {
        key: value
        for key, value in payload.items()
        if key not in {"artifact_hash", "lock_hash", "aggregate_hash", "artifact_path", "record_path", "package_path"}
    }
    encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _passing_candidate(candidate_id="MODEL_A"):
    return {
        "candidate_id": candidate_id,
        "checkpoint_hash": "k" * 64,
        "baseline_artifact": _artifact("baseline_artifact_v1"),
        "calibration_artifact": _artifact("calibration_artifact_v1"),
        "hidden_eval_artifact": _artifact("hidden_eval_artifact_v1"),
        "exploit_test_artifact": _artifact("exploit_test_artifact_v1"),
        "paired_sensitivity_artifact": _artifact("paired_sensitivity_artifact_v1"),
        "parent_gate_artifact": _parent_gate(True),
        "research_acceptance_lock": _lock(True),
    }


def test_long_arena_dry_run_writes_complete_evidence_package(tmp_path):
    calls = []

    def run_series(config, *, generations):
        calls.append((config, generations))
        return {
            "schema": "stock_sim.arena_generation_series_report.v1",
            "series_id": "SERIES_A",
            "generation_count": generations,
            "generations": [{"generation": idx} for idx in range(generations)],
            "reports": [{"episode_id": f"episode-{idx}"} for idx in range(generations)],
            "aggregate": {"generation_count": generations},
            "report_path": str(tmp_path / "SERIES_A-series.json"),
        }

    package = LongArenaDryRunRunner(output_root=tmp_path).run(
        run_series=run_series,
        config={"arena_id": "SERIES_A"},
        candidate_evidence=[_passing_candidate()],
        dry_run_id="dry-run-a",
        generations=3,
        min_generation_count=2,
        created_at="2026-05-05T00:00:00Z",
    )

    assert calls == [({"arena_id": "SERIES_A"}, 3)]
    assert package["record_kind"] == "long_arena_dry_run_package_v1"
    assert package["status"] == "complete"
    assert package["go_no_go"] == "go"
    assert package["run_policy"]["actual_generation_count"] == 3
    assert package["series_evidence_aggregate"]["go_no_go"] == "go"
    assert package["evidence_board"]["status"] == "available"
    assert package["gate_review"]["parent_eligible_candidates"] == ["MODEL_A"]
    assert len(package["package_hash"]) == 64
    assert Path(package["package_path"]).exists()


def test_long_arena_dry_run_records_no_go_when_evidence_is_incomplete(tmp_path):
    def run_series(config, *, generations):
        return {
            "schema": "stock_sim.arena_generation_series_report.v1",
            "series_id": "SERIES_B",
            "generation_count": 1,
            "generations": [{"generation": 1}],
            "reports": [{"episode_id": "episode-1"}],
            "runtime_evidence": {"database": {"dialect": "postgresql", "episode_count": 1}},
        }

    package = LongArenaDryRunRunner(output_root=tmp_path).run(
        run_series=run_series,
        candidate_evidence=[
            _passing_candidate(
                "MODEL_B",
            )
            | {
                "hidden_eval_artifact": {"status": "not_available", "reason": "hidden_runner_not_run"},
                "exploit_test_artifact": None,
                "parent_gate_artifact": _parent_gate(False),
            }
        ],
        dry_run_id="dry-run-b",
        generations=3,
        min_generation_count=2,
    )

    assert package["status"] == "incomplete"
    assert package["go_no_go"] == "no_go"
    assert package["arena_series_report"]["runtime_evidence"]["database"]["dialect"] == "postgresql"
    assert "evidence_package_has_failed_evidence" in package["failure_reasons"]
    assert "long_arena_generation_count_below_minimum" in package["failure_reasons"]
    assert "evidence_package_has_missing_evidence" in package["failure_reasons"]
    assert "evidence_package_has_not_available_evidence" in package["failure_reasons"]
    assert "no_candidate_passed_parent_gate" in package["failure_reasons"]


def test_long_arena_dry_run_keeps_complete_status_for_complete_failed_evidence(tmp_path):
    def run_series(config, *, generations):
        return {
            "schema": "stock_sim.arena_generation_series_report.v1",
            "series_id": "SERIES_C",
            "generation_count": generations,
            "generations": [{"generation": idx} for idx in range(generations)],
            "reports": [{"episode_id": f"episode-{idx}"} for idx in range(generations)],
        }

    package = LongArenaDryRunRunner(output_root=tmp_path).run(
        run_series=run_series,
        candidate_evidence=[
            _passing_candidate("MODEL_C")
            | {
                "calibration_artifact": _artifact("calibration_artifact_v1", passed=False),
                "parent_gate_artifact": _parent_gate(False),
                "research_acceptance_lock": _lock(False),
            }
        ],
        dry_run_id="dry-run-c",
        generations=3,
        min_generation_count=2,
    )

    assert package["status"] == "complete"
    assert package["go_no_go"] == "no_go"
    assert "evidence_package_has_failed_evidence" in package["failure_reasons"]
    assert "no_candidate_passed_parent_gate" in package["failure_reasons"]
