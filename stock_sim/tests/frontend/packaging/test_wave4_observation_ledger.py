from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import json

import pytest

from stock_sim.release.wave4_observation_ledger import (
    DAILY_LEDGER_SCHEMA_VERSION,
    DAILY_LEDGER_JSON_SCHEMA_PATH,
    METRIC_SET_ID,
    REQUIRED_FEATURE_ROUTES,
    DailyLedgerAssessment,
    LedgerCollectionError,
    LedgerValidationError,
    ObservationWindowError,
    ResetReason,
    assess_daily_observation_ledger,
    calculate_observation_window,
    collect_daily_observation_ledger,
    validate_daily_observation_ledger,
)
from stock_sim.release.wave4_legacy_inventory import (
    LEGACY_INVENTORY_SCHEMA_VERSION,
    LEGACY_ROUTE_IDS,
    build_legacy_route_inventory,
    legacy_route_inventory_sha256,
    validate_legacy_route_inventory,
)
from stock_sim.release.wave4_observation_ledger_cli import main as ledger_cli_main


def _artifact(kind: str, artifact_sha256: str) -> dict[str, object]:
    return {
        "kind": kind,
        "source_commit": "a" * 40,
        "dependency_lock_sha256": f"sha256:{'b' * 64}",
        "artifact_sha256": artifact_sha256,
        "package_id": f"uti-stocksim-{kind}-2026.08.10",
        "build_id": "wave4-build-20260810.1",
    }


def _valid_ledger() -> dict[str, object]:
    return {
        "schema_version": DAILY_LEDGER_SCHEMA_VERSION,
        "metric_set_id": METRIC_SET_ID,
        "ledger_id": "wave4-ledger-2026-08-10-hardware",
        "observation_date": "2026-08-10",
        "recorded_at": "2026-08-10T23:59:59Z",
        "calendar_timezone": "UTC",
        "artifacts": {
            "candidate": _artifact(
                "wave4-candidate",
                f"sha256:{'c' * 64}",
            ),
            "retained_widgets": _artifact(
                "retained-widgets",
                f"sha256:{'d' * 64}",
            ),
        },
        "release": {
            "channel": "formal",
            "release_gates_passed": True,
            "package_published": True,
            "published_at": "2026-08-10T00:00:00Z",
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
                "six-route-probe",
                "clean-exit",
            ],
        },
        "lifecycle": {
            "install": "passed",
            "upgrade": "passed",
            "launch": "passed",
            "clean_exit": "passed",
            "crash_count": 0,
            "unhandled_error_count": 0,
        },
        "routes": [
            {
                "route": route,
                "activation": "passed",
                "restore": "passed",
                "focus_restore": "passed",
                "typed_context_resolution": "passed",
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
            "disconnect_count": 0,
            "stale_count": 0,
            "fallback_count": 0,
            "recovery_outcome": "passed",
            "max_recovery_latency_ms": 23,
            "rejected_old_generation_count": 2,
            "rejected_duplicate_count": 1,
            "rejected_lower_revision_count": 2,
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
            "probe_id": "wave4-six-route-2026-08-10-hardware",
            "scheduled": True,
            "six_route_passed": True,
            "renderer_lane": "hardware",
            "graphics_api": "Direct3D11",
            "stall_probe_passed": True,
            "stall_over_50ms_count": 0,
            "max_stall_ms": 19,
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
            "manual_trading_exposed": False,
        },
        "legacy_inventory": {
            "inventory_id": "wave4-legacy-inventory-v1",
            "inventory_sha256": f"sha256:{'e' * 64}",
            "legacy_route_count": 8,
        },
        "product_rollback_forced": False,
    }


def _set_nested(
    payload: dict[str, object],
    path: tuple[str | int, ...],
    value: object,
) -> None:
    current: object = payload
    for part in path[:-1]:
        current = current[part]
    current[path[-1]] = value


def _ledger_for_day(
    observation_day: date,
    *,
    renderer_lane: str = "hardware",
) -> dict[str, object]:
    ledger = _valid_ledger()
    day = observation_day.isoformat()
    ledger["ledger_id"] = f"wave4-ledger-{day}-{renderer_lane}"
    ledger["observation_date"] = day
    ledger["recorded_at"] = f"{day}T23:59:59Z"
    ledger["probe"]["probe_id"] = f"wave4-six-route-{day}-{renderer_lane}"
    ledger["probe"]["renderer_lane"] = renderer_lane
    ledger["probe"]["graphics_api"] = (
        "Direct3D11" if renderer_lane == "hardware" else "Software"
    )
    return ledger


def test_daily_ledger_schema_is_strict_and_machine_readable() -> None:
    ledger = _valid_ledger()

    validated = validate_daily_observation_ledger(ledger)

    assert validated == ledger

    missing = deepcopy(ledger)
    del missing["continuity"]
    with pytest.raises(LedgerValidationError, match="continuity"):
        validate_daily_observation_ledger(missing)

    extra = deepcopy(ledger)
    extra["selectively_excluded_metrics"] = ["crashes"]
    with pytest.raises(LedgerValidationError, match="unexpected field"):
        validate_daily_observation_ledger(extra)


def test_daily_ledger_validates_nested_shape_and_reproducible_identities() -> None:
    schema = json.loads(DAILY_LEDGER_JSON_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schema_version"]["const"] == (
        DAILY_LEDGER_SCHEMA_VERSION
    )
    assert schema["additionalProperties"] is False
    artifacts = schema["properties"]["artifacts"]["properties"]
    assert artifacts["candidate"]["allOf"][1]["properties"]["kind"] == {
        "const": "wave4-candidate"
    }
    assert artifacts["retained_widgets"]["allOf"][1]["properties"]["kind"] == {
        "const": "retained-widgets"
    }
    assert len(schema["properties"]["probe"]["allOf"]) == 2

    missing_nested = _valid_ledger()
    del missing_nested["delivery"]["rejected_old_generation_count"]
    with pytest.raises(
        LedgerValidationError,
        match="delivery.*rejected_old_generation_count",
    ):
        validate_daily_observation_ledger(missing_nested)

    wrong_routes = _valid_ledger()
    wrong_routes["routes"][0]["route"] = "unknown_route"
    with pytest.raises(LedgerValidationError, match="exact six Feature routes"):
        validate_daily_observation_ledger(wrong_routes)

    wrong_source = _valid_ledger()
    wrong_source["artifacts"]["retained_widgets"]["source_commit"] = "f" * 40
    with pytest.raises(LedgerValidationError, match="same source commit"):
        validate_daily_observation_ledger(wrong_source)

    wrong_lock = _valid_ledger()
    wrong_lock["artifacts"]["retained_widgets"][
        "dependency_lock_sha256"
    ] = f"sha256:{'f' * 64}"
    with pytest.raises(LedgerValidationError, match="same dependency lock"):
        validate_daily_observation_ledger(wrong_lock)

    wrong_day = _valid_ledger()
    wrong_day["recorded_at"] = "2026-08-11T00:00:00Z"
    with pytest.raises(LedgerValidationError, match="observation_date"):
        validate_daily_observation_ledger(wrong_day)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("credential", "do-not-record"),
        ("api_key", "sk-proj-0123456789abcdefghijklmnopqrstuvwxyz"),
        ("password", "do-not-record"),
        ("token", "ghp_0123456789abcdefghijklmnopqrstuvwxyz"),
        ("database_url", "postgresql://operator:secret@db/prod"),
        ("database_path", "C:\\Users\\operator\\formal.sqlite3"),
        ("sql", "SELECT * FROM fills"),
        ("arbitrary_command", "powershell.exe -Command Get-ChildItem"),
        ("raw_traceback", "Traceback (most recent call last):"),
        ("order_payload", {"side": "Buy", "quantity": 100}),
        ("market_payload", {"symbol": "PRIVATE"}),
        ("account_payload", {"account_id": "private-account"}),
        ("fill_payload", {"fill_id": "private-fill"}),
        ("email", "private@example.invalid"),
    ],
)
def test_daily_ledger_rejects_secret_transaction_and_private_payloads(
    field: str,
    value: object,
) -> None:
    ledger = _valid_ledger()
    ledger[field] = value

    with pytest.raises(LedgerValidationError, match="prohibited"):
        validate_daily_observation_ledger(ledger)


def test_daily_ledger_rejects_secret_patterns_inside_allowed_fields() -> None:
    ledger = _valid_ledger()
    ledger["route_incidents"][0]["incident_code"] = (
        "ghp_0123456789abcdefghijklmnopqrstuvwxyz"
    )

    with pytest.raises(LedgerValidationError, match="secret-like value"):
        validate_daily_observation_ledger(ledger)


def test_daily_ledger_qualification_distinguishes_complete_and_formal_days() -> None:
    assessment = assess_daily_observation_ledger(_valid_ledger())

    assert assessment == DailyLedgerAssessment(
        ledger_id="wave4-ledger-2026-08-10-hardware",
        observation_date="2026-08-10",
        source_commit="a" * 40,
        dependency_lock_sha256=f"sha256:{'b' * 64}",
        renderer_lane="hardware",
        complete=True,
        qualifying=True,
        reset_reasons=(),
        disqualifications=(),
    )

    incomplete = _valid_ledger()
    incomplete["collection"]["observed_checkpoint_ids"].remove("clean-exit")
    incomplete["lifecycle"]["clean_exit"] = "not_observed"
    incomplete_assessment = assess_daily_observation_ledger(incomplete)
    assert incomplete_assessment.complete is False
    assert incomplete_assessment.qualifying is False
    assert incomplete_assessment.reset_reasons == ()
    assert "incomplete_daily_collection" in incomplete_assessment.disqualifications

    rc = _valid_ledger()
    rc["release"] = {
        "channel": "rc",
        "release_gates_passed": True,
        "package_published": False,
        "published_at": None,
    }
    rc_assessment = assess_daily_observation_ledger(rc)
    assert rc_assessment.complete is True
    assert rc_assessment.qualifying is False
    assert rc_assessment.reset_reasons == ()
    assert "non_formal_release_channel" in rc_assessment.disqualifications
    assert "formal_package_not_published" in rc_assessment.disqualifications


@pytest.mark.parametrize(
    ("mutations", "expected_reason"),
    [
        (
            ((('severity', 'unresolved_sev1_count'), 1),),
            ResetReason.UNRESOLVED_SEV1,
        ),
        (
            ((('severity', 'unresolved_sev2_count'), 1),),
            ResetReason.UNRESOLVED_SEV2,
        ),
        (
            ((('product_rollback_forced',), True),),
            ResetReason.FORCED_PRODUCT_ROLLBACK,
        ),
        (
            ((('route_incidents', 0, 'forced_rollback'), True),),
            ResetReason.FORCED_ROUTE_ROLLBACK,
        ),
        (
            ((('migration_integrity', 'data_loss'), True),),
            ResetReason.DATA_LOSS,
        ),
        (
            ((('migration_integrity', 'corruption'), True),),
            ResetReason.CORRUPTION,
        ),
        (
            ((('migration_integrity', 'destructive_migration'), True),),
            ResetReason.DESTRUCTIVE_MIGRATION,
        ),
        (
            ((('continuity', 'durable_identity_continuity'), 'failed'),),
            ResetReason.TYPED_IDENTITY_CONTINUITY_VIOLATION,
        ),
        (
            ((('continuity', 'task_handle_continuity'), 'failed'),),
            ResetReason.TYPED_IDENTITY_CONTINUITY_VIOLATION,
        ),
        (
            ((('routes', 3, 'typed_context_resolution'), 'failed'),),
            ResetReason.TYPED_IDENTITY_CONTINUITY_VIOLATION,
        ),
        (
            ((('continuity', 'duplicate_prevention'), 'failed'),),
            ResetReason.DUPLICATE_DIAGNOSTIC_WORK,
        ),
        (
            ((('delivery', 'incorrectly_accepted_old_generation_count'), 1),),
            ResetReason.INCORRECTLY_ACCEPTED_OLD_GENERATION,
        ),
        (
            ((('delivery', 'incorrectly_accepted_duplicate_count'), 1),),
            ResetReason.INCORRECTLY_ACCEPTED_DUPLICATE,
        ),
        (
            ((('delivery', 'incorrectly_accepted_lower_revision_count'), 1),),
            ResetReason.INCORRECTLY_ACCEPTED_LOWER_REVISION,
        ),
        (
            ((('continuity', 'reopen_accepted_identities'), 'failed'),),
            ResetReason.ACCEPTED_IDENTITY_REOPEN_FAILURE,
        ),
        (
            ((('policy', 'manual_trading_exposed'), True),),
            ResetReason.MANUAL_TRADING_EXPOSURE,
        ),
        (
            ((('policy', 'webengine_included'), True),),
            ResetReason.WEBENGINE_INCLUSION,
        ),
        (
            ((('policy', 'security_violation_count'), 1),),
            ResetReason.SECURITY_BREACH,
        ),
        (
            ((('policy', 'redaction_violation_count'), 1),),
            ResetReason.REDACTION_BREACH,
        ),
        (
            (
                (('route_incidents', 0, 'legacy_fallback_count'), 1),
                (('route_incidents', 0, 'legacy_fallback_forced'), True),
                (('route_incidents', 0, 'v2_route_caused_fallback'), True),
            ),
            ResetReason.V2_ROUTE_FORCED_LEGACY_FALLBACK,
        ),
    ],
)
def test_daily_ledger_derives_each_reset_condition_exactly(
    mutations: tuple[tuple[tuple[str | int, ...], object], ...],
    expected_reason: ResetReason,
) -> None:
    ledger = _valid_ledger()
    for path, value in mutations:
        _set_nested(ledger, path, value)

    assessment = assess_daily_observation_ledger(ledger)

    assert assessment.qualifying is False
    assert assessment.reset_reasons == (expected_reason,)
    assert "reset_condition_observed" in assessment.disqualifications


def test_route_specific_non_forced_incident_does_not_reset_window() -> None:
    ledger = _valid_ledger()
    ledger["route_incidents"][2]["legacy_fallback_count"] = 1
    ledger["route_incidents"][2]["incident_code"] = "diagnostic-route-fallback"

    assessment = assess_daily_observation_ledger(ledger)

    assert assessment.qualifying is False
    assert assessment.reset_reasons == ()
    assert "route_legacy_fallback_observed" in assessment.disqualifications


@pytest.mark.parametrize(
    ("path", "value", "disqualification"),
    [
        (
            ("continuity", "context_compatibility_failure_count"),
            1,
            "context_compatibility_failure",
        ),
        (
            ("continuity", "manifest_compatibility_failure_count"),
            1,
            "manifest_compatibility_failure",
        ),
        (
            ("health", "queue", "degradation_count"),
            1,
            "health_degradation_observed",
        ),
        (
            ("health", "cache", "degradation_count"),
            1,
            "health_degradation_observed",
        ),
        (
            ("health", "persistence", "degradation_count"),
            1,
            "health_degradation_observed",
        ),
        (
            ("health", "system_health", "degradation_count"),
            1,
            "health_degradation_observed",
        ),
    ],
)
def test_recorded_compatibility_and_health_failures_disqualify_without_reset(
    path: tuple[str | int, ...],
    value: object,
    disqualification: str,
) -> None:
    ledger = _valid_ledger()
    _set_nested(ledger, path, value)

    assessment = assess_daily_observation_ledger(ledger)

    assert assessment.qualifying is False
    assert assessment.reset_reasons == ()
    assert disqualification in assessment.disqualifications


def test_fourteen_consecutive_qualifying_days_require_both_renderer_lanes() -> None:
    first_day = date(2026, 8, 10)
    ledgers = [
        _ledger_for_day(
            first_day + timedelta(days=offset),
            renderer_lane="hardware" if offset % 2 == 0 else "software",
        )
        for offset in range(14)
    ]

    window = calculate_observation_window(ledgers)

    assert window.required_consecutive_days == 14
    assert window.current_consecutive_days == 14
    assert window.window_start_date == "2026-08-10"
    assert window.window_end_date == "2026-08-23"
    assert window.renderer_lanes == ("hardware", "software")
    assert window.fourteen_day_requirement_satisfied is True
    assert window.reset_events == ()
    assert window.interruptions == ()

    hardware_only = [
        _ledger_for_day(first_day + timedelta(days=offset))
        for offset in range(14)
    ]
    hardware_window = calculate_observation_window(hardware_only)
    assert hardware_window.current_consecutive_days == 14
    assert hardware_window.fourteen_day_requirement_satisfied is False
    assert hardware_window.renderer_lanes == ("hardware",)

    with pytest.raises(TypeError, match="required_consecutive_days"):
        calculate_observation_window(ledgers[:2], required_consecutive_days=2)


def test_observation_cannot_qualify_before_same_day_formal_publication() -> None:
    ledger = _valid_ledger()
    ledger["recorded_at"] = "2026-08-10T01:00:00Z"
    ledger["release"]["published_at"] = "2026-08-10T23:00:00Z"

    assessment = assess_daily_observation_ledger(ledger)

    assert assessment.qualifying is False
    assert "observation_precedes_formal_publication" in (
        assessment.disqualifications
    )


def test_window_interruptions_and_resets_restart_consecutive_counting() -> None:
    first_day = date(2026, 8, 10)
    pre_release = _ledger_for_day(first_day)
    pre_release["release"] = {
        "channel": "rc",
        "release_gates_passed": True,
        "package_published": False,
        "published_at": None,
    }
    before_incomplete = [
        _ledger_for_day(first_day + timedelta(days=offset))
        for offset in range(1, 4)
    ]
    incomplete = _ledger_for_day(first_day + timedelta(days=4))
    incomplete["collection"]["observed_checkpoint_ids"].remove("clean-exit")
    incomplete["lifecycle"]["clean_exit"] = "not_observed"
    reset = _ledger_for_day(first_day + timedelta(days=5))
    reset["delivery"]["incorrectly_accepted_lower_revision_count"] = 1
    restarted = [
        _ledger_for_day(
            first_day + timedelta(days=6 + offset),
            renderer_lane="hardware" if offset % 2 == 0 else "software",
        )
        for offset in range(14)
    ]

    window = calculate_observation_window(
        [pre_release, *before_incomplete, incomplete, reset, *restarted]
    )

    assert window.current_consecutive_days == 14
    assert window.window_start_date == "2026-08-16"
    assert window.window_end_date == "2026-08-29"
    assert window.fourteen_day_requirement_satisfied is True
    assert tuple(event.observation_date for event in window.interruptions) == (
        "2026-08-10",
        "2026-08-14",
    )
    assert window.reset_events[0].observation_date == "2026-08-15"
    assert window.reset_events[0].reasons == (
        ResetReason.INCORRECTLY_ACCEPTED_LOWER_REVISION,
    )


def test_active_window_rejects_artifact_or_metric_redefinition() -> None:
    first_day = date(2026, 8, 10)
    ledgers = [_ledger_for_day(first_day), _ledger_for_day(first_day + timedelta(days=1))]
    ledgers[1]["artifacts"]["candidate"]["artifact_sha256"] = f"sha256:{'f' * 64}"

    with pytest.raises(ObservationWindowError, match="artifact identity changed"):
        calculate_observation_window(ledgers)


def test_legacy_inventory_matches_both_retained_widgets_registrations() -> None:
    from app.ui.main_window import PRIMARY_WORKSPACE_PANELS
    from stock_sim.release.frontend_widgets_rollback_entry import (
        READ_ONLY_ROLLBACK_PANELS,
    )

    inventory = build_legacy_route_inventory(
        source_commit="a" * 40,
        captured_at="2026-08-10T12:00:00Z",
    )

    assert set(LEGACY_ROUTE_IDS) == set(PRIMARY_WORKSPACE_PANELS)
    assert set(LEGACY_ROUTE_IDS) == set(READ_ONLY_ROLLBACK_PANELS)
    assert validate_legacy_route_inventory(inventory) == inventory
    assert inventory["schema_version"] == LEGACY_INVENTORY_SCHEMA_VERSION
    assert inventory["legacy_route_count"] == 8
    assert inventory["widgets_shell_status"] == "retained"
    assert inventory["deletion_authorized"] is False
    assert inventory["clean_windows_gate_passed"] is False
    assert tuple(route["legacy_route_id"] for route in inventory["routes"]) == (
        LEGACY_ROUTE_IDS
    )
    assert all(route["status"] == "retained" for route in inventory["routes"])
    assert all(
        route["stakeholder_exit_record_id"] is None
        and route["route_rollback_drill_id"] is None
        and route["atomic_exit_authorized"] is False
        for route in inventory["routes"]
    )
    assert legacy_route_inventory_sha256(inventory).startswith("sha256:")

    deletion_claim = deepcopy(inventory)
    deletion_claim["deletion_authorized"] = True
    with pytest.raises(ValueError, match="not authorized"):
        validate_legacy_route_inventory(deletion_claim)

    missing_route = deepcopy(inventory)
    missing_route["routes"].pop()
    missing_route["legacy_route_count"] = 7
    with pytest.raises(ValueError, match="legacy_route_count"):
        validate_legacy_route_inventory(missing_route)


def test_daily_ledger_collection_is_canonical_idempotent_and_collision_safe(
    tmp_path,
) -> None:
    ledger = _valid_ledger()

    collected = collect_daily_observation_ledger(ledger, output_directory=tmp_path)

    assert collected.assessment.qualifying is True
    assert collected.sha256.startswith("sha256:")
    payload_on_disk = json.loads(collected.path.read_text(encoding="utf-8"))
    assert payload_on_disk == ledger
    assert "credential" not in collected.path.read_text(encoding="utf-8").casefold()
    assert collect_daily_observation_ledger(
        deepcopy(ledger),
        output_directory=tmp_path,
    ) == collected

    collision = deepcopy(ledger)
    collision["delivery"]["disconnect_count"] = 1
    with pytest.raises(LedgerCollectionError, match="different content"):
        collect_daily_observation_ledger(collision, output_directory=tmp_path)

    reserved = _valid_ledger()
    reserved["ledger_id"] = "CON"
    reserved_collected = collect_daily_observation_ledger(
        reserved,
        output_directory=tmp_path / "reserved",
    )
    assert reserved_collected.path.name != "CON.json"
    assert reserved_collected.path.name.startswith("ledger-")


def test_collection_can_retain_incomplete_day_but_reject_it_as_qualifying(
    tmp_path,
) -> None:
    incomplete = _valid_ledger()
    incomplete["collection"]["observed_checkpoint_ids"].remove("clean-exit")
    incomplete["lifecycle"]["clean_exit"] = "not_observed"

    collected = collect_daily_observation_ledger(
        incomplete,
        output_directory=tmp_path,
    )
    assert collected.assessment.complete is False
    assert collected.assessment.qualifying is False

    with pytest.raises(LedgerCollectionError, match="does not qualify"):
        collect_daily_observation_ledger(
            incomplete,
            output_directory=tmp_path / "formal-only",
            require_qualifying=True,
        )


def test_machine_readable_validator_cli_never_echoes_input_paths(
    tmp_path,
    capsys,
) -> None:
    valid_path = tmp_path / "valid-ledger.json"
    valid_path.write_text(json.dumps(_valid_ledger()), encoding="utf-8")

    assert ledger_cli_main(["--require-qualifying", str(valid_path)]) == 0
    accepted = json.loads(capsys.readouterr().out)
    assert accepted["schema_version"] == "wave4.ledger-validator-output.v1"
    assert accepted["status"] == "accepted"
    assert accepted["assessments"][0]["qualifying"] is True
    assert str(tmp_path) not in json.dumps(accepted)

    unsafe = _valid_ledger()
    unsafe["credential"] = "do-not-record"
    unsafe_path = tmp_path / "unsafe-ledger.json"
    unsafe_path.write_text(json.dumps(unsafe), encoding="utf-8")
    assert ledger_cli_main([str(unsafe_path)]) == 2
    rejected = json.loads(capsys.readouterr().out)
    assert rejected["status"] == "invalid"
    assert rejected["error_code"] == "ledger_validation_error"
    assert str(tmp_path) not in json.dumps(rejected)
