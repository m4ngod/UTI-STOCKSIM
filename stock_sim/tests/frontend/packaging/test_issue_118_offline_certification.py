from __future__ import annotations

from dataclasses import fields
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest

from stock_sim.release.frontend_v2_package_entry import (
    ACTIVE_JOURNEY_ROUTES,
    INSTALLED_UIA_ACK_TIMEOUT_SECONDS,
    PRODUCTION_PATH,
    PackageSmokeResult,
    _run_installed_migration_report,
)
from stock_sim.release.frontend_v2_packaging import (
    CLEAN_ROOM_REPORT_SCHEMA_VERSION,
    load_toolchain_lock,
)
from stock_sim.release.strategy_diagnostics_v1_release_fixture import (
    create_sealed_wave2_release_input_fixture,
    write_sealed_wave2_release_input_fixture_archive,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]


EXPECTED_PRODUCTION_DEPENDENCIES = {
    "PySide6": "6.9.1",
    "PySide6-Addons": "6.9.1",
    "PySide6-Essentials": "6.9.1",
    "SQLAlchemy": "2.0.49",
    "asn1crypto": "1.5.1",
    "duckdb": "1.5.4",
    "greenlet": "3.4.0",
    "numpy": "2.3.1",
    "pg8000": "1.31.5",
    "psycopg": "3.2.9",
    "psycopg-binary": "3.2.9",
    "pydantic": "1.10.26",
    "pyqtgraph": "0.13.7",
    "python-dateutil": "2.9.0.post0",
    "redis": "7.4.0",
    "scramp": "1.4.8",
    "shiboken6": "6.9.1",
    "six": "1.17.0",
    "typing-extensions": "4.15.0",
    "tzdata": "2025.2",
}
EXPECTED_BUILD_DEPENDENCIES = {
    "Nuitka": "4.1.3",
    "ordered-set": "4.1.0",
    "zstandard": "0.25.0",
}
SOURCE_COMMIT = "a" * 40


def test_issue_118_lock_captures_the_complete_production_and_build_closure():
    lock = load_toolchain_lock()

    assert lock.schema_version == 3
    assert lock.production_dependencies == EXPECTED_PRODUCTION_DEPENDENCIES
    assert lock.build_dependencies == EXPECTED_BUILD_DEPENDENCIES

    payload = json.loads(
        (
            PROJECT_ROOT
            / "stock_sim"
            / "release"
            / "frontend_v2_toolchain.lock.json"
        ).read_text(encoding="utf-8")
    )
    assert payload["production_dependencies"] == (
        EXPECTED_PRODUCTION_DEPENDENCIES
    )
    assert payload["build_dependencies"] == EXPECTED_BUILD_DEPENDENCIES


def test_issue_118_installed_journey_contract_covers_six_live_features():
    assert ACTIVE_JOURNEY_ROUTES == (
        "strategy_library",
        "scenario_lab",
        "diagnostic_tasks",
        "run_monitoring",
        "evidence_and_findings",
        "system_health",
    )
    assert PRODUCTION_PATH[-3:] == (
        "LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter",
        "LiveSystemHealthAdapter",
        "JourneyWorkspaceHost",
    )

    result_fields = {item.name for item in fields(PackageSmokeResult)}
    assert {
        "queued_state_observed",
        "running_state_observed",
        "partial_state_observed",
        "controlled_failure_observed",
        "safe_failure_reason_verified",
        "retry_idempotency_verified",
        "duplicate_work_count",
        "terminal_completion_observed",
        "system_health_context_verified",
        "system_health_identity_graph",
        "system_health_accessibility_verified",
        "focus_restoration_verified",
        "accessibility_checkpoints",
        "installed_accessibility_verified",
        "no_color_only_meaning_verified",
        "chart_narrative_table_revision_verified",
        "manual_trading_route_audits",
    }.issubset(result_fields)


@pytest.mark.parametrize("lane", ("hardware", "software"))
def test_issue_118_renderer_environment_pins_production_qt_style(
    lane,
    monkeypatch,
):
    from stock_sim.release import frontend_v2_package_entry
    from stock_sim.release import frontend_v2_performance

    monkeypatch.setenv("QT_QUICK_CONTROLS_STYLE", "Windows")
    renderer_lane = frontend_v2_package_entry.RendererLane(lane)

    frontend_v2_package_entry.configure_renderer_environment(renderer_lane)

    assert os.environ["QT_QUICK_CONTROLS_STYLE"] == "Basic"

    monkeypatch.setenv("QT_QUICK_CONTROLS_STYLE", "Windows")
    frontend_v2_performance._configure_renderer_environment(lane)

    assert os.environ["QT_QUICK_CONTROLS_STYLE"] == "Basic"


def test_issue_118_supported_data_copy_never_queries_storage_directly():
    source = (
        PROJECT_ROOT
        / "stock_sim"
        / "release"
        / "wave4_supported_data_copy.py"
    ).read_text(encoding="utf-8")

    assert "strategy_run_status" in source
    assert "from sqlalchemy" not in source
    assert ".connect()" not in source
    assert "diagnostic_run_orders" not in source


def test_issue_118_clean_room_contract_is_installed_schema_six():
    assert CLEAN_ROOM_REPORT_SCHEMA_VERSION == 6

    packaging_source = (
        PROJECT_ROOT
        / "stock_sim"
        / "release"
        / "frontend_v2_packaging.py"
    ).read_text(encoding="utf-8")
    clean_room_source = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
    ).read_text(encoding="utf-8")
    performance_source = (
        PROJECT_ROOT
        / "stock_sim"
        / "release"
        / "frontend_v2_performance_runtime.py"
    ).read_text(encoding="utf-8")
    sandbox_source = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_windows_sandbox.ps1"
    ).read_text(encoding="utf-8")

    for required in (
        "installed_performance",
        "fresh_install_migration",
        "copied_wave3_migration",
        "candidate_widgets_candidate_rollback",
        "observation_ledger_readiness",
    ):
        assert required in packaging_source
        assert required in clean_room_source

    assert "--performance-report" in clean_room_source
    assert '$rollbackLanes[$lane] = Invoke-InstalledRollbackLane' in (
        clean_room_source
    )
    assert "$candidateBeforePath" not in clean_room_source
    assert 'foreach ($lane in @("hardware", "software"))' in (
        clean_room_source
    )
    assert "DeterministicFakeStrategyLibraryAdapter" not in performance_source
    assert "DeterministicFakeScenarioLabAdapter" not in performance_source
    assert "DeterministicFakeDiagnosticTasksAdapter" not in performance_source
    for required_accessibility_probe in (
        "UIAutomationClient",
        "Narrator.exe",
        "TextScaleFactor",
        "Get-CompilerFreeWindowDpi",
        "GetDpiForWindow",
        "DefineDynamicAssembly",
        "GetProcAddress",
        "observed_window_dpi_x -eq 192",
        "native_window_dpi",
        "InvokePattern",
        "TogglePattern",
        "SelectionItemPattern",
        "ValuePattern",
        "forbidden_action_count",
        "UTI_STOCKSIM_UIA_CHECKPOINT_ACK_DIR",
        "installedAccessibilityCheckpointMarker",
        "lifecycle_state_observed",
        "Test-UiAutomationActionPatternProbeRequired",
        "window_device_pixel_ratio",
    ):
        assert required_accessibility_probe in clean_room_source
    assert "Graphics]::FromHwnd" not in clean_room_source
    assert "function Resolve-KnownUiAutomationObjectName" in clean_room_source
    assert (
        "function Register-UniqueCanonicalUiAutomationObjectName"
        in clean_room_source
    )
    assert 'EndsWith(".$objectName", [StringComparison]::Ordinal)' in (
        clean_room_source
    )
    assert (
        '$canonicalAutomationId = Resolve-KnownUiAutomationObjectName'
        in clean_room_source
    )
    assert (
        '$canonicalAutomationId -eq "installedAccessibilityCheckpointMarker"'
        in clean_room_source
    )
    assert "$snapshotSemanticByAutomationId[$canonicalAutomationId]" in (
        clean_room_source
    )
    assert "<AudioOutput>Disable</AudioOutput>" in sandbox_source


def test_issue_118_installed_uia_ack_wait_covers_one_complete_host_scan():
    assert INSTALLED_UIA_ACK_TIMEOUT_SECONDS == 60.0


def test_issue_118_performance_uses_a_real_shown_render_target():
    performance_runtime_source = (
        PROJECT_ROOT
        / "stock_sim"
        / "release"
        / "frontend_v2_performance_runtime.py"
    ).read_text(encoding="utf-8")

    assert "window.show()" in performance_runtime_source
    assert "WA_DontShowOnScreen" not in performance_runtime_source


def test_clean_room_uia_object_name_resolver_accepts_only_known_suffixes():
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell 7 is required for the Windows clean-room probe")

    script_path = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
    )
    probe = r"""
$scriptPath = $env:UTI_TEST_CLEAN_ROOM_SCRIPT
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {
    throw "clean-room script did not parse"
}
$resolver = $ast.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq "Resolve-KnownUiAutomationObjectName"
    },
    $true
)
if ($null -eq $resolver) {
    throw "UIA object-name resolver was unavailable"
}
Invoke-Expression $resolver.Extent.Text
$known = @(
    "installedAccessibilityCheckpointMarker",
    "runMonitoringRouteNavigation"
)
@(
    Resolve-KnownUiAutomationObjectName `
        -Value "runMonitoringRouteNavigation" `
        -KnownObjectNames $known
    Resolve-KnownUiAutomationObjectName `
        -Value (
            "QApplication.frontendV2PackageWindow." +
            "journeyWorkspaceHost.runMonitoringRouteNavigation"
        ) `
        -KnownObjectNames $known
    Resolve-KnownUiAutomationObjectName `
        -Value "prefix.runMonitoringRouteNavigation.evil" `
        -KnownObjectNames $known
    Resolve-KnownUiAutomationObjectName `
        -Value "prefix.unknownObject" `
        -KnownObjectNames $known
    Resolve-KnownUiAutomationObjectName `
        -Value "unsafe object id" `
        -KnownObjectNames $known
) | ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-Command",
            probe,
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UTI_TEST_CLEAN_ROOM_SCRIPT": str(script_path),
        },
    )

    assert json.loads(completed.stdout) == [
        "runMonitoringRouteNavigation",
        "runMonitoringRouteNavigation",
        "",
        "",
        "",
    ]


def test_clean_room_uia_canonical_object_names_reject_duplicates():
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell 7 is required for the Windows clean-room probe")

    script_path = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
    )
    probe = r"""
$scriptPath = $env:UTI_TEST_CLEAN_ROOM_SCRIPT
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {
    throw "clean-room script did not parse"
}
$register = $ast.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq "Register-UniqueCanonicalUiAutomationObjectName"
    },
    $true
)
if ($null -eq $register) {
    throw "canonical UIA uniqueness register was unavailable"
}
Invoke-Expression $register.Extent.Text
$counts = @{}
$first = Register-UniqueCanonicalUiAutomationObjectName `
    -CanonicalObjectName "runMonitoringRouteNavigation" `
    -ObservationCounts $counts
$second = Register-UniqueCanonicalUiAutomationObjectName `
    -CanonicalObjectName "runMonitoringRouteNavigation" `
    -ObservationCounts $counts
@($first, $second, $counts["runMonitoringRouteNavigation"]) |
    ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", probe],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UTI_TEST_CLEAN_ROOM_SCRIPT": str(script_path),
        },
    )

    assert json.loads(completed.stdout) == [True, False, 2]


def test_clean_room_uia_pattern_probe_covers_interactive_and_forbidden_peers():
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is required for the clean-room probe")
    script_path = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
    )
    probe = r"""
$scriptPath = $env:UTI_TEST_CLEAN_ROOM_SCRIPT
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$parseErrors
)
$helper = $ast.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq "Test-UiAutomationActionPatternProbeRequired"
    },
    $true
)
if ($null -eq $helper -or $parseErrors.Count -ne 0) {
    throw "UIA pattern-probe classifier was unavailable"
}
Invoke-Expression $helper.Extent.Text
@(
    Test-UiAutomationActionPatternProbeRequired `
        -ControlType "Button" -Focusable $false `
        -MatchesForbiddenCapability $false
    Test-UiAutomationActionPatternProbeRequired `
        -ControlType "Text" -Focusable $true `
        -MatchesForbiddenCapability $false
    Test-UiAutomationActionPatternProbeRequired `
        -ControlType "Text" -Focusable $false `
        -MatchesForbiddenCapability $true
    Test-UiAutomationActionPatternProbeRequired `
        -ControlType "Text" -Focusable $false `
        -MatchesForbiddenCapability $false
) | ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", probe],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UTI_TEST_CLEAN_ROOM_SCRIPT": str(script_path),
        },
    )

    assert json.loads(completed.stdout) == [True, True, True, False]


def test_clean_room_window_dpi_probe_runs_without_a_compiler():
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is required for the clean-room probe")

    script_path = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
    )
    probe = r"""
$scriptPath = $env:UTI_TEST_CLEAN_ROOM_SCRIPT
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {
    throw "clean-room script did not parse"
}
$dpiProbe = $ast.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq "Get-CompilerFreeWindowDpi"
    },
    $true
)
if ($null -eq $dpiProbe) {
    throw "compiler-free DPI probe was unavailable"
}
$script:getDpiForWindowDelegate = $null
Invoke-Expression $dpiProbe.Extent.Text
Add-Type -AssemblyName System.Windows.Forms
$form = New-Object Windows.Forms.Form
try {
    $form.ShowInTaskbar = $false
    $form.Opacity = 0
    $form.Show()
    [Windows.Forms.Application]::DoEvents()
    Get-CompilerFreeWindowDpi -WindowHandle $form.Handle
}
finally {
    $form.Close()
    $form.Dispose()
}
"""
    completed = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-Command",
            probe,
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UTI_TEST_CLEAN_ROOM_SCRIPT": str(script_path),
        },
    )

    assert int(completed.stdout.strip()) > 0


def test_clean_room_installed_journey_does_not_override_windows_dpi():
    source = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
    ).read_text(encoding="utf-8")

    journey_start = source.index(
        "function Invoke-InstalledJourneyWithAccessibilityProbe"
    )
    rollback_start = source.index(
        "function Invoke-InstalledRollbackLane",
        journey_start,
    )
    journey = source[journey_start:rollback_start]

    assert "QT_SCALE_FACTOR" not in source
    assert 'Name "LogPixels"' not in source
    assert 'Name "Win8DpiScaling"' not in source
    assert "UpdatePerUserSystemParameters" not in source
    assert "guest_dpi_override_applied = $false" in source
    assert 'native_dpi_evidence_source = "GetDpiForWindow"' in source
    assert "text_scale_registry_percent -eq 200" in journey

    package_entry = (
        PROJECT_ROOT
        / "stock_sim"
        / "release"
        / "frontend_v2_package_entry.py"
    ).read_text(encoding="utf-8")
    assert "window_device_pixel_ratio != 2.0" in package_entry
    assert "math.isfinite(window_device_pixel_ratio)" in package_entry


def test_clean_room_native_dpi_preflight_precedes_every_certification_gate():
    source = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
    ).read_text(encoding="utf-8")

    preflight = source.index(
        "$installedDpiPreflightInvocation = "
        "Invoke-InstalledJourneyWithAccessibilityProbe"
    )
    fail_closed = source.index(
        "if (-not $installedDpiPreflight.passed)",
        preflight,
    )
    migration = source.index("$freshInstallMigration =", preflight)
    widgets = source.index("$widgetsRollback =", preflight)
    renderer_loop = source.index(
        'foreach ($lane in @("hardware", "software"))',
        preflight,
    )
    performance = source.index('"--performance-report=$performancePath"')

    assert preflight < fail_closed < migration < widgets < renderer_loop
    assert fail_closed < performance
    assert '--installed-dpi-preflight-report=' in source
    assert 'stage = "installed-dpi-preflight"' in source
    assert "exit 1" in source[fail_closed:migration]


@pytest.mark.parametrize(
    (
        "candidate_ratio",
        "native_dpi",
        "candidate_clean_exit",
        "truncate_identity",
        "passed",
    ),
    (
        (2.0, 192, True, False, True),
        (1.0, 192, True, False, False),
        (2.0, 96, True, False, False),
        (2.0, 192, False, False, False),
        (2.0, 192, True, True, False),
    ),
)
def test_clean_room_native_dpi_preflight_binds_candidate_and_host_evidence(
    tmp_path,
    candidate_ratio,
    native_dpi,
    candidate_clean_exit,
    truncate_identity,
    passed,
):
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell 7 is required for the DPI preflight probe")

    script_path = PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
    probe = r'''
$ErrorActionPreference = "Stop"
$scriptPath = $env:UTI_TEST_CLEAN_ROOM_SCRIPT
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$parseErrors
)
$helper = $ast.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq "Test-InstalledDpiPreflightEvidence"
    },
    $true
)
if ($null -eq $helper) {
    throw "DPI preflight verifier helper was unavailable"
}
. ([scriptblock]::Create($helper.Extent.Text))
$candidate = Get-Content -LiteralPath $env:UTI_TEST_CANDIDATE -Raw |
    ConvertFrom-Json
$hostEvidence = Get-Content -LiteralPath $env:UTI_TEST_HOST -Raw |
    ConvertFrom-Json
$result = Test-InstalledDpiPreflightEvidence `
    -CandidateReport $candidate `
    -HostEvidence $hostEvidence `
    -CandidateExitCode 0 `
    -SourceCommit ("c" * 40) `
    -ExpectedProductionPath @("DiagnosticsApplication", "JourneyWorkspaceHost")
$result | ConvertTo-Json -Depth 12
'''
    snapshot_identity = (
        "uia:1:loading:run_monitoring:r1:r1"
        if truncate_identity
        else (
            "uia:1:loading:run_monitoring:r1:r1:"
            "runMonitoringRouteNavigation:loading:scale200"
        )
    )
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_commit": "c" * 40,
                "renderer_lane": "hardware",
                "certification_scope": "installed-dpi-preflight",
                "production_path": [
                    "DiagnosticsApplication",
                    "JourneyWorkspaceHost",
                ],
                "checkpoint": "loading",
                "checkpoint_sequence": 1,
                "snapshot_identity": snapshot_identity,
                "qt_window_device_pixel_ratio": candidate_ratio,
                "external_uia_acknowledged": True,
                "clean_exit": candidate_clean_exit,
                "passed": candidate_clean_exit and candidate_ratio == 2.0,
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    host_path = tmp_path / "host.json"
    host_path.write_text(
        json.dumps(
            {
                "narrator_checkpoint_evidence": [
                    {
                        "checkpoint": "loading",
                        "sequence": 1,
                        "snapshot_identity": snapshot_identity,
                        "route": "run_monitoring",
                        "run_revision": "r1",
                        "evidence_revision": "r1",
                        "status_object_name": "runMonitoringRouteNavigation",
                        "status_semantic_term": "loading",
                        "native_window_dpi": native_dpi,
                        "window_scale_percent": 200,
                        "passed": True,
                    }
                ],
                "forbidden_action_count": 0,
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", probe],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UTI_TEST_CLEAN_ROOM_SCRIPT": str(script_path),
            "UTI_TEST_CANDIDATE": str(candidate_path),
            "UTI_TEST_HOST": str(host_path),
        },
    )

    result = json.loads(completed.stdout)
    assert result["passed"] is passed
    assert result["qt_window_device_pixel_ratio"] == candidate_ratio
    assert result["native_window_dpi"] == native_dpi
    assert result["checkpoint"] == "loading"
    assert result["checkpoint_sequence"] == 1
    assert result["snapshot_identity"] == (
        "redacted" if truncate_identity else snapshot_identity
    )
    assert result["production_path_matches"] is True
    assert result["source_commit"] == "c" * 40


def test_clean_room_native_dpi_preflight_reader_redacts_malformed_json(tmp_path):
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell 7 is required for the DPI preflight probe")

    script_path = PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
    malformed = tmp_path / "installed-dpi-preflight.json"
    malformed.write_text('{"credential":"must-not-leak"', encoding="utf-8")
    probe = r'''
$ErrorActionPreference = "Stop"
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $env:UTI_TEST_CLEAN_ROOM_SCRIPT,
    [ref]$tokens,
    [ref]$parseErrors
)
$helper = $ast.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq "Read-InstalledDpiPreflightCandidateReport"
    },
    $true
)
. ([scriptblock]::Create($helper.Extent.Text))
$result = Read-InstalledDpiPreflightCandidateReport `
    -Path $env:UTI_TEST_MALFORMED_PREFLIGHT
if ($null -eq $result) { "REDACTED_FAILURE" } else { "UNEXPECTED_SUCCESS" }
'''
    completed = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", probe],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UTI_TEST_CLEAN_ROOM_SCRIPT": str(script_path),
            "UTI_TEST_MALFORMED_PREFLIGHT": str(malformed),
        },
    )
    assert completed.stdout.strip() == "REDACTED_FAILURE"
    assert completed.stderr == ""
    assert "must-not-leak" not in completed.stdout


def test_clean_room_native_dpi_preflight_redacts_parseable_invalid_identity(
    tmp_path,
):
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell 7 is required for the DPI preflight probe")

    script_path = PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
    secret = "credential-must-not-leak"
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_commit": "c" * 40,
                "renderer_lane": "hardware",
                "certification_scope": secret,
                "production_path": [secret],
                "checkpoint": "loading",
                "checkpoint_sequence": 1,
                "snapshot_identity": secret,
                "qt_window_device_pixel_ratio": 2.0,
                "external_uia_acknowledged": True,
                "clean_exit": True,
                "passed": True,
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    canonical_identity = (
        "uia:1:loading:run_monitoring:r1:r1:"
        "runMonitoringRouteNavigation:loading:scale200"
    )
    host_path = tmp_path / "host.json"
    host_path.write_text(
        json.dumps(
            {
                "narrator_checkpoint_evidence": [
                    {
                        "checkpoint": "loading",
                        "sequence": 1,
                        "snapshot_identity": canonical_identity,
                        "route": "run_monitoring",
                        "run_revision": "r1",
                        "evidence_revision": "r1",
                        "status_object_name": "runMonitoringRouteNavigation",
                        "status_semantic_term": "loading",
                        "native_window_dpi": 192,
                        "window_scale_percent": 200,
                        "passed": True,
                    }
                ],
                "forbidden_action_count": 0,
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    probe = r'''
$ErrorActionPreference = "Stop"
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $env:UTI_TEST_CLEAN_ROOM_SCRIPT,
    [ref]$tokens,
    [ref]$parseErrors
)
$helper = $ast.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq "Test-InstalledDpiPreflightEvidence"
    },
    $true
)
. ([scriptblock]::Create($helper.Extent.Text))
$candidate = Get-Content -LiteralPath $env:UTI_TEST_CANDIDATE -Raw |
    ConvertFrom-Json
$hostEvidence = Get-Content -LiteralPath $env:UTI_TEST_HOST -Raw |
    ConvertFrom-Json
Test-InstalledDpiPreflightEvidence `
    -CandidateReport $candidate `
    -HostEvidence $hostEvidence `
    -CandidateExitCode 0 `
    -SourceCommit ("c" * 40) `
    -ExpectedProductionPath @("DiagnosticsApplication", "JourneyWorkspaceHost") |
    ConvertTo-Json -Depth 12 -Compress
'''
    completed = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", probe],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UTI_TEST_CLEAN_ROOM_SCRIPT": str(script_path),
            "UTI_TEST_CANDIDATE": str(candidate_path),
            "UTI_TEST_HOST": str(host_path),
        },
    )

    result = json.loads(completed.stdout)
    assert result["passed"] is False
    assert result["certification_scope"] == "redacted"
    assert result["production_path"] == ["redacted"]
    assert result["snapshot_identity"] == "redacted"
    assert secret not in completed.stdout


@pytest.mark.parametrize(
    ("clean_room_exit_code", "ack_value"),
    (
        (0, None),
        (1, None),
        (0, "d" * 32),
        (0, "e" * 32),
    ),
)
def test_sandbox_guest_runner_waits_for_host_result_acknowledgment(
    tmp_path,
    clean_room_exit_code,
    ack_value,
):
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell 7 is required for the sandbox guest probe")

    source = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_windows_sandbox.ps1"
    ).read_text(encoding="utf-8")
    runner_start = source.index("$runner = @'")
    runner_start = source.index("\n", runner_start) + 1
    runner_end = source.index("\n'@", runner_start)
    guest_runner = source[runner_start:runner_end]

    evidence_root = tmp_path / "ReleaseEvidence"
    evidence_root.mkdir()
    clean_room_runner = evidence_root / "clean-room-runner.ps1"
    clean_room_runner.write_text(
        "param([Parameter(ValueFromRemainingArguments=$true)]$Ignored)\n"
        "[IO.File]::WriteAllText(\n"
        "    (Join-Path $PSScriptRoot 'clean-room-report.json'),\n"
        "    '{}',\n"
        "    [Text.UTF8Encoding]::new($false)\n"
        ")\n"
        f"exit {clean_room_exit_code}\n",
        encoding="utf-8",
    )
    escaped_evidence_root = str(evidence_root)
    guest_runner = (
        guest_runner.replace(
            "C:\\ReleaseEvidence",
            escaped_evidence_root,
        )
        .replace("__ARCHIVE_NAME__", "candidate.zip")
        .replace("__ARCHIVE_SHA256__", "sha256:" + "a" * 64)
        .replace("__WIDGETS_ARCHIVE_NAME__", "widgets.zip")
        .replace("__WIDGETS_ARCHIVE_SHA256__", "sha256:" + "b" * 64)
        .replace("__SOURCE_COMMIT__", "c" * 40)
        .replace("__RESULT_ACK_TOKEN__", "d" * 32)
        .replace(
            "$resultAckDeadline = [DateTime]::UtcNow.AddSeconds(60)",
            "$resultAckDeadline = [DateTime]::UtcNow.AddSeconds(2)",
        )
        .replace(
            "& shutdown.exe /s /t 0",
            "[IO.File]::WriteAllText(\n"
            "    (Join-Path $PSScriptRoot 'shutdown-observed.txt'),\n"
            "    'observed',\n"
            "    [Text.UTF8Encoding]::new($false)\n"
            ")",
        )
    )
    guest_runner_path = tmp_path / "sandbox-runner.ps1"
    guest_runner_path.write_text(guest_runner, encoding="utf-8")

    process = subprocess.Popen(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(guest_runner_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    exit_code_path = evidence_root / "sandbox-exit-code.txt"
    deadline = time.monotonic() + 10
    while not exit_code_path.is_file() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert exit_code_path.is_file()
    if ack_value is not None:
        (evidence_root / "sandbox-result-ack.txt").write_text(
            ack_value,
            encoding="utf-8",
        )
    stdout, stderr = process.communicate(timeout=15)

    assert process.returncode == 0, stderr
    assert stdout == ""
    assert (evidence_root / "clean-room-report.json").is_file()
    assert (evidence_root / "sandbox-exit-code.txt").read_text(
        encoding="utf-8"
    ) == str(clean_room_exit_code)
    assert (tmp_path / "shutdown-observed.txt").is_file()
    ack_received_path = evidence_root / "sandbox-result-ack-received.txt"
    if ack_value == "d" * 32:
        assert ack_received_path.read_text(encoding="utf-8") == ack_value
        assert not (evidence_root / "sandbox-error.txt").exists()
    else:
        assert not ack_received_path.exists()
    if clean_room_exit_code == 0 and ack_value != "d" * 32:
        assert (evidence_root / "sandbox-error.txt").read_text(
            encoding="utf-8"
        ) == "Windows Sandbox result acknowledgment was not received."
    elif clean_room_exit_code != 0:
        assert not (evidence_root / "sandbox-error.txt").exists()


def test_sandbox_host_requests_only_the_exact_owned_terminal_window_to_close():
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell 7 is required for the sandbox host probe")

    script_path = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_windows_sandbox.ps1"
    )
    probe = r"""
$ErrorActionPreference = "Stop"
$scriptPath = $env:UTI_TEST_WINDOWS_SANDBOX_SCRIPT
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$parseErrors
)
$helper = $ast.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq "Request-OwnedWindowsSandboxTerminalClose"
    },
    $true
)
if ($null -eq $helper -or $parseErrors.Count -ne 0) {
    throw "owned Sandbox terminal-close helper was unavailable"
}
Invoke-Expression $helper.Extent.Text

$script:closeCalls = 0
$script:candidateStartUtc = [DateTime]::Parse(
    "2026-08-12T15:20:28.0318160Z"
).ToUniversalTime()
$script:candidateParentPid = 71072
$script:candidatePid = 67668
$script:expectedName = "WindowsSandboxClient.exe"
$script:expectedProcessName = "WindowsSandboxClient"
$script:remoteCloseCalls = 0

function Request-OwnedWindowsSandboxRemoteSessionClose {
    param($TerminalProcessIdentity)
    $script:remoteCloseCalls += 1
    return $true
}

function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
        [PSCustomObject]@{
            Name = $script:expectedName
        ProcessId = $script:candidatePid
        ParentProcessId = $script:candidateParentPid
        CreationDate = $script:candidateStartUtc
    }
}
function Get-Process {
    param($Id, $ErrorAction)
    $process = [PSCustomObject]@{
        Id = $script:candidatePid
            ProcessName = $script:expectedProcessName
        StartTime = $script:candidateStartUtc.ToLocalTime()
        MainWindowHandle = [IntPtr]123
    }
    Add-Member `
        -InputObject $process `
        -MemberType ScriptMethod `
        -Name CloseMainWindow `
        -Value {
            $script:closeCalls += 1
            return $true
        }
    return $process
}

$owned = [PSCustomObject]@{
    Name = "WindowsSandboxClient.exe"
    ProcessId = 67668
    ParentProcessId = 71072
    StartTimeUtc = $script:candidateStartUtc
}
$exactClose = Request-OwnedWindowsSandboxTerminalClose `
    -TerminalProcessIdentity $owned
$wrongIdentity = [PSCustomObject]@{
    Name = "WindowsSandboxClient.exe"
    ProcessId = 67668
    ParentProcessId = 99999
    StartTimeUtc = $script:candidateStartUtc
}
$wrongClose = Request-OwnedWindowsSandboxTerminalClose `
    -TerminalProcessIdentity $wrongIdentity
$remoteIdentity = [PSCustomObject]@{
    Name = "WindowsSandboxRemoteSession.exe"
    ProcessId = 67668
    ParentProcessId = 71072
    StartTimeUtc = $script:candidateStartUtc
}
$script:expectedName = "WindowsSandboxRemoteSession.exe"
$script:expectedProcessName = "WindowsSandboxRemoteSession"
$remoteClose = Request-OwnedWindowsSandboxTerminalClose `
    -TerminalProcessIdentity $remoteIdentity
$unknownIdentity = [PSCustomObject]@{
    Name = "unowned.exe"
    ProcessId = 67668
    ParentProcessId = 71072
    StartTimeUtc = $script:candidateStartUtc
}
$unknownClose = Request-OwnedWindowsSandboxTerminalClose `
    -TerminalProcessIdentity $unknownIdentity
@(
    $exactClose,
    $wrongClose,
    $remoteClose,
    $unknownClose,
    $script:closeCalls,
    $script:remoteCloseCalls
) |
    ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", probe],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UTI_TEST_WINDOWS_SANDBOX_SCRIPT": str(script_path),
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [True, False, True, False, 1, 1]


def test_sandbox_remote_session_close_uses_the_exact_xaml_terminal_action():
    script = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_windows_sandbox.ps1"
    ).read_text(encoding="utf-8")

    assert "function Request-OwnedWindowsSandboxRemoteSessionClose" in script
    assert "Add-Type -AssemblyName UIAutomationClient" in script
    assert "Add-Type -AssemblyName UIAutomationTypes" in script
    assert 'AutomationId -ceq ""' in script
    assert 'ClassName -ceq "Button"' in script
    assert 'FrameworkId -ceq "XAML"' in script
    assert "[System.Windows.Automation.InvokePattern]::Pattern" in script
    assert "Start-Job" in script
    assert "sandbox-terminal-close-dispatch-started" in script
    assert "Receive-Job" in script
    assert "Stop-Job" in script
    assert "Remove-Job" in script
    assert "CloseMainWindow()" in script


def test_sandbox_terminal_close_job_requires_the_dispatch_marker():
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell 7 is required for the sandbox host probe")

    script_path = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_windows_sandbox.ps1"
    )
    probe = r"""
$ErrorActionPreference = "Stop"
$scriptPath = $env:UTI_TEST_WINDOWS_SANDBOX_SCRIPT
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$parseErrors
)
$helper = $ast.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq "Complete-OwnedWindowsSandboxTerminalCloseJob"
    },
    $true
)
if ($null -eq $helper -or $parseErrors.Count -ne 0) {
    throw "Sandbox terminal Close job helper was unavailable"
}
Invoke-Expression $helper.Extent.Text

$acceptedJob = Start-Job -ScriptBlock {
    "sandbox-terminal-close-dispatch-started"
}
$rejectedJob = Start-Job -ScriptBlock {
    "unexpected-marker"
}
$null = Wait-Job -Job @($acceptedJob, $rejectedJob) -Timeout 10
$accepted = Complete-OwnedWindowsSandboxTerminalCloseJob `
    -CloseJob $acceptedJob
$rejected = Complete-OwnedWindowsSandboxTerminalCloseJob `
    -CloseJob $rejectedJob
@($accepted, $rejected) | ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", probe],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UTI_TEST_WINDOWS_SANDBOX_SCRIPT": str(script_path),
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [True, False]


def test_sandbox_host_requires_exclusive_hcs_and_vm_worker_ownership():
    script = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_windows_sandbox.ps1"
    ).read_text(encoding="utf-8")

    assert "hcsdiag.exe" in script
    assert 'SystemType -cne "VirtualMachine"' in script
    assert "Test-WindowsSandboxComputeSystemOwner" in script
    assert '$Owner -ceq "Madrid"' in script
    assert '$Owner -ceq "WindowsSandbox"' in script
    assert "RuntimeId" in script
    assert "Windows Sandbox compute-system ownership was ambiguous." in script
    assert "Windows Sandbox VM worker ownership was ambiguous." in script
    assert "Windows Sandbox compute-system ownership was not observed." in script
    assert "Windows Sandbox VM worker ownership was not observed." in script
    assert "Windows Sandbox VM worker remained active after normal close." in script
    assert "try {" in script
    assert "finally {" in script


def test_sandbox_hcs_ownership_waits_for_runtime_template_identity():
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell 7 is required for the sandbox host probe")

    script_path = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_windows_sandbox.ps1"
    )
    probe = r"""
$ErrorActionPreference = "Stop"
$scriptPath = $env:UTI_TEST_WINDOWS_SANDBOX_SCRIPT
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$parseErrors
)
$helpers = @(
    "Get-WindowsSandboxComputeSystemSnapshot",
    "Test-WindowsSandboxComputeSystemOwner",
    "Get-NewWindowsSandboxComputeSystemIdentity",
    "Merge-WindowsSandboxComputeSystemIdentity",
    "Test-WindowsSandboxComputeSystemIdentityComplete"
)
foreach ($helperName in $helpers) {
    $helper = $ast.Find(
        {
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -eq $helperName
        },
        $true
    )
    if ($null -eq $helper -or $parseErrors.Count -ne 0) {
        throw "Sandbox HCS ownership helper was unavailable"
    }
    Invoke-Expression $helper.Extent.Text
}

$script:snapshot = @()
function Get-WindowsSandboxComputeSystemSnapshot {
    return @($script:snapshot)
}
$baseline = @("baseline-template", "baseline-template-2")
$sparseCandidate = [PSCustomObject]@{
    Id = "candidate"
    SystemType = ""
    Owner = ""
    RuntimeId = ""
    RuntimeTemplateId = ""
}
$script:snapshot = @($sparseCandidate)
$sparse = Get-NewWindowsSandboxComputeSystemIdentity `
    -BaselineComputeSystemIds @($baseline)
$boundSparse = Merge-WindowsSandboxComputeSystemIdentity `
    -CurrentIdentity $null `
    -ObservedIdentity $sparse
$sparseComplete = Test-WindowsSandboxComputeSystemIdentityComplete `
    -ComputeSystemIdentity $boundSparse `
    -BaselineComputeSystemIds @($baseline)
$pendingCandidate = [PSCustomObject]@{
    Id = "candidate"
    SystemType = "VirtualMachine"
    Owner = "Madrid"
    RuntimeId = "candidate"
    RuntimeTemplateId = ""
}
$script:snapshot = @($pendingCandidate)
$pending = Get-NewWindowsSandboxComputeSystemIdentity `
    -BaselineComputeSystemIds @($baseline)
$boundPending = Merge-WindowsSandboxComputeSystemIdentity `
    -CurrentIdentity $boundSparse `
    -ObservedIdentity $pending
$pendingComplete = Test-WindowsSandboxComputeSystemIdentityComplete `
    -ComputeSystemIdentity $boundPending `
    -BaselineComputeSystemIds @($baseline)
$stableCandidate = [PSCustomObject]@{
    Id = "candidate"
    SystemType = "VirtualMachine"
    Owner = "Madrid"
    RuntimeId = "candidate"
    RuntimeTemplateId = $baseline[0]
}
$script:snapshot = @($stableCandidate)
$stable = Get-NewWindowsSandboxComputeSystemIdentity `
    -BaselineComputeSystemIds @($baseline)
$boundStable = Merge-WindowsSandboxComputeSystemIdentity `
    -CurrentIdentity $boundPending `
    -ObservedIdentity $stable
$stableComplete = Test-WindowsSandboxComputeSystemIdentityComplete `
    -ComputeSystemIdentity $boundStable `
    -BaselineComputeSystemIds @($baseline)
$stableRuntimeTemplateId = [string]$stable.RuntimeTemplateId
$storeCandidate = [PSCustomObject]@{
    Id = "store-candidate"
    SystemType = "VirtualMachine"
    Owner = "WindowsSandbox"
    RuntimeId = "store-candidate"
    RuntimeTemplateId = $baseline[0]
}
$script:snapshot = @($storeCandidate)
$store = Get-NewWindowsSandboxComputeSystemIdentity `
    -BaselineComputeSystemIds @($baseline)
$storeComplete = Test-WindowsSandboxComputeSystemIdentityComplete `
    -ComputeSystemIdentity $store `
    -BaselineComputeSystemIds @($baseline)
$ownerlessCandidate = [PSCustomObject]@{
    Id = "ownerless-candidate"
    SystemType = "VirtualMachine"
    Owner = ""
    RuntimeId = "ownerless-candidate"
    RuntimeTemplateId = $baseline[0]
}
$script:snapshot = @($ownerlessCandidate)
$ownerless = Get-NewWindowsSandboxComputeSystemIdentity `
    -BaselineComputeSystemIds @($baseline)
$ownerlessComplete = Test-WindowsSandboxComputeSystemIdentityComplete `
    -ComputeSystemIdentity $ownerless `
    -BaselineComputeSystemIds @($baseline)
$identityFieldConflicts = @()
foreach ($identityFieldConflict in @(
    [PSCustomObject]@{
        Id = "candidate"
        SystemType = "Container"
        Owner = ""
        RuntimeId = ""
        RuntimeTemplateId = ""
    },
    [PSCustomObject]@{
        Id = "candidate"
        SystemType = ""
        Owner = "foreign-owner"
        RuntimeId = ""
        RuntimeTemplateId = ""
    },
    [PSCustomObject]@{
        Id = "candidate"
        SystemType = ""
        Owner = "madrid"
        RuntimeId = ""
        RuntimeTemplateId = ""
    },
    [PSCustomObject]@{
        Id = "candidate"
        SystemType = ""
        Owner = "windowssandbox"
        RuntimeId = ""
        RuntimeTemplateId = ""
    },
    [PSCustomObject]@{
        Id = "candidate"
        SystemType = ""
        Owner = "WindowsSandbox "
        RuntimeId = ""
        RuntimeTemplateId = ""
    },
    [PSCustomObject]@{
        Id = "candidate"
        SystemType = ""
        Owner = ""
        RuntimeId = "foreign-runtime"
        RuntimeTemplateId = ""
    }
)) {
    $script:snapshot = @($identityFieldConflict)
    try {
        Get-NewWindowsSandboxComputeSystemIdentity `
            -BaselineComputeSystemIds @($baseline) | Out-Null
        $identityFieldConflicts += "not-rejected"
    }
    catch {
        $identityFieldConflicts += $_.Exception.Message
    }
}
$foreignCandidate = [PSCustomObject]@{
    Id = "candidate"
    SystemType = "VirtualMachine"
    Owner = "Madrid"
    RuntimeId = "candidate"
    RuntimeTemplateId = "foreign-template"
}
$script:snapshot = @($foreignCandidate)
try {
    Get-NewWindowsSandboxComputeSystemIdentity `
        -BaselineComputeSystemIds @($baseline) | Out-Null
    $foreign = "not-rejected"
}
catch {
    $foreign = $_.Exception.Message
}
$replacementCandidate = [PSCustomObject]@{
    Id = "replacement"
    SystemType = "VirtualMachine"
    Owner = "Madrid"
    RuntimeId = "replacement"
    RuntimeTemplateId = $baseline[0]
}
try {
    Merge-WindowsSandboxComputeSystemIdentity `
        -CurrentIdentity $boundPending `
        -ObservedIdentity $replacementCandidate | Out-Null
    $replacement = "not-rejected"
}
catch {
    $replacement = $_.Exception.Message
}
$templateDriftCandidate = [PSCustomObject]@{
    Id = "candidate"
    SystemType = "VirtualMachine"
    Owner = "Madrid"
    RuntimeId = "candidate"
    RuntimeTemplateId = $baseline[1]
}
try {
    Merge-WindowsSandboxComputeSystemIdentity `
        -CurrentIdentity $boundStable `
        -ObservedIdentity $templateDriftCandidate | Out-Null
    $templateDrift = "not-rejected"
}
catch {
    $templateDrift = $_.Exception.Message
}
$storeOwnerDriftCandidate = [PSCustomObject]@{
    Id = "candidate"
    SystemType = "VirtualMachine"
    Owner = "WindowsSandbox"
    RuntimeId = "candidate"
    RuntimeTemplateId = $baseline[0]
}
try {
    Merge-WindowsSandboxComputeSystemIdentity `
        -CurrentIdentity $boundStable `
        -ObservedIdentity $storeOwnerDriftCandidate | Out-Null
    $storeOwnerDrift = "not-rejected"
}
catch {
    $storeOwnerDrift = $_.Exception.Message
}
$legacyOwnerDriftCandidate = [PSCustomObject]@{
    Id = "store-candidate"
    SystemType = "VirtualMachine"
    Owner = "Madrid"
    RuntimeId = "store-candidate"
    RuntimeTemplateId = $baseline[0]
}
try {
    Merge-WindowsSandboxComputeSystemIdentity `
        -CurrentIdentity $store `
        -ObservedIdentity $legacyOwnerDriftCandidate | Out-Null
    $legacyOwnerDrift = "not-rejected"
}
catch {
    $legacyOwnerDrift = $_.Exception.Message
}
@(
    $boundSparse.Id,
    [string]$boundSparse.SystemType,
    [string]$boundSparse.Owner,
    [string]$boundSparse.RuntimeId,
    $sparseComplete,
    $boundPending.Id,
    [string]$boundPending.SystemType,
    [string]$boundPending.Owner,
    [string]$boundPending.RuntimeId,
    [string]$boundPending.RuntimeTemplateId,
    $pendingComplete,
    $boundStable.Id,
    $stableRuntimeTemplateId,
    $stableComplete,
    $store.Id,
    [string]$store.Owner,
    $storeComplete,
    $ownerless.Id,
    [string]$ownerless.Owner,
    $ownerlessComplete,
    $identityFieldConflicts,
    $foreign,
    $replacement,
    $templateDrift,
    $storeOwnerDrift,
    $legacyOwnerDrift
) | ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", probe],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UTI_TEST_WINDOWS_SANDBOX_SCRIPT": str(script_path),
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [
        "candidate",
        "",
        "",
        "",
        False,
        "candidate",
        "VirtualMachine",
        "Madrid",
        "candidate",
        "",
        False,
        "candidate",
        "baseline-template",
        True,
        "store-candidate",
        "WindowsSandbox",
        True,
        "ownerless-candidate",
        "",
        False,
        [
            "Windows Sandbox compute-system ownership was ambiguous.",
            "Windows Sandbox compute-system ownership was ambiguous.",
            "Windows Sandbox compute-system ownership was ambiguous.",
            "Windows Sandbox compute-system ownership was ambiguous.",
            "Windows Sandbox compute-system ownership was ambiguous.",
            "Windows Sandbox compute-system ownership was ambiguous.",
        ],
        "Windows Sandbox compute-system ownership was ambiguous.",
        "Windows Sandbox compute-system ownership was ambiguous.",
        "Windows Sandbox compute-system ownership was ambiguous.",
        "Windows Sandbox compute-system ownership was ambiguous.",
        "Windows Sandbox compute-system ownership was ambiguous.",
    ]


def test_sandbox_host_waits_for_guest_processes_before_terminal_close():
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell 7 is required for the sandbox host probe")

    script_path = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_windows_sandbox.ps1"
    )
    probe = r"""
$scriptPath = $env:UTI_TEST_WINDOWS_SANDBOX_SCRIPT
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$parseErrors
)
    $identityHelper = $ast.Find(
        {
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -eq "Test-OwnedWindowsProcessIdentityAlive"
        },
        $true
    )
    $shutdownHelper = $ast.Find(
        {
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -eq "Test-OwnedWindowsSandboxGuestProcessesStopped"
        },
        $true
    )
if (
    $null -eq $identityHelper -or
    $null -eq $shutdownHelper -or
    $parseErrors.Count -ne 0
) {
    throw "Sandbox guest-shutdown helper was unavailable"
}
Invoke-Expression $identityHelper.Extent.Text
Invoke-Expression $shutdownHelper.Extent.Text

$script:activePids = @()
$script:startUtc = [DateTime]::Parse(
    "2026-08-12T15:20:28.0318160Z"
).ToUniversalTime()
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    $pidValue = [int](($Filter -split "=")[1].Trim())
    if ($script:activePids -contains $pidValue) {
        if ($pidValue -eq 64032) {
            return [PSCustomObject]@{
                Name = "WindowsSandboxServer.exe"
                ProcessId = 64032
                ParentProcessId = 67668
                CreationDate = $script:startUtc.AddMilliseconds(500)
            }
        }
        return [PSCustomObject]@{
            Name = "vmwp.exe"
            ProcessId = $pidValue
            ParentProcessId = 1234
            CreationDate = $script:startUtc.AddSeconds(1)
        }
    }
}
$server = [PSCustomObject]@{
    Name = "WindowsSandboxServer.exe"
    ProcessId = 64032
    ParentProcessId = 67668
    StartTimeUtc = $script:startUtc.AddMilliseconds(500)
}
$worker = [PSCustomObject]@{
    Name = "vmwp.exe"
    ProcessId = 41424
    ParentProcessId = $null
    StartTimeUtc = $script:startUtc.AddSeconds(1)
}
$script:activePids = @(64032)
$serverActive = Test-OwnedWindowsSandboxGuestProcessesStopped `
    -ServerIdentity $server `
    -VmWorkerIdentities @($worker)
$script:activePids = @(41424)
$workerActive = Test-OwnedWindowsSandboxGuestProcessesStopped `
    -ServerIdentity $server `
    -VmWorkerIdentities @($worker)
$script:activePids = @(99999)
$unrelatedWorkerIgnored = Test-OwnedWindowsSandboxGuestProcessesStopped `
    -ServerIdentity $server `
    -VmWorkerIdentities @($worker)
$script:activePids = @()
$guestStopped = Test-OwnedWindowsSandboxGuestProcessesStopped `
    -ServerIdentity $server `
    -VmWorkerIdentities @($worker)
@(
    $serverActive,
    $workerActive,
    $unrelatedWorkerIgnored,
    $guestStopped
) | ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", probe],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UTI_TEST_WINDOWS_SANDBOX_SCRIPT": str(script_path),
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [False, False, True, True]


def test_sandbox_server_ownership_matches_the_terminal_variant():
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell 7 is required for the sandbox host probe")

    script_path = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_windows_sandbox.ps1"
    )
    probe = r"""
$ErrorActionPreference = "Stop"
$scriptPath = $env:UTI_TEST_WINDOWS_SANDBOX_SCRIPT
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$parseErrors
)
$helper = $ast.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq "Test-OwnedWindowsSandboxServerOwnership"
    },
    $true
)
if ($null -eq $helper -or $parseErrors.Count -ne 0) {
    throw "Sandbox server ownership helper was unavailable"
}
Invoke-Expression $helper.Extent.Text

$client = [PSCustomObject]@{
    Name = "WindowsSandboxClient.exe"
    ProcessId = 100
}
$remote = [PSCustomObject]@{
    Name = "WindowsSandboxRemoteSession.exe"
    ProcessId = 200
}
$ownedServer = [PSCustomObject]@{
    Name = "WindowsSandboxServer.exe"
    ProcessId = 300
    ParentProcessId = 200
}
$foreignServer = [PSCustomObject]@{
    Name = "WindowsSandboxServer.exe"
    ProcessId = 301
    ParentProcessId = 999
}
$clientWithoutServer = Test-OwnedWindowsSandboxServerOwnership `
    -TerminalProcessIdentity $client `
    -ServerIdentities @()
$clientWithServer = Test-OwnedWindowsSandboxServerOwnership `
    -TerminalProcessIdentity $client `
    -ServerIdentities @($ownedServer)
$remoteWithOwnedServer = Test-OwnedWindowsSandboxServerOwnership `
    -TerminalProcessIdentity $remote `
    -ServerIdentities @($ownedServer)
$remoteWithoutServer = Test-OwnedWindowsSandboxServerOwnership `
    -TerminalProcessIdentity $remote `
    -ServerIdentities @()
$remoteWithForeignServer = Test-OwnedWindowsSandboxServerOwnership `
    -TerminalProcessIdentity $remote `
    -ServerIdentities @($foreignServer)
@(
    $clientWithoutServer,
    $clientWithServer,
    $remoteWithOwnedServer,
    $remoteWithoutServer,
    $remoteWithForeignServer
) | ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", probe],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UTI_TEST_WINDOWS_SANDBOX_SCRIPT": str(script_path),
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [True, False, True, False, False]


def test_sandbox_host_accepts_an_empty_guest_process_baseline():
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell 7 is required for the sandbox host probe")

    script_path = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_windows_sandbox.ps1"
    )
    probe = r"""
$ErrorActionPreference = "Stop"
$scriptPath = $env:UTI_TEST_WINDOWS_SANDBOX_SCRIPT
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$parseErrors
)
$helper = $ast.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq "Get-NewWindowsSandboxGuestProcessIdentities"
    },
    $true
)
if ($null -eq $helper -or $parseErrors.Count -ne 0) {
    throw "Sandbox guest-process discovery helper was unavailable"
}
Invoke-Expression $helper.Extent.Text

$script:startUtc = [DateTime]::Parse(
    "2026-08-12T15:20:28.0318160Z"
).ToUniversalTime()
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    if ($Filter -eq "Name = 'WindowsSandboxServer.exe'") {
        return [PSCustomObject]@{
            Name = "WindowsSandboxServer.exe"
            ProcessId = 64032
            ParentProcessId = 67668
            CreationDate = $script:startUtc.AddMilliseconds(500)
        }
    }
    if ($Filter -eq "Name = 'vmwp.exe'") {
        return [PSCustomObject]@{
            Name = "vmwp.exe"
            ProcessId = 41424
            ParentProcessId = 1234
            CreationDate = $script:startUtc.AddSeconds(1)
        }
    }
}

$identities = @(
    Get-NewWindowsSandboxGuestProcessIdentities `
        -BaselineProcessIds @() `
        -LauncherStartTimeUtc $script:startUtc
)
@(
    $identities.Count,
    @($identities | ForEach-Object { $_.Name } | Sort-Object)
) | ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", probe],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UTI_TEST_WINDOWS_SANDBOX_SCRIPT": str(script_path),
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [
        2,
        ["vmwp.exe", "WindowsSandboxServer.exe"],
    ]


def test_sandbox_guest_process_discovery_rejects_multiple_vm_workers():
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell 7 is required for the sandbox host probe")

    script_path = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_windows_sandbox.ps1"
    )
    probe = r"""
$ErrorActionPreference = "Stop"
$scriptPath = $env:UTI_TEST_WINDOWS_SANDBOX_SCRIPT
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$parseErrors
)
$helper = $ast.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq "Get-NewWindowsSandboxGuestProcessIdentities"
    },
    $true
)
if ($null -eq $helper -or $parseErrors.Count -ne 0) {
    throw "Sandbox guest-process discovery helper was unavailable"
}
Invoke-Expression $helper.Extent.Text

$script:startUtc = [DateTime]::Parse(
    "2026-08-12T15:20:28.0318160Z"
).ToUniversalTime()
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    if ($Filter -eq "Name = 'WindowsSandboxServer.exe'") {
        return @()
    }
    if ($Filter -eq "Name = 'vmwp.exe'") {
        return @(
            [PSCustomObject]@{
                Name = "vmwp.exe"
                ProcessId = 41424
                ParentProcessId = 1234
                CreationDate = $script:startUtc.AddSeconds(1)
            },
            [PSCustomObject]@{
                Name = "vmwp.exe"
                ProcessId = 41425
                ParentProcessId = 1234
                CreationDate = $script:startUtc.AddSeconds(2)
            }
        )
    }
}

try {
    Get-NewWindowsSandboxGuestProcessIdentities `
        -BaselineProcessIds @() `
        -LauncherStartTimeUtc $script:startUtc | Out-Null
    "not-rejected"
}
catch {
    $_.Exception.Message
}
"""
    completed = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", probe],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UTI_TEST_WINDOWS_SANDBOX_SCRIPT": str(script_path),
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == (
        "Windows Sandbox VM worker ownership was ambiguous."
    )


def test_issue_118_installed_migration_modes_use_real_public_persistence(
    tmp_path,
):
    fixture_root = tmp_path / "sealed-wave3"
    fixture_archive = tmp_path / "sealed-wave3.zip"
    create_sealed_wave2_release_input_fixture(
        bundle_root=fixture_root,
        source_commit=SOURCE_COMMIT,
    )
    write_sealed_wave2_release_input_fixture_archive(
        bundle_root=fixture_root,
        archive_path=fixture_archive,
    )

    for kind in ("fresh", "copied-wave3"):
        report_path = tmp_path / f"{kind}.json"
        assert _run_installed_migration_report(
            report_path=report_path,
            migration_kind=kind,
            work_root=tmp_path / f"{kind}-work",
            source_commit=SOURCE_COMMIT,
            fixture_archive_path=fixture_archive,
        ) == 0
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["passed"] is True
        assert report["schema_migration_verified"] is True
        assert report["bookmark_migration_verified"] is True
        assert report["deterministic"] is True
        assert report["idempotent"] is True
        assert report["identity_retention_verified"] is True
        assert report["reopen_verified"] is True
        assert report["destructive_migration"] is False
        assert report["clean_exit"] is True
        assert report["source_schema_revision"] == report["target_schema_revision"]
        assert report["first_reopen_applied_revisions"] == []
        assert report["second_reopen_applied_revisions"] == []
        if kind == "fresh":
            assert report["initial_applied_revisions"]
            assert report["initial_applied_revisions"][-1] == (
                report["target_schema_revision"]
            )
            assert report["initial_file_inventory"] == (
                report["final_file_inventory"]
            )
        else:
            assert report["initial_applied_revisions"] == []
