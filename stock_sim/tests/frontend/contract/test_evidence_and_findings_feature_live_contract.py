from concurrent.futures import Future
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.app_context import build_app_context
from app.event_bridge import EventBridge
from app.features import (
    Completeness,
    DeterministicFakeEvidenceAndFindingsAdapter,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsFeature,
    EvidenceAndFindingsPresentationState,
    EvidenceAndFindingsSelection,
    EvidenceAvailability,
    EvidenceCoverage,
    EvidenceDimension,
    FormalDiagnosticCampaignId,
    Freshness,
    LiveEvidenceAndFindingsAdapter,
    MarketScenarioId,
    ReproductionManifestId,
    SourceGenerationId,
    SourceKind,
    StrategyRunId,
    StrategyUnderTestId,
    ViewPhase,
    ApprovedScenarioRecipeId,
)
from app.runtime_gateway import RuntimeGateway
from stock_sim.persistence.models_agent_binding import AgentBinding
from stock_sim.persistence.models_imports import Base
from stock_sim.persistence.models_simulation_run import SimulationRun
from stock_sim.services import runtime_query_service
from stock_sim.services.runtime_query_service import RuntimeQueryService


UTC = timezone.utc
NOW = datetime(2030, 1, 2, 12, 0, tzinfo=UTC)


class _DirectExecutor:
    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as error:
            future.set_exception(error)
        return future

    def shutdown(self, wait=True, *, cancel_futures=False):
        return None


def _selected_context() -> EvidenceAndFindingsContext:
    return EvidenceAndFindingsContext.for_selection(
        EvidenceAndFindingsSelection(
            campaign_id=FormalDiagnosticCampaignId("FDC-001"),
            run_id=StrategyRunId("RUN-001"),
            strategy_id=StrategyUnderTestId("STRATEGY-MOMENTUM-001"),
            market_scenario_id=MarketScenarioId("SCENARIO-BASELINE"),
            approved_recipe_id=ApprovedScenarioRecipeId("RECIPE-001"),
            reproduction_manifest_id=ReproductionManifestId("RM-001"),
        )
    )


def _live_record() -> dict:
    evidence = [
        {
            "id": "E-LIVE-RETURN-BASE",
            "coverage": "baseline",
            "dimension": "return",
            "label": "Excess return",
            "value": "8.2",
            "unit": "%",
            "availability": "complete",
            "interpretation": "The baseline return is positive.",
        },
        {
            "id": "E-LIVE-RISK-BASE",
            "coverage": "baseline",
            "dimension": "risk",
            "label": "Maximum drawdown",
            "value": "-8.1",
            "unit": "%",
            "availability": "complete",
            "interpretation": "Baseline drawdown remains bounded.",
        },
        {
            "id": "E-LIVE-EXEC-ISO",
            "coverage": "isolated_sensitivity",
            "dimension": "execution",
            "label": "Fee sensitivity",
            "value": "-1.4",
            "comparison_evidence_id": "E-LIVE-RETURN-BASE",
            "comparison_value": "8.2",
            "unit": "return delta points",
            "availability": "complete",
            "interpretation": "Fees remove most excess return.",
        },
        {
            "id": "E-LIVE-EXPOSURE-COMPOUND",
            "coverage": "compound_scenario",
            "dimension": "exposure",
            "label": "Concentration under compound stress",
            "value": "44",
            "comparison_evidence_id": "E-LIVE-RISK-BASE",
            "comparison_value": "-8.1",
            "unit": "%",
            "availability": "complete",
            "interpretation": "Compound stress increases concentration.",
        },
        {
            "id": "E-LIVE-STABILITY-COMPOUND",
            "coverage": "compound_scenario",
            "dimension": "stability",
            "label": "Stable windows",
            "value": "3/8",
            "comparison_evidence_id": "E-LIVE-RISK-BASE",
            "comparison_value": "-8.1",
            "unit": "windows",
            "availability": "complete",
            "interpretation": "Stability falls under stress.",
        },
        {
            "id": "E-LIVE-DOMAIN-COMPOUND",
            "coverage": "compound_scenario",
            "dimension": "domain",
            "label": "Limit-up entry availability",
            "value": "blocked",
            "comparison_evidence_id": "E-LIVE-RETURN-BASE",
            "comparison_value": "available",
            "unit": "market rule state",
            "availability": "complete",
            "interpretation": "Market rules block the assumed entry.",
        },
        {
            "id": "E-LIVE-QUICK",
            "coverage": "quick_experiment",
            "dimension": "execution",
            "label": "Quick fee probe",
            "value": "-0.9",
            "comparison_evidence_id": "E-LIVE-RETURN-BASE",
            "comparison_value": "8.2",
            "unit": "return delta points",
            "availability": "complete",
            "interpretation": "Exploratory evidence only.",
            "counts_toward_formal_completeness": False,
        },
    ]
    return {
        "run_id": "RUN-001",
        "revision": 7,
        "updated_at": NOW.isoformat(),
        "status": "completed",
        "selection": {
            "campaign_id": "FDC-001",
            "run_id": "RUN-001",
            "strategy_id": "STRATEGY-MOMENTUM-001",
            "market_scenario_id": "SCENARIO-BASELINE",
            "approved_recipe_id": "RECIPE-001",
            "reproduction_manifest_id": "RM-001",
        },
        "candidates": [
            {
                "candidate_id": "MODEL-LIVE-B17",
                "label": "Live candidate B17",
                "evidence": evidence,
                "comparisons": [
                    {
                        "id": "CMP-LIVE-FEE",
                        "label": "Baseline versus isolated fee sensitivity",
                        "reference_evidence_id": "E-LIVE-RETURN-BASE",
                        "observed_evidence_id": "E-LIVE-EXEC-ISO",
                        "interpretation": "Fee sensitivity removes return.",
                    },
                    {
                        "id": "CMP-LIVE-EXPOSURE",
                        "label": "Baseline versus compound exposure",
                        "reference_evidence_id": "E-LIVE-RISK-BASE",
                        "observed_evidence_id": "E-LIVE-EXPOSURE-COMPOUND",
                        "interpretation": "Compound exposure increases.",
                    },
                    {
                        "id": "CMP-LIVE-STABILITY",
                        "label": "Baseline versus compound stability",
                        "reference_evidence_id": "E-LIVE-RISK-BASE",
                        "observed_evidence_id": "E-LIVE-STABILITY-COMPOUND",
                        "interpretation": "Stable windows decline.",
                    },
                    {
                        "id": "CMP-LIVE-DOMAIN",
                        "label": "Baseline versus compound domain outcome",
                        "reference_evidence_id": "E-LIVE-RETURN-BASE",
                        "observed_evidence_id": "E-LIVE-DOMAIN-COMPOUND",
                        "interpretation": "Market-rule outcomes differ.",
                    },
                    {
                        "id": "CMP-LIVE-QUICK",
                        "label": "Baseline versus Quick Experiment",
                        "reference_evidence_id": "E-LIVE-RETURN-BASE",
                        "observed_evidence_id": "E-LIVE-QUICK",
                        "interpretation": "Quick evidence is exploratory.",
                    },
                ],
                "findings": [
                    {
                        "id": "F-LIVE-01",
                        "title": "Fees break the baseline result",
                        "disposition": "failed",
                        "comparison_summary": (
                            "Isolated fees remove the baseline excess return."
                        ),
                        "failure_reason": "Turnover amplifies effective fees.",
                        "evidence_ids": [
                            "E-LIVE-RETURN-BASE",
                            "E-LIVE-EXEC-ISO",
                        ],
                        "comparison_ids": ["CMP-LIVE-FEE"],
                        "sensitivity_breakpoints": [
                            {
                                "id": "BP-LIVE-FEE",
                                "assumption_name": "fee_multiplier",
                                "threshold": "1.6x",
                                "outcome": "Excess return becomes non-positive.",
                                "evidence_ids": [
                                    "E-LIVE-RETURN-BASE",
                                    "E-LIVE-EXEC-ISO",
                                ],
                            }
                        ],
                    }
                ],
                "execution_assumptions": [
                    {
                        "name": "fee_multiplier",
                        "requested_value": "1.0x",
                        "effective_value": "1.6x",
                        "override_reason": "Approved Scenario Recipe override",
                    }
                ],
                "provenance": {
                    "artifact_hashes": [
                        "sha256:live-metrics",
                        "sha256:live-traces",
                    ],
                    "source_run_ids": ["RUN-001"],
                    "runner_version": "evidence-runner/3.0",
                    "build_version": "uti-stocksim/live-41",
                    "dependencies": [
                        {
                            "name": "reproduction-manifest",
                            "version": "RM-001",
                            "artifact_hash": "sha256:manifest-live",
                        }
                    ],
                },
            }
        ],
        "read_only_context": {
            "market": ["600519.SH · closed session"],
            "account": ["MODEL-LIVE-B17 · research account"],
            "positions": ["600519.SH · +100 · evidence snapshot"],
            "orders": [
                {
                    "id": "ORD-LIVE-001",
                    "instrument": "600519.SH",
                    "status": "filled",
                    "diagnostic_note": "Read-only execution trace.",
                }
            ],
            "fills": [
                {
                    "id": "FILL-LIVE-001",
                    "order_id": "ORD-LIVE-001",
                    "instrument": "600519.SH",
                    "quantity": 100,
                    "price": "1500.00",
                }
            ],
        },
        "ai_explanation": "MUST NEVER BECOME SOURCE EVIDENCE",
    }


class _EvidenceQueries:
    def __init__(self) -> None:
        self.record = _live_record()
        self.error: Exception | None = None
        self.on_read = None

    def get_evidence_and_findings_snapshot(self, run_id):
        if self.error is not None:
            raise self.error
        if run_id != self.record["run_id"]:
            return None
        on_read = self.on_read
        self.on_read = None
        if on_read is not None:
            on_read()
        return json.loads(json.dumps(self.record))


def _live_adapter():
    queries = _EvidenceQueries()
    gateway = RuntimeGateway()
    gateway._queries = queries
    bridge = EventBridge(subscribe_backend=False)
    adapter = LiveEvidenceAndFindingsAdapter(
        runtime_gateway=gateway,
        event_bridge=bridge,
        clock=lambda: NOW,
        executor=_DirectExecutor(),
    )
    return adapter, bridge, queries


class _EvidenceContractDriver:
    """Adapter-specific controls behind one shared Feature contract suite."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.context = _selected_context()
        self.current_time = [NOW]
        self.bridge = None
        self.queries = None
        if mode == "fake":
            self.adapter = DeterministicFakeEvidenceAndFindingsAdapter(
                clock=lambda: self.current_time[0],
                freshness_threshold=timedelta(seconds=5),
            )
            return
        self.queries = _EvidenceQueries()
        self.queries.record = {
            "run_id": "RUN-001",
            "revision": 1,
            "updated_at": NOW.isoformat(),
            "status": "loading",
        }
        gateway = RuntimeGateway()
        gateway._queries = self.queries
        self.bridge = EventBridge(subscribe_backend=False)
        self.adapter = LiveEvidenceAndFindingsAdapter(
            runtime_gateway=gateway,
            event_bridge=self.bridge,
            clock=lambda: self.current_time[0],
            freshness_threshold=timedelta(seconds=5),
            executor=_DirectExecutor(),
        )

    def close(self):
        self.adapter.close()

    def attempt_update_after_close(self):
        try:
            self.completed()
        except RuntimeError:
            pass

    def completed(self):
        if self.mode == "fake":
            return self.adapter.advance_to_completed(self.context)
        assert self.queries is not None
        assert self.bridge is not None
        self.queries.record = _live_record()
        self.bridge.on_snapshot({"run_id": "RUN-001"})
        self.bridge.flush(force=True)
        return self.adapter.snapshot(self.context)

    def partial(self):
        if self.adapter.snapshot(self.context).last_reliable_data is None:
            self.completed()
        if self.mode == "fake":
            return self.adapter.advance_to_partial(self.context)
        assert self.queries is not None
        assert self.bridge is not None
        self.queries.record["revision"] = 8
        self.queries.record["status"] = "partial"
        self.queries.record["candidates"][0]["evidence"][0][
            "availability"
        ] = "partial"
        self.bridge.on_snapshot({"run_id": "RUN-001"})
        self.bridge.flush(force=True)
        return self.adapter.snapshot(self.context)

    def failed(self):
        self.completed()
        if self.mode == "fake":
            return self.adapter.advance_to_failed(self.context)
        assert self.queries is not None
        assert self.bridge is not None
        self.queries.record["revision"] = 8
        self.queries.record["status"] = "failed"
        self.bridge.on_snapshot({"run_id": "RUN-001"})
        self.bridge.flush(force=True)
        return self.adapter.snapshot(self.context)

    def stale(self):
        self.completed()
        if self.mode == "fake":
            return self.adapter.advance_to_stale(self.context)
        self.current_time[0] = NOW + timedelta(seconds=6)
        return self.adapter.snapshot(self.context)

    def disconnected(self):
        completed = self.completed()
        if self.mode == "fake":
            state = self.adapter.advance_to_disconnected(self.context)
        else:
            assert self.bridge is not None
            self.bridge.mark_disconnected()
            state = self.adapter.snapshot(self.context)
        return completed, state

    def retention_sequence(self):
        completed = self.completed()
        if self.mode == "fake":
            stale = self.adapter.advance_to_stale(self.context)
            disconnected = self.adapter.advance_to_disconnected(self.context)
        else:
            self.current_time[0] = NOW + timedelta(seconds=6)
            stale = self.adapter.snapshot(self.context)
            assert self.bridge is not None
            self.bridge.mark_disconnected()
            disconnected = self.adapter.snapshot(self.context)
        return completed, stale, disconnected

    def empty(self):
        context = EvidenceAndFindingsContext.no_selection()
        if self.mode == "fake":
            return self.adapter.advance_to_empty(context)
        return self.adapter.snapshot(context)

    def no_prior_failed(self):
        if self.mode == "fake":
            return self.adapter.advance_to_disconnected(self.context)
        assert self.queries is not None
        self.queries.error = RuntimeError("source unavailable")
        return self.adapter.snapshot(self.context)

    def rejection_and_recovery_sequence(self):
        accepted = self.completed()
        if self.mode == "fake":
            lower = replace(accepted, revision=accepted.revision - 1)
            after_lower = self.adapter.replay_scripted_state(
                self.context,
                lower,
            )
            disconnected = self.adapter.advance_to_disconnected(self.context)
            recovered = replace(
                accepted,
                revision=disconnected.revision + 1,
                observed_at=self.current_time[0] + timedelta(seconds=1),
                source=replace(
                    accepted.source,
                    generation=SourceGenerationId(
                        accepted.source.generation.value + 1
                    ),
                ),
            )
            recovered = self.adapter.replay_scripted_state(
                self.context,
                recovered,
            )
            old_generation = replace(
                recovered,
                revision=recovered.revision + 1,
                source=accepted.source,
            )
            after_old_generation = self.adapter.replay_scripted_state(
                self.context,
                old_generation,
            )
            return (
                accepted,
                after_lower,
                disconnected,
                recovered,
                after_old_generation,
            )

        assert self.queries is not None
        assert self.bridge is not None
        self.queries.record["revision"] = 6
        self.bridge.on_snapshot({"run_id": "RUN-001"})
        self.bridge.flush(force=True)
        after_lower = self.adapter.snapshot(self.context)
        self.bridge.mark_disconnected()
        disconnected = self.adapter.snapshot(self.context)
        reconnected = self.bridge.mark_reconnected()
        self.queries.record = _live_record()
        self.bridge.on_snapshot(
            {"run_id": "RUN-001"},
            generation=reconnected.generation,
        )
        self.bridge.flush(force=True)
        recovered = self.adapter.snapshot(self.context)
        self.queries.record["revision"] = 8
        self.queries.record["candidates"][0]["evidence"][0]["value"] = "999"
        self.bridge.on_snapshot(
            {"run_id": "RUN-001"},
            generation=reconnected.generation.value - 1,
        )
        self.bridge.flush(force=True)
        after_old_generation = self.adapter.snapshot(self.context)
        return (
            accepted,
            after_lower,
            disconnected,
            recovered,
            after_old_generation,
        )


@pytest.fixture(params=("fake", "live"))
def evidence_and_findings_adapter(request):
    context = _selected_context()
    if request.param == "fake":
        adapter = DeterministicFakeEvidenceAndFindingsAdapter(
            clock=lambda: NOW,
        )
        adapter.advance_to_completed(context)
        yield adapter, context
        adapter.close()
        return

    adapter, _bridge, _queries = _live_adapter()
    yield adapter, context
    adapter.close()


@pytest.fixture(params=("fake", "live"))
def evidence_contract_driver(request):
    driver = _EvidenceContractDriver(request.param)
    yield driver
    driver.close()


def _walk_values(value):
    yield value
    if isinstance(value, tuple):
        for item in value:
            yield from _walk_values(item)
    elif is_dataclass(value):
        for field in fields(value):
            yield from _walk_values(getattr(value, field.name))


def test_live_and_fake_adapters_share_the_read_only_feature_contract(
    evidence_and_findings_adapter,
):
    adapter, context = evidence_and_findings_adapter
    delivered = []

    subscription = adapter.subscribe(context, delivered.append)
    state = adapter.snapshot(context)

    assert isinstance(adapter, EvidenceAndFindingsFeature)
    assert delivered == [state]
    assert state.source.kind in {
        SourceKind.DETERMINISTIC_FAKE,
        SourceKind.LIVE_RUNTIME,
    }
    assert state.phase is ViewPhase.READY
    assert state.presentation is EvidenceAndFindingsPresentationState.READY
    assert state.freshness is Freshness.FRESH
    assert state.completeness is Completeness.COMPLETE
    assert state.last_reliable_data is not None
    data = state.last_reliable_data
    assert data.selection == context.selection
    assert data.candidates
    evidence = tuple(
        item
        for candidate in data.candidates
        for item in candidate.evidence
    )
    assert {item.coverage for item in evidence} == {
        EvidenceCoverage.BASELINE,
        EvidenceCoverage.ISOLATED_SENSITIVITY,
        EvidenceCoverage.COMPOUND_SCENARIO,
        EvidenceCoverage.QUICK_EXPERIMENT,
    }
    assert {item.dimension for item in evidence} == {
        EvidenceDimension.RETURN,
        EvidenceDimension.RISK,
        EvidenceDimension.EXECUTION,
        EvidenceDimension.EXPOSURE,
        EvidenceDimension.STABILITY,
        EvidenceDimension.DOMAIN,
    }
    assert all(
        item.counts_toward_formal_completeness is False
        for item in evidence
        if item.coverage is EvidenceCoverage.QUICK_EXPERIMENT
    )
    assert all(
        candidate.findings
        and candidate.comparisons
        and candidate.execution_assumptions
        and candidate.provenance.artifact_hashes
        and candidate.provenance.source_run_ids
        and candidate.provenance.dependencies
        for candidate in data.candidates
    )
    assert data.read_only_context.orders
    assert data.read_only_context.fills
    values = tuple(_walk_values(state))
    assert not any(
        isinstance(value, (dict, list, set, bytearray))
        for value in values
    )
    assert not any(
        type(value).__module__.startswith("PySide6")
        or type(value).__name__
        in {
            "RuntimeGateway",
            "EventBridge",
            "SimulationRun",
        }
        for value in values
    )
    assert "MUST NEVER BECOME SOURCE EVIDENCE" not in repr(state)

    subscription.dispose()
    subscription.dispose()
    assert subscription.disposed is True


@pytest.mark.parametrize(
    ("scenario", "phase", "presentation", "completeness", "has_data"),
    (
        (
            "completed",
            ViewPhase.READY,
            EvidenceAndFindingsPresentationState.READY,
            Completeness.COMPLETE,
            True,
        ),
        (
            "partial",
            ViewPhase.DEGRADED,
            EvidenceAndFindingsPresentationState.READY,
            Completeness.PARTIAL,
            True,
        ),
        (
            "failed",
            ViewPhase.FAILED,
            EvidenceAndFindingsPresentationState.FAILED,
            Completeness.PARTIAL,
            True,
        ),
        (
            "empty",
            ViewPhase.READY,
            EvidenceAndFindingsPresentationState.EMPTY,
            Completeness.EMPTY,
            False,
        ),
        (
            "no_prior_failed",
            ViewPhase.FAILED,
            EvidenceAndFindingsPresentationState.DISCONNECTED,
            Completeness.UNKNOWN,
            False,
        ),
    ),
)
def test_live_and_fake_adapters_share_the_honest_state_matrix_contract(
    evidence_contract_driver,
    scenario,
    phase,
    presentation,
    completeness,
    has_data,
):
    state = getattr(evidence_contract_driver, scenario)()

    assert state.phase is phase
    assert state.presentation is presentation
    assert state.completeness is completeness
    assert (state.last_reliable_data is not None) is has_data
    assert (state.error is not None) is (
        phase in {ViewPhase.DEGRADED, ViewPhase.FAILED}
    )


def test_live_and_fake_adapters_share_stale_and_disconnected_retention_contract(
    evidence_contract_driver,
):
    completed, stale, disconnected = (
        evidence_contract_driver.retention_sequence()
    )

    assert stale.freshness is Freshness.STALE
    assert stale.phase is ViewPhase.DEGRADED
    assert stale.last_reliable_data == completed.last_reliable_data
    assert disconnected.freshness is Freshness.DISCONNECTED
    assert disconnected.phase is ViewPhase.DEGRADED
    assert disconnected.last_reliable_data == completed.last_reliable_data


def test_live_and_fake_adapters_share_revision_generation_recovery_contract(
    evidence_contract_driver,
):
    (
        accepted,
        after_lower,
        disconnected,
        recovered,
        after_old_generation,
    ) = evidence_contract_driver.rejection_and_recovery_sequence()

    assert after_lower == accepted
    assert disconnected.last_reliable_data == accepted.last_reliable_data
    assert recovered.revision > disconnected.revision
    assert (
        recovered.source.generation.value
        > accepted.source.generation.value
    )
    assert recovered.freshness is Freshness.FRESH
    assert recovered.phase is ViewPhase.READY
    assert recovered.last_reliable_data is not None
    assert after_old_generation == recovered


def test_live_and_fake_adapters_share_dispose_and_close_lifecycle_contract(
    evidence_contract_driver,
):
    disposed_deliveries = []
    disposed_subscription = evidence_contract_driver.adapter.subscribe(
        evidence_contract_driver.context,
        disposed_deliveries.append,
    )
    disposed_subscription.dispose()
    disposed_subscription.dispose()
    evidence_contract_driver.completed()
    assert len(disposed_deliveries) == 1
    assert disposed_subscription.disposed is True

    close_deliveries = []
    evidence_contract_driver.adapter.subscribe(
        evidence_contract_driver.context,
        close_deliveries.append,
    )
    visible_before_close = tuple(close_deliveries)
    evidence_contract_driver.close()
    evidence_contract_driver.close()
    evidence_contract_driver.attempt_update_after_close()
    assert tuple(close_deliveries) == visible_before_close


def test_live_and_fake_adapters_isolate_a_failing_observer_from_future_updates(
    evidence_contract_driver,
):
    def failing_observer(state):
        if state.revision > 1:
            raise RuntimeError("observer failure")

    healthy_deliveries = []
    evidence_contract_driver.adapter.subscribe(
        evidence_contract_driver.context,
        failing_observer,
    )
    evidence_contract_driver.adapter.subscribe(
        evidence_contract_driver.context,
        healthy_deliveries.append,
    )

    completed = evidence_contract_driver.completed()
    partial = evidence_contract_driver.partial()

    assert healthy_deliveries[-2:] == [completed, partial]
    assert partial.revision > completed.revision


def test_live_adapter_retains_evidence_and_rejects_old_generations_and_revisions():
    adapter, bridge, queries = _live_adapter()
    context = _selected_context()
    completed = adapter.snapshot(context)
    completed_data = completed.last_reliable_data
    assert completed_data is not None

    queries.record["revision"] = 8
    queries.record["status"] = "partial"
    queries.record["candidates"][0]["evidence"][3][
        "availability"
    ] = "missing"
    bridge.on_snapshot({"run_id": "RUN-001"})
    bridge.flush(force=True)
    partial = adapter.snapshot(context)
    assert partial.revision == completed.revision + 1
    assert partial.phase is ViewPhase.DEGRADED
    assert partial.completeness is Completeness.PARTIAL
    assert partial.last_reliable_data is not None
    assert any(
        item.availability is EvidenceAvailability.MISSING
        for item in partial.last_reliable_data.candidates[0].evidence
    )

    queries.record["revision"] = 7
    queries.record["candidates"][0]["evidence"][0]["value"] = "999"
    bridge.on_snapshot({"run_id": "RUN-001"})
    bridge.flush(force=True)
    assert adapter.snapshot(context) == partial

    bridge.mark_disconnected()
    disconnected = adapter.snapshot(context)
    assert disconnected.freshness is Freshness.DISCONNECTED
    assert disconnected.phase is ViewPhase.DEGRADED
    assert disconnected.last_reliable_data == partial.last_reliable_data

    reconnected = bridge.mark_reconnected()
    awaiting_current = adapter.snapshot(context)
    assert awaiting_current.freshness is Freshness.STALE
    assert awaiting_current.last_reliable_data == partial.last_reliable_data

    queries.record = _live_record()
    queries.record["revision"] = 8
    queries.record["updated_at"] = (NOW + timedelta(seconds=1)).isoformat()
    bridge.on_snapshot(
        {"run_id": "RUN-001"},
        generation=reconnected.generation.value - 1,
    )
    bridge.flush(force=True)
    assert adapter.snapshot(context) == awaiting_current

    bridge.on_snapshot(
        {"run_id": "RUN-001"},
        generation=reconnected.generation,
    )
    bridge.flush(force=True)
    recovered = adapter.snapshot(context)
    assert recovered.revision == awaiting_current.revision + 1
    assert recovered.freshness is Freshness.FRESH
    assert recovered.phase is ViewPhase.READY
    assert recovered.source.generation.value == 2
    assert recovered.last_reliable_data is not None
    assert recovered.last_reliable_data != partial.last_reliable_data

    queries.error = RuntimeError("SECRET-LIVE-EVIDENCE-FAILURE")
    bridge.on_snapshot(
        {"run_id": "RUN-001"},
        generation=reconnected.generation,
    )
    bridge.flush(force=True)
    degraded = adapter.snapshot(context)
    assert degraded.phase is ViewPhase.DEGRADED
    assert degraded.freshness is Freshness.STALE
    assert degraded.last_reliable_data == recovered.last_reliable_data
    assert degraded.error is not None
    assert degraded.error.code == "evidence_and_findings_query_failed"
    assert "SECRET" not in degraded.error.message
    adapter.close()


def test_live_adapter_retries_an_authoritative_refresh_after_local_revision_contention():
    current_time = [NOW]
    queries = _EvidenceQueries()
    gateway = RuntimeGateway()
    gateway._queries = queries
    bridge = EventBridge(subscribe_backend=False)
    adapter = LiveEvidenceAndFindingsAdapter(
        runtime_gateway=gateway,
        event_bridge=bridge,
        clock=lambda: current_time[0],
        freshness_threshold=timedelta(seconds=1),
        executor=_DirectExecutor(),
    )
    context = _selected_context()
    initial = adapter.snapshot(context)
    assert initial.revision == 1

    current_time[0] = NOW + timedelta(seconds=10)
    queries.record["revision"] = 8
    queries.record["updated_at"] = current_time[0].isoformat()
    queries.record["candidates"][0]["evidence"][0]["value"] = "9.4"

    def age_local_state_during_the_runtime_read():
        aged = adapter.snapshot(context)
        assert aged.revision == initial.revision + 1
        assert aged.freshness is Freshness.STALE

    queries.on_read = age_local_state_during_the_runtime_read
    bridge.on_snapshot({"run_id": "RUN-001"})
    bridge.flush(force=True)

    recovered = adapter.snapshot(context)
    assert recovered.revision == initial.revision + 2
    assert recovered.freshness is Freshness.FRESH
    assert recovered.last_reliable_data is not None
    assert recovered.last_reliable_data.candidates[0].evidence[0].value == "9.4"
    adapter.close()


def test_live_adapter_does_not_let_an_unversioned_payload_rewind_reliable_evidence():
    adapter, bridge, queries = _live_adapter()
    context = _selected_context()
    accepted = adapter.snapshot(context)

    queries.record.pop("revision")
    queries.record["candidates"][0]["evidence"][0]["value"] = "999"
    bridge.on_snapshot({"run_id": "RUN-001"})
    bridge.flush(force=True)

    assert adapter.snapshot(context) == accepted
    adapter.close()


def test_live_adapter_orders_hash_versioned_aggregate_updates_by_created_at():
    adapter, bridge, queries = _live_adapter()
    context = _selected_context()
    queries.record.pop("revision")
    queries.record["record_kind"] = "series_evidence_aggregate_v1"
    queries.record["aggregate_hash"] = "a" * 64
    queries.record["created_at"] = NOW.isoformat()
    queries.record["_source_version_order"] = 100
    accepted = adapter.snapshot(context)

    queries.record["aggregate_hash"] = "b" * 64
    queries.record["created_at"] = NOW.isoformat()
    queries.record["_source_version_order"] = 101
    queries.record["candidates"][0]["evidence"][0]["value"] = "9.4"
    bridge.on_snapshot({"run_id": "RUN-001"})
    bridge.flush(force=True)
    updated = adapter.snapshot(context)
    assert updated.revision == accepted.revision + 1
    assert updated.last_reliable_data is not None
    assert updated.last_reliable_data.candidates[0].evidence[0].value == "9.4"

    queries.record["aggregate_hash"] = "old".ljust(64, "0")
    queries.record["created_at"] = NOW.isoformat()
    queries.record["_source_version_order"] = 99
    queries.record["candidates"][0]["evidence"][0]["value"] = "999"
    bridge.on_snapshot({"run_id": "RUN-001"})
    bridge.flush(force=True)
    assert adapter.snapshot(context) == updated
    adapter.close()


def test_initial_read_retries_when_connection_generation_changes_in_flight():
    bridge = EventBridge(subscribe_backend=False)

    class _GenerationRacingQueries:
        def __init__(self):
            self.calls = 0
            self.old_record = _live_record()
            self.old_record["revision"] = 9
            self.old_record["candidates"][0]["evidence"][0]["value"] = "old"
            self.current_record = _live_record()
            self.current_record["revision"] = 1
            self.current_record["candidates"][0]["evidence"][0][
                "value"
            ] = "current"

        def get_evidence_and_findings_snapshot(self, run_id):
            assert run_id == "RUN-001"
            self.calls += 1
            if self.calls == 1:
                result = json.loads(json.dumps(self.old_record))
                bridge.mark_disconnected()
                bridge.mark_reconnected()
                return result
            return json.loads(json.dumps(self.current_record))

    queries = _GenerationRacingQueries()
    gateway = RuntimeGateway()
    gateway._queries = queries
    adapter = LiveEvidenceAndFindingsAdapter(
        runtime_gateway=gateway,
        event_bridge=bridge,
        clock=lambda: NOW,
        executor=_DirectExecutor(),
    )

    state = adapter.snapshot(_selected_context())

    assert queries.calls == 2
    assert state.source.generation.value == 2
    assert state.freshness is Freshness.FRESH
    assert state.phase is ViewPhase.READY
    assert state.last_reliable_data is not None
    assert state.last_reliable_data.candidates[0].evidence[0].value == "current"
    adapter.close()


def test_live_adapter_recovers_from_a_transient_query_failure_at_the_same_revision():
    adapter, bridge, queries = _live_adapter()
    context = _selected_context()
    accepted = adapter.snapshot(context)

    queries.error = RuntimeError("transient source failure")
    bridge.on_snapshot({"run_id": "RUN-001"})
    bridge.flush(force=True)
    degraded = adapter.snapshot(context)
    assert degraded.revision == accepted.revision + 1
    assert degraded.phase is ViewPhase.DEGRADED
    assert degraded.freshness is Freshness.STALE
    assert degraded.last_reliable_data == accepted.last_reliable_data

    queries.error = None
    bridge.on_snapshot({"run_id": "RUN-001"})
    bridge.flush(force=True)
    recovered = adapter.snapshot(context)

    assert recovered.revision == degraded.revision + 1
    assert recovered.phase is ViewPhase.READY
    assert recovered.freshness is Freshness.FRESH
    assert recovered.last_reliable_data == accepted.last_reliable_data
    adapter.close()


@pytest.mark.parametrize("status", ("partial", "failed"))
def test_live_adapter_rejects_equal_revision_status_reinterpretation(status):
    adapter, bridge, queries = _live_adapter()
    context = _selected_context()
    accepted = adapter.snapshot(context)

    queries.error = RuntimeError("transient source failure")
    bridge.on_snapshot({"run_id": "RUN-001"})
    bridge.flush(force=True)
    degraded = adapter.snapshot(context)
    assert degraded.last_reliable_data == accepted.last_reliable_data

    queries.error = None
    queries.record["status"] = status
    bridge.on_snapshot({"run_id": "RUN-001"})
    bridge.flush(force=True)

    assert adapter.snapshot(context) == degraded
    adapter.close()


@pytest.mark.parametrize(
    "mutation",
    (
        lambda record: record["candidates"][0]["evidence"][2].update(
            coverage="baseline"
        ),
        lambda record: record["candidates"][0].update(
            execution_assumptions=[]
        ),
        lambda record: record["candidates"][0].update(provenance={}),
        lambda record: record["candidates"][0]["provenance"].update(
            artifact_hashes=[]
        ),
        lambda record: record["candidates"][0]["provenance"].update(
            dependencies=[]
        ),
        lambda record: record["candidates"][0]["findings"][0].update(
            evidence_ids=[]
        ),
        lambda record: record["candidates"][0]["findings"][0].update(
            comparison_ids=[]
        ),
        lambda record: record["candidates"][0]["findings"][0].update(
            sensitivity_breakpoints=[]
        ),
        lambda record: record["candidates"][0]["findings"][0].update(
            failure_reason=None
        ),
    ),
    ids=(
        "missing-formal-coverage",
        "missing-assumptions",
        "missing-provenance",
        "missing-artifacts",
        "missing-manifest-dependency",
        "missing-finding-evidence-citation",
        "missing-finding-comparison-citation",
        "missing-sensitivity-breakpoint",
        "missing-failure-reason",
    ),
)
def test_live_adapter_never_reports_incomplete_formal_campaigns_as_complete(
    mutation,
):
    adapter, _bridge, queries = _live_adapter()
    mutation(queries.record)

    state = adapter.snapshot(_selected_context())

    assert state.completeness is Completeness.PARTIAL
    assert state.phase is ViewPhase.DEGRADED
    assert state.error is not None
    assert state.error.code == "evidence_and_findings_partial"
    adapter.close()


@pytest.mark.parametrize(
    "mutation",
    (
        lambda record: record["candidates"][0]["comparisons"][0].update(
            observed_evidence_id="E-DANGLING"
        ),
        lambda record: record["candidates"][0]["findings"][0].update(
            evidence_ids=["E-DANGLING"]
        ),
        lambda record: record["candidates"][0]["findings"][0].update(
            comparison_ids=["CMP-DANGLING"]
        ),
        lambda record: record["candidates"][0]["findings"][0][
            "sensitivity_breakpoints"
        ][0].update(evidence_ids=["E-DANGLING"]),
    ),
    ids=(
        "comparison-to-evidence",
        "finding-to-evidence",
        "finding-to-comparison",
        "breakpoint-to-evidence",
    ),
)
def test_live_adapter_rejects_dangling_typed_evidence_references(mutation):
    adapter, _bridge, queries = _live_adapter()
    mutation(queries.record)

    state = adapter.snapshot(_selected_context())

    assert state.phase is ViewPhase.FAILED
    assert state.presentation is EvidenceAndFindingsPresentationState.FAILED
    assert state.last_reliable_data is None
    assert state.error is not None
    assert state.error.code == "evidence_and_findings_mapping_failed"
    adapter.close()


def test_live_adapter_validates_nested_identity_and_boolean_semantics():
    adapter, _bridge, queries = _live_adapter()
    nested = _live_record()
    nested["candidates"][0]["evidence"][-1][
        "counts_toward_formal_completeness"
    ] = "false"
    queries.record = {
        "run_id": "RUN-001",
        "evidence_and_findings": nested,
    }

    state = adapter.snapshot(_selected_context())

    assert state.phase is ViewPhase.READY
    assert state.last_reliable_data is not None
    quick = next(
        item
        for item in state.last_reliable_data.candidates[0].evidence
        if item.coverage is EvidenceCoverage.QUICK_EXPERIMENT
    )
    assert quick.counts_toward_formal_completeness is False
    adapter.close()

    mismatched, _bridge, mismatch_queries = _live_adapter()
    nested = _live_record()
    nested["selection"]["run_id"] = "RUN-OTHER"
    mismatch_queries.record = {
        "run_id": "RUN-001",
        "evidence_and_findings": nested,
    }
    rejected = mismatched.snapshot(_selected_context())
    assert rejected.phase is ViewPhase.FAILED
    assert rejected.presentation is (
        EvidenceAndFindingsPresentationState.FAILED
    )
    assert rejected.last_reliable_data is None
    assert rejected.error is not None
    assert rejected.error.code == "evidence_and_findings_mapping_failed"
    mismatched.close()


def test_live_adapter_distinguishes_empty_from_unavailable_query_source():
    gateway = RuntimeGateway()
    queries = _EvidenceQueries()
    queries.record["run_id"] = "OTHER-RUN"
    gateway._queries = queries
    empty = LiveEvidenceAndFindingsAdapter(
        runtime_gateway=gateway,
        event_bridge=EventBridge(subscribe_backend=False),
        clock=lambda: NOW,
        executor=_DirectExecutor(),
    )
    empty_state = empty.snapshot(_selected_context())
    assert empty_state.presentation is (
        EvidenceAndFindingsPresentationState.EMPTY
    )
    assert empty_state.completeness is Completeness.EMPTY
    assert empty_state.last_reliable_data is None
    empty.close()

    gateway._queries = None
    unavailable = LiveEvidenceAndFindingsAdapter(
        runtime_gateway=gateway,
        event_bridge=EventBridge(subscribe_backend=False),
        clock=lambda: NOW,
        executor=_DirectExecutor(),
    )
    unavailable_state = unavailable.snapshot(_selected_context())
    assert unavailable_state.presentation is (
        EvidenceAndFindingsPresentationState.DISCONNECTED
    )
    assert unavailable_state.phase is ViewPhase.FAILED
    assert unavailable_state.freshness is Freshness.DISCONNECTED
    assert unavailable_state.last_reliable_data is None
    assert unavailable_state.error is not None
    unavailable.close()


def test_live_adapter_maps_existing_series_aggregate_without_flattening_states():
    adapter, _bridge, queries = _live_adapter()
    queries.record = {
        "run_id": "RUN-001",
        "revision": 12,
        "updated_at": (NOW - timedelta(seconds=6)).isoformat(),
        "status": "completed",
        "series_evidence_aggregate": {
            "candidate_summaries": [
                {
                    "candidate_id": "MODEL-LEGACY-LIVE",
                    "evidence_status": {
                        "baseline_artifact": "pass",
                        "hidden_eval_artifact": "fail",
                        "paired_sensitivity_artifact": "not_available",
                        "quick_experiment_artifact": "warning",
                    },
                    "evidence_details": {
                        "baseline_artifact": {
                            "status": "pass",
                            "artifact_hash": "sha256:baseline-live",
                            "source_run_ids": ["RUN-001"],
                            "runner_version": "evidence-runner/legacy-live",
                        },
                        "hidden_eval_artifact": {
                            "status": "fail",
                            "blocking_metrics": ["stable_window_count"],
                            "artifact_hash": "sha256:hidden-live",
                            "source_run_ids": ["RUN-HIDDEN"],
                            "runner_version": "evidence-runner/legacy-live",
                        },
                        "paired_sensitivity_artifact": {
                            "status": "not_available",
                            "next_action": "Run the paired fee sensitivity.",
                            "artifact_hash": "sha256:paired-live",
                            "source_run_ids": ["RUN-PAIR"],
                            "runner_version": "evidence-runner/legacy-live",
                            "sensitivity_breakpoints": [
                                {
                                    "id": "BP-LEGACY-LIVE-FEE",
                                    "assumption_name": "fee_multiplier",
                                    "threshold": "unavailable",
                                    "outcome": "Not assessed.",
                                    "evidence_ids": [
                                        "E-MODEL-LEGACY-LIVE-PAIRED-SENSITIVITY-ARTIFACT"
                                    ],
                                }
                            ],
                        },
                        "quick_experiment_artifact": {
                            "status": "warning",
                            "artifact_hash": "sha256:quick-live",
                            "source_run_ids": ["RUN-QUICK"],
                            "runner_version": "evidence-runner/legacy-live",
                        },
                    },
                    "dependencies": [
                        {
                            "name": "reproduction-manifest",
                            "version": "RM-001",
                            "artifact_hash": "sha256:rm-live",
                        }
                    ],
                }
            ]
        },
        "runtime_context": {
            "market_context": ["600519.SH"],
            "account_context": ["MODEL-LEGACY-LIVE"],
            "position_context": [],
            "order_context": ["ORD-LEGACY · 600519.SH · filled"],
            "fill_context": ["FILL-LEGACY · 600519.SH · 100 @ 1500"],
        },
    }

    state = adapter.snapshot(_selected_context())

    assert state.freshness is Freshness.STALE
    assert state.phase is ViewPhase.DEGRADED
    assert state.completeness is Completeness.PARTIAL
    assert state.last_reliable_data is not None
    candidate = state.last_reliable_data.candidates[0]
    assert {item.coverage for item in candidate.evidence} == {
        EvidenceCoverage.BASELINE,
        EvidenceCoverage.COMPOUND_SCENARIO,
        EvidenceCoverage.ISOLATED_SENSITIVITY,
        EvidenceCoverage.QUICK_EXPERIMENT,
    }
    assert {
        item.availability for item in candidate.evidence
    } == {
        EvidenceAvailability.COMPLETE,
        EvidenceAvailability.FAILED,
        EvidenceAvailability.UNAVAILABLE,
        EvidenceAvailability.PARTIAL,
    }
    assert all(
        item.counts_toward_formal_completeness is False
        for item in candidate.evidence
        if item.coverage is EvidenceCoverage.QUICK_EXPERIMENT
    )
    assert candidate.findings
    assert any(
        finding.sensitivity_breakpoints
        for finding in candidate.findings
    )
    assert candidate.provenance.artifact_hashes
    assert candidate.provenance.source_run_ids
    assert candidate.provenance.dependencies
    adapter.close()


def test_runtime_query_reads_persisted_evidence_package_for_the_selected_run(
    tmp_path,
    monkeypatch,
):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'live-evidence.sqlite3'}",
        future=True,
    )
    Base.metadata.create_all(engine)
    isolated_session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        future=True,
    )
    monkeypatch.setattr(
        runtime_query_service,
        "SessionLocal",
        isolated_session,
    )
    package_path = tmp_path / "evidence-package.json"
    persisted_record = _live_record()
    for identity in (
        "strategy_id",
        "approved_recipe_id",
        "reproduction_manifest_id",
    ):
        persisted_record["selection"].pop(identity)
    package_path.write_text(json.dumps(persisted_record), encoding="utf-8")
    session = isolated_session()
    try:
        session.add(
            SimulationRun(
                run_id="RUN-001",
                name="Persisted evidence diagnosis",
                scenario_name="SCENARIO-BASELINE",
                run_type="diagnostic",
                status="completed",
                started_at=NOW - timedelta(minutes=8),
                updated_at=NOW,
                sim_start_day=1,
                last_sim_day=4,
                sim_end_day=4,
                last_sim_dt=datetime(2029, 1, 4, 10, 30),
                config_version="RM-001",
                environment_tag="SCENARIO-SET-001",
            )
        )
        session.add(
            AgentBinding(
                agent_name="MODEL-LIVE-B17",
                agent_type="MODEL",
                account_id="ACCOUNT-B17",
                run_id="RUN-001",
                created_at=NOW.replace(tzinfo=None),
                updated_at=NOW.replace(tzinfo=None),
                meta=json.dumps(
                    {
                        "strategy": "STRATEGY-MOMENTUM-001",
                        "approved_recipe_id": "RECIPE-001",
                        "reproduction_manifest_id": "RM-001",
                        "evidence_package_path": str(package_path),
                    }
                ),
            )
        )
        session.add(
            AgentBinding(
                agent_name="MODEL-NEWER-WITHOUT-EVIDENCE",
                agent_type="MODEL",
                account_id="ACCOUNT-NEWER",
                run_id="RUN-001",
                created_at=(
                    NOW.replace(tzinfo=None) + timedelta(minutes=1)
                ),
                updated_at=(
                    NOW.replace(tzinfo=None) + timedelta(minutes=1)
                ),
                meta=json.dumps(
                    {
                        "strategy": "STRATEGY-UNRELATED",
                        "approved_recipe_id": "RECIPE-WRONG",
                        "reproduction_manifest_id": "RM-WRONG",
                    }
                ),
            )
        )
        session.commit()
    finally:
        session.close()

    query = RuntimeQueryService.__new__(RuntimeQueryService)
    snapshot = query.get_evidence_and_findings_snapshot("RUN-001")

    assert snapshot is not None
    assert snapshot["run_id"] == "RUN-001"
    assert snapshot["candidates"][0]["candidate_id"] == "MODEL-LIVE-B17"
    assert (
        snapshot["selection"]["strategy_id"]
        == "STRATEGY-MOMENTUM-001"
    )
    assert snapshot["selection"]["approved_recipe_id"] == "RECIPE-001"
    assert snapshot["selection"]["reproduction_manifest_id"] == "RM-001"
    assert snapshot["_source_version_order"] > 0
    assert snapshot["read_only_context"]["account"]
    engine.dispose()


def test_app_context_composes_live_or_fake_evidence_with_one_pinned_context(
    tmp_path,
    monkeypatch,
):
    identities = {
        "STOCKSIM_FRONTEND_V2_CAMPAIGN_ID": "FDC-001",
        "STOCKSIM_FRONTEND_V2_RUN_ID": "RUN-001",
        "STOCKSIM_FRONTEND_V2_STRATEGY_ID": "STRATEGY-MOMENTUM-001",
        "STOCKSIM_FRONTEND_V2_MARKET_SCENARIO_ID": "SCENARIO-BASELINE",
        "STOCKSIM_FRONTEND_V2_APPROVED_RECIPE_ID": "RECIPE-001",
        "STOCKSIM_FRONTEND_V2_REPRODUCTION_MANIFEST_ID": "RM-001",
    }
    for name, value in identities.items():
        monkeypatch.setenv(name, value)
    bridge = EventBridge(subscribe_backend=False)

    fake = build_app_context(
        settings_path=str(tmp_path / "fake.json"),
        run_monitoring_mode="fake",
        event_bridge=bridge,
    )
    live = build_app_context(
        settings_path=str(tmp_path / "live.json"),
        run_monitoring_mode="live",
        event_bridge=bridge,
    )

    assert isinstance(
        fake.evidence_and_findings_feature,
        DeterministicFakeEvidenceAndFindingsAdapter,
    )
    assert isinstance(
        live.evidence_and_findings_feature,
        LiveEvidenceAndFindingsAdapter,
    )
    assert (
        live.evidence_and_findings_context
        == fake.evidence_and_findings_context
        == _selected_context()
    )
    fake.run_monitoring_feature.close()
    fake.evidence_and_findings_feature.close()
    live.run_monitoring_feature.close()
    live.evidence_and_findings_feature.close()
