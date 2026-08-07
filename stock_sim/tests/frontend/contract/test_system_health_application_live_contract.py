from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest
from sqlalchemy import event

from app.event_bridge import EventBridge
from app.features import (
    DiagnosticCacheApplicationAvailability,
    DiagnosticCacheCompatibility,
    DiagnosticCacheFallbackState,
    DiagnosticCacheHealthClassification,
    DiagnosticCacheLastRefreshResult,
    DiagnosticQueueApplicationAvailability,
    DiagnosticQueueBlockageReason,
    DiagnosticQueueConsumerAvailability,
    DiagnosticCommandId,
    DiagnosticCommandIdempotencyKey,
    RUNTIME_HEALTH_APPLICATION_INTERFACE_VERSION,
    LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter,
    LiveSystemHealthAdapter,
    RuntimeHealthApplicationAvailability,
    RuntimeHealthApplicationErrorCode,
    RuntimeHealthClassification,
    StrategyDiagnosticsV1SystemHealthApplication,
    SystemHealthContext,
    StartFormalDiagnosticCampaign,
)
from strategy_diagnostics import create_diagnostics_application
from strategy_diagnostics.market_paths import InMemoryMarketPathArtifactStore
from tests.frontend.system_health_support import ApplicationDrivenCacheStore
from tests.frontend.contract.test_diagnostic_task_campaign_start_live_contract import (
    _approved_formal_task,
    _formal_live_stack,
)
from tests.strategy_diagnostics.test_recipe_lifecycle import (
    _baseline_payload,
    _RecipeFixtureSource,
)


NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


def test_runtime_health_application_1_0_reads_the_real_diagnostics_application() -> None:
    application = create_diagnostics_application()
    adapter = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        application,
        clock=lambda: NOW,
    )

    unavailable = adapter.read_runtime_health()
    assert adapter.interface_version.render() == "1.0"
    assert unavailable.availability is (
        RuntimeHealthApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
    )
    assert unavailable.observation is None
    assert unavailable.source_token is None
    assert unavailable.error is not None
    assert unavailable.error.code is (
        RuntimeHealthApplicationErrorCode.NO_AUTHORITATIVE_OBSERVATION
    )

    application.start()
    ready = adapter.read_runtime_health()

    assert ready.availability is RuntimeHealthApplicationAvailability.READY
    assert ready.observation is not None
    assert ready.observation.classification is RuntimeHealthClassification.HEALTHY
    assert ready.observation.observed_at == NOW
    assert ready.source_token is not None
    assert ready.error is None
    with pytest.raises(FrozenInstanceError):
        ready.observation.explanation = "mutable"  # type: ignore[misc]


def test_runtime_health_application_interface_is_small_and_read_only() -> None:
    assert RUNTIME_HEALTH_APPLICATION_INTERFACE_VERSION.render() == "1.0"
    operations = {
        name
        for name, member in inspect.getmembers(
            StrategyDiagnosticsV1SystemHealthApplication,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    assert operations == {
        "read_runtime_health",
        "read_diagnostic_queue_health",
        "read_diagnostic_cache_health",
    }


def test_queue_and_cache_health_read_only_seam_uses_supported_application_behavior() -> None:
    source = _RecipeFixtureSource()
    artifact_store = InMemoryMarketPathArtifactStore(clock=lambda: NOW)
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=artifact_store,
        recipe_clock=lambda: NOW,
        diagnostic_task_clock=lambda: NOW,
    )
    application.start()
    adapter = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        application,
        clock=lambda: NOW,
    )

    empty_queue = adapter.read_diagnostic_queue_health()
    assert empty_queue.availability is DiagnosticQueueApplicationAvailability.READY
    assert empty_queue.observation is not None
    assert (
        empty_queue.observation.pending_count,
        empty_queue.observation.running_count,
        empty_queue.observation.blocked_count,
    ) == (0, 0, 0)
    assert empty_queue.observation.oldest_pending_at is None
    assert empty_queue.observation.consumer_availability is (
        DiagnosticQueueConsumerAvailability.AVAILABLE
    )
    assert empty_queue.observation.blockage_reason is (
        DiagnosticQueueBlockageReason.NONE
    )

    unobserved_cache = adapter.read_diagnostic_cache_health()
    assert unobserved_cache.availability is (
        DiagnosticCacheApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
    )
    assert unobserved_cache.observation is None

    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    draft = application.create_manual_recipe_draft(
        _baseline_payload(admission.segment.segment_id),
        author="researcher",
    )
    assert application.validate_recipe_draft(draft.draft_id).is_valid
    approved = application.approve_recipe_draft(draft.draft_id, actor="owner")
    application.materialize_baseline_reference_path(approved.version_id)

    before_observation = artifact_store.diagnostic_cache_health()
    cache = adapter.read_diagnostic_cache_health()
    after_observation = artifact_store.diagnostic_cache_health()

    assert cache.availability is DiagnosticCacheApplicationAvailability.READY
    assert cache.observation is not None
    assert cache.observation.generation >= 1
    assert cache.observation.fallback is DiagnosticCacheFallbackState.PRIMARY
    assert cache.observation.last_refresh_result is (
        DiagnosticCacheLastRefreshResult.SUCCEEDED
    )
    assert cache.observation.compatibility is (
        DiagnosticCacheCompatibility.COMPATIBLE
    )
    assert before_observation == after_observation


def test_runtime_health_application_redacts_raw_failure_details() -> None:
    class _ThrowingApplication:
        def status(self) -> object:
            raise OSError(
                r"C:\secrets\runtime.exe --token super-secret SELECT * FROM users"
            )

        def diagnostic_task_queue_health(self) -> object:
            raise OSError(
                r"C:\private\task.db --credential queue-secret traceback payload"
            )

        def diagnostic_cache_health(self) -> object:
            raise OSError(
                r"C:\private\cache.bin --token cache-secret SELECT raw_value"
            )

    adapter = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        _ThrowingApplication(),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    results = (
        adapter.read_runtime_health(),
        adapter.read_diagnostic_queue_health(),
        adapter.read_diagnostic_cache_health(),
    )

    assert results[0].availability is RuntimeHealthApplicationAvailability.FAILED
    assert results[0].error is not None
    assert results[0].error.code is RuntimeHealthApplicationErrorCode.READ_FAILED
    for result in results:
        assert result.error is not None
        exposed = result.error.explanation.casefold()
        for forbidden in (
            "c:\\",
            "runtime.exe",
            "task.db",
            "cache.bin",
            "token",
            "credential",
            "secret",
            "select",
            "users",
            "payload",
            "traceback",
            "raw_value",
        ):
            assert forbidden not in exposed


def test_first_incompatible_cache_observation_keeps_typed_state_without_generation(
) -> None:
    source = _RecipeFixtureSource()
    store = ApplicationDrivenCacheStore(
        clock=lambda: NOW,
        incompatible_on_first_put=True,
    )
    application = create_diagnostics_application(
        historical_source=source,
        market_data_source=source,
        artifact_store=store,
        recipe_clock=lambda: NOW,
    )
    application.start()
    admission = application.admit_historical_segment(source.selection)
    assert admission.segment is not None
    draft = application.create_manual_recipe_draft(
        _baseline_payload(admission.segment.segment_id),
        author="researcher",
    )
    assert application.validate_recipe_draft(draft.draft_id).is_valid
    approved = application.approve_recipe_draft(draft.draft_id, actor="owner")
    with pytest.raises(ValueError):
        application.materialize_baseline_reference_path(approved.version_id)

    application_adapter = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        application,
        clock=lambda: NOW,
    )
    result = application_adapter.read_diagnostic_cache_health()
    assert result.availability is DiagnosticCacheApplicationAvailability.READY
    assert result.observation is not None
    assert result.observation.generation is None
    assert result.observation.compatibility is (
        DiagnosticCacheCompatibility.INCOMPATIBLE
    )

    feature = LiveSystemHealthAdapter(
        application_health=application_adapter,
        event_bridge=EventBridge(subscribe_backend=False),
        clock=lambda: NOW,
        sampling_interval=None,
    )
    try:
        component = feature.snapshot(SystemHealthContext()).diagnostic_cache
        assert component.classification is (
            DiagnosticCacheHealthClassification.INCOMPATIBLE
        )
        assert component.generation is None
    finally:
        feature.close()


def test_sql_queue_health_uses_one_bounded_active_target_projection(tmp_path) -> None:
    (
        _source,
        _artifact_store,
        engine,
        application,
        _application_adapter,
        task_feature,
    ) = _formal_live_stack(tmp_path)
    try:
        approved = _approved_formal_task(task_feature)
        accepted = task_feature.start_formal_diagnostic_campaign(
            StartFormalDiagnosticCampaign(
                command_id=DiagnosticCommandId("start-command-bounded-health-110"),
                idempotency_key=DiagnosticCommandIdempotencyKey(
                    "start-idempotency-bounded-health-110"
                ),
                task_id=approved.task_id,
                expected_revision=approved.revision,
                approved_revision=approved.revision,
            )
        )
        assert accepted.accepted
        statements: list[str] = []

        def capture_statement(
            _connection,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            statements.append(str(statement).casefold())

        event.listen(engine, "before_cursor_execute", capture_statement)
        try:
            result = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
                application,
                clock=lambda: NOW,
            ).read_diagnostic_queue_health()
        finally:
            event.remove(engine, "before_cursor_execute", capture_statement)

        assert result.availability is DiagnosticQueueApplicationAvailability.READY
        assert result.observation is not None
        assert len(statements) == 1
        assert "diagnostic_lifecycle_targets" in statements[0]
        for forbidden in (
            "configuration_json",
            "diagnostic_task_handles",
            "diagnostic_task_validations",
            "diagnostic_task_campaign_handoffs",
        ):
            assert forbidden not in statements[0]
    finally:
        task_feature.close()
