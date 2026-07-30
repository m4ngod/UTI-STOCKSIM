from pathlib import Path

from app.services.research_acceptance_lock import ResearchAcceptanceLockV2, REQUIRED_RESEARCH_EVIDENCE_HASHES


def _parent_gate(**overrides):
    gate = {
        "artifact_kind": "parent_gate_artifact_v2",
        "artifact_id": "parent-gate-ok",
        "artifact_hash": "g" * 64,
        "source": "live_postgresql_runtime",
        "source_run_ids": ["run-parent-gate"],
        "runner_version": "v2",
        "pass_gate": True,
        "pass_fail": True,
        "eligible_for_research_claim": True,
        "required": {
            "experiment_record_completeness": True,
            "checkpoint_hash": True,
            "lineage_evidence": True,
            "baseline_artifact": True,
            "calibration_artifact": True,
            "hidden_eval_artifact": True,
            "exploit_test_artifact": True,
            "paired_sensitivity_artifact": True,
        },
        "evidence_hashes": {
            "checkpoint_hash": "k" * 64,
            "lineage_evidence": "l" * 64,
            "baseline_artifact": "b" * 64,
            "calibration_artifact": "c" * 64,
            "hidden_eval_artifact": "h" * 64,
            "exploit_test_artifact": "e" * 64,
            "paired_sensitivity_artifact": "p" * 64,
        },
    }
    gate.update(overrides)
    return gate


def test_research_acceptance_lock_opens_when_parent_gate_allows_research_claim(tmp_path):
    record = ResearchAcceptanceLockV2(output_root=tmp_path).evaluate(
        candidate_id="MODEL_A",
        claim_text="MODEL_A passed the evidence stack for this run.",
        parent_gate_artifact=_parent_gate(),
        created_at="2026-05-05T00:00:00Z",
    )

    assert record["record_kind"] == "research_acceptance_lock_v2"
    assert record["runner_name"] == "research_acceptance_lock_v2"
    assert record["runner_version"] == "v2"
    assert record["status"] == "open"
    assert record["is_research_accepted"] is True
    assert record["pass_gate"] is True
    assert record["acceptance_level"] == "level_1_engineering_acceptance"
    assert record["failure_reasons"] == []
    assert sorted(record["required_evidence_hashes"]) == sorted(REQUIRED_RESEARCH_EVIDENCE_HASHES)
    assert len(record["lock_hash"]) == 64
    assert Path(record["record_path"]).exists()


def test_level_1_research_acceptance_lock_opens_without_research_claim_eligibility(tmp_path):
    record = ResearchAcceptanceLockV2(output_root=tmp_path).evaluate(
        candidate_id="MODEL_A",
        claim_text="MODEL_A reached level-1 engineering acceptance.",
        parent_gate_artifact=_parent_gate(eligible_for_research_claim=False),
    )

    assert record["status"] == "open"
    assert record["pass_gate"] is True
    assert record["acceptance_level"] == "level_1_engineering_acceptance"
    assert record["failure_reasons"] == []


def test_higher_level_research_acceptance_lock_blocks_when_parent_gate_not_research_eligible(tmp_path):
    record = ResearchAcceptanceLockV2(output_root=tmp_path).evaluate(
        candidate_id="MODEL_A",
        claim_text="MODEL_A is research accepted.",
        parent_gate_artifact=_parent_gate(eligible_for_research_claim=False),
        acceptance_level="level_2_sim_research_acceptance",
    )

    assert record["status"] == "locked"
    assert record["is_research_accepted"] is False
    assert "parent_gate_research_claim_not_eligible" in record["failure_reasons"]
    assert "acceptance_level_not_supported:level_2_sim_research_acceptance" in record["failure_reasons"]


def test_research_acceptance_lock_does_not_duplicate_research_claim_reason_when_parent_gate_failed(tmp_path):
    record = ResearchAcceptanceLockV2(output_root=tmp_path).evaluate(
        candidate_id="MODEL_A",
        claim_text="MODEL_A is research accepted.",
        parent_gate_artifact=_parent_gate(
            pass_gate=False,
            pass_fail=False,
            eligible_for_research_claim=False,
            required={"paired_sensitivity_artifact": False},
        ),
    )

    assert record["status"] == "locked"
    assert "parent_gate_artifact_not_passed" in record["failure_reasons"]
    assert "required_evidence_failed:paired_sensitivity_artifact" in record["failure_reasons"]
    assert "parent_gate_research_claim_not_eligible" not in record["failure_reasons"]


def test_research_acceptance_lock_blocks_missing_claim_and_evidence_hashes(tmp_path):
    gate = _parent_gate(
        pass_gate=False,
        pass_fail=False,
        required={"hidden_eval_artifact": False},
        evidence_hashes={"checkpoint_hash": "k" * 64},
    )

    record = ResearchAcceptanceLockV2(output_root=tmp_path).evaluate(
        candidate_id="",
        claim_text="",
        parent_gate_artifact=gate,
    )

    assert record["status"] == "locked"
    assert "missing_candidate_id" in record["failure_reasons"]
    assert "missing_research_claim_text" in record["failure_reasons"]
    assert "parent_gate_artifact_not_passed" in record["failure_reasons"]
    assert "required_evidence_failed:hidden_eval_artifact" in record["failure_reasons"]
    assert "missing_evidence_hash:hidden_eval_artifact" in record["failure_reasons"]
    assert "missing_evidence_hash:baseline_artifact" in record["failure_reasons"]


def test_research_acceptance_lock_blocks_transfer_level_without_scope(tmp_path):
    record = ResearchAcceptanceLockV2(output_root=tmp_path).evaluate(
        candidate_id="MODEL_A",
        claim_text="MODEL_A transfers to historical markets.",
        parent_gate_artifact=_parent_gate(),
        acceptance_level="level_3_transfer_acceptance",
    )

    assert record["status"] == "locked"
    assert record["pass_gate"] is False
    assert "acceptance_level_not_supported:level_3_transfer_acceptance" in record["failure_reasons"]
