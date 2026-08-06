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


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _require_safe_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} cannot be empty")
    if len(value) > 512:
        raise ValueError(f"{label} must be bounded")


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
