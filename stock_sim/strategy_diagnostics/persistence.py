"""Versioned persistence baseline owned by the diagnostic product path."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Final, Literal, cast

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from .historical_segments import (
    HistoricalMarketSegment,
    HistoricalSegmentSelection,
    SegmentAdmissionReport,
    SourceProvenance,
    SourceSnapshot,
)
from .recipes import (
    AIRecipeAssistantAttempt,
    ApprovedScenarioRecipeVersion,
    RecipeValidationIssue,
    RecipeValidationResult,
    ScenarioRecipeDraft,
    ScenarioRecipeV1,
    TransformationProposalV1,
)


_HISTORICAL_SEGMENT_REVISION: Final = "0002_historical_segment_catalog"
_SCENARIO_RECIPE_REVISION: Final = "0003_scenario_recipe_lifecycle"
_AI_RECIPE_ASSISTANT_REVISION: Final = "0004_ai_recipe_assistant"
_STRATEGY_RUN_REVISION: Final = "0005_strategy_runs"
_A_SHARE_EXECUTION_REVISION: Final = "0006_a_share_execution_audit"
_EXECUTION_STRESS_REVISION: Final = "0007_execution_stress_audit"
DIAGNOSTIC_SCHEMA_REVISION: Final = "0008_ptrade_host_audit"
_MIGRATION_TABLE: Final = "diagnostic_schema_migrations"
_MIGRATION_REVISIONS: Final = (
    "0001_diagnostics_baseline",
    _HISTORICAL_SEGMENT_REVISION,
    _SCENARIO_RECIPE_REVISION,
    _AI_RECIPE_ASSISTANT_REVISION,
    _STRATEGY_RUN_REVISION,
    _A_SHARE_EXECUTION_REVISION,
    _EXECUTION_STRESS_REVISION,
    DIAGNOSTIC_SCHEMA_REVISION,
)


@dataclass(frozen=True, slots=True)
class DiagnosticMigrationReport:
    current_revision: str
    applied_revisions: tuple[str, ...]


def initialize_diagnostic_persistence(engine: Engine) -> DiagnosticMigrationReport:
    """Apply diagnostic-only migrations without touching legacy metadata."""

    applied_revisions: list[str] = []
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE TABLE IF NOT EXISTS {_MIGRATION_TABLE} ("
            "revision VARCHAR(128) PRIMARY KEY NOT NULL, "
            "applied_at_utc VARCHAR(64) NOT NULL"
            ")"
        )
        existing_revisions = set(
            connection.execute(
                text(f"SELECT revision FROM {_MIGRATION_TABLE}")
            ).scalars()
        )
        for revision in _MIGRATION_REVISIONS:
            if revision in existing_revisions:
                continue
            if revision == _HISTORICAL_SEGMENT_REVISION:
                _create_historical_segment_catalog(connection)
            elif revision == _SCENARIO_RECIPE_REVISION:
                _create_scenario_recipe_lifecycle(connection)
            elif revision == _AI_RECIPE_ASSISTANT_REVISION:
                _create_ai_recipe_assistant_audit(connection)
            elif revision == _STRATEGY_RUN_REVISION:
                _create_strategy_run_facts(connection)
            elif revision == _A_SHARE_EXECUTION_REVISION:
                _add_a_share_execution_audit(connection)
            elif revision == _EXECUTION_STRESS_REVISION:
                _add_execution_stress_audit(connection)
            elif revision == DIAGNOSTIC_SCHEMA_REVISION:
                _add_ptrade_host_audit(connection)
            connection.execute(
                text(
                    f"INSERT INTO {_MIGRATION_TABLE} "
                    "(revision, applied_at_utc) VALUES (:revision, :applied_at_utc)"
                ),
                {
                    "revision": revision,
                    "applied_at_utc": datetime.now(timezone.utc).isoformat(),
                },
            )
            applied_revisions.append(revision)

    return DiagnosticMigrationReport(
        current_revision=DIAGNOSTIC_SCHEMA_REVISION,
        applied_revisions=tuple(applied_revisions),
    )


def _create_historical_segment_catalog(connection: Connection) -> None:
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS diagnostic_source_snapshots ("
        "snapshot_id VARCHAR(64) PRIMARY KEY NOT NULL, "
        "content_hash VARCHAR(64) UNIQUE NOT NULL, "
        "provenance_json TEXT NOT NULL, "
        "artifacts_json TEXT NOT NULL, "
        "created_at_utc VARCHAR(64) NOT NULL"
        ")"
    )
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS diagnostic_historical_segments ("
        "segment_id VARCHAR(64) PRIMARY KEY NOT NULL, "
        "content_hash VARCHAR(64) UNIQUE NOT NULL, "
        "source_snapshot_id VARCHAR(64) NOT NULL, "
        "market VARCHAR(64) NOT NULL, "
        "start_date VARCHAR(10) NOT NULL, "
        "end_date VARCHAR(10) NOT NULL, "
        "label VARCHAR(256) NOT NULL, "
        "eligible_instrument_count INTEGER NOT NULL, "
        "trading_day_count INTEGER NOT NULL, "
        "bar_count INTEGER NOT NULL, "
        "recommendation_tags_json TEXT NOT NULL, "
        "admission_report_json TEXT NOT NULL, "
        "created_at_utc VARCHAR(64) NOT NULL, "
        "FOREIGN KEY(source_snapshot_id) "
        "REFERENCES diagnostic_source_snapshots(snapshot_id)"
        ")"
    )


def _create_scenario_recipe_lifecycle(connection: Connection) -> None:
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS diagnostic_recipe_drafts ("
        "draft_id VARCHAR(96) PRIMARY KEY NOT NULL, "
        "recipe_id VARCHAR(96) NOT NULL, "
        "author VARCHAR(256) NOT NULL, "
        "created_at_utc VARCHAR(64) NOT NULL, "
        "payload_json TEXT NOT NULL, "
        "payload_hash VARCHAR(64) NOT NULL, "
        "based_on_version_id VARCHAR(96) NULL"
        ")"
    )
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS diagnostic_recipe_validations ("
        "draft_id VARCHAR(96) PRIMARY KEY NOT NULL, "
        "payload_hash VARCHAR(64) NOT NULL, "
        "is_valid INTEGER NOT NULL, "
        "issues_json TEXT NOT NULL, "
        "recipe_content_hash VARCHAR(64) NULL, "
        "validated_at_utc VARCHAR(64) NOT NULL, "
        "validated_recipe_json TEXT NULL, "
        "FOREIGN KEY(draft_id) REFERENCES diagnostic_recipe_drafts(draft_id)"
        ")"
    )
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS diagnostic_recipe_approvals ("
        "approval_id VARCHAR(96) PRIMARY KEY NOT NULL, "
        "draft_id VARCHAR(96) UNIQUE NOT NULL, "
        "actor VARCHAR(256) NOT NULL, "
        "approved_at_utc VARCHAR(64) NOT NULL, "
        "recipe_content_hash VARCHAR(64) NOT NULL, "
        "FOREIGN KEY(draft_id) REFERENCES diagnostic_recipe_drafts(draft_id)"
        ")"
    )
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS diagnostic_recipe_versions ("
        "version_id VARCHAR(96) PRIMARY KEY NOT NULL, "
        "recipe_id VARCHAR(96) NOT NULL, "
        "version_number INTEGER NOT NULL, "
        "recipe_json TEXT NOT NULL, "
        "content_hash VARCHAR(64) NOT NULL, "
        "author VARCHAR(256) NOT NULL, "
        "approval_id VARCHAR(96) UNIQUE NOT NULL, "
        "validation_draft_id VARCHAR(96) NOT NULL, "
        "validation_json TEXT NOT NULL, "
        "based_on_version_id VARCHAR(96) NULL, "
        "UNIQUE(recipe_id, version_number), "
        "FOREIGN KEY(approval_id) REFERENCES diagnostic_recipe_approvals(approval_id), "
        "FOREIGN KEY(validation_draft_id) "
        "REFERENCES diagnostic_recipe_validations(draft_id)"
        ")"
    )


def _create_ai_recipe_assistant_audit(connection: Connection) -> None:
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS diagnostic_ai_recipe_attempts ("
        "attempt_id VARCHAR(96) PRIMARY KEY NOT NULL, "
        "intent TEXT NOT NULL, "
        "author VARCHAR(256) NOT NULL, "
        "provider VARCHAR(128) NOT NULL, "
        "model VARCHAR(256) NOT NULL, "
        "prompt_template_version VARCHAR(128) NOT NULL, "
        "response_id VARCHAR(256) NULL, "
        "response_hash VARCHAR(64) NULL, "
        "status VARCHAR(32) NOT NULL, "
        "created_at_utc VARCHAR(64) NOT NULL, "
        "draft_id VARCHAR(96) UNIQUE NULL, "
        "transformation_proposals_json TEXT NOT NULL, "
        "error_code VARCHAR(128) NULL, "
        "error_message TEXT NULL, "
        "FOREIGN KEY(draft_id) REFERENCES diagnostic_recipe_drafts(draft_id)"
        ")"
    )


def _create_strategy_run_facts(connection: Connection) -> None:
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS diagnostic_strategy_runs ("
        "run_id VARCHAR(96) PRIMARY KEY NOT NULL, "
        "status VARCHAR(32) NOT NULL, "
        "materialization_hash VARCHAR(64) NOT NULL, "
        "recipe_version_id VARCHAR(96) NOT NULL, "
        "strategy_id VARCHAR(128) NOT NULL, "
        "strategy_version VARCHAR(128) NOT NULL, "
        "decision_cadence_minutes INTEGER NOT NULL, "
        "current_simulation_time VARCHAR(64) NULL, "
        "next_node_index INTEGER NOT NULL, "
        "state_json TEXT NOT NULL, "
        "run_artifact_hash VARCHAR(64) NULL, "
        "failure_code VARCHAR(128) NULL, "
        "failure_message TEXT NULL, "
        "updated_at_utc VARCHAR(64) NOT NULL"
        ")"
    )
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS diagnostic_run_orders ("
        "order_id VARCHAR(160) PRIMARY KEY NOT NULL, "
        "run_id VARCHAR(96) NOT NULL, "
        "instrument VARCHAR(32) NOT NULL, "
        "shares INTEGER NOT NULL, "
        "decision_time VARCHAR(64) NOT NULL, "
        "activation_time VARCHAR(64) NOT NULL, "
        "status VARCHAR(32) NOT NULL, "
        "rejection_reason VARCHAR(128) NULL, "
        "FOREIGN KEY(run_id) REFERENCES diagnostic_strategy_runs(run_id)"
        ")"
    )
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS diagnostic_run_fills ("
        "fill_id VARCHAR(192) PRIMARY KEY NOT NULL, "
        "run_id VARCHAR(96) NOT NULL, "
        "order_id VARCHAR(160) NOT NULL, "
        "instrument VARCHAR(32) NOT NULL, "
        "shares INTEGER NOT NULL, "
        "price VARCHAR(64) NOT NULL, "
        "gross_value VARCHAR(64) NOT NULL, "
        "simulation_time VARCHAR(64) NOT NULL, "
        "FOREIGN KEY(run_id) REFERENCES diagnostic_strategy_runs(run_id), "
        "FOREIGN KEY(order_id) REFERENCES diagnostic_run_orders(order_id)"
        ")"
    )
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS diagnostic_run_positions ("
        "run_id VARCHAR(96) NOT NULL, "
        "instrument VARCHAR(32) NOT NULL, "
        "shares INTEGER NOT NULL, "
        "total_cost VARCHAR(64) NOT NULL, "
        "PRIMARY KEY(run_id, instrument), "
        "FOREIGN KEY(run_id) REFERENCES diagnostic_strategy_runs(run_id)"
        ")"
    )
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS diagnostic_run_equity ("
        "run_id VARCHAR(96) NOT NULL, "
        "simulation_time VARCHAR(64) NOT NULL, "
        "cash VARCHAR(64) NOT NULL, "
        "positions_value VARCHAR(64) NOT NULL, "
        "equity VARCHAR(64) NOT NULL, "
        "PRIMARY KEY(run_id, simulation_time), "
        "FOREIGN KEY(run_id) REFERENCES diagnostic_strategy_runs(run_id)"
        ")"
    )


def _add_a_share_execution_audit(connection: Connection) -> None:
    for statement in (
        "ALTER TABLE diagnostic_run_orders ADD COLUMN accepted_shares INTEGER "
        "NOT NULL DEFAULT 0",
        "ALTER TABLE diagnostic_run_orders ADD COLUMN reason_code VARCHAR(128) NULL",
        "ALTER TABLE diagnostic_run_orders ADD COLUMN reason_message TEXT NULL",
        "ALTER TABLE diagnostic_run_orders ADD COLUMN execution_price VARCHAR(64) NULL",
        "ALTER TABLE diagnostic_run_orders ADD COLUMN price_limit_lower VARCHAR(64) NULL",
        "ALTER TABLE diagnostic_run_orders ADD COLUMN price_limit_upper VARCHAR(64) NULL",
        "ALTER TABLE diagnostic_run_orders ADD COLUMN cash_change VARCHAR(64) "
        "NOT NULL DEFAULT '0'",
        "ALTER TABLE diagnostic_run_orders ADD COLUMN position_change INTEGER "
        "NOT NULL DEFAULT 0",
        "ALTER TABLE diagnostic_run_orders ADD COLUMN "
        "sellable_shares_change INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE diagnostic_run_fills ADD COLUMN commission VARCHAR(64) "
        "NOT NULL DEFAULT '0'",
        "ALTER TABLE diagnostic_run_fills ADD COLUMN transfer_fee VARCHAR(64) "
        "NOT NULL DEFAULT '0'",
        "ALTER TABLE diagnostic_run_fills ADD COLUMN stamp_duty VARCHAR(64) "
        "NOT NULL DEFAULT '0'",
        "ALTER TABLE diagnostic_run_fills ADD COLUMN total_fee VARCHAR(64) "
        "NOT NULL DEFAULT '0'",
        "ALTER TABLE diagnostic_run_fills ADD COLUMN cash_change VARCHAR(64) "
        "NOT NULL DEFAULT '0'",
        "ALTER TABLE diagnostic_run_positions ADD COLUMN "
        "t_plus_one_locked_shares INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE diagnostic_run_positions ADD COLUMN "
        "lock_session_date VARCHAR(10) NULL",
    ):
        connection.exec_driver_sql(statement)


def _add_execution_stress_audit(connection: Connection) -> None:
    for statement in (
        "ALTER TABLE diagnostic_strategy_runs ADD COLUMN "
        "requested_execution_json TEXT NULL",
        "ALTER TABLE diagnostic_strategy_runs ADD COLUMN "
        "effective_execution_json TEXT NULL",
        "ALTER TABLE diagnostic_strategy_runs ADD COLUMN "
        "execution_overrides_json TEXT NULL",
        "ALTER TABLE diagnostic_run_orders ADD COLUMN unfilled_shares INTEGER "
        "NOT NULL DEFAULT 0",
        "ALTER TABLE diagnostic_run_orders ADD COLUMN reference_price VARCHAR(64) NULL",
        "ALTER TABLE diagnostic_run_orders ADD COLUMN slippage_bps VARCHAR(64) "
        "NOT NULL DEFAULT '0'",
        "ALTER TABLE diagnostic_run_fills ADD COLUMN reference_price VARCHAR(64) NULL",
        "ALTER TABLE diagnostic_run_fills ADD COLUMN slippage_bps VARCHAR(64) "
        "NOT NULL DEFAULT '0'",
        "ALTER TABLE diagnostic_run_fills ADD COLUMN execution_erosion VARCHAR(64) "
        "NOT NULL DEFAULT '0'",
    ):
        connection.exec_driver_sql(statement)


def _add_ptrade_host_audit(connection: Connection) -> None:
    for statement in (
        "ALTER TABLE diagnostic_strategy_runs ADD COLUMN "
        "ptrade_surface_version VARCHAR(128) NULL",
        "ALTER TABLE diagnostic_strategy_runs ADD COLUMN "
        "ptrade_manifest_hash VARCHAR(64) NULL",
        "ALTER TABLE diagnostic_strategy_runs ADD COLUMN "
        "ptrade_host_adapter_version VARCHAR(128) NULL",
        "ALTER TABLE diagnostic_strategy_runs ADD COLUMN "
        "ptrade_host_audit_json TEXT NULL",
    ):
        connection.exec_driver_sql(statement)


def _json_dumps(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class SqlHistoricalSegmentCatalog:
    """Transactional catalog adapter backed by diagnostic-owned tables."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(
        self,
        snapshot: SourceSnapshot,
        segment: HistoricalMarketSegment,
        report: SegmentAdmissionReport,
    ) -> HistoricalMarketSegment:
        provenance_json = _json_dumps(snapshot.provenance.to_dict())
        artifacts_json = _json_dumps(
            [artifact.to_dict() for artifact in snapshot.artifacts]
        )
        tags_json = _json_dumps(list(segment.recommendation_tags))
        report_json = _json_dumps(report.to_dict())
        created_at = datetime.now(timezone.utc).isoformat()
        with self._engine.begin() as connection:
            existing_snapshot = connection.execute(
                text(
                    "SELECT content_hash, provenance_json, artifacts_json "
                    "FROM diagnostic_source_snapshots "
                    "WHERE snapshot_id = :snapshot_id"
                ),
                {"snapshot_id": snapshot.snapshot_id},
            ).one_or_none()
            if existing_snapshot is None:
                connection.execute(
                    text(
                        "INSERT INTO diagnostic_source_snapshots ("
                        "snapshot_id, content_hash, provenance_json, artifacts_json, "
                        "created_at_utc) VALUES ("
                        ":snapshot_id, :content_hash, :provenance_json, "
                        ":artifacts_json, :created_at_utc)"
                    ),
                    {
                        "snapshot_id": snapshot.snapshot_id,
                        "content_hash": snapshot.content_hash,
                        "provenance_json": provenance_json,
                        "artifacts_json": artifacts_json,
                        "created_at_utc": created_at,
                    },
                )
            elif tuple(existing_snapshot) != (
                snapshot.content_hash,
                provenance_json,
                artifacts_json,
            ):
                raise ValueError("immutable source snapshot identity collision")

            existing_segment = connection.execute(
                text(
                    "SELECT content_hash, source_snapshot_id, market, start_date, "
                    "end_date, label, eligible_instrument_count, trading_day_count, "
                    "bar_count, recommendation_tags_json, admission_report_json "
                    "FROM diagnostic_historical_segments "
                    "WHERE segment_id = :segment_id"
                ),
                {"segment_id": segment.segment_id},
            ).one_or_none()
            if existing_segment is None:
                connection.execute(
                    text(
                        "INSERT INTO diagnostic_historical_segments ("
                        "segment_id, content_hash, source_snapshot_id, market, "
                        "start_date, end_date, label, eligible_instrument_count, "
                        "trading_day_count, bar_count, recommendation_tags_json, "
                        "admission_report_json, created_at_utc) VALUES ("
                        ":segment_id, :content_hash, :source_snapshot_id, :market, "
                        ":start_date, :end_date, :label, "
                        ":eligible_instrument_count, :trading_day_count, :bar_count, "
                        ":recommendation_tags_json, :admission_report_json, "
                        ":created_at_utc)"
                    ),
                    {
                        "segment_id": segment.segment_id,
                        "content_hash": segment.content_hash,
                        "source_snapshot_id": segment.source_snapshot_id,
                        "market": segment.selection.market,
                        "start_date": segment.selection.start_date.isoformat(),
                        "end_date": segment.selection.end_date.isoformat(),
                        "label": segment.label,
                        "eligible_instrument_count": segment.eligible_instrument_count,
                        "trading_day_count": segment.trading_day_count,
                        "bar_count": segment.bar_count,
                        "recommendation_tags_json": tags_json,
                        "admission_report_json": report_json,
                        "created_at_utc": created_at,
                    },
                )
            elif tuple(existing_segment) != (
                segment.content_hash,
                segment.source_snapshot_id,
                segment.selection.market,
                segment.selection.start_date.isoformat(),
                segment.selection.end_date.isoformat(),
                segment.label,
                segment.eligible_instrument_count,
                segment.trading_day_count,
                segment.bar_count,
                tags_json,
                report_json,
            ):
                raise ValueError("immutable historical segment identity collision")
        return segment

    def list_segments(self) -> tuple[HistoricalMarketSegment, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT s.segment_id, s.content_hash, s.source_snapshot_id, "
                    "s.market, "
                    "start_date, end_date, label, eligible_instrument_count, "
                    "trading_day_count, bar_count, recommendation_tags_json, "
                    "p.provenance_json "
                    "FROM diagnostic_historical_segments AS s "
                    "JOIN diagnostic_source_snapshots AS p "
                    "ON p.snapshot_id = s.source_snapshot_id "
                    "ORDER BY start_date, end_date, segment_id"
                )
            ).all()
        return tuple(
            HistoricalMarketSegment(
                segment_id=str(row.segment_id),
                content_hash=str(row.content_hash),
                source_snapshot_id=str(row.source_snapshot_id),
                source_provenance=_source_provenance_from_json(
                    str(row.provenance_json)
                ),
                selection=HistoricalSegmentSelection(
                    market=str(row.market),
                    start_date=datetime.strptime(
                        str(row.start_date), "%Y-%m-%d"
                    ).date(),
                    end_date=datetime.strptime(str(row.end_date), "%Y-%m-%d").date(),
                ),
                label=str(row.label),
                eligible_instrument_count=int(row.eligible_instrument_count),
                trading_day_count=int(row.trading_day_count),
                bar_count=int(row.bar_count),
                recommendation_tags=tuple(
                    str(tag) for tag in json.loads(row.recommendation_tags_json)
                ),
            )
            for row in rows
        )


class SqlScenarioRecipeRepository:
    """Transactional storage for drafts, validations, approvals, and versions."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add_ai_attempt(
        self,
        attempt: AIRecipeAssistantAttempt,
    ) -> AIRecipeAssistantAttempt:
        proposals_json = _json_dumps(
            [proposal.dict() for proposal in attempt.transformation_proposals]
        )
        values = (
            attempt.intent,
            attempt.author,
            attempt.provider,
            attempt.model,
            attempt.prompt_template_version,
            attempt.response_id,
            attempt.response_hash,
            attempt.status,
            attempt.created_at.isoformat(),
            attempt.draft_id,
            proposals_json,
            attempt.error_code,
            attempt.error_message,
        )
        with self._engine.begin() as connection:
            existing = connection.execute(
                text(
                    "SELECT intent, author, provider, model, "
                    "prompt_template_version, response_id, response_hash, status, "
                    "created_at_utc, draft_id, transformation_proposals_json, "
                    "error_code, error_message "
                    "FROM diagnostic_ai_recipe_attempts "
                    "WHERE attempt_id = :attempt_id"
                ),
                {"attempt_id": attempt.attempt_id},
            ).one_or_none()
            if existing is None:
                connection.execute(
                    text(
                        "INSERT INTO diagnostic_ai_recipe_attempts ("
                        "attempt_id, intent, author, provider, model, "
                        "prompt_template_version, response_id, response_hash, "
                        "status, created_at_utc, draft_id, "
                        "transformation_proposals_json, error_code, error_message) "
                        "VALUES (:attempt_id, :intent, :author, :provider, :model, "
                        ":prompt_template_version, :response_id, :response_hash, "
                        ":status, :created_at_utc, :draft_id, "
                        ":transformation_proposals_json, :error_code, :error_message)"
                    ),
                    {
                        "attempt_id": attempt.attempt_id,
                        "intent": attempt.intent,
                        "author": attempt.author,
                        "provider": attempt.provider,
                        "model": attempt.model,
                        "prompt_template_version": attempt.prompt_template_version,
                        "response_id": attempt.response_id,
                        "response_hash": attempt.response_hash,
                        "status": attempt.status,
                        "created_at_utc": attempt.created_at.isoformat(),
                        "draft_id": attempt.draft_id,
                        "transformation_proposals_json": proposals_json,
                        "error_code": attempt.error_code,
                        "error_message": attempt.error_message,
                    },
                )
            elif tuple(existing) != values:
                raise ValueError(
                    "immutable AI Recipe Assistant attempt identity collision"
                )
        return attempt

    def get_ai_attempt(
        self,
        attempt_id: str,
    ) -> AIRecipeAssistantAttempt | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT attempt_id, intent, author, provider, model, "
                    "prompt_template_version, response_id, response_hash, status, "
                    "created_at_utc, draft_id, transformation_proposals_json, "
                    "error_code, error_message "
                    "FROM diagnostic_ai_recipe_attempts "
                    "WHERE attempt_id = :attempt_id"
                ),
                {"attempt_id": attempt_id},
            ).one_or_none()
        if row is None:
            return None
        raw_status = str(row.status)
        if raw_status not in {
            "draft_valid",
            "draft_invalid",
            "provider_error",
            "malformed_output",
        }:
            raise ValueError("stored AI Recipe Assistant status is invalid")
        status = cast(
            Literal[
                "draft_valid",
                "draft_invalid",
                "provider_error",
                "malformed_output",
            ],
            raw_status,
        )
        raw_proposals = json.loads(str(row.transformation_proposals_json))
        if not isinstance(raw_proposals, list):
            raise ValueError("stored transformation proposals are invalid")
        return AIRecipeAssistantAttempt(
            attempt_id=str(row.attempt_id),
            intent=str(row.intent),
            author=str(row.author),
            provider=str(row.provider),
            model=str(row.model),
            prompt_template_version=str(row.prompt_template_version),
            response_id=(
                str(row.response_id) if row.response_id is not None else None
            ),
            response_hash=(
                str(row.response_hash) if row.response_hash is not None else None
            ),
            status=status,
            created_at=_parse_aware_datetime(str(row.created_at_utc)),
            draft_id=str(row.draft_id) if row.draft_id is not None else None,
            transformation_proposals=tuple(
                TransformationProposalV1.parse_obj(proposal)
                for proposal in raw_proposals
            ),
            error_code=(
                str(row.error_code) if row.error_code is not None else None
            ),
            error_message=(
                str(row.error_message) if row.error_message is not None else None
            ),
        )

    def add_draft(self, draft: ScenarioRecipeDraft) -> ScenarioRecipeDraft:
        values = (
            draft.recipe_id,
            draft.author,
            draft.created_at.isoformat(),
            draft.payload_json,
            draft.payload_hash,
            draft.based_on_version_id,
        )
        with self._engine.begin() as connection:
            existing = connection.execute(
                text(
                    "SELECT recipe_id, author, created_at_utc, payload_json, "
                    "payload_hash, based_on_version_id "
                    "FROM diagnostic_recipe_drafts WHERE draft_id = :draft_id"
                ),
                {"draft_id": draft.draft_id},
            ).one_or_none()
            if existing is None:
                connection.execute(
                    text(
                        "INSERT INTO diagnostic_recipe_drafts ("
                        "draft_id, recipe_id, author, created_at_utc, payload_json, "
                        "payload_hash, based_on_version_id) VALUES ("
                        ":draft_id, :recipe_id, :author, :created_at_utc, "
                        ":payload_json, :payload_hash, :based_on_version_id)"
                    ),
                    {
                        "draft_id": draft.draft_id,
                        "recipe_id": draft.recipe_id,
                        "author": draft.author,
                        "created_at_utc": draft.created_at.isoformat(),
                        "payload_json": draft.payload_json,
                        "payload_hash": draft.payload_hash,
                        "based_on_version_id": draft.based_on_version_id,
                    },
                )
            elif tuple(existing) != values:
                raise ValueError("immutable Scenario Recipe Draft identity collision")
        return draft

    def get_draft(self, draft_id: str) -> ScenarioRecipeDraft | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT draft_id, recipe_id, author, created_at_utc, "
                    "payload_json, payload_hash, based_on_version_id "
                    "FROM diagnostic_recipe_drafts WHERE draft_id = :draft_id"
                ),
                {"draft_id": draft_id},
            ).one_or_none()
        if row is None:
            return None
        draft = ScenarioRecipeDraft(
            draft_id=str(row.draft_id),
            recipe_id=str(row.recipe_id),
            author=str(row.author),
            created_at=_parse_aware_datetime(str(row.created_at_utc)),
            payload_json=str(row.payload_json),
            based_on_version_id=(
                str(row.based_on_version_id)
                if row.based_on_version_id is not None
                else None
            ),
        )
        if draft.payload_hash != str(row.payload_hash):
            raise ValueError("stored Scenario Recipe Draft hash mismatch")
        return draft

    def add_validation(
        self,
        validation: RecipeValidationResult,
    ) -> RecipeValidationResult:
        issues_json = _json_dumps(
            [issue.to_dict() for issue in validation.issues]
        )
        recipe_json = (
            validation.validated_recipe.canonical_json()
            if validation.validated_recipe is not None
            else None
        )
        parameters = {
            "draft_id": validation.draft_id,
            "payload_hash": validation.payload_hash,
            "is_valid": int(validation.is_valid),
            "issues_json": issues_json,
            "recipe_content_hash": validation.recipe_content_hash,
            "validated_at_utc": validation.validated_at.isoformat(),
            "validated_recipe_json": recipe_json,
        }
        with self._engine.begin() as connection:
            approved = connection.execute(
                text(
                    "SELECT approval_id FROM diagnostic_recipe_approvals "
                    "WHERE draft_id = :draft_id"
                ),
                {"draft_id": validation.draft_id},
            ).one_or_none()
            if approved is not None:
                raise ValueError(
                    "Validation belongs to an approved immutable "
                    "Scenario Recipe Version"
                )
            existing = connection.execute(
                text(
                    "SELECT draft_id FROM diagnostic_recipe_validations "
                    "WHERE draft_id = :draft_id"
                ),
                {"draft_id": validation.draft_id},
            ).one_or_none()
            if existing is None:
                connection.execute(
                    text(
                        "INSERT INTO diagnostic_recipe_validations ("
                        "draft_id, payload_hash, is_valid, issues_json, "
                        "recipe_content_hash, validated_at_utc, "
                        "validated_recipe_json) VALUES ("
                        ":draft_id, :payload_hash, :is_valid, :issues_json, "
                        ":recipe_content_hash, :validated_at_utc, "
                        ":validated_recipe_json)"
                    ),
                    parameters,
                )
            else:
                connection.execute(
                    text(
                        "UPDATE diagnostic_recipe_validations SET "
                        "payload_hash = :payload_hash, is_valid = :is_valid, "
                        "issues_json = :issues_json, "
                        "recipe_content_hash = :recipe_content_hash, "
                        "validated_at_utc = :validated_at_utc, "
                        "validated_recipe_json = :validated_recipe_json "
                        "WHERE draft_id = :draft_id"
                    ),
                    parameters,
                )
        return validation

    def get_validation(self, draft_id: str) -> RecipeValidationResult | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT draft_id, payload_hash, is_valid, issues_json, "
                    "recipe_content_hash, validated_at_utc, validated_recipe_json "
                    "FROM diagnostic_recipe_validations WHERE draft_id = :draft_id"
                ),
                {"draft_id": draft_id},
            ).one_or_none()
        if row is None:
            return None
        issue_values = json.loads(str(row.issues_json))
        return RecipeValidationResult(
            draft_id=str(row.draft_id),
            payload_hash=str(row.payload_hash),
            is_valid=bool(row.is_valid),
            issues=tuple(
                RecipeValidationIssue(
                    path=str(item["path"]),
                    rule=str(item["rule"]),
                    message=str(item["message"]),
                    correction=str(item["correction"]),
                )
                for item in issue_values
            ),
            recipe_content_hash=(
                str(row.recipe_content_hash)
                if row.recipe_content_hash is not None
                else None
            ),
            validated_at=_parse_aware_datetime(str(row.validated_at_utc)),
            validated_recipe=(
                ScenarioRecipeV1.parse_raw(str(row.validated_recipe_json))
                if row.validated_recipe_json is not None
                else None
            ),
        )

    def add_version(
        self,
        version: ApprovedScenarioRecipeVersion,
    ) -> ApprovedScenarioRecipeVersion:
        approval_identity = (
            f"{version.version_id}|{version.approval_actor}|"
            f"{version.approved_at.isoformat()}"
        )
        approval_id = "recipe_approval_" + hashlib.sha256(
            approval_identity.encode("utf-8")
        ).hexdigest()
        try:
            with self._engine.begin() as connection:
                approved = connection.execute(
                    text(
                        "SELECT approval_id FROM diagnostic_recipe_approvals "
                        "WHERE draft_id = :draft_id"
                    ),
                    {"draft_id": version.validation_result.draft_id},
                ).one_or_none()
                if approved is not None:
                    raise ValueError(
                        "Scenario Recipe Draft already belongs to an "
                        "approved immutable version"
                    )
                connection.execute(
                    text(
                        "INSERT INTO diagnostic_recipe_approvals ("
                        "approval_id, draft_id, actor, approved_at_utc, "
                        "recipe_content_hash) VALUES ("
                        ":approval_id, :draft_id, :actor, :approved_at_utc, "
                        ":recipe_content_hash)"
                    ),
                    {
                        "approval_id": approval_id,
                        "draft_id": version.validation_result.draft_id,
                        "actor": version.approval_actor,
                        "approved_at_utc": version.approved_at.isoformat(),
                        "recipe_content_hash": version.content_hash,
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO diagnostic_recipe_versions ("
                        "version_id, recipe_id, version_number, recipe_json, "
                        "content_hash, author, approval_id, validation_draft_id, "
                        "validation_json, based_on_version_id) VALUES ("
                        ":version_id, :recipe_id, :version_number, :recipe_json, "
                        ":content_hash, :author, :approval_id, "
                        ":validation_draft_id, :validation_json, "
                        ":based_on_version_id)"
                    ),
                    {
                        "version_id": version.version_id,
                        "recipe_id": version.recipe_id,
                        "version_number": version.version_number,
                        "recipe_json": version.recipe.canonical_json(),
                        "content_hash": version.content_hash,
                        "author": version.author,
                        "approval_id": approval_id,
                        "validation_draft_id": version.validation_result.draft_id,
                        "validation_json": _validation_snapshot_json(
                            version.validation_result
                        ),
                        "based_on_version_id": version.based_on_version_id,
                    },
                )
        except IntegrityError as error:
            raise ValueError(
                "Scenario Recipe approval or version identity collision"
            ) from error
        return version

    def get_version(
        self,
        version_id: str,
    ) -> ApprovedScenarioRecipeVersion | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT v.version_id, v.recipe_id, v.version_number, "
                    "v.recipe_json, v.content_hash, v.author, "
                    "v.validation_draft_id, v.validation_json, "
                    "v.based_on_version_id, a.actor, a.approved_at_utc, "
                    "a.recipe_content_hash AS approval_content_hash "
                    "FROM diagnostic_recipe_versions AS v "
                    "JOIN diagnostic_recipe_approvals AS a "
                    "ON a.approval_id = v.approval_id "
                    "WHERE v.version_id = :version_id"
                ),
                {"version_id": version_id},
            ).one_or_none()
        if row is None:
            return None
        validation = _validation_snapshot_from_json(str(row.validation_json))
        if validation.draft_id != str(row.validation_draft_id):
            raise ValueError("stored Scenario Recipe validation identity mismatch")
        recipe = ScenarioRecipeV1.parse_raw(str(row.recipe_json))
        if recipe.content_hash != str(row.content_hash):
            raise ValueError("stored Scenario Recipe Version hash mismatch")
        if (
            not validation.is_valid
            or validation.recipe_content_hash != str(row.content_hash)
            or str(row.approval_content_hash) != str(row.content_hash)
        ):
            raise ValueError("stored Scenario Recipe approval evidence mismatch")
        return ApprovedScenarioRecipeVersion(
            version_id=str(row.version_id),
            recipe_id=str(row.recipe_id),
            version_number=int(row.version_number),
            recipe=recipe,
            content_hash=str(row.content_hash),
            author=str(row.author),
            approval_actor=str(row.actor),
            approved_at=_parse_aware_datetime(str(row.approved_at_utc)),
            validation_result=validation,
            based_on_version_id=(
                str(row.based_on_version_id)
                if row.based_on_version_id is not None
                else None
            ),
        )

    def list_versions(
        self,
        recipe_id: str,
    ) -> tuple[ApprovedScenarioRecipeVersion, ...]:
        with self._engine.connect() as connection:
            version_ids = connection.execute(
                text(
                    "SELECT version_id FROM diagnostic_recipe_versions "
                    "WHERE recipe_id = :recipe_id ORDER BY version_number"
                ),
                {"recipe_id": recipe_id},
            ).scalars().all()
        versions = tuple(self.get_version(str(item)) for item in version_ids)
        if any(version is None for version in versions):
            raise ValueError("Scenario Recipe Version index is inconsistent")
        return tuple(version for version in versions if version is not None)


def _source_provenance_from_json(payload: str) -> SourceProvenance:
    values = json.loads(payload)
    observed_at = datetime.fromisoformat(str(values["observed_at"]))
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    return SourceProvenance(
        provider=str(values["provider"]),
        dataset=str(values["dataset"]),
        version=str(values["version"]),
        observed_at=observed_at,
    )


def _parse_aware_datetime(payload: str) -> datetime:
    value = datetime.fromisoformat(payload)
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def _validation_snapshot_json(validation: RecipeValidationResult) -> str:
    return _json_dumps(
        {
            "draft_id": validation.draft_id,
            "payload_hash": validation.payload_hash,
            "is_valid": validation.is_valid,
            "issues": [issue.to_dict() for issue in validation.issues],
            "recipe_content_hash": validation.recipe_content_hash,
            "validated_at": validation.validated_at.isoformat(),
            "validated_recipe": (
                json.loads(validation.validated_recipe.canonical_json())
                if validation.validated_recipe is not None
                else None
            ),
        }
    )


def _validation_snapshot_from_json(payload: str) -> RecipeValidationResult:
    values = json.loads(payload)
    recipe_payload = values.get("validated_recipe")
    return RecipeValidationResult(
        draft_id=str(values["draft_id"]),
        payload_hash=str(values["payload_hash"]),
        is_valid=bool(values["is_valid"]),
        issues=tuple(
            RecipeValidationIssue(
                path=str(item["path"]),
                rule=str(item["rule"]),
                message=str(item["message"]),
                correction=str(item["correction"]),
            )
            for item in values["issues"]
        ),
        recipe_content_hash=(
            str(values["recipe_content_hash"])
            if values.get("recipe_content_hash") is not None
            else None
        ),
        validated_at=_parse_aware_datetime(str(values["validated_at"])),
        validated_recipe=(
            ScenarioRecipeV1.parse_obj(recipe_payload)
            if recipe_payload is not None
            else None
        ),
    )


__all__ = [
    "DIAGNOSTIC_SCHEMA_REVISION",
    "DiagnosticMigrationReport",
    "SqlHistoricalSegmentCatalog",
    "SqlScenarioRecipeRepository",
    "initialize_diagnostic_persistence",
]
