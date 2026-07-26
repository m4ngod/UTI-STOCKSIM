"""Deterministic evidence-chart projection for the QML scene graph."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from app.features import (
    CandidateEvidence,
    Completeness,
    DiagnosticEvidenceChart,
    EvidenceChartOverlayAxis,
    EvidenceAndFindingsPresentationState,
    EvidenceAndFindingsViewState,
    EvidenceCoverage,
    EvidenceDimension,
    Finding,
    SensitivityBreakpoint,
    ViewPhase,
)


class EvidenceChartSamplingPolicy(str, Enum):
    """Versioned policies make viewport projection reproducible."""

    UNIFORM_ENDPOINTS_V1 = "uniform_endpoints_v1"


@dataclass(frozen=True, slots=True)
class EvidenceChartViewport:
    start: float
    end: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.start < self.end <= 1.0):
            raise ValueError(
                "Evidence chart viewport must satisfy 0 <= start < end <= 1"
            )


@dataclass(frozen=True, slots=True)
class EvidenceChartSampleKey:
    source_identity: str
    revision: int
    viewport: EvidenceChartViewport
    resolution: int
    policy: EvidenceChartSamplingPolicy

    def __post_init__(self) -> None:
        if not self.source_identity.strip():
            raise ValueError("Evidence chart source identity cannot be empty")
        if self.revision < 1:
            raise ValueError("Evidence chart revision must be positive")
        if not 2 <= self.resolution <= 4_000:
            raise ValueError(
                "Evidence chart resolution must be between 2 and 4,000"
            )


@dataclass(frozen=True, slots=True)
class EvidenceChartSamplePoint:
    source_index: int
    normalized_x: float
    normalized_y: float
    value: float


@dataclass(frozen=True, slots=True)
class EvidenceChartSample:
    key: EvidenceChartSampleKey
    points: tuple[EvidenceChartSamplePoint, ...]


@dataclass(frozen=True, slots=True)
class EvidenceChartPresentation:
    frame: EvidenceChartRenderFrame
    source_identity: str
    source_point_count: int
    sample: EvidenceChartSample | None
    overlay_identities: tuple[str, ...]
    breakpoint_identities: tuple[str, ...]
    selected_finding_identity: str
    selected_point_source_index: int | None
    selected_overlay_identity: str
    selected_breakpoint_identity: str
    narrative_text: str
    table_text: str
    accessible_text: str


@dataclass(frozen=True, slots=True)
class EvidenceChartRenderOverlay:
    identity: str
    axis: EvidenceChartOverlayAxis
    normalized_coordinate: float


@dataclass(frozen=True, slots=True)
class EvidenceChartRenderFrame:
    revision: int
    terminal: bool
    points: tuple[tuple[float, float], ...]
    overlays: tuple[EvidenceChartRenderOverlay, ...]
    selected_point_source_index: int | None = None
    selected_point: tuple[float, float] | None = None
    selected_overlay_identity: str = ""
    selected_finding_identity: str = ""
    selected_breakpoint_identity: str = ""

    @classmethod
    def from_sample(
        cls,
        source: DiagnosticEvidenceChart,
        sample: EvidenceChartSample,
        *,
        terminal: bool,
    ) -> "EvidenceChartRenderFrame":
        values = tuple(point.value for point in sample.points)
        minimum = min(values)
        maximum = max(values)
        value_span = max(maximum - minimum, 1e-12)
        first_index = sample.points[0].source_index
        last_index = sample.points[-1].source_index
        index_span = max(last_index - first_index, 1)
        overlays = tuple(
            EvidenceChartRenderOverlay(
                identity=overlay.identity,
                axis=overlay.axis,
                normalized_coordinate=(
                    (overlay.coordinate - minimum) / value_span
                    if overlay.axis is EvidenceChartOverlayAxis.HORIZONTAL
                    else (overlay.coordinate - first_index) / index_span
                ),
            )
            for overlay in source.overlays
        )
        return cls(
            revision=sample.key.revision,
            terminal=terminal,
            points=tuple(
                (point.normalized_x, point.normalized_y)
                for point in sample.points
            ),
            overlays=overlays,
        )


@dataclass(frozen=True, slots=True)
class EvidenceChartFrameGateResult:
    accepted: bool
    committed: tuple[EvidenceChartRenderFrame, ...]
    due_in_ns: int | None


class EvidenceChartFrameGate:
    """Monotonic 20 fps gate that preserves terminal frames."""

    def __init__(self, *, max_frames_per_second: int = 20) -> None:
        if max_frames_per_second < 1:
            raise ValueError("max_frames_per_second must be positive")
        self._minimum_interval_ns = 1_000_000_000 // max_frames_per_second
        self._last_commit_ns: int | None = None
        self._highest_revision = 0
        self._committed_revision = 0
        self._pending: EvidenceChartRenderFrame | None = None
        self._queued_after_terminal: EvidenceChartRenderFrame | None = None

    def offer(
        self,
        frame: EvidenceChartRenderFrame,
        *,
        now_ns: int,
    ) -> EvidenceChartFrameGateResult:
        committed = self._flush_due(now_ns)
        if frame.revision <= self._highest_revision:
            return EvidenceChartFrameGateResult(
                accepted=False,
                committed=committed,
                due_in_ns=self._due_in_ns(now_ns),
            )
        self._highest_revision = frame.revision
        if self._last_commit_ns is None and self._pending is None:
            committed += self._commit(frame, now_ns)
        elif (
            self._pending is None
            and self._last_commit_ns is not None
            and now_ns - self._last_commit_ns >= self._minimum_interval_ns
        ):
            committed += self._commit(frame, now_ns)
        elif self._pending is not None and self._pending.terminal:
            self._queued_after_terminal = frame
        elif frame.terminal:
            self._pending = frame
        else:
            self._pending = frame
        return EvidenceChartFrameGateResult(
            accepted=True,
            committed=committed,
            due_in_ns=self._due_in_ns(now_ns),
        )

    def flush(self, *, now_ns: int) -> EvidenceChartFrameGateResult:
        return EvidenceChartFrameGateResult(
            accepted=False,
            committed=self._flush_due(now_ns),
            due_in_ns=self._due_in_ns(now_ns),
        )

    def offer_local(
        self,
        frame: EvidenceChartRenderFrame,
        *,
        now_ns: int,
    ) -> EvidenceChartFrameGateResult:
        committed = self._flush_due(now_ns)
        if (
            self._highest_revision == 0
            or frame.revision != self._highest_revision
        ):
            return EvidenceChartFrameGateResult(
                accepted=False,
                committed=committed,
                due_in_ns=self._due_in_ns(now_ns),
            )
        local_frame = replace(frame, terminal=False)
        if self._last_commit_ns is None and self._pending is None:
            committed += self._commit(local_frame, now_ns)
        elif (
            self._pending is None
            and self._last_commit_ns is not None
            and now_ns - self._last_commit_ns >= self._minimum_interval_ns
        ):
            committed += self._commit(local_frame, now_ns)
        elif self._pending is not None and self._pending.terminal:
            self._queued_after_terminal = local_frame
        else:
            self._pending = local_frame
        return EvidenceChartFrameGateResult(
            accepted=True,
            committed=committed,
            due_in_ns=self._due_in_ns(now_ns),
        )

    @property
    def committedRevision(self) -> int:  # noqa: N802
        return self._committed_revision

    @property
    def pendingRevision(self) -> int:  # noqa: N802
        return 0 if self._pending is None else self._pending.revision

    @property
    def queuedAfterTerminalRevision(self) -> int:  # noqa: N802
        queued = self._queued_after_terminal
        return 0 if queued is None else queued.revision

    def _flush_due(
        self,
        now_ns: int,
    ) -> tuple[EvidenceChartRenderFrame, ...]:
        pending = self._pending
        if pending is None:
            return ()
        if (
            self._last_commit_ns is not None
            and now_ns - self._last_commit_ns < self._minimum_interval_ns
        ):
            return ()
        self._pending = self._queued_after_terminal
        self._queued_after_terminal = None
        return self._commit(pending, now_ns)

    def _commit(
        self,
        frame: EvidenceChartRenderFrame,
        now_ns: int,
    ) -> tuple[EvidenceChartRenderFrame, ...]:
        self._last_commit_ns = now_ns
        self._committed_revision = frame.revision
        return (frame,)

    def _due_in_ns(self, now_ns: int) -> int | None:
        if self._pending is None:
            return None
        if self._last_commit_ns is None:
            return 0
        return max(
            self._minimum_interval_ns - (now_ns - self._last_commit_ns),
            0,
        )


class DeterministicEvidenceChartSampler:
    """Projects immutable sources without changing or retaining their values."""

    def sample(
        self,
        source: DiagnosticEvidenceChart,
        *,
        source_identity: str,
        revision: int,
        viewport: EvidenceChartViewport,
        resolution: int,
        policy: EvidenceChartSamplingPolicy,
    ) -> EvidenceChartSample:
        key = EvidenceChartSampleKey(
            source_identity=source_identity,
            revision=revision,
            viewport=viewport,
            resolution=resolution,
            policy=policy,
        )
        if policy is not EvidenceChartSamplingPolicy.UNIFORM_ENDPOINTS_V1:
            raise ValueError(f"Unsupported evidence chart policy: {policy}")

        source_count = len(source.values)
        final_source_index = source_count - 1
        first = round(viewport.start * final_source_index)
        last = round(viewport.end * final_source_index)
        visible_count = last - first + 1
        sample_count = min(visible_count, resolution)
        if sample_count == visible_count:
            indices = tuple(range(first, last + 1))
        else:
            span = last - first
            indices = tuple(
                first + (span * offset) // (sample_count - 1)
                for offset in range(sample_count)
            )

        visible_values = tuple(source.values[index] for index in indices)
        minimum = min(visible_values)
        maximum = max(visible_values)
        value_span = maximum - minimum
        index_span = max(last - first, 1)
        points = tuple(
            EvidenceChartSamplePoint(
                source_index=index,
                normalized_x=(index - first) / index_span,
                normalized_y=(
                    0.5
                    if value_span == 0.0
                    else (source.values[index] - minimum) / value_span
                ),
                value=source.values[index],
            )
            for index in indices
        )
        return EvidenceChartSample(key=key, points=points)


def build_evidence_chart_presentation(
    state: EvidenceAndFindingsViewState,
    candidate: CandidateEvidence | None,
    *,
    selected_finding_identity: str,
    viewport: EvidenceChartViewport,
    resolution: int = 4_000,
    policy: EvidenceChartSamplingPolicy = (
        EvidenceChartSamplingPolicy.UNIFORM_ENDPOINTS_V1
    ),
    selected_point_source_index: int | None = None,
    selected_overlay_identity: str = "",
    selected_breakpoint_identity: str = "",
    evidence_filter: str = "all",
    sort_order: str = "dimension",
) -> EvidenceChartPresentation:
    terminal = (
        state.phase is ViewPhase.FAILED
        or state.presentation is EvidenceAndFindingsPresentationState.FAILED
        or (
            state.phase is ViewPhase.READY
            and state.completeness is Completeness.COMPLETE
        )
    )
    finding = (
        None
        if candidate is None
        else _selected_finding(candidate, selected_finding_identity)
    )
    breakpoints = (
        ()
        if candidate is None
        else tuple(
            breakpoint
            for candidate_finding in candidate.findings
            for breakpoint in candidate_finding.sensitivity_breakpoints
        )
    )
    breakpoint = next(
        (
            item
            for item in breakpoints
            if item.identity.value == selected_breakpoint_identity
        ),
        _finding_breakpoint(finding, breakpoints),
    )
    accepted_finding_identity = (
        "" if finding is None else finding.identity.value
    )
    accepted_breakpoint_identity = (
        "" if breakpoint is None else breakpoint.identity.value
    )
    source = None if candidate is None else candidate.chart
    if candidate is None or source is None:
        frame = EvidenceChartRenderFrame(
            revision=state.revision,
            terminal=terminal,
            points=(),
            overlays=(),
            selected_finding_identity=accepted_finding_identity,
            selected_breakpoint_identity=accepted_breakpoint_identity,
        )
        marker = f"Accepted evidence revision · r{state.revision}"
        unavailable = "No full-fidelity diagnostic chart source is available."
        candidate_line = (
            "Candidate · none"
            if candidate is None
            else f"Candidate · {candidate.identity.value} · {candidate.label}"
        )
        finding_lines = (
            ("Finding · none",)
            if finding is None
            else (
                f"Finding · {finding.identity.value} · {finding.title}",
                f"Disposition · {finding.disposition.value}",
                f"Comparison · {finding.comparison_summary}",
                f"Failure reason · {finding.failure_reason or 'none'}",
                (
                    "Evidence citations · "
                    f"{', '.join(item.value for item in finding.evidence_ids)}"
                ),
                (
                    "Comparison citations · "
                    f"{', '.join(item.value for item in finding.comparison_ids)}"
                ),
            )
        )
        breakpoint_line = (
            "Sensitivity Breakpoint · "
            f"{_breakpoint_text(breakpoint)}"
        )
        narrative_text = "\n".join(
            (
                marker,
                candidate_line,
                *finding_lines,
                breakpoint_line,
                unavailable,
            )
        )
        evidence_rows = (
            ()
            if candidate is None
            else _evidence_rows(
                candidate,
                evidence_filter=evidence_filter,
                sort_order=sort_order,
            )
        )
        table_text = "\n".join(
            (
                marker,
                candidate_line.replace(" · ", " | "),
                *(line.replace(" · ", " | ") for line in finding_lines),
                breakpoint_line.replace(" · ", " | "),
                f"Chart | unavailable | {unavailable}",
                *evidence_rows,
            )
        )
        return EvidenceChartPresentation(
            frame=frame,
            source_identity="unavailable",
            source_point_count=0,
            sample=None,
            overlay_identities=(),
            breakpoint_identities=tuple(
                item.identity.value for item in breakpoints
            ),
            selected_finding_identity=accepted_finding_identity,
            selected_point_source_index=None,
            selected_overlay_identity="",
            selected_breakpoint_identity=accepted_breakpoint_identity,
            narrative_text=narrative_text,
            table_text=table_text,
            accessible_text=narrative_text.replace("\n", ". "),
        )

    source_identity = _chart_source_identity(state, candidate, source)
    sample = DeterministicEvidenceChartSampler().sample(
        source,
        source_identity=source_identity,
        revision=state.revision,
        viewport=viewport,
        resolution=resolution,
        policy=policy,
    )
    overlay = next(
        (
            item
            for item in source.overlays
            if item.identity == selected_overlay_identity
        ),
        source.overlays[0],
    )
    sample_point = next(
        (
            item
            for item in sample.points
            if item.source_index == selected_point_source_index
        ),
        sample.points[-1],
    )
    marker = f"Accepted evidence revision · r{state.revision}"
    evidence_citations = (
        ", ".join(item.value for item in finding.evidence_ids)
        if finding is not None
        else "none"
    )
    comparison_citations = (
        ", ".join(item.value for item in finding.comparison_ids)
        if finding is not None
        else "none"
    )
    breakpoint_text = _breakpoint_text(breakpoint)
    finding_text = (
        (
            f"{finding.identity.value} · {finding.title}\n"
            f"Disposition · {finding.disposition.value}\n"
            f"Comparison · {finding.comparison_summary}\n"
            f"Failure reason · {finding.failure_reason or 'none'}"
        )
        if finding is not None
        else "No Diagnostic Finding is selected."
    )
    overlay_citations = ", ".join(
        item.value for item in overlay.evidence_ids
    )
    selection_lines = (
        (
            f"Selected point · #{sample_point.source_index} · "
            f"{sample_point.value:.4f} {source.unit}"
        ),
        (
            f"Selected overlay · {overlay.identity} · {overlay.label} · "
            f"{overlay.interpretation} · evidence {overlay_citations}"
        ),
        f"Selected Sensitivity Breakpoint · {breakpoint_text}",
    )
    narrative_text = "\n".join(
        (
            marker,
            f"Candidate · {candidate.identity.value} · {candidate.label}",
            finding_text,
            f"Evidence citations · {evidence_citations}",
            f"Comparison citations · {comparison_citations}",
            *selection_lines,
        )
    )
    evidence_rows = _evidence_rows(
        candidate,
        evidence_filter=evidence_filter,
        sort_order=sort_order,
    )
    table_text = "\n".join(
        (
            marker,
            (
                f"Point | #{sample_point.source_index} | "
                f"{sample_point.value:.4f} {source.unit}"
            ),
            (
                f"Overlay | {overlay.identity} | {overlay.label} | "
                f"{overlay.interpretation} | evidence {overlay_citations}"
            ),
            f"Breakpoint | {breakpoint_text}",
            (
                f"Finding | "
                f"{finding.identity.value if finding is not None else 'none'} "
                f"| disposition "
                f"{finding.disposition.value if finding is not None else 'none'} "
                f"| failure "
                f"{finding.failure_reason if finding is not None else 'none'} "
                f"| evidence {evidence_citations} "
                f"| comparisons {comparison_citations}"
            ),
            *evidence_rows,
        )
    )
    frame = replace(
        EvidenceChartRenderFrame.from_sample(
            source,
            sample,
            terminal=terminal,
        ),
        selected_point_source_index=sample_point.source_index,
        selected_point=(
            sample_point.normalized_x,
            sample_point.normalized_y,
        ),
        selected_overlay_identity=overlay.identity,
        selected_finding_identity=accepted_finding_identity,
        selected_breakpoint_identity=accepted_breakpoint_identity,
    )
    return EvidenceChartPresentation(
        frame=frame,
        source_identity=source_identity,
        source_point_count=len(source.values),
        sample=sample,
        overlay_identities=tuple(item.identity for item in source.overlays),
        breakpoint_identities=tuple(
            item.identity.value for item in breakpoints
        ),
        selected_finding_identity=accepted_finding_identity,
        selected_point_source_index=sample_point.source_index,
        selected_overlay_identity=overlay.identity,
        selected_breakpoint_identity=accepted_breakpoint_identity,
        narrative_text=narrative_text,
        table_text=table_text,
        accessible_text=(
            f"{marker}. {candidate.label}. "
            f"{len(sample.points)} visible of {len(source.values)} source "
            f"points. {finding_text.replace(chr(10), '. ')}. "
            f"{' '.join(selection_lines)}"
        ),
    )


def _selected_finding(
    candidate: CandidateEvidence,
    selected_identity: str,
) -> Finding | None:
    return next(
        (
            item
            for item in candidate.findings
            if item.identity.value == selected_identity
        ),
        candidate.findings[0] if candidate.findings else None,
    )


def _finding_breakpoint(
    finding: Finding | None,
    all_breakpoints: tuple[SensitivityBreakpoint, ...],
) -> SensitivityBreakpoint | None:
    if finding is not None and finding.sensitivity_breakpoints:
        return finding.sensitivity_breakpoints[0]
    return all_breakpoints[0] if all_breakpoints else None


def _evidence_rows(
    candidate: CandidateEvidence,
    *,
    evidence_filter: str,
    sort_order: str,
) -> tuple[str, ...]:
    records = candidate.evidence
    if evidence_filter != "all":
        records = tuple(
            item
            for item in records
            if evidence_filter
            in {item.dimension.value, item.coverage.value}
        )
    key = (
        (lambda item: (item.coverage.value, item.dimension.value))
        if sort_order == "coverage"
        else (lambda item: (item.dimension.value, item.coverage.value))
    )
    records = tuple(sorted(records, key=key))
    return tuple(
        (
            f"Evidence | {item.identity.value} | "
            f"{_enum_title(item.coverage)} | {_enum_title(item.dimension)} | "
            f"{item.label} | {item.value} {item.unit} | "
            f"{item.availability.value} | {item.interpretation}"
        )
        for item in records
    )


def _enum_title(value: EvidenceCoverage | EvidenceDimension) -> str:
    if value is EvidenceCoverage.QUICK_EXPERIMENT:
        return "Quick Experiment"
    return str(value.value).replace("_", " ").capitalize()


def _breakpoint_text(
    breakpoint: SensitivityBreakpoint | None,
) -> str:
    if breakpoint is None:
        return "none"
    return (
        f"{breakpoint.identity.value} · {breakpoint.assumption_name} "
        f"{breakpoint.threshold} · {breakpoint.outcome} · evidence "
        f"{', '.join(item.value for item in breakpoint.evidence_ids)}"
    )


def _chart_source_identity(
    state: EvidenceAndFindingsViewState,
    candidate: CandidateEvidence,
    source: DiagnosticEvidenceChart,
) -> str:
    selection = state.context.selection
    campaign_identity = (
        "no-campaign"
        if selection is None
        else selection.campaign_id.value
    )
    run_identity = (
        "no-run" if selection is None else selection.run_id.value
    )
    return "|".join(
        (
            f"source={state.source.identity}",
            f"generation={state.source.generation.value}",
            f"campaign={campaign_identity}",
            f"run={run_identity}",
            f"candidate={candidate.identity.value}",
            f"chart={source.identity}",
        )
    )


__all__ = [
    "DeterministicEvidenceChartSampler",
    "EvidenceChartFrameGate",
    "EvidenceChartFrameGateResult",
    "EvidenceChartPresentation",
    "EvidenceChartRenderFrame",
    "EvidenceChartRenderOverlay",
    "EvidenceChartSample",
    "EvidenceChartSampleKey",
    "EvidenceChartSamplePoint",
    "EvidenceChartSamplingPolicy",
    "EvidenceChartViewport",
    "build_evidence_chart_presentation",
]
