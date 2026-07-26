from concurrent.futures import Future
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.app_context import build_app_context
from app.event_bridge import EventBridge
from app.features import (
    CancelDiagnosticTask,
    Completeness,
    DeterministicFakeRunMonitoringAdapter,
    DiagnosticCommandRejectionReason,
    DiagnosticTaskId,
    Freshness,
    LiveRunMonitoringAdapter,
    PauseDiagnosticTask,
    ResumeDiagnosticTask,
    RunLifecyclePhase,
    RunMonitoringContext,
    RunMonitoringFeature,
    RunMonitoringPresentationState,
    RunMonitoringSelection,
    SourceKind,
    StrategyRunId,
    FormalDiagnosticCampaignId,
    TaskPhase,
    ViewPhase,
)
from app.runtime_gateway import RuntimeGateway
from app.services.training_arena_service import (
    ArenaModelSpec,
    TrainingArenaConfig,
    TrainingArenaService,
)
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


class _DelayedExecutor:
    def __init__(self):
        self.pending = []

    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        self.pending.append((future, fn, args, kwargs))
        return future

    def run_next(self):
        self.run_at(0)

    def run_at(self, index):
        future, fn, args, kwargs = self.pending.pop(index)
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as error:
            future.set_exception(error)

    def shutdown(self, wait=True, *, cancel_futures=False):
        return None


class _AgentService:
    def __init__(self):
        self.actions = []

    def get(self, _agent_id):
        return object()

    def control_many(self, agent_ids, action):
        self.actions.append((tuple(agent_ids), action))


class _FailingControlAgentService(_AgentService):
    def __init__(self):
        super().__init__()
        self.fail_action = None

    def control_many(self, agent_ids, action):
        if action == self.fail_action:
            return {
                "success_ids": [],
                "failed": [
                    {
                        "agent_id": agent_ids[0],
                        "error": f"{action} failed",
                    }
                ],
            }
        super().control_many(agent_ids, action)
        return {"success_ids": list(agent_ids), "failed": []}


class _RunQueries:
    def __init__(self):
        self.error = None
        self.record = {
            "run_id": "RUN-001",
            "name": "Baseline diagnosis",
            "scenario_name": "SCENARIO-BASELINE",
            "scenario_set_id": "SCENARIO-SET-001",
            "strategy_id": "STRATEGY-MOMENTUM-001",
            "reproduction_manifest_id": "RM-001",
            "status": "running",
            "failure_reason": None,
            "started_at": NOW - timedelta(minutes=10),
            "updated_at": NOW,
            "ended_at": None,
            "sim_start_day": 1,
            "last_sim_day": 3,
            "sim_end_day": 10,
            "last_sim_dt": datetime(2029, 1, 3, 10, 30, tzinfo=UTC),
            "current_node_id": "NODE-03",
            "current_node_label": "Isolated sensitivity",
            "completed_nodes": 2,
            "total_nodes": 10,
            "task_id": "ARENA-001",
            "requested_execution": {
                "fee_model": "standard",
                "latency_ms": "10",
            },
            "effective_execution": {
                "fee_model": "stress-1.6x",
                "latency_ms": "10",
            },
            "execution_override_reasons": {
                "fee_model": "Scenario override",
            },
            "alerts": [
                {
                    "code": "spread_widening",
                    "severity": "warning",
                    "message": "Spread widening is affecting fills.",
                }
            ],
            "market_context": ["600519.SH"],
            "account_context": ["MODEL-B17"],
            "position_context": ["600519.SH +100"],
            "order_context": ["ORD-001 filled"],
            "fill_context": ["FILL-001 100 @ 1500.00"],
        }

    def get_run_monitoring_snapshot(self, run_id):
        if self.error is not None:
            raise self.error
        if run_id != self.record["run_id"]:
            return None
        return dict(self.record)


class _FailingDiagnosticTasks:
    def get_arena(self, _task_id):
        return {"status": "RUNNING"}

    def pause_arena(self, _task_id):
        raise RuntimeError("SECRET-INTERNAL-FAILURE")


def _selected_context():
    return RunMonitoringContext.for_run(
        RunMonitoringSelection(
            campaign_id=FormalDiagnosticCampaignId("FDC-001"),
            run_id=StrategyRunId("RUN-001"),
        )
    )


def _live_adapter():
    queries = _RunQueries()
    gateway = RuntimeGateway()
    gateway._queries = queries
    bridge = EventBridge(subscribe_backend=False)
    agents = _AgentService()
    tasks = TrainingArenaService(
        agent_service=agents,
        session_factory=None,
    )
    tasks.create_arena(
        TrainingArenaConfig(
            arena_id="ARENA-001",
            model_specs=[
                ArenaModelSpec(
                    agent_id="MODEL-B17",
                    model_id="momentum-v1",
                )
            ],
        )
    )
    tasks.start_arena("ARENA-001", episode_id="EP-001")
    adapter = LiveRunMonitoringAdapter(
        runtime_gateway=gateway,
        event_bridge=bridge,
        diagnostic_tasks=tasks,
        clock=lambda: NOW,
        executor=_DirectExecutor(),
    )
    return adapter, bridge, queries


@pytest.fixture(params=("fake", "live"))
def run_monitoring_adapter(request):
    context = _selected_context()
    if request.param == "fake":
        adapter = DeterministicFakeRunMonitoringAdapter(clock=lambda: NOW)
        adapter.advance_to_running(context)
        yield adapter, context, None, None
        adapter.close()
        return

    adapter, bridge, queries = _live_adapter()
    yield adapter, context, bridge, queries
    adapter.close()


def test_fake_and_live_adapters_share_the_complete_wave1_contract(
    run_monitoring_adapter,
):
    adapter, context, _bridge, _queries = run_monitoring_adapter

    state = adapter.snapshot(context)

    assert isinstance(adapter, RunMonitoringFeature)
    assert state.source.kind in {
        SourceKind.DETERMINISTIC_FAKE,
        SourceKind.LIVE_RUNTIME,
    }
    assert state.phase is ViewPhase.READY
    assert state.presentation is RunMonitoringPresentationState.ACTIVE
    assert state.freshness is Freshness.FRESH
    assert state.completeness is Completeness.COMPLETE
    assert state.last_reliable_data is not None
    data = state.last_reliable_data
    assert data.selection == context.selection
    assert data.strategy_id.value
    assert data.market_scenario_id.value
    assert data.scenario_set_id.value
    assert data.reproduction_manifest_id.value
    assert data.lifecycle is RunLifecyclePhase.RUNNING
    assert data.terminal_outcome is None
    assert data.progress.current_node_id == "NODE-03"
    assert data.progress.completed == 2
    assert data.progress.total == 10
    assert data.simulation_time.instant != data.wall_time.observed_at
    assert data.execution_assumptions[0].requested_value
    assert any(
        assumption.override_reason
        for assumption in data.execution_assumptions
    )
    assert data.alerts[0].code == "spread_widening"
    assert data.context.market
    assert data.context.account
    assert data.context.positions
    assert data.context.orders
    assert data.context.fills
    assert data.capabilities.can_pause is True
    assert data.capabilities.can_resume is False
    assert data.capabilities.can_cancel is True

    values = list(_walk_values(state))
    assert not any(isinstance(value, (dict, list, set, bytearray)) for value in values)
    assert not any(
        type(value).__module__.startswith("PySide6")
        or type(value).__name__ in {
            "RuntimeGateway",
            "EventBridge",
            "SimulationRun",
        }
        for value in values
    )


def test_fake_and_live_adapters_apply_revision_checked_diagnostic_commands(
    run_monitoring_adapter,
):
    adapter, context, _bridge, _queries = run_monitoring_adapter
    state = adapter.snapshot(context)
    data = state.last_reliable_data
    assert data is not None

    stale = adapter.pause_diagnostic_task(
        PauseDiagnosticTask(
            target_id=data.task_id,
            expected_revision=state.revision + 10,
        )
    )
    accepted = adapter.pause_diagnostic_task(
        PauseDiagnosticTask(
            target_id=data.task_id,
            expected_revision=state.revision,
        )
    )

    assert stale.accepted is False
    assert (
        stale.rejection_reason
        is DiagnosticCommandRejectionReason.STALE_EXPECTED_REVISION
    )
    assert stale.task is None
    assert accepted.accepted is True
    assert accepted.rejection_reason is None
    assert accepted.task is not None
    assert accepted.task.target_id is data.task_id
    assert accepted.task.phase in {
        TaskPhase.QUEUED,
        TaskPhase.RUNNING,
        TaskPhase.COMPLETED,
    }
    if accepted.task.phase is TaskPhase.COMPLETED:
        assert accepted.task.result == "diagnostic_task_paused"
    assert 0.0 <= accepted.task.progress <= 1.0
    assert accepted.task.cancelable is False

    paused = adapter.snapshot(context)
    paused_data = paused.last_reliable_data
    assert paused_data is not None
    assert paused.revision > state.revision
    assert paused_data.lifecycle is RunLifecyclePhase.PAUSED
    assert paused_data.capabilities.can_pause is False
    assert paused_data.capabilities.can_resume is True

    resumed = adapter.resume_diagnostic_task(
        ResumeDiagnosticTask(
            target_id=paused_data.task_id,
            expected_revision=paused.revision,
        )
    )
    assert resumed.accepted is True

    running = adapter.snapshot(context)
    running_data = running.last_reliable_data
    assert running_data is not None
    canceled = adapter.cancel_diagnostic_task(
        CancelDiagnosticTask(
            target_id=running_data.task_id,
            expected_revision=running.revision,
        )
    )
    assert canceled.accepted is True
    terminal = adapter.snapshot(context)
    terminal_data = terminal.last_reliable_data
    assert terminal_data is not None
    assert terminal_data.lifecycle is RunLifecyclePhase.CANCELED
    assert terminal.presentation is RunMonitoringPresentationState.TERMINAL


def test_fake_and_live_adapters_share_subscription_and_close_lifecycle(
    run_monitoring_adapter,
):
    adapter, context, bridge, queries = run_monitoring_adapter
    observed = []
    subscription = adapter.subscribe(context, observed.append)
    delivered = len(observed)

    subscription.dispose()
    subscription.dispose()
    if bridge is None:
        adapter.advance_to_running(context)
    else:
        queries.record["current_node_id"] = "NODE-AFTER-DISPOSE"
        bridge.on_snapshot(
            {
                "run_id": "RUN-001",
                "symbol": "600519.SH",
            }
        )
        bridge.flush(force=True)

    assert len(observed) == delivered
    adapter.close()
    adapter.close()
    with pytest.raises(RuntimeError, match="closed"):
        adapter.snapshot(context)


def test_live_adapter_consumes_one_eventbridge_batch_as_one_new_revision():
    adapter, bridge, queries = _live_adapter()
    context = _selected_context()
    observed = []
    subscription = adapter.subscribe(context, observed.append)
    initial_revision = observed[-1].revision
    queries.record["last_sim_day"] = 4
    queries.record["completed_nodes"] = 3
    queries.record["current_node_id"] = "NODE-04"

    for index in range(20):
        bridge.on_snapshot(
            {
                "run_id": "RUN-001",
                "symbol": "600519.SH",
                "last": 1500.0 + index,
            }
        )
    bridge.flush(force=True)

    assert len(observed) == 2
    assert observed[-1].revision == initial_revision + 1
    assert observed[-1].last_reliable_data.progress.current_node_id == "NODE-04"

    subscription.dispose()
    queries.record["current_node_id"] = "NODE-05"
    bridge.on_snapshot({"run_id": "RUN-001", "symbol": "600519.SH"})
    bridge.flush(force=True)
    assert len(observed) == 2
    adapter.close()


def test_live_adapter_derives_freshness_and_retains_data_on_query_failure():
    adapter, bridge, queries = _live_adapter()
    context = _selected_context()
    queries.record["updated_at"] = NOW - timedelta(seconds=10)

    stale = adapter.snapshot(context)

    assert stale.freshness is Freshness.STALE
    assert stale.phase is ViewPhase.DEGRADED
    assert stale.age == timedelta(seconds=10)
    assert stale.freshness_threshold == timedelta(seconds=5)
    assert stale.last_reliable_data is not None

    queries.record["updated_at"] = NOW
    bridge.on_snapshot({"run_id": "RUN-001", "symbol": "600519.SH"})
    bridge.flush(force=True)
    fresh = adapter.snapshot(context)
    assert fresh.freshness is Freshness.FRESH
    queries.error = RuntimeError("database offline")
    bridge.on_snapshot({"run_id": "RUN-001", "symbol": "600519.SH"})
    bridge.flush(force=True)

    degraded = adapter.snapshot(context)

    assert degraded.revision == fresh.revision + 1
    assert degraded.phase is ViewPhase.DEGRADED
    assert degraded.freshness is Freshness.STALE
    assert degraded.last_reliable_data == fresh.last_reliable_data
    assert degraded.presentation is RunMonitoringPresentationState.ACTIVE
    assert degraded.error is not None
    assert degraded.error.code == "run_monitoring_query_failed"
    adapter.close()


def test_live_adapter_maps_the_real_runtime_query_persistence_implementation(
    tmp_path,
    monkeypatch,
):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'run-monitoring.sqlite3'}",
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
    session = isolated_session()
    try:
        session.add(
            SimulationRun(
                run_id="RUN-001",
                name="Persisted baseline diagnosis",
                scenario_name="SCENARIO-PERSISTED",
                run_type="diagnostic",
                status="running",
                started_at=NOW - timedelta(minutes=8),
                updated_at=NOW,
                sim_start_day=1,
                last_sim_day=4,
                sim_end_day=12,
                last_sim_dt=datetime(2029, 1, 4, 10, 30),
                config_version="RM-PERSISTED",
                environment_tag="SCENARIO-SET-PERSISTED",
            )
        )
        session.add(
            AgentBinding(
                agent_name="MODEL-B17",
                agent_type="MODEL",
                account_id="ACCOUNT-B17",
                run_id="RUN-001",
                meta=json.dumps(
                    {
                        "strategy": "STRATEGY-PERSISTED",
                        "diagnostic_task_id": "ARENA-001",
                        "reproduction_manifest_id": "RM-PERSISTED",
                        "current_node_id": "NODE-04",
                        "current_node_label": "Persisted sensitivity",
                        "completed_nodes": 3,
                        "total_nodes": 12,
                        "requested_execution": {
                            "fee_model": "standard",
                        },
                        "effective_execution": {
                            "fee_model": "stress-1.6x",
                        },
                        "execution_override_reasons": {
                            "fee_model": "Scenario override",
                        },
                    }
                ),
            )
        )
        session.commit()
    finally:
        session.close()

    gateway = RuntimeGateway()
    gateway._queries = RuntimeQueryService.__new__(RuntimeQueryService)
    bridge = EventBridge(subscribe_backend=False)
    agents = _AgentService()
    tasks = TrainingArenaService(
        agent_service=agents,
        session_factory=None,
    )
    tasks.create_arena(
        TrainingArenaConfig(
            arena_id="ARENA-001",
            model_specs=[
                ArenaModelSpec(
                    agent_id="MODEL-B17",
                    model_id="momentum-v1",
                )
            ],
        )
    )
    tasks.start_arena("ARENA-001", episode_id="EP-001")
    adapter = LiveRunMonitoringAdapter(
        runtime_gateway=gateway,
        event_bridge=bridge,
        diagnostic_tasks=tasks,
        clock=lambda: NOW,
        executor=_DirectExecutor(),
    )

    state = adapter.snapshot(_selected_context())

    assert state.source.kind is SourceKind.LIVE_RUNTIME
    assert state.presentation is RunMonitoringPresentationState.ACTIVE
    assert state.last_reliable_data is not None
    assert (
        state.last_reliable_data.strategy_id.value
        == "STRATEGY-PERSISTED"
    )
    assert (
        state.last_reliable_data.market_scenario_id.value
        == "SCENARIO-PERSISTED"
    )
    assert (
        state.last_reliable_data.reproduction_manifest_id.value
        == "RM-PERSISTED"
    )
    assert state.last_reliable_data.progress.current_node_id == "NODE-04"
    assert state.last_reliable_data.simulation_time.sim_day == 4
    assert state.last_reliable_data.context.account == (
        "MODEL-B17 · STRATEGY-PERSISTED · ACCOUNT-B17",
    )
    assert state.last_reliable_data.execution_assumptions[0].override_reason
    adapter.close()
    engine.dispose()


def test_missing_live_identities_and_task_are_explicitly_partial():
    queries = _RunQueries()
    for field in (
        "strategy_id",
        "scenario_name",
        "scenario_set_id",
        "reproduction_manifest_id",
        "task_id",
    ):
        queries.record[field] = None
    gateway = RuntimeGateway()
    gateway._queries = queries
    bridge = EventBridge(subscribe_backend=False)
    adapter = LiveRunMonitoringAdapter(
        runtime_gateway=gateway,
        event_bridge=bridge,
        clock=lambda: NOW,
        executor=_DirectExecutor(),
    )

    state = adapter.snapshot(_selected_context())

    assert state.completeness is Completeness.PARTIAL
    assert state.last_reliable_data is not None
    assert state.last_reliable_data.strategy_id is None
    assert state.last_reliable_data.market_scenario_id is None
    assert state.last_reliable_data.scenario_set_id is None
    assert state.last_reliable_data.reproduction_manifest_id is None
    assert state.last_reliable_data.task_id is None
    assert state.last_reliable_data.capabilities.can_pause is False
    assert state.last_reliable_data.capabilities.can_resume is False
    assert state.last_reliable_data.capabilities.can_cancel is False
    adapter.close()


def test_live_adapter_reports_async_command_failure_without_leaking_details():
    queries = _RunQueries()
    gateway = RuntimeGateway()
    gateway._queries = queries
    bridge = EventBridge(subscribe_backend=False)
    adapter = LiveRunMonitoringAdapter(
        runtime_gateway=gateway,
        event_bridge=bridge,
        diagnostic_tasks=_FailingDiagnosticTasks(),
        clock=lambda: NOW,
        executor=_DirectExecutor(),
    )
    context = _selected_context()
    running = adapter.snapshot(context)
    data = running.last_reliable_data
    assert data is not None

    accepted = adapter.pause_diagnostic_task(
        PauseDiagnosticTask(
            target_id=data.task_id,
            expected_revision=running.revision,
        )
    )
    failed = adapter.snapshot(context)

    assert accepted.accepted is True
    assert accepted.task is not None
    assert accepted.task.identity.value.startswith("LIVE-TASK-")
    assert failed.phase is ViewPhase.DEGRADED
    assert failed.last_reliable_data is not None
    task = failed.last_reliable_data.active_task
    assert task is not None
    assert task.identity == accepted.task.identity
    assert task.target_id == data.task_id
    assert task.phase is TaskPhase.FAILED
    assert task.progress == 1.0
    assert task.result is None
    assert task.cancelable is False
    assert task.error is not None
    assert task.error.code == "diagnostic_task_pause_failed"
    assert task.error.message == "The diagnostic task action failed."
    assert "SECRET" not in task.error.message
    adapter.close()


def test_live_adapter_rejects_a_second_command_while_task_handle_is_in_flight():
    queries = _RunQueries()
    gateway = RuntimeGateway()
    gateway._queries = queries
    bridge = EventBridge(subscribe_backend=False)
    agents = _AgentService()
    tasks = TrainingArenaService(
        agent_service=agents,
        session_factory=None,
    )
    tasks.create_arena(
        TrainingArenaConfig(
            arena_id="ARENA-001",
            model_specs=[
                ArenaModelSpec(
                    agent_id="MODEL-B17",
                    model_id="momentum-v1",
                )
            ],
        )
    )
    tasks.start_arena("ARENA-001", episode_id="EP-001")
    executor = _DelayedExecutor()
    adapter = LiveRunMonitoringAdapter(
        runtime_gateway=gateway,
        event_bridge=bridge,
        diagnostic_tasks=tasks,
        clock=lambda: NOW,
        executor=executor,
    )
    context = _selected_context()
    running = adapter.snapshot(context)
    data = running.last_reliable_data
    assert data is not None
    assert data.task_id is not None

    first = adapter.pause_diagnostic_task(
        PauseDiagnosticTask(
            target_id=data.task_id,
            expected_revision=running.revision,
        )
    )
    queued = adapter.snapshot(context)
    second = adapter.pause_diagnostic_task(
        PauseDiagnosticTask(
            target_id=data.task_id,
            expected_revision=queued.revision,
        )
    )

    assert first.accepted is True
    assert first.task is not None
    assert queued.last_reliable_data is not None
    assert queued.last_reliable_data.active_task == first.task
    assert queued.last_reliable_data.capabilities.can_pause is False
    assert queued.last_reliable_data.capabilities.can_resume is False
    assert queued.last_reliable_data.capabilities.can_cancel is False
    assert second.accepted is False
    assert second.rejection_reason is (
        DiagnosticCommandRejectionReason.UNAVAILABLE_CAPABILITY
    )
    queries.record["current_node_id"] = "NODE-DURING-TASK"
    bridge.on_snapshot({"run_id": "RUN-001", "symbol": "600519.SH"})
    bridge.flush(force=True)
    executor.run_at(1)
    refreshed = adapter.snapshot(context)
    assert refreshed.last_reliable_data is not None
    assert refreshed.last_reliable_data.active_task == first.task
    assert refreshed.last_reliable_data.capabilities.can_pause is False
    assert refreshed.last_reliable_data.capabilities.can_resume is False
    assert refreshed.last_reliable_data.capabilities.can_cancel is False
    executor.run_next()
    completed = adapter.snapshot(context)
    assert completed.last_reliable_data is not None
    assert completed.last_reliable_data.active_task is not None
    assert (
        completed.last_reliable_data.active_task.identity
        == first.task.identity
    )
    assert completed.last_reliable_data.active_task.phase is TaskPhase.COMPLETED
    adapter.close()


def test_snapshot_returns_the_canonical_runtime_state_when_age_refresh_races(
    monkeypatch,
):
    queries = _RunQueries()
    gateway = RuntimeGateway()
    gateway._queries = queries
    bridge = EventBridge(subscribe_backend=False)
    clock = [NOW]
    adapter = LiveRunMonitoringAdapter(
        runtime_gateway=gateway,
        event_bridge=bridge,
        clock=lambda: clock[0],
        executor=_DirectExecutor(),
    )
    context = _selected_context()
    initial = adapter.snapshot(context)
    assert initial.revision == 1
    original_store = adapter._store_and_notify
    raced = False

    def _race_with_terminal_state(target_context, aged_candidate):
        nonlocal raced
        if not raced:
            raced = True
            queries.record["status"] = "completed"
            queries.record["updated_at"] = clock[0]
            queries.record["current_node_id"] = "NODE-TERMINAL"
            terminal = adapter._read_state(target_context, revision=2)
            original_store(target_context, terminal)
        return original_store(target_context, aged_candidate)

    monkeypatch.setattr(
        adapter,
        "_store_and_notify",
        _race_with_terminal_state,
    )
    clock[0] = NOW + timedelta(seconds=10)

    returned = adapter.snapshot(context)
    canonical = adapter._states[context]

    assert returned is canonical
    assert returned.revision == 2
    assert returned.presentation is RunMonitoringPresentationState.TERMINAL
    assert returned.last_reliable_data is not None
    assert returned.last_reliable_data.progress.current_node_id == "NODE-TERMINAL"
    adapter.close()


def test_training_arena_diagnostic_control_failure_does_not_advance_lifecycle():
    agents = _FailingControlAgentService()
    tasks = TrainingArenaService(
        agent_service=agents,
        session_factory=None,
    )
    tasks.create_arena(
        TrainingArenaConfig(
            arena_id="ARENA-STRICT",
            model_specs=[
                ArenaModelSpec(
                    agent_id="MODEL-STRICT",
                    model_id="momentum-v1",
                )
            ],
        )
    )
    tasks.start_arena("ARENA-STRICT", episode_id="EP-STRICT")
    agents.fail_action = "pause"

    with pytest.raises(RuntimeError, match="pause failed"):
        tasks.pause_arena("ARENA-STRICT")

    assert tasks.get_arena("ARENA-STRICT")["status"] == "RUNNING"


def test_campaign_only_context_is_valid_and_never_queries_or_launches_a_run(
    tmp_path,
    monkeypatch,
):
    context = RunMonitoringContext.for_campaign(
        FormalDiagnosticCampaignId("FDC-CAMPAIGN-ONLY")
    )
    queries = _RunQueries()
    queries.error = AssertionError("campaign-only context queried a run")
    gateway = RuntimeGateway()
    gateway._queries = queries
    adapter = LiveRunMonitoringAdapter(
        runtime_gateway=gateway,
        event_bridge=EventBridge(subscribe_backend=False),
        clock=lambda: NOW,
        executor=_DirectExecutor(),
    )

    state = adapter.snapshot(context)

    assert state.presentation is RunMonitoringPresentationState.EMPTY
    assert state.context.selection is not None
    assert state.context.selection.campaign_id.value == "FDC-CAMPAIGN-ONLY"
    assert state.context.selection.run_id is None
    monkeypatch.setenv(
        "STOCKSIM_FRONTEND_V2_CAMPAIGN_ID",
        "FDC-CAMPAIGN-ONLY",
    )
    monkeypatch.delenv("STOCKSIM_FRONTEND_V2_RUN_ID", raising=False)
    composed = build_app_context(
        settings_path=str(tmp_path / "campaign-only.json"),
        run_monitoring_mode="fake",
        event_bridge=EventBridge(subscribe_backend=False),
    )
    assert composed.run_monitoring_context == context
    adapter.close()
    composed.run_monitoring_feature.close()


def test_live_adapter_never_normalizes_an_unavailable_query_source_to_empty():
    gateway = RuntimeGateway()
    gateway._queries = None
    bridge = EventBridge(subscribe_backend=False)
    adapter = LiveRunMonitoringAdapter(
        runtime_gateway=gateway,
        event_bridge=bridge,
        clock=lambda: NOW,
        executor=_DirectExecutor(),
    )

    state = adapter.snapshot(_selected_context())

    assert state.presentation is RunMonitoringPresentationState.DISCONNECTED
    assert state.phase is ViewPhase.FAILED
    assert state.freshness is Freshness.DISCONNECTED
    assert state.last_reliable_data is None
    assert state.error is not None
    assert state.error.code == "run_monitoring_query_failed"
    adapter.close()


def test_external_interface_has_no_launch_manual_order_or_generic_dispatch():
    public_interface = {
        name
        for name in RunMonitoringFeature.__dict__
        if not name.startswith("_")
    }

    assert public_interface == {
        "interface_version",
        "snapshot",
        "subscribe",
        "pause_diagnostic_task",
        "resume_diagnostic_task",
        "cancel_diagnostic_task",
        "close",
    }
    forbidden = (
        "start",
        "launch",
        "submit_order",
        "cancel_order",
        "replace_order",
        "bulk_order",
        "buy",
        "sell",
        "dispatch",
    )
    normalized = " ".join(public_interface).casefold()
    assert not any(name in normalized for name in forbidden)


def test_app_context_selects_live_or_fake_and_preserves_existing_route_identity(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        "STOCKSIM_FRONTEND_V2_CAMPAIGN_ID",
        "FDC-001",
    )
    monkeypatch.setenv(
        "STOCKSIM_FRONTEND_V2_RUN_ID",
        "RUN-001",
    )
    bridge = EventBridge(subscribe_backend=False)

    fake_context = build_app_context(
        settings_path=str(tmp_path / "fake-settings.json"),
        run_monitoring_mode="fake",
        event_bridge=bridge,
    )
    live_context = build_app_context(
        settings_path=str(tmp_path / "live-settings.json"),
        run_monitoring_mode="live",
        event_bridge=bridge,
    )

    assert isinstance(
        fake_context.run_monitoring_feature,
        DeterministicFakeRunMonitoringAdapter,
    )
    assert isinstance(
        live_context.run_monitoring_feature,
        LiveRunMonitoringAdapter,
    )
    assert (
        fake_context.run_monitoring_context.selection.campaign_id.value
        == "FDC-001"
    )
    assert (
        fake_context.run_monitoring_context.selection.run_id.value
        == "RUN-001"
    )
    assert (
        live_context.run_monitoring_context
        == fake_context.run_monitoring_context
    )

    fake_context.run_monitoring_feature.close()
    live_context.run_monitoring_feature.close()


def test_frontend_v2_composition_never_creates_or_launches_a_run(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("STOCKSIM_FRONTEND_V2", "1")
    monkeypatch.setenv(
        "STOCKSIM_FRONTEND_V2_CAMPAIGN_ID",
        "FDC-EXISTING",
    )
    monkeypatch.setenv(
        "STOCKSIM_FRONTEND_V2_RUN_ID",
        "RUN-EXISTING",
    )

    def _unexpected_launch(_self):
        raise AssertionError("Frontend V2 attempted to create a desktop run")

    monkeypatch.setattr(
        RuntimeGateway,
        "ensure_desktop_run",
        _unexpected_launch,
    )

    context = build_app_context(
        settings_path=str(tmp_path / "settings.json"),
        run_monitoring_mode="fake",
        event_bridge=EventBridge(subscribe_backend=False),
    )

    assert context.run_monitoring_context.selection.run_id.value == "RUN-EXISTING"
    context.run_monitoring_feature.close()


def test_diagnostic_command_rejections_are_stable_and_feature_specific():
    context = _selected_context()
    adapter = DeterministicFakeRunMonitoringAdapter(clock=lambda: NOW)
    running = adapter.advance_to_running(context)
    data = running.last_reliable_data
    assert data is not None

    unavailable = adapter.pause_diagnostic_task(
        PauseDiagnosticTask(
            target_id=DiagnosticTaskId("OTHER-TASK"),
            expected_revision=running.revision,
        )
    )
    paused = adapter.pause_diagnostic_task(
        PauseDiagnosticTask(
            target_id=data.task_id,
            expected_revision=running.revision,
        )
    )
    paused_state = adapter.snapshot(context)
    invalid_phase = adapter.pause_diagnostic_task(
        PauseDiagnosticTask(
            target_id=data.task_id,
            expected_revision=paused_state.revision,
        )
    )
    adapter.advance_to_disconnected(context)
    disconnected_state = adapter.snapshot(context)
    disconnected = adapter.resume_diagnostic_task(
        ResumeDiagnosticTask(
            target_id=data.task_id,
            expected_revision=disconnected_state.revision,
        )
    )
    fresh_again = adapter.advance_to_running(context)
    fresh_data = fresh_again.last_reliable_data
    assert fresh_data is not None
    canceled = adapter.cancel_diagnostic_task(
        CancelDiagnosticTask(
            target_id=fresh_data.task_id,
            expected_revision=fresh_again.revision,
        )
    )
    canceled_state = adapter.snapshot(context)
    non_cancelable = adapter.cancel_diagnostic_task(
        CancelDiagnosticTask(
            target_id=fresh_data.task_id,
            expected_revision=canceled_state.revision,
        )
    )

    assert unavailable.rejection_reason is (
        DiagnosticCommandRejectionReason.UNAVAILABLE_CAPABILITY
    )
    assert paused.accepted is True
    assert invalid_phase.rejection_reason is (
        DiagnosticCommandRejectionReason.INVALID_LIFECYCLE_PHASE
    )
    assert disconnected.rejection_reason is (
        DiagnosticCommandRejectionReason.DISCONNECTED_SOURCE
    )
    assert canceled.accepted is True
    assert non_cancelable.rejection_reason is (
        DiagnosticCommandRejectionReason.NON_CANCELABLE_TASK
    )
    adapter.close()


def _walk_values(value):
    yield value
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            yield from _walk_values(getattr(value, field.name))
    elif isinstance(value, tuple):
        for item in value:
            yield from _walk_values(item)
