from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone

import pytest

from app.features import (
    ACTIVE_FEATURE_INTERFACES,
    SYSTEM_HEALTH_INTERFACE_VERSION,
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
        "error",
    }

    component = RuntimeHealthComponent(
        identity=RuntimeHealthComponentIdentity.APPLICATION_RUNTIME,
        classification=RuntimeHealthClassification.HEALTHY,
        revision=1,
        observed_at=NOW,
        last_successful_observation_at=NOW,
        explanation="Diagnostics runtime is ready.",
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
        error=None,
    )

    assert state.components == (component,)
    assert isinstance(state.components, tuple)
    with pytest.raises(FrozenInstanceError):
        component.explanation = "mutable"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        state.revision = 2  # type: ignore[misc]


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
