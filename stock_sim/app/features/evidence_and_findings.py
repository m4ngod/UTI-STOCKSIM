"""Evidence & Findings Feature Interface and deterministic fake Adapter."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import lru_cache
from math import isfinite, sin
from threading import RLock
from typing import Callable, Protocol, runtime_checkable

from .run_monitoring import (
    Completeness,
    ExecutionAssumption,
    FormalDiagnosticCampaignId,
    Freshness,
    MarketScenarioId,
    ReproductionManifestId,
    SourceGenerationId,
    SourceKind,
    StrategyRunId,
    StrategyUnderTestId,
    StructuredFeatureError,
    ViewPhase,
)
from .versioning import (
    EVIDENCE_AND_FINDINGS_INTERFACE_VERSION,
    FeatureInterfaceVersion,
)


class EvidenceAndFindingsPresentationState(str, Enum):
    LOADING = "loading"
    EMPTY = "empty"
    READY = "ready"
    DISCONNECTED = "disconnected"
    FAILED = "failed"


class EvidenceCoverage(str, Enum):
    BASELINE = "baseline"
    ISOLATED_SENSITIVITY = "isolated_sensitivity"
    COMPOUND_SCENARIO = "compound_scenario"
    QUICK_EXPERIMENT = "quick_experiment"


class EvidenceDimension(str, Enum):
    RETURN = "return"
    RISK = "risk"
    EXECUTION = "execution"
    EXPOSURE = "exposure"
    STABILITY = "stability"
    DOMAIN = "domain"


class EvidenceAvailability(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class FindingDisposition(str, Enum):
    SUPPORTED = "supported"
    CONCERN = "concern"
    FAILED = "failed"
    NOT_ASSESSED = "not_assessed"


class EvidenceChartOverlayAxis(str, Enum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


def _require_identity(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} identity cannot be empty")


@dataclass(frozen=True, slots=True)
class ApprovedScenarioRecipeId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Approved Scenario Recipe")


@dataclass(frozen=True, slots=True)
class DiagnosticEvidencePackageId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Diagnostic Evidence Package")


@dataclass(frozen=True, slots=True)
class DiagnosticCandidateId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Diagnostic candidate")


@dataclass(frozen=True, slots=True)
class EvidenceRecordId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Evidence record")


@dataclass(frozen=True, slots=True)
class EvidenceComparisonId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Evidence comparison")


@dataclass(frozen=True, slots=True)
class FindingId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Finding")


@dataclass(frozen=True, slots=True)
class SensitivityBreakpointId:
    value: str

    def __post_init__(self) -> None:
        _require_identity(self.value, "Sensitivity breakpoint")


@dataclass(frozen=True, slots=True)
class EvidenceAndFindingsSelection:
    campaign_id: FormalDiagnosticCampaignId
    run_id: StrategyRunId
    strategy_id: StrategyUnderTestId | None
    market_scenario_id: MarketScenarioId | None
    approved_recipe_id: ApprovedScenarioRecipeId | None
    reproduction_manifest_id: ReproductionManifestId | None

    def __post_init__(self) -> None:
        expected_types = (
            ("campaign_id", self.campaign_id, FormalDiagnosticCampaignId),
            ("run_id", self.run_id, StrategyRunId),
            ("strategy_id", self.strategy_id, StrategyUnderTestId),
            ("market_scenario_id", self.market_scenario_id, MarketScenarioId),
            (
                "approved_recipe_id",
                self.approved_recipe_id,
                ApprovedScenarioRecipeId,
            ),
            (
                "reproduction_manifest_id",
                self.reproduction_manifest_id,
                ReproductionManifestId,
            ),
        )
        for name, value, expected_type in expected_types:
            if value is not None and not isinstance(value, expected_type):
                raise TypeError(f"{name} must be a {expected_type.__name__}")


@dataclass(frozen=True, slots=True)
class EvidenceAndFindingsContext:
    """Pinned selection carried from the diagnostic research journey."""

    selection: EvidenceAndFindingsSelection | None

    @classmethod
    def no_selection(cls) -> "EvidenceAndFindingsContext":
        return cls(selection=None)

    @classmethod
    def for_selection(
        cls,
        selection: EvidenceAndFindingsSelection,
    ) -> "EvidenceAndFindingsContext":
        return cls(selection=selection)


@dataclass(frozen=True, slots=True)
class EvidenceAndFindingsSource:
    kind: SourceKind
    identity: str
    generation: SourceGenerationId


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    identity: EvidenceRecordId
    coverage: EvidenceCoverage
    dimension: EvidenceDimension
    label: str
    value: str
    comparison_evidence_id: EvidenceRecordId | None
    comparison_value: str | None
    unit: str
    availability: EvidenceAvailability
    interpretation: str
    counts_toward_formal_completeness: bool = True


@dataclass(frozen=True, slots=True)
class SensitivityBreakpoint:
    identity: SensitivityBreakpointId
    assumption_name: str
    threshold: str
    outcome: str
    evidence_ids: tuple[EvidenceRecordId, ...]


@dataclass(frozen=True, slots=True)
class EvidenceComparison:
    identity: EvidenceComparisonId
    label: str
    reference_evidence_id: EvidenceRecordId
    observed_evidence_id: EvidenceRecordId
    interpretation: str


@dataclass(frozen=True, slots=True)
class Finding:
    identity: FindingId
    title: str
    disposition: FindingDisposition
    comparison_summary: str
    failure_reason: str | None
    evidence_ids: tuple[EvidenceRecordId, ...]
    comparison_ids: tuple[EvidenceComparisonId, ...]
    sensitivity_breakpoints: tuple[SensitivityBreakpoint, ...]


@dataclass(frozen=True, slots=True)
class DependencyProvenance:
    name: str
    version: str
    artifact_hash: str


@dataclass(frozen=True, slots=True)
class EvidenceProvenance:
    artifact_hashes: tuple[str, ...]
    source_run_ids: tuple[StrategyRunId, ...]
    runner_version: str
    build_version: str
    dependencies: tuple[DependencyProvenance, ...]


@dataclass(frozen=True, slots=True)
class EvidenceChartOverlay:
    identity: str
    label: str
    axis: EvidenceChartOverlayAxis
    coordinate: float
    interpretation: str
    evidence_ids: tuple[EvidenceRecordId, ...]

    def __post_init__(self) -> None:
        _require_identity(self.identity, "Evidence chart overlay")
        if not self.label.strip():
            raise ValueError("Evidence chart overlay label cannot be empty")
        if not isinstance(self.axis, EvidenceChartOverlayAxis):
            raise TypeError("axis must be an EvidenceChartOverlayAxis")
        if not isfinite(self.coordinate):
            raise ValueError("Evidence chart overlay coordinate must be finite")
        if not self.interpretation.strip():
            raise ValueError(
                "Evidence chart overlay interpretation cannot be empty"
            )
        if not isinstance(self.evidence_ids, tuple) or not self.evidence_ids:
            raise ValueError(
                "Evidence chart overlay must cite immutable diagnostic evidence"
            )


@dataclass(frozen=True, slots=True)
class DiagnosticEvidenceChart:
    """Immutable full-fidelity evidence series held outside the renderer."""

    identity: str
    label: str
    unit: str
    values: tuple[float, ...]
    overlays: tuple[EvidenceChartOverlay, ...]

    def __post_init__(self) -> None:
        _require_identity(self.identity, "Diagnostic evidence chart")
        if not self.label.strip():
            raise ValueError("Diagnostic evidence chart label cannot be empty")
        if not self.unit.strip():
            raise ValueError("Diagnostic evidence chart unit cannot be empty")
        if not isinstance(self.values, tuple) or len(self.values) < 2:
            raise ValueError(
                "Diagnostic evidence chart requires an immutable source series"
            )
        if not all(
            isinstance(value, (int, float)) and isfinite(float(value))
            for value in self.values
        ):
            raise ValueError(
                "Diagnostic evidence chart values must all be finite numbers"
            )
        if not isinstance(self.overlays, tuple) or not self.overlays:
            raise ValueError(
                "Diagnostic evidence chart requires immutable overlays"
            )
        _require_unique_identities(
            "evidence chart overlay",
            tuple(item.identity for item in self.overlays),
        )


def _require_unique_identities(
    label: str,
    identities: tuple[object, ...],
) -> None:
    if len(set(identities)) != len(identities):
        raise ValueError(f"{label} identities must be unique")


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    identity: DiagnosticCandidateId
    label: str
    evidence: tuple[EvidenceRecord, ...]
    comparisons: tuple[EvidenceComparison, ...]
    findings: tuple[Finding, ...]
    execution_assumptions: tuple[ExecutionAssumption, ...]
    provenance: EvidenceProvenance
    chart: DiagnosticEvidenceChart | None = None

    def __post_init__(self) -> None:
        evidence_ids = tuple(item.identity for item in self.evidence)
        comparison_ids = tuple(item.identity for item in self.comparisons)
        finding_ids = tuple(item.identity for item in self.findings)
        breakpoints = tuple(
            breakpoint
            for finding in self.findings
            for breakpoint in finding.sensitivity_breakpoints
        )
        breakpoint_ids = tuple(item.identity for item in breakpoints)

        _require_unique_identities("evidence", evidence_ids)
        _require_unique_identities("comparison", comparison_ids)
        _require_unique_identities("finding", finding_ids)
        _require_unique_identities(
            "sensitivity breakpoint",
            breakpoint_ids,
        )

        evidence_id_set = set(evidence_ids)

        for record in self.evidence:
            has_comparison_id = record.comparison_evidence_id is not None
            has_comparison_value = record.comparison_value is not None
            if has_comparison_id != has_comparison_value:
                raise ValueError(
                    "Evidence comparison_evidence_id and comparison_value "
                    "must be paired"
                )
            if (
                record.comparison_evidence_id is not None
                and record.comparison_evidence_id not in evidence_id_set
            ):
                raise ValueError(
                    "Evidence comparison_evidence_id must reference evidence "
                    "in the same candidate"
                )
            if record.comparison_evidence_id == record.identity:
                raise ValueError(
                    "Evidence comparison_evidence_id must reference different "
                    "evidence"
                )

        for comparison in self.comparisons:
            if (
                comparison.reference_evidence_id
                == comparison.observed_evidence_id
            ):
                raise ValueError(
                    "Evidence comparison reference and observed evidence "
                    "must differ"
                )
        for finding in self.findings:
            _require_unique_identities(
                "finding evidence reference",
                tuple(finding.evidence_ids),
            )
            _require_unique_identities(
                "finding comparison reference",
                tuple(finding.comparison_ids),
            )
            for breakpoint in finding.sensitivity_breakpoints:
                _require_unique_identities(
                    "sensitivity breakpoint evidence reference",
                    tuple(breakpoint.evidence_ids),
                )
        if self.chart is not None:
            for overlay in self.chart.overlays:
                if not set(overlay.evidence_ids).issubset(evidence_id_set):
                    raise ValueError(
                        "Evidence chart overlay references must resolve within "
                        "the same candidate"
                    )


@dataclass(frozen=True, slots=True)
class OrderEvidenceTrace:
    identity: str
    instrument: str
    status: str
    diagnostic_note: str


@dataclass(frozen=True, slots=True)
class FillEvidenceTrace:
    identity: str
    order_identity: str
    instrument: str
    quantity: int
    price: str


@dataclass(frozen=True, slots=True)
class ReadOnlyEvidenceContext:
    market: tuple[str, ...]
    account: tuple[str, ...]
    positions: tuple[str, ...]
    orders: tuple[OrderEvidenceTrace, ...]
    fills: tuple[FillEvidenceTrace, ...]


@dataclass(frozen=True, slots=True)
class EvidenceAndFindingsData:
    """Independently renderable, read-only research evidence payload."""

    evidence_package_id: DiagnosticEvidencePackageId
    selection: EvidenceAndFindingsSelection
    candidates: tuple[CandidateEvidence, ...]
    read_only_context: ReadOnlyEvidenceContext

    def __post_init__(self) -> None:
        if not isinstance(
            self.evidence_package_id,
            DiagnosticEvidencePackageId,
        ):
            raise TypeError(
                "evidence_package_id must be a DiagnosticEvidencePackageId"
            )
        _require_unique_identities(
            "candidate",
            tuple(item.identity for item in self.candidates),
        )
        evidence_ids = tuple(
            record.identity
            for candidate in self.candidates
            for record in candidate.evidence
        )
        comparison_ids = tuple(
            comparison.identity
            for candidate in self.candidates
            for comparison in candidate.comparisons
        )
        finding_ids = tuple(
            finding.identity
            for candidate in self.candidates
            for finding in candidate.findings
        )
        breakpoints = tuple(
            breakpoint
            for candidate in self.candidates
            for finding in candidate.findings
            for breakpoint in finding.sensitivity_breakpoints
        )
        _require_unique_identities("evidence", evidence_ids)
        _require_unique_identities("comparison", comparison_ids)
        _require_unique_identities("finding", finding_ids)
        _require_unique_identities(
            "sensitivity breakpoint",
            tuple(item.identity for item in breakpoints),
        )
        evidence_id_set = set(evidence_ids)
        comparison_id_set = set(comparison_ids)
        for candidate in self.candidates:
            for comparison in candidate.comparisons:
                if not {
                    comparison.reference_evidence_id,
                    comparison.observed_evidence_id,
                }.issubset(evidence_id_set):
                    raise ValueError(
                        "Evidence comparison evidence references must resolve "
                        "within the evidence package"
                    )
            for finding in candidate.findings:
                if not set(finding.evidence_ids).issubset(evidence_id_set):
                    raise ValueError(
                        "Finding evidence references must resolve within the "
                        "evidence package"
                    )
                if not set(finding.comparison_ids).issubset(
                    comparison_id_set
                ):
                    raise ValueError(
                        "Finding comparison references must resolve within the "
                        "evidence package"
                    )
                for breakpoint in finding.sensitivity_breakpoints:
                    if not set(breakpoint.evidence_ids).issubset(
                        evidence_id_set
                    ):
                        raise ValueError(
                            "Sensitivity breakpoint evidence references must "
                            "resolve within the evidence package"
                        )


@dataclass(frozen=True, slots=True)
class EvidenceAndFindingsViewState:
    interface_version: FeatureInterfaceVersion
    revision: int
    observed_at: datetime
    freshness: Freshness
    age: timedelta
    freshness_threshold: timedelta
    source: EvidenceAndFindingsSource
    context: EvidenceAndFindingsContext
    phase: ViewPhase
    presentation: EvidenceAndFindingsPresentationState
    last_reliable_data: EvidenceAndFindingsData | None
    error: StructuredFeatureError | None
    completeness: Completeness


EvidenceAndFindingsObserver = Callable[[EvidenceAndFindingsViewState], None]


@runtime_checkable
class EvidenceAndFindingsSubscription(Protocol):
    @property
    def disposed(self) -> bool: ...

    def dispose(self) -> None: ...


@runtime_checkable
class EvidenceAndFindingsFeature(Protocol):
    @property
    def interface_version(self) -> FeatureInterfaceVersion: ...

    def snapshot(
        self,
        context: EvidenceAndFindingsContext,
    ) -> EvidenceAndFindingsViewState: ...

    def subscribe(
        self,
        context: EvidenceAndFindingsContext,
        observer: EvidenceAndFindingsObserver,
    ) -> EvidenceAndFindingsSubscription: ...

    def close(self) -> None: ...


def _default_fake_time() -> datetime:
    return datetime(2030, 1, 1, tzinfo=timezone.utc)


class _Subscription:
    def __init__(self, dispose: Callable[[], None]) -> None:
        self._dispose = dispose
        self._disposed = False
        self._last_revision = 0
        self._lock = RLock()

    @property
    def disposed(self) -> bool:
        with self._lock:
            return self._disposed

    def dispose(self) -> None:
        with self._lock:
            if self._disposed:
                return
            self._disposed = True
        self._dispose()

    def mark_disposed(self) -> None:
        with self._lock:
            self._disposed = True

    def deliver(
        self,
        observer: EvidenceAndFindingsObserver,
        state: EvidenceAndFindingsViewState,
    ) -> None:
        with self._lock:
            if self._disposed or state.revision <= self._last_revision:
                return
            self._last_revision = state.revision
            try:
                observer(state)
            except Exception:
                return


class DeterministicFakeEvidenceAndFindingsAdapter:
    """Scriptable fake for the read-only Evidence & Findings seam."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = _default_fake_time,
        freshness_threshold: timedelta = timedelta(seconds=5),
        completed_data: EvidenceAndFindingsData | None = None,
    ) -> None:
        self._clock = clock
        self._freshness_threshold = freshness_threshold
        self._completed_data = completed_data
        self._states: dict[
            EvidenceAndFindingsContext,
            EvidenceAndFindingsViewState,
        ] = {}
        self._subscriptions: dict[
            int,
            tuple[
                EvidenceAndFindingsContext,
                EvidenceAndFindingsObserver,
                _Subscription,
            ],
        ] = {}
        self._next_subscription_id = 1
        self._closed = False
        self._lock = RLock()

    @property
    def interface_version(self) -> FeatureInterfaceVersion:
        return EVIDENCE_AND_FINDINGS_INTERFACE_VERSION

    def snapshot(
        self,
        context: EvidenceAndFindingsContext,
    ) -> EvidenceAndFindingsViewState:
        with self._lock:
            self._ensure_open()
            state = self._states.get(context)
            if state is None:
                state = self._loading_state(context)
                self._states[context] = state
            return state

    def subscribe(
        self,
        context: EvidenceAndFindingsContext,
        observer: EvidenceAndFindingsObserver,
    ) -> EvidenceAndFindingsSubscription:
        with self._lock:
            self._ensure_open()
            subscription_id = self._next_subscription_id
            self._next_subscription_id += 1
            subscription = _Subscription(
                lambda: self._remove_subscription(subscription_id)
            )
            self._subscriptions[subscription_id] = (
                context,
                observer,
                subscription,
            )
            state = self._states.get(context)
            if state is None:
                state = self._loading_state(context)
                self._states[context] = state
        subscription.deliver(observer, state)
        return subscription

    def advance_to_completed(
        self,
        context: EvidenceAndFindingsContext,
    ) -> EvidenceAndFindingsViewState:
        selection = context.selection
        if selection is None:
            raise ValueError("A selected research run is required")
        if any(
            identity is None
            for identity in (
                selection.strategy_id,
                selection.market_scenario_id,
                selection.approved_recipe_id,
                selection.reproduction_manifest_id,
            )
        ):
            raise ValueError(
                "Completed evidence requires every pinned research identity"
            )
        data = self._completed_data or _completed_data(selection)
        if data.selection != selection:
            raise ValueError(
                "Scripted completed evidence must match the selected context"
            )
        return self._transition(
            context,
            freshness=Freshness.FRESH,
            phase=ViewPhase.READY,
            presentation=EvidenceAndFindingsPresentationState.READY,
            completeness=Completeness.COMPLETE,
            error=None,
            data=data,
        )

    def advance_to_empty(
        self,
        context: EvidenceAndFindingsContext,
    ) -> EvidenceAndFindingsViewState:
        if context.selection is not None:
            raise ValueError("A selected research run cannot be empty")
        return self._transition(
            context,
            freshness=Freshness.FRESH,
            phase=ViewPhase.READY,
            presentation=EvidenceAndFindingsPresentationState.EMPTY,
            completeness=Completeness.EMPTY,
            error=None,
            data=None,
        )

    def advance_to_stale(
        self,
        context: EvidenceAndFindingsContext,
    ) -> EvidenceAndFindingsViewState:
        current = self.snapshot(context)
        if current.last_reliable_data is None:
            raise ValueError("Stale evidence requires prior reliable data")
        return self._transition(
            context,
            freshness=Freshness.STALE,
            phase=ViewPhase.DEGRADED,
            presentation=EvidenceAndFindingsPresentationState.READY,
            completeness=current.completeness,
            error=StructuredFeatureError(
                code="evidence_and_findings_stale",
                message="Evidence is older than its freshness threshold.",
                retryable=True,
            ),
            data=None,
            age=self._freshness_threshold + timedelta(seconds=1),
        )

    def advance_to_disconnected(
        self,
        context: EvidenceAndFindingsContext,
    ) -> EvidenceAndFindingsViewState:
        current = self.snapshot(context)
        return self._transition(
            context,
            freshness=Freshness.DISCONNECTED,
            phase=(
                ViewPhase.DEGRADED
                if current.last_reliable_data is not None
                else ViewPhase.FAILED
            ),
            presentation=EvidenceAndFindingsPresentationState.DISCONNECTED,
            completeness=Completeness.UNKNOWN,
            error=StructuredFeatureError(
                code="evidence_and_findings_disconnected",
                message="Evidence source is disconnected.",
                retryable=True,
            ),
            data=None,
        )

    def advance_to_partial(
        self,
        context: EvidenceAndFindingsContext,
    ) -> EvidenceAndFindingsViewState:
        current = self.snapshot(context)
        data = current.last_reliable_data
        if data is None:
            raise ValueError("Reliable evidence is required for a partial state")
        candidates = tuple(
            replace(
                candidate,
                evidence=tuple(
                    replace(
                        record,
                        availability=(
                            EvidenceAvailability.PARTIAL
                            if index == 0
                            else EvidenceAvailability.MISSING
                            if index == 1
                            else EvidenceAvailability.UNAVAILABLE
                            if index == 2
                            else record.availability
                        ),
                    )
                    for index, record in enumerate(candidate.evidence)
                ),
            )
            for candidate in data.candidates
        )
        return self._transition(
            context,
            freshness=Freshness.FRESH,
            phase=ViewPhase.DEGRADED,
            presentation=EvidenceAndFindingsPresentationState.READY,
            completeness=Completeness.PARTIAL,
            error=StructuredFeatureError(
                code="evidence_and_findings_partial",
                message=(
                    "Some evidence is partial, missing, or unavailable; "
                    "no formal conclusion is inferred."
                ),
                retryable=True,
            ),
            data=replace(data, candidates=candidates),
        )

    def advance_to_failed(
        self,
        context: EvidenceAndFindingsContext,
    ) -> EvidenceAndFindingsViewState:
        current = self.snapshot(context)
        data = current.last_reliable_data
        if data is None:
            raise ValueError("Reliable evidence is required for a failed state")
        candidates = tuple(
            replace(
                candidate,
                evidence=(
                    replace(
                        candidate.evidence[0],
                        availability=EvidenceAvailability.FAILED,
                    ),
                    *candidate.evidence[1:],
                ),
            )
            for candidate in data.candidates
        )
        return self._transition(
            context,
            freshness=Freshness.FRESH,
            phase=ViewPhase.FAILED,
            presentation=EvidenceAndFindingsPresentationState.FAILED,
            completeness=Completeness.PARTIAL,
            error=StructuredFeatureError(
                code="evidence_and_findings_failed",
                message="Evidence processing failed; no pass state is inferred.",
                retryable=False,
            ),
            data=replace(data, candidates=candidates),
        )

    def replay_scripted_state(
        self,
        context: EvidenceAndFindingsContext,
        state: EvidenceAndFindingsViewState,
    ) -> EvidenceAndFindingsViewState:
        """Accept a scripted state only when revision and generation advance."""

        if state.context != context:
            raise ValueError("Scripted evidence state must match its context")
        with self._lock:
            self._ensure_open()
            previous = self._states.get(context) or self._loading_state(context)
            if (
                state.revision <= previous.revision
                or state.source.generation.value
                < previous.source.generation.value
            ):
                return previous
            self._states[context] = state
            deliveries = tuple(
                (observer, subscription)
                for subscribed_context, observer, subscription
                in self._subscriptions.values()
                if subscribed_context == context
            )
        for observer, subscription in deliveries:
            subscription.deliver(observer, state)
        return state

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            subscriptions = tuple(
                item[2] for item in self._subscriptions.values()
            )
            self._subscriptions.clear()
        for subscription in subscriptions:
            subscription.mark_disposed()

    def _loading_state(
        self,
        context: EvidenceAndFindingsContext,
    ) -> EvidenceAndFindingsViewState:
        return EvidenceAndFindingsViewState(
            interface_version=self.interface_version,
            revision=1,
            observed_at=self._clock(),
            freshness=Freshness.AWAITING_FIRST_STATE,
            age=timedelta(0),
            freshness_threshold=self._freshness_threshold,
            source=EvidenceAndFindingsSource(
                kind=SourceKind.DETERMINISTIC_FAKE,
                identity="frontend-v2-evidence-and-findings-fake",
                generation=SourceGenerationId(1),
            ),
            context=context,
            phase=ViewPhase.LOADING,
            presentation=EvidenceAndFindingsPresentationState.LOADING,
            last_reliable_data=None,
            error=None,
            completeness=Completeness.UNKNOWN,
        )

    def _transition(
        self,
        context: EvidenceAndFindingsContext,
        *,
        freshness: Freshness,
        phase: ViewPhase,
        presentation: EvidenceAndFindingsPresentationState,
        completeness: Completeness,
        error: StructuredFeatureError | None,
        data: EvidenceAndFindingsData | None,
        age: timedelta = timedelta(0),
    ) -> EvidenceAndFindingsViewState:
        with self._lock:
            self._ensure_open()
            previous = self._states.get(context) or self._loading_state(context)
            state = EvidenceAndFindingsViewState(
                interface_version=self.interface_version,
                revision=previous.revision + 1,
                observed_at=self._clock(),
                freshness=freshness,
                age=age,
                freshness_threshold=self._freshness_threshold,
                source=previous.source,
                context=context,
                phase=phase,
                presentation=presentation,
                last_reliable_data=(
                    data if data is not None else previous.last_reliable_data
                ),
                error=error,
                completeness=completeness,
            )
            self._states[context] = state
            deliveries = tuple(
                (observer, subscription)
                for subscribed_context, observer, subscription
                in self._subscriptions.values()
                if subscribed_context == context
            )
        for observer, subscription in deliveries:
            subscription.deliver(observer, state)
        return state

    def _remove_subscription(self, subscription_id: int) -> None:
        with self._lock:
            self._subscriptions.pop(subscription_id, None)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Evidence & Findings Adapter is closed")


def _evidence(
    candidate: str,
    suffix: str,
    *,
    coverage: EvidenceCoverage,
    dimension: EvidenceDimension,
    label: str,
    value: str,
    comparison_value: str | None,
    unit: str,
    interpretation: str,
    formal: bool = True,
    comparison_evidence_id: EvidenceRecordId | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        identity=EvidenceRecordId(f"E-{candidate}-{suffix}"),
        coverage=coverage,
        dimension=dimension,
        label=label,
        value=value,
        comparison_evidence_id=comparison_evidence_id,
        comparison_value=comparison_value,
        unit=unit,
        availability=EvidenceAvailability.COMPLETE,
        interpretation=interpretation,
        counts_toward_formal_completeness=formal,
    )


@lru_cache(maxsize=8)
def _reference_chart(
    candidate_identity: str,
    return_evidence_id: str,
    risk_evidence_id: str,
    sensitivity_evidence_id: str,
) -> DiagnosticEvidenceChart:
    phase_offset = 0.0 if candidate_identity == "MODEL-B17" else 0.35
    values = tuple(
        100.0
        + index * 0.00004
        + 1.7 * sin(index / 911.0 + phase_offset)
        + 0.45 * sin(index / 83.0 + phase_offset)
        for index in range(100_000)
    )
    return DiagnosticEvidenceChart(
        identity=f"{candidate_identity}-diagnostic-series",
        label="Normalized diagnostic outcome path",
        unit="normalized evidence value",
        values=values,
        overlays=(
            EvidenceChartOverlay(
                identity=f"OV-{candidate_identity}-BASELINE",
                label="Baseline reference",
                axis=EvidenceChartOverlayAxis.HORIZONTAL,
                coordinate=100.0,
                interpretation=(
                    "Reference level for the candidate baseline outcome."
                ),
                evidence_ids=(EvidenceRecordId(return_evidence_id),),
            ),
            EvidenceChartOverlay(
                identity=f"OV-{candidate_identity}-DRAWDOWN",
                label="Observed drawdown boundary",
                axis=EvidenceChartOverlayAxis.HORIZONTAL,
                coordinate=97.5,
                interpretation=(
                    "Risk boundary tied to the observed drawdown evidence."
                ),
                evidence_ids=(EvidenceRecordId(risk_evidence_id),),
            ),
            EvidenceChartOverlay(
                identity=f"OV-{candidate_identity}-FEE-BREAKPOINT",
                label="Fee sensitivity breakpoint",
                axis=EvidenceChartOverlayAxis.VERTICAL,
                coordinate=60_000.0,
                interpretation=(
                    "Viewport marker for the fee sensitivity failure evidence."
                ),
                evidence_ids=(EvidenceRecordId(sensitivity_evidence_id),),
            ),
        ),
    )


def _candidate(
    identity: str,
    *,
    label: str,
    run_id: StrategyRunId,
    return_value: str,
    drawdown_value: str,
    breakpoint_threshold: str,
) -> CandidateEvidence:
    evidence = (
        _evidence(
            identity,
            "RET-BASE",
            coverage=EvidenceCoverage.BASELINE,
            dimension=EvidenceDimension.RETURN,
            label="Net return",
            value=return_value,
            comparison_value=None,
            unit="percent",
            interpretation="Baseline return after effective fees.",
        ),
        _evidence(
            identity,
            "RISK-BASE",
            coverage=EvidenceCoverage.BASELINE,
            dimension=EvidenceDimension.RISK,
            label="Maximum drawdown",
            value=drawdown_value,
            comparison_value=None,
            unit="percent",
            interpretation="Observed baseline peak-to-trough loss.",
        ),
        _evidence(
            identity,
            "EXEC-BASE",
            coverage=EvidenceCoverage.BASELINE,
            dimension=EvidenceDimension.EXECUTION,
            label="Baseline fee drag",
            value="-1.1",
            comparison_value=None,
            unit="return delta percentage points",
            interpretation="Effective fee drag in the baseline run.",
        ),
        _evidence(
            identity,
            "EXPOSURE-BASE",
            coverage=EvidenceCoverage.BASELINE,
            dimension=EvidenceDimension.EXPOSURE,
            label="Baseline concentration",
            value="41",
            comparison_value=None,
            unit="percent",
            interpretation="Single-name concentration in the baseline run.",
        ),
        _evidence(
            identity,
            "STABILITY-BASE",
            coverage=EvidenceCoverage.BASELINE,
            dimension=EvidenceDimension.STABILITY,
            label="Baseline profitable windows",
            value="6/8",
            comparison_value=None,
            unit="windows",
            interpretation="Profitable windows in the baseline run.",
        ),
        _evidence(
            identity,
            "DOMAIN-BASE",
            coverage=EvidenceCoverage.BASELINE,
            dimension=EvidenceDimension.DOMAIN,
            label="Baseline entry availability",
            value="available",
            comparison_value=None,
            unit="market rule state",
            interpretation="The expected entry is available at baseline.",
        ),
        _evidence(
            identity,
            "EXEC-ISO",
            coverage=EvidenceCoverage.ISOLATED_SENSITIVITY,
            dimension=EvidenceDimension.EXECUTION,
            label="Fee sensitivity",
            value="-3.8",
            comparison_value="-1.1",
            unit="return delta percentage points",
            interpretation="Fees above the breakpoint erase excess return.",
            comparison_evidence_id=EvidenceRecordId(
                f"E-{identity}-EXEC-BASE"
            ),
        ),
        _evidence(
            identity,
            "EXPOSURE-COMPOUND",
            coverage=EvidenceCoverage.COMPOUND_SCENARIO,
            dimension=EvidenceDimension.EXPOSURE,
            label="Concentration under compound stress",
            value="64",
            comparison_value="41",
            unit="percent",
            interpretation="Stress increases single-name concentration.",
            comparison_evidence_id=EvidenceRecordId(
                f"E-{identity}-EXPOSURE-BASE"
            ),
        ),
        _evidence(
            identity,
            "STABILITY-ISO",
            coverage=EvidenceCoverage.ISOLATED_SENSITIVITY,
            dimension=EvidenceDimension.STABILITY,
            label="Profitable windows",
            value="3/8",
            comparison_value="6/8",
            unit="windows",
            interpretation="Performance is unstable across fee perturbations.",
            comparison_evidence_id=EvidenceRecordId(
                f"E-{identity}-STABILITY-BASE"
            ),
        ),
        _evidence(
            identity,
            "DOMAIN-COMPOUND",
            coverage=EvidenceCoverage.COMPOUND_SCENARIO,
            dimension=EvidenceDimension.DOMAIN,
            label="Limit-up participation",
            value="blocked",
            comparison_value="available",
            unit="market rule state",
            interpretation="Domain constraints prevent expected entry.",
            comparison_evidence_id=EvidenceRecordId(
                f"E-{identity}-DOMAIN-BASE"
            ),
        ),
        _evidence(
            identity,
            "QUICK",
            coverage=EvidenceCoverage.QUICK_EXPERIMENT,
            dimension=EvidenceDimension.EXECUTION,
            label="Quick fee probe",
            value="-2.7",
            comparison_value="-1.1",
            unit="return delta percentage points",
            interpretation=(
                "Exploratory only; this result does not satisfy formal coverage."
            ),
            formal=False,
            comparison_evidence_id=EvidenceRecordId(
                f"E-{identity}-EXEC-BASE"
            ),
        ),
    )
    comparisons = (
        EvidenceComparison(
            identity=EvidenceComparisonId(f"CMP-{identity}-FEE"),
            label="Baseline versus isolated fee sensitivity",
            reference_evidence_id=evidence[2].identity,
            observed_evidence_id=evidence[6].identity,
            interpretation="Isolated fee stress increases return drag.",
        ),
        EvidenceComparison(
            identity=EvidenceComparisonId(f"CMP-{identity}-EXPOSURE"),
            label="Baseline versus compound concentration",
            reference_evidence_id=evidence[3].identity,
            observed_evidence_id=evidence[7].identity,
            interpretation="Compound stress increases concentration.",
        ),
        EvidenceComparison(
            identity=EvidenceComparisonId(f"CMP-{identity}-STABILITY"),
            label="Baseline versus isolated stability",
            reference_evidence_id=evidence[4].identity,
            observed_evidence_id=evidence[8].identity,
            interpretation="Isolated fee stress reduces stable windows.",
        ),
        EvidenceComparison(
            identity=EvidenceComparisonId(f"CMP-{identity}-DOMAIN"),
            label="Baseline versus compound market-rule outcome",
            reference_evidence_id=evidence[5].identity,
            observed_evidence_id=evidence[9].identity,
            interpretation="Compound rules block the expected entry.",
        ),
        EvidenceComparison(
            identity=EvidenceComparisonId(f"CMP-{identity}-QUICK"),
            label="Baseline versus Quick Experiment fee probe",
            reference_evidence_id=evidence[2].identity,
            observed_evidence_id=evidence[10].identity,
            interpretation=(
                "Quick Experiment is exploratory and not formal evidence."
            ),
        ),
    )
    breakpoint = SensitivityBreakpoint(
        identity=SensitivityBreakpointId(f"BP-{identity}-FEE"),
        assumption_name="fee_multiplier",
        threshold=breakpoint_threshold,
        outcome="Excess return becomes non-positive.",
        evidence_ids=(
            evidence[0].identity,
            evidence[6].identity,
            evidence[10].identity,
        ),
    )
    return CandidateEvidence(
        identity=DiagnosticCandidateId(identity),
        label=label,
        evidence=evidence,
        comparisons=comparisons,
        findings=(
            Finding(
                identity=FindingId(f"F-{identity}-01"),
                title="Fee sensitivity breaks the baseline result",
                disposition=FindingDisposition.FAILED,
                comparison_summary=(
                    "Baseline is positive, while isolated and compound stress "
                    "remove the excess return."
                ),
                failure_reason=(
                    "Turnover amplifies effective fees beyond the stable range."
                ),
                evidence_ids=(
                    evidence[0].identity,
                    evidence[6].identity,
                    evidence[8].identity,
                ),
                comparison_ids=(
                    comparisons[0].identity,
                    comparisons[2].identity,
                ),
                sensitivity_breakpoints=(breakpoint,),
            ),
            Finding(
                identity=FindingId(f"F-{identity}-02"),
                title="Market-rule constraints change entry availability",
                disposition=FindingDisposition.CONCERN,
                comparison_summary=(
                    "The compound scenario differs materially from baseline."
                ),
                failure_reason="Limit-up rules block the assumed entry path.",
                evidence_ids=(
                    evidence[7].identity,
                    evidence[9].identity,
                ),
                comparison_ids=(
                    comparisons[1].identity,
                    comparisons[3].identity,
                ),
                sensitivity_breakpoints=(),
            ),
        ),
        execution_assumptions=(
            ExecutionAssumption(
                name="fee_multiplier",
                requested_value="1.0x",
                effective_value="1.6x",
                override_reason="Approved Scenario Recipe override",
            ),
            ExecutionAssumption(
                name="latency_ms",
                requested_value="10",
                effective_value="10",
            ),
        ),
        provenance=EvidenceProvenance(
            artifact_hashes=(
                f"sha256:{identity.casefold()}-metrics",
                f"sha256:{identity.casefold()}-traces",
            ),
            source_run_ids=(run_id,),
            runner_version="evidence-runner/2.4.0",
            build_version="uti-stocksim/0.1.0+fake40",
            dependencies=(
                DependencyProvenance(
                    name="market-calendar",
                    version="2029.1",
                    artifact_hash="sha256:calendar-a13f",
                ),
            ),
        ),
        chart=_reference_chart(
            identity,
            evidence[0].identity.value,
            evidence[1].identity.value,
            evidence[6].identity.value,
        ),
    )


def _completed_data(
    selection: EvidenceAndFindingsSelection,
) -> EvidenceAndFindingsData:
    return EvidenceAndFindingsData(
        evidence_package_id=DiagnosticEvidencePackageId(
            f"diagnostic-evidence-{selection.campaign_id.value}"
        ),
        selection=selection,
        candidates=(
            _candidate(
                "MODEL-B17",
                label="Candidate B17",
                run_id=selection.run_id,
                return_value="8.4",
                drawdown_value="-12.6",
                breakpoint_threshold="1.6x",
            ),
            _candidate(
                "MODEL-A04",
                label="Candidate A04",
                run_id=selection.run_id,
                return_value="6.9",
                drawdown_value="-8.1",
                breakpoint_threshold="2.1x",
            ),
        ),
        read_only_context=ReadOnlyEvidenceContext(
            market=("600519.SH · closed session",),
            account=("MODEL-B17 · simulated research account",),
            positions=("600519.SH · +100 · evidence snapshot",),
            orders=(
                OrderEvidenceTrace(
                    identity="ORD-001",
                    instrument="600519.SH",
                    status="filled",
                    diagnostic_note="Read-only trace; no order action is exposed.",
                ),
            ),
            fills=(
                FillEvidenceTrace(
                    identity="FILL-001",
                    order_identity="ORD-001",
                    instrument="600519.SH",
                    quantity=100,
                    price="1500.00",
                ),
            ),
        ),
    )


__all__ = [
    "ApprovedScenarioRecipeId",
    "CandidateEvidence",
    "DependencyProvenance",
    "DeterministicFakeEvidenceAndFindingsAdapter",
    "DiagnosticCandidateId",
    "DiagnosticEvidencePackageId",
    "EvidenceComparison",
    "EvidenceComparisonId",
    "EvidenceAndFindingsContext",
    "EvidenceAndFindingsData",
    "EvidenceAndFindingsFeature",
    "EvidenceAndFindingsObserver",
    "EvidenceAndFindingsPresentationState",
    "EvidenceAndFindingsSelection",
    "EvidenceAndFindingsSource",
    "EvidenceAndFindingsSubscription",
    "EvidenceAndFindingsViewState",
    "EvidenceAvailability",
    "EvidenceCoverage",
    "EvidenceDimension",
    "EvidenceProvenance",
    "EvidenceRecord",
    "EvidenceRecordId",
    "FillEvidenceTrace",
    "Finding",
    "FindingDisposition",
    "FindingId",
    "OrderEvidenceTrace",
    "ReadOnlyEvidenceContext",
    "SensitivityBreakpoint",
    "SensitivityBreakpointId",
]
