import os
from dataclasses import replace
from datetime import timedelta
from threading import Event, Thread

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtWidgets import QApplication

import app.features.live_run_monitoring as live_run_monitoring_module
from app.event_bridge import (
    EventBridge,
    EventBridgeBatch,
    EventBridgeConnectionPhase,
    EventBridgeGenerationId,
)
from app.features import (
    Completeness,
    DeterministicFakeRunMonitoringAdapter,
    DiagnosticCommandRejectionReason,
    DiagnosticTaskId,
    Freshness,
    LiveRunMonitoringAdapter,
    PauseDiagnosticTask,
    RunLifecyclePhase,
    RunMonitoringContext,
    RunMonitoringPresentationState,
    TerminalOutcome,
    ViewPhase,
)
from app.ui.journey_workspace import RunMonitoringQtAdapter
from tests.frontend.contract.test_run_monitoring_feature_wave1_contract import (
    NOW,
    _DelayedExecutor,
    _DirectExecutor,
    _RunQueries,
    _selected_context,
)
from tests.frontend.strategy_diagnostics_v1_test_support import (
    DictionaryFixtureApplicationReadModel,
)


class _TrackingExecutor(_DirectExecutor):
    def __init__(self):
        self.submissions = 0
        self.shutdown_calls = []

    def submit(self, fn, /, *args, **kwargs):
        self.submissions += 1
        return super().submit(fn, *args, **kwargs)

    def shutdown(self, wait=True, *, cancel_futures=False):
        self.shutdown_calls.append((wait, cancel_futures))


def _live_adapter(*, executor=None, use_owned_executor=False):
    queries = _RunQueries()
    bridge = EventBridge(subscribe_backend=False)
    adapter_options = {
        "application_read_model": DictionaryFixtureApplicationReadModel(queries),
        "event_bridge": bridge,
        "clock": lambda: NOW,
    }
    if not use_owned_executor:
        adapter_options["executor"] = executor or _DirectExecutor()
    adapter = LiveRunMonitoringAdapter(
        **adapter_options,
    )
    return adapter, bridge, queries


def _app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(params=("fake", "live"))
def recovery_adapter(request):
    context = _selected_context()
    if request.param == "fake":
        adapter = DeterministicFakeRunMonitoringAdapter(clock=lambda: NOW)
        adapter.advance_to_running(context)

        def disconnect():
            adapter.advance_to_disconnected(context)

        def reconnect():
            adapter.advance_to_reconnected(context)

        yield adapter, context, disconnect, reconnect
        adapter.close()
        return

    adapter, bridge, queries = _live_adapter()
    adapter.snapshot(context)

    def disconnect():
        bridge.mark_disconnected()

    def reconnect():
        bridge.mark_reconnected()
        queries.record["updated_at"] = NOW
        bridge.on_snapshot(
            {"run_id": "RUN-001", "symbol": "600519.SH"},
            generation=bridge.connection_generation,
        )
        bridge.flush(force=True)

    yield adapter, context, disconnect, reconnect
    adapter.close()


def test_eventbridge_batches_and_connection_state_have_strong_generations():
    bridge = EventBridge(subscribe_backend=False)
    batches = []
    connections = []
    bridge.subscribe_batches(batches.append)
    bridge.subscribe_connection_state(connections.append)

    bridge.on_snapshot({"run_id": "RUN-001", "symbol": "AAA"})
    bridge.flush(force=True)
    bridge.mark_disconnected()
    bridge.mark_reconnected()
    bridge.on_snapshot(
        {
            "run_id": "RUN-001",
            "symbol": "AAA",
            "status": "completed",
        },
        generation=bridge.connection_generation,
    )
    bridge.flush(force=True)

    assert isinstance(batches[0], EventBridgeBatch)
    assert batches[0].generation == EventBridgeGenerationId(1)
    assert batches[0].terminal is False
    assert batches[1].generation == EventBridgeGenerationId(2)
    assert batches[1].terminal is True
    terminal_phase = batches[1].terminal_phase_for("RUN-001")
    assert terminal_phase is not None
    assert terminal_phase.value == "completed"
    assert connections[0].phase is EventBridgeConnectionPhase.DISCONNECTED
    assert connections[0].generation == EventBridgeGenerationId(1)
    assert connections[1].phase is EventBridgeConnectionPhase.CONNECTED
    assert connections[1].generation == EventBridgeGenerationId(2)


def test_eventbridge_connection_states_have_a_monotonic_sequence():
    bridge = EventBridge(subscribe_backend=False)
    states = []
    dispose = bridge.subscribe_connection_state(
        states.append,
        replay_current=True,
    )
    bridge.mark_disconnected()

    assert [state.phase for state in states] == [
        EventBridgeConnectionPhase.CONNECTED,
        EventBridgeConnectionPhase.DISCONNECTED,
    ]
    assert [state.sequence.value for state in states] == [1, 2]
    dispose()


def test_fake_and_live_recovery_retains_data_and_never_flashes_empty(
    recovery_adapter,
):
    adapter, context, disconnect, reconnect = recovery_adapter
    initial = adapter.snapshot(context)
    initial_data = initial.last_reliable_data
    assert initial_data is not None
    initial_generation = initial.source.generation
    observed = []
    subscription = adapter.subscribe(context, observed.append)

    disconnect()
    degraded = adapter.snapshot(context)

    assert degraded.revision > initial.revision
    assert degraded.phase is ViewPhase.DEGRADED
    assert degraded.freshness in {Freshness.STALE, Freshness.DISCONNECTED}
    assert degraded.presentation is not RunMonitoringPresentationState.EMPTY
    assert degraded.last_reliable_data == initial_data
    assert degraded.error is not None
    assert degraded.error.retryable is True

    reconnect()
    recovered = adapter.snapshot(context)

    assert recovered.revision > degraded.revision
    assert recovered.freshness is Freshness.FRESH
    assert recovered.presentation is RunMonitoringPresentationState.ACTIVE
    assert recovered.last_reliable_data is not None
    assert recovered.source.generation.value > initial_generation.value
    assert all(
        state.presentation is not RunMonitoringPresentationState.EMPTY
        for state in observed[1:]
    )
    subscription.dispose()


def test_fake_disconnect_without_prior_data_is_typed_failed():
    adapter = DeterministicFakeRunMonitoringAdapter(clock=lambda: NOW)
    context = _selected_context()
    loading = adapter.snapshot(context)

    disconnected = adapter.advance_to_disconnected(context)

    assert loading.last_reliable_data is None
    assert disconnected.phase is ViewPhase.FAILED
    assert disconnected.presentation is (RunMonitoringPresentationState.DISCONNECTED)
    assert disconnected.last_reliable_data is None
    assert disconnected.error is not None
    adapter.close()


@pytest.mark.parametrize("kind", ("fake", "live"))
def test_no_selection_disconnect_reconnect_returns_to_typed_empty(kind):
    context = RunMonitoringContext.no_selection()
    if kind == "fake":
        adapter = DeterministicFakeRunMonitoringAdapter(clock=lambda: NOW)
        initial = adapter.advance_to_empty(context)
        disconnected = adapter.advance_to_disconnected(context)
        recovered = adapter.advance_to_reconnected(context)
    else:
        adapter, bridge, _queries = _live_adapter()
        initial = adapter.snapshot(context)
        bridge.mark_disconnected()
        disconnected = adapter.snapshot(context)
        bridge.mark_reconnected()
        recovered = adapter.snapshot(context)

    assert initial.presentation is RunMonitoringPresentationState.EMPTY
    assert disconnected.presentation is (RunMonitoringPresentationState.DISCONNECTED)
    assert recovered.revision > disconnected.revision
    assert recovered.phase is ViewPhase.READY
    assert recovered.freshness is Freshness.FRESH
    assert recovered.presentation is RunMonitoringPresentationState.EMPTY
    assert recovered.error is None
    adapter.close()


def test_fake_recovery_sequences_are_deterministic_and_honest():
    adapter = DeterministicFakeRunMonitoringAdapter(clock=lambda: NOW)
    context = _selected_context()

    loading = adapter.snapshot(context)
    running = adapter.advance_to_running(context)
    stale = adapter.advance_to_stale(context)
    partial = adapter.advance_to_partial(context)
    disconnected = adapter.advance_to_disconnected(context)
    recovered = adapter.advance_to_reconnected(context)
    failed = adapter.advance_to_failed(context)
    rerunning = adapter.advance_to_running(context)
    completed = adapter.advance_to_completed(context)

    states = (
        loading,
        running,
        stale,
        partial,
        disconnected,
        recovered,
        failed,
        rerunning,
        completed,
    )
    assert [state.revision for state in states] == list(range(1, len(states) + 1))
    assert stale.freshness is Freshness.STALE
    assert stale.last_reliable_data == running.last_reliable_data
    assert partial.completeness is Completeness.PARTIAL
    assert disconnected.last_reliable_data is not None
    assert failed.phase is ViewPhase.FAILED
    assert failed.last_reliable_data is not None
    assert failed.last_reliable_data.lifecycle is RunLifecyclePhase.FAILED
    assert failed.last_reliable_data.terminal_outcome is TerminalOutcome.FAILED
    assert completed.presentation is RunMonitoringPresentationState.TERMINAL
    assert completed.last_reliable_data is not None
    assert completed.last_reliable_data.terminal_outcome is (TerminalOutcome.COMPLETED)
    adapter.close()


def test_live_adapter_quarantines_delayed_batches_from_an_old_generation():
    adapter, bridge, queries = _live_adapter()
    context = _selected_context()
    first = adapter.snapshot(context)
    old_generation = bridge.connection_generation
    bridge.mark_disconnected()
    bridge.mark_reconnected()
    new_generation = bridge.connection_generation
    queries.record["updated_at"] = NOW
    queries.record["current_node_id"] = "NODE-NEW-GENERATION"
    bridge.on_snapshot(
        {"run_id": "RUN-001", "symbol": "AAA"},
        generation=new_generation,
    )
    bridge.flush(force=True)
    accepted = adapter.snapshot(context)
    queries.record["current_node_id"] = "NODE-OLD-GENERATION"
    bridge.on_snapshot(
        {"run_id": "RUN-001", "symbol": "AAA"},
        generation=old_generation,
    )
    bridge.flush(force=True)
    after_old = adapter.snapshot(context)

    assert new_generation.value > old_generation.value
    assert accepted.revision > first.revision
    assert accepted.last_reliable_data is not None
    assert accepted.last_reliable_data.progress.current_node_id == "NODE-NEW-GENERATION"
    assert after_old == accepted
    adapter.close()


def test_live_adapter_does_not_accept_delayed_batches_while_disconnected():
    adapter, bridge, queries = _live_adapter()
    context = _selected_context()
    initial = adapter.snapshot(context)
    assert initial.last_reliable_data is not None
    initial_node = initial.last_reliable_data.progress.current_node_id

    bridge.mark_disconnected()
    disconnected = adapter.snapshot(context)
    queries.record["current_node_id"] = "NODE-DELAYED-WHILE-OFFLINE"
    bridge.on_snapshot(
        {"run_id": "RUN-001", "symbol": "AAA"},
        generation=bridge.connection_generation,
    )
    bridge.flush(force=True)
    after_delayed = adapter.snapshot(context)

    assert after_delayed == disconnected
    assert after_delayed.freshness is Freshness.DISCONNECTED
    assert after_delayed.last_reliable_data is not None
    assert after_delayed.last_reliable_data.progress.current_node_id == initial_node
    adapter.close()


def test_live_adapter_drops_a_refresh_queued_before_disconnect():
    executor = _DelayedExecutor()
    adapter, bridge, queries = _live_adapter(executor=executor)
    context = _selected_context()
    initial = adapter.snapshot(context)
    assert initial.last_reliable_data is not None
    initial_node = initial.last_reliable_data.progress.current_node_id

    queries.record["current_node_id"] = "NODE-QUEUED-BEFORE-DISCONNECT"
    bridge.on_snapshot({"run_id": "RUN-001", "symbol": "AAA"})
    bridge.flush(force=True)
    assert len(executor.pending) == 1
    bridge.mark_disconnected()
    disconnected = adapter.snapshot(context)
    executor.run_next()
    after_late_refresh = adapter.snapshot(context)

    assert after_late_refresh == disconnected
    assert after_late_refresh.freshness is Freshness.DISCONNECTED
    assert after_late_refresh.last_reliable_data is not None
    assert (
        after_late_refresh.last_reliable_data.progress.current_node_id == initial_node
    )
    adapter.close()


@pytest.mark.parametrize("query_fails", (False, True))
def test_disconnect_wins_if_a_refresh_passed_precommit_checks(query_fails):
    adapter, bridge, queries = _live_adapter()
    context = _selected_context()
    initial = adapter.snapshot(context)
    assert initial.last_reliable_data is not None
    initial_node = initial.last_reliable_data.progress.current_node_id
    refresh_at_commit = Event()
    release_refresh = Event()
    original_store = adapter._store_and_notify

    def blocked_store(target_context, state, **store_options):
        refresh_at_commit.set()
        assert release_refresh.wait(1)
        return original_store(
            target_context,
            state,
            **store_options,
        )

    adapter._store_and_notify = blocked_store
    if query_fails:
        queries.error = RuntimeError("transient query failure")
    else:
        queries.record["current_node_id"] = "NODE-RACING-DISCONNECT"

    def publish():
        bridge.on_snapshot({"run_id": "RUN-001", "symbol": "AAA"})
        bridge.flush(force=True)

    publish_thread = Thread(target=publish)
    publish_thread.start()
    assert refresh_at_commit.wait(1)
    bridge.mark_disconnected()
    disconnected = adapter.snapshot(context)
    release_refresh.set()
    publish_thread.join(1)
    after_refresh = adapter.snapshot(context)

    assert after_refresh == disconnected
    assert after_refresh.freshness is Freshness.DISCONNECTED
    assert after_refresh.last_reliable_data is not None
    assert after_refresh.last_reliable_data.progress.current_node_id == initial_node
    adapter.close()


def test_authoritative_refresh_retries_after_a_local_age_tick_wins_cas():
    adapter, bridge, queries = _live_adapter()
    context = _selected_context()
    clock = [NOW]
    adapter._clock = lambda: clock[0]
    initial = adapter.snapshot(context)
    assert initial.last_reliable_data is not None
    refresh_at_commit = Event()
    release_refresh = Event()
    original_store = adapter._store_and_notify
    blocked_once = {"value": False}

    def blocked_store(target_context, state, **store_options):
        if (
            store_options.get("expected_revision") is not None
            and not blocked_once["value"]
        ):
            blocked_once["value"] = True
            refresh_at_commit.set()
            assert release_refresh.wait(1)
        return original_store(
            target_context,
            state,
            **store_options,
        )

    adapter._store_and_notify = blocked_store
    queries.record["updated_at"] = NOW + timedelta(seconds=1)
    queries.record["current_node_id"] = "NODE-AUTHORITATIVE-NEW"

    def publish():
        bridge.on_snapshot({"run_id": "RUN-001", "symbol": "AAA"})
        bridge.flush(force=True)

    publish_thread = Thread(target=publish)
    publish_thread.start()
    assert refresh_at_commit.wait(1)
    clock[0] = NOW + timedelta(seconds=1)
    aged = adapter.snapshot(context)
    assert aged.revision == initial.revision + 1
    release_refresh.set()
    publish_thread.join(1)
    final = adapter.snapshot(context)

    assert final.revision > aged.revision
    assert final.last_reliable_data is not None
    assert final.last_reliable_data.progress.current_node_id == (
        "NODE-AUTHORITATIVE-NEW"
    )
    assert final.last_reliable_data.wall_time.observed_at == (
        NOW + timedelta(seconds=1)
    )
    adapter.close()


def test_live_snapshot_opened_while_disconnected_is_typed_not_fresh_or_empty():
    adapter, bridge, _queries = _live_adapter()
    context = _selected_context()
    bridge.mark_disconnected()

    state = adapter.snapshot(context)

    assert state.revision == 1
    assert state.phase is ViewPhase.FAILED
    assert state.presentation is RunMonitoringPresentationState.DISCONNECTED
    assert state.freshness is Freshness.DISCONNECTED
    assert state.last_reliable_data is None
    assert state.error is not None
    assert state.error.code == "run_monitoring_source_disconnected"
    adapter.close()


def test_task_command_stays_unavailable_during_connection_publish():
    adapter, bridge, _queries = _live_adapter()
    context = _selected_context()
    state = adapter.snapshot(context)
    assert state.last_reliable_data is not None
    assert state.last_reliable_data.task_id is None
    publish_entered = Event()
    release_publish = Event()
    original_publish = adapter._publish_connection_state

    def blocked_publish(*args, **kwargs):
        publish_entered.set()
        assert release_publish.wait(1)
        return original_publish(*args, **kwargs)

    adapter._publish_connection_state = blocked_publish
    disconnect_thread = Thread(target=bridge.mark_disconnected)
    disconnect_thread.start()
    assert publish_entered.wait(1)

    result = adapter.pause_diagnostic_task(
        PauseDiagnosticTask(
            target_id=DiagnosticTaskId("READ-ONLY-V1"),
            expected_revision=state.revision,
        )
    )
    release_publish.set()
    disconnect_thread.join(1)

    assert result.accepted is False
    assert result.rejection_reason is (
        DiagnosticCommandRejectionReason.UNAVAILABLE_CAPABILITY
    )
    adapter.close()


def test_live_adapter_requests_atomic_connection_state_replay(monkeypatch):
    original = EventBridge.subscribe_connection_state
    replay_requests = []

    def interleaving_subscribe(
        bridge,
        observer,
        *,
        replay_current=False,
    ):
        bridge.mark_disconnected()
        bridge.mark_reconnected()
        replay_requests.append(replay_current)
        dispose = original(bridge, observer)
        if replay_current:
            observer(bridge.connection_state)
        return dispose

    monkeypatch.setattr(
        EventBridge,
        "subscribe_connection_state",
        interleaving_subscribe,
    )
    adapter, bridge, _queries = _live_adapter()
    context = _selected_context()

    state = adapter.snapshot(context)

    assert replay_requests == [True]
    assert state.source.generation.value == bridge.connection_generation.value
    adapter.close()


def test_live_adapter_rejects_an_out_of_order_connection_replay():
    adapter, bridge, _queries = _live_adapter()
    context = _selected_context()
    adapter.snapshot(context)
    stale_connected_replay = bridge.connection_state
    bridge.mark_disconnected()
    disconnected = adapter.snapshot(context)

    adapter._on_connection_state(stale_connected_replay)

    assert adapter.snapshot(context) == disconnected
    adapter.close()


@pytest.mark.parametrize(
    ("terminal_status", "expected_lifecycle", "expected_outcome"),
    (
        (
            "completed",
            RunLifecyclePhase.COMPLETED,
            TerminalOutcome.COMPLETED,
        ),
        ("failed", RunLifecyclePhase.FAILED, TerminalOutcome.FAILED),
    ),
)
def test_live_adapter_coalesces_intermediate_batches_without_losing_terminal(
    terminal_status,
    expected_lifecycle,
    expected_outcome,
):
    executor = _DelayedExecutor()
    adapter, bridge, queries = _live_adapter(executor=executor)
    context = _selected_context()
    observed = []
    subscription = adapter.subscribe(context, observed.append)
    generation = bridge.connection_generation

    for index in range(20):
        queries.record["current_node_id"] = f"NODE-{index:02d}"
        bridge.on_snapshot(
            {"run_id": "RUN-001", "symbol": "AAA"},
            generation=generation,
        )
        bridge.flush(force=True)
    queries.record["status"] = terminal_status
    queries.record["failure_reason"] = (
        "runtime-confirmed failure" if terminal_status == "failed" else None
    )
    queries.record["current_node_id"] = "NODE-COMPLETED"
    bridge.on_snapshot(
        {
            "run_id": "RUN-001",
            "symbol": "AAA",
            "status": terminal_status,
        },
        generation=generation,
    )
    bridge.flush(force=True)

    assert len(executor.pending) == 1
    executor.run_next()
    terminal = adapter.snapshot(context)
    assert terminal.presentation is RunMonitoringPresentationState.TERMINAL
    assert terminal.last_reliable_data is not None
    assert terminal.last_reliable_data.lifecycle is expected_lifecycle
    assert terminal.last_reliable_data.terminal_outcome is expected_outcome
    assert observed[-1] == terminal
    subscription.dispose()
    adapter.close()


def test_terminal_confirmation_survives_more_than_the_initial_60ms():
    adapter, bridge, queries = _live_adapter()
    context = _selected_context()
    query_reads = {"count": 0}
    terminal_seen = Event()

    def delayed_terminal_query(run_id):
        query_reads["count"] += 1
        if run_id != queries.record["run_id"]:
            return None
        record = dict(queries.record)
        if query_reads["count"] >= 7:
            record["status"] = "completed"
            record["current_node_id"] = "NODE-CONFIRMED-AFTER-60MS"
        return record

    queries.get_run_monitoring_snapshot = delayed_terminal_query

    def observer(state):
        if state.presentation is RunMonitoringPresentationState.TERMINAL:
            terminal_seen.set()

    subscription = adapter.subscribe(context, observer)
    bridge.on_snapshot(
        {
            "run_id": "RUN-001",
            "status": "completed",
        }
    )
    bridge.flush(force=True)

    assert terminal_seen.wait(1)
    terminal = adapter.snapshot(context)
    assert query_reads["count"] >= 7
    assert terminal.presentation is RunMonitoringPresentationState.TERMINAL
    assert terminal.last_reliable_data is not None
    assert terminal.last_reliable_data.progress.current_node_id == (
        "NODE-CONFIRMED-AFTER-60MS"
    )
    subscription.dispose()
    adapter.close()


def test_terminal_phase_is_scoped_to_the_matching_run_in_a_mixed_batch():
    executor = _DelayedExecutor()
    adapter, bridge, queries = _live_adapter(executor=executor)
    context = _selected_context()
    initial = adapter.snapshot(context)
    queries.record["status"] = "running"
    queries.record["current_node_id"] = "NODE-RUN-001-CURRENT"

    bridge.on_snapshot(
        {
            "run_id": "RUN-002",
            "status": "completed",
        }
    )
    bridge.on_snapshot(
        {
            "run_id": "RUN-001",
            "status": "running",
        }
    )
    bridge.flush(force=True)
    executor.run_next()
    current = adapter.snapshot(context)

    assert current.revision > initial.revision
    assert current.presentation is RunMonitoringPresentationState.ACTIVE
    assert current.last_reliable_data is not None
    assert current.last_reliable_data.lifecycle is RunLifecyclePhase.RUNNING
    assert current.last_reliable_data.terminal_outcome is None
    adapter.close()


def test_qt_adapter_rejects_duplicate_and_lower_revisions():
    _app()
    feature = DeterministicFakeRunMonitoringAdapter(clock=lambda: NOW)
    context = _selected_context()
    running = feature.advance_to_running(context)
    adapter = RunMonitoringQtAdapter(feature, context=context)
    original_lifecycle = adapter.lifecycle
    assert adapter.sourceGenerationText == "g1"
    assert running.last_reliable_data is not None
    terminal_data = replace(
        running.last_reliable_data,
        lifecycle=RunLifecyclePhase.COMPLETED,
        terminal_outcome=TerminalOutcome.COMPLETED,
    )

    adapter._accept_state(
        adapter.mountGeneration,
        replace(
            running,
            last_reliable_data=terminal_data,
        ),
    )
    adapter._accept_state(
        adapter.mountGeneration,
        replace(
            running,
            revision=running.revision - 1,
            last_reliable_data=terminal_data,
        ),
    )

    assert adapter.lifecycle == original_lifecycle
    disconnected = feature.advance_to_disconnected(context)
    reconnected = feature.advance_to_reconnected(context)
    adapter._accept_state(adapter.mountGeneration, disconnected)
    adapter._accept_state(adapter.mountGeneration, reconnected)
    assert adapter.sourceGenerationText == "g2"
    adapter.close()
    feature.close()


def test_qt_remount_has_a_new_generation_and_rejects_old_mount_delivery():
    _app()
    feature = DeterministicFakeRunMonitoringAdapter(clock=lambda: NOW)
    context = _selected_context()
    running = feature.advance_to_running(context)
    first = RunMonitoringQtAdapter(feature, context=context)
    first_mount = first.mountGeneration
    source_generation = first.sourceGenerationText
    first.close()

    second = RunMonitoringQtAdapter(feature, context=context)
    original_lifecycle = second.lifecycle
    assert running.last_reliable_data is not None
    late_data = replace(
        running.last_reliable_data,
        lifecycle=RunLifecyclePhase.COMPLETED,
        terminal_outcome=TerminalOutcome.COMPLETED,
    )
    second._accept_state(
        first_mount,
        replace(
            running,
            revision=running.revision + 10,
            last_reliable_data=late_data,
        ),
    )

    assert second.mountGeneration != first_mount
    assert second.sourceGenerationText == source_generation
    assert second.lifecycle == original_lifecycle
    second.close()
    feature.close()


@pytest.mark.parametrize("kind", ("fake", "live"))
def test_dispose_waits_for_inflight_delivery_and_none_arrive_after_return(kind):
    context = _selected_context()
    bridge = None
    queries = None
    if kind == "fake":
        adapter = DeterministicFakeRunMonitoringAdapter(clock=lambda: NOW)
        initial = adapter.advance_to_running(context)
    else:
        adapter, bridge, queries = _live_adapter()
        initial = adapter.snapshot(context)

    observer_entered = Event()
    release_observer = Event()
    dispose_returned = Event()
    delivered_revisions = []

    def observer(state):
        delivered_revisions.append(state.revision)
        if state.revision > initial.revision:
            observer_entered.set()
            assert release_observer.wait(1)

    subscription = adapter.subscribe(context, observer)

    def publish():
        if kind == "fake":
            adapter.advance_to_stale(context)
            return
        assert bridge is not None
        assert queries is not None
        queries.record["current_node_id"] = "NODE-BLOCKED-OBSERVER"
        bridge.on_snapshot({"run_id": "RUN-001", "symbol": "AAA"})
        bridge.flush(force=True)

    publish_thread = Thread(target=publish)
    publish_thread.start()
    assert observer_entered.wait(1)

    def dispose():
        subscription.dispose()
        dispose_returned.set()

    dispose_thread = Thread(target=dispose)
    dispose_thread.start()
    assert dispose_returned.wait(0.05) is False
    release_observer.set()
    publish_thread.join(1)
    dispose_thread.join(1)
    delivered_after_dispose = tuple(delivered_revisions)

    if kind == "fake":
        adapter.advance_to_running(context)
    else:
        assert bridge is not None
        bridge.on_snapshot({"run_id": "RUN-001", "symbol": "AAA"})
        bridge.flush(force=True)

    assert dispose_returned.is_set()
    assert tuple(delivered_revisions) == delivered_after_dispose
    adapter.close()


@pytest.mark.parametrize("kind", ("fake", "live"))
def test_subscribe_never_delivers_initial_state_after_a_newer_revision(kind):
    context = _selected_context()
    bridge = None
    queries = None
    if kind == "fake":
        adapter = DeterministicFakeRunMonitoringAdapter(clock=lambda: NOW)
        initial = adapter.snapshot(context)
    else:
        adapter, bridge, queries = _live_adapter()
        initial = adapter.snapshot(context)

    initial_entered = Event()
    release_initial = Event()
    newer_delivered = Event()
    revisions = []
    subscriptions = []

    def observer(state):
        if state.revision == initial.revision:
            initial_entered.set()
            assert release_initial.wait(1)
        revisions.append(state.revision)
        if state.revision > initial.revision:
            newer_delivered.set()

    subscribe_thread = Thread(
        target=lambda: subscriptions.append(adapter.subscribe(context, observer))
    )
    subscribe_thread.start()
    assert initial_entered.wait(1)

    def publish():
        if kind == "fake":
            adapter.advance_to_running(context)
            return
        assert bridge is not None
        assert queries is not None
        queries.record["current_node_id"] = "NODE-NEWER-SUBSCRIPTION"
        bridge.on_snapshot({"run_id": "RUN-001", "symbol": "AAA"})
        bridge.flush(force=True)

    publish_thread = Thread(target=publish)
    publish_thread.start()
    assert newer_delivered.wait(0.05) is False
    release_initial.set()
    subscribe_thread.join(1)
    publish_thread.join(1)

    assert len(subscriptions) == 1
    assert revisions == [initial.revision, initial.revision + 1]
    subscriptions[0].dispose()
    adapter.close()


def test_live_subscribe_recaptures_state_updated_before_registration():
    adapter, bridge, queries = _live_adapter()
    context = _selected_context()
    initial = adapter.snapshot(context)
    snapshot_captured = Event()
    release_snapshot = Event()
    original_snapshot = adapter.snapshot
    observed = []
    subscriptions = []

    def blocked_snapshot(target_context):
        state = original_snapshot(target_context)
        snapshot_captured.set()
        assert release_snapshot.wait(1)
        return state

    adapter.snapshot = blocked_snapshot
    subscribe_thread = Thread(
        target=lambda: subscriptions.append(adapter.subscribe(context, observed.append))
    )
    subscribe_thread.start()
    assert snapshot_captured.wait(1)
    queries.record["current_node_id"] = "NODE-BEFORE-REGISTRATION"
    bridge.on_snapshot({"run_id": "RUN-001", "symbol": "AAA"})
    bridge.flush(force=True)
    canonical = adapter._states[context]
    release_snapshot.set()
    subscribe_thread.join(1)

    assert canonical.revision > initial.revision
    assert len(subscriptions) == 1
    assert observed == [canonical]
    subscriptions[0].dispose()
    adapter.close()


def test_live_close_releases_callbacks_and_suppresses_late_work():
    executor = _TrackingExecutor()
    adapter, bridge, _queries = _live_adapter(executor=executor)
    context = _selected_context()
    observed = []
    adapter.subscribe(context, observed.append)
    delivered = len(observed)

    adapter.close()
    adapter.close()
    bridge.mark_disconnected()
    bridge.on_snapshot({"run_id": "RUN-001", "symbol": "AAA"})
    bridge.flush(force=True)

    assert len(observed) == delivered
    assert executor.submissions == 0
    assert bridge._batch_observers == {}
    assert bridge._connection_observers == {}
    with pytest.raises(RuntimeError, match="closed"):
        adapter.snapshot(context)


def test_live_close_waits_for_the_owned_executor_exactly_once(monkeypatch):
    executor = _TrackingExecutor()
    monkeypatch.setattr(
        live_run_monitoring_module,
        "ThreadPoolExecutor",
        lambda **_kwargs: executor,
    )
    adapter, _bridge, _queries = _live_adapter(use_owned_executor=True)

    adapter.close()
    adapter.close()

    assert executor.shutdown_calls == [(True, True)]


def test_observer_can_close_owned_executor_without_self_joining():
    adapter, bridge, queries = _live_adapter(use_owned_executor=True)
    context = _selected_context()
    initial = adapter.snapshot(context)
    close_returned = Event()
    errors = []

    def observer(state):
        if state.revision <= initial.revision:
            return
        try:
            adapter.close()
        except Exception as error:  # noqa: BLE001 - exercising close races
            errors.append(error)
        finally:
            close_returned.set()

    adapter.subscribe(context, observer)
    queries.record["current_node_id"] = "NODE-CLOSE-FROM-OBSERVER"
    bridge.on_snapshot({"run_id": "RUN-001", "symbol": "AAA"})
    bridge.flush(force=True)

    assert close_returned.wait(1)
    executor_threads = tuple(adapter._executor._threads)
    for thread in executor_threads:
        thread.join(1)

    assert errors == []
    assert all(not thread.is_alive() for thread in executor_threads)


def test_close_cancels_pending_terminal_confirmation_timers():
    adapter, bridge, queries = _live_adapter()
    context = _selected_context()
    adapter._TERMINAL_CONFIRMATION_INTERVAL_SECONDS = 1.0
    adapter.snapshot(context)
    queries.record["status"] = "running"
    bridge.on_snapshot(
        {
            "run_id": "RUN-001",
            "status": "completed",
        }
    )
    bridge.flush(force=True)
    pending_timers = tuple(
        timer for _, timer in adapter._terminal_confirmation_timers.values()
    )
    assert len(pending_timers) == 1

    adapter.close()
    for timer in pending_timers:
        timer.join(1)

    assert adapter._terminal_confirmation_timers == {}
    assert all(not timer.is_alive() for timer in pending_timers)


def test_qt_close_is_idempotent_and_rejects_queued_or_direct_late_state():
    app = _app()
    feature = DeterministicFakeRunMonitoringAdapter(clock=lambda: NOW)
    context = _selected_context()
    feature.advance_to_running(context)
    adapter = RunMonitoringQtAdapter(feature, context=context)
    revision = adapter.revisionText

    adapter.close()
    adapter.close()
    late = feature.advance_to_completed(context)
    adapter._queue_state(late)
    adapter._accept_state(adapter.mountGeneration, late)
    app.processEvents()

    assert adapter.revisionText == revision
    feature.close()


def test_recovery_interfaces_add_no_order_or_generic_dispatch_operation():
    public = {
        name
        for name in (
            *DeterministicFakeRunMonitoringAdapter.__dict__,
            *LiveRunMonitoringAdapter.__dict__,
        )
        if not name.startswith("_")
    }
    normalized = " ".join(public).casefold()
    for forbidden in (
        "submit_order",
        "cancel_order",
        "replace_order",
        "bulk_order",
        "buy",
        "sell",
        "dispatch",
    ):
        assert forbidden not in normalized
