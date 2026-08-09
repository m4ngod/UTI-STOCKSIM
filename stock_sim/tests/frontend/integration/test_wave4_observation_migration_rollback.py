from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from sqlalchemy import create_engine

from app.journey_recovery import restore_journey_workspace_bookmark
from stock_sim.release.frontend_v2_package_entry import RendererLane, run_smoke_journey
from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
    create_sealed_wave2_release_input_fixture,
    load_sealed_wave2_release_input_fixture_manifest,
    open_sealed_wave2_release_input_fixture,
)
from stock_sim.release.wave4_rollback_evidence import (
    READABLE_ARTIFACT_KINDS,
    ROLLBACK_DRILL_SCHEMA_VERSION,
    ROLLBACK_STAGE_SEQUENCE,
    validate_rollback_drill_evidence,
)
from stock_sim.release.wave4_rollback_probe import (
    run_candidate_authoritative_recovery_probe,
    run_retained_widgets_source_probe,
)
from stock_sim.release.wave4_legacy_inventory import (
    build_legacy_route_inventory,
    legacy_route_inventory_sha256,
)
from stock_sim.release.wave4_observation_bundle import validate_observation_bundle
from stock_sim.release.wave4_observation_ledger import REQUIRED_FEATURE_ROUTES
from strategy_diagnostics.persistence import (
    DIAGNOSTIC_SCHEMA_REVISION,
    initialize_diagnostic_persistence,
)


_SOURCE_COMMIT = "a" * 40
_DEPENDENCY_LOCK_SHA256 = f"sha256:{'b' * 64}"


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _file_sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _wave3_bookmark() -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "last_route": "diagnostic_tasks",
            "diagnostic_task_id": "diagnostic-task-wave3-1",
            "scenario_focus_target": "market_scenario",
            "scenario_focus_identity": "market-scenario-wave3-1",
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _identity_map_from_result(result) -> dict[str, list[str]]:
    return {
        "Strategy": [result.strategy_identity],
        "Recipe": [result.approved_recipe_identity],
        "Task": [result.diagnostic_task_identity],
        "Campaign": [result.campaign_identity],
        "Run": [result.run_identity],
        "Evidence": [result.evidence_package_identity],
        "Finding": list(result.evidence_identity_sets["findings"]),
        "Manifest": [result.reproduction_manifest_identity],
    }


def _source_seam_daily_ledger(candidate, evidence, inventory) -> dict[str, object]:
    rendered = set(candidate.routes_rendered)
    return {
        "schema_version": "wave4.daily-observation-ledger.v1",
        "metric_set_id": "wave4.formal-observation.v1",
        "ledger_id": "wave4-source-seam-2026-08-10-software",
        "observation_date": "2026-08-10",
        "recorded_at": "2026-08-10T23:59:59Z",
        "calendar_timezone": "UTC",
        "artifacts": {
            "candidate": evidence["candidate_artifact"],
            "retained_widgets": evidence["retained_widgets_artifact"],
        },
        "release": {
            "channel": "development",
            "release_gates_passed": False,
            "package_published": False,
            "published_at": None,
        },
        "collection": {
            "expected_checkpoint_ids": [
                "install",
                "upgrade",
                "launch",
                "six-route-probe",
                "clean-exit",
            ],
            "observed_checkpoint_ids": [
                "install",
                "upgrade",
                "launch",
                "clean-exit",
            ],
        },
        "lifecycle": {
            "install": "passed",
            "upgrade": "passed",
            "launch": "passed",
            "clean_exit": "passed" if candidate.clean_exit else "failed",
            "crash_count": 0,
            "unhandled_error_count": len(candidate.errors),
        },
        "routes": [
            {
                "route": route,
                "activation": "passed" if route in rendered else "not_observed",
                "restore": "passed" if route in rendered else "not_observed",
                "focus_restore": "passed" if route in rendered else "not_observed",
                "typed_context_resolution": (
                    "passed" if route in rendered else "not_observed"
                ),
            }
            for route in REQUIRED_FEATURE_ROUTES
        ],
        "continuity": {
            "task_handle_continuity": "passed",
            "duplicate_prevention": "passed",
            "durable_identity_continuity": "passed",
            "reopen_accepted_identities": "passed",
            "context_compatibility_failure_count": 0,
            "manifest_compatibility_failure_count": 0,
        },
        "delivery": {
            "disconnect_count": 1,
            "stale_count": 1,
            "fallback_count": 0,
            "recovery_outcome": "passed",
            "max_recovery_latency_ms": 0,
            "rejected_old_generation_count": (
                1 if candidate.old_generation_rejected else 0
            ),
            "rejected_duplicate_count": 0,
            "rejected_lower_revision_count": 0,
            "incorrectly_accepted_old_generation_count": 0,
            "incorrectly_accepted_duplicate_count": 0,
            "incorrectly_accepted_lower_revision_count": 0,
        },
        "health": {
            component: {
                "degradation_count": 0,
                "max_degradation_duration_ms": 0,
            }
            for component in ("queue", "cache", "persistence", "system_health")
        },
        "route_incidents": [
            {
                "route": route,
                "legacy_fallback_count": 0,
                "legacy_fallback_forced": False,
                "forced_rollback": False,
                "v2_route_caused_fallback": False,
                "incident_code": None,
            }
            for route in REQUIRED_FEATURE_ROUTES
        ],
        "probe": {
            "probe_id": "wave4-source-seam-software",
            "scheduled": False,
            "six_route_passed": False,
            "renderer_lane": "software",
            "graphics_api": "Software",
            "stall_probe_passed": False,
            "stall_over_50ms_count": 0,
            "max_stall_ms": 0,
        },
        "migration_integrity": {
            "data_loss": False,
            "corruption": False,
            "destructive_migration": False,
        },
        "severity": {
            "unresolved_sev1_count": 0,
            "unresolved_sev2_count": 0,
        },
        "policy": {
            "security_violation_count": 0,
            "redaction_violation_count": 0,
            "webengine_included": False,
            "manual_trading_exposed": candidate.manual_trading_action_count > 0,
        },
        "legacy_inventory": {
            "inventory_id": inventory["inventory_id"],
            "inventory_sha256": legacy_route_inventory_sha256(inventory),
            "legacy_route_count": inventory["legacy_route_count"],
        },
        "product_rollback_forced": False,
    }


def test_fresh_and_copied_wave3_migrations_are_idempotent_and_exact(tmp_path) -> None:
    fresh_engine = create_engine(f"sqlite:///{tmp_path / 'fresh.sqlite3'}", future=True)
    try:
        first = initialize_diagnostic_persistence(fresh_engine)
        second = initialize_diagnostic_persistence(fresh_engine)
    finally:
        fresh_engine.dispose()
    assert first.current_revision == DIAGNOSTIC_SCHEMA_REVISION
    assert first.applied_revisions[-1] == DIAGNOSTIC_SCHEMA_REVISION
    assert second.current_revision == DIAGNOSTIC_SCHEMA_REVISION
    assert second.applied_revisions == ()

    source_bundle = tmp_path / "formal-wave3-source"
    copied_bundle = tmp_path / "formal-wave3-copy"
    source_manifest = create_sealed_wave2_release_input_fixture(
        bundle_root=source_bundle,
        source_commit=_SOURCE_COMMIT,
    )
    shutil.copytree(source_bundle, copied_bundle)
    copied_manifest = load_sealed_wave2_release_input_fixture_manifest(copied_bundle)
    assert copied_manifest.authoritative_input_identities == (
        source_manifest.authoritative_input_identities
    )

    first_open = open_sealed_wave2_release_input_fixture(
        bundle_root=copied_bundle,
        expected_source_commit=_SOURCE_COMMIT,
    )
    first_identities = first_open.authoritative_input_identities
    first_open.close()
    second_open = open_sealed_wave2_release_input_fixture(
        bundle_root=copied_bundle,
        expected_source_commit=_SOURCE_COMMIT,
    )
    try:
        assert second_open.authoritative_input_identities == first_identities
        assert second_open.authoritative_input_identities == (
            source_manifest.authoritative_input_identities
        )
    finally:
        second_open.close()

    migrated = restore_journey_workspace_bookmark(_wave3_bookmark())
    idempotent = restore_journey_workspace_bookmark(migrated.canonical_payload)
    assert migrated.migrated is True
    assert migrated.bookmark.diagnostic_task_id is not None
    assert migrated.bookmark.diagnostic_task_id.value == "diagnostic-task-wave3-1"
    assert migrated.bookmark.scenario_focus_identity == "market-scenario-wave3-1"
    assert idempotent.migrated is False
    assert idempotent.bookmark == migrated.bookmark
    assert idempotent.canonical_payload == migrated.canonical_payload


def test_supported_data_copy_candidate_widgets_candidate_drill(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QT_QUICK_BACKEND", "software")
    report_dir = tmp_path / "wave4-candidate"
    candidate = run_smoke_journey(
        report_dir=report_dir,
        renderer_lane=RendererLane.SOFTWARE,
        source_commit=_SOURCE_COMMIT,
        capture_images=False,
    )
    assert candidate.clean_exit is True
    assert candidate.errors == ()
    assert candidate.application_reopened is True
    assert candidate.writable_persistence_verified is True
    assert candidate.task_created_after_install is True
    assert candidate.task_handle_identities
    assert candidate.task_cancel_order_isolation_verified is True

    candidate_identities = _identity_map_from_result(candidate)
    source_persistence = report_dir / "v1-persistence"
    retained_copy = tmp_path / "retained-widgets-supported-copy"
    shutil.copytree(source_persistence, retained_copy)

    candidate_before = run_candidate_authoritative_recovery_probe(
        bundle_root=retained_copy,
        campaign_id=candidate.campaign_identity,
        evidence_package_id=candidate.evidence_package_identity,
        selected_manifest_id=candidate.reproduction_manifest_identity,
        diagnostic_task_id=candidate.diagnostic_task_identity,
    )
    widgets_source = run_retained_widgets_source_probe(
        report_directory=tmp_path / "retained-widgets-source-smoke",
        source_commit=_SOURCE_COMMIT,
        bundle_root=retained_copy,
        campaign_id=candidate.campaign_identity,
        evidence_package_id=candidate.evidence_package_identity,
        selected_manifest_id=candidate.reproduction_manifest_identity,
        diagnostic_task_id=candidate.diagnostic_task_identity,
    )
    recovered = run_candidate_authoritative_recovery_probe(
        bundle_root=retained_copy,
        campaign_id=candidate.campaign_identity,
        evidence_package_id=candidate.evidence_package_identity,
        selected_manifest_id=candidate.reproduction_manifest_identity,
        diagnostic_task_id=candidate.diagnostic_task_identity,
    )
    retained_identities = {
        kind: list(values)
        for kind, values in widgets_source.durable_identities.items()
    }
    recovered_identities = {
        kind: list(values)
        for kind, values in recovered.durable_identities.items()
    }
    assert {
        kind: list(values)
        for kind, values in candidate_before.durable_identities.items()
    } == candidate_identities
    assert retained_identities == candidate_identities
    assert recovered_identities == candidate_identities
    assert list(widgets_source.task_handle_identities) == list(
        candidate.task_handle_identities
    )
    assert list(recovered.task_handle_identities) == list(
        candidate.task_handle_identities
    )
    assert widgets_source.opened_panels
    assert widgets_source.placeholder_panels == ()
    assert widgets_source.manual_trading_action_count == 0
    assert widgets_source.supported_data_copy_verified is True
    assert widgets_source.order_count == candidate_before.order_count
    assert widgets_source.clean_exit is True

    source_root = Path(__file__).resolve().parents[3]
    evidence = {
        "schema_version": ROLLBACK_DRILL_SCHEMA_VERSION,
        "drill_id": "wave4-supported-data-rollback-2026-08-10",
        "started_at": "2026-08-10T12:00:00Z",
        "completed_at": "2026-08-10T12:03:00Z",
        "execution_mode": "supported-data-copy",
        "installed_binary_gate_verified": False,
        "candidate_artifact": {
            "kind": "wave4-candidate",
            "source_commit": _SOURCE_COMMIT,
            "dependency_lock_sha256": _DEPENDENCY_LOCK_SHA256,
            "artifact_sha256": _file_sha256(
                source_root / "stock_sim/release/frontend_v2_package_entry.py"
            ),
            "package_id": "wave4-candidate-source-seam",
            "build_id": "wave4-source-seam-20260810",
        },
        "retained_widgets_artifact": {
            "kind": "retained-widgets",
            "source_commit": _SOURCE_COMMIT,
            "dependency_lock_sha256": _DEPENDENCY_LOCK_SHA256,
            "artifact_sha256": _file_sha256(
                source_root
                / "stock_sim/release/frontend_widgets_rollback_entry.py"
            ),
            "package_id": "retained-widgets-source-seam",
            "build_id": "wave4-source-seam-20260810",
        },
        "supported_data_copy_sha256": _tree_sha256(retained_copy),
        "stage_sequence": list(ROLLBACK_STAGE_SEQUENCE),
        "stages": [
            {
                "stage": stage,
                "started_at": f"2026-08-10T12:0{index}:00Z",
                "completed_at": f"2026-08-10T12:0{index + 1}:00Z",
                "verification_surface": verification_surface,
                "clean_exit": clean_exit,
                "readable_artifacts": list(READABLE_ARTIFACT_KINDS),
                "durable_identities": identities,
                "task_handle_identities": handles,
                "order_state_sha256": order_state_sha256,
            }
            for index, (
                stage,
                verification_surface,
                clean_exit,
                identities,
                handles,
                order_state_sha256,
            ) in enumerate(
                (
                    (
                        "wave4-candidate",
                        "qml-source-smoke",
                        candidate.clean_exit and candidate_before.clean_exit,
                        candidate_identities,
                        list(candidate.task_handle_identities),
                        candidate_before.order_state_sha256,
                    ),
                    (
                        "retained-widgets",
                        "widgets-source-smoke",
                        widgets_source.clean_exit,
                        retained_identities,
                        list(widgets_source.task_handle_identities),
                        widgets_source.order_state_sha256,
                    ),
                    (
                        "wave4-candidate-recovered",
                        "application-authoritative-reopen",
                        recovered.clean_exit,
                        recovered_identities,
                        list(recovered.task_handle_identities),
                        recovered.order_state_sha256,
                    ),
                )
            )
        ],
        "persistence_migration": {
            "fresh_initialization_revision": DIAGNOSTIC_SCHEMA_REVISION,
            "copied_wave3_source_revision": DIAGNOSTIC_SCHEMA_REVISION,
            "upgraded_revision": DIAGNOSTIC_SCHEMA_REVISION,
            "deterministic": True,
            "idempotent": True,
            "additive": True,
            "retained_widgets_compatible": True,
            "order_mutation_count": sum(
                value != candidate_before.order_state_sha256
                for value in (
                    widgets_source.order_state_sha256,
                    recovered.order_state_sha256,
                )
            ),
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
    assert validate_rollback_drill_evidence(evidence) == evidence
    inventory = build_legacy_route_inventory(
        source_commit=_SOURCE_COMMIT,
        captured_at="2026-08-10T12:03:00Z",
    )
    ledger = _source_seam_daily_ledger(candidate, evidence, inventory)
    bundle = validate_observation_bundle(
        daily_ledgers=[ledger],
        rollback_evidence=evidence,
        legacy_inventory=inventory,
    )
    assert bundle.daily_assessments[0].complete is False
    assert bundle.daily_assessments[0].qualifying is False
    assert "non_formal_release_channel" in (
        bundle.daily_assessments[0].disqualifications
    )
    assert bundle.installed_binary_gate_verified is False
    assert bundle.legacy_route_count == 8
