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
from .system_health import RuntimeHealthClassification

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


@runtime_checkable
class StrategyDiagnosticsV1SystemHealthApplication(Protocol):
    @property
    def interface_version(self) -> RuntimeHealthApplicationVersion: ...

    def read_runtime_health(self) -> RuntimeHealthApplicationResult: ...


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


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Runtime Health observation time must be timezone-aware")


__all__ = [
    "RUNTIME_HEALTH_APPLICATION_INTERFACE_VERSION",
    "LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter",
    "RuntimeHealthApplicationAvailability",
    "RuntimeHealthApplicationError",
    "RuntimeHealthApplicationErrorCode",
    "RuntimeHealthApplicationObservation",
    "RuntimeHealthApplicationResult",
    "RuntimeHealthApplicationVersion",
    "StrategyDiagnosticsV1SystemHealthApplication",
]
