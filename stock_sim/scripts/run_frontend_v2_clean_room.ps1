param(
    [Parameter(Mandatory = $true)]
    [string]$PackageArchive,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedArchiveSha256,
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
$packageArchiveName = Split-Path -Leaf $PackageArchive
if ($packageArchiveName -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
    throw "Package archive name contains unsafe characters."
}

$resolvedEvidence = [IO.Path]::GetFullPath($EvidenceDir)
$installDir = Join-Path $resolvedEvidence "installed"
$resolvedInstall = [IO.Path]::GetFullPath($installDir)
if (-not $resolvedInstall.StartsWith(
    $resolvedEvidence + [IO.Path]::DirectorySeparatorChar,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "Refusing to install outside the evidence directory."
}
New-Item -ItemType Directory -Force -Path $resolvedEvidence | Out-Null
if (Test-Path -LiteralPath $resolvedInstall) {
    Remove-Item -LiteralPath $resolvedInstall -Recurse -Force
}

$archiveHash = (Get-FileHash -LiteralPath $PackageArchive -Algorithm SHA256).Hash.ToLowerInvariant()
$normalizedExpected = $ExpectedArchiveSha256.ToLowerInvariant().Replace("sha256:", "")
if ($archiveHash -ne $normalizedExpected) {
    throw "Package archive checksum does not match the expected SHA-256."
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
$executable = Get-ChildItem -LiteralPath $resolvedInstall -Recurse -File |
    Where-Object { $_.Name -eq "UTI-Frontend-V2.exe" } |
    Select-Object -First 1
$installSucceeded = [bool]$executable
$rendererLanes = [ordered]@{}
if ($installSucceeded) {
    $expectedJourneySignatures = @(
        "launched_active_run|run_monitoring|active|ready|fresh|fresh",
        "active_evidence|evidence_and_findings|active|ready|fresh|fresh",
        "disconnected_run|run_monitoring|active|ready|disconnected|disconnected",
        "disconnected_evidence|evidence_and_findings|active|ready|disconnected|disconnected",
        "reconnected_run|run_monitoring|active|ready|fresh|fresh",
        "reconnected_evidence|evidence_and_findings|active|ready|fresh|fresh",
        "completed_run|run_monitoring|terminal|ready|fresh|fresh",
        "completed_evidence|evidence_and_findings|terminal|ready|fresh|fresh"
    )
    $expectedProductionPath = @(
        "AppContext",
        "EventBridge",
        "LiveRunMonitoringAdapter",
        "LiveEvidenceAndFindingsAdapter",
        "JourneyWorkspaceHost"
    )
    $expectedRoutes = @("run_monitoring", "evidence_and_findings")
    $expectedTransitions = @(
        "connected",
        "disconnected",
        "reconnected",
        "completed"
    )
    $requiredVisualGroups = @(
        @(
            "launched_active_run",
            "disconnected_run",
            "completed_run"
        ),
        @(
            "active_evidence",
            "disconnected_evidence",
            "completed_evidence"
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
            $rendererLanes[$lane] = [ordered]@{
                exit_code = $exitCode
                graphics_api = $smoke.graphics_api
                source_commit_matches = (
                    [string]$smoke.source_commit -eq $SourceCommit
                )
                source_commit = [string]$smoke.source_commit
                production_path = $productionPath
                production_path_matches = $productionPathMatches
                run_identity = [string]$smoke.run_identity
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
                    [bool]$smoke.read_only_context_visible
                )
                clean_exit = $smoke.clean_exit
                errors = @($smoke.errors)
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
                run_identity = ""
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

$report = [ordered]@{
    schema_version = 3
    source_commit = $SourceCommit
    archive_sha256 = "sha256:$archiveHash"
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
    renderer_lanes = $rendererLanes
}
$reportPath = Join-Path $resolvedEvidence "clean-room-report.json"
$reportJson = $report | ConvertTo-Json -Depth 8
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
    $rendererLanes.hardware.exit_code -eq 0 -and
    $rendererLanes.hardware.graphics_api -eq "Direct3D11" -and
    $rendererLanes.hardware.source_commit_matches -and
    $rendererLanes.hardware.production_path_matches -and
    $rendererLanes.hardware.run_identity -eq "RUN-RC-001" -and
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
    $rendererLanes.software.run_identity -eq "RUN-RC-001" -and
    $rendererLanes.software.routes_match -and
    $rendererLanes.software.connection_transitions_match -and
    $rendererLanes.software.states_match -and
    $rendererLanes.software.screenshots_distinct -and
    $rendererLanes.software.manual_trading_action_count -eq 0 -and
    $rendererLanes.software.read_only_context_visible -and
    $rendererLanes.software.clean_exit -and
    $rendererLanes.software.errors.Count -eq 0
)
if (-not $gatePassed) {
    exit 1
}
exit 0
