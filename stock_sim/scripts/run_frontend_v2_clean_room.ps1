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

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

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
    foreach ($lane in @("hardware", "software")) {
        $laneDir = Join-Path $resolvedEvidence $lane
        New-Item -ItemType Directory -Force -Path $laneDir | Out-Null
        & $executable.FullName "--renderer-lane=$lane" "--smoke-report-dir=$laneDir"
        $exitCode = $LASTEXITCODE
        $smokePath = Join-Path $laneDir "smoke-report.json"
        if (Test-Path -LiteralPath $smokePath) {
            $smoke = Get-Content -LiteralPath $smokePath -Raw -Encoding utf8 |
                ConvertFrom-Json
            $states = @($smoke.observations | ForEach-Object { $_.state })
            $statesMatch = (
                ($states -join "|") -eq "loading|empty|disconnected"
            )
            $rendererLanes[$lane] = [ordered]@{
                exit_code = $exitCode
                graphics_api = $smoke.graphics_api
                states = $states
                states_match = $statesMatch
                clean_exit = $smoke.clean_exit
                errors = @($smoke.errors)
            }
        }
        else {
            $rendererLanes[$lane] = [ordered]@{
                exit_code = $exitCode
                graphics_api = "unavailable"
                states = @()
                states_match = $false
                clean_exit = $false
                errors = @("smoke-report.json was not produced")
            }
        }
    }
}

$report = [ordered]@{
    schema_version = 2
    source_commit = $SourceCommit
    archive_sha256 = "sha256:$archiveHash"
    operating_system = $operatingSystem
    architecture = $architecture
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
$report | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $reportPath -Encoding utf8

$gatePassed = (
    $operatingSystem -match "Windows 11" -and
    $architecture -match "AMD64|x86_64" -and
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
    $rendererLanes.hardware.states_match -and
    $rendererLanes.hardware.clean_exit -and
    $rendererLanes.hardware.errors.Count -eq 0 -and
    $rendererLanes.software.exit_code -eq 0 -and
    $rendererLanes.software.graphics_api -eq "Software" -and
    $rendererLanes.software.states_match -and
    $rendererLanes.software.clean_exit -and
    $rendererLanes.software.errors.Count -eq 0
)
if (-not $gatePassed) {
    exit 1
}
exit 0
