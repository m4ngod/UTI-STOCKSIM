from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone

import pytest

from app.features import (
    ACTIVE_FEATURE_INTERFACES,
    SYSTEM_HEALTH_INTERFACE_VERSION,
    DiagnosticDataSourceComponentIdentity,
    DiagnosticDataSourceConnectionState,
    DiagnosticDataSourceFallbackState,
    DiagnosticDataSourceHealthClassification,
    DiagnosticDataSourceHealthComponent,
    DiagnosticDataSourceIdentity,
    DiagnosticDataSourceObservation,
    DiagnosticDataSourceRecoveryPhase,
    DiagnosticDataSourceRevision,
    DiagnosticDataSourceScope,
    DiagnosticCacheCompatibility,
    DiagnosticCacheFallbackState,
    DiagnosticCacheHealthClassification,
    DiagnosticCacheHealthComponent,
    DiagnosticCacheLastRefreshResult,
    DiagnosticCacheRecoveryPhase,
    DiagnosticCacheScope,
    DiagnosticQueueBlockageReason,
    DiagnosticQueueConsumerAvailability,
    DiagnosticQueueHealthClassification,
    DiagnosticQueueHealthComponent,
    DiagnosticQueueRecoveryPhase,
    DiagnosticQueueScope,
    FeatureModuleName,
    RuntimeHealthClassification,
    RuntimeHealthComponent,
    RuntimeHealthComponentIdentity,
    RuntimeHealthRecoveryPhase,
    SystemHealthContext,
    SystemHealthError,
    SystemHealthErrorCode,
    SystemHealthFeature,
    SystemHealthPresentationState,
    SystemHealthSource,
    SystemHealthViewState,
)
from app.features.run_monitoring import (
    Completeness,
    Freshness,
    SourceGenerationId,
    SourceKind,
    ViewPhase,
)


NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


def test_system_health_1_0_exposes_finite_queue_and_cache_components() -> None:
    assert {item.value for item in DiagnosticDataSourceHealthClassification} == {
        "healthy",
        "degraded",
        "stale",
        "unavailable",
        "recovering",
    }
    assert {item.value for item in DiagnosticDataSourceConnectionState} == {
        "connected",
        "disconnected",
        "reconnecting",
        "unavailable",
    }
    assert {item.value for item in DiagnosticDataSourceFallbackState} == {
        "primary",
        "active",
        "unavailable",
    }
    assert {item.value for item in DiagnosticDataSourceRecoveryPhase} == {
        "idle",
        "disconnected",
        "fallback",
        "reconnecting",
        "rereading",
        "recovered",
        "failed_recovery",
    }
    assert {item.value for item in DiagnosticQueueHealthClassification} == {
        "healthy",
        "degraded",
        "stale",
        "unavailable",
        "recovering",
        "unknown",
    }
    assert {item.value for item in DiagnosticCacheHealthClassification} == {
        "healthy",
        "degraded",
        "stale",
        "fallback",
        "incompatible",
        "unavailable",
        "recovering",
        "unknown",
    }
    assert {field.name for field in fields(DiagnosticQueueHealthComponent)} == {
        "classification",
        "revision",
        "observed_at",
        "freshness",
        "age",
        "freshness_threshold",
        "pending_count",
        "running_count",
        "blocked_count",
        "oldest_pending_age",
        "consumer_availability",
        "blockage_reason",
        "affected_scope",
        "recovery_phase",
        "explanation",
        "error",
    }
    assert {field.name for field in fields(DiagnosticCacheHealthComponent)} == {
        "classification",
        "revision",
        "observed_at",
        "freshness",
        "age",
        "freshness_threshold",
        "generation",
        "fallback",
        "last_refresh_result",
        "compatibility",
        "affected_scope",
        "recovery_phase",
        "explanation",
        "error",
    }
    assert set(DiagnosticQueueConsumerAvailability) == {
        DiagnosticQueueConsumerAvailability.AVAILABLE,
        DiagnosticQueueConsumerAvailability.BLOCKED,
        DiagnosticQueueConsumerAvailability.UNAVAILABLE,
        DiagnosticQueueConsumerAvailability.UNKNOWN,
    }
    assert set(DiagnosticQueueBlockageReason) == {
        DiagnosticQueueBlockageReason.NONE,
        DiagnosticQueueBlockageReason.PAUSED_DIAGNOSTIC_WORK,
        DiagnosticQueueBlockageReason.RECOVERY_REQUIRED,
        DiagnosticQueueBlockageReason.SOURCE_UNAVAILABLE,
        DiagnosticQueueBlockageReason.UNKNOWN,
    }
    assert set(DiagnosticQueueScope) == {
        DiagnosticQueueScope.DIAGNOSTIC_TASK,
        DiagnosticQueueScope.FORMAL_DIAGNOSTIC_CAMPAIGN,
        DiagnosticQueueScope.CAMPAIGN_NODES,
    }
    assert set(DiagnosticCacheFallbackState) == {
        DiagnosticCacheFallbackState.PRIMARY,
        DiagnosticCacheFallbackState.ACTIVE,
        DiagnosticCacheFallbackState.UNAVAILABLE,
        DiagnosticCacheFallbackState.UNKNOWN,
    }
    assert set(DiagnosticCacheLastRefreshResult) == {
        DiagnosticCacheLastRefreshResult.NOT_OBSERVED,
        DiagnosticCacheLastRefreshResult.SUCCEEDED,
        DiagnosticCacheLastRefreshResult.FALLBACK_SUCCEEDED,
        DiagnosticCacheLastRefreshResult.FAILED,
    }
    assert set(DiagnosticCacheCompatibility) == {
        DiagnosticCacheCompatibility.COMPATIBLE,
        DiagnosticCacheCompatibility.INCOMPATIBLE,
        DiagnosticCacheCompatibility.UNKNOWN,
    }
    assert set(DiagnosticCacheScope) == {
        DiagnosticCacheScope.REFERENCE_MARKET_PATHS,
        DiagnosticCacheScope.DIAGNOSTIC_EVIDENCE,
    }
    assert DiagnosticQueueRecoveryPhase.FAILED_RECOVERY.value == "failed_recovery"
    assert DiagnosticCacheRecoveryPhase.FAILED_RECOVERY.value == "failed_recovery"


def test_system_health_1_0_activates_the_read_only_six_feature_registry() -> None:
    assert SYSTEM_HEALTH_INTERFACE_VERSION.render() == "1.0"
    assert tuple(
        (descriptor.name, descriptor.version.render())
        for descriptor in ACTIVE_FEATURE_INTERFACES
    ) == (
        (FeatureModuleName.STRATEGY_LIBRARY, "1.0"),
        (FeatureModuleName.SCENARIO_LAB, "1.0"),
        (FeatureModuleName.DIAGNOSTIC_TASKS, "1.0"),
        (FeatureModuleName.RUN_MONITORING, "1.2"),
        (FeatureModuleName.EVIDENCE_AND_FINDINGS, "1.1"),
        (FeatureModuleName.SYSTEM_HEALTH, "1.0"),
    )

    operations = {
        name
        for name, member in inspect.getmembers(
            SystemHealthFeature,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    assert operations == {"close", "snapshot", "subscribe"}


def test_system_health_1_0_freezes_the_runtime_health_view_state() -> None:
    assert {item.value for item in RuntimeHealthClassification} == {
        "healthy",
        "degraded",
        "stale",
        "unavailable",
        "incompatible",
        "recovering",
        "recovered",
        "unknown",
    }
    assert {item.value for item in SystemHealthPresentationState} == {
        "healthy",
        "degraded",
        "stale",
        "unavailable",
        "incompatible",
        "recovering",
        "recovered",
        "unknown",
    }
    assert {field.name for field in fields(SystemHealthViewState)} == {
        "interface_version",
        "revision",
        "observed_at",
        "last_reliable_at",
        "freshness",
        "age",
        "freshness_threshold",
        "source",
        "context",
        "phase",
        "presentation",
        "completeness",
        "components",
        "last_reliable_payload",
        "recovery_phase",
        "diagnostic_data_source",
        "diagnostic_queue",
        "diagnostic_cache",
        "error",
        "diagnostic_context",
        "overall_classification",
        "component_impacts",
    }

    component = RuntimeHealthComponent(
        identity=RuntimeHealthComponentIdentity.APPLICATION_RUNTIME,
        classification=RuntimeHealthClassification.HEALTHY,
        revision=1,
        observed_at=NOW,
        last_successful_observation_at=NOW,
        explanation="Diagnostics runtime is ready.",
    )
    queue = DiagnosticQueueHealthComponent(
        classification=DiagnosticQueueHealthClassification.HEALTHY,
        revision=1,
        observed_at=NOW,
        freshness=Freshness.FRESH,
        age=timedelta(0),
        freshness_threshold=timedelta(seconds=30),
        pending_count=0,
        running_count=0,
        blocked_count=0,
        oldest_pending_age=None,
        consumer_availability=DiagnosticQueueConsumerAvailability.AVAILABLE,
        blockage_reason=DiagnosticQueueBlockageReason.NONE,
        affected_scope=(DiagnosticQueueScope.DIAGNOSTIC_TASK,),
        recovery_phase=DiagnosticQueueRecoveryPhase.IDLE,
        explanation="The diagnostic queue is empty and available.",
        error=None,
    )
    cache = DiagnosticCacheHealthComponent(
        classification=DiagnosticCacheHealthClassification.UNKNOWN,
        revision=1,
        observed_at=NOW,
        freshness=Freshness.AWAITING_FIRST_STATE,
        age=timedelta(0),
        freshness_threshold=timedelta(seconds=30),
        generation=None,
        fallback=DiagnosticCacheFallbackState.UNKNOWN,
        last_refresh_result=DiagnosticCacheLastRefreshResult.NOT_OBSERVED,
        compatibility=DiagnosticCacheCompatibility.UNKNOWN,
        affected_scope=(DiagnosticCacheScope.REFERENCE_MARKET_PATHS,),
        recovery_phase=DiagnosticCacheRecoveryPhase.IDLE,
        explanation="No diagnostic cache refresh has been observed.",
        error=None,
    )
    identity = DiagnosticDataSourceIdentity(
        public_id="admitted-source-0123456789abcdef",
        provider="Provider 01234567",
        dataset="Dataset 89abcdef",
        version="Version fedcba98",
    )
    observation = DiagnosticDataSourceObservation(
        identity=identity,
        revision=DiagnosticDataSourceRevision(1),
        generation=SourceGenerationId(1),
        observed_at=NOW,
    )
    data_source = DiagnosticDataSourceHealthComponent(
        identity=(
            DiagnosticDataSourceComponentIdentity.ADMITTED_HISTORICAL_MARKET_DATA
        ),
        classification=DiagnosticDataSourceHealthClassification.HEALTHY,
        connection=DiagnosticDataSourceConnectionState.CONNECTED,
        fallback=DiagnosticDataSourceFallbackState.PRIMARY,
        accepted_revision=DiagnosticDataSourceRevision(1),
        accepted_generation=SourceGenerationId(1),
        observed_at=NOW,
        freshness=Freshness.FRESH,
        age=timedelta(0),
        freshness_threshold=timedelta(seconds=30),
        last_reliable_observation=observation,
        affected_scope=(DiagnosticDataSourceScope.SCENARIO_INPUTS,),
        recovery_phase=DiagnosticDataSourceRecoveryPhase.IDLE,
        explanation="The admitted diagnostic data source is fresh.",
        error=None,
    )
    state = SystemHealthViewState(
        interface_version=SYSTEM_HEALTH_INTERFACE_VERSION,
        revision=1,
        observed_at=NOW,
        last_reliable_at=NOW,
        freshness=Freshness.FRESH,
        age=timedelta(0),
        freshness_threshold=timedelta(seconds=30),
        source=SystemHealthSource(
            kind=SourceKind.LIVE_RUNTIME,
            identity="diagnostics_application",
            generation=SourceGenerationId(1),
        ),
        context=SystemHealthContext(),
        phase=ViewPhase.READY,
        presentation=SystemHealthPresentationState.HEALTHY,
        completeness=Completeness.COMPLETE,
        components=(component,),
        last_reliable_payload=(component,),
        recovery_phase=RuntimeHealthRecoveryPhase.IDLE,
        diagnostic_data_source=data_source,
        diagnostic_queue=queue,
        diagnostic_cache=cache,
        error=None,
    )

    assert state.components == (component,)
    assert state.diagnostic_data_source is data_source
    assert state.diagnostic_queue is queue
    assert state.diagnostic_cache is cache
    assert "metrics" not in {field.name for field in fields(state)}
    assert isinstance(state.components, tuple)
    with pytest.raises(FrozenInstanceError):
        component.explanation = "mutable"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        state.revision = 2  # type: ignore[misc]
    with pytest.raises(ValueError, match="component revisions"):
        replace(state, diagnostic_queue=replace(queue, revision=2))


def test_data_source_identity_and_component_fail_closed() -> None:
    for unsafe_provider in (
        "redis://diagnostics",
        r"C:\secrets\source.db",
        "token=super-secret",
        "credential bundle",
    ):
        with pytest.raises(ValueError):
            DiagnosticDataSourceIdentity(
                public_id="admitted-source-0123456789abcdef",
                provider=unsafe_provider,
                dataset="Dataset 89abcdef",
                version="Version fedcba98",
            )
    with pytest.raises(ValueError, match="opaque"):
        DiagnosticDataSourceIdentity(
            public_id="admitted-source-token-super-secret",
            provider="Provider 01234567",
            dataset="Dataset 89abcdef",
            version="Version fedcba98",
        )
    with pytest.raises(TypeError, match="classification"):
        DiagnosticDataSourceHealthComponent(
            identity=(
                DiagnosticDataSourceComponentIdentity.ADMITTED_HISTORICAL_MARKET_DATA
            ),
            classification="healthy",  # type: ignore[arg-type]
            connection=DiagnosticDataSourceConnectionState.CONNECTED,
            fallback=DiagnosticDataSourceFallbackState.PRIMARY,
            accepted_revision=None,
            accepted_generation=None,
            observed_at=NOW,
            freshness=Freshness.FRESH,
            age=timedelta(0),
            freshness_threshold=timedelta(seconds=30),
            last_reliable_observation=None,
            affected_scope=(DiagnosticDataSourceScope.SCENARIO_INPUTS,),
            recovery_phase=DiagnosticDataSourceRecoveryPhase.IDLE,
            explanation="A typed state is required.",
            error=None,
        )


def test_system_health_error_is_typed_safe_and_runtime_scoped() -> None:
    error = SystemHealthError(
        code=SystemHealthErrorCode.NO_AUTHORITATIVE_OBSERVATION,
        explanation="No authoritative Runtime Health observation is available.",
        retryable=True,
        correlation_identity="runtime-health-1",
    )
    assert error.code is SystemHealthErrorCode.NO_AUTHORITATIVE_OBSERVATION
    with pytest.raises(TypeError, match="SystemHealthErrorCode"):
        SystemHealthError(
            code="raw-error",  # type: ignore[arg-type]
            explanation="Untyped errors fail closed.",
            retryable=False,
        )


def test_system_health_surface_contains_no_control_or_trading_operation() -> None:
    operations = {
        name.casefold()
        for name, member in inspect.getmembers(
            SystemHealthFeature,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    forbidden = (
        "buy",
        "sell",
        "order",
        "broker",
        "transaction",
        "dispatch",
        "restart",
        "reconnect",
        "clear",
        "purge",
        "migrate",
        "execute",
        "command",
    )
    assert not {
        operation
        for operation in operations
        if any(marker in operation for marker in forbidden)
    }
