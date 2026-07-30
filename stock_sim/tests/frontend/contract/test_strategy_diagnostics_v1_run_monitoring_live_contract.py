from __future__ import annotations

import inspect
from concurrent.futures import Executor, Future
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Event, Thread, current_thread
from time import monotonic, sleep

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from app.event_bridge import EventBridge
from app.features import (
    APPLICATION_READ_MODEL_INTERFACE_VERSION,
    ApplicationReadAvailability,
    ApplicationReadError,
    ApplicationReadErrorCode,
    ApplicationReadModelVersion,
    ApplicationReadResult,
    ApprovedScenarioRecipeId,
    DeterministicFakeEvidenceAndFindingsAdapter,
    DiagnosticEvidencePackageId,
    DiagnosticTaskCapabilities,
    EvidenceAndFindingsContext,
    EvidenceAndFindingsSelection,
    EvidenceCoverage,
    FormalDiagnosticCampaignId,
    Freshness,
    LiveRunMonitoringAdapter,
    LiveStrategyDiagnosticsV1ApplicationAdapter,
    MarketScenarioId,
    ReadOnlyDiagnosticContext,
    ReproductionManifestId,
    ResolvedV1Journey,
    RunLifecyclePhase,
    RunMonitoringContext,
    RunMonitoringData,
    RunMonitoringPresentationState,
    RunMonitoringSelection,
    RunMonitoringViewState,
    RunProgress,
    SimulationTime,
    SourceRevisionToken,
    StrategyRunId,
    StrategyUnderTestId,
    TerminalOutcome,
    V1JourneySelector,
    ViewPhase,
    WallTime,
)
from app.ui.main_window import MainWindow
from tests.frontend.contract.test_strategy_diagnostics_v1_application_read_model_live_contract import (
    _persist_formal_v1,
)

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


class _DirectExecutor(Executor):
    def submit(self, fn, /, *args, **kwargs):
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as error:  # noqa: BLE001  # pragma: no cover
            future.set_exception(error)
        return future


class _TypedRunReadModel:
    def __init__(self, journey: ResolvedV1Journey, data: RunMonitoringData) -> None:
        self.journey = journey
        self.data = data
        self.run_token = SourceRevisionToken("b" * 64)
        self.resolve_count = 0
        self.read_count = 0
        self.read_threads: list[str] = []
        self.run_result: ApplicationReadResult[RunMonitoringData] | None = None

    @property
    def interface_version(self) -> ApplicationReadModelVersion:
        return APPLICATION_READ_MODEL_INTERFACE_VERSION

    def resolve_journey(
        self,
        selector: V1JourneySelector,
    ) -> ApplicationReadResult[ResolvedV1Journey]:
        self.resolve_count += 1
        self.read_threads.append(current_thread().name)
        assert selector.campaign_id == self.data.selection.campaign_id
        assert selector.run_id == self.data.selection.run_id
        return ApplicationReadResult(
            availability=ApplicationReadAvailability.READY,
            source_token=SourceRevisionToken("a" * 64),
            source_observed_at=NOW,
            value=self.journey,
            error=None,
        )

    def read_run(
        self,
        journey: ResolvedV1Journey,
    ) -> ApplicationReadResult[RunMonitoringData]:
        self.read_count += 1
        self.read_threads.append(current_thread().name)
        assert journey == self.journey
        if self.run_result is not None:
            return self.run_result
        return ApplicationReadResult(
            availability=ApplicationReadAvailability.READY,
            source_token=self.run_token,
            source_observed_at=NOW,
            value=self.data,
            error=None,
        )

    def read_evidence(self, journey: ResolvedV1Journey):
        raise AssertionError("Issue #50 must not read or connect Evidence")


def _run_fixture() -> tuple[
    RunMonitoringContext,
    ResolvedV1Journey,
    RunMonitoringData,
]:
    selection = RunMonitoringSelection(
        campaign_id=FormalDiagnosticCampaignId("FDC-50"),
        run_id=StrategyRunId("RUN-50"),
    )
    context = RunMonitoringContext.for_run(selection)
    manifest_id = ReproductionManifestId("RM-50")
    journey = ResolvedV1Journey(
        run_context=context,
        evidence_context=EvidenceAndFindingsContext.for_selection(
            EvidenceAndFindingsSelection(
                campaign_id=selection.campaign_id,
                run_id=selection.run_id,
                strategy_id=StrategyUnderTestId("STRATEGY-50"),
                market_scenario_id=MarketScenarioId("CASE-50"),
                approved_recipe_id=ApprovedScenarioRecipeId("RECIPE-50"),
                reproduction_manifest_id=manifest_id,
            )
        ),
        evidence_package_id=DiagnosticEvidencePackageId("PACKAGE-50"),
        campaign_case_id=MarketScenarioId("CASE-50"),
        campaign_layer=EvidenceCoverage.BASELINE,
    )
    data = RunMonitoringData(
        selection=selection,
        strategy_id=StrategyUnderTestId("STRATEGY-50"),
        market_scenario_id=MarketScenarioId("CASE-50"),
        scenario_set_id=None,
        reproduction_manifest_id=manifest_id,
        task_id=None,
        lifecycle=RunLifecyclePhase.COMPLETED,
        terminal_outcome=TerminalOutcome.COMPLETED,
        progress=RunProgress(
            current_node_id="CASE-50:5",
            current_node_label="baseline · 5/5",
            completed=5,
            total=5,
        ),
        simulation_time=SimulationTime(sim_day=2, instant=NOW),
        wall_time=WallTime(
            started_at=None,
            observed_at=NOW,
            elapsed=timedelta(0),
        ),
        execution_assumptions=(),
        alerts=(),
        context=ReadOnlyDiagnosticContext(
            market=("case CASE-50", "run artifact " + "c" * 64),
            account=("cash 100000",),
            positions=(),
            orders=(),
            fills=(),
        ),
        capabilities=DiagnosticTaskCapabilities(False, False, False),
        active_task=None,
    )
    return context, journey, data


def test_live_run_adapter_uses_only_the_typed_application_read_model() -> None:
    parameters = inspect.signature(LiveRunMonitoringAdapter).parameters
    assert "application_read_model" in parameters
    assert "runtime_gateway" not in parameters
    assert "diagnostic_tasks" not in parameters

    context, journey, data = _run_fixture()
    data = replace(
        data,
        lifecycle=RunLifecyclePhase.RUNNING,
        terminal_outcome=None,
    )
    read_model = _TypedRunReadModel(journey, data)
    bridge = EventBridge(subscribe_backend=False)
    adapter = LiveRunMonitoringAdapter(
        application_read_model=read_model,
        event_bridge=bridge,
        clock=lambda: NOW,
        executor=_DirectExecutor(),
    )

    first = adapter.snapshot(context)
    assert read_model.resolve_count == 1
    assert read_model.read_count == 1
    assert first.presentation is RunMonitoringPresentationState.ACTIVE
    assert first.freshness is Freshness.FRESH
    assert first.last_reliable_data == data
    assert first.last_reliable_data.capabilities == DiagnosticTaskCapabilities(
        False,
        False,
        False,
    )

    bridge.on_snapshot(
        {"run_id": "RUN-50", "ignored": "invalidation only"},
        generation=bridge.connection_generation,
    )
    bridge.flush(force=True)
    duplicate = adapter.snapshot(context)
    assert read_model.read_count == 2
    assert duplicate.revision == first.revision

    read_model.data = replace(
        data,
        context=replace(
            data.context,
            account=("cash 101000",),
        ),
    )
    read_model.run_token = SourceRevisionToken("d" * 64)
    bridge.on_snapshot(
        {"run_id": "RUN-50", "cash": "must not become Feature data"},
        generation=bridge.connection_generation,
    )
    bridge.flush(force=True)
    changed = adapter.snapshot(context)
    assert read_model.read_count == 3
    assert changed.revision == first.revision + 1
    assert changed.last_reliable_data is not None
    assert changed.last_reliable_data.context.account == ("cash 101000",)

    adapter.close()


def test_live_run_adapter_executes_authoritative_reads_off_the_caller_thread() -> None:
    context, journey, data = _run_fixture()
    read_model = _TypedRunReadModel(journey, data)
    bridge = EventBridge(subscribe_backend=False)
    caller_thread = current_thread().name
    adapter = LiveRunMonitoringAdapter(
        application_read_model=read_model,
        event_bridge=bridge,
        clock=lambda: NOW,
    )

    initial = adapter.snapshot(context)
    state = _wait_for_run_state(adapter, context)

    assert initial.presentation is RunMonitoringPresentationState.LOADING
    assert initial.phase is ViewPhase.LOADING
    assert state.last_reliable_data == data
    assert read_model.read_threads
    assert caller_thread not in read_model.read_threads
    assert all(
        thread_name.startswith("run-monitoring-")
        for thread_name in read_model.read_threads
    )
    adapter.close()


def test_owned_worker_initial_read_never_blocks_the_snapshot_caller() -> None:
    context, journey, data = _run_fixture()
    entered = Event()
    release = Event()

    class _BlockingReadModel(_TypedRunReadModel):
        def resolve_journey(self, selector):
            entered.set()
            assert release.wait(2)
            return super().resolve_journey(selector)

    read_model = _BlockingReadModel(journey, data)
    bridge = EventBridge(subscribe_backend=False)
    adapter = LiveRunMonitoringAdapter(
        application_read_model=read_model,
        event_bridge=bridge,
        clock=lambda: NOW,
    )
    returned: list = []
    caller = Thread(target=lambda: returned.append(adapter.snapshot(context)))
    caller.start()
    assert entered.wait(1)
    caller.join(0.1)
    try:
        assert not caller.is_alive()
        assert returned
        assert returned[0].presentation is RunMonitoringPresentationState.LOADING
    finally:
        release.set()
        caller.join(2)

    assert _wait_for_run_state(adapter, context).last_reliable_data == data
    adapter.close()


def test_terminal_transient_failure_retains_data_without_integrity_alarm() -> None:
    context, journey, data = _run_fixture()
    read_model = _TypedRunReadModel(journey, data)
    bridge = EventBridge(subscribe_backend=False)
    adapter = LiveRunMonitoringAdapter(
        application_read_model=read_model,
        event_bridge=bridge,
        clock=lambda: NOW,
        executor=_DirectExecutor(),
    )
    terminal = adapter.snapshot(context)
    read_model.run_result = _failed_run_read(
        ApplicationReadErrorCode.READ_FAILED,
        retryable=True,
    )

    bridge.on_snapshot({"run_id": "RUN-50"})
    bridge.flush(force=True)
    degraded = adapter.snapshot(context)

    assert degraded.last_reliable_data == terminal.last_reliable_data
    assert degraded.phase is ViewPhase.DEGRADED
    assert degraded.error is not None
    assert degraded.error.code == ApplicationReadErrorCode.READ_FAILED.value

    read_model.run_result = None
    bridge.on_snapshot({"run_id": "RUN-50"})
    bridge.flush(force=True)
    recovered = adapter.snapshot(context)

    assert recovered.presentation is RunMonitoringPresentationState.TERMINAL
    assert recovered.last_reliable_data == terminal.last_reliable_data
    assert recovered.error is None
    adapter.close()


def test_non_retryable_integrity_failure_after_success_fails_closed() -> None:
    context, journey, data = _run_fixture()
    read_model = _TypedRunReadModel(journey, data)
    bridge = EventBridge(subscribe_backend=False)
    adapter = LiveRunMonitoringAdapter(
        application_read_model=read_model,
        event_bridge=bridge,
        clock=lambda: NOW,
        executor=_DirectExecutor(),
    )
    adapter.snapshot(context)
    read_model.run_result = _failed_run_read(
        ApplicationReadErrorCode.INTEGRITY_FAILED,
        retryable=False,
    )

    bridge.on_snapshot({"run_id": "RUN-50"})
    bridge.flush(force=True)
    failed = adapter.snapshot(context)

    assert failed.phase is ViewPhase.FAILED
    assert failed.last_reliable_data is None
    assert failed.error is not None
    assert failed.error.code == ApplicationReadErrorCode.INTEGRITY_FAILED.value
    adapter.close()


def test_live_run_adapter_quarantines_terminal_regression_and_hash_conflict() -> None:
    context, journey, data = _run_fixture()
    read_model = _TypedRunReadModel(journey, data)
    bridge = EventBridge(subscribe_backend=False)
    adapter = LiveRunMonitoringAdapter(
        application_read_model=read_model,
        event_bridge=bridge,
        clock=lambda: NOW,
        executor=_DirectExecutor(),
    )
    terminal = adapter.snapshot(context)

    read_model.data = replace(
        data,
        context=replace(
            data.context,
            market=("case CASE-50", "run artifact " + "d" * 64),
        ),
    )
    read_model.run_token = SourceRevisionToken("e" * 64)
    bridge.on_snapshot({"run_id": "RUN-50"})
    bridge.flush(force=True)
    conflicted = adapter.snapshot(context)

    assert conflicted.last_reliable_data == terminal.last_reliable_data
    assert conflicted.error is not None
    assert conflicted.error.code == "strategy_diagnostics_integrity_failed"

    bridge.on_snapshot({"run_id": "RUN-50"})
    bridge.flush(force=True)
    repeated_conflict = adapter.snapshot(context)
    assert repeated_conflict.last_reliable_data == terminal.last_reliable_data
    assert repeated_conflict.error is not None
    assert (
        repeated_conflict.error.code == "strategy_diagnostics_integrity_failed"
    )

    read_model.data = replace(
        data,
        lifecycle=RunLifecyclePhase.RUNNING,
        terminal_outcome=None,
    )
    read_model.run_token = SourceRevisionToken("f" * 64)
    bridge.on_snapshot({"run_id": "RUN-50"})
    bridge.flush(force=True)
    regressed = adapter.snapshot(context)
    assert regressed.last_reliable_data == terminal.last_reliable_data
    assert regressed.error is not None
    assert regressed.error.code == "strategy_diagnostics_integrity_failed"
    adapter.close()


def test_real_file_backed_v1_run_is_visible_in_the_qml_journey(tmp_path) -> None:
    (
        application,
        engine,
        campaign,
        selected_run,
        package,
        manifest,
    ) = _persist_formal_v1(
        tmp_path / "diagnostics.sqlite3",
        tmp_path / "artifacts",
    )
    read_model = LiveStrategyDiagnosticsV1ApplicationAdapter(
        application,
        engine,
        clock=lambda: NOW,
    )
    selector = V1JourneySelector(
        campaign_id=FormalDiagnosticCampaignId(campaign.campaign_id),
        run_id=StrategyRunId(selected_run.run_id),
        evidence_package_id=DiagnosticEvidencePackageId(package.evidence_package_id),
        manifest_id=ReproductionManifestId(manifest.manifest_id),
    )
    resolved = read_model.resolve_journey(selector)
    assert resolved.value is not None
    bridge = EventBridge(subscribe_backend=False)
    run_feature = LiveRunMonitoringAdapter(
        application_read_model=read_model,
        event_bridge=bridge,
        journey_selector=selector,
        clock=lambda: NOW,
    )
    evidence_feature = DeterministicFakeEvidenceAndFindingsAdapter(clock=lambda: NOW)
    evidence_feature.advance_to_completed(resolved.value.evidence_context)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        run_monitoring_feature=run_feature,
        run_monitoring_context=resolved.value.run_context,
        evidence_and_findings_feature=evidence_feature,
        evidence_and_findings_context=resolved.value.evidence_context,
        frontend_v2_enabled=True,
    )
    app.processEvents()
    root = window.centralWidget().rootObject()
    expected_values = (
        campaign.campaign_id,
        selected_run.run_id,
        selected_run.specification.strategy_id,
        selected_run.specification.strategy_version,
        resolved.value.campaign_case_id.value,
        selected_run.specification.recipe_version_id,
        manifest.manifest_id,
        selected_run.run_artifact_hash,
    )
    _wait_for_run_state(run_feature, resolved.value.run_context, app=app)
    _wait_for_visible_text(
        root,
        expected_values,
        app=app,
    )
    run_state = run_feature.snapshot(resolved.value.run_context)
    assert run_state.last_reliable_data is not None
    assert window.centralWidget()._run_monitoring.progressText == (
        f"{run_state.last_reliable_data.progress.completed} / "
        f"{run_state.last_reliable_data.progress.total}"
    )
    assert run_state.presentation is RunMonitoringPresentationState.TERMINAL

    window.close()
    run_feature.close()
    evidence_feature.close()
    bridge.stop()
    engine.dispose()


def _failed_run_read(
    code: ApplicationReadErrorCode,
    *,
    retryable: bool,
) -> ApplicationReadResult[RunMonitoringData]:
    return ApplicationReadResult(
        availability=ApplicationReadAvailability.FAILED,
        source_token=SourceRevisionToken("9" * 64),
        source_observed_at=NOW,
        value=None,
        error=ApplicationReadError(
            code=code,
            message="The authoritative Run read failed.",
            retryable=retryable,
        ),
    )


def _wait_for_run_state(
    adapter: LiveRunMonitoringAdapter,
    context: RunMonitoringContext,
    *,
    app: QApplication | None = None,
) -> RunMonitoringViewState:
    deadline = monotonic() + 2
    while monotonic() < deadline:
        if app is not None:
            app.processEvents()
        state = adapter.snapshot(context)
        if state.last_reliable_data is not None:
            return state
        sleep(0.005)
    raise AssertionError("Run Monitoring did not receive its authoritative state")


def _wait_for_visible_text(
    root: QObject,
    expected_values: tuple[str | None, ...],
    *,
    app: QApplication,
) -> None:
    deadline = monotonic() + 2
    missing = expected_values
    while monotonic() < deadline:
        app.processEvents()
        visible_text = " ".join(
            str(item.property("text"))
            for item in root.findChildren(QObject)
            if item.metaObject().indexOfProperty("text") >= 0
            and item.property("visible")
            and item.property("text")
        )
        missing = tuple(
            value
            for value in expected_values
            if value is None or value not in visible_text
        )
        if not missing:
            return
        sleep(0.005)
    raise AssertionError(
        f"Run Monitoring QML did not expose expected values: {missing!r}"
    )
