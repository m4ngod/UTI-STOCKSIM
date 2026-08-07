from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone

import pytest

from app.features import (
    DiagnosticDataSourceApplicationAvailability,
    DiagnosticDataSourceScope,
    RUNTIME_HEALTH_APPLICATION_INTERFACE_VERSION,
    LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter,
    RuntimeHealthApplicationAvailability,
    RuntimeHealthApplicationErrorCode,
    RuntimeHealthClassification,
    StrategyDiagnosticsV1SystemHealthApplication,
)
from strategy_diagnostics import (
    AdmissionCheck,
    HistoricalSegmentSelection,
    HistoricalSourceInspection,
    InMemoryHistoricalSource,
    SourceArtifact,
    SourceProvenance,
    create_diagnostics_application,
)


NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
REQUIRED_SOURCE_CHECKS = (
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


def _application_with_admitted_source():
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
            AdmissionCheck(
                code=code,
                passed=True,
                summary=f"{code} passed.",
            )
            for code in REQUIRED_SOURCE_CHECKS
        ),
    )
    application = create_diagnostics_application(
        historical_source=InMemoryHistoricalSource((inspection,))
    )
    application.start()
    admission = application.admit_historical_segment(selection)
    assert admission.status == "admitted"
    return application


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


def test_system_health_application_reads_a_safe_admitted_data_source() -> None:
    adapter = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        _application_with_admitted_source(),
        clock=lambda: NOW,
    )

    result = adapter.read_diagnostic_data_source_health()

    assert result.availability is DiagnosticDataSourceApplicationAvailability.READY
    assert result.observation is not None
    assert result.observation.identity.provider == "BaoStock"
    assert result.observation.identity.dataset == "local-a-share-fixture"
    assert result.observation.identity.version == "fixture-2026-07-21"
    assert result.observation.identity.public_id.startswith("admitted-source-")
    assert result.observation.affected_scope == (
        DiagnosticDataSourceScope.SCENARIO_INPUTS,
        DiagnosticDataSourceScope.DIAGNOSTIC_EVIDENCE_INTERPRETATION,
    )
    assert result.source_token is not None
    assert result.error is None
    with pytest.raises(FrozenInstanceError):
        result.observation.identity.provider = "mutable"  # type: ignore[misc]


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
        "read_diagnostic_data_source_health",
        "read_runtime_health",
    }


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


def test_data_source_application_redacts_raw_failure_details() -> None:
    class _ThrowingApplication:
        def list_historical_segments(self) -> object:
            raise OSError(
                r"C:\secrets\source.db?token=super-secret SELECT market_payload"
            )

    result = LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter(
        _ThrowingApplication(),  # type: ignore[arg-type]
        clock=lambda: NOW,
    ).read_diagnostic_data_source_health()

    assert result.availability is DiagnosticDataSourceApplicationAvailability.FAILED
    assert result.error is not None
    exposed = result.error.explanation.casefold()
    for forbidden in (
        "c:\\",
        "source.db",
        "token",
        "secret",
        "select",
        "market_payload",
    ):
        assert forbidden not in exposed
