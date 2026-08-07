"""Read-only System Health Feature Interface 1.0 contract."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Protocol, runtime_checkable

from .run_monitoring import (
    Completeness,
    Freshness,
    SourceGenerationId,
    SourceKind,
    Subscription,
    ViewPhase,
)
from .versioning import FeatureInterfaceVersion


class RuntimeHealthClassification(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class RuntimeHealthComponentIdentity(str, Enum):
    APPLICATION_RUNTIME = "application_runtime"


class RuntimeHealthRecoveryPhase(str, Enum):
    IDLE = "idle"
    DISCONNECTED = "disconnected"
    REREADING = "rereading"
    RECOVERED = "recovered"
    FAILED = "failed"


class DiagnosticQueueHealthClassification(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    RECOVERING = "recovering"
    UNKNOWN = "unknown"


class DiagnosticQueueConsumerAvailability(str, Enum):
    AVAILABLE = "available"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class DiagnosticQueueBlockageReason(str, Enum):
    NONE = "none"
    PAUSED_DIAGNOSTIC_WORK = "paused_diagnostic_work"
    RECOVERY_REQUIRED = "recovery_required"
    SOURCE_UNAVAILABLE = "source_unavailable"
    UNKNOWN = "unknown"


class DiagnosticQueueScope(str, Enum):
    DIAGNOSTIC_TASK = "diagnostic_task"
    FORMAL_DIAGNOSTIC_CAMPAIGN = "formal_diagnostic_campaign"
    CAMPAIGN_NODES = "campaign_nodes"


class DiagnosticQueueRecoveryPhase(str, Enum):
    IDLE = "idle"
    RECOVERING = "recovering"
    RECOVERED = "recovered"
    FAILED_RECOVERY = "failed_recovery"


class DiagnosticCacheHealthClassification(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    FALLBACK = "fallback"
    INCOMPATIBLE = "incompatible"
    UNAVAILABLE = "unavailable"
    RECOVERING = "recovering"
    UNKNOWN = "unknown"


class DiagnosticCacheFallbackState(str, Enum):
    PRIMARY = "primary"
    ACTIVE = "active"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class DiagnosticCacheLastRefreshResult(str, Enum):
    NOT_OBSERVED = "not_observed"
    SUCCEEDED = "succeeded"
    FALLBACK_SUCCEEDED = "fallback_succeeded"
    FAILED = "failed"


class DiagnosticCacheCompatibility(str, Enum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


class DiagnosticCacheScope(str, Enum):
    REFERENCE_MARKET_PATHS = "reference_market_paths"
    DIAGNOSTIC_EVIDENCE = "diagnostic_evidence"


class DiagnosticCacheRecoveryPhase(str, Enum):
    IDLE = "idle"
    RECOVERING = "recovering"
    RECOVERED = "recovered"
    FAILED_RECOVERY = "failed_recovery"


class SystemHealthPresentationState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class SystemHealthErrorCode(str, Enum):
    NO_AUTHORITATIVE_OBSERVATION = "runtime_health_no_authoritative_observation"
    OBSERVATION_FAILED = "runtime_health_observation_failed"
    SOURCE_DISCONNECTED = "runtime_health_source_disconnected"
    AUTHORITATIVE_REREAD_FAILED = "runtime_health_authoritative_reread_failed"
    DIAGNOSTIC_QUEUE_NO_AUTHORITATIVE_OBSERVATION = (
        "diagnostic_queue_no_authoritative_observation"
    )
    DIAGNOSTIC_QUEUE_READ_FAILED = "diagnostic_queue_read_failed"
    DIAGNOSTIC_CACHE_NO_AUTHORITATIVE_OBSERVATION = (
        "diagnostic_cache_no_authoritative_observation"
    )
    DIAGNOSTIC_CACHE_READ_FAILED = "diagnostic_cache_read_failed"


@dataclass(frozen=True, slots=True)
class SystemHealthError:
    code: SystemHealthErrorCode
    explanation: str
    retryable: bool
    correlation_identity: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, SystemHealthErrorCode):
            raise TypeError("code must be a SystemHealthErrorCode")
        _require_safe_text(self.explanation, "System Health explanation")
        if not isinstance(self.retryable, bool):
            raise TypeError("retryable must be a bool")
        if self.correlation_identity is not None:
            _require_safe_text(
                self.correlation_identity,
                "System Health correlation identity",
            )


@dataclass(frozen=True, slots=True)
class RuntimeHealthComponent:
    identity: RuntimeHealthComponentIdentity
    classification: RuntimeHealthClassification
    revision: int
    observed_at: datetime
    last_successful_observation_at: datetime | None
    explanation: str

    def __post_init__(self) -> None:
        if not isinstance(self.identity, RuntimeHealthComponentIdentity):
            raise TypeError("identity must be a RuntimeHealthComponentIdentity")
        if not isinstance(self.classification, RuntimeHealthClassification):
            raise TypeError("classification must be a RuntimeHealthClassification")
        if not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("Runtime Health revision must be positive")
        _require_aware(self.observed_at, "Runtime Health observation time")
        if self.last_successful_observation_at is not None:
            _require_aware(
                self.last_successful_observation_at,
                "Runtime Health last successful observation time",
            )
        _require_safe_text(self.explanation, "Runtime Health explanation")


@dataclass(frozen=True, slots=True)
class DiagnosticQueueHealthComponent:
    classification: DiagnosticQueueHealthClassification
    revision: int
    observed_at: datetime
    freshness: Freshness
    age: timedelta
    freshness_threshold: timedelta
    pending_count: int
    running_count: int
    blocked_count: int
    oldest_pending_age: timedelta | None
    consumer_availability: DiagnosticQueueConsumerAvailability
    blockage_reason: DiagnosticQueueBlockageReason
    affected_scope: tuple[DiagnosticQueueScope, ...]
    recovery_phase: DiagnosticQueueRecoveryPhase
    explanation: str
    error: SystemHealthError | None

    def __post_init__(self) -> None:
        if not isinstance(self.classification, DiagnosticQueueHealthClassification):
            raise TypeError("classification must be a DiagnosticQueueHealthClassification")
        _require_component_revision(self.revision, "Diagnostic Queue Health")
        _require_aware(self.observed_at, "Diagnostic Queue Health observation time")
        _require_freshness_window(
            self.age,
            self.freshness_threshold,
            "Diagnostic Queue Health",
        )
        for value, label in (
            (self.pending_count, "pending count"),
            (self.running_count, "running count"),
            (self.blocked_count, "blocked count"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"Diagnostic Queue Health {label} must be non-negative")
        if self.oldest_pending_age is not None and self.oldest_pending_age < timedelta(0):
            raise ValueError("Diagnostic Queue Health oldest pending age cannot be negative")
        if not isinstance(self.consumer_availability, DiagnosticQueueConsumerAvailability):
            raise TypeError("consumer_availability must be typed")
        if not isinstance(self.blockage_reason, DiagnosticQueueBlockageReason):
            raise TypeError("blockage_reason must be typed")
        _require_typed_scope(self.affected_scope, DiagnosticQueueScope, "Diagnostic Queue")
        if not isinstance(self.recovery_phase, DiagnosticQueueRecoveryPhase):
            raise TypeError("recovery_phase must be typed")
        _require_safe_text(self.explanation, "Diagnostic Queue Health explanation")
        if self.error is not None and not isinstance(self.error, SystemHealthError):
            raise TypeError("error must be a SystemHealthError")


@dataclass(frozen=True, slots=True)
class DiagnosticCacheHealthComponent:
    classification: DiagnosticCacheHealthClassification
    revision: int
    observed_at: datetime
    freshness: Freshness
    age: timedelta
    freshness_threshold: timedelta
    generation: SourceGenerationId | None
    fallback: DiagnosticCacheFallbackState
    last_refresh_result: DiagnosticCacheLastRefreshResult
    compatibility: DiagnosticCacheCompatibility
    affected_scope: tuple[DiagnosticCacheScope, ...]
    recovery_phase: DiagnosticCacheRecoveryPhase
    explanation: str
    error: SystemHealthError | None

    def __post_init__(self) -> None:
        if not isinstance(self.classification, DiagnosticCacheHealthClassification):
            raise TypeError("classification must be a DiagnosticCacheHealthClassification")
        _require_component_revision(self.revision, "Diagnostic Cache Health")
        _require_aware(self.observed_at, "Diagnostic Cache Health observation time")
        _require_freshness_window(
            self.age,
            self.freshness_threshold,
            "Diagnostic Cache Health",
        )
        if self.generation is not None and not isinstance(self.generation, SourceGenerationId):
            raise TypeError("generation must be a SourceGenerationId")
        if not isinstance(self.fallback, DiagnosticCacheFallbackState):
            raise TypeError("fallback must be typed")
        if not isinstance(self.last_refresh_result, DiagnosticCacheLastRefreshResult):
            raise TypeError("last_refresh_result must be typed")
        if not isinstance(self.compatibility, DiagnosticCacheCompatibility):
            raise TypeError("compatibility must be typed")
        _require_typed_scope(self.affected_scope, DiagnosticCacheScope, "Diagnostic Cache")
        if not isinstance(self.recovery_phase, DiagnosticCacheRecoveryPhase):
            raise TypeError("recovery_phase must be typed")
        _require_safe_text(self.explanation, "Diagnostic Cache Health explanation")
        if self.error is not None and not isinstance(self.error, SystemHealthError):
            raise TypeError("error must be a SystemHealthError")


@dataclass(frozen=True, slots=True)
class SystemHealthSource:
    kind: SourceKind
    identity: str
    generation: SourceGenerationId

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SourceKind):
            raise TypeError("kind must be a SourceKind")
        _require_safe_text(self.identity, "System Health source identity")
        if not isinstance(self.generation, SourceGenerationId):
            raise TypeError("generation must be a SourceGenerationId")


@dataclass(frozen=True, slots=True)
class SystemHealthContext:
    """The Runtime-only 1.0 context; contextual identity is deferred."""


@dataclass(frozen=True, slots=True)
class SystemHealthViewState:
    interface_version: FeatureInterfaceVersion
    revision: int
    observed_at: datetime
    last_reliable_at: datetime | None
    freshness: Freshness
    age: timedelta
    freshness_threshold: timedelta
    source: SystemHealthSource
    context: SystemHealthContext
    phase: ViewPhase
    presentation: SystemHealthPresentationState
    completeness: Completeness
    components: tuple[RuntimeHealthComponent, ...]
    last_reliable_payload: RuntimeHealthComponent | None
    recovery_phase: RuntimeHealthRecoveryPhase
    diagnostic_queue: DiagnosticQueueHealthComponent
    diagnostic_cache: DiagnosticCacheHealthComponent
    error: SystemHealthError | None

    def __post_init__(self) -> None:
        if not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("System Health view revision must be positive")
        _require_aware(self.observed_at, "System Health observation time")
        if self.last_reliable_at is not None:
            _require_aware(self.last_reliable_at, "last reliable time")
        if self.age < timedelta(0):
            raise ValueError("System Health age cannot be negative")
        if self.freshness_threshold <= timedelta(0):
            raise ValueError("System Health freshness threshold must be positive")
        if not isinstance(self.components, tuple):
            raise TypeError("System Health components must be an immutable tuple")
        if len(self.components) > 1:
            raise ValueError("System Health 1.0 exposes only Runtime Health")
        if self.components and self.components[0].identity is not (
            RuntimeHealthComponentIdentity.APPLICATION_RUNTIME
        ):
            raise ValueError("System Health 1.0 exposes only Runtime Health")
        if not isinstance(self.diagnostic_queue, DiagnosticQueueHealthComponent):
            raise TypeError("diagnostic_queue must be typed")
        if not isinstance(self.diagnostic_cache, DiagnosticCacheHealthComponent):
            raise TypeError("diagnostic_cache must be typed")
        if (
            self.diagnostic_queue.revision != self.revision
            or self.diagnostic_cache.revision != self.revision
        ):
            raise ValueError(
                "Queue and Cache component revisions must compose the System Health revision"
            )


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _require_safe_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} cannot be empty")
    if len(value) > 512:
        raise ValueError(f"{label} must be bounded")


def _require_component_revision(value: int, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label} revision must be positive")


def _require_freshness_window(age: timedelta, threshold: timedelta, label: str) -> None:
    if age < timedelta(0):
        raise ValueError(f"{label} age cannot be negative")
    if threshold <= timedelta(0):
        raise ValueError(f"{label} freshness threshold must be positive")


def _require_typed_scope(
    value: tuple[object, ...],
    enum_type: type[Enum],
    label: str,
) -> None:
    if not isinstance(value, tuple):
        raise TypeError(f"{label} affected scope must be an immutable tuple")
    if not value or any(not isinstance(item, enum_type) for item in value):
        raise ValueError(f"{label} affected scope must be finite and typed")


SystemHealthObserver = Callable[[SystemHealthViewState], None]


@runtime_checkable
class SystemHealthFeature(Protocol):
    @property
    def interface_version(self) -> FeatureInterfaceVersion: ...

    def snapshot(
        self,
        context: "SystemHealthContext",
    ) -> "SystemHealthViewState": ...

    def subscribe(
        self,
        context: "SystemHealthContext",
        observer: SystemHealthObserver,
    ) -> Subscription: ...

    def close(self) -> None: ...


__all__ = [
    "DiagnosticCacheCompatibility",
    "DiagnosticCacheFallbackState",
    "DiagnosticCacheHealthClassification",
    "DiagnosticCacheHealthComponent",
    "DiagnosticCacheLastRefreshResult",
    "DiagnosticCacheRecoveryPhase",
    "DiagnosticCacheScope",
    "DiagnosticQueueBlockageReason",
    "DiagnosticQueueConsumerAvailability",
    "DiagnosticQueueHealthClassification",
    "DiagnosticQueueHealthComponent",
    "DiagnosticQueueRecoveryPhase",
    "DiagnosticQueueScope",
    "RuntimeHealthClassification",
    "RuntimeHealthComponent",
    "RuntimeHealthComponentIdentity",
    "RuntimeHealthRecoveryPhase",
    "SystemHealthContext",
    "SystemHealthError",
    "SystemHealthErrorCode",
    "SystemHealthFeature",
    "SystemHealthObserver",
    "SystemHealthPresentationState",
    "SystemHealthSource",
    "SystemHealthViewState",
]
