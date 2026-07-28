"""Typed Strategy Diagnostics V1 read-model fixtures for frontend tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from app.features import (
    APPLICATION_READ_MODEL_INTERFACE_VERSION,
    AlertSeverity,
    ApplicationReadAvailability,
    ApplicationReadError,
    ApplicationReadErrorCode,
    ApplicationReadModelVersion,
    ApplicationReadResult,
    DiagnosticTaskCapabilities,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsData,
    EvidenceCoverage,
    ExecutionAssumption,
    MarketScenarioId,
    ReadOnlyDiagnosticContext,
    ReproductionManifestId,
    ResolvedV1Journey,
    RunAlert,
    RunLifecyclePhase,
    RunMonitoringContext,
    RunMonitoringData,
    RunMonitoringSelection,
    RunProgress,
    ScenarioSetId,
    SimulationTime,
    SourceRevisionToken,
    StrategyUnderTestId,
    TerminalOutcome,
    V1JourneySelector,
    WallTime,
)
from app.features.live_evidence_and_findings import (
    _candidate_rows,
    _content_digest,
    _evidence_payload,
    _map_record as _map_evidence_record,
    _optional_aware as _optional_evidence_time,
    _status_token,
    _validate_record_selection,
)


class DictionaryFixtureApplicationReadModel:
    """Translate legacy dictionary fixtures at the test boundary only."""

    def __init__(
        self,
        queries: object | None,
        *,
        evidence_context: EvidenceAndFindingsContext | None = None,
    ) -> None:
        self._queries = queries
        self._evidence_context = (
            evidence_context or EvidenceAndFindingsContext.no_selection()
        )

    @property
    def interface_version(self) -> ApplicationReadModelVersion:
        return APPLICATION_READ_MODEL_INTERFACE_VERSION

    def resolve_journey(
        self,
        selector: V1JourneySelector,
    ) -> ApplicationReadResult[ResolvedV1Journey]:
        journey = ResolvedV1Journey(
            run_context=RunMonitoringContext.for_run(
                RunMonitoringSelection(
                    campaign_id=selector.campaign_id,
                    run_id=selector.run_id,
                )
            ),
            evidence_context=self._evidence_context,
            evidence_package_id=selector.evidence_package_id,
            campaign_case_id=MarketScenarioId("TEST-CASE"),
            campaign_layer=EvidenceCoverage.BASELINE,
        )
        return ApplicationReadResult(
            availability=ApplicationReadAvailability.READY,
            source_token=_token(
                {
                    "campaign_id": selector.campaign_id.value,
                    "run_id": selector.run_id.value,
                }
            ),
            source_observed_at=None,
            value=journey,
            error=None,
        )

    def read_run(
        self,
        journey: ResolvedV1Journey,
    ) -> ApplicationReadResult[RunMonitoringData]:
        selection = journey.run_context.selection
        assert selection is not None
        assert selection.run_id is not None
        queries = self._queries
        method = (
            getattr(queries, "get_run_monitoring_snapshot", None)
            if queries is not None
            else None
        )
        if not callable(method):
            return _failure("run_monitoring_query_failed")
        record = method(selection.run_id.value)
        if not isinstance(record, Mapping):
            return _failure("strategy_diagnostics_selection_not_found")
        data = _map_record(selection, record)
        return ApplicationReadResult(
            availability=ApplicationReadAvailability.READY,
            source_token=_token(record),
            source_observed_at=data.wall_time.observed_at,
            value=data,
            error=None,
        )

    def read_evidence(
        self,
        journey: ResolvedV1Journey,
    ) -> ApplicationReadResult[EvidenceAndFindingsData]:
        selection = journey.evidence_context.selection
        if selection is None:
            return _evidence_failure(
                ApplicationReadErrorCode.SELECTION_NOT_FOUND,
                retryable=False,
            )
        queries = self._queries
        method = (
            getattr(queries, "get_evidence_and_findings_snapshot", None)
            if queries is not None
            else None
        )
        if not callable(method):
            return _evidence_failure(
                ApplicationReadErrorCode.READ_FAILED,
                retryable=True,
            )
        try:
            record = method(selection.run_id.value)
        except Exception:
            return _evidence_failure(
                ApplicationReadErrorCode.READ_FAILED,
                retryable=True,
            )
        if not isinstance(record, Mapping):
            return _evidence_failure(
                ApplicationReadErrorCode.EVIDENCE_PENDING,
                retryable=True,
                availability=ApplicationReadAvailability.PENDING,
            )
        token: SourceRevisionToken | None = None
        try:
            record_dict = dict(record)
            _validate_record_selection(journey.evidence_context, record_dict)
            payload = _evidence_payload(record_dict)
            _validate_record_selection(journey.evidence_context, payload)
            content_digest = _content_digest(record_dict, payload)
            token = (
                SourceRevisionToken(content_digest.removeprefix("sha256:"))
                if content_digest is not None
                else _token(_evidence_semantic_payload(record_dict, payload))
            )
            candidate_rows = _candidate_rows(payload)
            status = _status_token(
                payload.get("status") or record.get("status")
            )
            if not candidate_rows:
                return _evidence_failure(
                    ApplicationReadErrorCode.EVIDENCE_PENDING,
                    retryable=True,
                    availability=ApplicationReadAvailability.PENDING,
                    token=token,
                )
            data = _map_evidence_record(
                journey.evidence_context,
                record_dict,
                payload,
                candidate_rows,
            )
        except Exception:
            return _evidence_failure(
                ApplicationReadErrorCode.EVIDENCE_MAPPING_FAILED,
                retryable=False,
                token=token,
            )
        observed_at = (
            _optional_evidence_time(payload.get("updated_at"))
            or _optional_evidence_time(payload.get("created_at"))
            or _optional_evidence_time(record.get("updated_at"))
        )
        if status in {"failed", "error"}:
            return ApplicationReadResult(
                availability=ApplicationReadAvailability.PARTIAL,
                source_token=token,
                source_observed_at=observed_at,
                value=data,
                error=ApplicationReadError(
                    code=ApplicationReadErrorCode.EVIDENCE_MAPPING_FAILED,
                    message="The Diagnostic Evidence result failed.",
                    retryable=False,
                ),
            )
        if status in {"partial", "running", "pending"}:
            return ApplicationReadResult(
                availability=ApplicationReadAvailability.PARTIAL,
                source_token=token,
                source_observed_at=observed_at,
                value=data,
                error=ApplicationReadError(
                    code=ApplicationReadErrorCode.EVIDENCE_PARTIAL,
                    message=(
                        "Some diagnostic evidence is incomplete or "
                        "temporarily unavailable."
                    ),
                    retryable=True,
                ),
            )
        return ApplicationReadResult(
            availability=ApplicationReadAvailability.READY,
            source_token=token,
            source_observed_at=observed_at,
            value=data,
            error=None,
        )


def _failure(code: str) -> ApplicationReadResult[RunMonitoringData]:
    error_code = (
        ApplicationReadErrorCode.SELECTION_NOT_FOUND
        if code == "strategy_diagnostics_selection_not_found"
        else ApplicationReadErrorCode.READ_FAILED
    )
    return ApplicationReadResult(
        availability=ApplicationReadAvailability.FAILED,
        source_token=None,
        source_observed_at=None,
        value=None,
        error=ApplicationReadError(
            code=error_code,
            message="Run Monitoring data is unavailable.",
            retryable=error_code is ApplicationReadErrorCode.READ_FAILED,
        ),
    )


def _evidence_failure(
    code: ApplicationReadErrorCode,
    *,
    retryable: bool,
    availability: ApplicationReadAvailability = (
        ApplicationReadAvailability.FAILED
    ),
    token: SourceRevisionToken | None = None,
) -> ApplicationReadResult[EvidenceAndFindingsData]:
    return ApplicationReadResult(
        availability=availability,
        source_token=token,
        source_observed_at=None,
        value=None,
        error=ApplicationReadError(
            code=code,
            message=(
                "Diagnostic Evidence is still materializing."
                if code is ApplicationReadErrorCode.EVIDENCE_PENDING
                else "Diagnostic Evidence is unavailable."
            ),
            retryable=retryable,
        ),
    )


def _map_record(
    selection: RunMonitoringSelection,
    record: Mapping[str, Any],
) -> RunMonitoringData:
    lifecycle = _lifecycle(record.get("status"))
    observed_at = _optional_aware(record.get("updated_at")) or datetime.now(
        timezone.utc
    )
    started_at = _optional_aware(record.get("started_at"))
    simulation_instant = _optional_aware(record.get("last_sim_dt")) or datetime(
        1,
        1,
        1,
        tzinfo=timezone.utc,
    )
    requested = _string_mapping(record.get("requested_execution"))
    effective = _string_mapping(record.get("effective_execution"))
    overrides = _string_mapping(record.get("execution_override_reasons"))
    assumption_names = tuple(sorted(set(requested) | set(effective)))
    completed = max(int(record.get("completed_nodes") or 0), 0)
    total = max(int(record.get("total_nodes") or 1), 1)
    completed = min(completed, total)
    return RunMonitoringData(
        selection=selection,
        strategy_id=_optional_identity(
            record.get("strategy_id"),
            StrategyUnderTestId,
        ),
        market_scenario_id=_optional_identity(
            record.get("scenario_name"),
            MarketScenarioId,
        ),
        scenario_set_id=_optional_identity(
            record.get("scenario_set_id"),
            ScenarioSetId,
        ),
        reproduction_manifest_id=_optional_identity(
            record.get("reproduction_manifest_id"),
            ReproductionManifestId,
        ),
        task_id=None,
        lifecycle=lifecycle,
        terminal_outcome=_terminal_outcome(lifecycle),
        progress=RunProgress(
            current_node_id=_nonempty(
                record.get("current_node_id"),
                f"RUN-{lifecycle.value.upper()}",
            ),
            current_node_label=_nonempty(
                record.get("current_node_label"),
                lifecycle.value.replace("_", " ").title(),
            ),
            completed=completed,
            total=total,
        ),
        simulation_time=SimulationTime(
            sim_day=max(int(record.get("last_sim_day") or 0), 0),
            instant=simulation_instant,
        ),
        wall_time=WallTime(
            started_at=started_at,
            observed_at=observed_at,
            elapsed=(
                max(observed_at - started_at, timedelta(0))
                if started_at is not None
                else timedelta(0)
            ),
        ),
        execution_assumptions=tuple(
            ExecutionAssumption(
                name=name,
                requested_value=requested.get(
                    name,
                    effective.get(name, "unavailable"),
                ),
                effective_value=effective.get(
                    name,
                    requested.get(name, "unavailable"),
                ),
                override_reason=overrides.get(name),
            )
            for name in assumption_names
        ),
        alerts=tuple(
            RunAlert(
                code=_nonempty(item.get("code"), "runtime_alert"),
                severity=_alert_severity(item.get("severity")),
                message=_nonempty(
                    item.get("message"),
                    "Runtime alert details are unavailable.",
                ),
            )
            for item in _mapping_sequence(record.get("alerts"))
        ),
        context=ReadOnlyDiagnosticContext(
            market=_string_tuple(record.get("market_context")),
            account=_string_tuple(record.get("account_context")),
            positions=_string_tuple(record.get("position_context")),
            orders=_string_tuple(record.get("order_context")),
            fills=_string_tuple(record.get("fill_context")),
        ),
        capabilities=DiagnosticTaskCapabilities(False, False, False),
        active_task=None,
    )


def _evidence_semantic_payload(
    record: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, object]:
    transient = {
        "revision",
        "updated_at",
        "created_at",
        "_source_version_order",
        "content_digest",
    }
    return {
        "record": {
            str(key): value
            for key, value in record.items()
            if key not in transient and key != "evidence_and_findings"
        },
        "payload": {
            str(key): value
            for key, value in payload.items()
            if key not in transient
        },
    }


def _token(value: object) -> SourceRevisionToken:
    serialized = json.dumps(
        value,
        default=str,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return SourceRevisionToken(hashlib.sha256(serialized.encode()).hexdigest())


def _optional_aware(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _optional_identity(value: object, identity_type):
    text = _optional_text(value)
    return identity_type(text) if text is not None else None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _nonempty(value: object, fallback: str) -> str:
    return _optional_text(value) or fallback


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items() if item is not None}


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item) for item in value if item is not None)


def _mapping_sequence(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _lifecycle(value: object) -> RunLifecyclePhase:
    normalized = str(value or "pending").strip().lower()
    aliases = {
        "pending": RunLifecyclePhase.QUEUED,
        "queued": RunLifecyclePhase.QUEUED,
        "starting": RunLifecyclePhase.QUEUED,
        "running": RunLifecyclePhase.RUNNING,
        "paused": RunLifecyclePhase.PAUSED,
        "completed": RunLifecyclePhase.COMPLETED,
        "failed": RunLifecyclePhase.FAILED,
        "canceled": RunLifecyclePhase.CANCELED,
        "cancelled": RunLifecyclePhase.CANCELED,
    }
    return aliases.get(normalized, RunLifecyclePhase.FAILED)


def _terminal_outcome(
    lifecycle: RunLifecyclePhase,
) -> TerminalOutcome | None:
    return {
        RunLifecyclePhase.COMPLETED: TerminalOutcome.COMPLETED,
        RunLifecyclePhase.FAILED: TerminalOutcome.FAILED,
        RunLifecyclePhase.CANCELED: TerminalOutcome.CANCELED,
    }.get(lifecycle)


def _alert_severity(value: object) -> AlertSeverity:
    normalized = str(value or "info").strip().lower()
    return {
        "info": AlertSeverity.INFO,
        "warning": AlertSeverity.WARNING,
        "error": AlertSeverity.ERROR,
    }.get(normalized, AlertSeverity.INFO)


__all__ = ["DictionaryFixtureApplicationReadModel"]
