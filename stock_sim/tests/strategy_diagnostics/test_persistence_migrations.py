from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from strategy_diagnostics import (
    AdmissionCheck,
    HistoricalSegmentSelection,
    HistoricalSourceInspection,
    InMemoryHistoricalSource,
    SourceArtifact,
    SourceProvenance,
    create_diagnostics_application,
)
from strategy_diagnostics.persistence import SqlHistoricalSegmentCatalog

REQUIRED_CHECKS = (
    "bar_continuity",
    "instrument_coverage",
    "eligible_universe",
    "trading_status",
    "st_status",
    "suspension_state",
    "industry_as_of",
    "adjustment_consistency",
    "causal_availability",
    "required_fields",
    "missing_data",
    "duplicates",
    "timestamps",
)


def _column_contract(engine: object, table_name: str) -> list[tuple[object, ...]]:
    return [
        (
            column["name"],
            str(column["type"]),
            column["nullable"],
            column["default"],
            column["primary_key"],
        )
        for column in inspect(engine).get_columns(table_name)
    ]


def test_diagnostic_migration_baseline_preserves_legacy_tables(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'diagnostics.db'}", future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE legacy_accounts ("
            "id INTEGER PRIMARY KEY, owner VARCHAR(64) NOT NULL, balance INTEGER NOT NULL"
            ")"
        )
        connection.execute(
            text(
                "INSERT INTO legacy_accounts (id, owner, balance) "
                "VALUES (1, 'existing-user', 125000)"
            )
        )

    columns_before = _column_contract(engine, "legacy_accounts")

    application = create_diagnostics_application()
    application.start()
    first = application.initialize_persistence(engine)
    second = application.initialize_persistence(engine)

    assert (
        first.current_revision
        == "0018_diagnostic_campaign_attempt_history"
    )
    assert first.applied_revisions == (
        "0001_diagnostics_baseline",
        "0002_historical_segment_catalog",
        "0003_scenario_recipe_lifecycle",
        "0004_ai_recipe_assistant",
        "0005_strategy_runs",
        "0006_a_share_execution_audit",
        "0007_execution_stress_audit",
        "0008_ptrade_host_audit",
        "0009_isolated_sensitivity_sets",
        "0010_formal_diagnostic_campaigns",
        "0011_diagnostic_evidence",
        "0012_reproduction_manifests",
        "0013_diagnostic_tasks",
        "0014_diagnostic_task_approval",
        "0015_diagnostic_task_campaign_handoff",
        "0016_diagnostic_task_start_continuation_claim",
        "0017_diagnostic_lifecycle_targets",
        "0018_diagnostic_campaign_attempt_history",
    )
    assert (
        second.current_revision
        == "0018_diagnostic_campaign_attempt_history"
    )
    assert second.applied_revisions == ()
    assert application.status().persistence_status == "ready"
    assert (
        application.status().persistence_revision
        == "0018_diagnostic_campaign_attempt_history"
    )
    assert _column_contract(engine, "legacy_accounts") == columns_before
    with engine.connect() as connection:
        legacy_row = connection.execute(
            text("SELECT id, owner, balance FROM legacy_accounts")
        ).one()
        revisions = connection.execute(
            text(
                "SELECT revision FROM diagnostic_schema_migrations "
                "ORDER BY revision"
            )
        ).scalars().all()
    assert legacy_row == (1, "existing-user", 125000)
    assert revisions == [
        "0001_diagnostics_baseline",
        "0002_historical_segment_catalog",
        "0003_scenario_recipe_lifecycle",
        "0004_ai_recipe_assistant",
        "0005_strategy_runs",
        "0006_a_share_execution_audit",
        "0007_execution_stress_audit",
        "0008_ptrade_host_audit",
        "0009_isolated_sensitivity_sets",
        "0010_formal_diagnostic_campaigns",
        "0011_diagnostic_evidence",
        "0012_reproduction_manifests",
        "0013_diagnostic_tasks",
        "0014_diagnostic_task_approval",
        "0015_diagnostic_task_campaign_handoff",
        "0016_diagnostic_task_start_continuation_claim",
        "0017_diagnostic_lifecycle_targets",
        "0018_diagnostic_campaign_attempt_history",
    ]
    strategy_run_columns = {
        column["name"]
        for column in inspect(engine).get_columns("diagnostic_strategy_runs")
    }
    assert {
        "ptrade_surface_version",
        "ptrade_manifest_hash",
        "ptrade_host_adapter_version",
        "ptrade_host_audit_json",
    } <= strategy_run_columns
    assert {
        "diagnostic_source_snapshots",
        "diagnostic_historical_segments",
        "diagnostic_recipe_drafts",
        "diagnostic_recipe_validations",
        "diagnostic_recipe_approvals",
        "diagnostic_recipe_versions",
        "diagnostic_ai_recipe_attempts",
        "diagnostic_strategy_runs",
        "diagnostic_isolated_sensitivity_sets",
        "diagnostic_campaigns",
        "diagnostic_guardrail_profiles",
        "diagnostic_evidence_packages",
        "diagnostic_findings",
        "diagnostic_reproduction_manifests",
        "diagnostic_reproduction_attempts",
        "diagnostic_tasks",
        "diagnostic_task_commands",
        "diagnostic_task_handles",
        "diagnostic_task_sequences",
        "diagnostic_task_configuration_revisions",
        "diagnostic_task_command_identities",
        "diagnostic_task_validations",
        "diagnostic_task_approvals",
        "diagnostic_task_mutation_commands",
        "diagnostic_task_campaign_handoffs",
        "diagnostic_lifecycle_targets",
        "diagnostic_run_orders",
        "diagnostic_run_fills",
        "diagnostic_run_positions",
        "diagnostic_run_equity",
    }.issubset(set(inspect(engine).get_table_names()))


def test_issue_58_migration_upgrades_and_backfills_issue_57_tasks(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'issue-57-upgrade.db'}",
        future=True,
    )
    application = create_diagnostics_application()
    application.start()
    application.initialize_persistence(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO diagnostic_tasks ("
                "task_id, creation_sequence, revision, lifecycle, "
                "schema_version, configuration_content_id, "
                "configuration_json, created_at_utc, updated_at_utc"
                ") VALUES ("
                "'diagnostic-task-upgrade-58', 1, 2, 'draft', '1.0', "
                "'sha256:configuration-upgrade-58', '{}', "
                "'2030-01-01T00:00:00+00:00', "
                "'2030-01-02T00:00:00+00:00')"
            )
        )
        for table_name in (
            "diagnostic_task_mutation_commands",
            "diagnostic_task_approvals",
            "diagnostic_task_validations",
            "diagnostic_task_configuration_revisions",
            "diagnostic_task_command_identities",
        ):
            connection.exec_driver_sql(f"DROP TABLE {table_name}")
        connection.execute(
            text(
                "DELETE FROM diagnostic_schema_migrations "
                "WHERE revision = '0014_diagnostic_task_approval'"
            )
        )

    report = application.initialize_persistence(engine)

    assert (
        report.current_revision
        == "0018_diagnostic_campaign_attempt_history"
    )
    assert report.applied_revisions == ("0014_diagnostic_task_approval",)
    with engine.connect() as connection:
        backfilled = connection.execute(
            text(
                "SELECT task_id, revision, configuration_content_id, "
                "configuration_json, accepted_command_id, created_at_utc "
                "FROM diagnostic_task_configuration_revisions"
            )
        ).mappings().one()
    assert dict(backfilled) == {
        "task_id": "diagnostic-task-upgrade-58",
        "revision": 2,
        "configuration_content_id": "sha256:configuration-upgrade-58",
        "configuration_json": "{}",
        "accepted_command_id": None,
        "created_at_utc": "2030-01-02T00:00:00+00:00",
    }
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT COUNT(*) "
                "FROM diagnostic_task_command_identities"
            )
        ).scalar_one() == 0


def test_issue_59_migration_adds_durable_campaign_handoff_without_rewriting_0014(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'issue-58-upgrade.db'}",
        future=True,
    )
    application = create_diagnostics_application()
    application.start()
    application.initialize_persistence(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DROP TABLE diagnostic_task_campaign_handoffs"
        )
        connection.execute(
            text(
                "DELETE FROM diagnostic_schema_migrations "
                "WHERE revision IN ("
                "'0015_diagnostic_task_campaign_handoff', "
                "'0016_diagnostic_task_start_continuation_claim')"
            )
        )
        revision_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM diagnostic_schema_migrations "
                "WHERE revision = '0014_diagnostic_task_approval'"
            )
        ).scalar_one()
    assert revision_count == 1

    report = application.initialize_persistence(engine)

    assert (
        report.current_revision
        == "0018_diagnostic_campaign_attempt_history"
    )
    assert report.applied_revisions == (
        "0015_diagnostic_task_campaign_handoff",
        "0016_diagnostic_task_start_continuation_claim",
    )
    assert "diagnostic_task_campaign_handoffs" in set(
        inspect(engine).get_table_names()
    )
    handle_columns = {
        column["name"]
        for column in inspect(engine).get_columns(
            "diagnostic_task_handles"
        )
    }
    assert {
        "start_continuation_claim_id",
        "start_continuation_claimed_at_utc",
    }.issubset(handle_columns)


def test_issue_60_migration_backfills_lifecycle_targets_idempotently(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'issue-59-upgrade.db'}",
        future=True,
    )
    application = create_diagnostics_application()
    application.start()
    application.initialize_persistence(engine)
    handoff = {
        "campaign_id": "formal-campaign-upgrade-60",
        "campaign_nodes": [
            {
                "active_attempt_id": "attempt-completed-60",
                "attempts": [
                    {
                        "attempt_id": "attempt-completed-60",
                        "runs": [],
                    }
                ],
                "campaign_case_id": "case-completed-60",
                "campaign_node_id": "node-completed-60",
                "market_scenario_id": "scenario-completed-60",
                "selected_campaign_case_id": "case-completed-60",
            },
            {
                "active_attempt_id": None,
                "attempts": [],
                "campaign_case_id": "case-queued-60",
                "campaign_node_id": "node-queued-60",
                "market_scenario_id": "scenario-queued-60",
                "selected_campaign_case_id": "case-queued-60",
            },
        ],
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO diagnostic_tasks ("
                "task_id, creation_sequence, revision, lifecycle, "
                "schema_version, configuration_content_id, "
                "configuration_json, created_at_utc, updated_at_utc"
                ") VALUES ("
                "'diagnostic-task-upgrade-60', 1, 7, 'running', '1.0', "
                "'sha256:configuration-upgrade-60', '{}', "
                "'2030-01-01T00:00:00+00:00', "
                "'2030-01-02T00:00:00+00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO diagnostic_task_campaign_handoffs ("
                "task_id, campaign_id, handoff_json, updated_at_utc"
                ") VALUES ("
                "'diagnostic-task-upgrade-60', "
                "'formal-campaign-upgrade-60', :handoff_json, "
                "'2030-01-02T00:00:00+00:00')"
            ),
            {
                "handoff_json": json.dumps(
                    handoff,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            },
        )
        connection.exec_driver_sql("DROP TABLE diagnostic_lifecycle_targets")
        connection.execute(
            text(
                "DELETE FROM diagnostic_schema_migrations "
                "WHERE revision = '0017_diagnostic_lifecycle_targets'"
            )
        )

    first = application.initialize_persistence(engine)

    assert first.applied_revisions == (
        "0017_diagnostic_lifecycle_targets",
    )
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT target_kind, target_id, revision, lifecycle "
                "FROM diagnostic_lifecycle_targets "
                "ORDER BY target_kind, target_id"
            )
        ).all()
    assert rows == [
        ("campaign_node", "node-completed-60", 1, "completed"),
        ("campaign_node", "node-queued-60", 1, "queued"),
        (
            "diagnostic_task",
            "diagnostic-task-upgrade-60",
            7,
            "running",
        ),
        (
            "formal_diagnostic_campaign",
            "formal-campaign-upgrade-60",
            1,
            "running",
        ),
    ]
    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM diagnostic_schema_migrations "
                "WHERE revision = '0017_diagnostic_lifecycle_targets'"
            )
        )

    second = application.initialize_persistence(engine)

    assert second.applied_revisions == (
        "0017_diagnostic_lifecycle_targets",
    )
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM diagnostic_lifecycle_targets")
        ).scalar_one() == 4


def test_issue_61_migration_backfills_attempt_lineage_idempotently(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'issue-60-upgrade.db'}",
        future=True,
    )
    application = create_diagnostics_application()
    application.start()
    application.initialize_persistence(engine)
    legacy_handoff = {
        "campaign_id": "formal-campaign-upgrade-61",
        "campaign_lifecycle": "failed",
        "campaign_revision": 3,
        "campaign_nodes": [
            {
                "active_attempt_id": "attempt-2-upgrade-61",
                "attempts": [
                    {"attempt_id": "attempt-1-upgrade-61", "runs": []},
                    {"attempt_id": "attempt-2-upgrade-61", "runs": []},
                ],
                "campaign_case_id": "case-upgrade-61",
                "campaign_node_id": "node-upgrade-61",
                "lifecycle": "failed",
                "market_scenario_id": "scenario-upgrade-61",
                "revision": 4,
                "selected_campaign_case_id": "case-upgrade-61",
            }
        ],
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO diagnostic_tasks ("
                "task_id, creation_sequence, revision, lifecycle, "
                "schema_version, configuration_content_id, "
                "configuration_json, created_at_utc, updated_at_utc"
                ") VALUES ("
                "'diagnostic-task-upgrade-61', 1, 7, 'failed', '1.0', "
                "'sha256:configuration-upgrade-61', '{}', "
                "'2030-01-01T00:00:00+00:00', "
                "'2030-01-02T00:00:00+00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO diagnostic_task_campaign_handoffs ("
                "task_id, campaign_id, handoff_json, updated_at_utc"
                ") VALUES ("
                "'diagnostic-task-upgrade-61', "
                "'formal-campaign-upgrade-61', :handoff_json, "
                "'2030-01-02T00:00:00+00:00')"
            ),
            {
                "handoff_json": json.dumps(
                    legacy_handoff,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            },
        )
        connection.execute(
            text(
                "DELETE FROM diagnostic_schema_migrations "
                "WHERE revision = "
                "'0018_diagnostic_campaign_attempt_history'"
            )
        )

    first = application.initialize_persistence(engine)

    assert first.applied_revisions == (
        "0018_diagnostic_campaign_attempt_history",
    )
    with engine.connect() as connection:
        first_json = str(
            connection.execute(
                text(
                    "SELECT handoff_json "
                    "FROM diagnostic_task_campaign_handoffs "
                    "WHERE task_id = 'diagnostic-task-upgrade-61'"
                )
            ).scalar_one()
        )
    payload = json.loads(first_json)
    attempts = payload["campaign_nodes"][0]["attempts"]
    assert attempts == [
        {
            "attempt_id": "attempt-1-upgrade-61",
            "attempt_number": 1,
            "failure_code": None,
            "failure_message": None,
            "lifecycle": "completed",
            "predecessor_attempt_id": None,
            "runs": [],
            "task_handle_id": None,
        },
        {
            "attempt_id": "attempt-2-upgrade-61",
            "attempt_number": 2,
            "failure_code": "IncompleteCampaign",
            "failure_message": "Campaign result is incomplete",
            "lifecycle": "failed",
            "predecessor_attempt_id": "attempt-1-upgrade-61",
            "runs": [],
            "task_handle_id": None,
        },
    ]
    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM diagnostic_schema_migrations "
                "WHERE revision = "
                "'0018_diagnostic_campaign_attempt_history'"
            )
        )

    second = application.initialize_persistence(engine)

    assert second.applied_revisions == (
        "0018_diagnostic_campaign_attempt_history",
    )
    with engine.connect() as connection:
        second_json = str(
            connection.execute(
                text(
                    "SELECT handoff_json "
                    "FROM diagnostic_task_campaign_handoffs "
                    "WHERE task_id = 'diagnostic-task-upgrade-61'"
                )
            ).scalar_one()
        )
    assert second_json == first_json


def test_admitted_segment_catalog_survives_application_restart(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'diagnostics.db'}", future=True)
    selection = HistoricalSegmentSelection(
        market="mainland-a-share",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
    )
    inspection_result = HistoricalSourceInspection(
        selection=selection,
        label="Durable development interval",
        provenance=SourceProvenance(
            provider="BaoStock",
            dataset="restart-fixture",
            version="v1",
            observed_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
        ),
        artifacts=(SourceArtifact("bars", "a" * 64, 100),),
        eligible_instrument_count=2,
        trading_day_count=2,
        bar_count=100,
        checks=tuple(
            AdmissionCheck(code, True, f"{code} passed")
            for code in REQUIRED_CHECKS
        ),
    )
    source = InMemoryHistoricalSource((inspection_result,))

    first_application = create_diagnostics_application(historical_source=source)
    first_application.start()
    first_application.initialize_persistence(engine)
    admitted = first_application.admit_historical_segment(selection)

    restarted_application = create_diagnostics_application(historical_source=source)
    restarted_application.start()
    restarted_application.initialize_persistence(engine)

    assert admitted.segment is not None
    assert admitted.source_snapshot is not None
    assert restarted_application.list_historical_segments() == (admitted.segment,)
    assert restarted_application.recommend_historical_segments()[0].segment == admitted.segment
    catalog = SqlHistoricalSegmentCatalog(engine)
    assert catalog.get_source_snapshot(
        admitted.source_snapshot.snapshot_id
    ) == admitted.source_snapshot

    provenance = admitted.source_snapshot.provenance.to_dict()
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_source_snapshots "
                "SET provenance_json = :provenance_json "
                "WHERE snapshot_id = :snapshot_id"
            ),
            {
                "provenance_json": json.dumps(
                    {**provenance, "unexpected": "must fail closed"},
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "snapshot_id": admitted.source_snapshot.snapshot_id,
            },
        )
    with pytest.raises(ValueError, match="provenance schema mismatch"):
        catalog.get_source_snapshot(admitted.source_snapshot.snapshot_id)

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE diagnostic_source_snapshots "
                "SET provenance_json = :provenance_json "
                "WHERE snapshot_id = :snapshot_id"
            ),
            {
                "provenance_json": json.dumps(
                    {
                        **provenance,
                        "observed_at": "2026-07-21T00:00:00",
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "snapshot_id": admitted.source_snapshot.snapshot_id,
            },
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        catalog.get_source_snapshot(admitted.source_snapshot.snapshot_id)


def test_diagnostic_migration_rejects_an_unknown_future_revision(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'future.db'}", future=True)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE diagnostic_schema_migrations ("
            "revision VARCHAR(128) PRIMARY KEY NOT NULL, "
            "applied_at_utc VARCHAR(64) NOT NULL"
            ")"
        )
        connection.execute(
            text(
                "INSERT INTO diagnostic_schema_migrations "
                "(revision, applied_at_utc) VALUES "
                "('9999_future_schema', '2030-01-01T00:00:00+00:00')"
            )
        )

    application = create_diagnostics_application()
    application.start()

    with pytest.raises(ValueError, match="incompatible diagnostic schema"):
        application.initialize_persistence(engine)
    assert "diagnostic_tasks" not in inspect(engine).get_table_names()
