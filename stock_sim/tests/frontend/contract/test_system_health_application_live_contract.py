from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from app.features import (
    RUNTIME_HEALTH_APPLICATION_INTERFACE_VERSION,
    LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter,
    RuntimeHealthApplicationAvailability,
    RuntimeHealthApplicationErrorCode,
    RuntimeHealthClassification,
    StrategyDiagnosticsV1SystemHealthApplication,
)
from strategy_diagnostics import create_diagnostics_application


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
    assert operations == {"read_runtime_health"}


def test_runtime_health_application_redacts_raw_failure_details() -> None:
    class _ThrowingApplication:
        def status(self) -> object:
            raise OSError(
                r"C:\secrets\runtime.exe --token super-secret SELECT * FROM users"
            )

    result = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        _ThrowingApplication(),  # type: ignore[arg-type]
        clock=lambda: NOW,
    ).read_runtime_health()

    assert result.availability is RuntimeHealthApplicationAvailability.FAILED
    assert result.error is not None
    assert result.error.code is RuntimeHealthApplicationErrorCode.READ_FAILED
    exposed = result.error.explanation.casefold()
    for forbidden in ("c:\\", "runtime.exe", "token", "secret", "select", "users"):
        assert forbidden not in exposed
