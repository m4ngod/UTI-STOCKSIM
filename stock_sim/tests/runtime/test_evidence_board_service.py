from app.services.evidence_board_service import build_evidence_board


def test_evidence_board_builds_rows_from_series_aggregate():
    board = build_evidence_board(
        {
            "go_no_go": "no_go",
            "status_counts": {"pass": 5, "fail": 1, "missing": 1, "not_available": 1},
            "blocking_candidates": ["MODEL_A"],
            "candidate_summaries": [
                {
                    "candidate_id": "MODEL_A",
                    "checkpoint_hash": "k" * 64,
                    "evidence_status": {
                        "baseline_artifact": "pass",
                        "calibration_artifact": "pass",
                        "hidden_eval_artifact": "fail",
                        "exploit_test_artifact": "missing",
                        "paired_sensitivity_artifact": "not_available",
                    },
                    "parent_eligible": False,
                    "research_claim_eligible": False,
                    "research_accepted": False,
                    "overall_status": "fail",
                    "failed_evidence": ["hidden_eval_artifact"],
                    "missing_evidence": ["exploit_test_artifact"],
                    "not_available_evidence": ["paired_sensitivity_artifact"],
                    "evidence_details": {
                        "hidden_eval_artifact": {
                            "status": "fail",
                            "failure_type": "underperform_baseline",
                            "blocking_metrics": ["win_rate_vs_baselines"],
                            "next_action": "Candidate underperformed TWAP/VWAP/AC-lite; keep fail and improve candidate/reward/action space.",
                            "artifact_hash": "h" * 64,
                            "runner_version": "v0",
                            "source_run_ids": ["run-hidden"],
                            "source": "live_postgresql_runtime",
                        }
                    },
                }
            ],
        }
    )

    row = board["rows"][0]
    assert board["status"] == "available"
    assert board["go_no_go"] == "no_go"
    assert row["baseline"] == "pass"
    assert row["hidden"] == "fail"
    assert row["exploit"] == "missing"
    assert row["fee_impact_sensitivity"] == "not_available"
    assert row["parent_eligible"] == "fail"
    assert row["research_claim_eligible"] == "fail"
    assert row["failure_details"][0]["failure_type"] == "underperform_baseline"
    assert row["failure_details"][0]["source_run_ids"] == ["run-hidden"]
    assert board["not_available_debt"][0]["planned_task_id"] == "94"


def test_evidence_board_reports_not_available_without_series_aggregate():
    board = build_evidence_board(None)

    assert board["status"] == "not_available"
    assert board["reason"] == "series_evidence_aggregate_not_available"
    assert board["rows"] == []
