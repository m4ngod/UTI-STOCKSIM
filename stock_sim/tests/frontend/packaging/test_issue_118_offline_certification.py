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


def test_issue_118_clean_room_contract_is_installed_schema_four():
    assert CLEAN_ROOM_REPORT_SCHEMA_VERSION == 4

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
        "LogPixels",
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

    assert "QT_SCALE_FACTOR" not in journey

    package_entry = (
        PROJECT_ROOT
        / "stock_sim"
        / "release"
        / "frontend_v2_package_entry.py"
    ).read_text(encoding="utf-8")
    assert "window_device_pixel_ratio != 2.0" in package_entry
    assert "math.isfinite(window_device_pixel_ratio)" in package_entry


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
