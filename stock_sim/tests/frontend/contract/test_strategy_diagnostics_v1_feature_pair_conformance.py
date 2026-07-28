from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from typing import Protocol

import pytest

from app.event_bridge import EventBridge
from app.features import (
    ApplicationReadAvailability,
    ApplicationReadError,
    ApplicationReadErrorCode,
    ApprovedScenarioRecipeId,
    CancelDiagnosticTask,
    Completeness,
    DeterministicFakeEvidenceAndFindingsAdapter,
    DeterministicFakeRunMonitoringAdapter,
    DiagnosticTaskCapabilities,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsData,
    EvidenceAndFindingsFeature,
    EvidenceAndFindingsPresentationState,
    EvidenceAndFindingsSelection,
    EvidenceAndFindingsViewState,
    FormalDiagnosticCampaignId,
    Freshness,
    LiveEvidenceAndFindingsAdapter,
    LiveRunMonitoringAdapter,
    MarketScenarioId,
    ReproductionManifestId,
    RunLifecyclePhase,
    RunMonitoringContext,
    RunMonitoringData,
    RunMonitoringFeature,
    RunMonitoringPresentationState,
    RunMonitoringSelection,
    RunMonitoringViewState,
    SourceGenerationId,
    StrategyRunId,
    StrategyUnderTestId,
    TerminalOutcome,
    ViewPhase,
)
from tests.frontend.strategy_diagnostics_v1_test_support import (
    TypedScriptedApplicationReadModel,
)

UTC = timezone.utc

_CANDIDATE_IDS = frozenset(("MODEL-A04", "MODEL-B17"))
_METRIC_SUFFIXES = (
    "DOMAIN-BASE",
    "DOMAIN-COMPOUND",
    "EXEC-BASE",
    "EXEC-ISO",
    "EXPOSURE-BASE",
    "EXPOSURE-COMPOUND",
    "QUICK",
    "RET-BASE",
    "RISK-BASE",
    "STABILITY-BASE",
    "STABILITY-ISO",
)
_COMPARISON_SUFFIXES = (
    "DOMAIN",
    "EXPOSURE",
    "FEE",
    "QUICK",
    "STABILITY",
)
_EXPECTED_EVIDENCE_IDENTITY_SETS = {
    "candidates": _CANDIDATE_IDS,
    "metrics": frozenset(
        f"E-{candidate}-{suffix}"
        for candidate in _CANDIDATE_IDS
        for suffix in _METRIC_SUFFIXES
    ),
    "comparisons": frozenset(
        f"CMP-{candidate}-{suffix}"
        for candidate in _CANDIDATE_IDS
        for suffix in _COMPARISON_SUFFIXES
    ),
    "curves": frozenset(),
    "findings": frozenset(
        f"F-{candidate}-{number:02d}"
        for candidate in _CANDIDATE_IDS
        for number in (1, 2)
    ),
    "breakpoints": frozenset(
        f"BP-{candidate}-FEE" for candidate in _CANDIDATE_IDS
    ),
}


def _run_context() -> RunMonitoringContext:
    return RunMonitoringContext.for_run(
        RunMonitoringSelection(
            campaign_id=FormalDiagnosticCampaignId("FDC-CONFORMANCE"),
            run_id=StrategyRunId("RUN-CONFORMANCE"),
        )
    )


def _evidence_context() -> EvidenceAndFindingsContext:
    return EvidenceAndFindingsContext.for_selection(
        EvidenceAndFindingsSelection(
            campaign_id=FormalDiagnosticCampaignId("FDC-CONFORMANCE"),
            run_id=StrategyRunId("RUN-CONFORMANCE"),
            strategy_id=StrategyUnderTestId("STRATEGY-MOMENTUM-001"),
            market_scenario_id=MarketScenarioId("SCENARIO-BASELINE"),
            approved_recipe_id=ApprovedScenarioRecipeId("RECIPE-CONFORMANCE"),
            reproduction_manifest_id=ReproductionManifestId("RM-001"),
        )
    )


def _evidence_identity_sets(
    data: EvidenceAndFindingsData,
) -> dict[str, frozenset[str]]:
    return {
        "candidates": frozenset(
            candidate.identity.value for candidate in data.candidates
        ),
        "metrics": frozenset(
            record.identity.value
            for candidate in data.candidates
            for record in candidate.evidence
        ),
        "comparisons": frozenset(
            comparison.identity.value
            for candidate in data.candidates
            for comparison in candidate.comparisons
        ),
        "curves": frozenset(
            curve.identity
            for candidate in data.candidates
            for curve in candidate.curves
        ),
        "findings": frozenset(
            finding.identity.value
            for candidate in data.candidates
            for finding in candidate.findings
        ),
        "breakpoints": frozenset(
            breakpoint.identity.value
            for candidate in data.candidates
            for finding in candidate.findings
            for breakpoint in finding.sensitivity_breakpoints
        ),
    }


def _run_identity_tuple(data: RunMonitoringData) -> tuple[object, ...]:
    return (
        data.selection,
        data.strategy_id,
        data.market_scenario_id,
        data.scenario_set_id,
        data.reproduction_manifest_id,
        data.task_id,
    )


class _DirectExecutor:
    def submit(self, fn, /, *args, **kwargs):
        from concurrent.futures import Future

        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as error:  # noqa: BLE001 - Future semantics
            future.set_exception(error)
        return future

    def shutdown(self, wait=True, *, cancel_futures=False):
        return None


class _FeaturePairDriver(Protocol):
    run_feature: RunMonitoringFeature
    evidence_feature: EvidenceAndFindingsFeature
    run_context: RunMonitoringContext
    evidence_context: EvidenceAndFindingsContext

    def ready(
        self,
    ) -> tuple[RunMonitoringViewState, EvidenceAndFindingsViewState]: ...

    def duplicate(
        self,
    ) -> tuple[RunMonitoringViewState, EvidenceAndFindingsViewState]: ...

    def partial(
        self,
    ) -> tuple[RunMonitoringViewState, EvidenceAndFindingsViewState]: ...

    def stale(
        self,
    ) -> tuple[RunMonitoringViewState, EvidenceAndFindingsViewState]: ...

    def disconnect(
        self,
    ) -> tuple[RunMonitoringViewState, EvidenceAndFindingsViewState]: ...

    def reconnect(
        self,
    ) -> tuple[RunMonitoringViewState, EvidenceAndFindingsViewState]: ...

    def reject_old_generation(
        self,
    ) -> tuple[RunMonitoringViewState, EvidenceAndFindingsViewState]: ...

    def terminal(
        self,
        outcome: TerminalOutcome,
    ) -> tuple[RunMonitoringViewState, EvidenceAndFindingsViewState]: ...

    def attempt_terminal_regression(self) -> RunMonitoringViewState: ...

    def close(self) -> None: ...


class _FakeFeaturePairDriver:
    def __init__(self) -> None:
        self.now = datetime(2030, 2, 1, 12, 0, tzinfo=UTC)
        self.run_context = _run_context()
        self.evidence_context = _evidence_context()
        self.run_feature = DeterministicFakeRunMonitoringAdapter(
            clock=lambda: self.now,
        )
        self.evidence_feature = DeterministicFakeEvidenceAndFindingsAdapter(
            clock=lambda: self.now,
        )

    def ready(self):
        return (
            self.run_feature.advance_to_running(self.run_context),
            self.evidence_feature.advance_to_completed(self.evidence_context),
        )

    def duplicate(self):
        return (
            self.run_feature.snapshot(self.run_context),
            self.evidence_feature.snapshot(self.evidence_context),
        )

    def partial(self):
        return (
            self.run_feature.advance_to_partial(self.run_context),
            self.evidence_feature.advance_to_partial(self.evidence_context),
        )

    def stale(self):
        return (
            self.run_feature.advance_to_stale(self.run_context),
            self.evidence_feature.advance_to_stale(self.evidence_context),
        )

    def disconnect(self):
        return (
            self.run_feature.advance_to_disconnected(self.run_context),
            self.evidence_feature.advance_to_disconnected(self.evidence_context),
        )

    def reconnect(self):
        run = self.run_feature.advance_to_reconnected(self.run_context)
        previous = self.evidence_feature.snapshot(self.evidence_context)
        evidence = self.evidence_feature.replay_scripted_state(
            self.evidence_context,
            replace(
                previous,
                revision=previous.revision + 1,
                observed_at=self.now,
                freshness=Freshness.FRESH,
                age=timedelta(0),
                source=replace(
                    previous.source,
                    generation=SourceGenerationId(previous.source.generation.value + 1),
                ),
                phase=ViewPhase.READY,
                presentation=EvidenceAndFindingsPresentationState.READY,
                error=None,
                completeness=Completeness.COMPLETE,
            ),
        )
        return run, evidence

    def reject_old_generation(self):
        evidence = self.evidence_feature.snapshot(self.evidence_context)
        old_generation = SourceGenerationId(evidence.source.generation.value - 1)
        rejected = self.evidence_feature.replay_scripted_state(
            self.evidence_context,
            replace(
                evidence,
                revision=evidence.revision + 1,
                source=replace(
                    evidence.source,
                    generation=old_generation,
                ),
            ),
        )
        return self.run_feature.snapshot(self.run_context), rejected

    def terminal(self, outcome):
        if outcome is TerminalOutcome.COMPLETED:
            run = self.run_feature.advance_to_completed(self.run_context)
        elif outcome is TerminalOutcome.FAILED:
            run = self.run_feature.advance_to_failed(self.run_context)
        else:
            current = self.run_feature.snapshot(self.run_context)
            data = current.last_reliable_data
            assert data is not None and data.task_id is not None
            result = self.run_feature.cancel_diagnostic_task(
                CancelDiagnosticTask(
                    target_id=data.task_id,
                    expected_revision=current.revision,
                )
            )
            assert result.accepted
            run = self.run_feature.snapshot(self.run_context)
        return run, self.evidence_feature.snapshot(self.evidence_context)

    def attempt_terminal_regression(self):
        return self.run_feature.advance_to_running(self.run_context)

    def close(self):
        self.run_feature.close()
        self.evidence_feature.close()


class _LiveFeaturePairDriver:
    def __init__(self) -> None:
        self.now = datetime(2030, 2, 1, 12, 0, tzinfo=UTC)
        self.run_context = _run_context()
        self.evidence_context = _evidence_context()
        run_seed = DeterministicFakeRunMonitoringAdapter(clock=lambda: self.now)
        evidence_seed = DeterministicFakeEvidenceAndFindingsAdapter(
            clock=lambda: self.now
        )
        run_data = run_seed.advance_to_running(self.run_context).last_reliable_data
        evidence_data = evidence_seed.advance_to_completed(
            self.evidence_context
        ).last_reliable_data
        assert run_data is not None
        assert evidence_data is not None
        run_seed.close()
        evidence_seed.close()
        self._running_data = run_data
        self._completed_run_data = replace(
            run_data,
            lifecycle=RunLifecyclePhase.COMPLETED,
            terminal_outcome=TerminalOutcome.COMPLETED,
            progress=replace(
                run_data.progress,
                completed=run_data.progress.total,
            ),
            capabilities=DiagnosticTaskCapabilities(False, False, False),
        )
        self._failed_run_data = replace(
            run_data,
            lifecycle=RunLifecyclePhase.FAILED,
            terminal_outcome=TerminalOutcome.FAILED,
            capabilities=DiagnosticTaskCapabilities(False, False, False),
        )
        self._canceled_run_data = replace(
            run_data,
            lifecycle=RunLifecyclePhase.CANCELED,
            terminal_outcome=TerminalOutcome.CANCELED,
            capabilities=DiagnosticTaskCapabilities(False, False, False),
        )
        self._evidence_data = evidence_data
        self._read_model = TypedScriptedApplicationReadModel(
            run_context=self.run_context,
            evidence_context=self.evidence_context,
            run_data=run_data,
            evidence_data=evidence_data,
            clock=lambda: self.now,
        )
        self._bridge = EventBridge(subscribe_backend=False)
        executor = _DirectExecutor()
        self.run_feature = LiveRunMonitoringAdapter(
            application_read_model=self._read_model,
            event_bridge=self._bridge,
            clock=lambda: self.now,
            executor=executor,
        )
        self.evidence_feature = LiveEvidenceAndFindingsAdapter(
            application_read_model=self._read_model,
            event_bridge=self._bridge,
            clock=lambda: self.now,
            executor=executor,
        )
        self._old_generation = self._bridge.connection_generation

    def _emit(self, *, generation=None):
        self._bridge.on_snapshot(
            {"run_id": self.run_context.selection.run_id.value},
            generation=(
                self._bridge.connection_generation if generation is None else generation
            ),
        )
        self._bridge.flush(force=True)
        return (
            self.run_feature.snapshot(self.run_context),
            self.evidence_feature.snapshot(self.evidence_context),
        )

    def ready(self):
        return (
            self.run_feature.snapshot(self.run_context),
            self.evidence_feature.snapshot(self.evidence_context),
        )

    def duplicate(self):
        return self._emit()

    def partial(self):
        self._read_model.set_run(
            self._running_data,
            availability=ApplicationReadAvailability.PARTIAL,
            error=ApplicationReadError(
                code=ApplicationReadErrorCode.EVIDENCE_PARTIAL,
                message="Some persisted run identity is pending.",
                retryable=True,
            ),
        )
        self._read_model.set_evidence(
            self._evidence_data,
            availability=ApplicationReadAvailability.PARTIAL,
            error=ApplicationReadError(
                code=ApplicationReadErrorCode.EVIDENCE_PARTIAL,
                message="Some persisted evidence is pending.",
                retryable=True,
            ),
        )
        return self._emit()

    def stale(self):
        self.now += timedelta(seconds=6)
        return (
            self.run_feature.snapshot(self.run_context),
            self.evidence_feature.snapshot(self.evidence_context),
        )

    def disconnect(self):
        self._old_generation = self._bridge.connection_generation
        self._bridge.mark_disconnected()
        return (
            self.run_feature.snapshot(self.run_context),
            self.evidence_feature.snapshot(self.evidence_context),
        )

    def reconnect(self):
        self._running_data = replace(
            self._running_data,
            wall_time=replace(
                self._running_data.wall_time,
                observed_at=self.now,
            ),
        )
        self._completed_run_data = replace(
            self._completed_run_data,
            wall_time=replace(
                self._completed_run_data.wall_time,
                observed_at=self.now,
            ),
        )
        self._read_model.set_run(self._running_data)
        self._read_model.set_evidence(self._evidence_data)
        self._bridge.mark_reconnected()
        return self._emit()

    def reject_old_generation(self):
        return self._emit(generation=self._old_generation)

    def terminal(self, outcome):
        terminal_data = {
            TerminalOutcome.COMPLETED: self._completed_run_data,
            TerminalOutcome.FAILED: self._failed_run_data,
            TerminalOutcome.CANCELED: self._canceled_run_data,
        }[outcome]
        self._read_model.set_run(terminal_data)
        return self._emit()

    def attempt_terminal_regression(self):
        self._read_model.set_run(self._running_data)
        return self._emit()[0]

    def close(self):
        self.run_feature.close()
        self.evidence_feature.close()


@pytest.fixture(params=(_FakeFeaturePairDriver, _LiveFeaturePairDriver))
def feature_pair(request) -> _FeaturePairDriver:
    driver = request.param()
    yield driver
    driver.close()


def test_shared_feature_pair_identity_immutability_and_duplicate_suppression(
    feature_pair,
):
    run, evidence = feature_pair.ready()
    run_data = run.last_reliable_data
    evidence_data = evidence.last_reliable_data
    assert run_data is not None
    assert evidence_data is not None
    assert (
        run_data.selection.campaign_id.value,
        run_data.selection.run_id.value,
        run_data.strategy_id.value,
        run_data.market_scenario_id.value,
        run_data.scenario_set_id.value,
        run_data.reproduction_manifest_id.value,
    ) == (
        "FDC-CONFORMANCE",
        "RUN-CONFORMANCE",
        "STRATEGY-MOMENTUM-001",
        "SCENARIO-BASELINE",
        "SCENARIO-SET-001",
        "RM-001",
    )
    assert run_data.selection.run_id == evidence_data.selection.run_id
    assert run_data.selection.campaign_id == evidence_data.selection.campaign_id
    assert run_data.strategy_id == evidence_data.selection.strategy_id
    assert (
        run_data.market_scenario_id
        == evidence_data.selection.market_scenario_id
    )
    assert (
        run_data.reproduction_manifest_id
        == evidence_data.selection.reproduction_manifest_id
    )
    assert evidence_data.selection.approved_recipe_id.value
    assert evidence_data.evidence_package_id.value
    assert (
        _evidence_identity_sets(evidence_data)
        == _EXPECTED_EVIDENCE_IDENTITY_SETS
    )
    with pytest.raises(FrozenInstanceError):
        run_data.progress.completed = 99  # type: ignore[misc]

    delivered_run: list[int] = []
    delivered_evidence: list[int] = []
    run_subscription = feature_pair.run_feature.subscribe(
        feature_pair.run_context,
        lambda state: delivered_run.append(state.revision),
    )
    evidence_subscription = feature_pair.evidence_feature.subscribe(
        feature_pair.evidence_context,
        lambda state: delivered_evidence.append(state.revision),
    )
    duplicate_run, duplicate_evidence = feature_pair.duplicate()
    assert duplicate_run.revision == run.revision
    assert duplicate_evidence.revision == evidence.revision
    assert duplicate_run.last_reliable_data is run_data
    assert duplicate_evidence.last_reliable_data is evidence_data
    assert (
        _evidence_identity_sets(duplicate_evidence.last_reliable_data)
        == _EXPECTED_EVIDENCE_IDENTITY_SETS
    )
    assert delivered_run == [run.revision]
    assert delivered_evidence == [evidence.revision]
    run_subscription.dispose()
    evidence_subscription.dispose()
    assert run_subscription.disposed
    assert evidence_subscription.disposed

    public_surface = {
        name.casefold()
        for feature in (
            feature_pair.run_feature,
            feature_pair.evidence_feature,
        )
        for name in dir(feature)
        if not name.startswith("_")
    }
    for forbidden in (
        "buy",
        "sell",
        "order",
        "trade",
        "dispatch",
        "invoke",
        "execute",
    ):
        assert not any(forbidden in name for name in public_surface)


def test_shared_feature_pair_partial_stale_disconnect_recovery_and_generation(
    feature_pair,
):
    ready_run, ready_evidence = feature_pair.ready()
    ready_run_data = ready_run.last_reliable_data
    ready_evidence_data = ready_evidence.last_reliable_data
    assert ready_run_data is not None
    assert ready_evidence_data is not None
    assert (
        _evidence_identity_sets(ready_evidence_data)
        == _EXPECTED_EVIDENCE_IDENTITY_SETS
    )
    ready_run_identity = _run_identity_tuple(ready_run_data)
    ready_evidence_pins = (
        ready_evidence_data.selection,
        ready_evidence_data.evidence_package_id,
    )

    def assert_identities_preserved(run_state, evidence_state) -> None:
        assert run_state.last_reliable_data is not None
        assert evidence_state.last_reliable_data is not None
        assert _run_identity_tuple(
            run_state.last_reliable_data
        ) == ready_run_identity
        assert (
            evidence_state.last_reliable_data.selection,
            evidence_state.last_reliable_data.evidence_package_id,
        ) == ready_evidence_pins
        assert (
            _evidence_identity_sets(evidence_state.last_reliable_data)
            == _EXPECTED_EVIDENCE_IDENTITY_SETS
        )

    partial_run, partial_evidence = feature_pair.partial()
    assert partial_run.revision > ready_run.revision
    assert partial_evidence.revision > ready_evidence.revision
    assert partial_run.completeness is Completeness.PARTIAL
    assert partial_evidence.completeness is Completeness.PARTIAL
    assert partial_run.last_reliable_data is not None
    assert partial_evidence.last_reliable_data is not None
    assert partial_run.error is not None and partial_run.error.retryable
    assert partial_evidence.error is not None and partial_evidence.error.retryable
    assert partial_run.last_reliable_data == ready_run_data
    assert_identities_preserved(partial_run, partial_evidence)

    stale_run, stale_evidence = feature_pair.stale()
    assert stale_run.freshness is Freshness.STALE
    assert stale_evidence.freshness is Freshness.STALE
    assert stale_run.last_reliable_data == partial_run.last_reliable_data
    assert stale_evidence.last_reliable_data == partial_evidence.last_reliable_data
    assert_identities_preserved(stale_run, stale_evidence)
    disconnected_run, disconnected_evidence = feature_pair.disconnect()
    assert disconnected_run.freshness is Freshness.DISCONNECTED
    assert disconnected_evidence.freshness is Freshness.DISCONNECTED
    assert disconnected_run.last_reliable_data == stale_run.last_reliable_data
    assert (
        disconnected_evidence.last_reliable_data
        == stale_evidence.last_reliable_data
    )
    assert_identities_preserved(disconnected_run, disconnected_evidence)

    recovered_run, recovered_evidence = feature_pair.reconnect()
    assert recovered_run.freshness is Freshness.FRESH
    assert recovered_evidence.freshness is Freshness.FRESH
    assert recovered_run.last_reliable_data is not None
    assert recovered_evidence.last_reliable_data is not None
    assert_identities_preserved(recovered_run, recovered_evidence)
    before_old = (recovered_run.revision, recovered_evidence.revision)
    old_run, old_evidence = feature_pair.reject_old_generation()
    assert (old_run.revision, old_evidence.revision) == before_old
    assert old_run.last_reliable_data == recovered_run.last_reliable_data
    assert old_evidence.last_reliable_data == recovered_evidence.last_reliable_data
    assert_identities_preserved(old_run, old_evidence)


def test_shared_feature_pair_disconnect_before_first_reliable_state_is_structured(
    feature_pair,
):
    disconnected_run, disconnected_evidence = feature_pair.disconnect()

    for state in (disconnected_run, disconnected_evidence):
        assert state.freshness is Freshness.DISCONNECTED
        assert state.last_reliable_data is None
        assert state.phase is ViewPhase.FAILED
        assert state.error is not None
        assert state.error.code
        assert state.error.message
        assert state.error.retryable


@pytest.mark.parametrize("outcome", tuple(TerminalOutcome))
def test_shared_feature_pair_terminal_outcome_is_stable_and_close_is_final(
    feature_pair,
    outcome,
):
    feature_pair.ready()
    terminal_run, terminal_evidence = feature_pair.terminal(outcome)
    assert terminal_run.presentation is RunMonitoringPresentationState.TERMINAL
    assert terminal_run.last_reliable_data is not None
    assert terminal_run.last_reliable_data.terminal_outcome is outcome
    assert not terminal_run.last_reliable_data.capabilities.can_pause
    assert not terminal_run.last_reliable_data.capabilities.can_resume
    assert not terminal_run.last_reliable_data.capabilities.can_cancel
    assert terminal_evidence.presentation is (
        EvidenceAndFindingsPresentationState.READY
    )
    if outcome is TerminalOutcome.FAILED:
        assert terminal_run.error is not None
        assert terminal_run.error.code == "diagnostic_run_failed"
        assert not terminal_run.error.retryable

    regressed = feature_pair.attempt_terminal_regression()
    assert regressed.revision > terminal_run.revision
    assert regressed.presentation is RunMonitoringPresentationState.TERMINAL
    assert regressed.error is not None
    assert regressed.error.code == "strategy_diagnostics_integrity_failed"
    assert regressed.error.retryable is False
    assert regressed.last_reliable_data is not None
    assert regressed.last_reliable_data.terminal_outcome is outcome

    disconnected_run, disconnected_evidence = feature_pair.disconnect()
    assert disconnected_run.last_reliable_data == regressed.last_reliable_data
    assert (
        disconnected_evidence.last_reliable_data
        == terminal_evidence.last_reliable_data
    )

    feature_pair.close()
    with pytest.raises(RuntimeError, match="closed"):
        feature_pair.run_feature.snapshot(feature_pair.run_context)
    with pytest.raises(RuntimeError, match="closed"):
        feature_pair.evidence_feature.snapshot(feature_pair.evidence_context)
