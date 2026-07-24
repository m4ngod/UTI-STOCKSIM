"""Technology-neutral read model for the issue #33 vertical slice.

THROWAWAY PROTOTYPE — this contract exists only to make the three view
implementations comparable. It is not the production Frontend V2 API.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Literal

import numpy as np

UiState = Literal[
    "loading",
    "empty",
    "stale",
    "disconnected",
    "partial",
    "failed",
    "completed",
]

UI_STATES: tuple[UiState, ...] = (
    "loading",
    "empty",
    "stale",
    "disconnected",
    "partial",
    "failed",
    "completed",
)


@dataclass(frozen=True, slots=True)
class CandidateRow:
    rank: int
    candidate_id: str
    model: str
    return_pct: float
    drawdown_pct: float
    evidence_status: str
    research_lock: str
    scenario_family: str


@dataclass(frozen=True, slots=True)
class SliceViewState:
    revision: int
    ui_state: UiState
    strategy: str
    scenario: str
    campaign_id: str
    run_id: str
    progress_pct: int
    completed_replicas: int
    total_replicas: int
    freshness: str
    selected_candidate: str
    candidates: tuple[CandidateRow, ...]
    anomaly_count: int
    finding_count: int
    headline: str
    detail: str
    last_reliable_at: str


@dataclass(frozen=True, slots=True)
class TimelineArtifact:
    x: np.ndarray
    candidate: np.ndarray
    baseline: np.ndarray
    stress: np.ndarray

    @property
    def point_count(self) -> int:
        return int(self.x.size)

    def display_points(self, maximum: int = 4_000) -> tuple[np.ndarray, ...]:
        """Return one shared deterministic sample for all three renderers."""
        stride = max(1, self.point_count // maximum)
        return (
            self.x[::stride],
            self.candidate[::stride],
            self.baseline[::stride],
            self.stress[::stride],
        )

    def semantic_rows(self, count: int = 12) -> list[dict[str, float]]:
        indexes = np.linspace(0, self.point_count - 1, count, dtype=int)
        return [
            {
                "step": int(self.x[index]),
                "candidate": round(float(self.candidate[index]), 3),
                "baseline": round(float(self.baseline[index]), 3),
                "stress": round(float(self.stress[index]), 3),
            }
            for index in indexes
        ]


def _status_for(index: int) -> tuple[str, str]:
    pattern = (
        ("fail", "locked"),
        ("missing", "locked"),
        ("pass", "reference"),
        ("warning", "locked"),
        ("pass", "eligible"),
    )
    return pattern[index % len(pattern)]


def build_candidates(count: int = 50) -> tuple[CandidateRow, ...]:
    rows: list[CandidateRow] = []
    for index in range(count):
        status, lock = _status_for(index)
        return_pct = 12.4 - index * 0.31 + ((index % 4) - 1.5) * 0.07
        drawdown = -(4.8 + (index % 11) * 0.71)
        rows.append(
            CandidateRow(
                rank=index + 1,
                candidate_id=f"MODEL-{chr(65 + index % 6)}{index + 1:02d}",
                model=("ppo_lstm_v1.gen4", "ppo_mlp_v3.gen2", "twap_baseline_v1")[
                    index % 3
                ],
                return_pct=round(return_pct, 2),
                drawdown_pct=round(drawdown, 2),
                evidence_status=status,
                research_lock=lock,
                scenario_family=("LQ stress", "fee sensitivity", "hidden world")[
                    index % 3
                ],
            )
        )
    return tuple(rows)


@lru_cache(maxsize=1)
def build_timeline(point_count: int = 100_000) -> TimelineArtifact:
    rng = np.random.default_rng(730_033)
    x = np.arange(point_count, dtype=np.float64)
    baseline_noise = rng.normal(0.0, 0.035, point_count).cumsum()
    baseline = 100.0 + baseline_noise + np.sin(x / 2_400.0) * 1.6
    candidate = baseline + np.sin(x / 1_350.0) * 1.25 + x / point_count * 2.2
    stress = candidate - np.maximum(0.0, x - point_count * 0.58) / point_count * 5.5
    return TimelineArtifact(x=x, candidate=candidate, baseline=baseline, stress=stress)


def build_state(ui_state: UiState = "completed", revision: int = 5_240) -> SliceViewState:
    candidates = build_candidates()
    progress = {
        "loading": 0,
        "empty": 0,
        "stale": 83,
        "disconnected": 83,
        "partial": 83,
        "failed": 71,
        "completed": 100,
    }[ui_state]
    completed = {
        "loading": 0,
        "empty": 0,
        "stale": 15,
        "disconnected": 15,
        "partial": 15,
        "failed": 13,
        "completed": 18,
    }[ui_state]
    headline, detail = {
        "loading": (
            "Materializing deterministic campaign",
            "No comparison is available until the first immutable ViewState arrives.",
        ),
        "empty": (
            "No candidates matched this diagnostic question",
            "Change the filter or return to the Scenario Lab; empty is not a runtime failure.",
        ),
        "stale": (
            "Last reliable evidence retained",
            "Updates are 42 s old. Values remain visible with their freshness boundary.",
        ),
        "disconnected": (
            "Runtime transport disconnected",
            "The last reliable state remains inspectable; reconnect does not erase context.",
        ),
        "partial": (
            "Three evidence debts keep interpretation locked",
            "Missing and not_available remain distinct and never count as pass.",
        ),
        "failed": (
            "Hidden-world evidence production stopped",
            "Completed artifacts are retained; this is not a negative strategy verdict.",
        ),
        "completed": (
            "Campaign complete · Research Acceptance Lock closed",
            "MODEL-A01 ranks first but hidden and fee sensitivity evidence block promotion.",
        ),
    }[ui_state]
    if ui_state in {"loading", "empty"}:
        candidates = ()
    freshness = {
        "stale": "stale · 42 s",
        "disconnected": "disconnected",
        "loading": "awaiting first state",
    }.get(ui_state, "fresh · < 100 ms")
    return SliceViewState(
        revision=revision,
        ui_state=ui_state,
        strategy="Breakout v4.2 · 7ec31a",
        scenario="2021 Q1 / Liquidity stress × 1.8",
        campaign_id="FDC-24-0719",
        run_id="DGN-24-0719-A",
        progress_pct=progress,
        completed_replicas=completed,
        total_replicas=18,
        freshness=freshness,
        selected_candidate=candidates[0].candidate_id if candidates else "",
        candidates=candidates,
        anomaly_count=2 if ui_state not in {"loading", "empty"} else 0,
        finding_count=3 if ui_state == "completed" else 0,
        headline=headline,
        detail=detail,
        last_reliable_at="Day 42 · 11:24:08",
    )


def advance_state(state: SliceViewState, event_id: int) -> SliceViewState:
    if not state.candidates:
        return replace(state, revision=state.revision + 1)
    rows = list(state.candidates)
    first = rows[0]
    drift = ((event_id % 9) - 4) * 0.004
    rows[0] = replace(first, return_pct=round(first.return_pct + drift, 3))
    return replace(state, revision=state.revision + 1, candidates=tuple(rows))


def state_to_dict(state: SliceViewState) -> dict[str, object]:
    return {
        "revision": state.revision,
        "uiState": state.ui_state,
        "strategy": state.strategy,
        "scenario": state.scenario,
        "campaignId": state.campaign_id,
        "runId": state.run_id,
        "progressPct": state.progress_pct,
        "replicas": f"{state.completed_replicas} / {state.total_replicas}",
        "freshness": state.freshness,
        "selectedCandidate": state.selected_candidate,
        "anomalyCount": state.anomaly_count,
        "findingCount": state.finding_count,
        "headline": state.headline,
        "detail": state.detail,
        "lastReliableAt": state.last_reliable_at,
        "candidates": [
            {
                "rank": row.rank,
                "candidateId": row.candidate_id,
                "model": row.model,
                "returnPct": row.return_pct,
                "drawdownPct": row.drawdown_pct,
                "evidenceStatus": row.evidence_status,
                "researchLock": row.research_lock,
                "scenarioFamily": row.scenario_family,
            }
            for row in state.candidates
        ],
    }
