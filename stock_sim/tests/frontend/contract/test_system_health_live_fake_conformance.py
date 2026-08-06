from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError, dataclass
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread

import pytest

from app.event_bridge import EventBridge
from app.features import (
    DeterministicFakeSystemHealthAdapter,
    LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter,
    LiveSystemHealthAdapter,
    RuntimeHealthClassification,
    RuntimeHealthApplicationAvailability,
    RuntimeHealthApplicationError,
    RuntimeHealthApplicationErrorCode,
    RuntimeHealthApplicationObservation,
    RuntimeHealthApplicationResult,
    RuntimeHealthRecoveryPhase,
    SourceRevisionToken,
    SystemHealthContext,
    SystemHealthFeature,
    SystemHealthPresentationState,
)
from app.features.run_monitoring import Completeness, Freshness, ViewPhase
from strategy_diagnostics import create_diagnostics_application


@dataclass
class _Clock:
    now: datetime = datetime(2030, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


@dataclass
class _Harness:
    feature: SystemHealthFeature
    become_healthy: Callable[[], None]
    publish_change: Callable[[], None]
    disconnect: Callable[[], None]
    reconnect: Callable[[], None]
    fail: Callable[[], None]
    advance: Callable[[timedelta], None]


def _live_harness(*, initially_healthy: bool) -> _Harness:
    clock = _Clock()
    application = create_diagnostics_application()
    if initially_healthy:
        application.start()
    bridge = EventBridge(subscribe_backend=False)
    application_health = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        application,
        clock=clock,
    )
    failed = False

    def read_runtime_health() -> RuntimeHealthApplicationResult:
        if not failed:
            return application_health.read_runtime_health()
        return RuntimeHealthApplicationResult(
            availability=RuntimeHealthApplicationAvailability.FAILED,
            observation=None,
            source_token=None,
            observed_at=clock(),
            error=RuntimeHealthApplicationError(
                code=RuntimeHealthApplicationErrorCode.READ_FAILED,
                explanation=(
                    r"C:\secrets\runtime.exe --token super-secret SELECT users"
                ),
                retryable=True,
            ),
        )

    class _ControllableHealth:
        interface_version = application_health.interface_version

        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            return read_runtime_health()

    feature = LiveSystemHealthAdapter(
        application_health=_ControllableHealth(),
        event_bridge=bridge,
        clock=clock,
        freshness_threshold=timedelta(seconds=5),
    )

    def become_healthy() -> None:
        application.start()
        bridge.on_snapshot({"feature": "system_health"})
        bridge.flush(force=True)

    def publish_change() -> None:
        bridge.on_snapshot({"feature": "system_health"})
        bridge.flush(force=True)

    def fail() -> None:
        nonlocal failed
        failed = True
        publish_change()

    return _Harness(
        feature=feature,
        become_healthy=become_healthy,
        publish_change=publish_change,
        disconnect=lambda: bridge.mark_disconnected(),
        reconnect=lambda: bridge.mark_reconnected(),
        fail=fail,
        advance=clock.advance,
    )


def _fake_harness(*, initially_healthy: bool) -> _Harness:
    feature = DeterministicFakeSystemHealthAdapter(
        initially_healthy=initially_healthy,
        freshness_threshold=timedelta(seconds=5),
    )
    return _Harness(
        feature=feature,
        become_healthy=feature.advance_to_healthy,
        publish_change=feature.publish_authoritative_observation,
        disconnect=feature.advance_to_disconnected,
        reconnect=feature.advance_to_reconnected,
        fail=feature.advance_to_failed,
        advance=feature.advance_clock,
    )


@pytest.fixture(params=(_live_harness, _fake_harness), ids=("live", "fake"))
def harness_factory(request: pytest.FixtureRequest) -> Callable[..., _Harness]:
    return request.param


def test_live_and_fake_share_the_initial_authoritative_health_contract(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(initially_healthy=True)
    try:
        state = harness.feature.snapshot(SystemHealthContext())

        assert state.presentation is SystemHealthPresentationState.HEALTHY
        assert state.phase is ViewPhase.READY
        assert state.freshness is Freshness.FRESH
        assert state.completeness is Completeness.COMPLETE
        assert state.last_reliable_payload is state.components[0]
        assert state.components[0].classification is (
            RuntimeHealthClassification.HEALTHY
        )
        with pytest.raises(FrozenInstanceError):
            state.revision = 99  # type: ignore[misc]
    finally:
        harness.feature.close()


def test_unknown_is_never_presented_as_healthy(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(initially_healthy=False)
    try:
        state = harness.feature.snapshot(SystemHealthContext())

        assert state.presentation is SystemHealthPresentationState.UNKNOWN
        assert state.components == ()
        assert state.last_reliable_payload is None
        assert state.completeness is Completeness.UNKNOWN
        assert state.error is not None
    finally:
        harness.feature.close()


def test_connected_snapshot_rereads_the_real_diagnostics_application() -> None:
    clock = _Clock()
    application = create_diagnostics_application()
    feature = LiveSystemHealthAdapter(
        application_health=(
            LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
                application,
                clock=clock,
            )
        ),
        event_bridge=EventBridge(subscribe_backend=False),
        clock=clock,
    )
    try:
        unavailable = feature.snapshot(SystemHealthContext())
        application.start()
        healthy = feature.snapshot(SystemHealthContext())

        assert unavailable.presentation is SystemHealthPresentationState.UNKNOWN
        assert healthy.presentation is SystemHealthPresentationState.HEALTHY
        assert healthy.revision > unavailable.revision
        assert healthy.last_reliable_payload is not None
    finally:
        feature.close()


def test_disconnect_staleness_and_reconnect_retain_last_reliable_state(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(initially_healthy=True)
    observed: list = []
    subscription = harness.feature.subscribe(SystemHealthContext(), observed.append)
    try:
        reliable = observed[-1].last_reliable_payload
        harness.disconnect()
        degraded = observed[-1]
        assert degraded.presentation is SystemHealthPresentationState.DEGRADED
        assert degraded.recovery_phase is RuntimeHealthRecoveryPhase.DISCONNECTED
        assert degraded.last_reliable_payload == reliable

        harness.advance(timedelta(seconds=6))
        stale = harness.feature.snapshot(SystemHealthContext())
        assert stale.presentation is SystemHealthPresentationState.STALE
        assert stale.freshness is Freshness.STALE
        assert stale.last_reliable_payload == reliable

        harness.reconnect()
        recovered = observed[-1]
        assert any(
            state.recovery_phase is RuntimeHealthRecoveryPhase.REREADING
            for state in observed
        )
        assert recovered.recovery_phase is RuntimeHealthRecoveryPhase.RECOVERED
        assert recovered.presentation is SystemHealthPresentationState.HEALTHY
        assert recovered.last_reliable_payload is not None
        assert [state.revision for state in observed] == sorted(
            {state.revision for state in observed}
        )
    finally:
        subscription.dispose()
        harness.feature.close()


def test_subscription_dispose_and_adapter_close_are_idempotent_and_terminal(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(initially_healthy=True)
    observed: list = []
    subscription = harness.feature.subscribe(SystemHealthContext(), observed.append)
    delivered = len(observed)

    subscription.dispose()
    subscription.dispose()
    harness.publish_change()
    assert len(observed) == delivered

    harness.feature.close()
    harness.feature.close()
    harness.publish_change()
    assert len(observed) == delivered


def test_read_failure_retains_safe_degraded_then_stale_last_reliable_state(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(initially_healthy=True)
    observed: list = []
    subscription = harness.feature.subscribe(SystemHealthContext(), observed.append)
    try:
        reliable = observed[-1].last_reliable_payload
        harness.fail()
        failed = observed[-1]

        assert failed.presentation is SystemHealthPresentationState.DEGRADED
        assert failed.last_reliable_payload == reliable
        assert failed.error is not None
        exposed = failed.error.explanation.casefold()
        for forbidden in ("c:\\", "runtime.exe", "token", "secret", "select"):
            assert forbidden not in exposed

        harness.advance(timedelta(seconds=6))
        stale = harness.feature.snapshot(SystemHealthContext())
        assert stale.presentation is SystemHealthPresentationState.STALE
        assert stale.last_reliable_payload == reliable
    finally:
        subscription.dispose()
        harness.feature.close()


def test_live_adapter_rejects_batches_from_an_old_connection_generation() -> None:
    clock = _Clock()
    application = create_diagnostics_application()
    application.start()
    bridge = EventBridge(subscribe_backend=False)
    feature = LiveSystemHealthAdapter(
        application_health=(
            LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
                application,
                clock=clock,
            )
        ),
        event_bridge=bridge,
        clock=clock,
    )
    observed: list = []
    subscription = feature.subscribe(SystemHealthContext(), observed.append)
    try:
        bridge.mark_disconnected()
        bridge.mark_reconnected()
        delivered = tuple(state.revision for state in observed)

        bridge.on_snapshot({"feature": "run_monitoring"})
        bridge.flush(force=True)

        assert tuple(state.revision for state in observed) == delivered

        bridge.on_snapshot(
            {"feature": "system_health", "sequence": "old"},
            generation=1,
        )
        bridge.flush(force=True)

        assert tuple(state.revision for state in observed) == delivered
        assert observed[-1].source.generation.value == 2
    finally:
        subscription.dispose()
        feature.close()


def test_live_adapter_replays_a_disconnect_during_construction() -> None:
    class _DisconnectingBridge(EventBridge):
        replay_requested = False

        def subscribe_connection_state(
            self,
            observer,
            *,
            replay_current: bool = False,
        ):
            self.replay_requested = replay_current
            self.mark_disconnected()
            return super().subscribe_connection_state(
                observer,
                replay_current=replay_current,
            )

    clock = _Clock()
    application = create_diagnostics_application()
    application.start()
    bridge = _DisconnectingBridge(subscribe_backend=False)
    feature = LiveSystemHealthAdapter(
        application_health=(
            LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
                application,
                clock=clock,
            )
        ),
        event_bridge=bridge,
        clock=clock,
    )
    try:
        state = feature.snapshot(SystemHealthContext())

        assert bridge.replay_requested is True
        assert state.recovery_phase is RuntimeHealthRecoveryPhase.DISCONNECTED
        assert state.freshness is Freshness.DISCONNECTED
        assert state.presentation is SystemHealthPresentationState.UNAVAILABLE
    finally:
        feature.close()


def test_concurrent_healthy_then_failed_reads_preserve_last_reliable_state() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    first_read_entered = Event()
    release_first_read = Event()
    read_lock = Lock()
    read_calls = 0
    healthy_result = RuntimeHealthApplicationResult(
        availability=RuntimeHealthApplicationAvailability.READY,
        observation=RuntimeHealthApplicationObservation(
            classification=RuntimeHealthClassification.HEALTHY,
            observed_at=now,
            explanation="The application runtime is available.",
        ),
        source_token=SourceRevisionToken("0" * 64),
        observed_at=now,
        error=None,
    )
    failed_result = RuntimeHealthApplicationResult(
        availability=RuntimeHealthApplicationAvailability.FAILED,
        observation=None,
        source_token=None,
        observed_at=now,
        error=RuntimeHealthApplicationError(
            code=RuntimeHealthApplicationErrorCode.READ_FAILED,
            explanation="The authoritative Runtime Health read failed safely.",
            retryable=True,
        ),
    )

    class _ApplicationHealth:
        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            nonlocal read_calls
            with read_lock:
                read_calls += 1
                call = read_calls
            if call == 1:
                first_read_entered.set()
                release_first_read.wait(timeout=5)
                return healthy_result
            return failed_result

    feature = LiveSystemHealthAdapter(
        application_health=_ApplicationHealth(),  # type: ignore[arg-type]
        event_bridge=EventBridge(subscribe_backend=False),
        clock=lambda: now,
    )
    states = []
    errors: list[BaseException] = []

    def take_snapshot() -> None:
        try:
            states.append(feature.snapshot(SystemHealthContext()))
        except BaseException as error:  # noqa: BLE001 - preserve thread failure
            errors.append(error)

    first = Thread(target=take_snapshot)
    second = Thread(target=take_snapshot)
    second_started = False
    try:
        first.start()
        assert first_read_entered.wait(timeout=5)
        second.start()
        second_started = True
        release_first_read.set()
        first.join(timeout=5)
        second.join(timeout=5)
        assert not first.is_alive()
        assert not second.is_alive()
        assert errors == []

        stored = feature.snapshot(SystemHealthContext())
        assert len(states) == 2
        assert states[0].presentation is SystemHealthPresentationState.HEALTHY
        assert states[1].presentation is SystemHealthPresentationState.DEGRADED
        assert states[1].last_reliable_payload == states[0].components[0]
        assert [state.revision for state in states] == [1, 2]
        assert stored.revision == 3
        assert stored.last_reliable_payload == states[0].components[0]
    finally:
        release_first_read.set()
        first.join(timeout=5)
        if second_started:
            second.join(timeout=5)
        feature.close()


def test_disconnect_waits_for_an_inflight_read_and_remains_degraded() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    second_read_entered = Event()
    release_second_read = Event()
    disconnect_attempted = Event()
    read_lock = Lock()
    read_calls = 0
    healthy_result = RuntimeHealthApplicationResult(
        availability=RuntimeHealthApplicationAvailability.READY,
        observation=RuntimeHealthApplicationObservation(
            classification=RuntimeHealthClassification.HEALTHY,
            observed_at=now,
            explanation="The application runtime is available.",
        ),
        source_token=SourceRevisionToken("1" * 64),
        observed_at=now,
        error=None,
    )

    class _SlowApplicationHealth:
        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            nonlocal read_calls
            with read_lock:
                read_calls += 1
                call = read_calls
            if call == 2:
                second_read_entered.set()
                release_second_read.wait(timeout=5)
            return healthy_result

    bridge = EventBridge(subscribe_backend=False)
    feature = LiveSystemHealthAdapter(
        application_health=_SlowApplicationHealth(),  # type: ignore[arg-type]
        event_bridge=bridge,
        clock=lambda: now,
    )
    feature.snapshot(SystemHealthContext())
    reread_states = []
    errors: list[BaseException] = []

    def reread() -> None:
        try:
            reread_states.append(feature.snapshot(SystemHealthContext()))
        except BaseException as error:  # noqa: BLE001 - preserve thread failure
            errors.append(error)

    def disconnect() -> None:
        disconnect_attempted.set()
        bridge.mark_disconnected()

    reread_thread = Thread(target=reread)
    disconnect_thread = Thread(target=disconnect)
    disconnect_started = False
    try:
        reread_thread.start()
        assert second_read_entered.wait(timeout=5)
        disconnect_thread.start()
        disconnect_started = True
        assert disconnect_attempted.wait(timeout=5)
        release_second_read.set()
        reread_thread.join(timeout=5)
        disconnect_thread.join(timeout=5)
        assert not reread_thread.is_alive()
        assert not disconnect_thread.is_alive()
        assert errors == []

        disconnected = feature.snapshot(SystemHealthContext())
        assert reread_states[0].presentation is (
            SystemHealthPresentationState.HEALTHY
        )
        assert disconnected.presentation is (
            SystemHealthPresentationState.DEGRADED
        )
        assert disconnected.recovery_phase is (
            RuntimeHealthRecoveryPhase.DISCONNECTED
        )
        assert disconnected.last_reliable_payload is not None
        assert disconnected.revision > reread_states[0].revision
    finally:
        release_second_read.set()
        reread_thread.join(timeout=5)
        if disconnect_started:
            disconnect_thread.join(timeout=5)
        feature.close()
