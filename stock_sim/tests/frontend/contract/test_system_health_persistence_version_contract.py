from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone

import pytest

from app.features import (
    ACTIVE_FEATURE_INTERFACES,
    HealthCompatibilityState,
    PersistenceAvailability,
    PersistenceHealthComponent,
    PersistenceReopenVerification,
    RuntimeHealthClassification,
    RuntimeHealthRecoveryPhase,
    SystemHealthAffectedScope,
    SystemHealthComponentIdentity,
    SystemHealthError,
    SystemHealthErrorCode,
    SystemHealthRecoveryExpectation,
    VersionHealthComponent,
)
from app.features.run_monitoring import Freshness


NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


def test_persistence_and_version_health_components_are_finite_typed_and_immutable() -> None:
    persistence = PersistenceHealthComponent(
        identity=SystemHealthComponentIdentity.DIAGNOSTIC_PERSISTENCE,
        classification=RuntimeHealthClassification.HEALTHY,
        revision=7,
        observed_at=NOW,
        last_successful_observation_at=NOW,
        freshness=Freshness.FRESH,
        age=timedelta(0),
        freshness_threshold=timedelta(seconds=30),
        availability=PersistenceAvailability.AVAILABLE,
        schema_compatibility=HealthCompatibilityState.COMPATIBLE,
        schema_head="0021_diagnostic_selection_dependency_invalidation",
        supported_schema_head="0021_diagnostic_selection_dependency_invalidation",
        last_successful_durable_read_at=NOW,
        last_successful_durable_write_at=NOW,
        reopen_verification=PersistenceReopenVerification.VERIFIED,
        affected_scope=SystemHealthAffectedScope.DIAGNOSTIC_PERSISTENCE,
        recovery_phase=RuntimeHealthRecoveryPhase.RECOVERED,
        explanation="Diagnostic persistence is available and compatible.",
        error=None,
    )
    version = VersionHealthComponent(
        identity=SystemHealthComponentIdentity.VERSION_COMPATIBILITY,
        classification=RuntimeHealthClassification.HEALTHY,
        revision=7,
        observed_at=NOW,
        last_successful_observation_at=NOW,
        product_build="stock-sim/0.0.1",
        feature_interfaces=ACTIVE_FEATURE_INTERFACES,
        dependency_lock_identity="sha256:" + "a" * 64,
        release_manifest_compatibility=HealthCompatibilityState.COMPATIBLE,
        runner_version="strategy-diagnostics-v1",
        schema_version="0021_diagnostic_selection_dependency_invalidation",
        evidence_format_version="diagnostic-evidence.v1",
        manifest_format_version="reproduction-manifest.v1",
        reproduction_manifest_compatibility=(
            HealthCompatibilityState.COMPATIBLE
        ),
        affected_scope=SystemHealthAffectedScope.VERSION_COMPATIBILITY,
        recovery_phase=RuntimeHealthRecoveryPhase.RECOVERED,
        explanation="Product and diagnostic format versions are compatible.",
        error=None,
    )

    assert persistence.identity is (
        SystemHealthComponentIdentity.DIAGNOSTIC_PERSISTENCE
    )
    assert version.feature_interfaces == ACTIVE_FEATURE_INTERFACES
    assert version.reproduction_manifest_compatibility is (
        HealthCompatibilityState.COMPATIBLE
    )
    with pytest.raises(FrozenInstanceError):
        persistence.schema_head = "mutated"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        version.runner_version = "mutated"  # type: ignore[misc]


def test_structured_errors_expose_only_safe_diagnostic_impact_facts() -> None:
    error = SystemHealthError(
        code=SystemHealthErrorCode.PERSISTENCE_SCHEMA_INCOMPATIBLE,
        explanation="Diagnostic Persistence schema is incompatible.",
        affected_scope=SystemHealthAffectedScope.DIAGNOSTIC_PERSISTENCE,
        retryable=False,
        recovery_expectation=SystemHealthRecoveryExpectation.COMPATIBLE_BUILD_REQUIRED,
        correlation_identity="health-4f8a",
    )

    assert {field.name for field in fields(error)} == {
        "code",
        "explanation",
        "affected_scope",
        "retryable",
        "recovery_expectation",
        "correlation_identity",
    }
    with pytest.raises(ValueError):
        SystemHealthError(
            code=SystemHealthErrorCode.OBSERVATION_FAILED,
            explanation="A safe read failed.",
            affected_scope=SystemHealthAffectedScope.APPLICATION_RUNTIME,
            retryable=True,
            recovery_expectation=SystemHealthRecoveryExpectation.AUTOMATIC_RETRY,
            correlation_identity=r"C:\private\database.sqlite",
        )
    for unsafe_identity in (
        "diagnostics.sqlite3",
        "SELECT users",
        "diagnostic_reproduction_manifests",
    ):
        with pytest.raises(ValueError):
            SystemHealthError(
                code=SystemHealthErrorCode.OBSERVATION_FAILED,
                explanation="A safe read failed.",
                affected_scope=SystemHealthAffectedScope.APPLICATION_RUNTIME,
                retryable=True,
                recovery_expectation=(
                    SystemHealthRecoveryExpectation.AUTOMATIC_RETRY
                ),
                correlation_identity=unsafe_identity,
            )
    with pytest.raises(ValueError):
        SystemHealthError(
            code=SystemHealthErrorCode.OBSERVATION_FAILED,
            explanation="C:/private/database.sqlite SELECT diagnostics",
            affected_scope=SystemHealthAffectedScope.APPLICATION_RUNTIME,
            retryable=True,
            recovery_expectation=SystemHealthRecoveryExpectation.AUTOMATIC_RETRY,
        )
