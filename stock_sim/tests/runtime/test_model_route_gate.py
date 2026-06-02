from pathlib import Path

from app.services.model_route_gate import ModelRouteGate


def test_model_route_gate_blocks_advanced_routes_when_evidence_runner_is_no_go(tmp_path):
    record = ModelRouteGate(output_root=tmp_path).evaluate(
        model_specs=[
            {"model_id": "ppo_lstm_v1", "policy_type": "ppo_recurrent"},
            {"model_id": "twap_execution_v1", "policy_type": "scheduled_execution_baseline"},
            {"model_id": "transformer_temporal_encoder_v1", "policy_type": "transformer"},
            {"model_id": "abides_marl_v1", "policy_type": "marl"},
        ],
        go_no_go_review={"decision": "no_go"},
        created_at="2026-05-05T00:00:00Z",
    )

    assert record["record_kind"] == "model_route_gate_v1"
    assert record["status"] == "fail"
    assert record["advanced_routes_allowed"] is False
    assert record["allowed_model_ids"] == ["ppo_lstm_v1", "twap_execution_v1"]
    assert record["blocked_model_ids"] == ["transformer_temporal_encoder_v1", "abides_marl_v1"]
    assert "evidence_runner_no_go_blocks_complex_model_route" in record["failure_reasons"]
    assert Path(record["record_path"]).exists()


def test_model_route_gate_allows_advanced_routes_after_go_decision(tmp_path):
    record = ModelRouteGate(output_root=tmp_path).evaluate(
        model_specs=[
            {"model_id": "transformer_temporal_encoder_v1", "policy_type": "transformer"},
            {"model_id": "historical_replay_hybrid_env_v1", "policy_type": "hybrid_env"},
        ],
        go_no_go_review={"decision": "go"},
        created_at="2026-05-05T00:00:00Z",
    )

    assert record["status"] == "pass"
    assert record["advanced_routes_allowed"] is True
    assert record["blocked_model_ids"] == []
    assert record["allowed_model_ids"] == ["transformer_temporal_encoder_v1", "historical_replay_hybrid_env_v1"]


def test_model_route_gate_defaults_to_no_go_without_review(tmp_path):
    record = ModelRouteGate(output_root=tmp_path).evaluate(
        model_specs=[{"model_id": "gtrxl_policy_v1", "policy_type": "transformer"}],
        go_no_go_review=None,
    )

    assert record["go_no_go_decision"] == "no_go"
    assert record["status"] == "fail"
    assert record["blocked_model_ids"] == ["gtrxl_policy_v1"]
    assert len(record["route_gate_hash"]) == 64
