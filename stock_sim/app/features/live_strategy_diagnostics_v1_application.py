"""Live typed read adapter over the persisted Strategy Diagnostics V1 product."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from strategy_diagnostics.application import (
    DIAGNOSTIC_SCHEMA_REVISION,
    DiagnosticsApplication,
)
from strategy_diagnostics.diagnostic_evidence import DiagnosticEvidencePackage
from strategy_diagnostics.formal_diagnostic_campaigns import (
    DiagnosticCampaignCaseSnapshot,
    DiagnosticCampaignSnapshot,
)
from strategy_diagnostics.reproduction import ReproductionManifest
from strategy_diagnostics.strategy_runs import StrategyRunSnapshot

from .evidence_and_findings import (
    ApprovedScenarioRecipeId,
    CandidateEvidence,
    DependencyProvenance,
    DiagnosticCandidateId,
    DiagnosticEvidencePackageId,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsData,
    EvidenceAndFindingsSelection,
    EvidenceAvailability,
    EvidenceComparison,
    EvidenceComparisonId,
    EvidenceCoverage,
    EvidenceDimension,
    EvidenceProvenance,
    EvidenceRecord,
    EvidenceRecordId,
    FillEvidenceTrace,
    Finding,
    FindingDisposition,
    FindingId,
    OrderEvidenceTrace,
    ReadOnlyEvidenceContext,
    SensitivityBreakpoint,
    SensitivityBreakpointId,
)
from .run_monitoring import (
    AlertSeverity,
    DiagnosticTaskCapabilities,
    ExecutionAssumption,
    FormalDiagnosticCampaignId,
    MarketScenarioId,
    ReadOnlyDiagnosticContext,
    ReproductionManifestId,
    RunAlert,
    RunLifecyclePhase,
    RunMonitoringContext,
    RunMonitoringData,
    RunMonitoringSelection,
    RunProgress,
    ScenarioSetId,
    SimulationTime,
    StrategyRunId,
    StrategyUnderTestId,
    TerminalOutcome,
    WallTime,
)
from .strategy_diagnostics_v1_read_model import (
    APPLICATION_READ_MODEL_INTERFACE_VERSION,
    ApplicationReadAvailability,
    ApplicationReadError,
    ApplicationReadErrorCode,
    ApplicationReadModelVersion,
    ApplicationReadResult,
    ResolvedV1Journey,
    SourceRevisionToken,
    V1JourneySelector,
)

_SUPPORTED_MIGRATIONS = frozenset(
    {
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
        DIAGNOSTIC_SCHEMA_REVISION,
    }
)
_COVERAGE_BY_LAYER = {
    "baseline": EvidenceCoverage.BASELINE,
    "isolated_sensitivity": EvidenceCoverage.ISOLATED_SENSITIVITY,
    "compound": EvidenceCoverage.COMPOUND_SCENARIO,
}
_LIFECYCLE_BY_STATUS = {
    "running": RunLifecyclePhase.RUNNING,
    "paused": RunLifecyclePhase.PAUSED,
    "completed": RunLifecyclePhase.COMPLETED,
    "failed": RunLifecyclePhase.FAILED,
    "cancelled": RunLifecyclePhase.CANCELED,
}
_TERMINAL_BY_STATUS = {
    "completed": TerminalOutcome.COMPLETED,
    "failed": TerminalOutcome.FAILED,
    "cancelled": TerminalOutcome.CANCELED,
}
_RETURN_METRICS = frozenset(
    {
        "total_return",
        "net_return",
        "gross_return_before_execution_erosion",
        "benchmark_return",
        "benchmark_relative_return",
    }
)
_RISK_METRICS = frozenset(
    {
        "maximum_drawdown",
        "maximum_recovery_duration_minutes",
        "return_volatility",
        "loss_period_fraction",
        "worst_period_return",
    }
)
_EXPOSURE_METRICS = frozenset(
    {
        "turnover",
        "average_holding_duration_minutes",
        "average_cash_utilization",
        "instrument_concentration",
        "industry_concentration",
    }
)
_EXECUTION_METRICS = frozenset(
    {
        "order_count",
        "trade_count",
        "fill_count",
        "partial_fill_count",
        "rejection_count",
        "filled_quantity",
        "unfilled_quantity",
        "fill_rate",
        "commission_fees",
        "transfer_fees",
        "stamp_duties",
        "total_fees",
        "execution_erosion",
        "execution_erosion_bps",
    }
)
_RATIO_METRICS = _RETURN_METRICS | {
    "maximum_drawdown",
    "return_volatility",
    "loss_period_fraction",
    "worst_period_return",
    "turnover",
    "average_cash_utilization",
    "instrument_concentration",
    "industry_concentration",
    "fill_rate",
}
_DURATION_METRICS = frozenset(
    {"maximum_recovery_duration_minutes", "average_holding_duration_minutes"}
)
_COUNT_METRICS = frozenset(
    {
        "order_count",
        "trade_count",
        "fill_count",
        "partial_fill_count",
        "rejection_count",
    }
)
_QUANTITY_METRICS = frozenset({"filled_quantity", "unfilled_quantity"})
_CURRENCY_METRICS = frozenset(
    {
        "commission_fees",
        "transfer_fees",
        "stamp_duties",
        "total_fees",
        "execution_erosion",
    }
)


@dataclass(frozen=True, slots=True)
class _ResolvedBackendJourney:
    campaign: DiagnosticCampaignSnapshot
    case: DiagnosticCampaignCaseSnapshot
    run: StrategyRunSnapshot
    package: DiagnosticEvidencePackage | None
    manifest: ReproductionManifest | None
    typed: ResolvedV1Journey
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class _SealedEvidenceGraph:
    metrics: tuple[Mapping[str, object], ...]
    comparisons: tuple[Mapping[str, object], ...]
    breakpoints: tuple[Mapping[str, object], ...]
    findings: tuple[Mapping[str, object], ...]

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> _SealedEvidenceGraph:
        return cls(
            metrics=_mapping_sequence(payload, "metrics"),
            comparisons=_mapping_sequence(payload, "comparisons"),
            breakpoints=_mapping_sequence(payload, "sensitivity_breakpoints"),
            findings=_mapping_sequence(payload, "diagnostic_findings"),
        )


class _ReadFailure(Exception):
    def __init__(
        self,
        *,
        code: ApplicationReadErrorCode,
        message: str,
        retryable: bool,
        availability: ApplicationReadAvailability,
        episode: str,
        value: object | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.availability = availability
        self.episode = episode
        self.value = value


class LiveStrategyDiagnosticsV1ApplicationAdapter:
    """Translate authoritative V1 state into immutable Frontend V2 values."""

    def __init__(
        self,
        application: DiagnosticsApplication,
        engine: Engine,
        *,
        clock: Callable[[], datetime] | None = None,
        provider_version: ApplicationReadModelVersion = (
            APPLICATION_READ_MODEL_INTERFACE_VERSION
        ),
    ) -> None:
        self._application = application
        self._engine = engine
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._provider_version = provider_version

    @property
    def interface_version(self) -> ApplicationReadModelVersion:
        return self._provider_version

    def resolve_journey(
        self,
        selector: V1JourneySelector,
    ) -> ApplicationReadResult[ResolvedV1Journey]:
        try:
            resolved = self._resolve(selector)
            availability = (
                ApplicationReadAvailability.READY
                if resolved.package is not None and resolved.manifest is not None
                else ApplicationReadAvailability.PENDING
            )
            error = (
                None
                if availability is ApplicationReadAvailability.READY
                else self._error(
                    code=ApplicationReadErrorCode.EVIDENCE_PENDING,
                    message=(
                        "The selected run is valid, but sealed evidence and its "
                        "Reproduction Manifest are not yet available."
                    ),
                    retryable=True,
                    episode=_selector_episode(selector),
                )
            )
            return self._result(
                availability=availability,
                value=resolved.typed,
                error=error,
                observed_at=resolved.observed_at,
            )
        except _ReadFailure as failure:
            return self._failure_result(failure)
        except (SQLAlchemyError, RuntimeError):
            return self._failure_result(_transient_failure("resolve_journey"))
        except (OSError, TypeError, ValueError, KeyError):
            return self._failure_result(_integrity_failure("resolve_journey"))

    def read_run(
        self,
        journey: ResolvedV1Journey,
    ) -> ApplicationReadResult[RunMonitoringData]:
        try:
            resolved = self._resolve(_selector_from(journey))
            _require_exact_journey(journey, resolved.typed)
            run = resolved.run
            if run.current_simulation_time is None:
                raise _ReadFailure(
                    code=ApplicationReadErrorCode.EVIDENCE_PENDING,
                    message=(
                        "The selected Strategy Run has not persisted its first "
                        "verifiable Simulation Time."
                    ),
                    retryable=True,
                    availability=ApplicationReadAvailability.PENDING,
                    episode=f"run-time:{run.run_id}",
                )
            value = self._map_run(resolved)
            if resolved.manifest is None:
                error = self._error(
                    code=ApplicationReadErrorCode.EVIDENCE_PENDING,
                    message=(
                        "Run state is available, but its sealed evidence Manifest "
                        "is still pending."
                    ),
                    retryable=True,
                    episode=f"run-manifest:{run.run_id}",
                )
                availability = ApplicationReadAvailability.PARTIAL
            else:
                error = None
                availability = ApplicationReadAvailability.READY
            return self._result(
                availability=availability,
                value=value,
                error=error,
                observed_at=resolved.observed_at,
            )
        except _ReadFailure as failure:
            return self._failure_result(failure)
        except (SQLAlchemyError, RuntimeError):
            return self._failure_result(_transient_failure("read_run"))
        except (OSError, TypeError, ValueError, KeyError, ArithmeticError):
            return self._failure_result(_integrity_failure("read_run"))

    def read_evidence(
        self,
        journey: ResolvedV1Journey,
    ) -> ApplicationReadResult[EvidenceAndFindingsData]:
        try:
            resolved = self._resolve(_selector_from(journey))
            _require_exact_journey(journey, resolved.typed)
            if resolved.package is None or resolved.manifest is None:
                raise _ReadFailure(
                    code=ApplicationReadErrorCode.EVIDENCE_PENDING,
                    message=(
                        "Sealed Diagnostic Evidence and its Reproduction Manifest "
                        "are not yet available."
                    ),
                    retryable=True,
                    availability=ApplicationReadAvailability.PENDING,
                    episode=f"evidence:{resolved.run.run_id}",
                )
            value = self._map_evidence(resolved)
            return self._result(
                availability=ApplicationReadAvailability.READY,
                value=value,
                error=None,
                observed_at=resolved.observed_at,
            )
        except _ReadFailure as failure:
            return self._failure_result(failure)
        except (SQLAlchemyError, RuntimeError):
            return self._failure_result(_transient_failure("read_evidence"))
        except (
            OSError,
            TypeError,
            ValueError,
            KeyError,
            ArithmeticError,
            json.JSONDecodeError,
        ):
            return self._failure_result(_integrity_failure("read_evidence"))

    def _resolve(self, selector: V1JourneySelector) -> _ResolvedBackendJourney:
        self._validate_contract()
        campaign_id = selector.campaign_id.value
        run_id = selector.run_id.value
        if not self._row_exists(
            "diagnostic_campaigns",
            "campaign_id",
            campaign_id,
        ):
            raise _not_found("campaign", campaign_id)
        campaign = self._application.diagnostic_campaign_status(campaign_id)
        if (
            campaign.campaign_id != campaign_id
            or campaign.specification.campaign_type != "formal_diagnostic_campaign"
        ):
            raise _identity_failure("campaign")

        if not self._row_exists(
            "diagnostic_strategy_runs",
            "run_id",
            run_id,
        ):
            raise _not_found("run", run_id)
        case, member = self._campaign_member(campaign, run_id)
        if case is None or member is None:
            raise _ReadFailure(
                code=ApplicationReadErrorCode.RUN_NOT_IN_CAMPAIGN,
                message=(
                    "The selected Strategy Run is not a member of the selected "
                    "Formal Diagnostic Campaign."
                ),
                retryable=False,
                availability=ApplicationReadAvailability.FAILED,
                episode=f"membership:{campaign_id}:{run_id}",
            )
        run = self._application.strategy_run_status(run_id)
        self._validate_run_membership(case, member, run)

        package = self._resolve_package(selector, campaign)
        manifest = self._resolve_manifest(selector, package, case, run)
        typed = self._typed_journey(campaign, case, run, package, manifest)
        observed_at = self._observed_at(run)
        return _ResolvedBackendJourney(
            campaign=campaign,
            case=case,
            run=run,
            package=package,
            manifest=manifest,
            typed=typed,
            observed_at=observed_at,
        )

    def _validate_contract(self) -> None:
        if not APPLICATION_READ_MODEL_INTERFACE_VERSION.accepts(self.interface_version):
            raise _ReadFailure(
                code=ApplicationReadErrorCode.CONTRACT_INCOMPATIBLE,
                message="The Strategy Diagnostics read-model version is incompatible.",
                retryable=False,
                availability=ApplicationReadAvailability.FAILED,
                episode=f"interface:{self.interface_version.major}",
            )
        state = self._application.status()
        with self._engine.connect() as connection:
            rows = tuple(
                str(value)
                for value in connection.execute(
                    text(
                        "SELECT revision FROM diagnostic_schema_migrations "
                        "ORDER BY revision"
                    )
                ).scalars()
            )
        if (
            state.persistence_revision != DIAGNOSTIC_SCHEMA_REVISION
            or DIAGNOSTIC_SCHEMA_REVISION not in rows
            or set(rows) != _SUPPORTED_MIGRATIONS
        ):
            raise _ReadFailure(
                code=ApplicationReadErrorCode.CONTRACT_INCOMPATIBLE,
                message="The Strategy Diagnostics persistence schema is incompatible.",
                retryable=False,
                availability=ApplicationReadAvailability.FAILED,
                episode="persistence-schema",
            )

    def _campaign_member(
        self,
        campaign: DiagnosticCampaignSnapshot,
        run_id: str,
    ) -> tuple[
        DiagnosticCampaignCaseSnapshot | None,
        Mapping[str, object] | None,
    ]:
        matches: list[tuple[DiagnosticCampaignCaseSnapshot, Mapping[str, object]]] = []
        for case in campaign.cases:
            if not case.attempts:
                continue
            latest = case.attempts[-1].to_dict()
            members = latest.get("members", ())
            if not isinstance(members, Sequence) or isinstance(
                members,
                (str, bytes),
            ):
                raise _identity_failure("campaign-members")
            for candidate in members:
                if not isinstance(candidate, Mapping):
                    raise _identity_failure("campaign-member")
                if candidate.get("run_id") == run_id:
                    matches.append((case, candidate))
        if not matches:
            return None, None
        if len(matches) != 1:
            raise _identity_failure("campaign-run-membership")
        return matches[0]

    def _validate_run_membership(
        self,
        case: DiagnosticCampaignCaseSnapshot,
        member: Mapping[str, object],
        run: StrategyRunSnapshot,
    ) -> None:
        member_specification = member.get("specification")
        if (
            run.run_id != member.get("run_id")
            or not isinstance(member_specification, Mapping)
            or dict(member_specification) != run.specification.to_dict()
            or run.specification.recipe_version_id
            != case.specification.recipe_version_id
            or run.specification.recipe_content_hash
            != case.specification.recipe_content_hash
            or run.specification.materialization_hash
            != case.specification.materialization_hash
        ):
            raise _identity_failure("campaign-run")

    def _resolve_package(
        self,
        selector: V1JourneySelector,
        campaign: DiagnosticCampaignSnapshot,
    ) -> DiagnosticEvidencePackage | None:
        selected = (
            selector.evidence_package_id.value
            if selector.evidence_package_id is not None
            else None
        )
        if selector.manifest_id is not None and selected is None:
            with self._engine.connect() as connection:
                selected = connection.execute(
                    text(
                        "SELECT evidence_package_id "
                        "FROM diagnostic_reproduction_manifests "
                        "WHERE manifest_id = :manifest_id"
                    ),
                    {"manifest_id": selector.manifest_id.value},
                ).scalar_one_or_none()
            if selected is not None:
                selected = str(selected)
        if selected is None:
            with self._engine.connect() as connection:
                package_ids = tuple(
                    str(value)
                    for value in connection.execute(
                        text(
                            "SELECT evidence_package_id "
                            "FROM diagnostic_evidence_packages "
                            "WHERE campaign_id = :campaign_id "
                            "ORDER BY evidence_package_id"
                        ),
                        {"campaign_id": campaign.campaign_id},
                    ).scalars()
                )
            if not package_ids:
                return None
            if len(package_ids) != 1:
                raise _ReadFailure(
                    code=ApplicationReadErrorCode.EVIDENCE_SELECTION_AMBIGUOUS,
                    message=(
                        "More than one sealed evidence package exists; select "
                        "one by exact identity."
                    ),
                    retryable=False,
                    availability=ApplicationReadAvailability.FAILED,
                    episode=f"ambiguous:{campaign.campaign_id}",
                )
            selected = package_ids[0]
        if not self._row_exists(
            "diagnostic_evidence_packages",
            "evidence_package_id",
            selected,
        ):
            raise _not_found("evidence", selected)
        package = self._application.diagnostic_evidence_status(selected)
        payload = package.sealed_payload()
        if (
            package.evidence_package_id != selected
            or package.campaign_id != campaign.campaign_id
            or payload.get("campaign_type") != "formal_diagnostic_campaign"
            or payload.get("status") != "sealed"
        ):
            raise _identity_failure("evidence-package")
        return package

    def _resolve_manifest(
        self,
        selector: V1JourneySelector,
        package: DiagnosticEvidencePackage | None,
        case: DiagnosticCampaignCaseSnapshot,
        run: StrategyRunSnapshot,
    ) -> ReproductionManifest | None:
        if package is None:
            if selector.manifest_id is not None:
                raise _not_found("manifest", selector.manifest_id.value)
            return None
        manifests = self._application.reproduction_manifests(
            package.evidence_package_id
        )
        matching = tuple(
            item
            for item in manifests
            if item.run_id == run.run_id and item.case_id == case.case_id
        )
        if selector.manifest_id is not None:
            matching = tuple(
                item
                for item in matching
                if item.manifest_id == selector.manifest_id.value
            )
        if not matching:
            if selector.manifest_id is not None and not self._row_exists(
                "diagnostic_reproduction_manifests",
                "manifest_id",
                selector.manifest_id.value,
            ):
                raise _not_found("manifest", selector.manifest_id.value)
            if selector.manifest_id is not None:
                raise _identity_failure("reproduction-manifest-selection")
            raise _integrity_failure("reproduction-manifest-missing")
        if len(matching) != 1:
            raise _identity_failure("reproduction-manifest-selection")
        manifest = matching[0]
        payload = package.sealed_payload()
        references = tuple(
            cast(Mapping[str, object], item)
            for item in cast(
                Sequence[object],
                payload["reproduction_manifests"],
            )
        )
        reference = tuple(
            item for item in references if item.get("run_id") == run.run_id
        )
        if (
            len(reference) != 1
            or reference[0].get("reproduction_manifest_id")
            != manifest.evidence_reference_id
            or manifest.specification != run.specification
            or manifest.run_artifact_hash != run.run_artifact_hash
            or manifest.evidence_package_id != package.evidence_package_id
            or manifest.evidence_artifact_hash != package.artifact_hash
            or manifest.measurement_artifact_hash
            != payload.get("measurement_artifact_hash")
            or manifest.case_id != case.case_id
            or manifest.layer != case.layer
        ):
            raise _identity_failure("reproduction-manifest")
        return manifest

    def _typed_journey(
        self,
        campaign: DiagnosticCampaignSnapshot,
        case: DiagnosticCampaignCaseSnapshot,
        run: StrategyRunSnapshot,
        package: DiagnosticEvidencePackage | None,
        manifest: ReproductionManifest | None,
    ) -> ResolvedV1Journey:
        coverage = _coverage(case.layer)
        campaign_id = FormalDiagnosticCampaignId(campaign.campaign_id)
        run_id = StrategyRunId(run.run_id)
        case_id = MarketScenarioId(case.case_id)
        manifest_id = (
            ReproductionManifestId(manifest.manifest_id)
            if manifest is not None
            else None
        )
        evidence_selection = EvidenceAndFindingsSelection(
            campaign_id=campaign_id,
            run_id=run_id,
            strategy_id=StrategyUnderTestId(run.specification.strategy_id),
            market_scenario_id=case_id,
            approved_recipe_id=ApprovedScenarioRecipeId(
                run.specification.recipe_version_id
            ),
            reproduction_manifest_id=manifest_id,
        )
        return ResolvedV1Journey(
            run_context=RunMonitoringContext.for_run(
                RunMonitoringSelection(
                    campaign_id=campaign_id,
                    run_id=run_id,
                )
            ),
            evidence_context=EvidenceAndFindingsContext.for_selection(
                evidence_selection
            ),
            evidence_package_id=(
                DiagnosticEvidencePackageId(package.evidence_package_id)
                if package is not None
                else None
            ),
            campaign_case_id=case_id,
            campaign_layer=coverage,
        )

    def _map_run(
        self,
        resolved: _ResolvedBackendJourney,
    ) -> RunMonitoringData:
        run = resolved.run
        specification = run.specification
        current = run.current_simulation_time
        assert current is not None
        if run.total_node_count < 1:
            raise ValueError("Strategy Run total node count is invalid")
        lifecycle = _LIFECYCLE_BY_STATUS.get(run.status)
        if lifecycle is None:
            raise ValueError("Unsupported Strategy Run lifecycle")
        if run.status == "completed" and (
            run.processed_node_count != run.total_node_count
            or run.run_artifact_hash is None
        ):
            raise ValueError("Completed Strategy Run integrity failed")
        if run.status == "failed" and (not run.failure_code or not run.failure_message):
            raise ValueError("Failed Strategy Run lacks a stable failure")
        if run.status == "cancelled" and run.run_artifact_hash is not None:
            raise ValueError("Canceled Strategy Run cannot claim a completed artifact")

        observed_at = resolved.observed_at
        assumptions = ()
        if specification.resolved_execution_conditions is not None:
            assumptions = tuple(
                ExecutionAssumption(
                    name=item.name,
                    requested_value=item.requested_value,
                    effective_value=item.effective_value,
                    override_reason=item.override_reason,
                )
                for item in specification.resolved_execution_conditions.resolutions
            )
        session_dates = {
            point.simulation_time.date()
            for point in run.equity_curve
            if point.simulation_time <= current
        }
        positions = tuple(
            (
                f"{item.instrument} · {item.shares} shares · "
                f"market value {_decimal_text(item.market_value)}"
            )
            for item in run.positions
        )
        orders = tuple(
            (
                f"{item.order_id} · {item.instrument} · {item.status} · "
                f"{item.shares} shares"
            )
            for item in run.orders
        )
        fills = tuple(
            (
                f"{item.fill_id} · {item.instrument} · {item.shares} @ "
                f"{_decimal_text(item.price)}"
            )
            for item in run.fills
        )
        alerts: tuple[RunAlert, ...] = ()
        if run.status == "failed":
            alerts = (
                RunAlert(
                    code=cast(str, run.failure_code),
                    severity=AlertSeverity.ERROR,
                    message="The persisted Strategy Run ended with a failure.",
                ),
            )
        selection = resolved.typed.run_context.selection
        assert selection is not None
        return RunMonitoringData(
            selection=selection,
            strategy_id=StrategyUnderTestId(specification.strategy_id),
            market_scenario_id=resolved.typed.campaign_case_id,
            scenario_set_id=self._scenario_set_id(resolved),
            reproduction_manifest_id=(
                ReproductionManifestId(resolved.manifest.manifest_id)
                if resolved.manifest is not None
                else None
            ),
            task_id=None,
            lifecycle=lifecycle,
            terminal_outcome=_TERMINAL_BY_STATUS.get(run.status),
            progress=RunProgress(
                current_node_id=(f"{resolved.case.case_id}:{run.processed_node_count}"),
                current_node_label=(
                    f"{resolved.case.layer} · "
                    f"{run.processed_node_count}/{run.total_node_count}"
                ),
                completed=run.processed_node_count,
                total=run.total_node_count,
            ),
            simulation_time=SimulationTime(
                sim_day=len(session_dates),
                instant=_aware(current),
            ),
            wall_time=WallTime(
                started_at=None,
                observed_at=observed_at,
                elapsed=timedelta(0),
            ),
            execution_assumptions=assumptions,
            alerts=alerts,
            context=ReadOnlyDiagnosticContext(
                market=tuple(
                    item
                    for item in (
                        f"case {resolved.case.case_id}",
                        (
                            f"strategy {specification.strategy_id}"
                            f"@{specification.strategy_version}"
                        ),
                        f"approved recipe {specification.recipe_version_id}",
                        (
                            f"manifest {resolved.manifest.manifest_id}"
                            if resolved.manifest is not None
                            else None
                        ),
                        f"materialization {specification.materialization_hash}",
                        (
                            f"run artifact {run.run_artifact_hash}"
                            if run.run_artifact_hash is not None
                            else None
                        ),
                        f"Simulation Time {_aware(current).isoformat()}",
                    )
                    if item is not None
                ),
                account=(
                    f"cash {_decimal_text(run.cash)}",
                    (
                        f"equity {_decimal_text(run.equity_curve[-1].equity)}"
                        if run.equity_curve
                        else "equity unavailable"
                    ),
                ),
                positions=positions,
                orders=orders,
                fills=fills,
            ),
            capabilities=DiagnosticTaskCapabilities(
                can_pause=False,
                can_resume=False,
                can_cancel=False,
            ),
            active_task=None,
        )

    def _scenario_set_id(
        self,
        resolved: _ResolvedBackendJourney,
    ) -> ScenarioSetId:
        if resolved.case.layer == "isolated_sensitivity":
            sensitivity = resolved.campaign.specification.isolated_sensitivity_set
            if sensitivity is None:
                raise ValueError("Isolated case lacks its sensitivity set")
            return ScenarioSetId(sensitivity.sensitivity_set_id)
        return ScenarioSetId(f"{resolved.campaign.campaign_id}:{resolved.case.layer}")

    def _map_evidence(
        self,
        resolved: _ResolvedBackendJourney,
    ) -> EvidenceAndFindingsData:
        package = resolved.package
        manifest = resolved.manifest
        assert package is not None and manifest is not None
        payload = package.sealed_payload()
        graph = _SealedEvidenceGraph.from_payload(payload)
        manifests = self._application.reproduction_manifests(
            package.evidence_package_id
        )
        manifests_by_reference = {
            item.evidence_reference_id: item for item in manifests
        }
        self._validate_evidence_graph(
            graph,
            manifests_by_reference,
        )

        candidate_keys = sorted(
            {
                (str(item["strategy_id"]), str(item["strategy_version"]))
                for item in graph.metrics
            }
        )
        candidates = tuple(
            self._map_candidate(
                strategy_id,
                strategy_version,
                graph,
                manifests,
                package,
            )
            for strategy_id, strategy_version in candidate_keys
        )
        selection = resolved.typed.evidence_context.selection
        assert selection is not None
        return EvidenceAndFindingsData(
            evidence_package_id=DiagnosticEvidencePackageId(
                package.evidence_package_id
            ),
            selection=selection,
            candidates=candidates,
            read_only_context=self._evidence_context(resolved.run),
        )

    def _validate_evidence_graph(
        self,
        graph: _SealedEvidenceGraph,
        manifests_by_reference: Mapping[str, ReproductionManifest],
    ) -> None:
        metric_ids = _unique_source_ids(graph.metrics, "metric_id")
        comparison_ids = _unique_source_ids(graph.comparisons, "comparison_id")
        breakpoint_ids = _unique_source_ids(graph.breakpoints, "breakpoint_id")
        _unique_source_ids(graph.findings, "finding_id")
        for comparison in graph.comparisons:
            if not {
                str(comparison["control_metric_id"]),
                str(comparison["subject_metric_id"]),
            }.issubset(metric_ids):
                raise ValueError("Evidence comparison has a dangling metric")
        for breakpoint in graph.breakpoints:
            if not _string_set(breakpoint, "metric_ids").issubset(metric_ids):
                raise ValueError("Sensitivity breakpoint has a dangling metric")
            if not _string_set(
                breakpoint,
                "comparison_ids",
            ).issubset(comparison_ids):
                raise ValueError("Sensitivity breakpoint has a dangling comparison")
        for finding in graph.findings:
            if not _string_set(finding, "metric_ids").issubset(metric_ids):
                raise ValueError("Finding has a dangling metric")
            if not _string_set(
                finding,
                "comparison_ids",
            ).issubset(comparison_ids):
                raise ValueError("Finding has a dangling comparison")
            if not _string_set(
                finding,
                "breakpoint_ids",
            ).issubset(breakpoint_ids):
                raise ValueError("Finding has a dangling breakpoint")
            if any(
                reference not in manifests_by_reference
                for reference in _string_set(
                    finding,
                    "reproduction_manifest_ids",
                )
            ):
                raise ValueError("Finding has a dangling Reproduction Manifest")

    def _map_candidate(
        self,
        strategy_id: str,
        strategy_version: str,
        graph: _SealedEvidenceGraph,
        manifests: tuple[ReproductionManifest, ...],
        package: DiagnosticEvidencePackage,
    ) -> CandidateEvidence:
        selected_metrics = tuple(
            sorted(
                (
                    item
                    for item in graph.metrics
                    if item["strategy_id"] == strategy_id
                    and item["strategy_version"] == strategy_version
                ),
                key=lambda item: (
                    str(item["layer"]),
                    _dimension(str(item["name"])).value,
                    str(item["case_id"]),
                    str(item["name"]),
                    str(item["metric_id"]),
                ),
            )
        )
        metric_ids = {str(item["metric_id"]) for item in selected_metrics}
        selected_comparisons = tuple(
            sorted(
                (
                    item
                    for item in graph.comparisons
                    if item.get("subject_strategy_id") == strategy_id
                    and item.get("subject_strategy_version") == strategy_version
                ),
                key=lambda item: str(item["comparison_id"]),
            )
        )
        selected_findings = tuple(
            sorted(
                (
                    item
                    for item in graph.findings
                    if item["strategy_id"] == strategy_id
                    and item["strategy_version"] == strategy_version
                ),
                key=lambda item: str(item["finding_id"]),
            )
        )
        breakpoints_by_id = {
            str(item["breakpoint_id"]): item for item in graph.breakpoints
        }
        mapped_records = tuple(_map_metric(item) for item in selected_metrics)
        mapped_comparisons = tuple(
            _map_comparison(item) for item in selected_comparisons
        )
        mapped_findings = tuple(
            _map_finding(
                item,
                graph.comparisons,
                breakpoints_by_id,
            )
            for item in selected_findings
        )
        relevant_manifests = tuple(
            item
            for item in manifests
            if item.specification.strategy_id == strategy_id
            and item.specification.strategy_version == strategy_version
        )
        run_ids = tuple(
            StrategyRunId(value)
            for value in sorted({str(item["run_id"]) for item in selected_metrics})
        )
        artifact_hashes = {
            package.artifact_hash,
            str(package.sealed_payload()["measurement_artifact_hash"]),
        }
        for item in relevant_manifests:
            artifact_hashes.update(
                {
                    item.run_artifact_hash,
                    item.evidence_artifact_hash,
                    item.measurement_artifact_hash,
                    item.specification.materialization_hash,
                    item.specification.recipe_content_hash,
                    item.manifest_content_hash,
                }
            )
        assumptions = ()
        if relevant_manifests:
            resolved_conditions = relevant_manifests[
                0
            ].specification.resolved_execution_conditions
            if resolved_conditions is not None:
                assumptions = tuple(
                    ExecutionAssumption(
                        name=item.name,
                        requested_value=item.requested_value,
                        effective_value=item.effective_value,
                        override_reason=item.override_reason,
                    )
                    for item in resolved_conditions.resolutions
                )
        if not metric_ids or not relevant_manifests:
            raise ValueError("Evidence candidate is missing authoritative V1 facts")
        return CandidateEvidence(
            identity=DiagnosticCandidateId(f"{strategy_id}@{strategy_version}"),
            label=f"{strategy_id} · {strategy_version}",
            evidence=mapped_records,
            comparisons=mapped_comparisons,
            findings=mapped_findings,
            execution_assumptions=assumptions,
            provenance=EvidenceProvenance(
                artifact_hashes=tuple(
                    f"sha256:{value}" for value in sorted(artifact_hashes)
                ),
                source_run_ids=run_ids,
                runner_version="strategy-diagnostics-v1",
                build_version=(relevant_manifests[0].specification.code_identity),
                dependencies=tuple(
                    DependencyProvenance(
                        name="reproduction-manifest",
                        version=item.manifest_id,
                        artifact_hash=(f"sha256:{item.manifest_content_hash}"),
                    )
                    for item in sorted(
                        relevant_manifests,
                        key=lambda value: value.manifest_id,
                    )
                ),
            ),
            chart=None,
        )

    def _evidence_context(
        self,
        run: StrategyRunSnapshot,
    ) -> ReadOnlyEvidenceContext:
        return ReadOnlyEvidenceContext(
            market=(f"materialization {run.specification.materialization_hash}",),
            account=(f"cash {_decimal_text(run.cash)}",),
            positions=tuple(
                (
                    f"{item.instrument} · {item.shares} shares · "
                    f"market value {_decimal_text(item.market_value)}"
                )
                for item in run.positions
            ),
            orders=tuple(
                OrderEvidenceTrace(
                    identity=item.order_id,
                    instrument=item.instrument,
                    status=item.status,
                    diagnostic_note="Read-only persisted V1 Strategy Order.",
                )
                for item in run.orders
            ),
            fills=tuple(
                FillEvidenceTrace(
                    identity=item.fill_id,
                    order_identity=item.order_id,
                    instrument=item.instrument,
                    quantity=item.shares,
                    price=_decimal_text(item.price),
                )
                for item in run.fills
            ),
        )

    def _observed_at(
        self,
        run: StrategyRunSnapshot,
    ) -> datetime:
        if run.status in _TERMINAL_BY_STATUS:
            return _aware(self._clock())
        with self._engine.connect() as connection:
            value = connection.execute(
                text(
                    "SELECT updated_at_utc FROM diagnostic_strategy_runs "
                    "WHERE run_id = :run_id"
                ),
                {"run_id": run.run_id},
            ).scalar_one()
        return _parse_aware(value)

    def _row_exists(self, table: str, key: str, value: str) -> bool:
        allowed = {
            ("diagnostic_campaigns", "campaign_id"),
            ("diagnostic_strategy_runs", "run_id"),
            (
                "diagnostic_evidence_packages",
                "evidence_package_id",
            ),
            (
                "diagnostic_reproduction_manifests",
                "manifest_id",
            ),
        }
        if (table, key) not in allowed:
            raise ValueError("Unsupported diagnostics metadata query")
        with self._engine.connect() as connection:
            result = connection.execute(
                text(f"SELECT {key} FROM {table} WHERE {key} = :value"),
                {"value": value},
            ).scalar_one_or_none()
        return result is not None

    def _result(
        self,
        *,
        availability: ApplicationReadAvailability,
        value: Any,
        error: ApplicationReadError | None,
        observed_at: datetime,
    ) -> ApplicationReadResult[Any]:
        semantic = {
            "availability": availability.value,
            "value": _semantic_token_value(value),
            "error": _canonical_value(error),
        }
        return ApplicationReadResult(
            availability=availability,
            source_token=_source_token(semantic),
            source_observed_at=_aware(observed_at),
            value=value,
            error=error,
        )

    def _failure_result(
        self,
        failure: _ReadFailure,
    ) -> ApplicationReadResult[Any]:
        error = self._error(
            code=failure.code,
            message=failure.message,
            retryable=failure.retryable,
            episode=failure.episode,
        )
        return self._result(
            availability=failure.availability,
            value=failure.value,
            error=error,
            observed_at=_aware(self._clock()),
        )

    def _error(
        self,
        *,
        code: ApplicationReadErrorCode,
        message: str,
        retryable: bool,
        episode: str,
    ) -> ApplicationReadError:
        return ApplicationReadError(
            code=code,
            message=message,
            retryable=retryable,
            correlation_id=hashlib.sha256(f"{code}:{episode}".encode()).hexdigest()[
                :24
            ],
        )


def _selector_from(journey: ResolvedV1Journey) -> V1JourneySelector:
    run_selection = journey.run_context.selection
    evidence_selection = journey.evidence_context.selection
    if run_selection is None or run_selection.run_id is None:
        raise _identity_failure("run-context")
    if evidence_selection is None:
        raise _identity_failure("evidence-context")
    if (
        evidence_selection.campaign_id != run_selection.campaign_id
        or evidence_selection.run_id != run_selection.run_id
        or evidence_selection.market_scenario_id != journey.campaign_case_id
    ):
        raise _identity_failure("resolved-journey")
    return V1JourneySelector(
        campaign_id=run_selection.campaign_id,
        run_id=run_selection.run_id,
        evidence_package_id=journey.evidence_package_id,
        manifest_id=evidence_selection.reproduction_manifest_id,
    )


def _require_exact_journey(
    claimed: ResolvedV1Journey,
    resolved: ResolvedV1Journey,
) -> None:
    if claimed != resolved:
        raise _identity_failure("resolved-journey")


def _selector_episode(selector: V1JourneySelector) -> str:
    return ":".join(
        (
            selector.campaign_id.value,
            selector.run_id.value,
            (
                selector.evidence_package_id.value
                if selector.evidence_package_id is not None
                else "pending-package"
            ),
            (
                selector.manifest_id.value
                if selector.manifest_id is not None
                else "pending-manifest"
            ),
        )
    )


def _not_found(kind: str, identity: str) -> _ReadFailure:
    return _ReadFailure(
        code=ApplicationReadErrorCode.SELECTION_NOT_FOUND,
        message=(f"The selected Strategy Diagnostics {kind} identity was not found."),
        retryable=False,
        availability=ApplicationReadAvailability.NOT_FOUND,
        episode=f"{kind}:{identity}",
    )


def _identity_failure(episode: str) -> _ReadFailure:
    return _ReadFailure(
        code=ApplicationReadErrorCode.IDENTITY_MISMATCH,
        message="The selected Strategy Diagnostics identities do not agree.",
        retryable=False,
        availability=ApplicationReadAvailability.FAILED,
        episode=episode,
    )


def _integrity_failure(episode: str) -> _ReadFailure:
    return _ReadFailure(
        code=ApplicationReadErrorCode.INTEGRITY_FAILED,
        message="Persisted Strategy Diagnostics evidence failed integrity validation.",
        retryable=False,
        availability=ApplicationReadAvailability.FAILED,
        episode=episode,
    )


def _mapping_failure(episode: str) -> _ReadFailure:
    return _ReadFailure(
        code=ApplicationReadErrorCode.EVIDENCE_MAPPING_FAILED,
        message="Persisted diagnostics data cannot be mapped without semantic loss.",
        retryable=False,
        availability=ApplicationReadAvailability.FAILED,
        episode=episode,
    )


def _transient_failure(episode: str) -> _ReadFailure:
    return _ReadFailure(
        code=ApplicationReadErrorCode.READ_FAILED,
        message="The Strategy Diagnostics application could not be read.",
        retryable=True,
        availability=ApplicationReadAvailability.FAILED,
        episode=episode,
    )


def _coverage(layer: str) -> EvidenceCoverage:
    try:
        return _COVERAGE_BY_LAYER[layer]
    except KeyError as error:
        raise ValueError("Unsupported Formal Campaign layer") from error


def _mapping_sequence(
    payload: Mapping[str, object],
    key: str,
) -> tuple[Mapping[str, object], ...]:
    value = payload.get(key)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{key} must be a sequence")
    result = tuple(value)
    if not all(isinstance(item, Mapping) for item in result):
        raise ValueError(f"{key} must contain objects")
    return cast(tuple[Mapping[str, object], ...], result)


def _unique_source_ids(
    values: Sequence[Mapping[str, object]],
    key: str,
) -> set[str]:
    identities = tuple(str(item[key]) for item in values)
    if any(not value.strip() for value in identities):
        raise ValueError(f"{key} cannot be blank")
    if len(set(identities)) != len(identities):
        raise ValueError(f"{key} values must be unique")
    return set(identities)


def _string_set(
    payload: Mapping[str, object],
    key: str,
) -> set[str]:
    value = payload.get(key)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{key} must be a sequence")
    return {str(item) for item in value}


def _dimension(name: str) -> EvidenceDimension:
    if name in _RETURN_METRICS:
        return EvidenceDimension.RETURN
    if name in _RISK_METRICS:
        return EvidenceDimension.RISK
    if name in _EXPOSURE_METRICS:
        return EvidenceDimension.EXPOSURE
    if name in _EXECUTION_METRICS:
        return EvidenceDimension.EXECUTION
    raise ValueError("Unsupported V1 metric family")


def _unit(name: str) -> str:
    if name in _RATIO_METRICS:
        return "ratio"
    if name == "execution_erosion_bps":
        return "bps"
    if name in _DURATION_METRICS:
        return "Simulation Time minutes"
    if name in _CURRENCY_METRICS:
        return "currency"
    if name in _QUANTITY_METRICS:
        return "shares"
    if name in _COUNT_METRICS:
        return "count"
    raise ValueError("Unsupported V1 metric unit")


def _map_metric(payload: Mapping[str, object]) -> EvidenceRecord:
    name = str(payload["name"])
    return EvidenceRecord(
        identity=EvidenceRecordId(str(payload["metric_id"])),
        coverage=_coverage(str(payload["layer"])),
        dimension=_dimension(name),
        label=name.replace("_", " "),
        value=str(payload["value"]),
        comparison_evidence_id=None,
        comparison_value=None,
        unit=_unit(name),
        availability=EvidenceAvailability.COMPLETE,
        interpretation=(
            f"Persisted V1 {name} for case {payload['case_id']} and "
            f"run {payload['run_id']}."
        ),
        counts_toward_formal_completeness=True,
    )


def _map_comparison(payload: Mapping[str, object]) -> EvidenceComparison:
    return EvidenceComparison(
        identity=EvidenceComparisonId(str(payload["comparison_id"])),
        label=(
            f"{payload['kind']} · {payload['metric_name']} · "
            f"{payload['control_case_id']} → {payload['subject_case_id']}"
        ),
        reference_evidence_id=EvidenceRecordId(str(payload["control_metric_id"])),
        observed_evidence_id=EvidenceRecordId(str(payload["subject_metric_id"])),
        interpretation=(
            f"Persisted V1 delta {payload['delta']} between control run "
            f"{payload['control_run_id']} and subject run "
            f"{payload['subject_run_id']}."
        ),
    )


def _map_finding(
    payload: Mapping[str, object],
    comparisons: Sequence[Mapping[str, object]],
    breakpoints_by_id: Mapping[str, Mapping[str, object]],
) -> Finding:
    comparison_ids = tuple(
        EvidenceComparisonId(value)
        for value in sorted(_string_set(payload, "comparison_ids"))
    )
    comparison_by_id = {str(item["comparison_id"]): item for item in comparisons}
    summaries = tuple(
        (f"{value}: delta {comparison_by_id[value]['delta']}")
        for value in sorted(_string_set(payload, "comparison_ids"))
    )
    breakpoints = tuple(
        _map_breakpoint(breakpoints_by_id[value])
        for value in sorted(_string_set(payload, "breakpoint_ids"))
    )
    kind = str(payload["kind"])
    disposition = {
        "profit_source": FindingDisposition.SUPPORTED,
        "robustness": FindingDisposition.SUPPORTED,
        "weakness": FindingDisposition.CONCERN,
    }.get(kind)
    if disposition is None:
        raise ValueError("Unsupported V1 Finding kind")
    threshold_ids = sorted(_string_set(payload, "threshold_ids"))
    return Finding(
        identity=FindingId(str(payload["finding_id"])),
        title=str(payload["statement"]),
        disposition=disposition,
        comparison_summary=(
            "; ".join(summaries) if summaries else "No comparison edge is cited."
        ),
        failure_reason=(
            f"Persisted threshold identities: {', '.join(threshold_ids)}"
            if threshold_ids
            else None
        ),
        evidence_ids=tuple(
            EvidenceRecordId(value)
            for value in sorted(_string_set(payload, "metric_ids"))
        ),
        comparison_ids=comparison_ids,
        sensitivity_breakpoints=breakpoints,
    )


def _map_breakpoint(
    payload: Mapping[str, object],
) -> SensitivityBreakpoint:
    threshold = payload.get("threshold")
    if not isinstance(threshold, Mapping):
        raise TypeError("Sensitivity breakpoint threshold must be an object")
    observed = payload.get("observed_level")
    bounded = payload.get("bounded_interval")
    outcome = (
        f"Observed at {json.dumps(observed, sort_keys=True)}"
        if observed is not None
        else f"Bounded by {json.dumps(bounded, sort_keys=True)}"
    )
    return SensitivityBreakpoint(
        identity=SensitivityBreakpointId(str(payload["breakpoint_id"])),
        assumption_name=str(payload["transformation_family"]),
        threshold=(f"{threshold.get('operator')} {threshold.get('value')}"),
        outcome=outcome,
        evidence_ids=tuple(
            EvidenceRecordId(value)
            for value in sorted(_string_set(payload, "metric_ids"))
        ),
    )


def _canonical_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical_value(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return _aware(value).isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonical_value(child) for child in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError("Unsupported semantic token value")


def _semantic_token_value(value: object) -> object:
    canonical = _canonical_value(value)
    if isinstance(value, RunMonitoringData):
        if not isinstance(canonical, dict):
            raise TypeError("Run Monitoring token value must be an object")
        wall_time = canonical.get("wall_time")
        if not isinstance(wall_time, dict):
            raise TypeError("Run Monitoring Wall Time must be an object")
        canonical = dict(canonical)
        canonical["wall_time"] = {
            key: child for key, child in wall_time.items() if key != "observed_at"
        }
    return canonical


def _source_token(value: object) -> SourceRevisionToken:
    encoded = json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return SourceRevisionToken(hashlib.sha256(encoded).hexdigest())


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_aware(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Persisted timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


__all__ = ["LiveStrategyDiagnosticsV1ApplicationAdapter"]
