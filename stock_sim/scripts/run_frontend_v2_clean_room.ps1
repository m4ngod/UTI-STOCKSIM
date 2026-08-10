param(
    [Parameter(Mandatory = $true)]
    [string]$PackageArchive,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedArchiveSha256,
    [Parameter(Mandatory = $true)]
    [string]$WidgetsPackageArchive,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedWidgetsArchiveSha256,
    [Parameter(Mandatory = $true)]
    [string]$SourceCommit,
    [Parameter(Mandatory = $true)]
    [string]$EvidenceDir
)

function Reset-RendererLaneEvidence {
    param(
        [Parameter(Mandatory = $true)]
        [string]$EvidenceRoot,
        [Parameter(Mandatory = $true)]
        [string]$LaneDirectory
    )

    $resolvedRoot = [IO.Path]::GetFullPath($EvidenceRoot)
    $resolvedLane = [IO.Path]::GetFullPath($LaneDirectory)
    $allowedLanePaths = @(
        [IO.Path]::GetFullPath((Join-Path $resolvedRoot "hardware")),
        [IO.Path]::GetFullPath((Join-Path $resolvedRoot "software"))
    )
    $laneIsAllowed = $false
    foreach ($allowedLanePath in $allowedLanePaths) {
        if ([string]::Equals(
            $resolvedLane,
            $allowedLanePath,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            $laneIsAllowed = $true
            break
        }
    }
    if (-not $laneIsAllowed) {
        throw "Refusing to reset a renderer lane outside the evidence root."
    }
    if (Test-Path -LiteralPath $resolvedLane) {
        Remove-Item -LiteralPath $resolvedLane -Recurse -Force
    }
    New-Item -ItemType Directory -Path $resolvedLane | Out-Null
}

function ConvertTo-ReleaseErrorList {
    param(
        [AllowNull()]
        [object]$Errors
    )

    foreach ($errorValue in @($Errors)) {
        $message = [string]$errorValue
        if (-not [string]::IsNullOrWhiteSpace($message)) {
            $message
        }
    }
}

function Test-ExactStringArray {
    param(
        [AllowNull()]
        [object]$Actual,
        [AllowNull()]
        [object]$Expected
    )

    $actualValues = @($Actual | ForEach-Object { [string]$_ })
    $expectedValues = @($Expected | ForEach-Object { [string]$_ })
    return (
        $actualValues.Count -eq $expectedValues.Count -and
        ($actualValues -join [char]0) -ceq
            ($expectedValues -join [char]0)
    )
}

function Test-DurableIdentityMap {
    param(
        [AllowNull()]
        [object]$Actual,
        [AllowNull()]
        [object]$Expected
    )

    $expectedKinds = @(
        "Strategy", "Recipe", "Task", "Campaign",
        "Run", "Evidence", "Finding", "Manifest"
    )
    if ($null -eq $Actual -or $null -eq $Expected) {
        return $false
    }
    $actualKinds = @($Actual.PSObject.Properties.Name | Sort-Object)
    if (-not (Test-ExactStringArray `
        -Actual $actualKinds `
        -Expected @($expectedKinds | Sort-Object)
    )) {
        return $false
    }
    foreach ($kind in $expectedKinds) {
        $actualProperty = $Actual.PSObject.Properties[$kind]
        $expectedProperty = $Expected.PSObject.Properties[$kind]
        if (
            $null -eq $actualProperty -or
            $null -eq $expectedProperty -or
            -not (Test-ExactStringArray `
                -Actual $actualProperty.Value `
                -Expected $expectedProperty.Value
            )
        ) {
            return $false
        }
    }
    return $true
}

function Invoke-InstalledRollbackLane {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Lane,
        [Parameter(Mandatory = $true)]
        [string]$EvidenceRoot,
        [Parameter(Mandatory = $true)]
        [string]$CandidateExecutable,
        [Parameter(Mandatory = $true)]
        [string]$WidgetsExecutable,
        [Parameter(Mandatory = $true)]
        [string]$SourceCommit,
        [Parameter(Mandatory = $true)]
        [string]$CandidateDependencyLockSha256,
        [Parameter(Mandatory = $true)]
        [string]$WidgetsDependencyLockSha256
    )

    $failed = [ordered]@{
        lane = $Lane
        source_commit = $SourceCommit
        passed = $false
        same_source_commit = $false
        same_dependency_lock = $false
        identity_retention_verified = $false
        task_handle_continuity_verified = $false
        order_state_continuity_verified = $false
        reopen_verified = $false
        destructive_migration = $true
        errors = @("Installed rollback lane was not completed")
    }
    $smokePath = Join-Path $EvidenceRoot "$Lane\smoke-report.json"
    $sourcePersistence = Join-Path $EvidenceRoot "$Lane\v1-persistence"
    if (
        -not (Test-Path -LiteralPath $smokePath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $sourcePersistence -PathType Container)
    ) {
        return $failed
    }
    $smoke = Get-Content -LiteralPath $smokePath -Raw -Encoding utf8 |
        ConvertFrom-Json
    $laneRoot = Join-Path $EvidenceRoot "installed-rollback-$Lane"
    $supportedCopy = Join-Path $laneRoot "supported-data-copy"
    New-Item -ItemType Directory -Path $laneRoot | Out-Null
    Copy-Item `
        -LiteralPath $sourcePersistence `
        -Destination $supportedCopy `
        -Recurse

    $commonArguments = @(
        "--supported-data-copy=$supportedCopy",
        "--campaign-id=$([string]$smoke.campaign_identity)",
        "--evidence-package-id=$([string]$smoke.evidence_package_identity)",
        "--selected-manifest-id=$([string]$smoke.reproduction_manifest_identity)",
        "--diagnostic-task-id=$([string]$smoke.diagnostic_task_identity)",
        "--source-commit=$SourceCommit"
    )
    $beforePath = Join-Path $laneRoot "candidate-before.json"
    & $CandidateExecutable "--recovery-report=$beforePath" @commonArguments
    $beforeExitCode = $LASTEXITCODE

    $widgetsDir = Join-Path $laneRoot "widgets"
    New-Item -ItemType Directory -Path $widgetsDir | Out-Null
    & $WidgetsExecutable "--smoke-report-dir=$widgetsDir" @commonArguments
    $widgetsExitCode = $LASTEXITCODE
    $widgetsPath = Join-Path $widgetsDir "smoke-report.json"

    $afterPath = Join-Path $laneRoot "candidate-after.json"
    & $CandidateExecutable "--recovery-report=$afterPath" @commonArguments
    $afterExitCode = $LASTEXITCODE
    if (
        -not (Test-Path -LiteralPath $beforePath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $widgetsPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $afterPath -PathType Leaf)
    ) {
        return $failed
    }

    $before = Get-Content -LiteralPath $beforePath -Raw -Encoding utf8 |
        ConvertFrom-Json
    $widgets = Get-Content -LiteralPath $widgetsPath -Raw -Encoding utf8 |
        ConvertFrom-Json
    $after = Get-Content -LiteralPath $afterPath -Raw -Encoding utf8 |
        ConvertFrom-Json
    $expected = [pscustomobject][ordered]@{
        Strategy = @([string]$smoke.strategy_identity)
        Recipe = @([string]$smoke.approved_recipe_identity)
        Task = @([string]$smoke.diagnostic_task_identity)
        Campaign = @([string]$smoke.campaign_identity)
        Run = @([string]$smoke.run_identity)
        Evidence = @([string]$smoke.evidence_package_identity)
        Finding = @($smoke.evidence_identity_sets.findings)
        Manifest = @([string]$smoke.reproduction_manifest_identity)
    }
    $identitiesMatch = (
        (Test-DurableIdentityMap -Actual $before.durable_identities -Expected $expected) -and
        (Test-DurableIdentityMap -Actual $widgets.durable_identities -Expected $expected) -and
        (Test-DurableIdentityMap -Actual $after.durable_identities -Expected $expected)
    )
    $taskHandlesMatch = (
        (Test-ExactStringArray -Actual $before.task_handle_identities -Expected $smoke.task_handle_identities) -and
        (Test-ExactStringArray -Actual $widgets.task_handle_identities -Expected $smoke.task_handle_identities) -and
        (Test-ExactStringArray -Actual $after.task_handle_identities -Expected $smoke.task_handle_identities)
    )
    $orderStateMatches = (
        [string]$before.order_state_sha256 -eq
            [string]$widgets.order_state_sha256 -and
        [string]$before.order_state_sha256 -eq
            [string]$after.order_state_sha256 -and
        [int]$before.order_count -eq [int]$widgets.order_count -and
        [int]$before.order_count -eq [int]$after.order_count
    )
    $sameSourceCommit = (
        [string]$before.source_commit -eq $SourceCommit -and
        [string]$widgets.source_commit -eq $SourceCommit -and
        [string]$after.source_commit -eq $SourceCommit
    )
    $sameDependencyLock = (
        -not [string]::IsNullOrWhiteSpace($CandidateDependencyLockSha256) -and
        $CandidateDependencyLockSha256 -eq $WidgetsDependencyLockSha256
    )
    $reopenVerified = (
        $beforeExitCode -eq 0 -and
        $widgetsExitCode -eq 0 -and
        $afterExitCode -eq 0 -and
        $before.clean_exit -eq $true -and
        $widgets.clean_exit -eq $true -and
        $widgets.supported_data_copy_verified -eq $true -and
        $after.clean_exit -eq $true
    )
    $passed = (
        $identitiesMatch -and
        $taskHandlesMatch -and
        $orderStateMatches -and
        $sameSourceCommit -and
        $sameDependencyLock -and
        $reopenVerified
    )
    return [ordered]@{
        lane = $Lane
        source_commit = $SourceCommit
        passed = $passed
        same_source_commit = $sameSourceCommit
        same_dependency_lock = $sameDependencyLock
        identity_retention_verified = $identitiesMatch
        task_handle_continuity_verified = $taskHandlesMatch
        order_state_continuity_verified = $orderStateMatches
        reopen_verified = $reopenVerified
        destructive_migration = $false
        candidate_before = $before
        retained_widgets = $widgets
        candidate_after = $after
        errors = @(
            if (-not $passed) {
                "Installed $Lane rollback lane failed"
            }
        )
    }
}

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

if ($SourceCommit -cnotmatch '^[0-9a-f]{40}$') {
    throw "SourceCommit must be a lowercase 40-character Git commit."
}
if ($ExpectedArchiveSha256 -cnotmatch '^sha256:[0-9a-f]{64}$') {
    throw "ExpectedArchiveSha256 must be a lowercase sha256 digest."
}
if ($ExpectedWidgetsArchiveSha256 -cnotmatch '^sha256:[0-9a-f]{64}$') {
    throw "ExpectedWidgetsArchiveSha256 must be a lowercase sha256 digest."
}
$packageArchiveName = Split-Path -Leaf $PackageArchive
if ($packageArchiveName -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
    throw "Package archive name contains unsafe characters."
}
$widgetsArchiveName = Split-Path -Leaf $WidgetsPackageArchive
if ($widgetsArchiveName -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
    throw "Widgets archive name contains unsafe characters."
}

$resolvedEvidence = [IO.Path]::GetFullPath($EvidenceDir)
$installDir = Join-Path $resolvedEvidence "installed"
$resolvedInstall = [IO.Path]::GetFullPath($installDir)
$widgetsInstallDir = Join-Path $resolvedEvidence "widgets-installed"
$resolvedWidgetsInstall = [IO.Path]::GetFullPath($widgetsInstallDir)
if (-not $resolvedInstall.StartsWith(
    $resolvedEvidence + [IO.Path]::DirectorySeparatorChar,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "Refusing to install outside the evidence directory."
}
if (-not $resolvedWidgetsInstall.StartsWith(
    $resolvedEvidence + [IO.Path]::DirectorySeparatorChar,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "Refusing to install Widgets outside the evidence directory."
}
New-Item -ItemType Directory -Force -Path $resolvedEvidence | Out-Null
if (Test-Path -LiteralPath $resolvedInstall) {
    Remove-Item -LiteralPath $resolvedInstall -Recurse -Force
}
if (Test-Path -LiteralPath $resolvedWidgetsInstall) {
    Remove-Item -LiteralPath $resolvedWidgetsInstall -Recurse -Force
}

$archiveHash = (Get-FileHash -LiteralPath $PackageArchive -Algorithm SHA256).Hash.ToLowerInvariant()
$normalizedExpected = $ExpectedArchiveSha256.ToLowerInvariant().Replace("sha256:", "")
if ($archiveHash -ne $normalizedExpected) {
    throw "Package archive checksum does not match the expected SHA-256."
}
$widgetsArchiveHash = (
    Get-FileHash -LiteralPath $WidgetsPackageArchive -Algorithm SHA256
).Hash.ToLowerInvariant()
$normalizedWidgetsExpected = (
    $ExpectedWidgetsArchiveSha256.ToLowerInvariant().Replace("sha256:", "")
)
if ($widgetsArchiveHash -ne $normalizedWidgetsExpected) {
    throw "Widgets archive checksum does not match the expected SHA-256."
}

$os = Get-CimInstance Win32_OperatingSystem
$operatingSystem = "$($os.Caption) $($os.Version)"
$architecture = $env:PROCESSOR_ARCHITECTURE
$userName = $env:USERNAME
$isWindowsSandbox = (
    $userName -eq "WDAGUtilityAccount" -and
    (Test-Path -LiteralPath "C:\Users\WDAGUtilityAccount")
)
$networkEnumerationSucceeded = $false
$networkAdaptersUp = @()
try {
    $networkAdaptersUp = @(
        Get-NetAdapter -ErrorAction Stop |
            Where-Object { $_.Status -eq "Up" } |
            ForEach-Object { $_.Name }
    )
    $networkEnumerationSucceeded = $true
}
catch {
    $networkAdaptersUp = @("inventory-failed: $($_.Exception.Message)")
}
$pythonCommands = @(
    Get-Command python, py -CommandType Application -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch "\\WindowsApps\\" }
)
$compilerCommands = @(
    Get-Command cl, gcc, clang -CommandType Application -ErrorAction SilentlyContinue
)
$uninstallRoots = @(
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*"
)
$installedApplications = @(
    foreach ($root in $uninstallRoots) {
        Get-ItemProperty -Path $root -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName } |
            ForEach-Object { $_.DisplayName }
    }
)
$pythonKnownPaths = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python"),
    (Join-Path $env:ProgramFiles "Python*"),
    (Join-Path ${env:ProgramFiles(x86)} "Python*")
)
$pythonInstallations = @(
    @(
        $pythonCommands | ForEach-Object { $_.Source }
        $installedApplications |
            Where-Object { $_ -match "^Python(?:\s|$)" }
        $pythonKnownPaths |
            Where-Object { $_ -and (Test-Path -Path $_) }
    ) | Sort-Object -Unique
)
$compilerKnownPaths = @(
    (Join-Path $env:ProgramFiles "Microsoft Visual Studio"),
    (Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio"),
    (Join-Path $env:ProgramFiles "LLVM"),
    "C:\msys64",
    "C:\mingw64"
)
$compilerInstallations = @(
    @(
        $compilerCommands | ForEach-Object { $_.Source }
        $installedApplications |
            Where-Object {
                $_ -match "Visual Studio.*(?:Build Tools|Community|Professional|Enterprise)" -or
                $_ -match "^(?:LLVM|MinGW|MSYS2)"
            }
        $compilerKnownPaths |
            Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    ) | Sort-Object -Unique
)
$cacheCandidates = @(
    (Join-Path $env:LOCALAPPDATA "pip\Cache"),
    (Join-Path $env:LOCALAPPDATA "Nuitka"),
    (Join-Path $env:LOCALAPPDATA "pypa"),
    (Join-Path $env:LOCALAPPDATA "uv\cache"),
    (Join-Path $env:APPDATA "Python"),
    (Join-Path $env:USERPROFILE ".cache"),
    (Join-Path $env:USERPROFILE ".cache\pip"),
    (Join-Path $env:USERPROFILE ".cache\uv")
)
$dependencyCachePaths = @(
    @(
        $cacheCandidates | Where-Object { Test-Path -LiteralPath $_ }
    ) | Sort-Object -Unique
)
$dependencyCachePresent = $dependencyCachePaths.Count -gt 0

Expand-Archive -LiteralPath $PackageArchive -DestinationPath $resolvedInstall
Expand-Archive `
    -LiteralPath $WidgetsPackageArchive `
    -DestinationPath $resolvedWidgetsInstall
$executable = Get-ChildItem -LiteralPath $resolvedInstall -Recurse -File |
    Where-Object { $_.Name -eq "UTI-Frontend-V2.exe" } |
    Select-Object -First 1
$installSucceeded = [bool]$executable
$widgetsExecutable = (
    Get-ChildItem -LiteralPath $resolvedWidgetsInstall -Recurse -File |
        Where-Object { $_.Name -eq "UTI-Widgets-Rollback.exe" } |
        Select-Object -First 1
)
$widgetsInstallSucceeded = [bool]$widgetsExecutable
$candidateToolchainLock = Get-ChildItem `
    -LiteralPath $resolvedInstall `
    -Recurse `
    -File `
    -Filter "frontend_v2_toolchain.lock.json" |
    Select-Object -First 1
$widgetsToolchainLock = Get-ChildItem `
    -LiteralPath $resolvedWidgetsInstall `
    -Recurse `
    -File `
    -Filter "frontend_v2_toolchain.lock.json" |
    Select-Object -First 1
$candidateDependencyLockSha256 = ""
$widgetsDependencyLockSha256 = ""
if ($candidateToolchainLock) {
    $candidateDependencyLockSha256 = "sha256:" + (
        Get-FileHash `
            -LiteralPath $candidateToolchainLock.FullName `
            -Algorithm SHA256
    ).Hash.ToLowerInvariant()
}
if ($widgetsToolchainLock) {
    $widgetsDependencyLockSha256 = "sha256:" + (
        Get-FileHash `
            -LiteralPath $widgetsToolchainLock.FullName `
            -Algorithm SHA256
    ).Hash.ToLowerInvariant()
}

$freshInstallMigration = [ordered]@{
    source_commit = $SourceCommit
    passed = $false
    schema_migration_verified = $false
    bookmark_migration_verified = $false
    deterministic = $false
    idempotent = $false
    identity_retention_verified = $false
    reopen_verified = $false
    destructive_migration = $true
    errors = @("Fresh install migration probe was not run")
}
$copiedWave3Migration = [ordered]@{
    source_commit = $SourceCommit
    passed = $false
    schema_migration_verified = $false
    bookmark_migration_verified = $false
    deterministic = $false
    idempotent = $false
    identity_retention_verified = $false
    reopen_verified = $false
    destructive_migration = $true
    errors = @("Copied Wave 3 migration probe was not run")
}
$observationLedgerReadiness = [ordered]@{
    source_commit = $SourceCommit
    passed = $false
    legacy_inventory_available = $false
    legacy_route_count = 0
    observation_ledger_configuration_available = $false
    observation_window_started = $false
    destructive_migration = $false
    errors = @("Observation-ledger readiness probe was not run")
}
if ($installSucceeded) {
    $migrationEvidenceDir = Join-Path $resolvedEvidence "migration"
    New-Item -ItemType Directory -Path $migrationEvidenceDir | Out-Null
    $freshReportPath = Join-Path $migrationEvidenceDir "fresh-install.json"
    & $executable.FullName `
        "--migration-report=$freshReportPath" `
        "--migration-kind=fresh" `
        "--migration-work-root=$(Join-Path $migrationEvidenceDir 'fresh-work')" `
        "--source-commit=$SourceCommit"
    $freshExitCode = $LASTEXITCODE
    if (Test-Path -LiteralPath $freshReportPath -PathType Leaf) {
        $freshInstallMigration = Get-Content `
            -LiteralPath $freshReportPath `
            -Raw `
            -Encoding utf8 | ConvertFrom-Json
        $freshInstallMigration | Add-Member `
            -NotePropertyName exit_code `
            -NotePropertyValue $freshExitCode `
            -Force
    }
    $copiedReportPath = Join-Path $migrationEvidenceDir "copied-wave3.json"
    & $executable.FullName `
        "--migration-report=$copiedReportPath" `
        "--migration-kind=copied-wave3" `
        "--migration-work-root=$(Join-Path $migrationEvidenceDir 'copied-work')" `
        "--source-commit=$SourceCommit"
    $copiedExitCode = $LASTEXITCODE
    if (Test-Path -LiteralPath $copiedReportPath -PathType Leaf) {
        $copiedWave3Migration = Get-Content `
            -LiteralPath $copiedReportPath `
            -Raw `
            -Encoding utf8 | ConvertFrom-Json
        $copiedWave3Migration | Add-Member `
            -NotePropertyName exit_code `
            -NotePropertyValue $copiedExitCode `
            -Force
    }
    $readinessReportPath = Join-Path `
        $migrationEvidenceDir `
        "observation-ledger-readiness.json"
    & $executable.FullName `
        "--observation-readiness-report=$readinessReportPath" `
        "--source-commit=$SourceCommit"
    $readinessExitCode = $LASTEXITCODE
    if (Test-Path -LiteralPath $readinessReportPath -PathType Leaf) {
        $observationLedgerReadiness = Get-Content `
            -LiteralPath $readinessReportPath `
            -Raw `
            -Encoding utf8 | ConvertFrom-Json
        $observationLedgerReadiness | Add-Member `
            -NotePropertyName exit_code `
            -NotePropertyValue $readinessExitCode `
            -Force
    }
}
$widgetsRollback = [ordered]@{
    exit_code = -1
    source_commit = ""
    source_commit_matches = $false
    mode = ""
    placeholder_panels = @()
    real_panel_count = 0
    manual_trading_action_count = -1
    opened_panels = @()
    clean_exit = $false
    errors = @("Widgets rollback smoke was not run")
}
if ($widgetsInstallSucceeded) {
    $widgetsSmokeDir = Join-Path $resolvedEvidence "widgets-smoke"
    if (Test-Path -LiteralPath $widgetsSmokeDir) {
        Remove-Item -LiteralPath $widgetsSmokeDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $widgetsSmokeDir | Out-Null
    & $widgetsExecutable.FullName `
        "--source-commit=$SourceCommit" `
        "--smoke-report-dir=$widgetsSmokeDir"
    $widgetsExitCode = $LASTEXITCODE
    $widgetsSmokePath = Join-Path $widgetsSmokeDir "smoke-report.json"
    if (Test-Path -LiteralPath $widgetsSmokePath -PathType Leaf) {
        $widgetsSmoke = (
            Get-Content -LiteralPath $widgetsSmokePath -Raw -Encoding utf8 |
                ConvertFrom-Json
        )
        $widgetsCleanExit = (
            $widgetsSmoke.clean_exit -is [bool] -and
            $widgetsSmoke.clean_exit -eq $true
        )
        $widgetsRollback = [ordered]@{
            exit_code = $widgetsExitCode
            source_commit = [string]$widgetsSmoke.source_commit
            source_commit_matches = (
                [string]$widgetsSmoke.source_commit -eq $SourceCommit
            )
            mode = [string]$widgetsSmoke.mode
            placeholder_panels = @($widgetsSmoke.placeholder_panels)
            real_panel_count = [int]$widgetsSmoke.real_panel_count
            manual_trading_action_count = (
                [int]$widgetsSmoke.manual_trading_action_count
            )
            opened_panels = @($widgetsSmoke.opened_panels)
            clean_exit = $widgetsCleanExit
            errors = @(
                ConvertTo-ReleaseErrorList -Errors $widgetsSmoke.errors
            )
        }
    }
    else {
        $widgetsRollback.exit_code = $widgetsExitCode
        $widgetsRollback.errors = @(
            "Widgets smoke-report.json was not produced"
        )
    }
}
$rendererLanes = [ordered]@{}
$installedPerformance = [ordered]@{}
if ($installSucceeded) {
    $expectedJourneySignatures = @(
        "launched_terminal_run|run_monitoring|terminal|ready|fresh|fresh",
        "terminal_evidence|evidence_and_findings|terminal|ready|fresh|fresh",
        "disconnected_run|run_monitoring|terminal|ready|disconnected|fresh",
        "disconnected_evidence|evidence_and_findings|terminal|ready|disconnected|disconnected",
        "reconnected_pending_run|run_monitoring|terminal|ready|stale|stale",
        "reconnected_pending_evidence|evidence_and_findings|terminal|ready|stale|stale",
        "reconnected_terminal_run|run_monitoring|terminal|ready|fresh|stale",
        "reconnected_evidence|evidence_and_findings|terminal|ready|fresh|fresh",
        "remounted_terminal_run|run_monitoring|terminal|ready|fresh|fresh",
        "remounted_terminal_evidence|evidence_and_findings|terminal|ready|fresh|fresh"
    )
    $expectedProductionPath = @(
        "DiagnosticsApplication",
        "FileBackedV1Persistence",
        "LiveStrategyDiagnosticsV1StrategyLibraryApplicationAdapter",
        "LiveStrategyLibraryAdapter",
        "LiveStrategyDiagnosticsV1ScenarioLabApplicationAdapter",
        "LiveScenarioLabAdapter",
        "LiveStrategyDiagnosticsV1DiagnosticTasksApplicationAdapter",
        "LiveDiagnosticTasksAdapter",
        "LiveStrategyDiagnosticsV1ApplicationAdapter",
        "EventBridge",
        "LiveRunMonitoringAdapter",
        "LiveEvidenceAndFindingsAdapter",
        "LiveStrategyDiagnosticsV1SystemHealthApplicationAdapter",
        "LiveSystemHealthAdapter",
        "JourneyWorkspaceHost"
    )
    $expectedRoutes = @(
        "strategy_library",
        "scenario_lab",
        "diagnostic_tasks",
        "run_monitoring",
        "evidence_and_findings",
        "system_health"
    )
    $expectedAcceptedCommandKinds = @(
        "create_diagnostic_task",
        "revise_configuration",
        "validate_configuration",
        "approve_configuration",
        "start_formal_diagnostic_campaign"
    )
    $expectedSetupCommandKinds = @(
        "compare_formal_strategy_set",
        "select_formal_strategy_set",
        "create_recipe_draft",
        "validate_recipe_draft",
        "approve_recipe",
        "materialize_reference_path",
        "compose_formal_scenario_set",
        "resolve_execution_assumptions",
        "select_formal_scenario_set"
    )
    $expectedTransitions = @(
        "connected",
        "disconnected",
        "reconnected",
        "remounted",
        "closed"
    )
    $requiredVisualGroups = @(
        @(
            "launched_terminal_run",
            "disconnected_run"
        ),
        @(
            "terminal_evidence",
            "disconnected_evidence"
        )
    )
    foreach ($lane in @("hardware", "software")) {
        $laneDir = Join-Path $resolvedEvidence $lane
        Reset-RendererLaneEvidence `
            -EvidenceRoot $resolvedEvidence `
            -LaneDirectory $laneDir
        & $executable.FullName `
            "--renderer-lane=$lane" `
            "--smoke-report-dir=$laneDir" `
            "--source-commit=$SourceCommit"
        $exitCode = $LASTEXITCODE
        $performancePath = Join-Path $laneDir "performance.json"
        & $executable.FullName `
            "--renderer-lane=$lane" `
            "--performance-report=$performancePath" `
            "--performance-duration-seconds=60" `
            "--source-commit=$SourceCommit"
        $performanceExitCode = $LASTEXITCODE
        if (Test-Path -LiteralPath $performancePath -PathType Leaf) {
            $performanceReport = Get-Content `
                -LiteralPath $performancePath `
                -Raw `
                -Encoding utf8 | ConvertFrom-Json
            $performanceReport | Add-Member `
                -NotePropertyName installed_exit_code `
                -NotePropertyValue $performanceExitCode `
                -Force
            $installedPerformance[$lane] = $performanceReport
        }
        else {
            $installedPerformance[$lane] = [ordered]@{
                status = "failed"
                lane = $lane
                source_commit = $SourceCommit
                installed_exit_code = $performanceExitCode
                errors = @("Installed performance report was not produced")
            }
        }
        $smokePath = Join-Path $laneDir "smoke-report.json"
        if (Test-Path -LiteralPath $smokePath) {
            $smoke = Get-Content -LiteralPath $smokePath -Raw -Encoding utf8 |
                ConvertFrom-Json
            $observations = @($smoke.observations)
            $journeySignatures = @(
                $observations |
                    ForEach-Object {
                        @(
                            [string]$_.stage,
                            [string]$_.route,
                            [string]$_.run_state,
                            [string]$_.evidence_state,
                            [string]$_.run_freshness,
                            [string]$_.evidence_freshness
                        ) -join "|"
                    }
            )
            $statesMatch = (
                ($journeySignatures -join "`n") -eq
                    ($expectedJourneySignatures -join "`n")
            )
            $screenshotNames = @(
                $observations |
                    ForEach-Object { [string]$_.screenshot }
            )
            $screenshotHashes = @()
            $screenshotHashesByStage = @{}
            $screenshotEvidence = @()
            $screenshotsPresent = (
                $screenshotNames.Count -eq
                    $expectedJourneySignatures.Count
            )
            foreach ($observation in $observations) {
                $screenshotName = [string]$observation.screenshot
                $safeName = [IO.Path]::GetFileName($screenshotName)
                if (
                    [string]::IsNullOrWhiteSpace($screenshotName) -or
                    $safeName -ne $screenshotName
                ) {
                    $screenshotsPresent = $false
                    continue
                }
                $screenshotPath = Join-Path $laneDir $safeName
                if (-not (Test-Path -LiteralPath $screenshotPath -PathType Leaf)) {
                    $screenshotsPresent = $false
                    continue
                }
                $screenshotHash = (
                    Get-FileHash -LiteralPath $screenshotPath -Algorithm SHA256
                ).Hash.ToLowerInvariant()
                $qualifiedHash = "sha256:$screenshotHash"
                $screenshotHashes += $qualifiedHash
                $screenshotHashesByStage[
                    [string]$observation.stage
                ] = $qualifiedHash
                $relativeScreenshotPath = "$lane/$safeName"
                $screenshotEvidence += [ordered]@{
                    stage = [string]$observation.stage
                    relative_path = $relativeScreenshotPath
                    sha256 = $qualifiedHash
                }
            }
            $majorStatesAreDistinct = $true
            foreach ($visualGroup in $requiredVisualGroups) {
                $groupHashes = @(
                    $visualGroup |
                        ForEach-Object {
                            $screenshotHashesByStage[[string]$_]
                        }
                )
                if (
                    $groupHashes.Count -ne $visualGroup.Count -or
                    @($groupHashes | Sort-Object -Unique).Count -ne
                        $visualGroup.Count
                ) {
                    $majorStatesAreDistinct = $false
                }
            }
            $screenshotsDistinct = (
                $screenshotsPresent -and
                $screenshotHashes.Count -eq
                    $expectedJourneySignatures.Count -and
                $majorStatesAreDistinct
            )
            $productionPath = @($smoke.production_path)
            $routesRendered = @($smoke.routes_rendered)
            $connectionTransitions = @($smoke.connection_transitions)
            $productionPathMatches = (
                ($productionPath -join "|") -eq
                    ($expectedProductionPath -join "|")
            )
            $routesMatch = (
                ($routesRendered -join "|") -eq
                    ($expectedRoutes -join "|")
            )
            $connectionTransitionsMatch = (
                ($connectionTransitions -join "|") -eq
                    ($expectedTransitions -join "|")
            )
            $acceptedCommandKinds = @($smoke.accepted_command_kinds)
            $installedSetupCommandKinds = @(
                $smoke.installed_setup_command_kinds
            )
            $installedRecipeDraftIdentities = @(
                $smoke.installed_recipe_draft_identities
            )
            $installedRecipeValidationIdentities = @(
                $smoke.installed_recipe_validation_identities
            )
            $installedApprovedRecipeIdentities = @(
                $smoke.installed_approved_recipe_identities
            )
            $installedMaterializationTaskHandleIdentities = @(
                $smoke.installed_materialization_task_handle_identities
            )
            $installedMaterializedPathIdentities = @(
                $smoke.installed_materialized_path_identities
            )
            $installedMaterializedScenarioIdentities = @(
                $smoke.installed_materialized_scenario_identities
            )
            $installedRecipeFamilyValid = $true
            foreach ($identityFamily in @(
                $installedRecipeDraftIdentities,
                $installedRecipeValidationIdentities,
                $installedApprovedRecipeIdentities,
                $installedMaterializationTaskHandleIdentities,
                $installedMaterializedPathIdentities,
                $installedMaterializedScenarioIdentities
            )) {
                if (
                    @($identityFamily).Count -ne 14 -or
                    @(
                        $identityFamily |
                            Where-Object {
                                [string]::IsNullOrWhiteSpace([string]$_)
                            }
                    ).Count -ne 0 -or
                    @($identityFamily | Sort-Object -Unique).Count -ne 14
                ) {
                    $installedRecipeFamilyValid = $false
                }
            }
            $selectedRecipeIndex = [Array]::IndexOf(
                [Array]$installedApprovedRecipeIdentities,
                [string]$smoke.approved_recipe_identity
            )
            $installedRecipeBindingValid = (
                $selectedRecipeIndex -ge 0 -and
                [string]$smoke.recipe_draft_identity -eq
                    [string]$installedRecipeDraftIdentities[$selectedRecipeIndex] -and
                [string]$smoke.recipe_validation_identity -eq
                    [string]$installedRecipeValidationIdentities[$selectedRecipeIndex] -and
                [string]$smoke.materialization_task_handle_identity -eq
                    [string]$installedMaterializationTaskHandleIdentities[$selectedRecipeIndex] -and
                [string]$smoke.materialized_path_identity -eq
                    [string]$installedMaterializedPathIdentities[$selectedRecipeIndex] -and
                [string]$smoke.materialized_scenario_identity -eq
                    [string]$installedMaterializedScenarioIdentities[$selectedRecipeIndex]
            )
            $terminalCaseBindingValid = (
                $smoke.terminal_case_manifest_binding_verified -is [bool] -and
                $smoke.terminal_case_manifest_binding_verified -eq $true -and
                -not [string]::IsNullOrWhiteSpace(
                    [string]$smoke.terminal_campaign_case_identity
                ) -and
                [string]$smoke.terminal_campaign_case_identity -eq
                    [string]$smoke.case_identity -and
                -not [string]::IsNullOrWhiteSpace(
                    [string]$smoke.terminal_selected_campaign_case_identity
                ) -and
                [string]$smoke.terminal_selected_campaign_case_identity -eq
                    [string]$smoke.materialized_scenario_identity -and
                -not [string]::IsNullOrWhiteSpace(
                    [string]$smoke.terminal_node_market_scenario_identity
                ) -and
                [string]$smoke.terminal_node_market_scenario_identity -eq
                    [string]$smoke.materialized_path_identity -and
                [string]$smoke.terminal_campaign_node_lifecycle -eq
                    "completed"
            )
            $expectedSetupLedger = [ordered]@{}
            if ($installedRecipeFamilyValid) {
                $draftValidationApprovalBindings = @(
                    for ($index = 0; $index -lt 14; $index++) {
                        "$($installedRecipeDraftIdentities[$index])|" +
                            "$($installedRecipeValidationIdentities[$index])|" +
                            "$($installedApprovedRecipeIdentities[$index])"
                    }
                ) | Sort-Object
                $materializationBindings = @(
                    for ($index = 0; $index -lt 14; $index++) {
                        "$($installedApprovedRecipeIdentities[$index])|" +
                            "$($installedMaterializationTaskHandleIdentities[$index])|" +
                            "$($installedMaterializedPathIdentities[$index])"
                    }
                ) | Sort-Object
                $campaignCaseBindings = @(
                    for ($index = 0; $index -lt 14; $index++) {
                        "$($installedApprovedRecipeIdentities[$index])|" +
                            "$($installedMaterializedPathIdentities[$index])|" +
                            "$($installedMaterializedScenarioIdentities[$index])"
                    }
                ) | Sort-Object
                $expectedSetupLedger = [ordered]@{
                    recipe_drafts = @(
                        $installedRecipeDraftIdentities | Sort-Object
                    )
                    recipe_validations = @(
                        $installedRecipeValidationIdentities | Sort-Object
                    )
                    approved_recipes = @(
                        $installedApprovedRecipeIdentities | Sort-Object
                    )
                    materialization_task_handles = @(
                        $installedMaterializationTaskHandleIdentities |
                            Sort-Object
                    )
                    materialized_paths = @(
                        $installedMaterializedPathIdentities | Sort-Object
                    )
                    materialized_scenarios = @(
                        $installedMaterializedScenarioIdentities | Sort-Object
                    )
                    draft_validation_approval_bindings = (
                        $draftValidationApprovalBindings
                    )
                    materialization_bindings = $materializationBindings
                    campaign_case_bindings = $campaignCaseBindings
                    formal_scenario_sets = @(
                        [string]$smoke.formal_scenario_set_identity
                    )
                    scenario_selection_contexts = @(
                        [string]$smoke.scenario_selection_context_identity
                    )
                    scenario_selection_set_bindings = @(
                        "$([string]$smoke.scenario_selection_context_identity)|" +
                            "$([string]$smoke.formal_scenario_set_identity)"
                    )
                    strategy_selection_contexts = @(
                        [string]$smoke.strategy_selection_context_identity
                    )
                    setup_selection_contexts = @(
                        [string]$smoke.setup_selection_context_identity
                    )
                    task_scenario_selection_contexts = @(
                        [string]$smoke.scenario_selection_context_identity
                    )
                }
            }
            $actualSetupLedger = $smoke.reopened_installed_setup_ledger
            $installedSetupLedgerReopenedValid = (
                $smoke.installed_setup_ledger_reopened -is [bool] -and
                $smoke.installed_setup_ledger_reopened -eq $true -and
                $null -ne $actualSetupLedger -and
                $expectedSetupLedger.Count -eq 15
            )
            if ($installedSetupLedgerReopenedValid) {
                $actualLedgerKeys = @(
                    $actualSetupLedger.PSObject.Properties.Name |
                        Sort-Object
                )
                $expectedLedgerKeys = @(
                    $expectedSetupLedger.Keys | Sort-Object
                )
                $installedSetupLedgerReopenedValid = (Test-ExactStringArray -Actual $actualLedgerKeys -Expected $expectedLedgerKeys)
            }
            if ($installedSetupLedgerReopenedValid) {
                foreach ($ledgerKey in $expectedSetupLedger.Keys) {
                    $actualLedgerProperty = (
                        $actualSetupLedger.PSObject.Properties[$ledgerKey]
                    )
                    if (
                        $null -eq $actualLedgerProperty -or
                        -not (Test-ExactStringArray -Actual $actualLedgerProperty.Value -Expected $expectedSetupLedger[$ledgerKey])
                    ) {
                        $installedSetupLedgerReopenedValid = $false
                        break
                    }
                }
            }
            $taskHandleIdentities = @($smoke.task_handle_identities)
            $taskHandleIdentitiesValid = (
                $taskHandleIdentities.Count -ge 3 -and
                @(
                    $taskHandleIdentities |
                        Where-Object {
                            [string]::IsNullOrWhiteSpace([string]$_)
                        }
                ).Count -eq 0 -and
                @($taskHandleIdentities | Sort-Object -Unique).Count -eq
                    $taskHandleIdentities.Count
            )
            $installedWave3JourneyValid = (
                [string]$smoke.fixture_kind -eq
                    "authoritative_writable_wave3_inputs" -and
                $smoke.strategy_selection_created_after_install -is [bool] -and
                $smoke.strategy_selection_created_after_install -eq $true -and
                $smoke.recipe_draft_created_after_install -is [bool] -and
                $smoke.recipe_draft_created_after_install -eq $true -and
                $smoke.recipe_validation_created_after_install -is [bool] -and
                $smoke.recipe_validation_created_after_install -eq $true -and
                $smoke.recipe_approval_created_after_install -is [bool] -and
                $smoke.recipe_approval_created_after_install -eq $true -and
                $smoke.reference_path_materialized_after_install -is [bool] -and
                $smoke.reference_path_materialized_after_install -eq $true -and
                $smoke.scenario_set_created_after_install -is [bool] -and
                $smoke.scenario_set_created_after_install -eq $true -and
                $smoke.scenario_selection_created_after_install -is [bool] -and
                $smoke.scenario_selection_created_after_install -eq $true -and
                ($installedSetupCommandKinds -join "|") -eq
                    ($expectedSetupCommandKinds -join "|") -and
                $installedRecipeFamilyValid -and
                $installedRecipeBindingValid -and
                $terminalCaseBindingValid -and
                $installedSetupLedgerReopenedValid -and
                @(
                    @(
                        [string]$smoke.strategy_selection_context_identity,
                        [string]$smoke.recipe_draft_identity,
                        [string]$smoke.recipe_validation_identity,
                        [string]$smoke.approved_recipe_identity,
                        [string]$smoke.materialization_task_handle_identity,
                        [string]$smoke.materialized_path_identity,
                        [string]$smoke.materialized_scenario_identity,
                        [string]$smoke.formal_scenario_set_identity,
                        [string]$smoke.scenario_selection_context_identity,
                        [string]$smoke.setup_selection_context_identity
                    ) |
                        Where-Object {
                            [string]::IsNullOrWhiteSpace([string]$_)
                        }
                ).Count -eq 0 -and
                $smoke.task_created_after_install -is [bool] -and
                $smoke.task_created_after_install -eq $true -and
                $smoke.campaign_created_after_install -is [bool] -and
                $smoke.campaign_created_after_install -eq $true -and
                -not [string]::IsNullOrWhiteSpace(
                    [string]$smoke.diagnostic_task_identity
                ) -and
                ($acceptedCommandKinds -join "|") -eq
                    ($expectedAcceptedCommandKinds -join "|") -and
                $taskHandleIdentitiesValid -and
                $smoke.writable_persistence_verified -is [bool] -and
                $smoke.writable_persistence_verified -eq $true -and
                $smoke.application_reopened -is [bool] -and
                $smoke.application_reopened -eq $true -and
                $smoke.background_continuation_verified -is [bool] -and
                $smoke.background_continuation_verified -eq $true -and
                $smoke.task_cancel_order_isolation_verified -is [bool] -and
                $smoke.task_cancel_order_isolation_verified -eq $true
            )
            $artifactHashes = @($smoke.artifact_hashes)
            $artifactHashesValid = (
                $artifactHashes.Count -gt 0 -and
                @(
                    $artifactHashes |
                        Where-Object {
                            [string]$_ -notmatch "^sha256:[0-9a-f]{64}$"
                        }
                ).Count -eq 0
            )
            $activeFeatureInterfaces = @(
                $smoke.active_feature_interfaces
            )
            $identityValues = @(
                [string]$smoke.campaign_identity,
                [string]$smoke.case_identity,
                [string]$smoke.run_identity,
                [string]$smoke.strategy_identity,
                [string]$smoke.approved_recipe_identity,
                [string]$smoke.evidence_package_identity,
                [string]$smoke.reproduction_manifest_identity
            )
            $persistenceReopened = (
                $smoke.persistence_reopened -is [bool] -and
                $smoke.persistence_reopened -eq $true
            )
            $readOnlyContextVisible = (
                $smoke.read_only_context_visible -is [bool] -and
                $smoke.read_only_context_visible -eq $true
            )
            $cleanExit = (
                $smoke.clean_exit -is [bool] -and
                $smoke.clean_exit -eq $true
            )
            $expectedIdentityGraph = @($smoke.expected_identity_graph)
            $featureIdentityGraph = @($smoke.feature_identity_graph)
            $persistedManifestIdentities = @(
                $smoke.persisted_manifest_identities
            )
            $persistedRunIdentities = @(
                $smoke.persisted_run_identities
            )
            $rawArtifactHashes = @($smoke.raw_artifact_hashes)
            $installedMaterializedPathsPersisted = (
                @(
                    $installedMaterializedPathIdentities |
                        Where-Object { $_ -notin $rawArtifactHashes }
                ).Count -eq 0
            )
            $installedWave3JourneyValid = (
                $installedWave3JourneyValid -and
                $installedMaterializedPathsPersisted
            )
            $persistedIdentitySetsValid = (
                $persistedManifestIdentities.Count -gt 0 -and
                $persistedRunIdentities.Count -gt 0 -and
                $rawArtifactHashes.Count -gt 0 -and
                @(
                    @(
                        $persistedManifestIdentities +
                            $persistedRunIdentities
                    ) |
                        Where-Object {
                            [string]::IsNullOrWhiteSpace([string]$_)
                        }
                ).Count -eq 0 -and
                @(
                    $rawArtifactHashes |
                        Where-Object {
                            [string]$_ -notmatch "^[0-9a-f]{64}$"
                        }
                ).Count -eq 0
            )
            $featureIdentityGraphMatches = (
                $expectedIdentityGraph.Count -gt 0 -and
                ($featureIdentityGraph -join "|") -eq
                    ($expectedIdentityGraph -join "|")
            )
            $identitySetNames = @(
                "candidates",
                "metrics",
                "comparisons",
                "curves",
                "breakpoints",
                "findings"
            )
            $identitySetsValid = $true
            $flattenedIdentityGraph = @(
                $identityValues +
                    @([string]$smoke.diagnostic_task_identity) +
                    $taskHandleIdentities +
                    $persistedManifestIdentities +
                    $persistedRunIdentities +
                    $rawArtifactHashes
            )
            foreach ($identitySetName in $identitySetNames) {
                $identityProperty = (
                    $smoke.evidence_identity_sets.PSObject.Properties |
                        Where-Object { $_.Name -eq $identitySetName }
                )
                if (-not $identityProperty) {
                    $identitySetsValid = $false
                    continue
                }
                $identitySetValues = @($identityProperty.Value)
                if (
                    $identitySetName -ne "breakpoints" -and
                    $identitySetValues.Count -eq 0
                ) {
                    $identitySetsValid = $false
                }
                $flattenedIdentityGraph += $identitySetValues
            }
            $flattenedIdentityGraph = @(
                $flattenedIdentityGraph | Sort-Object -Unique
            )
            $expectedSortedIdentityGraph = @(
                $expectedIdentityGraph | Sort-Object -Unique
            )
            $identitySetsValid = (
                $identitySetsValid -and
                $persistedIdentitySetsValid -and
                ($flattenedIdentityGraph -join "|") -eq
                    ($expectedSortedIdentityGraph -join "|")
            )
            $identityCheckpoints = (
                $smoke.qml_identity_graph_checkpoints.PSObject.Properties
            )
            $identityCheckpointsValid = (
                @($identityCheckpoints).Count -eq
                    $expectedJourneySignatures.Count
            )
            foreach ($checkpoint in $identityCheckpoints) {
                if (
                    (@($checkpoint.Value) -join "|") -ne
                    ($expectedIdentityGraph -join "|")
                ) {
                    $identityCheckpointsValid = $false
                }
            }
            $announcementText = (
                @($smoke.accessibility_announcements) -join " "
            ).ToLowerInvariant()
            $releaseBehaviorValid = (
                $smoke.keyboard_navigation_verified -is [bool] -and
                $smoke.keyboard_navigation_verified -eq $true -and
                $smoke.accessibility_preferences_verified -is [bool] -and
                $smoke.accessibility_preferences_verified -eq $true -and
                $smoke.old_generation_rejected -is [bool] -and
                $smoke.old_generation_rejected -eq $true -and
                $smoke.authoritative_reconnect_verified -is [bool] -and
                $smoke.authoritative_reconnect_verified -eq $true -and
                $announcementText.Contains("disconnected") -and
                $announcementText.Contains("fresh")
            )
            $realV1IdentityValid = (
                @(
                    $identityValues |
                        Where-Object { [string]::IsNullOrWhiteSpace($_) }
                ).Count -eq 0 -and
                $artifactHashesValid -and
                [string]$smoke.persistence_kind -eq
                    "sqlite+json+parquet" -and
                $persistenceReopened -and
                [string]$smoke.application_read_model_interface -eq
                    "StrategyDiagnosticsV1ApplicationReadModel/1.0" -and
                ($activeFeatureInterfaces -join "|") -eq
                    "StrategyLibraryFeature/1.0|ScenarioLabFeature/1.0|DiagnosticTasksFeature/1.0|RunMonitoringFeature/1.2|EvidenceAndFindingsFeature/1.1|SystemHealthFeature/1.0" -and
                [string]$smoke.campaign_status -eq "completed" -and
                [string]$smoke.run_status -eq "completed" -and
                [string]$smoke.evidence_status -eq "sealed" -and
                $featureIdentityGraphMatches -and
                $identitySetsValid -and
                $identityCheckpointsValid -and
                $releaseBehaviorValid -and
                $installedWave3JourneyValid
            )
            $rendererLanes[$lane] = [ordered]@{
                exit_code = $exitCode
                graphics_api = $smoke.graphics_api
                source_commit_matches = (
                    [string]$smoke.source_commit -eq $SourceCommit
                )
                source_commit = [string]$smoke.source_commit
                production_path = $productionPath
                production_path_matches = $productionPathMatches
                fixture_kind = [string]$smoke.fixture_kind
                strategy_selection_created_after_install = (
                    $smoke.strategy_selection_created_after_install -is [bool] -and
                    $smoke.strategy_selection_created_after_install -eq $true
                )
                recipe_draft_created_after_install = (
                    $smoke.recipe_draft_created_after_install -is [bool] -and
                    $smoke.recipe_draft_created_after_install -eq $true
                )
                recipe_validation_created_after_install = (
                    $smoke.recipe_validation_created_after_install -is [bool] -and
                    $smoke.recipe_validation_created_after_install -eq $true
                )
                recipe_approval_created_after_install = (
                    $smoke.recipe_approval_created_after_install -is [bool] -and
                    $smoke.recipe_approval_created_after_install -eq $true
                )
                reference_path_materialized_after_install = (
                    $smoke.reference_path_materialized_after_install -is [bool] -and
                    $smoke.reference_path_materialized_after_install -eq $true
                )
                scenario_set_created_after_install = (
                    $smoke.scenario_set_created_after_install -is [bool] -and
                    $smoke.scenario_set_created_after_install -eq $true
                )
                scenario_selection_created_after_install = (
                    $smoke.scenario_selection_created_after_install -is [bool] -and
                    $smoke.scenario_selection_created_after_install -eq $true
                )
                strategy_selection_context_identity = (
                    [string]$smoke.strategy_selection_context_identity
                )
                recipe_draft_identity = [string]$smoke.recipe_draft_identity
                recipe_validation_identity = (
                    [string]$smoke.recipe_validation_identity
                )
                materialization_task_handle_identity = (
                    [string]$smoke.materialization_task_handle_identity
                )
                materialized_path_identity = (
                    [string]$smoke.materialized_path_identity
                )
                materialized_scenario_identity = (
                    [string]$smoke.materialized_scenario_identity
                )
                terminal_campaign_case_identity = (
                    [string]$smoke.terminal_campaign_case_identity
                )
                terminal_selected_campaign_case_identity = (
                    [string]$smoke.terminal_selected_campaign_case_identity
                )
                terminal_node_market_scenario_identity = (
                    [string]$smoke.terminal_node_market_scenario_identity
                )
                terminal_campaign_node_lifecycle = (
                    [string]$smoke.terminal_campaign_node_lifecycle
                )
                terminal_case_manifest_binding_verified = (
                    $terminalCaseBindingValid
                )
                installed_setup_ledger_reopened = (
                    $installedSetupLedgerReopenedValid
                )
                reopened_installed_setup_ledger = $actualSetupLedger
                formal_scenario_set_identity = (
                    [string]$smoke.formal_scenario_set_identity
                )
                scenario_selection_context_identity = (
                    [string]$smoke.scenario_selection_context_identity
                )
                setup_selection_context_identity = (
                    [string]$smoke.setup_selection_context_identity
                )
                installed_setup_command_kinds = $installedSetupCommandKinds
                installed_recipe_draft_identities = (
                    $installedRecipeDraftIdentities
                )
                installed_recipe_validation_identities = (
                    $installedRecipeValidationIdentities
                )
                installed_approved_recipe_identities = (
                    $installedApprovedRecipeIdentities
                )
                installed_materialization_task_handle_identities = (
                    $installedMaterializationTaskHandleIdentities
                )
                installed_materialized_path_identities = (
                    $installedMaterializedPathIdentities
                )
                installed_materialized_scenario_identities = (
                    $installedMaterializedScenarioIdentities
                )
                task_created_after_install = (
                    $smoke.task_created_after_install -is [bool] -and
                    $smoke.task_created_after_install -eq $true
                )
                campaign_created_after_install = (
                    $smoke.campaign_created_after_install -is [bool] -and
                    $smoke.campaign_created_after_install -eq $true
                )
                diagnostic_task_identity = (
                    [string]$smoke.diagnostic_task_identity
                )
                accepted_command_kinds = $acceptedCommandKinds
                task_handle_identities = $taskHandleIdentities
                writable_persistence_verified = (
                    $smoke.writable_persistence_verified -is [bool] -and
                    $smoke.writable_persistence_verified -eq $true
                )
                application_reopened = (
                    $smoke.application_reopened -is [bool] -and
                    $smoke.application_reopened -eq $true
                )
                background_continuation_verified = (
                    $smoke.background_continuation_verified -is [bool] -and
                    $smoke.background_continuation_verified -eq $true
                )
                task_cancel_order_isolation_verified = (
                    $smoke.task_cancel_order_isolation_verified -is [bool] -and
                    $smoke.task_cancel_order_isolation_verified -eq $true
                )
                installed_wave3_journey_valid = (
                    $installedWave3JourneyValid
                )
                campaign_identity = [string]$smoke.campaign_identity
                case_identity = [string]$smoke.case_identity
                run_identity = [string]$smoke.run_identity
                strategy_identity = [string]$smoke.strategy_identity
                approved_recipe_identity = (
                    [string]$smoke.approved_recipe_identity
                )
                evidence_package_identity = (
                    [string]$smoke.evidence_package_identity
                )
                reproduction_manifest_identity = (
                    [string]$smoke.reproduction_manifest_identity
                )
                artifact_hashes = $artifactHashes
                persistence_kind = [string]$smoke.persistence_kind
                persistence_reopened = (
                    $persistenceReopened
                )
                application_read_model_interface = (
                    [string]$smoke.application_read_model_interface
                )
                active_feature_interfaces = $activeFeatureInterfaces
                campaign_status = [string]$smoke.campaign_status
                run_status = [string]$smoke.run_status
                evidence_status = [string]$smoke.evidence_status
                expected_identity_graph = $expectedIdentityGraph
                feature_identity_graph = $featureIdentityGraph
                qml_identity_graph_checkpoints = (
                    $smoke.qml_identity_graph_checkpoints
                )
                evidence_identity_sets = $smoke.evidence_identity_sets
                persisted_manifest_identities = (
                    $persistedManifestIdentities
                )
                persisted_run_identities = $persistedRunIdentities
                raw_artifact_hashes = $rawArtifactHashes
                keyboard_navigation_verified = (
                    $smoke.keyboard_navigation_verified -is [bool] -and
                    $smoke.keyboard_navigation_verified -eq $true
                )
                accessibility_preferences_verified = (
                    $smoke.accessibility_preferences_verified -is [bool] -and
                    $smoke.accessibility_preferences_verified -eq $true
                )
                accessibility_announcements = @(
                    $smoke.accessibility_announcements
                )
                old_generation_rejected = (
                    $smoke.old_generation_rejected -is [bool] -and
                    $smoke.old_generation_rejected -eq $true
                )
                authoritative_reconnect_verified = (
                    $smoke.authoritative_reconnect_verified -is [bool] -and
                    $smoke.authoritative_reconnect_verified -eq $true
                )
                real_v1_identity_valid = $realV1IdentityValid
                routes_rendered = $routesRendered
                routes_match = $routesMatch
                connection_transitions = $connectionTransitions
                connection_transitions_match = (
                    $connectionTransitionsMatch
                )
                observations = @(
                    $observations |
                        ForEach-Object {
                            [ordered]@{
                                stage = [string]$_.stage
                                route = [string]$_.route
                                run_state = [string]$_.run_state
                                evidence_state = [string]$_.evidence_state
                                run_freshness = [string]$_.run_freshness
                                evidence_freshness = (
                                    [string]$_.evidence_freshness
                                )
                                run_phase = [string]$_.run_phase
                                evidence_phase = [string]$_.evidence_phase
                                run_revision = [string]$_.run_revision
                                evidence_revision = (
                                    [string]$_.evidence_revision
                                )
                                source_generation = (
                                    [string]$_.source_generation
                                )
                            }
                        }
                )
                states_match = $statesMatch
                screenshots = $screenshotEvidence
                screenshots_distinct = $screenshotsDistinct
                manual_trading_action_count = (
                    [int]$smoke.manual_trading_action_count
                )
                read_only_context_visible = (
                    $readOnlyContextVisible
                )
                clean_exit = $cleanExit
                errors = @(
                    ConvertTo-ReleaseErrorList -Errors $smoke.errors
                )
            }
        }
        else {
            $rendererLanes[$lane] = [ordered]@{
                exit_code = $exitCode
                graphics_api = "unavailable"
                source_commit_matches = $false
                source_commit = ""
                production_path = @()
                production_path_matches = $false
                fixture_kind = ""
                strategy_selection_created_after_install = $false
                recipe_draft_created_after_install = $false
                recipe_validation_created_after_install = $false
                recipe_approval_created_after_install = $false
                reference_path_materialized_after_install = $false
                scenario_set_created_after_install = $false
                scenario_selection_created_after_install = $false
                strategy_selection_context_identity = ""
                recipe_draft_identity = ""
                recipe_validation_identity = ""
                materialization_task_handle_identity = ""
                materialized_path_identity = ""
                materialized_scenario_identity = ""
                terminal_campaign_case_identity = ""
                terminal_selected_campaign_case_identity = ""
                terminal_node_market_scenario_identity = ""
                terminal_campaign_node_lifecycle = ""
                terminal_case_manifest_binding_verified = $false
                installed_setup_ledger_reopened = $false
                reopened_installed_setup_ledger = [ordered]@{}
                formal_scenario_set_identity = ""
                scenario_selection_context_identity = ""
                setup_selection_context_identity = ""
                installed_setup_command_kinds = @()
                installed_recipe_draft_identities = @()
                installed_recipe_validation_identities = @()
                installed_approved_recipe_identities = @()
                installed_materialization_task_handle_identities = @()
                installed_materialized_path_identities = @()
                installed_materialized_scenario_identities = @()
                task_created_after_install = $false
                campaign_created_after_install = $false
                diagnostic_task_identity = ""
                accepted_command_kinds = @()
                task_handle_identities = @()
                writable_persistence_verified = $false
                application_reopened = $false
                background_continuation_verified = $false
                task_cancel_order_isolation_verified = $false
                installed_wave3_journey_valid = $false
                campaign_identity = ""
                case_identity = ""
                run_identity = ""
                strategy_identity = ""
                approved_recipe_identity = ""
                evidence_package_identity = ""
                reproduction_manifest_identity = ""
                artifact_hashes = @()
                persistence_kind = ""
                persistence_reopened = $false
                application_read_model_interface = ""
                active_feature_interfaces = @()
                campaign_status = ""
                run_status = ""
                evidence_status = ""
                expected_identity_graph = @()
                feature_identity_graph = @()
                qml_identity_graph_checkpoints = [ordered]@{}
                evidence_identity_sets = [ordered]@{}
                persisted_manifest_identities = @()
                persisted_run_identities = @()
                raw_artifact_hashes = @()
                keyboard_navigation_verified = $false
                accessibility_preferences_verified = $false
                accessibility_announcements = @()
                old_generation_rejected = $false
                authoritative_reconnect_verified = $false
                real_v1_identity_valid = $false
                routes_rendered = @()
                routes_match = $false
                connection_transitions = @()
                connection_transitions_match = $false
                observations = @()
                states_match = $false
                screenshots = @()
                screenshots_distinct = $false
                manual_trading_action_count = -1
                read_only_context_visible = $false
                clean_exit = $false
                errors = @("smoke-report.json was not produced")
            }
        }
    }
}

$candidateWidgetsCandidateRollback = [ordered]@{
    source_commit = $SourceCommit
    passed = $false
    same_source_commit = $false
    same_dependency_lock = $false
    identity_retention_verified = $false
    reopen_verified = $false
    destructive_migration = $true
    errors = @("Installed candidate-to-Widgets rollback drill was not run")
}
$hardwareSmokePath = Join-Path $resolvedEvidence "hardware\smoke-report.json"
if (
    $installSucceeded -and
    $widgetsInstallSucceeded -and
    (Test-Path -LiteralPath $hardwareSmokePath -PathType Leaf)
) {
    $hardwareSmoke = Get-Content `
        -LiteralPath $hardwareSmokePath `
        -Raw `
        -Encoding utf8 | ConvertFrom-Json
    $sourcePersistence = Join-Path $resolvedEvidence "hardware\v1-persistence"
    $rollbackRoot = Join-Path $resolvedEvidence "installed-rollback"
    $supportedCopy = Join-Path $rollbackRoot "supported-data-copy"
    New-Item -ItemType Directory -Path $rollbackRoot | Out-Null
    if (Test-Path -LiteralPath $sourcePersistence -PathType Container) {
        Copy-Item `
            -LiteralPath $sourcePersistence `
            -Destination $supportedCopy `
            -Recurse
    }
    $candidateBeforePath = Join-Path $rollbackRoot "candidate-before.json"
    if (Test-Path -LiteralPath $supportedCopy -PathType Container) {
        & $executable.FullName `
            "--recovery-report=$candidateBeforePath" `
            "--supported-data-copy=$supportedCopy" `
            "--campaign-id=$([string]$hardwareSmoke.campaign_identity)" `
            "--evidence-package-id=$([string]$hardwareSmoke.evidence_package_identity)" `
            "--selected-manifest-id=$([string]$hardwareSmoke.reproduction_manifest_identity)" `
            "--diagnostic-task-id=$([string]$hardwareSmoke.diagnostic_task_identity)" `
            "--source-commit=$SourceCommit"
        $candidateBeforeExitCode = $LASTEXITCODE
    }
    else {
        $candidateBeforeExitCode = -1
    }
    $rollbackWidgetsDir = Join-Path $rollbackRoot "widgets"
    New-Item -ItemType Directory -Path $rollbackWidgetsDir | Out-Null
    if (Test-Path -LiteralPath $supportedCopy -PathType Container) {
        & $widgetsExecutable.FullName `
            "--source-commit=$SourceCommit" `
            "--smoke-report-dir=$rollbackWidgetsDir" `
            "--supported-data-copy=$supportedCopy" `
            "--campaign-id=$([string]$hardwareSmoke.campaign_identity)" `
            "--evidence-package-id=$([string]$hardwareSmoke.evidence_package_identity)" `
            "--selected-manifest-id=$([string]$hardwareSmoke.reproduction_manifest_identity)" `
            "--diagnostic-task-id=$([string]$hardwareSmoke.diagnostic_task_identity)"
        $rollbackWidgetsExitCode = $LASTEXITCODE
    }
    else {
        $rollbackWidgetsExitCode = -1
    }
    $candidateAfterPath = Join-Path $rollbackRoot "candidate-after.json"
    if (Test-Path -LiteralPath $supportedCopy -PathType Container) {
        & $executable.FullName `
            "--recovery-report=$candidateAfterPath" `
            "--supported-data-copy=$supportedCopy" `
            "--campaign-id=$([string]$hardwareSmoke.campaign_identity)" `
            "--evidence-package-id=$([string]$hardwareSmoke.evidence_package_identity)" `
            "--selected-manifest-id=$([string]$hardwareSmoke.reproduction_manifest_identity)" `
            "--diagnostic-task-id=$([string]$hardwareSmoke.diagnostic_task_identity)" `
            "--source-commit=$SourceCommit"
        $candidateAfterExitCode = $LASTEXITCODE
    }
    else {
        $candidateAfterExitCode = -1
    }

    $rollbackWidgetsReportPath = Join-Path `
        $rollbackWidgetsDir `
        "smoke-report.json"
    if (
        (Test-Path -LiteralPath $candidateBeforePath -PathType Leaf) -and
        (Test-Path -LiteralPath $rollbackWidgetsReportPath -PathType Leaf) -and
        (Test-Path -LiteralPath $candidateAfterPath -PathType Leaf)
    ) {
        $candidateBefore = Get-Content `
            -LiteralPath $candidateBeforePath `
            -Raw `
            -Encoding utf8 | ConvertFrom-Json
        $rollbackWidgetsReport = Get-Content `
            -LiteralPath $rollbackWidgetsReportPath `
            -Raw `
            -Encoding utf8 | ConvertFrom-Json
        $candidateAfter = Get-Content `
            -LiteralPath $candidateAfterPath `
            -Raw `
            -Encoding utf8 | ConvertFrom-Json
        $expectedDurableIdentities = [pscustomobject][ordered]@{
            Strategy = @([string]$hardwareSmoke.strategy_identity)
            Recipe = @([string]$hardwareSmoke.approved_recipe_identity)
            Task = @([string]$hardwareSmoke.diagnostic_task_identity)
            Campaign = @([string]$hardwareSmoke.campaign_identity)
            Run = @([string]$hardwareSmoke.run_identity)
            Evidence = @([string]$hardwareSmoke.evidence_package_identity)
            Finding = @($hardwareSmoke.evidence_identity_sets.findings)
            Manifest = @(
                [string]$hardwareSmoke.reproduction_manifest_identity
            )
        }
        $identityRetentionVerified = (
            (Test-DurableIdentityMap `
                -Actual $candidateBefore.durable_identities `
                -Expected $expectedDurableIdentities) -and
            (Test-DurableIdentityMap `
                -Actual $rollbackWidgetsReport.durable_identities `
                -Expected $expectedDurableIdentities) -and
            (Test-DurableIdentityMap `
                -Actual $candidateAfter.durable_identities `
                -Expected $expectedDurableIdentities)
        )
        $taskHandleContinuity = (
            (Test-ExactStringArray `
                -Actual $candidateBefore.task_handle_identities `
                -Expected $hardwareSmoke.task_handle_identities) -and
            (Test-ExactStringArray `
                -Actual $rollbackWidgetsReport.task_handle_identities `
                -Expected $hardwareSmoke.task_handle_identities) -and
            (Test-ExactStringArray `
                -Actual $candidateAfter.task_handle_identities `
                -Expected $hardwareSmoke.task_handle_identities)
        )
        $orderStateContinuity = (
            [string]$candidateBefore.order_state_sha256 -eq
                [string]$rollbackWidgetsReport.order_state_sha256 -and
            [string]$candidateBefore.order_state_sha256 -eq
                [string]$candidateAfter.order_state_sha256 -and
            [int]$candidateBefore.order_count -eq
                [int]$rollbackWidgetsReport.order_count -and
            [int]$candidateBefore.order_count -eq
                [int]$candidateAfter.order_count
        )
        $sameSourceCommit = (
            [string]$candidateBefore.source_commit -eq $SourceCommit -and
            [string]$rollbackWidgetsReport.source_commit -eq $SourceCommit -and
            [string]$candidateAfter.source_commit -eq $SourceCommit
        )
        $sameDependencyLock = (
            -not [string]::IsNullOrWhiteSpace(
                $candidateDependencyLockSha256
            ) -and
            $candidateDependencyLockSha256 -eq
                $widgetsDependencyLockSha256
        )
        $reopenVerified = (
            $candidateBeforeExitCode -eq 0 -and
            $rollbackWidgetsExitCode -eq 0 -and
            $candidateAfterExitCode -eq 0 -and
            $candidateBefore.clean_exit -is [bool] -and
            $candidateBefore.clean_exit -eq $true -and
            $rollbackWidgetsReport.clean_exit -is [bool] -and
            $rollbackWidgetsReport.clean_exit -eq $true -and
            $rollbackWidgetsReport.supported_data_copy_verified -is [bool] -and
            $rollbackWidgetsReport.supported_data_copy_verified -eq $true -and
            $candidateAfter.clean_exit -is [bool] -and
            $candidateAfter.clean_exit -eq $true
        )
        $rollbackPassed = (
            $sameSourceCommit -and
            $sameDependencyLock -and
            $identityRetentionVerified -and
            $taskHandleContinuity -and
            $orderStateContinuity -and
            $reopenVerified
        )
        $candidateWidgetsCandidateRollback = [ordered]@{
            source_commit = $SourceCommit
            passed = $rollbackPassed
            same_source_commit = $sameSourceCommit
            same_dependency_lock = $sameDependencyLock
            candidate_dependency_lock_sha256 = (
                $candidateDependencyLockSha256
            )
            widgets_dependency_lock_sha256 = (
                $widgetsDependencyLockSha256
            )
            identity_retention_verified = $identityRetentionVerified
            task_handle_continuity_verified = $taskHandleContinuity
            order_state_continuity_verified = $orderStateContinuity
            reopen_verified = $reopenVerified
            destructive_migration = $false
            candidate_before = $candidateBefore
            retained_widgets = $rollbackWidgetsReport
            candidate_after = $candidateAfter
            errors = @(
                if (-not $rollbackPassed) {
                    "Installed candidate-to-Widgets rollback drill failed"
                }
            )
        }
        $widgetsRollback = [ordered]@{
            exit_code = $rollbackWidgetsExitCode
            source_commit = [string]$rollbackWidgetsReport.source_commit
            source_commit_matches = (
                [string]$rollbackWidgetsReport.source_commit -eq $SourceCommit
            )
            mode = [string]$rollbackWidgetsReport.mode
            placeholder_panels = @(
                $rollbackWidgetsReport.placeholder_panels
            )
            real_panel_count = [int]$rollbackWidgetsReport.real_panel_count
            manual_trading_action_count = (
                [int]$rollbackWidgetsReport.manual_trading_action_count
            )
            opened_panels = @($rollbackWidgetsReport.opened_panels)
            supported_data_copy_verified = (
                $rollbackWidgetsReport.supported_data_copy_verified -is [bool] -and
                $rollbackWidgetsReport.supported_data_copy_verified -eq $true
            )
            clean_exit = (
                $rollbackWidgetsReport.clean_exit -is [bool] -and
                $rollbackWidgetsReport.clean_exit -eq $true
            )
            errors = @()
        }
    }
}

$hardwareRollbackLane = $candidateWidgetsCandidateRollback
$softwareRollbackLane = [ordered]@{
    lane = "software"
    source_commit = $SourceCommit
    passed = $false
    same_source_commit = $false
    same_dependency_lock = $false
    identity_retention_verified = $false
    reopen_verified = $false
    destructive_migration = $true
    errors = @("Software rollback lane was not run")
}
if ($installSucceeded -and $widgetsInstallSucceeded) {
    $softwareRollbackLane = Invoke-InstalledRollbackLane `
        -Lane "software" `
        -EvidenceRoot $resolvedEvidence `
        -CandidateExecutable $executable.FullName `
        -WidgetsExecutable $widgetsExecutable.FullName `
        -SourceCommit $SourceCommit `
        -CandidateDependencyLockSha256 $candidateDependencyLockSha256 `
        -WidgetsDependencyLockSha256 $widgetsDependencyLockSha256
}
$rollbackBothLanesPassed = (
    $hardwareRollbackLane.passed -and
    $softwareRollbackLane.passed
)
$candidateWidgetsCandidateRollback = [ordered]@{
    source_commit = $SourceCommit
    passed = $rollbackBothLanesPassed
    same_source_commit = (
        $hardwareRollbackLane.same_source_commit -and
        $softwareRollbackLane.same_source_commit
    )
    same_dependency_lock = (
        $hardwareRollbackLane.same_dependency_lock -and
        $softwareRollbackLane.same_dependency_lock
    )
    identity_retention_verified = (
        $hardwareRollbackLane.identity_retention_verified -and
        $softwareRollbackLane.identity_retention_verified
    )
    reopen_verified = (
        $hardwareRollbackLane.reopen_verified -and
        $softwareRollbackLane.reopen_verified
    )
    destructive_migration = (
        $hardwareRollbackLane.destructive_migration -or
        $softwareRollbackLane.destructive_migration
    )
    renderer_lanes = [ordered]@{
        hardware = $hardwareRollbackLane
        software = $softwareRollbackLane
    }
    errors = @(
        if (-not $hardwareRollbackLane.passed) {
            "Hardware rollback lane failed"
        }
        if (-not $softwareRollbackLane.passed) {
            "Software rollback lane failed"
        }
    )
}

$report = [ordered]@{
    schema_version = 4
    source_commit = $SourceCommit
    archive_sha256 = "sha256:$archiveHash"
    widgets_archive_sha256 = "sha256:$widgetsArchiveHash"
    operating_system = $operatingSystem
    architecture = $architecture
    user_name = $userName
    is_windows_sandbox = $isWindowsSandbox
    network_enumeration_succeeded = $networkEnumerationSucceeded
    network_adapters_up = $networkAdaptersUp
    python_on_path = [bool]$pythonCommands
    python_installations = $pythonInstallations
    compiler_on_path = [bool]$compilerCommands
    compiler_installations = $compilerInstallations
    dependency_cache_present = $dependencyCachePresent
    dependency_cache_paths = $dependencyCachePaths
    install_succeeded = $installSucceeded
    widgets_install_succeeded = $widgetsInstallSucceeded
    widgets_rollback = $widgetsRollback
    installed_performance = $installedPerformance
    fresh_install_migration = $freshInstallMigration
    copied_wave3_migration = $copiedWave3Migration
    candidate_widgets_candidate_rollback = (
        $candidateWidgetsCandidateRollback
    )
    observation_ledger_readiness = $observationLedgerReadiness
    renderer_lanes = $rendererLanes
}
$reportPath = Join-Path $resolvedEvidence "clean-room-report.json"
$reportJson = $report | ConvertTo-Json -Depth 12
[IO.File]::WriteAllText(
    $reportPath,
    $reportJson,
    [Text.UTF8Encoding]::new($false)
)

$gatePassed = (
    $operatingSystem -match "Windows 11" -and
    $architecture -match "AMD64|x86_64" -and
    $isWindowsSandbox -and
    $networkEnumerationSucceeded -and
    $networkAdaptersUp.Count -eq 0 -and
    -not $pythonCommands -and
    $pythonInstallations.Count -eq 0 -and
    -not $compilerCommands -and
    $compilerInstallations.Count -eq 0 -and
    -not $dependencyCachePresent -and
    $dependencyCachePaths.Count -eq 0 -and
    $installSucceeded -and
    $widgetsInstallSucceeded -and
    $widgetsRollback.exit_code -eq 0 -and
    $widgetsRollback.source_commit_matches -and
    $widgetsRollback.mode -eq "read-only" -and
    $widgetsRollback.placeholder_panels.Count -eq 0 -and
    $widgetsRollback.real_panel_count -ge 3 -and
    $widgetsRollback.manual_trading_action_count -eq 0 -and
    @(
        $widgetsRollback.opened_panels |
            Where-Object { $_ -in @("diagnostics", "market", "orders") } |
            Sort-Object -Unique
    ).Count -eq 3 -and
    $widgetsRollback.clean_exit -and
    $widgetsRollback.errors.Count -eq 0 -and
    $freshInstallMigration.exit_code -eq 0 -and
    $freshInstallMigration.passed -and
    $freshInstallMigration.schema_migration_verified -and
    $freshInstallMigration.bookmark_migration_verified -and
    $freshInstallMigration.deterministic -and
    $freshInstallMigration.idempotent -and
    $freshInstallMigration.identity_retention_verified -and
    $freshInstallMigration.reopen_verified -and
    -not $freshInstallMigration.destructive_migration -and
    $copiedWave3Migration.exit_code -eq 0 -and
    $copiedWave3Migration.passed -and
    $copiedWave3Migration.schema_migration_verified -and
    $copiedWave3Migration.bookmark_migration_verified -and
    $copiedWave3Migration.deterministic -and
    $copiedWave3Migration.idempotent -and
    $copiedWave3Migration.identity_retention_verified -and
    $copiedWave3Migration.reopen_verified -and
    -not $copiedWave3Migration.destructive_migration -and
    $candidateWidgetsCandidateRollback.passed -and
    $candidateWidgetsCandidateRollback.same_source_commit -and
    $candidateWidgetsCandidateRollback.same_dependency_lock -and
    $candidateWidgetsCandidateRollback.identity_retention_verified -and
    $candidateWidgetsCandidateRollback.reopen_verified -and
    -not $candidateWidgetsCandidateRollback.destructive_migration -and
    $observationLedgerReadiness.exit_code -eq 0 -and
    $observationLedgerReadiness.passed -and
    $observationLedgerReadiness.legacy_inventory_available -and
    $observationLedgerReadiness.legacy_route_count -ge 1 -and
    $observationLedgerReadiness.observation_ledger_configuration_available -and
    -not $observationLedgerReadiness.observation_window_started -and
    -not $observationLedgerReadiness.destructive_migration -and
    $installedPerformance.hardware.installed_exit_code -eq 0 -and
    $installedPerformance.hardware.status -eq "passed" -and
    $installedPerformance.hardware.lane -eq "hardware" -and
    $installedPerformance.hardware.graphics_api -eq "Direct3D11" -and
    $installedPerformance.software.installed_exit_code -eq 0 -and
    $installedPerformance.software.status -eq "passed" -and
    $installedPerformance.software.lane -eq "software" -and
    $installedPerformance.software.graphics_api -eq "Software" -and
    $rendererLanes.hardware.exit_code -eq 0 -and
    $rendererLanes.hardware.graphics_api -eq "Direct3D11" -and
    $rendererLanes.hardware.source_commit_matches -and
    $rendererLanes.hardware.production_path_matches -and
    $rendererLanes.hardware.real_v1_identity_valid -and
    $rendererLanes.hardware.installed_wave3_journey_valid -and
    $rendererLanes.hardware.routes_match -and
    $rendererLanes.hardware.connection_transitions_match -and
    $rendererLanes.hardware.states_match -and
    $rendererLanes.hardware.screenshots_distinct -and
    $rendererLanes.hardware.manual_trading_action_count -eq 0 -and
    $rendererLanes.hardware.read_only_context_visible -and
    $rendererLanes.hardware.clean_exit -and
    $rendererLanes.hardware.errors.Count -eq 0 -and
    $rendererLanes.software.exit_code -eq 0 -and
    $rendererLanes.software.graphics_api -eq "Software" -and
    $rendererLanes.software.source_commit_matches -and
    $rendererLanes.software.production_path_matches -and
    $rendererLanes.software.real_v1_identity_valid -and
    $rendererLanes.software.installed_wave3_journey_valid -and
    $rendererLanes.software.routes_match -and
    $rendererLanes.software.connection_transitions_match -and
    $rendererLanes.software.states_match -and
    $rendererLanes.software.screenshots_distinct -and
    $rendererLanes.software.manual_trading_action_count -eq 0 -and
    $rendererLanes.software.read_only_context_visible -and
    $rendererLanes.software.clean_exit -and
    $rendererLanes.software.errors.Count -eq 0 -and
    ($rendererLanes.hardware.accepted_command_kinds -join "|") -eq
        ($rendererLanes.software.accepted_command_kinds -join "|")
)
if (-not $gatePassed) {
    exit 1
}
exit 0
