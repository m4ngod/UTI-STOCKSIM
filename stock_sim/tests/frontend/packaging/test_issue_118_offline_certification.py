from __future__ import annotations

import ast
from dataclasses import fields
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest

from stock_sim.release import frontend_v2_package_entry as package_entry
from stock_sim.release.frontend_v2_package_entry import (
    ACTIVE_JOURNEY_ROUTES,
    CertificationScope,
    COMPILED_SMOKE_OBSERVATION_SETTLE_TIMEOUT_SECONDS,
    DEFAULT_SETTLE_TIMEOUT_SECONDS,
    INSTALLED_UIA_ACK_TIMEOUT_SECONDS,
    PRODUCTION_PATH,
    PackageSmokeResult,
    _run_installed_migration_report,
    _smoke_observation_settle_timeout_seconds,
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


def test_issue_118_clean_room_contract_is_installed_schema_eight():
    assert CLEAN_ROOM_REPORT_SCHEMA_VERSION == 8

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
    assert INSTALLED_UIA_ACK_TIMEOUT_SECONDS == 120.0


def test_clean_room_owns_one_narrator_session_across_all_installed_journeys():
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
$commands = @(
    $ast.FindAll(
        {
            param($node)
            $node -is [Management.Automation.Language.CommandAst]
        },
        $true
    )
)
$journeyCalls = @(
    $commands |
        Where-Object {
            $_.GetCommandName() -ceq (
                "Invoke-InstalledJourneyWithAccessibilityProbe"
            )
        }
)
$journeySessionBindings = @(
    $journeyCalls |
        Where-Object {
            $_.Extent.Text -cmatch (
                '(?s)-NarratorSession\s+\$narratorSession'
            )
        }
)
[ordered]@{
    journey_call_count = $journeyCalls.Count
    journey_session_binding_count = $journeySessionBindings.Count
    narrator_session_create_count = @(
        $commands |
            Where-Object {
                $_.GetCommandName() -ceq "New-InstalledNarratorSession"
            }
    ).Count
    narrator_session_start_count = @(
        $commands |
            Where-Object {
                $_.GetCommandName() -ceq "Start-InstalledNarratorSession"
            }
    ).Count
    narrator_session_stop_count = @(
        $commands |
            Where-Object {
                $_.GetCommandName() -ceq "Stop-InstalledNarratorSession"
            }
    ).Count
    narrator_executable_literal_count = @(
        $tokens |
            Where-Object { $_.Text -ceq '"$env:WINDIR\System32\Narrator.exe"' }
    ).Count
} | ConvertTo-Json -Compress
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

    assert json.loads(completed.stdout) == {
        "journey_call_count": 2,
        "journey_session_binding_count": 2,
        "narrator_session_create_count": 1,
        "narrator_session_start_count": 1,
        "narrator_session_stop_count": 1,
        "narrator_executable_literal_count": 1,
    }


def test_clean_room_runs_later_uia_scans_in_fresh_windows_powershell():
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
$commands = @(
    $ast.FindAll(
        {
            param($node)
            $node -is [Management.Automation.Language.CommandAst]
        },
        $true
    )
)
$freshProcessCalls = @(
    $commands |
        Where-Object {
            $_.GetCommandName() -ceq (
                "Invoke-InstalledUiAutomationScanInFreshPowerShell"
            )
        }
)
$directProbeCalls = @(
    $commands |
        Where-Object {
            $_.GetCommandName() -ceq (
                "Invoke-InstalledUiAutomationScan"
            )
        }
)
$journeyProbeParameter = @(
    $ast.ParamBlock.Parameters |
        Where-Object {
            $_.Name.VariablePath.UserPath -ceq "UiAutomationScanRequest"
        }
)
[ordered]@{
    fresh_process_call_count = $freshProcessCalls.Count
    fresh_process_session_binding_count = @(
        $freshProcessCalls |
            Where-Object {
                $_.Extent.Text -cmatch (
                    '(?s)-NarratorSession\s+\$NarratorSession'
                )
            }
    ).Count
    direct_probe_call_count = $directProbeCalls.Count
    journey_probe_parameter_count = $journeyProbeParameter.Count
    child_powershell_literal_count = @(
        $tokens |
            Where-Object {
                $_.Text -ceq (
                    '"$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"'
                )
            }
    ).Count
} | ConvertTo-Json -Compress
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

    assert json.loads(completed.stdout) == {
        "fresh_process_call_count": 1,
        "fresh_process_session_binding_count": 1,
        "direct_probe_call_count": 2,
        "journey_probe_parameter_count": 1,
        "child_powershell_literal_count": 1,
    }


def test_clean_room_activates_uia_in_parent_then_isolates_later_scans():
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
$journeyFunction = $ast.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -ceq "Invoke-InstalledJourneyWithAccessibilityProbe"
    },
    $true
)
$freshScanFunction = $ast.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -ceq (
                "Invoke-InstalledUiAutomationScanInFreshPowerShell"
            )
    },
    $true
)
$commands = @(
    $ast.FindAll(
        {
            param($node)
            $node -is [Management.Automation.Language.CommandAst]
        },
        $true
    )
)
$journeyCommands = @(
    $journeyFunction.Body.FindAll(
        {
            param($node)
            $node -is [Management.Automation.Language.CommandAst]
        },
        $true
    )
)
$freshScanCommands = @(
    $freshScanFunction.Body.FindAll(
        {
            param($node)
            $node -is [Management.Automation.Language.CommandAst]
        },
        $true
    )
)
$journeyDirectScanCalls = @(
    $journeyCommands |
        Where-Object {
            $_.GetCommandName() -ceq "Invoke-InstalledUiAutomationScan"
        }
)
[ordered]@{
    fresh_scan_call_count = @(
        $journeyCommands |
            Where-Object {
                $_.GetCommandName() -ceq (
                    "Invoke-InstalledUiAutomationScanInFreshPowerShell"
                )
            }
    ).Count
    all_direct_scan_call_count = @(
        $commands |
            Where-Object {
                $_.GetCommandName() -ceq "Invoke-InstalledUiAutomationScan"
            }
    ).Count
    parent_activation_scan_call_count = $journeyDirectScanCalls.Count
    parent_activation_uses_cache_count = @(
        $journeyDirectScanCalls |
            Where-Object {
                $_.Extent.Text -cmatch '(?m)^\s*-UseCachedProperties\s*$'
            }
    ).Count
    cached_direct_scan_call_count = @(
        $commands |
            Where-Object {
                $_.GetCommandName() -ceq "Invoke-InstalledUiAutomationScan" -and
                    $_.Extent.Text -cmatch (
                        '(?m)^\s*-UseCachedProperties\s*$'
                    )
            }
    ).Count
    scan_request_parameter_count = @(
        $ast.ParamBlock.Parameters |
            Where-Object {
                $_.Name.VariablePath.UserPath -ceq (
                    "UiAutomationScanRequest"
                )
            }
    ).Count
    fresh_scan_start_process_count = @(
        $freshScanCommands |
            Where-Object { $_.GetCommandName() -ceq "Start-Process" }
    ).Count
    fresh_scan_wait_switch_count = @(
        $freshScanCommands |
            Where-Object {
                $_.GetCommandName() -ceq "Start-Process" -and
                    $_.Extent.Text -cmatch '(?m)^\s*-Wait\s'
            }
    ).Count
    fresh_scan_stop_process_count = @(
        $freshScanCommands |
            Where-Object { $_.GetCommandName() -ceq "Stop-Process" }
    ).Count
    scan_timeout_assignment_count = @(
        $ast.FindAll(
            {
                param($node)
                $node -is (
                    [Management.Automation.Language.AssignmentStatementAst]
                ) -and
                    $node.Left.Extent.Text -ceq (
                        '$script:installedUiAutomationScanTimeoutMilliseconds'
                    )
            },
            $true
        )
    ).Count
    completed_checkpoint_scan_stop_count = @(
        $journeyFunction.Body.FindAll(
            {
                param($node)
                $node -is (
                    [Management.Automation.Language.AssignmentStatementAst]
                ) -and
                    $node.Left.Extent.Text -ceq '$nextScan' -and
                    $node.Right.Extent.Text -ceq '[DateTime]::MaxValue'
            },
            $true
        )
    ).Count
} | ConvertTo-Json -Compress
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

    assert json.loads(completed.stdout) == {
        "fresh_scan_call_count": 1,
        "all_direct_scan_call_count": 2,
        "parent_activation_scan_call_count": 1,
        "parent_activation_uses_cache_count": 0,
        "cached_direct_scan_call_count": 1,
        "scan_request_parameter_count": 1,
        "fresh_scan_start_process_count": 1,
        "fresh_scan_wait_switch_count": 1,
        "fresh_scan_stop_process_count": 0,
        "scan_timeout_assignment_count": 0,
        "completed_checkpoint_scan_stop_count": 1,
    }


def test_clean_room_uia_tree_scan_bulk_caches_public_properties_and_patterns():
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
$merge = $ast.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -ceq "Merge-UiAutomationSnapshot"
    },
    $true
)
if ($null -eq $merge -or $parseErrors.Count -ne 0) {
    throw "UI Automation snapshot helper was unavailable"
}
$memberNames = @(
    $merge.Body.FindAll(
        {
            param($node)
            $node -is [Management.Automation.Language.MemberExpressionAst]
        },
        $true
    ) |
        ForEach-Object { [string]$_.Member.Value }
)
    $mergeText = $merge.Extent.Text
[ordered]@{
    cache_switch_parameter_count = @(
        $merge.Body.ParamBlock.Parameters |
            Where-Object {
                $_.Name.VariablePath.UserPath -ceq "UseCachedProperties"
            }
    ).Count
    cache_request_count = @(
        [regex]::Matches(
            $mergeText,
            '\[System\.Windows\.Automation\.CacheRequest\]'
        )
    ).Count
    cached_property_reads = @(
        $memberNames | Where-Object { $_ -ceq "Cached" }
    ).Count
    current_property_reads = @(
        $memberNames | Where-Object { $_ -ceq "Current" }
    ).Count
    cached_pattern_calls = @(
        $memberNames | Where-Object { $_ -ceq "TryGetCachedPattern" }
    ).Count
    current_pattern_calls = @(
        $memberNames | Where-Object { $_ -ceq "TryGetCurrentPattern" }
    ).Count
    required_property_count = @(
        @(
            "NameProperty",
            "AutomationIdProperty",
            "ControlTypeProperty",
            "IsEnabledProperty",
            "IsOffscreenProperty",
            "IsKeyboardFocusableProperty",
            "HasKeyboardFocusProperty",
            "HelpTextProperty",
            "ItemStatusProperty",
            "ProcessIdProperty"
        ) |
            Where-Object { $mergeText.Contains($_) }
    ).Count
    required_pattern_count = @(
        @(
            "InvokePattern",
            "TogglePattern",
            "SelectionItemPattern",
            "ValuePattern",
            "ExpandCollapsePattern"
        ) |
            Where-Object { $mergeText.Contains($_) }
    ).Count
} | ConvertTo-Json -Compress
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

    assert json.loads(completed.stdout) == {
        "cache_switch_parameter_count": 1,
        "cache_request_count": 1,
        "cached_property_reads": 1,
        "current_property_reads": 1,
        "cached_pattern_calls": 1,
        "current_pattern_calls": 1,
        "required_property_count": 10,
        "required_pattern_count": 5,
    }


def test_clean_room_merges_uia_semantics_across_exact_dictionary_shapes():
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
$merge = $ast.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -ceq "Merge-InstalledUiAutomationScanEvidence"
    },
    $true
)
if ($null -eq $merge -or $parseErrors.Count -ne 0) {
    throw "UI Automation evidence merge helper was unavailable"
}
    $mergeText = $merge.Extent.Text
[ordered]@{
    dictionary_shape_count = @(
        [regex]::Matches(
            $mergeText,
            'semantic_terms\s+-is\s+\[System\.Collections\.IDictionary\]'
        )
    ).Count
    json_shape_count = @(
        [regex]::Matches(
            $mergeText,
            'semantic_terms\s+-is\s+\[pscustomobject\]'
        )
    ).Count
    property_projection_count = @(
        [regex]::Matches(
            $mergeText,
            '\$ScanEvidence\.semantic_terms\.PSObject\.Properties'
        )
    ).Count
    exact_key_comparison_count = @(
        [regex]::Matches(
            $mergeText,
            'Compare-Object[\s\S]*-CaseSensitive'
        )
    ).Count
    fragile_contains_key_count = @(
        [regex]::Matches(
            $mergeText,
            '\.ContainsKey\(\$semanticKey\)'
        )
    ).Count
} | ConvertTo-Json -Compress
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

    assert json.loads(completed.stdout) == {
        "dictionary_shape_count": 1,
        "json_shape_count": 1,
        "property_projection_count": 1,
        "exact_key_comparison_count": 1,
        "fragile_contains_key_count": 0,
    }


def test_clean_room_merges_ordered_uia_semantics_from_parent_scan():
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
foreach ($helperName in @(
    "New-UiAutomationAccessibilityEvidence",
    "Merge-InstalledUiAutomationScanEvidence"
)) {
    $helper = $ast.Find(
        {
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -ceq $helperName
        },
        $true
    )
    if ($null -eq $helper -or $parseErrors.Count -ne 0) {
        throw "UI Automation evidence merge helper was unavailable"
    }
    Invoke-Expression $helper.Extent.Text
}
$evidence = New-UiAutomationAccessibilityEvidence
$delta = New-UiAutomationAccessibilityEvidence
$delta.semantic_terms.loading = $true
$accepted = $true
try {
    Merge-InstalledUiAutomationScanEvidence `
        -Evidence $evidence `
        -ScanEvidence $delta
}
catch {
    $accepted = $false
}
$missingKeyRejected = $false
$missingKeyDelta = New-UiAutomationAccessibilityEvidence
$missingKeyDelta.semantic_terms.Remove("recovery")
try {
    Merge-InstalledUiAutomationScanEvidence `
        -Evidence (New-UiAutomationAccessibilityEvidence) `
        -ScanEvidence $missingKeyDelta
}
catch {
    $missingKeyRejected = $true
}
$malformedValueRejected = $false
$malformedValueDelta = New-UiAutomationAccessibilityEvidence
$malformedValueDelta.semantic_terms.loading = "true"
try {
    Merge-InstalledUiAutomationScanEvidence `
        -Evidence (New-UiAutomationAccessibilityEvidence) `
        -ScanEvidence $malformedValueDelta
}
catch {
    $malformedValueRejected = $true
}
[ordered]@{
    accepted = $accepted
    source_type = [string]$delta.semantic_terms.GetType().FullName
    semantic_loading = [bool]$evidence.semantic_terms.loading
    missing_key_rejected = $missingKeyRejected
    malformed_value_rejected = $malformedValueRejected
} | ConvertTo-Json -Compress
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

    assert json.loads(completed.stdout) == {
        "accepted": True,
        "source_type": "System.Collections.Specialized.OrderedDictionary",
        "semantic_loading": True,
        "missing_key_rejected": True,
        "malformed_value_rejected": True,
    }


def test_clean_room_retains_qt_scale_when_checkpoint_ack_is_suppressed():
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
$merge = $ast.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -ceq "Merge-UiAutomationSnapshot"
    },
    $true
)
if ($null -eq $merge -or $parseErrors.Count -ne 0) {
    throw "UI Automation snapshot merge helper was unavailable"
}
$suppressAckIf = $merge.FindAll(
    {
        param($node)
        if ($node -isnot [Management.Automation.Language.IfStatementAst]) {
            return $false
        }
        foreach ($clause in $node.Clauses) {
            if ($clause.Item1.Extent.Text -cmatch '\$SuppressCheckpointAck') {
                return $true
            }
        }
        return $false
    },
    $true
) | Select-Object -First 1
if ($null -eq $suppressAckIf) {
    throw "Suppressed checkpoint ACK branch was unavailable"
}
[ordered]@{
    scale_assignment_count = @(
        [regex]::Matches(
            $merge.Extent.Text,
            '\$Evidence\.observed_qt_window_scale_percent\s*='
        )
    ).Count
    scale_assignment_inside_suppressed_ack_count = @(
        [regex]::Matches(
            $suppressAckIf.Extent.Text,
            '\$Evidence\.observed_qt_window_scale_percent\s*='
        )
    ).Count
} | ConvertTo-Json -Compress
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

    assert json.loads(completed.stdout) == {
        "scale_assignment_count": 1,
        "scale_assignment_inside_suppressed_ack_count": 0,
    }


def test_clean_room_fresh_uia_child_request_is_exact_and_path_bounded(
    tmp_path,
):
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is required for the clean-room probe")

    script_path = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
    )
    probe_id = "0123456789abcdef0123456789abcdef"
    control_dir = tmp_path / probe_id
    control_dir.mkdir()
    lane_dir = tmp_path / "lane"
    lane_dir.mkdir()
    request_path = (
        control_dir
        / f"installed-uia-scan-{probe_id}-request.json"
    )
    result_path = (
        control_dir
        / f"installed-uia-scan-{probe_id}-result.json"
    )
    valid_request = {
        "schema_version": 1,
        "candidate_process_id": 31337,
        "candidate_process_start_time_utc_ticks": 638000000000000001,
        "lane": "hardware",
        "lane_directory": str(lane_dir),
        "source_commit": "a" * 40,
        "narrator_process_id": 4242,
        "narrator_process_start_time_utc_ticks": 638000000000000000,
        "scan_sequence_base": 2,
        "result_path": str(result_path),
    }
    probe = r"""
$scriptPath = $env:UTI_TEST_CLEAN_ROOM_SCRIPT
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$parseErrors
)
foreach ($helperName in @(
    "Resolve-NormalizedFullyQualifiedPath",
    "Test-ExactEvidencePropertyNames",
    "Read-InstalledUiAutomationScanRequest"
)) {
    $helper = $ast.Find(
        {
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -ceq $helperName
        },
        $true
    )
    if ($null -eq $helper -or $parseErrors.Count -ne 0) {
        throw "journey probe request helper was unavailable"
    }
    Invoke-Expression $helper.Extent.Text
}
try {
    $request = Read-InstalledUiAutomationScanRequest `
        -Path $env:UTI_TEST_JOURNEY_PROBE_REQUEST
    [ordered]@{
        accepted = $true
        lane = [string]$request.lane
        scan_sequence_base = [int]$request.scan_sequence_base
        candidate_process_id = [int]$request.candidate_process_id
        narrator_process_id = [int]$request.narrator_process_id
    } | ConvertTo-Json -Compress
}
catch {
    [ordered]@{
        accepted = $false
        lane = ""
        scan_sequence_base = -1
        candidate_process_id = 0
        narrator_process_id = 0
    } | ConvertTo-Json -Compress
}
"""

    def invoke(request):
        request_path.write_text(json.dumps(request), encoding="utf-8")
        completed = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-Command", probe],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={
                **os.environ,
                "UTI_TEST_CLEAN_ROOM_SCRIPT": str(script_path),
                "UTI_TEST_JOURNEY_PROBE_REQUEST": str(request_path),
            },
        )
        return json.loads(completed.stdout)

    assert invoke(valid_request) == {
        "accepted": True,
        "lane": "hardware",
        "scan_sequence_base": 2,
        "candidate_process_id": 31337,
        "narrator_process_id": 4242,
    }

    extra_top_level = {**valid_request, "credential_backup": "secret"}
    assert invoke(extra_top_level)["accepted"] is False

    invalid_sequence_type = {
        **valid_request,
        "scan_sequence_base": False,
    }
    assert invoke(invalid_sequence_type)["accepted"] is False

    escaped_result = {
        **valid_request,
        "result_path": str(tmp_path / "escaped-result.json"),
    }
    assert invoke(escaped_result)["accepted"] is False


def test_clean_room_uia_scan_result_binds_process_and_evidence_shape(tmp_path):
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is required for the clean-room probe")

    script_path = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
    )
    result_path = tmp_path / "scan-result.json"
    probe = r"""
$scriptPath = $env:UTI_TEST_CLEAN_ROOM_SCRIPT
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $scriptPath,
    [ref]$tokens,
    [ref]$parseErrors
)
foreach ($helperName in @(
    "Test-ExactEvidencePropertyNames",
    "New-UiAutomationAccessibilityEvidence",
    "Read-InstalledUiAutomationScanResult"
)) {
    $helper = $ast.Find(
        {
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -ceq $helperName
        },
        $true
    )
    if ($null -eq $helper -or $parseErrors.Count -ne 0) {
        throw "UI Automation scan result helper was unavailable"
    }
    Invoke-Expression $helper.Extent.Text
}
$session = [ordered]@{
    process_id = 4242
    process_start_time_utc_ticks = [long]638000000000000000
    start_attempted = $true
    stopped = $false
}
$evidence = New-UiAutomationAccessibilityEvidence
$evidence.scan_count = 3
$result = [ordered]@{
    schema_version = 1
    purpose = "installed-uia-tree-scan"
    source_commit = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    lane = "hardware"
    candidate_process_id = 31337
    candidate_process_start_time_utc_ticks = [long]638000000000000001
    narrator_process_id = 4242
    narrator_process_start_time_utc_ticks = [long]638000000000000000
    scan_sequence_base = 2
    scan_evidence = $evidence
}
$result | ConvertTo-Json -Depth 100 | Set-Content `
    -LiteralPath $env:UTI_TEST_UIA_SCAN_RESULT `
    -Encoding UTF8
$accepted = Read-InstalledUiAutomationScanResult `
    -Path $env:UTI_TEST_UIA_SCAN_RESULT `
    -SourceCommit "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" `
    -Lane "hardware" `
    -NarratorSession $session `
    -CandidateProcessId 31337 `
    -CandidateProcessStartTimeUtcTicks ([long]638000000000000001) `
    -ScanSequenceBase 2
$result.narrator_process_id = 4243
$result | ConvertTo-Json -Depth 100 | Set-Content `
    -LiteralPath $env:UTI_TEST_UIA_SCAN_RESULT `
    -Encoding UTF8
$driftRejected = $false
try {
    Read-InstalledUiAutomationScanResult `
        -Path $env:UTI_TEST_UIA_SCAN_RESULT `
        -SourceCommit "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" `
        -Lane "hardware" `
        -NarratorSession $session `
        -CandidateProcessId 31337 `
        -CandidateProcessStartTimeUtcTicks ([long]638000000000000001) `
        -ScanSequenceBase 2 | Out-Null
}
catch {
    $driftRejected = $true
}
[ordered]@{
    scan_count = [int]$accepted.scan_count
    narrator_drift_rejected = $driftRejected
} | ConvertTo-Json -Compress
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
            "UTI_TEST_UIA_SCAN_RESULT": str(result_path),
        },
    )

    assert json.loads(completed.stdout) == {
        "scan_count": 3,
        "narrator_drift_rejected": True,
    }


def test_clean_room_merges_scan_delta_before_writing_candidate_ack(tmp_path):
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
foreach ($helperName in @(
    "New-UiAutomationAccessibilityEvidence",
    "Merge-InstalledUiAutomationScanEvidence",
    "Write-InstalledUiAutomationCheckpointAcknowledgements"
)) {
    $helper = $ast.Find(
        {
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -ceq $helperName
        },
        $true
    )
    if ($null -eq $helper -or $parseErrors.Count -ne 0) {
        throw "UI Automation scan merge helper was unavailable"
    }
    Invoke-Expression $helper.Extent.Text
}
$evidence = New-UiAutomationAccessibilityEvidence
$delta = New-UiAutomationAccessibilityEvidence
$delta.provider_available = $true
$delta.scan_count = 1
$delta.complete_snapshot_count = 1
$delta.named_element_count = 4
$delta.semantic_terms.loading = $true
$delta.narrator_checkpoint_evidence = @(
    [pscustomobject]@{
        checkpoint = "loading"
        sequence = 1
        snapshot_identity = (
            "uia:1:loading:strategy_library:r1:r1:" +
            "runMonitoringRouteNavigation:loading:scale200"
        )
        passed = $true
    }
)
$delta = $delta | ConvertTo-Json -Depth 100 | ConvertFrom-Json
Merge-InstalledUiAutomationScanEvidence `
    -Evidence $evidence `
    -ScanEvidence $delta
Write-InstalledUiAutomationCheckpointAcknowledgements `
    -ScanEvidence $delta `
    -CheckpointAckDirectory $env:UTI_TEST_UIA_ACK_DIR
$ackPath = Join-Path `
    $env:UTI_TEST_UIA_ACK_DIR `
    "uia-checkpoint-01-loading.json"
$ack = Get-Content -LiteralPath $ackPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
[ordered]@{
    scan_count = [int]$evidence.scan_count
    complete_snapshot_count = [int]$evidence.complete_snapshot_count
    semantic_loading = [bool]$evidence.semantic_terms.loading
    checkpoint_count = @($evidence.narrator_checkpoint_evidence).Count
    ack_passed = [bool]$ack.passed
    ack_identity = [string]$ack.snapshot_identity
} | ConvertTo-Json -Compress
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
            "UTI_TEST_UIA_ACK_DIR": str(tmp_path),
        },
    )

    assert json.loads(completed.stdout) == {
        "scan_count": 1,
        "complete_snapshot_count": 1,
        "semantic_loading": True,
        "checkpoint_count": 1,
        "ack_passed": True,
        "ack_identity": (
            "uia:1:loading:strategy_library:r1:r1:"
            "runMonitoringRouteNavigation:loading:scale200"
        ),
    }


def test_clean_room_narrator_session_reuses_and_stops_only_exact_owned_process():
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
$helperNames = @(
    "New-InstalledNarratorSession",
    "Test-InstalledNarratorSessionRunning",
    "Start-InstalledNarratorSession",
    "Stop-InstalledNarratorSession"
)
foreach ($helperName in $helperNames) {
    $helper = $ast.Find(
        {
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -ceq $helperName
        },
        $true
    )
    if ($null -eq $helper -or $parseErrors.Count -ne 0) {
        throw "Narrator ownership helper was unavailable"
    }
    Invoke-Expression $helper.Extent.Text
}

function New-FakeNarratorProcess {
    $process = [pscustomobject]@{
        Id = 4242
        ProcessName = "Narrator"
        HasExited = $false
        StartTime = [DateTime]::UtcNow
    }
    $process | Add-Member -MemberType ScriptMethod -Name Refresh -Value {}
    return $process
}

$script:fakeProcess = New-FakeNarratorProcess
$script:fakeVisible = $false
$script:startCount = 0
$script:stopCount = 0
function Get-Process {
    param($Name, $Id, $ErrorAction)
    if ($PSBoundParameters.ContainsKey("Name")) {
        if ($script:fakeVisible -and -not $script:fakeProcess.HasExited) {
            return $script:fakeProcess
        }
        return
    }
    if (
        $script:fakeVisible -and
        -not $script:fakeProcess.HasExited -and
        [int]$Id -eq [int]$script:fakeProcess.Id
    ) {
        return $script:fakeProcess
    }
    throw "process unavailable"
}
function Start-Process {
    param($FilePath, [switch]$PassThru)
    $script:startCount += 1
    $script:fakeVisible = $true
    return $script:fakeProcess
}
function Stop-Process {
    param($Id, [switch]$Force, $ErrorAction)
    if ([int]$Id -ne [int]$script:fakeProcess.Id) {
        throw "wrong process"
    }
    $script:stopCount += 1
    $script:fakeProcess.HasExited = $true
}
function Start-Sleep {
    param($Milliseconds)
}

$session = New-InstalledNarratorSession
Start-InstalledNarratorSession -NarratorSession $session
Start-InstalledNarratorSession -NarratorSession $session
$runningBeforeStop = Test-InstalledNarratorSessionRunning $session
Stop-InstalledNarratorSession -NarratorSession $session
$runningAfterStop = Test-InstalledNarratorSessionRunning $session
$restartRejected = $false
try {
    Start-InstalledNarratorSession -NarratorSession $session
}
catch {
    $restartRejected = $true
}

$firstResult = [ordered]@{
    start_count = $script:startCount
    stop_count = $script:stopCount
    running_before_stop = $runningBeforeStop
    running_after_stop = $runningAfterStop
    stopped = [bool]$session.stopped
    restart_rejected = $restartRejected
}

$script:fakeProcess = New-FakeNarratorProcess
$script:fakeVisible = $false
$script:startCount = 0
$script:stopCount = 0
$driftedSession = New-InstalledNarratorSession
Start-InstalledNarratorSession -NarratorSession $driftedSession
$script:fakeProcess.StartTime = $script:fakeProcess.StartTime.AddSeconds(1)
Stop-InstalledNarratorSession -NarratorSession $driftedSession

$script:fakeProcess = New-FakeNarratorProcess
$script:fakeVisible = $true
$preExistingSession = New-InstalledNarratorSession
$preExistingRejected = $false
try {
    Start-InstalledNarratorSession -NarratorSession $preExistingSession
}
catch {
    $preExistingRejected = $true
}

[ordered]@{
    first = $firstResult
    identity_drift_stop_count = $script:stopCount
    pre_existing_rejected = $preExistingRejected
} | ConvertTo-Json -Depth 5 -Compress
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

    assert json.loads(completed.stdout) == {
        "first": {
            "start_count": 1,
            "stop_count": 1,
            "running_before_stop": True,
            "running_after_stop": False,
            "stopped": True,
            "restart_rejected": True,
        },
        "identity_drift_stop_count": 0,
        "pre_existing_rejected": True,
    }


def test_issue_118_smoke_observation_settle_timeout_is_scope_bound():
    package_entry_source = (
        PROJECT_ROOT
        / "stock_sim"
        / "release"
        / "frontend_v2_package_entry.py"
    ).read_text(encoding="utf-8")
    module = ast.parse(package_entry_source)
    smoke_journey = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "_run_smoke_journey"
    )
    settle_timeout_assignment = next(
        node
        for node in smoke_journey.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "observation_settle_timeout_seconds"
            for target in node.targets
        )
    )
    settle_timeout_call = settle_timeout_assignment.value
    observe = next(
        node
        for node in smoke_journey.body
        if isinstance(node, ast.FunctionDef) and node.name == "observe"
    )
    settle_call = next(
        node
        for node in ast.walk(observe)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_settle_until"
    )
    timeout_keyword = next(
        keyword
        for keyword in settle_call.keywords
        if keyword.arg == "timeout_seconds"
    )

    assert DEFAULT_SETTLE_TIMEOUT_SECONDS == 3.0
    assert COMPILED_SMOKE_OBSERVATION_SETTLE_TIMEOUT_SECONDS == 10.0
    assert _smoke_observation_settle_timeout_seconds(
        CertificationScope.SOURCE_VALIDATION
    ) == 3.0
    assert _smoke_observation_settle_timeout_seconds(
        CertificationScope.INSTALLED_DPI_PREFLIGHT
    ) == 3.0
    assert _smoke_observation_settle_timeout_seconds(
        CertificationScope.INSTALLED
    ) == 10.0
    assert _smoke_observation_settle_timeout_seconds(
        CertificationScope.PACKAGE_ASSEMBLY
    ) == 10.0
    assert isinstance(settle_timeout_call, ast.Call)
    assert isinstance(settle_timeout_call.func, ast.Name)
    assert (
        settle_timeout_call.func.id
        == "_smoke_observation_settle_timeout_seconds"
    )
    assert len(settle_timeout_call.args) == 1
    assert isinstance(settle_timeout_call.args[0], ast.Name)
    assert settle_timeout_call.args[0].id == "certification_scope"
    assert isinstance(timeout_keyword.value, ast.Name)
    assert timeout_keyword.value.id == "observation_settle_timeout_seconds"


def test_issue_118_installed_observation_settle_extends_only_the_route_wait(
    monkeypatch: pytest.MonkeyPatch,
):
    clock = [0.0]

    class App:
        @staticmethod
        def processEvents() -> None:
            return None

    monkeypatch.setattr(package_entry, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        package_entry,
        "sleep",
        lambda _duration: clock.__setitem__(0, clock[0] + 1.0),
    )

    package_entry._settle_until(
        App(),
        lambda: clock[0] >= 4.0,
        "installed route observation",
        timeout_seconds=_smoke_observation_settle_timeout_seconds(
            CertificationScope.INSTALLED
        ),
    )
    assert clock[0] == 4.0

    clock[0] = 0.0
    with pytest.raises(RuntimeError, match="source route observation"):
        package_entry._settle_until(
            App(),
            lambda: clock[0] >= 4.0,
            "source route observation",
            timeout_seconds=_smoke_observation_settle_timeout_seconds(
                CertificationScope.SOURCE_VALIDATION
            ),
        )
    assert clock[0] == 3.0

    clock[0] = 0.0
    with pytest.raises(RuntimeError, match="installed route timeout"):
        package_entry._settle_until(
            App(),
            lambda: False,
            "installed route timeout",
            timeout_seconds=_smoke_observation_settle_timeout_seconds(
                CertificationScope.PACKAGE_ASSEMBLY
            ),
        )
    assert clock[0] == 10.0


def test_issue_118_performance_uses_a_real_shown_render_target():
    performance_runtime_source = (
        PROJECT_ROOT
        / "stock_sim"
        / "release"
        / "frontend_v2_performance_runtime.py"
    ).read_text(encoding="utf-8")

    assert "window.show()" in performance_runtime_source
    assert "WA_DontShowOnScreen" not in performance_runtime_source


def test_clean_room_resolves_installation_on_guest_local_filesystem():
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell 7 is required for the clean-room probe")

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
$requiredFunctions = @(
    "Resolve-NormalizedFullyQualifiedPath",
    "Test-NormalizedPathIsSameOrDescendant",
    "Resolve-GuestLocalCertificationInstallRoots"
)
foreach ($functionName in $requiredFunctions) {
    $definition = $ast.Find(
        {
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -eq $functionName
        },
        $true
    )
    if ($null -eq $definition) {
        throw "required guest-local path helper was unavailable"
    }
    Invoke-Expression $definition.Extent.Text
}
$localAppData = [IO.Path]::GetFullPath(
    (Join-Path $env:TEMP "issue118-guest-local-appdata")
)
$mappedEvidence = [IO.Path]::GetFullPath(
    (Join-Path $env:TEMP "issue118-host-mapped-evidence")
)
$roots = Resolve-GuestLocalCertificationInstallRoots `
    -LocalAppDataRoot $localAppData `
    -EvidenceRoot $mappedEvidence `
    -SourceCommit ("a" * 40)
$trailingLocalRoots = Resolve-GuestLocalCertificationInstallRoots `
    -LocalAppDataRoot ($localAppData + [IO.Path]::DirectorySeparatorChar) `
    -EvidenceRoot ($mappedEvidence + [IO.Path]::DirectorySeparatorChar) `
    -SourceCommit ("a" * 40)
$overlapRejected = $false
try {
    Resolve-GuestLocalCertificationInstallRoots `
        -LocalAppDataRoot $localAppData `
        -EvidenceRoot (Join-Path $roots.Root "mapped-evidence") `
        -SourceCommit ("a" * 40) | Out-Null
}
catch {
    $overlapRejected = $true
}
$ancestorOverlapRejected = $false
try {
    Resolve-GuestLocalCertificationInstallRoots `
        -LocalAppDataRoot $localAppData `
        -EvidenceRoot ($localAppData + [IO.Path]::DirectorySeparatorChar) `
        -SourceCommit ("a" * 40) | Out-Null
}
catch {
    $ancestorOverlapRejected = $true
}
$driveRoot = [IO.Path]::GetPathRoot($localAppData)
$driveRootOverlapRejected = $false
try {
    Resolve-GuestLocalCertificationInstallRoots `
        -LocalAppDataRoot $localAppData `
        -EvidenceRoot $driveRoot `
        -SourceCommit ("a" * 40) | Out-Null
}
catch {
    $driveRootOverlapRejected = $true
}
$relativeRootRejected = $false
try {
    Resolve-GuestLocalCertificationInstallRoots `
        -LocalAppDataRoot "relative-local-appdata" `
        -EvidenceRoot $mappedEvidence `
        -SourceCommit ("a" * 40) | Out-Null
}
catch {
    $relativeRootRejected = $true
}
$invalidCommitRejected = $false
try {
    Resolve-GuestLocalCertificationInstallRoots `
        -LocalAppDataRoot $localAppData `
        -EvidenceRoot $mappedEvidence `
        -SourceCommit "ABC123" | Out-Null
}
catch {
    $invalidCommitRejected = $true
}
[pscustomobject]@{
    storage_kind = $roots.StorageKind
    root_is_guest_local = $roots.Root.StartsWith(
        $localAppData + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
    candidate_is_guest_local = $roots.Candidate.StartsWith(
        $roots.Root + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
    widgets_is_guest_local = $roots.Widgets.StartsWith(
        $roots.Root + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
    root_uses_mapped_evidence = $roots.Root.StartsWith(
        $mappedEvidence + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
    roots_are_distinct = $roots.Candidate -cne $roots.Widgets
    trailing_separator_is_idempotent = (
        $trailingLocalRoots.Root -ceq $roots.Root -and
        $trailingLocalRoots.Candidate -ceq $roots.Candidate -and
        $trailingLocalRoots.Widgets -ceq $roots.Widgets
    )
    overlap_rejected = $overlapRejected
    ancestor_overlap_rejected = $ancestorOverlapRejected
    drive_root_contains_install = (
        Test-NormalizedPathIsSameOrDescendant `
            -Path $roots.Root `
            -Root $driveRoot
    )
    drive_root_overlap_rejected = $driveRootOverlapRejected
    unc_share_root_contains_child = (
        Test-NormalizedPathIsSameOrDescendant `
            -Path '\\issue118-host\share\mapped\evidence' `
            -Root '\\issue118-host\share\'
    )
    relative_root_rejected = $relativeRootRejected
    invalid_commit_rejected = $invalidCommitRejected
} | ConvertTo-Json -Compress
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

    assert json.loads(completed.stdout) == {
        "storage_kind": "guest_local_filesystem",
        "root_is_guest_local": True,
        "candidate_is_guest_local": True,
        "widgets_is_guest_local": True,
        "root_uses_mapped_evidence": False,
        "roots_are_distinct": True,
        "trailing_separator_is_idempotent": True,
        "overlap_rejected": True,
        "ancestor_overlap_rejected": True,
        "drive_root_contains_install": True,
        "drive_root_overlap_rejected": True,
        "unc_share_root_contains_child": True,
        "relative_root_rejected": True,
        "invalid_commit_rejected": True,
    }


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


def test_clean_room_ignores_only_typed_stale_uia_boundaries():
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
$helper = $ast.Find(
    {
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq "Test-IsTransientUiAutomationBoundaryFailure"
    },
    $true
)
if ($null -eq $helper -or $parseErrors.Count -ne 0) {
    throw "typed stale UIA boundary classifier was unavailable"
}
Invoke-Expression $helper.Extent.Text
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

function New-TestErrorRecord([Exception]$Exception) {
    return [Management.Automation.ErrorRecord]::new(
        $Exception,
        "issue118-uia-probe",
        [Management.Automation.ErrorCategory]::NotSpecified,
        $null
    )
}

$elementUnavailable = New-TestErrorRecord (
    [System.Windows.Automation.ElementNotAvailableException]::new()
)
$elementUnavailableCom = New-TestErrorRecord (
    [Runtime.InteropServices.COMException]::new(
        "redacted",
        [int]0x80040201
    )
)
$nestedElementUnavailable = New-TestErrorRecord (
    [InvalidOperationException]::new(
        "redacted",
        [Runtime.InteropServices.COMException]::new(
            "redacted",
            [int]0x80040201
        )
    )
)
$otherCom = New-TestErrorRecord (
    [Runtime.InteropServices.COMException]::new(
        "redacted",
        [int]0x80004005
    )
)
$messageOnly = New-TestErrorRecord (
    [InvalidOperationException]::new("Element not available")
)

@(
    Test-IsTransientUiAutomationBoundaryFailure `
        -ErrorRecord $elementUnavailable
    Test-IsTransientUiAutomationBoundaryFailure `
        -ErrorRecord $elementUnavailableCom
    Test-IsTransientUiAutomationBoundaryFailure `
        -ErrorRecord $nestedElementUnavailable
    Test-IsTransientUiAutomationBoundaryFailure -ErrorRecord $otherCom
    Test-IsTransientUiAutomationBoundaryFailure -ErrorRecord $messageOnly
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

    assert json.loads(completed.stdout) == [True, True, True, False, False]


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
    narrator_cleanup = source.index(
        "Stop-InstalledNarratorSession -NarratorSession $narratorSession",
        renderer_loop,
    )
    final_gate_exit = source.index(
        "if (-not $gatePassed)",
        narrator_cleanup,
    )

    assert preflight < fail_closed < migration < widgets < renderer_loop
    assert fail_closed < performance
    assert renderer_loop < narrator_cleanup < final_gate_exit
    assert '--installed-dpi-preflight-report=' in source
    assert 'stage = "installed-dpi-preflight"' in source
    assert "break certification" in source[fail_closed:migration]
    assert "exit 1" in source[final_gate_exit:]


@pytest.mark.parametrize(
    (
        "candidate_bytes",
        "widgets_bytes",
        "expected_candidate_sha256",
        "expected_widgets_sha256",
        "expected_stage",
    ),
    (
        (
            b"not-the-locked-candidate",
            b"not-the-locked-widgets",
            "a" * 64,
            "b" * 64,
            "archive-validation",
        ),
        (
            b"",
            b"",
            "e3b0c44298fc1c149afbf4c8996fb924"
            "27ae41e4649b934ca495991b7852b855",
            "e3b0c44298fc1c149afbf4c8996fb924"
            "27ae41e4649b934ca495991b7852b855",
            "package-extraction",
        ),
    ),
)
def test_clean_room_records_stage_before_preflight_boundary_failure(
    tmp_path,
    candidate_bytes,
    widgets_bytes,
    expected_candidate_sha256,
    expected_widgets_sha256,
    expected_stage,
):
    powershell = Path(
        r"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe"
    )
    if not powershell.is_file():
        pytest.skip("Windows PowerShell 5.1 is required for the guest probe")

    candidate = tmp_path / "candidate.zip"
    candidate.write_bytes(candidate_bytes)
    widgets = tmp_path / "widgets.zip"
    widgets.write_bytes(widgets_bytes)
    evidence_root = tmp_path / "ReleaseEvidence"
    local_app_data = tmp_path / "LocalAppData"
    powershell_environment = {
        key: value
        for key, value in os.environ.items()
        if key.casefold() != "psmodulepath"
    }
    powershell_environment["LOCALAPPDATA"] = str(local_app_data)

    completed = subprocess.run(
        [
            str(powershell),
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(
                PROJECT_ROOT
                / "scripts"
                / "run_frontend_v2_clean_room.ps1"
            ),
            "-PackageArchive",
            str(candidate),
            "-ExpectedArchiveSha256",
            "sha256:" + expected_candidate_sha256,
            "-WidgetsPackageArchive",
            str(widgets),
            "-ExpectedWidgetsArchiveSha256",
            "sha256:" + expected_widgets_sha256,
            "-SourceCommit",
            "c" * 40,
            "-EvidenceDir",
            str(evidence_root),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=powershell_environment,
    )

    assert completed.returncode == 1
    observed_stage = (evidence_root / "clean-room-stage.txt").read_text(
        encoding="utf-8"
    )
    assert observed_stage == expected_stage, completed.stderr
    assert not (evidence_root / "clean-room-report.json").exists()


def test_clean_room_records_installed_preflight_stage_without_executables(
    tmp_path,
):
    powershell = Path(
        r"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe"
    )
    if not powershell.is_file():
        pytest.skip("Windows PowerShell 5.1 is required for the guest probe")

    candidate_source = tmp_path / "candidate-source"
    candidate_source.mkdir()
    (candidate_source / "candidate.txt").write_text("candidate", encoding="utf-8")
    widgets_source = tmp_path / "widgets-source"
    widgets_source.mkdir()
    (widgets_source / "widgets.txt").write_text("widgets", encoding="utf-8")
    candidate = Path(
        shutil.make_archive(
            str(tmp_path / "candidate"),
            "zip",
            root_dir=candidate_source,
        )
    )
    widgets = Path(
        shutil.make_archive(
            str(tmp_path / "widgets"),
            "zip",
            root_dir=widgets_source,
        )
    )
    evidence_root = tmp_path / "ReleaseEvidence"
    local_app_data = tmp_path / "LocalAppData"
    powershell_environment = {
        key: value
        for key, value in os.environ.items()
        if key.casefold() != "psmodulepath"
    }
    powershell_environment["LOCALAPPDATA"] = str(local_app_data)

    completed = subprocess.run(
        [
            str(powershell),
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(
                PROJECT_ROOT
                / "scripts"
                / "run_frontend_v2_clean_room.ps1"
            ),
            "-PackageArchive",
            str(candidate),
            "-ExpectedArchiveSha256",
            "sha256:" + hashlib.sha256(candidate.read_bytes()).hexdigest(),
            "-WidgetsPackageArchive",
            str(widgets),
            "-ExpectedWidgetsArchiveSha256",
            "sha256:" + hashlib.sha256(widgets.read_bytes()).hexdigest(),
            "-SourceCommit",
            "c" * 40,
            "-EvidenceDir",
            str(evidence_root),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=powershell_environment,
    )

    assert completed.returncode == 1
    assert (evidence_root / "clean-room-stage.txt").read_text(
        encoding="utf-8"
    ) == "installed-dpi-preflight"
    report = json.loads(
        (evidence_root / "clean-room-report.json").read_text(encoding="utf-8")
    )
    assert report["schema_version"] == 8
    assert report["stage"] == "installed-dpi-preflight"
    assert report["install_succeeded"] is False
    assert report["passed"] is False


@pytest.mark.parametrize(
    (
        "candidate_ratio",
        "native_dpi",
        "candidate_clean_exit",
        "truncate_identity",
        "host_route",
        "passed",
    ),
    (
        (2.0, 192, True, False, "strategy_library", True),
        (1.0, 192, True, False, "strategy_library", False),
        (2.0, 96, True, False, "strategy_library", False),
        (2.0, 192, False, False, "strategy_library", False),
        (2.0, 192, True, True, "strategy_library", False),
        (2.0, 192, True, False, "run_monitoring", False),
    ),
)
def test_clean_room_native_dpi_preflight_binds_candidate_and_host_evidence(
    tmp_path,
    candidate_ratio,
    native_dpi,
    candidate_clean_exit,
    truncate_identity,
    host_route,
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
        f"uia:1:loading:{host_route}:r1:r1"
        if truncate_identity
        else (
            f"uia:1:loading:{host_route}:r1:r1:"
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
                        "route": host_route,
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
        "uia:1:loading:strategy_library:r1:r1:"
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
                        "route": "strategy_library",
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
    ("clean_room_exit_code", "ack_value", "writes_clean_room_report"),
    (
        (0, None, True),
        (1, None, True),
        (0, "d" * 32, True),
        (0, "e" * 32, True),
        (1, "d" * 32, False),
    ),
)
def test_sandbox_guest_runner_waits_for_host_result_acknowledgment(
    tmp_path,
    clean_room_exit_code,
    ack_value,
    writes_clean_room_report,
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
    if writes_clean_room_report:
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
    else:
        clean_room_runner.write_text(
            "param([Parameter(ValueFromRemainingArguments=$true)]$Ignored)\n"
            "[IO.File]::WriteAllText(\n"
            "    (Join-Path $PSScriptRoot 'clean-room-stage.txt'),\n"
            "    'package-extraction',\n"
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
    report_path = evidence_root / "clean-room-report.json"
    assert report_path.is_file()
    if not writes_clean_room_report:
        boundary_report = json.loads(report_path.read_text(encoding="utf-8"))
        assert boundary_report == {
            "schema_version": 8,
            "stage": "package-extraction",
            "source_commit": "c" * 40,
            "archive_sha256": "sha256:" + "a" * 64,
            "widgets_archive_sha256": "sha256:" + "b" * 64,
            "passed": False,
            "failure_classification": "preflight-boundary",
            "errors": [
                "Clean-room runner failed before machine-readable report "
                "at a redacted boundary"
            ],
        }
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


def test_sandbox_hcs_inventory_parser_expands_multiple_compute_systems():
    powershell = shutil.which("powershell")
    if powershell is None:
        pytest.skip("Windows PowerShell is required for the HCS parser probe")

    script_path = (
        PROJECT_ROOT / "scripts" / "run_frontend_v2_windows_sandbox.ps1"
    )
    probe = r'''
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
            $node.Name -eq "ConvertFrom-WindowsSandboxComputeSystemInventory"
    },
    $true
)
if ($null -eq $helper -or $parseErrors.Count -ne 0) {
    throw "Sandbox HCS inventory parser was unavailable"
}
Invoke-Expression $helper.Extent.Text
$raw = @'
[
  {
    "Id": "baseline-template",
    "SystemType": "VirtualMachine",
    "Owner": "CmService",
    "RuntimeId": "baseline-template",
    "State": "SavedAsTemplate"
  },
  {
    "Id": "candidate",
    "SystemType": "VirtualMachine",
    "Owner": "WindowsSandbox",
    "RuntimeId": "candidate",
    "RuntimeTemplateId": "baseline-template",
    "State": "Running"
  }
]
'@
@(ConvertFrom-WindowsSandboxComputeSystemInventory -RawSnapshot $raw) |
    ConvertTo-Json -Compress
'''
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
        {
            "Id": "baseline-template",
            "SystemType": "VirtualMachine",
            "Owner": "CmService",
            "RuntimeId": "baseline-template",
            "RuntimeTemplateId": "",
        },
        {
            "Id": "candidate",
            "SystemType": "VirtualMachine",
            "Owner": "WindowsSandbox",
            "RuntimeId": "candidate",
            "RuntimeTemplateId": "baseline-template",
        },
    ]


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


def test_clean_room_renderer_lane_evidence_retains_installed_smoke_facts():
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is required for the renderer evidence probe")

    script_path = PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
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
            $node.Name -eq "New-InstalledRendererLaneEvidence"
    },
    $true
)
if ($null -eq $helper) {
    throw "Installed renderer evidence helper was unavailable"
}
. ([scriptblock]::Create($helper.Extent.Text))
$smoke = [pscustomobject][ordered]@{
    schema_version = 4
    certification_scope = "installed"
    renderer_lane = "hardware"
    diagnostic_task_identity = "diagnostic-task-safe"
    campaign_identity = "diagnostic-campaign-safe"
    run_identity = "strategy-run-safe"
    evidence_package_identity = "diagnostic-evidence-safe"
    reproduction_manifest_identity = "reproduction-manifest-safe"
    installed_setup = [ordered]@{
        source_fixture_marker = "must-not-be-retained"
    }
    queued_state_observed = $true
    running_state_observed = $true
    partial_state_observed = $true
    controlled_failure_observed = $true
    safe_failure_reason_verified = $true
    retry_idempotency_verified = $true
    terminal_completion_observed = $true
    system_health_context_verified = $true
    system_health_accessibility_verified = $true
    focus_restoration_verified = $true
    duplicate_work_count = 0
    system_health_identity_graph = @(
        "diagnostic-task-safe",
        "diagnostic-campaign-safe",
        "strategy-run-safe",
        "diagnostic-evidence-safe",
        "reproduction-manifest-safe"
    )
    errors = @()
}
$derived = [ordered]@{
    campaign_identity = "diagnostic-campaign-safe"
    diagnostic_task_identity = "diagnostic-task-safe"
    evidence_package_identity = "diagnostic-evidence-safe"
    errors = @()
    exit_code = 0
    reproduction_manifest_identity = "reproduction-manifest-safe"
    run_identity = "strategy-run-safe"
    uia_accessibility = [ordered]@{ passed = $true }
}
New-InstalledRendererLaneEvidence `
    -SmokeReport $smoke `
    -DerivedEvidence $derived `
    -ExpectedRendererLane "hardware" |
    ConvertTo-Json -Depth 12 -Compress
'''
    completed = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", probe],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UTI_TEST_CLEAN_ROOM_SCRIPT": str(script_path),
        },
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert "installed_setup" not in result
    assert result == {
        "schema_version": 4,
        "certification_scope": "installed",
        "renderer_lane": "hardware",
        "queued_state_observed": True,
        "running_state_observed": True,
        "partial_state_observed": True,
        "controlled_failure_observed": True,
        "safe_failure_reason_verified": True,
        "retry_idempotency_verified": True,
        "terminal_completion_observed": True,
        "system_health_context_verified": True,
        "system_health_accessibility_verified": True,
        "focus_restoration_verified": True,
        "duplicate_work_count": 0,
        "system_health_identity_graph": [
            "diagnostic-task-safe",
            "diagnostic-campaign-safe",
            "strategy-run-safe",
            "diagnostic-evidence-safe",
            "reproduction-manifest-safe",
        ],
        "campaign_identity": "diagnostic-campaign-safe",
        "diagnostic_task_identity": "diagnostic-task-safe",
        "evidence_package_identity": "diagnostic-evidence-safe",
        "errors": [],
        "exit_code": 0,
        "reproduction_manifest_identity": "reproduction-manifest-safe",
        "run_identity": "strategy-run-safe",
        "uia_accessibility": {"passed": True},
    }


def test_clean_room_identity_checkpoint_names_execute_the_real_call_site():
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is required for the checkpoint-name probe")

    script_path = PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
    probe = r'''
$ErrorActionPreference = "Stop"
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $env:UTI_TEST_CLEAN_ROOM_SCRIPT,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {
    throw "clean-room script did not parse"
}
$assignments = @($ast.FindAll(
    {
        param($node)
        $node -is [Management.Automation.Language.AssignmentStatementAst] -and
            $node.Left -is [Management.Automation.Language.VariableExpressionAst]
    },
    $true
))
function Get-UniqueAssignment {
    param([string]$VariableName)
    $matches = @(
        $assignments |
            Where-Object { $_.Left.VariablePath.UserPath -ceq $VariableName }
    )
    if ($matches.Count -ne 1) {
        throw "expected one production assignment"
    }
    return $matches[0].Extent.Text
}
$productionAssignments = @(
    Get-UniqueAssignment -VariableName "expectedJourneySignatures"
    Get-UniqueAssignment -VariableName "expectedIdentityCheckpointNames"
) -join "`n"
$expectedNames = & ([scriptblock]::Create(
    $productionAssignments + "`n@(`$expectedIdentityCheckpointNames)"
))
$rawSmokeCheckpointNames = @(
    "launched_terminal_run",
    "terminal_evidence",
    "disconnected_run",
    "disconnected_evidence",
    "reconnected_pending_run",
    "reconnected_pending_evidence",
    "reconnected_terminal_run",
    "reconnected_evidence",
    "remounted_terminal_run",
    "remounted_terminal_evidence"
) | Sort-Object
[ordered]@{
    expected_names = @($expectedNames)
    raw_smoke_names_match = (
        (@($expectedNames) -join [char]0) -ceq
            ($rawSmokeCheckpointNames -join [char]0)
    )
} | ConvertTo-Json -Depth 4 -Compress
'''
    completed = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", probe],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UTI_TEST_CLEAN_ROOM_SCRIPT": str(script_path),
        },
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["raw_smoke_names_match"] is True
    assert len(result["expected_names"]) == 10


def test_clean_room_renderer_lane_evidence_rejects_unknown_and_sensitive_data():
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is required for the renderer evidence probe")

    script_path = PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
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
            $node.Name -eq "New-InstalledRendererLaneEvidence"
    },
    $true
)
if ($null -eq $helper) {
    throw "Installed renderer evidence helper was unavailable"
}
. ([scriptblock]::Create($helper.Extent.Text))

$derived = [ordered]@{
    campaign_identity = "diagnostic-campaign-safe"
    diagnostic_task_identity = "diagnostic-task-safe"
    evidence_package_identity = "diagnostic-evidence-safe"
    errors = @()
    exit_code = 0
    reproduction_manifest_identity = "reproduction-manifest-safe"
    run_identity = "strategy-run-safe"
    uia_accessibility = [ordered]@{ passed = $true }
}
$unknownSecret = "credential-secret-must-not-leak"
$nestedSecret = "nested-credential-must-not-leak"
$valueSecret = "SELECT 1 -- value-secret-must-not-leak"
$derivedSecret = "derived-api-token-must-not-leak"
function New-ValidSmokeReport {
    return [pscustomobject][ordered]@{
        schema_version = 4
        certification_scope = "installed"
        renderer_lane = "hardware"
        diagnostic_task_identity = "diagnostic-task-safe"
        campaign_identity = "diagnostic-campaign-safe"
        run_identity = "strategy-run-safe"
        evidence_package_identity = "diagnostic-evidence-safe"
        reproduction_manifest_identity = "reproduction-manifest-safe"
        queued_state_observed = $true
        running_state_observed = $true
        partial_state_observed = $true
        controlled_failure_observed = $true
        safe_failure_reason_verified = $true
        retry_idempotency_verified = $true
        terminal_completion_observed = $true
        system_health_context_verified = $true
        system_health_accessibility_verified = $true
        focus_restoration_verified = $true
        duplicate_work_count = 0
        system_health_identity_graph = @(
            "diagnostic-task-safe",
            "diagnostic-campaign-safe",
            "strategy-run-safe",
            "diagnostic-evidence-safe",
            "reproduction-manifest-safe"
        )
    }
}
$unknown = New-ValidSmokeReport
$unknown | Add-Member -NotePropertyName credential -NotePropertyValue $unknownSecret
$nested = New-ValidSmokeReport
$nested.system_health_identity_graph = @(
    [pscustomobject][ordered]@{ credential_backup = $nestedSecret }
)
$sensitiveValue = New-ValidSmokeReport
$sensitiveValue.system_health_identity_graph = @($valueSecret)
$derivedSensitive = [ordered]@{
    campaign_identity = "diagnostic-campaign-safe"
    diagnostic_task_identity = "diagnostic-task-safe"
    evidence_package_identity = "diagnostic-evidence-safe"
    errors = @()
    exit_code = 0
    reproduction_manifest_identity = "reproduction-manifest-safe"
    run_identity = "strategy-run-safe"
    uia_accessibility = [ordered]@{ apiTokenValue = $derivedSecret }
}
$wrongLane = New-ValidSmokeReport
$wrongLane.renderer_lane = "software"

function Invoke-RejectionProbe {
    param(
        [object]$SmokeReport,
        [System.Collections.IDictionary]$DerivedEvidence = $derived
    )
    try {
        New-InstalledRendererLaneEvidence `
            -SmokeReport $SmokeReport `
            -DerivedEvidence $DerivedEvidence `
            -ExpectedRendererLane "hardware" | Out-Null
        return [ordered]@{ rejected = $false; error = "" }
    }
    catch {
        return [ordered]@{
            rejected = $true
            error = [string]$_.Exception.Message
        }
    }
}

[ordered]@{
    unknown = Invoke-RejectionProbe -SmokeReport $unknown
    nested = Invoke-RejectionProbe -SmokeReport $nested
    value = Invoke-RejectionProbe -SmokeReport $sensitiveValue
    derived = Invoke-RejectionProbe `
        -SmokeReport (New-ValidSmokeReport) `
        -DerivedEvidence $derivedSensitive
    wrong_lane = Invoke-RejectionProbe -SmokeReport $wrongLane
} | ConvertTo-Json -Depth 8 -Compress
'''
    completed = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", probe],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UTI_TEST_CLEAN_ROOM_SCRIPT": str(script_path),
        },
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "credential-secret-must-not-leak" not in completed.stdout
    assert "credential-secret-must-not-leak" not in completed.stderr
    assert "nested-credential-must-not-leak" not in completed.stdout
    assert "nested-credential-must-not-leak" not in completed.stderr
    assert "value-secret-must-not-leak" not in completed.stdout
    assert "value-secret-must-not-leak" not in completed.stderr
    assert "derived-api-token-must-not-leak" not in completed.stdout
    assert "derived-api-token-must-not-leak" not in completed.stderr
    result = json.loads(completed.stdout)
    assert result == {
        "unknown": {
            "rejected": True,
            "error": "Installed renderer smoke evidence was rejected at a redacted boundary.",
        },
        "nested": {
            "rejected": True,
            "error": "Installed renderer smoke evidence was rejected at a redacted boundary.",
        },
        "value": {
            "rejected": True,
            "error": "Installed renderer smoke evidence was rejected at a redacted boundary.",
        },
        "derived": {
            "rejected": True,
            "error": "Installed renderer smoke evidence was rejected at a redacted boundary.",
        },
        "wrong_lane": {
            "rejected": True,
            "error": "Installed renderer smoke evidence was rejected at a redacted boundary.",
        },
    }


def test_clean_room_renderer_nested_evidence_rejects_extra_properties():
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is required for the renderer evidence probe")

    script_path = PROJECT_ROOT / "scripts" / "run_frontend_v2_clean_room.ps1"
    probe = r'''
$ErrorActionPreference = "Stop"
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $env:UTI_TEST_CLEAN_ROOM_SCRIPT,
    [ref]$tokens,
    [ref]$parseErrors
)
foreach ($functionName in @(
    "Test-ExactEvidencePropertyNames",
    "ConvertTo-ExactEvidenceStringArray",
    "ConvertTo-InstalledAccessibilityCheckpointEvidence",
    "ConvertTo-ManualTradingRouteAuditEvidence"
)) {
    $helper = $ast.Find(
        {
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -eq $functionName
        },
        $true
    )
    if ($null -eq $helper) {
        throw "Installed renderer evidence helper was unavailable"
    }
    . ([scriptblock]::Create($helper.Extent.Text))
}

$checkpointSecret = "checkpoint-extra-must-not-leak"
$auditSecret = "audit-extra-must-not-leak"
$node = [pscustomobject][ordered]@{
    description_present = $true
    name_present = $true
    object_name = "statusObject"
    role = "StatusBar"
    semantic_terms = @("loading")
    states = @("visible")
    visible = $true
    debug_note = $checkpointSecret
}
$checkpoint = [pscustomobject][ordered]@{
    active_route = "strategy_library"
    captured_at_utc = "2026-08-16T00:00:00+00:00"
    chart_narrative_table_revision = [pscustomobject][ordered]@{
        accepted_revision = 0
        available = $false
        same_revision = $false
    }
    checkpoint = "loading"
    contrast = @()
    evidence_revision = "r1"
    evidence_state = "loading"
    high_contrast = $true
    motion_duration_ms = 0
    nodes = @($node)
    non_color_cue_verified = $true
    non_color_cues = @()
    reduced_motion = $true
    rendered_text_nodes = @()
    route = "strategy_library"
    run_revision = "r1"
    run_state = "loading"
    sequence = 1
    snapshot_identity = "uia:1:loading"
    status_object_name = "statusObject"
    status_semantic_term = "loading"
    text_scale_percent = 200
    wcag_2_2_aa_contrast_verified = $true
    window_device_pixel_ratio = 2.0
}
$audit = [pscustomobject][ordered]@{
    accessible_object_count = 1
    action_patterns_observed = @()
    command_binding_surface_count = 0
    context_menu_surface_count = 0
    coverage = @("qml_object_tree")
    declared_signal_surface_count = 0
    disabled_object_count = 0
    forbidden_action_count = 0
    forbidden_actions = @()
    hidden_object_count = 0
    interactive_object_count = 1
    object_count = 1
    route = "strategy_library"
    shortcut_surface_count = 0
    signal_surface_count = 0
    stage = "running"
    static_read_only_diagnostics = @()
    debug_note = $auditSecret
}

function Invoke-RedactedProbe {
    param([scriptblock]$Action)
    try {
        & $Action | Out-Null
        return [ordered]@{ rejected = $false; error = "" }
    }
    catch {
        return [ordered]@{
            rejected = $true
            error = [string]$_.Exception.Message
        }
    }
}
$checkpointExtraResult = Invoke-RedactedProbe {
    ConvertTo-InstalledAccessibilityCheckpointEvidence `
        -Checkpoints @($checkpoint)
}
$node.PSObject.Properties.Remove("debug_note")
function Invoke-InvalidContrastProbe {
    param(
        [object]$Ratio,
        [object]$RequiredRatio
    )
    $checkpoint.contrast = @(
        [pscustomobject][ordered]@{
            background = "#000000"
            background_token = "surface"
            foreground = "#ffffff"
            foreground_token = "text"
            passed = $true
            ratio = $Ratio
            required_ratio = $RequiredRatio
        }
    )
    return Invoke-RedactedProbe {
        ConvertTo-InstalledAccessibilityCheckpointEvidence `
            -Checkpoints @($checkpoint)
    }
}
[ordered]@{
    checkpoint = $checkpointExtraResult
    audit = Invoke-RedactedProbe {
        ConvertTo-ManualTradingRouteAuditEvidence -Audits @($audit)
    }
    contrast_bool = Invoke-InvalidContrastProbe `
        -Ratio $true `
        -RequiredRatio 4.5
    contrast_datetime = Invoke-InvalidContrastProbe `
        -Ratio ([datetime]"2026-08-16T00:00:00Z") `
        -RequiredRatio 4.5
    contrast_nan = Invoke-InvalidContrastProbe `
        -Ratio ([double]::NaN) `
        -RequiredRatio 4.5
    contrast_infinity = Invoke-InvalidContrastProbe `
        -Ratio 7.0 `
        -RequiredRatio ([double]::PositiveInfinity)
} | ConvertTo-Json -Depth 8 -Compress
'''
    completed = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", probe],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "UTI_TEST_CLEAN_ROOM_SCRIPT": str(script_path),
        },
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "checkpoint-extra-must-not-leak" not in completed.stdout
    assert "checkpoint-extra-must-not-leak" not in completed.stderr
    assert "audit-extra-must-not-leak" not in completed.stdout
    assert "audit-extra-must-not-leak" not in completed.stderr
    expected = {
        "rejected": True,
        "error": "Installed renderer smoke evidence was rejected at a redacted boundary.",
    }
    assert json.loads(completed.stdout) == {
        "checkpoint": expected,
        "audit": expected,
        "contrast_bool": expected,
        "contrast_datetime": expected,
        "contrast_nan": expected,
        "contrast_infinity": expected,
    }
