from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from threading import Event, Lock, Thread

import pytest

from app.event_bridge import EventBridge
from app.features import (
    DiagnosticDataSourceApplicationAvailability,
    DiagnosticDataSourceApplicationError,
    DiagnosticDataSourceApplicationErrorCode,
    DiagnosticDataSourceApplicationObservation,
    DiagnosticDataSourceApplicationResult,
    DiagnosticDataSourceConnectionState,
    DiagnosticDataSourceFallbackState,
    DiagnosticDataSourceHealthClassification,
    DiagnosticDataSourceIdentity,
    DiagnosticDataSourceRecoveryPhase,
    DiagnosticDataSourceRevision,
    DiagnosticDataSourceScope,
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
from strategy_diagnostics import (
    AdmissionCheck,
    HistoricalSegmentSelection,
    HistoricalSourceInspection,
    InMemoryHistoricalSource,
    SourceArtifact,
    SourceProvenance,
    create_diagnostics_application,
)


_SOURCE_CHECKS = (
    "bar_continuity",
    "instrument_coverage",
    "eligible_universe",
    "trading_status",
    "st_status",
    "suspension_state",
    "industry_as_of",
    "adjustment_consistency",
    "causal_availability",
    "required_fields",
    "missing_data",
    "duplicates",
    "timestamps",
)


def _application_with_admitted_source(*, started: bool):
    selection = HistoricalSegmentSelection(
        market="mainland-a-share",
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
    )
    inspection = HistoricalSourceInspection(
        selection=selection,
        label="A-share diagnostic interval",
        provenance=SourceProvenance(
            provider="BaoStock",
            dataset="local-a-share-fixture",
            version="fixture-2026-07-21",
            observed_at=datetime(2026, 7, 21, 23, 0, tzinfo=timezone.utc),
        ),
        artifacts=(
            SourceArtifact(
                name="daily-unadjusted",
                content_hash="1" * 64,
                row_count=60,
            ),
        ),
        eligible_instrument_count=120,
        trading_day_count=2,
        bar_count=60,
        checks=tuple(
            AdmissionCheck(code=code, passed=True, summary=f"{code} passed.")
            for code in _SOURCE_CHECKS
        ),
    )
    application = create_diagnostics_application(
        historical_source=InMemoryHistoricalSource((inspection,))
    )
    if started:
        application.start()
        admission = application.admit_historical_segment(selection)
        assert admission.status == "admitted"
    return application


def _ready_data_source_result(now: datetime) -> DiagnosticDataSourceApplicationResult:
    token = SourceRevisionToken("d" * 64)
    return DiagnosticDataSourceApplicationResult(
        availability=DiagnosticDataSourceApplicationAvailability.READY,
        observation=DiagnosticDataSourceApplicationObservation(
            identity=DiagnosticDataSourceIdentity(
                public_id="admitted-source-dddddddddddddddd",
                provider="BaoStock",
                dataset="local-a-share-fixture",
                version="fixture-2026-07-21",
            ),
            observed_at=now,
            affected_scope=(
                DiagnosticDataSourceScope.SCENARIO_INPUTS,
                DiagnosticDataSourceScope.DIAGNOSTIC_EVIDENCE_INTERPRETATION,
            ),
        ),
        source_token=token,
        observed_at=now,
        error=None,
    )


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
    fallback: Callable[[], None]
    deliver_data_source: Callable[[int, int | None], None]
    fail_data_source: Callable[[], None]
    advance: Callable[[timedelta], None]


def _serialized_text_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        return tuple(
            text
            for item in value.values()
            for text in _serialized_text_values(item)
        )
    if isinstance(value, (list, tuple)):
        return tuple(
            text for item in value for text in _serialized_text_values(item)
        )
    return ()


def _live_harness(*, initially_healthy: bool) -> _Harness:
    clock = _Clock()
    application = _application_with_admitted_source(started=initially_healthy)
    bridge = EventBridge(subscribe_backend=False)
    application_health = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        application,
        clock=clock,
    )
    failed = False
    data_source_failed = False

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

        def read_diagnostic_data_source_health(
            self,
        ) -> DiagnosticDataSourceApplicationResult:
            if data_source_failed:
                return DiagnosticDataSourceApplicationResult(
                    availability=DiagnosticDataSourceApplicationAvailability.FAILED,
                    observation=None,
                    source_token=None,
                    observed_at=clock(),
                    error=DiagnosticDataSourceApplicationError(
                        code=DiagnosticDataSourceApplicationErrorCode.READ_FAILED,
                        explanation=(
                            r"C:\secrets\source.db?token=super-secret SELECT payload"
                        ),
                        retryable=True,
                    ),
                )
            return application_health.read_diagnostic_data_source_health()

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

    def deliver_data_source(revision: int, generation: int | None = None) -> None:
        bridge.on_snapshot(
            {
                "feature": "system_health",
                "component": "diagnostic_data_source",
                "source_revision": revision,
            },
            generation=generation,
        )
        bridge.flush(force=True)

    def fail_data_source() -> None:
        nonlocal data_source_failed
        data_source_failed = True

    return _Harness(
        feature=feature,
        become_healthy=become_healthy,
        publish_change=publish_change,
        disconnect=lambda: bridge.mark_disconnected(),
        reconnect=lambda: bridge.mark_reconnected(),
        fail=fail,
        fallback=bridge.mark_fallback_active,
        deliver_data_source=deliver_data_source,
        fail_data_source=fail_data_source,
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
        fallback=feature.advance_data_source_to_fallback,
        deliver_data_source=(
            lambda revision, generation=None: feature.deliver_data_source_revision(
                revision,
                generation=generation,
            )
        ),
        fail_data_source=feature.fail_next_data_source_reread,
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


def test_live_and_fake_expose_the_same_fresh_typed_data_source_health(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(initially_healthy=True)
    try:
        state = harness.feature.snapshot(SystemHealthContext())
        source = state.diagnostic_data_source

        assert source.classification is DiagnosticDataSourceHealthClassification.HEALTHY
        assert source.connection is DiagnosticDataSourceConnectionState.CONNECTED
        assert source.fallback is DiagnosticDataSourceFallbackState.PRIMARY
        assert source.accepted_revision.value == 1
        assert source.accepted_generation.value == 1
        assert source.freshness is Freshness.FRESH
        assert source.last_reliable_observation is not None
        assert source.last_reliable_observation.identity.public_id.startswith(
            "admitted-source-"
        )
        assert source.affected_scope == (
            DiagnosticDataSourceScope.SCENARIO_INPUTS,
            DiagnosticDataSourceScope.DIAGNOSTIC_EVIDENCE_INTERPRETATION,
        )
        assert source.recovery_phase is DiagnosticDataSourceRecoveryPhase.IDLE
        with pytest.raises(FrozenInstanceError):
            source.explanation = "mutable"  # type: ignore[misc]
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
        assert healthy.presentation is SystemHealthPresentationState.UNAVAILABLE
        assert healthy.components[0].classification is RuntimeHealthClassification.HEALTHY
        assert healthy.diagnostic_data_source.classification is (
            DiagnosticDataSourceHealthClassification.UNAVAILABLE
        )
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
        assert recovered.presentation is SystemHealthPresentationState.STALE
        assert recovered.diagnostic_data_source.recovery_phase is (
            DiagnosticDataSourceRecoveryPhase.RECONNECTING
        )
        assert recovered.last_reliable_payload is not None
        assert [state.revision for state in observed] == sorted(
            {state.revision for state in observed}
        )
    finally:
        subscription.dispose()
        harness.feature.close()


def test_first_revision_is_accepted_after_initially_unavailable_source() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    source_available = False

    class _ApplicationHealth:
        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            return RuntimeHealthApplicationResult(
                availability=RuntimeHealthApplicationAvailability.READY,
                observation=RuntimeHealthApplicationObservation(
                    classification=RuntimeHealthClassification.HEALTHY,
                    observed_at=now,
                    explanation="The application runtime is available.",
                ),
                source_token=SourceRevisionToken("a" * 64),
                observed_at=now,
                error=None,
            )

        def read_diagnostic_data_source_health(
            self,
        ) -> DiagnosticDataSourceApplicationResult:
            if source_available:
                return _ready_data_source_result(now)
            return DiagnosticDataSourceApplicationResult(
                availability=(
                    DiagnosticDataSourceApplicationAvailability.NO_ADMITTED_SOURCE
                ),
                observation=None,
                source_token=None,
                observed_at=now,
                error=DiagnosticDataSourceApplicationError(
                    code=(
                        DiagnosticDataSourceApplicationErrorCode.NO_ADMITTED_SOURCE
                    ),
                    explanation="No admitted source is available.",
                    retryable=True,
                ),
            )

    bridge = EventBridge(subscribe_backend=False)
    feature = LiveSystemHealthAdapter(
        application_health=_ApplicationHealth(),  # type: ignore[arg-type]
        event_bridge=bridge,
        clock=lambda: now,
    )
    recovered = Event()
    subscription = feature.subscribe(
        SystemHealthContext(),
        lambda state: (
            recovered.set()
            if state.diagnostic_data_source.accepted_revision
            == DiagnosticDataSourceRevision(1)
            else None
        ),
    )
    try:
        assert feature.snapshot(
            SystemHealthContext()
        ).diagnostic_data_source.accepted_revision is None
        source_available = True
        bridge.on_snapshot(
            {
                "feature": "system_health",
                "component": "diagnostic_data_source",
                "source_revision": 1,
            }
        )
        bridge.flush(force=True)

        assert recovered.wait(timeout=5)
        state = feature.snapshot(SystemHealthContext())
        assert state.diagnostic_data_source.accepted_revision == (
            DiagnosticDataSourceRevision(1)
        )
        assert state.presentation is SystemHealthPresentationState.HEALTHY
    finally:
        subscription.dispose()
        feature.close()


def test_data_source_disconnect_and_staleness_retain_last_reliable_observation(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(initially_healthy=True)
    observed: list = []
    subscription = harness.feature.subscribe(SystemHealthContext(), observed.append)
    try:
        reliable = observed[-1].diagnostic_data_source.last_reliable_observation
        assert reliable is not None

        harness.disconnect()
        disconnected = observed[-1].diagnostic_data_source
        assert disconnected.connection is DiagnosticDataSourceConnectionState.DISCONNECTED
        assert disconnected.classification is DiagnosticDataSourceHealthClassification.DEGRADED
        assert disconnected.freshness is Freshness.DISCONNECTED
        assert disconnected.last_reliable_observation == reliable
        assert disconnected.recovery_phase is DiagnosticDataSourceRecoveryPhase.DISCONNECTED

        harness.advance(timedelta(seconds=6))
        stale = harness.feature.snapshot(SystemHealthContext()).diagnostic_data_source
        assert stale.classification is DiagnosticDataSourceHealthClassification.STALE
        assert stale.freshness is Freshness.STALE
        assert stale.last_reliable_observation == reliable
    finally:
        subscription.dispose()
        harness.feature.close()


def test_connected_data_source_becomes_stale_without_wall_clock_sleep(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(initially_healthy=True)
    try:
        reliable = harness.feature.snapshot(
            SystemHealthContext()
        ).diagnostic_data_source.last_reliable_observation
        harness.advance(timedelta(seconds=6))

        state = harness.feature.snapshot(SystemHealthContext())
        source = state.diagnostic_data_source
        assert source.connection is DiagnosticDataSourceConnectionState.CONNECTED
        assert source.classification is DiagnosticDataSourceHealthClassification.STALE
        assert source.freshness is Freshness.STALE
        assert source.last_reliable_observation == reliable
        assert state.presentation is SystemHealthPresentationState.STALE
    finally:
        harness.feature.close()


def test_data_source_recovers_only_after_current_generation_authoritative_reread(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(initially_healthy=True)
    observed: list = []
    subscription = harness.feature.subscribe(SystemHealthContext(), observed.append)
    try:
        initial = observed[-1].diagnostic_data_source
        assert initial.accepted_revision is not None
        assert initial.accepted_revision.value == 1
        assert initial.accepted_generation.value == 1

        harness.disconnect()
        harness.fallback()
        reconnecting = observed[-1].diagnostic_data_source
        assert reconnecting.connection is DiagnosticDataSourceConnectionState.RECONNECTING
        assert reconnecting.classification is (
            DiagnosticDataSourceHealthClassification.RECOVERING
        )
        assert reconnecting.fallback is DiagnosticDataSourceFallbackState.ACTIVE
        assert reconnecting.recovery_phase is DiagnosticDataSourceRecoveryPhase.FALLBACK
        assert reconnecting.accepted_revision == initial.accepted_revision
        assert reconnecting.accepted_generation == initial.accepted_generation

        harness.deliver_data_source(2, None)
        recovered = observed[-1].diagnostic_data_source
        assert any(
            state.diagnostic_data_source.recovery_phase
            is DiagnosticDataSourceRecoveryPhase.REREADING
            for state in observed
        )
        assert recovered.recovery_phase is DiagnosticDataSourceRecoveryPhase.RECOVERED
        assert recovered.accepted_revision is not None
        assert recovered.accepted_revision.value == 2
        assert recovered.accepted_generation.value == 2
        assert recovered.last_reliable_observation is not None
        assert recovered.last_reliable_observation.revision.value == 2

        delivered = tuple(state.revision for state in observed)
        harness.deliver_data_source(99, 1)
        harness.deliver_data_source(2, 2)
        harness.deliver_data_source(1, 2)
        assert tuple(state.revision for state in observed) == delivered
    finally:
        subscription.dispose()
        harness.feature.close()


def test_connected_primary_can_rotate_directly_to_fallback_generation(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(initially_healthy=True)
    observed: list = []
    subscription = harness.feature.subscribe(SystemHealthContext(), observed.append)
    try:
        harness.fallback()

        fallback = observed[-1].diagnostic_data_source
        assert fallback.connection is DiagnosticDataSourceConnectionState.RECONNECTING
        assert fallback.fallback is DiagnosticDataSourceFallbackState.ACTIVE
        assert fallback.recovery_phase is DiagnosticDataSourceRecoveryPhase.FALLBACK
        assert fallback.accepted_revision == DiagnosticDataSourceRevision(1)
        assert fallback.accepted_generation.value == 1
        assert observed[-1].source.generation.value == 2
        assert observed[-1].presentation is SystemHealthPresentationState.DEGRADED

        harness.deliver_data_source(2, 2)
        assert observed[-1].diagnostic_data_source.recovery_phase is (
            DiagnosticDataSourceRecoveryPhase.RECOVERED
        )
    finally:
        subscription.dispose()
        harness.feature.close()


def test_data_source_failed_recovery_is_terminal_safe_and_retains_history(
    harness_factory: Callable[..., _Harness],
) -> None:
    harness = harness_factory(initially_healthy=True)
    observed: list = []
    subscription = harness.feature.subscribe(SystemHealthContext(), observed.append)
    try:
        reliable = observed[-1].diagnostic_data_source.last_reliable_observation
        harness.disconnect()
        harness.fallback()
        harness.fail_data_source()
        harness.deliver_data_source(2, None)

        failed = observed[-1].diagnostic_data_source
        assert failed.recovery_phase is DiagnosticDataSourceRecoveryPhase.FAILED_RECOVERY
        assert failed.classification is DiagnosticDataSourceHealthClassification.DEGRADED
        assert failed.last_reliable_observation == reliable
        assert failed.accepted_revision is not None
        assert failed.accepted_revision.value == 1
        assert failed.accepted_generation.value == 1
        assert failed.error is not None
        exposed = f"{failed.explanation} {failed.error.explanation}".casefold()
        serialized_values = " ".join(
            _serialized_text_values(asdict(observed[-1]))
        ).casefold()
        for forbidden in (
            "c:\\",
            "source.db",
            "token",
            "secret",
            "select",
            "payload",
        ):
            assert forbidden not in exposed
            assert forbidden not in serialized_values
        assert any(
            state.diagnostic_data_source.recovery_phase
            is DiagnosticDataSourceRecoveryPhase.REREADING
            for state in observed
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


def test_live_adapter_uses_50ms_batch_and_highest_revision_merge_order() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    data_source_reads = 0
    accepted = Event()

    class _ApplicationHealth:
        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            return RuntimeHealthApplicationResult(
                availability=RuntimeHealthApplicationAvailability.READY,
                observation=RuntimeHealthApplicationObservation(
                    classification=RuntimeHealthClassification.HEALTHY,
                    observed_at=now,
                    explanation="The application runtime is available.",
                ),
                source_token=SourceRevisionToken("a" * 64),
                observed_at=now,
                error=None,
            )

        def read_diagnostic_data_source_health(
            self,
        ) -> DiagnosticDataSourceApplicationResult:
            nonlocal data_source_reads
            data_source_reads += 1
            return _ready_data_source_result(now)

    bridge = EventBridge(subscribe_backend=False)
    feature = LiveSystemHealthAdapter(
        application_health=_ApplicationHealth(),  # type: ignore[arg-type]
        event_bridge=bridge,
        clock=lambda: now,
    )
    observed: list = []

    def observe(state) -> None:
        observed.append(state)
        if state.diagnostic_data_source.accepted_revision == (
            DiagnosticDataSourceRevision(4)
        ):
            accepted.set()

    subscription = feature.subscribe(SystemHealthContext(), observe)
    try:
        assert bridge.flush_interval_ms == 50
        for revision in (2, 4, 3, 4):
            bridge.on_snapshot(
                {
                    "feature": "system_health",
                    "component": "diagnostic_data_source",
                    "source_revision": revision,
                }
            )
        bridge.flush(force=True)

        assert accepted.wait(timeout=5)
        assert data_source_reads == 2
        accepted_revisions = tuple(
            state.diagnostic_data_source.accepted_revision
            for state in observed
            if state.diagnostic_data_source.recovery_phase
            is DiagnosticDataSourceRecoveryPhase.RECOVERED
        )
        assert accepted_revisions == (DiagnosticDataSourceRevision(4),)
    finally:
        subscription.dispose()
        feature.close()


def test_data_source_authoritative_reread_does_not_block_eventbridge_delivery() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    reread_entered = Event()
    release_reread = Event()
    flush_returned = Event()
    recovered = Event()
    calls = 0
    runtime = RuntimeHealthApplicationResult(
        availability=RuntimeHealthApplicationAvailability.READY,
        observation=RuntimeHealthApplicationObservation(
            classification=RuntimeHealthClassification.HEALTHY,
            observed_at=now,
            explanation="The application runtime is available.",
        ),
        source_token=SourceRevisionToken("a" * 64),
        observed_at=now,
        error=None,
    )

    class _BlockingApplicationHealth:
        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            return runtime

        def read_diagnostic_data_source_health(
            self,
        ) -> DiagnosticDataSourceApplicationResult:
            nonlocal calls
            calls += 1
            if calls > 1:
                reread_entered.set()
                assert release_reread.wait(timeout=5)
            return _ready_data_source_result(now)

    bridge = EventBridge(subscribe_backend=False)
    feature = LiveSystemHealthAdapter(
        application_health=_BlockingApplicationHealth(),  # type: ignore[arg-type]
        event_bridge=bridge,
        clock=lambda: now,
    )
    subscription = feature.subscribe(
        SystemHealthContext(),
        lambda state: (
            recovered.set()
            if state.diagnostic_data_source.recovery_phase
            is DiagnosticDataSourceRecoveryPhase.RECOVERED
            else None
        ),
    )
    delivery_thread = None
    try:
        bridge.mark_disconnected()
        bridge.mark_fallback_active()

        def deliver() -> None:
            bridge.on_snapshot(
                {
                    "feature": "system_health",
                    "component": "diagnostic_data_source",
                    "source_revision": 2,
                }
            )
            bridge.flush(force=True)
            flush_returned.set()

        delivery_thread = Thread(target=deliver)
        delivery_thread.start()
        assert reread_entered.wait(timeout=5)
        assert flush_returned.wait(timeout=1)
        release_reread.set()
        assert recovered.wait(timeout=5)
        delivery_thread.join(timeout=5)
        assert not delivery_thread.is_alive()
    finally:
        release_reread.set()
        if delivery_thread is not None:
            delivery_thread.join(timeout=5)
        subscription.dispose()
        feature.close()


def test_live_close_isolates_a_late_authoritative_reread_callback() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    reread_entered = Event()
    release_reread = Event()
    reread_returned = Event()
    calls = 0

    class _BlockingApplicationHealth:
        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            return RuntimeHealthApplicationResult(
                availability=RuntimeHealthApplicationAvailability.READY,
                observation=RuntimeHealthApplicationObservation(
                    classification=RuntimeHealthClassification.HEALTHY,
                    observed_at=now,
                    explanation="The application runtime is available.",
                ),
                source_token=SourceRevisionToken("a" * 64),
                observed_at=now,
                error=None,
            )

        def read_diagnostic_data_source_health(
            self,
        ) -> DiagnosticDataSourceApplicationResult:
            nonlocal calls
            calls += 1
            if calls > 1:
                reread_entered.set()
                assert release_reread.wait(timeout=5)
                reread_returned.set()
            return _ready_data_source_result(now)

    executor = ThreadPoolExecutor(max_workers=1)
    bridge = EventBridge(subscribe_backend=False)
    feature = LiveSystemHealthAdapter(
        application_health=_BlockingApplicationHealth(),  # type: ignore[arg-type]
        event_bridge=bridge,
        clock=lambda: now,
        executor=executor,
    )
    observed: list = []
    subscription = feature.subscribe(SystemHealthContext(), observed.append)
    try:
        bridge.mark_disconnected()
        bridge.mark_fallback_active()
        bridge.on_snapshot(
            {
                "feature": "system_health",
                "component": "diagnostic_data_source",
                "source_revision": 2,
            }
        )
        bridge.flush(force=True)
        assert reread_entered.wait(timeout=5)
        delivered_before_close = len(observed)

        feature.close()
        release_reread.set()
        assert reread_returned.wait(timeout=5)
        executor.shutdown(wait=True)

        assert len(observed) == delivered_before_close
        assert observed[-1].diagnostic_data_source.recovery_phase is (
            DiagnosticDataSourceRecoveryPhase.REREADING
        )
    finally:
        release_reread.set()
        subscription.dispose()
        feature.close()
        executor.shutdown(wait=True)


def test_owned_live_adapter_close_does_not_wait_for_an_inflight_reread() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    reread_entered = Event()
    release_reread = Event()
    close_returned = Event()
    calls = 0

    class _BlockingApplicationHealth:
        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            return RuntimeHealthApplicationResult(
                availability=RuntimeHealthApplicationAvailability.READY,
                observation=RuntimeHealthApplicationObservation(
                    classification=RuntimeHealthClassification.HEALTHY,
                    observed_at=now,
                    explanation="The application runtime is available.",
                ),
                source_token=SourceRevisionToken("a" * 64),
                observed_at=now,
                error=None,
            )

        def read_diagnostic_data_source_health(
            self,
        ) -> DiagnosticDataSourceApplicationResult:
            nonlocal calls
            calls += 1
            if calls > 1:
                reread_entered.set()
                assert release_reread.wait(timeout=5)
            return _ready_data_source_result(now)

    bridge = EventBridge(subscribe_backend=False)
    feature = LiveSystemHealthAdapter(
        application_health=_BlockingApplicationHealth(),  # type: ignore[arg-type]
        event_bridge=bridge,
        clock=lambda: now,
    )
    feature.snapshot(SystemHealthContext())
    bridge.on_snapshot(
        {
            "feature": "system_health",
            "component": "diagnostic_data_source",
            "source_revision": 2,
        }
    )
    bridge.flush(force=True)
    assert reread_entered.wait(timeout=5)

    close_thread = Thread(
        target=lambda: (feature.close(), close_returned.set()),
    )
    close_thread.start()
    try:
        assert close_returned.wait(timeout=0.1)
    finally:
        release_reread.set()
        close_thread.join(timeout=5)
        assert not close_thread.is_alive()


def test_live_coalescing_preserves_failed_then_recovered_terminal_states() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    first_reread_entered = Event()
    release_first_reread = Event()
    terminal_recovered = Event()
    calls = 0

    class _SequencedApplicationHealth:
        def read_runtime_health(self) -> RuntimeHealthApplicationResult:
            return RuntimeHealthApplicationResult(
                availability=RuntimeHealthApplicationAvailability.READY,
                observation=RuntimeHealthApplicationObservation(
                    classification=RuntimeHealthClassification.HEALTHY,
                    observed_at=now,
                    explanation="The application runtime is available.",
                ),
                source_token=SourceRevisionToken("a" * 64),
                observed_at=now,
                error=None,
            )

        def read_diagnostic_data_source_health(
            self,
        ) -> DiagnosticDataSourceApplicationResult:
            nonlocal calls
            calls += 1
            if calls == 2:
                first_reread_entered.set()
                assert release_first_reread.wait(timeout=5)
                return DiagnosticDataSourceApplicationResult(
                    availability=DiagnosticDataSourceApplicationAvailability.FAILED,
                    observation=None,
                    source_token=None,
                    observed_at=now,
                    error=DiagnosticDataSourceApplicationError(
                        code=DiagnosticDataSourceApplicationErrorCode.READ_FAILED,
                        explanation="The authoritative read failed safely.",
                        retryable=True,
                    ),
                )
            return _ready_data_source_result(now)

    bridge = EventBridge(subscribe_backend=False)
    feature = LiveSystemHealthAdapter(
        application_health=_SequencedApplicationHealth(),  # type: ignore[arg-type]
        event_bridge=bridge,
        clock=lambda: now,
    )
    observed: list = []

    def observe(state) -> None:
        observed.append(state)
        if state.diagnostic_data_source.recovery_phase is (
            DiagnosticDataSourceRecoveryPhase.RECOVERED
        ) and state.diagnostic_data_source.accepted_revision == (
            DiagnosticDataSourceRevision(3)
        ):
            terminal_recovered.set()

    subscription = feature.subscribe(SystemHealthContext(), observe)
    try:
        bridge.mark_disconnected()
        bridge.mark_fallback_active()
        for revision in (2, 3):
            bridge.on_snapshot(
                {
                    "feature": "system_health",
                    "component": "diagnostic_data_source",
                    "source_revision": revision,
                }
            )
            bridge.flush(force=True)
            if revision == 2:
                assert first_reread_entered.wait(timeout=5)
        release_first_reread.set()
        assert terminal_recovered.wait(timeout=5)

        phases = tuple(
            state.diagnostic_data_source.recovery_phase for state in observed
        )
        assert DiagnosticDataSourceRecoveryPhase.FAILED_RECOVERY in phases
        assert phases[-1] is DiagnosticDataSourceRecoveryPhase.RECOVERED
        assert observed[-1].diagnostic_data_source.accepted_revision == (
            DiagnosticDataSourceRevision(3)
        )
    finally:
        release_first_reread.set()
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

        def read_diagnostic_data_source_health(
            self,
        ) -> DiagnosticDataSourceApplicationResult:
            return _ready_data_source_result(now)

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

        def read_diagnostic_data_source_health(
            self,
        ) -> DiagnosticDataSourceApplicationResult:
            return _ready_data_source_result(now)

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
