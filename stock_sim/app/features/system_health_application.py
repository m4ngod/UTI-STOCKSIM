"""Feature-specific Runtime Health Application Interface 1.0."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ._diagnostics_application_access import (
    shared_diagnostics_application_access_gate,
)
from .diagnostics_application_ownership import (
    DiagnosticsApplicationIdentity,
    diagnostics_application_identity,
)
from .strategy_diagnostics_v1_read_model import SourceRevisionToken
from .system_health import (
    DiagnosticCacheCompatibility,
    DiagnosticCacheFallbackState,
    DiagnosticCacheLastRefreshResult,
    DiagnosticCacheScope,
    DiagnosticQueueBlockageReason,
    DiagnosticQueueConsumerAvailability,
    DiagnosticQueueScope,
    RuntimeHealthClassification,
)

if TYPE_CHECKING:
    from strategy_diagnostics.application import DiagnosticsApplication


@dataclass(frozen=True, slots=True)
class RuntimeHealthApplicationVersion:
    major: int
    minor: int

    def render(self) -> str:
        return f"{self.major}.{self.minor}"


RUNTIME_HEALTH_APPLICATION_INTERFACE_VERSION = RuntimeHealthApplicationVersion(
    major=1,
    minor=0,
)


class RuntimeHealthApplicationAvailability(str, Enum):
    READY = "ready"
    NO_AUTHORITATIVE_OBSERVATION = "no_authoritative_observation"
    FAILED = "failed"


class RuntimeHealthApplicationErrorCode(str, Enum):
    NO_AUTHORITATIVE_OBSERVATION = "runtime_health_no_authoritative_observation"
    READ_FAILED = "runtime_health_read_failed"


class DiagnosticQueueApplicationAvailability(str, Enum):
    READY = "ready"
    NO_AUTHORITATIVE_OBSERVATION = "no_authoritative_observation"
    FAILED = "failed"


class DiagnosticQueueApplicationErrorCode(str, Enum):
    NO_AUTHORITATIVE_OBSERVATION = "diagnostic_queue_no_authoritative_observation"
    READ_FAILED = "diagnostic_queue_read_failed"


class DiagnosticCacheApplicationAvailability(str, Enum):
    READY = "ready"
    NO_AUTHORITATIVE_OBSERVATION = "no_authoritative_observation"
    FAILED = "failed"


class DiagnosticCacheApplicationErrorCode(str, Enum):
    NO_AUTHORITATIVE_OBSERVATION = "diagnostic_cache_no_authoritative_observation"
    READ_FAILED = "diagnostic_cache_read_failed"


@dataclass(frozen=True, slots=True)
class RuntimeHealthApplicationError:
    code: RuntimeHealthApplicationErrorCode
    explanation: str
    retryable: bool
    correlation_identity: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, RuntimeHealthApplicationErrorCode):
            raise TypeError("code must be a RuntimeHealthApplicationErrorCode")
        if not self.explanation.strip() or len(self.explanation) > 512:
            raise ValueError("Runtime Health error explanation must be bounded")


@dataclass(frozen=True, slots=True)
class RuntimeHealthApplicationObservation:
    classification: RuntimeHealthClassification
    observed_at: datetime
    explanation: str

    def __post_init__(self) -> None:
        if not isinstance(self.classification, RuntimeHealthClassification):
            raise TypeError("classification must be a RuntimeHealthClassification")
        _require_aware(self.observed_at)
        if not self.explanation.strip() or len(self.explanation) > 512:
            raise ValueError("Runtime Health explanation must be bounded")


@dataclass(frozen=True, slots=True)
class RuntimeHealthApplicationResult:
    availability: RuntimeHealthApplicationAvailability
    observation: RuntimeHealthApplicationObservation | None
    source_token: SourceRevisionToken | None
    observed_at: datetime
    error: RuntimeHealthApplicationError | None

    def __post_init__(self) -> None:
        if not isinstance(self.availability, RuntimeHealthApplicationAvailability):
            raise TypeError(
                "availability must be a RuntimeHealthApplicationAvailability"
            )
        _require_aware(self.observed_at)
        if self.availability is RuntimeHealthApplicationAvailability.READY:
            if self.observation is None or self.source_token is None:
                raise ValueError("Ready Runtime Health requires an observation")
            if self.error is not None:
                raise ValueError("Ready Runtime Health cannot carry an error")
        elif self.observation is not None:
            raise ValueError("Unavailable Runtime Health cannot carry an observation")


@dataclass(frozen=True, slots=True)
class DiagnosticQueueApplicationError:
    code: DiagnosticQueueApplicationErrorCode
    explanation: str
    retryable: bool

    def __post_init__(self) -> None:
        if not isinstance(self.code, DiagnosticQueueApplicationErrorCode):
            raise TypeError("code must be a DiagnosticQueueApplicationErrorCode")
        _require_safe_text(self.explanation, "Diagnostic Queue error")


@dataclass(frozen=True, slots=True)
class DiagnosticQueueApplicationObservation:
    pending_count: int
    running_count: int
    blocked_count: int
    oldest_pending_at: datetime | None
    consumer_availability: DiagnosticQueueConsumerAvailability
    blockage_reason: DiagnosticQueueBlockageReason
    affected_scope: tuple[DiagnosticQueueScope, ...]
    observed_at: datetime
    explanation: str

    def __post_init__(self) -> None:
        for count in (self.pending_count, self.running_count, self.blocked_count):
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError("Diagnostic Queue counts must be non-negative")
        if self.oldest_pending_at is not None:
            _require_aware(self.oldest_pending_at)
        if not isinstance(self.consumer_availability, DiagnosticQueueConsumerAvailability):
            raise TypeError("consumer availability must be typed")
        if not isinstance(self.blockage_reason, DiagnosticQueueBlockageReason):
            raise TypeError("blockage reason must be typed")
        if not self.affected_scope or any(
            not isinstance(item, DiagnosticQueueScope)
            for item in self.affected_scope
        ):
            raise ValueError("affected scope must be finite and typed")
        _require_aware(self.observed_at)
        _require_safe_text(self.explanation, "Diagnostic Queue explanation")


@dataclass(frozen=True, slots=True)
class DiagnosticQueueApplicationResult:
    availability: DiagnosticQueueApplicationAvailability
    observation: DiagnosticQueueApplicationObservation | None
    source_token: SourceRevisionToken | None
    observed_at: datetime
    error: DiagnosticQueueApplicationError | None

    def __post_init__(self) -> None:
        _validate_application_result(
            self.availability,
            DiagnosticQueueApplicationAvailability.READY,
            self.observation,
            self.source_token,
            self.error,
            "Diagnostic Queue",
        )
        _require_aware(self.observed_at)


@dataclass(frozen=True, slots=True)
class DiagnosticCacheApplicationError:
    code: DiagnosticCacheApplicationErrorCode
    explanation: str
    retryable: bool

    def __post_init__(self) -> None:
        if not isinstance(self.code, DiagnosticCacheApplicationErrorCode):
            raise TypeError("code must be a DiagnosticCacheApplicationErrorCode")
        _require_safe_text(self.explanation, "Diagnostic Cache error")


@dataclass(frozen=True, slots=True)
class DiagnosticCacheApplicationObservation:
    generation: int | None
    fallback: DiagnosticCacheFallbackState
    last_refresh_result: DiagnosticCacheLastRefreshResult
    compatibility: DiagnosticCacheCompatibility
    affected_scope: tuple[DiagnosticCacheScope, ...]
    last_refresh_at: datetime
    observed_at: datetime
    explanation: str

    def __post_init__(self) -> None:
        if self.generation is not None and self.generation < 1:
            raise ValueError("Diagnostic Cache generation must be positive")
        if not isinstance(self.fallback, DiagnosticCacheFallbackState):
            raise TypeError("fallback must be typed")
        if not isinstance(self.last_refresh_result, DiagnosticCacheLastRefreshResult):
            raise TypeError("last refresh result must be typed")
        if not isinstance(self.compatibility, DiagnosticCacheCompatibility):
            raise TypeError("compatibility must be typed")
        if not self.affected_scope or any(
            not isinstance(item, DiagnosticCacheScope)
            for item in self.affected_scope
        ):
            raise ValueError("affected scope must be finite and typed")
        _require_aware(self.last_refresh_at)
        _require_aware(self.observed_at)
        _require_safe_text(self.explanation, "Diagnostic Cache explanation")


@dataclass(frozen=True, slots=True)
class DiagnosticCacheApplicationResult:
    availability: DiagnosticCacheApplicationAvailability
    observation: DiagnosticCacheApplicationObservation | None
    source_token: SourceRevisionToken | None
    observed_at: datetime
    error: DiagnosticCacheApplicationError | None

    def __post_init__(self) -> None:
        _validate_application_result(
            self.availability,
            DiagnosticCacheApplicationAvailability.READY,
            self.observation,
            self.source_token,
            self.error,
            "Diagnostic Cache",
        )
        _require_aware(self.observed_at)


@runtime_checkable
class StrategyDiagnosticsV1SystemHealthApplication(Protocol):
    @property
    def interface_version(self) -> RuntimeHealthApplicationVersion: ...

    def read_runtime_health(self) -> RuntimeHealthApplicationResult: ...

    def read_diagnostic_queue_health(
        self,
    ) -> DiagnosticQueueApplicationResult: ...

    def read_diagnostic_cache_health(
        self,
    ) -> DiagnosticCacheApplicationResult: ...


class LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter:
    """Translate the real DiagnosticsApplication lifecycle to safe typed health."""

    def __init__(
        self,
        application: DiagnosticsApplication,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._application = application
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._application_access_gate = (
            shared_diagnostics_application_access_gate(application)
        )

    @property
    def interface_version(self) -> RuntimeHealthApplicationVersion:
        return RUNTIME_HEALTH_APPLICATION_INTERFACE_VERSION

    @property
    def application_identity(self) -> DiagnosticsApplicationIdentity:
        return diagnostics_application_identity(self._application)

    def read_runtime_health(self) -> RuntimeHealthApplicationResult:
        observed_at = self._clock()
        _require_aware(observed_at)
        try:
            with self._application_access_gate:
                state = self._application.status()
        except RuntimeError:
            return _application_failure(
                observed_at=observed_at,
                availability=(
                    RuntimeHealthApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
                ),
                code=(
                    RuntimeHealthApplicationErrorCode.NO_AUTHORITATIVE_OBSERVATION
                ),
                explanation=(
                    "No authoritative Runtime Health observation is available."
                ),
                retryable=True,
            )
        except Exception:  # noqa: BLE001 - redact every backend failure at the seam
            return _application_failure(
                observed_at=observed_at,
                availability=RuntimeHealthApplicationAvailability.FAILED,
                code=RuntimeHealthApplicationErrorCode.READ_FAILED,
                explanation="The authoritative Runtime Health read failed safely.",
                retryable=True,
            )

        normalized = str(state.status).strip().casefold()
        classification = (
            RuntimeHealthClassification.HEALTHY
            if normalized == "ready"
            else RuntimeHealthClassification.DEGRADED
            if normalized == "degraded"
            else RuntimeHealthClassification.UNAVAILABLE
        )
        explanation = (
            "Diagnostics runtime is ready."
            if classification is RuntimeHealthClassification.HEALTHY
            else "Diagnostics runtime reports degraded availability."
            if classification is RuntimeHealthClassification.DEGRADED
            else "Diagnostics runtime is unavailable."
        )
        token = hashlib.sha256(
            f"runtime-health|{normalized}|{state.workspace}".encode("utf-8")
        ).hexdigest()
        return RuntimeHealthApplicationResult(
            availability=RuntimeHealthApplicationAvailability.READY,
            observation=RuntimeHealthApplicationObservation(
                classification=classification,
                observed_at=observed_at,
                explanation=explanation,
            ),
            source_token=SourceRevisionToken(token),
            observed_at=observed_at,
            error=None,
        )

    def read_diagnostic_queue_health(self) -> DiagnosticQueueApplicationResult:
        observed_at = self._clock()
        _require_aware(observed_at)
        try:
            with self._application_access_gate:
                summary = self._application.diagnostic_task_queue_health()
        except RuntimeError:
            return _queue_application_failure(
                observed_at=observed_at,
                availability=(
                    DiagnosticQueueApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
                ),
                code=(
                    DiagnosticQueueApplicationErrorCode.NO_AUTHORITATIVE_OBSERVATION
                ),
                explanation=(
                    "No authoritative Diagnostic Queue observation is available."
                ),
            )
        except Exception:  # noqa: BLE001 - redact every backend failure at the seam
            return _queue_application_failure(
                observed_at=observed_at,
                availability=DiagnosticQueueApplicationAvailability.FAILED,
                code=DiagnosticQueueApplicationErrorCode.READ_FAILED,
                explanation="The authoritative Diagnostic Queue read failed safely.",
            )

        pending_count = summary.pending_count
        running_count = summary.running_count
        blocked_count = summary.blocked_count
        if blocked_count:
            consumer_availability = DiagnosticQueueConsumerAvailability.BLOCKED
            blockage_reason = DiagnosticQueueBlockageReason.PAUSED_DIAGNOSTIC_WORK
            explanation = "Diagnostic work is paused at a supported lifecycle boundary."
        elif pending_count and not running_count:
            consumer_availability = DiagnosticQueueConsumerAvailability.UNKNOWN
            blockage_reason = DiagnosticQueueBlockageReason.RECOVERY_REQUIRED
            explanation = "Diagnostic work is queued and awaiting a consumer observation."
        else:
            consumer_availability = DiagnosticQueueConsumerAvailability.AVAILABLE
            blockage_reason = DiagnosticQueueBlockageReason.NONE
            explanation = (
                "The Diagnostic Queue is empty and available."
                if not (pending_count or running_count or blocked_count)
                else "Diagnostic work is being consumed without a reported blockage."
            )
        scope_by_kind = {
            "diagnostic_task": DiagnosticQueueScope.DIAGNOSTIC_TASK,
            "formal_diagnostic_campaign": (
                DiagnosticQueueScope.FORMAL_DIAGNOSTIC_CAMPAIGN
            ),
            "campaign_node": DiagnosticQueueScope.CAMPAIGN_NODES,
        }
        affected_scope = tuple(
            scope_by_kind[item.value]
            for item in summary.affected_target_kinds
        )
        token_content = (
            "diagnostic-queue",
            summary.revision,
            pending_count,
            running_count,
            blocked_count,
            consumer_availability.value,
            blockage_reason.value,
            (
                None
                if summary.oldest_pending_at is None
                else summary.oldest_pending_at.isoformat()
            ),
            tuple(item.value for item in affected_scope),
        )
        return DiagnosticQueueApplicationResult(
            availability=DiagnosticQueueApplicationAvailability.READY,
            observation=DiagnosticQueueApplicationObservation(
                pending_count=pending_count,
                running_count=running_count,
                blocked_count=blocked_count,
                oldest_pending_at=summary.oldest_pending_at,
                consumer_availability=consumer_availability,
                blockage_reason=blockage_reason,
                affected_scope=affected_scope,
                observed_at=observed_at,
                explanation=explanation,
            ),
            source_token=SourceRevisionToken(
                hashlib.sha256(repr(token_content).encode("utf-8")).hexdigest()
            ),
            observed_at=observed_at,
            error=None,
        )

    def read_diagnostic_cache_health(self) -> DiagnosticCacheApplicationResult:
        observed_at = self._clock()
        _require_aware(observed_at)
        try:
            with self._application_access_gate:
                snapshot = self._application.diagnostic_cache_health()
        except RuntimeError:
            return _cache_application_failure(
                observed_at=observed_at,
                availability=(
                    DiagnosticCacheApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
                ),
                code=(
                    DiagnosticCacheApplicationErrorCode.NO_AUTHORITATIVE_OBSERVATION
                ),
                explanation=(
                    "No authoritative Diagnostic Cache observation is available."
                ),
            )
        except Exception:  # noqa: BLE001 - redact every backend failure at the seam
            return _cache_application_failure(
                observed_at=observed_at,
                availability=DiagnosticCacheApplicationAvailability.FAILED,
                code=DiagnosticCacheApplicationErrorCode.READ_FAILED,
                explanation="The authoritative Diagnostic Cache read failed safely.",
            )
        if snapshot is None or snapshot.observed_at is None:
            return _cache_application_failure(
                observed_at=observed_at,
                availability=(
                    DiagnosticCacheApplicationAvailability.NO_AUTHORITATIVE_OBSERVATION
                ),
                code=(
                    DiagnosticCacheApplicationErrorCode.NO_AUTHORITATIVE_OBSERVATION
                ),
                explanation=(
                    "No authoritative Diagnostic Cache observation is available."
                ),
            )
        fallback = DiagnosticCacheFallbackState(snapshot.fallback.value)
        refresh_result = DiagnosticCacheLastRefreshResult(
            snapshot.last_refresh_result.value
        )
        compatibility = DiagnosticCacheCompatibility(snapshot.compatibility.value)
        explanation = _cache_explanation(
            fallback=fallback,
            refresh_result=refresh_result,
            compatibility=compatibility,
        )
        token_content = (
            "diagnostic-cache",
            snapshot.generation,
            snapshot.observed_at.isoformat(),
            fallback.value,
            refresh_result.value,
            compatibility.value,
            snapshot.affected_artifact_count,
        )
        return DiagnosticCacheApplicationResult(
            availability=DiagnosticCacheApplicationAvailability.READY,
            observation=DiagnosticCacheApplicationObservation(
                generation=(
                    None if snapshot.generation < 1 else snapshot.generation
                ),
                fallback=fallback,
                last_refresh_result=refresh_result,
                compatibility=compatibility,
                affected_scope=(
                    DiagnosticCacheScope.REFERENCE_MARKET_PATHS,
                    DiagnosticCacheScope.DIAGNOSTIC_EVIDENCE,
                ),
                last_refresh_at=snapshot.observed_at,
                observed_at=observed_at,
                explanation=explanation,
            ),
            source_token=SourceRevisionToken(
                hashlib.sha256(repr(token_content).encode("utf-8")).hexdigest()
            ),
            observed_at=observed_at,
            error=None,
        )


def _application_failure(
    *,
    observed_at: datetime,
    availability: RuntimeHealthApplicationAvailability,
    code: RuntimeHealthApplicationErrorCode,
    explanation: str,
    retryable: bool,
) -> RuntimeHealthApplicationResult:
    return RuntimeHealthApplicationResult(
        availability=availability,
        observation=None,
        source_token=None,
        observed_at=observed_at,
        error=RuntimeHealthApplicationError(
            code=code,
            explanation=explanation,
            retryable=retryable,
        ),
    )


def _queue_application_failure(
    *,
    observed_at: datetime,
    availability: DiagnosticQueueApplicationAvailability,
    code: DiagnosticQueueApplicationErrorCode,
    explanation: str,
) -> DiagnosticQueueApplicationResult:
    return DiagnosticQueueApplicationResult(
        availability=availability,
        observation=None,
        source_token=None,
        observed_at=observed_at,
        error=DiagnosticQueueApplicationError(
            code=code,
            explanation=explanation,
            retryable=True,
        ),
    )


def _cache_application_failure(
    *,
    observed_at: datetime,
    availability: DiagnosticCacheApplicationAvailability,
    code: DiagnosticCacheApplicationErrorCode,
    explanation: str,
) -> DiagnosticCacheApplicationResult:
    return DiagnosticCacheApplicationResult(
        availability=availability,
        observation=None,
        source_token=None,
        observed_at=observed_at,
        error=DiagnosticCacheApplicationError(
            code=code,
            explanation=explanation,
            retryable=True,
        ),
    )


def _cache_explanation(
    *,
    fallback: DiagnosticCacheFallbackState,
    refresh_result: DiagnosticCacheLastRefreshResult,
    compatibility: DiagnosticCacheCompatibility,
) -> str:
    if compatibility is DiagnosticCacheCompatibility.INCOMPATIBLE:
        return "The Diagnostic Cache observation is incompatible."
    if fallback is DiagnosticCacheFallbackState.ACTIVE:
        return "The Diagnostic Cache is serving a verified fallback."
    if refresh_result is DiagnosticCacheLastRefreshResult.FAILED:
        return "The Diagnostic Cache refresh failed safely."
    return "The Diagnostic Cache refresh completed successfully."


def _validate_application_result(
    availability: Enum,
    ready: Enum,
    observation: object | None,
    source_token: SourceRevisionToken | None,
    error: object | None,
    label: str,
) -> None:
    if availability is ready:
        if observation is None or source_token is None:
            raise ValueError(f"Ready {label} requires an observation")
        if error is not None:
            raise ValueError(f"Ready {label} cannot carry an error")
    elif observation is not None or source_token is not None or error is None:
        raise ValueError(f"Unavailable {label} must carry only a typed error")


def _require_safe_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"{label} explanation must be bounded")


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Runtime Health observation time must be timezone-aware")


__all__ = [
    "RUNTIME_HEALTH_APPLICATION_INTERFACE_VERSION",
    "DiagnosticCacheApplicationAvailability",
    "DiagnosticCacheApplicationError",
    "DiagnosticCacheApplicationErrorCode",
    "DiagnosticCacheApplicationObservation",
    "DiagnosticCacheApplicationResult",
    "DiagnosticQueueApplicationAvailability",
    "DiagnosticQueueApplicationError",
    "DiagnosticQueueApplicationErrorCode",
    "DiagnosticQueueApplicationObservation",
    "DiagnosticQueueApplicationResult",
    "LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter",
    "RuntimeHealthApplicationAvailability",
    "RuntimeHealthApplicationError",
    "RuntimeHealthApplicationErrorCode",
    "RuntimeHealthApplicationObservation",
    "RuntimeHealthApplicationResult",
    "RuntimeHealthApplicationVersion",
    "StrategyDiagnosticsV1SystemHealthApplication",
]
