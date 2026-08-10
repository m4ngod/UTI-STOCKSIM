from __future__ import annotations

from copy import deepcopy
import json

import pytest

from stock_sim.release.wave4_rollback_evidence import (
    READABLE_ARTIFACT_KINDS,
    ROLLBACK_DRILL_JSON_SCHEMA_PATH,
    ROLLBACK_DRILL_SCHEMA_VERSION,
    ROLLBACK_STAGE_SEQUENCE,
    RollbackEvidenceValidationError,
    validate_rollback_drill_evidence,
)
from strategy_diagnostics.persistence import DIAGNOSTIC_SCHEMA_REVISION


def _artifact(kind: str, digest_character: str) -> dict[str, str]:
    return {
        "kind": kind,
        "source_commit": "a" * 40,
        "dependency_lock_sha256": f"sha256:{'b' * 64}",
        "artifact_sha256": f"sha256:{digest_character * 64}",
        "package_id": f"uti-stocksim-{kind}-2026.08.10",
        "build_id": "wave4-build-20260810.1",
    }


def _durable_identities() -> dict[str, list[str]]:
    return {
        "Strategy": ["strategy-release-1"],
        "Recipe": ["recipe-release-1"],
        "Task": ["diagnostic-task-release-1"],
        "Campaign": ["campaign-release-1"],
        "Run": ["run-release-1"],
        "Evidence": ["evidence-release-1"],
        "Finding": ["finding-release-1"],
        "Manifest": ["manifest-release-1"],
    }


def _stage(
    stage: str,
    started_at: str,
    completed_at: str,
    verification_surface: str,
) -> dict[str, object]:
    return {
        "stage": stage,
        "started_at": started_at,
        "completed_at": completed_at,
        "verification_surface": verification_surface,
        "clean_exit": True,
        "readable_artifacts": list(READABLE_ARTIFACT_KINDS),
        "durable_identities": _durable_identities(),
        "task_handle_identities": ["task-handle-release-1"],
        "order_state_sha256": f"sha256:{'f' * 64}",
    }


def _valid_rollback_evidence() -> dict[str, object]:
    return {
        "schema_version": ROLLBACK_DRILL_SCHEMA_VERSION,
        "drill_id": "wave4-rollback-drill-2026-08-10",
        "started_at": "2026-08-10T12:00:00Z",
        "completed_at": "2026-08-10T12:03:00Z",
        "execution_mode": "supported-data-copy",
        "installed_binary_gate_verified": False,
        "candidate_artifact": _artifact("wave4-candidate", "c"),
        "retained_widgets_artifact": _artifact("retained-widgets", "d"),
        "supported_data_copy_sha256": f"sha256:{'e' * 64}",
        "stage_sequence": list(ROLLBACK_STAGE_SEQUENCE),
        "stages": [
            _stage(
                "wave4-candidate",
                "2026-08-10T12:00:00Z",
                "2026-08-10T12:01:00Z",
                "qml-source-smoke",
            ),
            _stage(
                "retained-widgets",
                "2026-08-10T12:01:00Z",
                "2026-08-10T12:02:00Z",
                "widgets-source-smoke",
            ),
            _stage(
                "wave4-candidate-recovered",
                "2026-08-10T12:02:00Z",
                "2026-08-10T12:03:00Z",
                "application-authoritative-reopen",
            ),
        ],
        "persistence_migration": {
            "fresh_initialization_revision": DIAGNOSTIC_SCHEMA_REVISION,
            "copied_wave3_source_revision": DIAGNOSTIC_SCHEMA_REVISION,
            "upgraded_revision": DIAGNOSTIC_SCHEMA_REVISION,
            "deterministic": True,
            "idempotent": True,
            "additive": True,
            "retained_widgets_compatible": True,
            "order_mutation_count": 0,
        },
        "bookmark_migration": {
            "source_schema_version": "1.0",
            "target_schema_version": "2.0",
            "deterministic": True,
            "idempotent": True,
            "exact_durable_identities_preserved": True,
        },
        "task_handle_continuity": True,
        "duplicate_identity_count": 0,
    }


def test_rollback_evidence_requires_exact_reversible_identity_graph() -> None:
    evidence = _valid_rollback_evidence()

    assert validate_rollback_drill_evidence(evidence) == evidence

    key_sorted_round_trip = json.loads(json.dumps(evidence, sort_keys=True))
    assert validate_rollback_drill_evidence(key_sorted_round_trip) == (
        key_sorted_round_trip
    )

    changed_identity = deepcopy(evidence)
    changed_identity["stages"][1]["durable_identities"]["Manifest"] = [
        "manifest-drifted"
    ]
    with pytest.raises(
        RollbackEvidenceValidationError,
        match="durable identity graph changed",
    ):
        validate_rollback_drill_evidence(changed_identity)

    duplicate = deepcopy(evidence)
    duplicate["duplicate_identity_count"] = 1
    with pytest.raises(
        RollbackEvidenceValidationError,
        match="duplicate identity",
    ):
        validate_rollback_drill_evidence(duplicate)


def test_rollback_json_schema_locks_artifact_and_stage_positions() -> None:
    schema = json.loads(ROLLBACK_DRILL_JSON_SCHEMA_PATH.read_text(encoding="utf-8"))
    properties = schema["properties"]
    assert properties["candidate_artifact"]["allOf"][1]["properties"]["kind"] == {
        "const": "wave4-candidate"
    }
    assert properties["retained_widgets_artifact"]["allOf"][1]["properties"][
        "kind"
    ] == {"const": "retained-widgets"}
    stage_items = properties["stages"]["prefixItems"]
    assert tuple(
        item["allOf"][1]["properties"]["stage"]["const"]
        for item in stage_items
    ) == ROLLBACK_STAGE_SEQUENCE
    assert "order_state_sha256" in schema["$defs"]["stage"]["required"]


def test_rollback_evidence_requires_same_source_lock_and_sha256_artifacts() -> None:
    wrong_source = _valid_rollback_evidence()
    wrong_source["retained_widgets_artifact"]["source_commit"] = "f" * 40
    with pytest.raises(
        RollbackEvidenceValidationError,
        match="same source commit",
    ):
        validate_rollback_drill_evidence(wrong_source)

    wrong_lock = _valid_rollback_evidence()
    wrong_lock["retained_widgets_artifact"][
        "dependency_lock_sha256"
    ] = f"sha256:{'f' * 64}"
    with pytest.raises(
        RollbackEvidenceValidationError,
        match="same dependency lock",
    ):
        validate_rollback_drill_evidence(wrong_lock)

    bad_hash = _valid_rollback_evidence()
    bad_hash["candidate_artifact"]["artifact_sha256"] = "not-a-sha256"
    with pytest.raises(RollbackEvidenceValidationError, match="SHA-256"):
        validate_rollback_drill_evidence(bad_hash)


def test_rollback_evidence_rejects_destructive_or_incomplete_drill() -> None:
    order_mutation = _valid_rollback_evidence()
    order_mutation["stages"][1]["order_state_sha256"] = f"sha256:{'9' * 64}"
    order_mutation["persistence_migration"]["order_mutation_count"] = 1
    with pytest.raises(
        RollbackEvidenceValidationError,
        match="must not mutate orders",
    ):
        validate_rollback_drill_evidence(order_mutation)

    unclean = _valid_rollback_evidence()
    unclean["stages"][1]["clean_exit"] = False
    with pytest.raises(RollbackEvidenceValidationError, match="clean exit"):
        validate_rollback_drill_evidence(unclean)

    missing_artifact_kind = _valid_rollback_evidence()
    missing_artifact_kind["stages"][1]["readable_artifacts"].remove("Finding")
    with pytest.raises(
        RollbackEvidenceValidationError,
        match="readable artifact kinds",
    ):
        validate_rollback_drill_evidence(missing_artifact_kind)

    false_binary_claim = _valid_rollback_evidence()
    false_binary_claim["installed_binary_gate_verified"] = True
    with pytest.raises(
        RollbackEvidenceValidationError,
        match="supported-data-copy.*binary gate",
    ):
        validate_rollback_drill_evidence(false_binary_claim)
