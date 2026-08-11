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
    [string]$EvidenceDir,
    [ValidateRange(60, 7200)]
    [int]$TimeoutSeconds = 3600
)

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

$resolvedArchive = (Resolve-Path -LiteralPath $PackageArchive).Path
$archiveItem = Get-Item -LiteralPath $resolvedArchive
if (-not $archiveItem.Exists) {
    throw "Release archive is unavailable."
}
$resolvedWidgetsArchive = (
    Resolve-Path -LiteralPath $WidgetsPackageArchive
).Path
$widgetsArchiveItem = Get-Item -LiteralPath $resolvedWidgetsArchive
if (-not $widgetsArchiveItem.Exists) {
    throw "Widgets release archive is unavailable."
}
$cleanRoomScript = Join-Path $PSScriptRoot "run_frontend_v2_clean_room.ps1"
$resolvedCleanRoomScript = (
    Resolve-Path -LiteralPath $cleanRoomScript
).Path

$resolvedEvidence = [IO.Path]::GetFullPath($EvidenceDir)
if (Test-Path -LiteralPath $resolvedEvidence) {
    if (@(Get-ChildItem -LiteralPath $resolvedEvidence -Force).Count -gt 0) {
        throw "Windows Sandbox evidence directory must be empty."
    }
}
else {
    New-Item -ItemType Directory -Path $resolvedEvidence | Out-Null
}

$archiveName = Split-Path -Leaf $resolvedArchive
if ($archiveName -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
    throw "Package archive name contains unsafe characters."
}
$widgetsArchiveName = Split-Path -Leaf $resolvedWidgetsArchive
if ($widgetsArchiveName -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
    throw "Widgets archive name contains unsafe characters."
}
$candidateInputStage = Join-Path $resolvedEvidence "candidate-input"
$widgetsInputStage = Join-Path $resolvedEvidence "widgets-input"
New-Item -ItemType Directory -Path $candidateInputStage | Out-Null
New-Item -ItemType Directory -Path $widgetsInputStage | Out-Null
Copy-Item `
    -LiteralPath $resolvedArchive `
    -Destination (Join-Path $candidateInputStage $archiveName)
Copy-Item `
    -LiteralPath $resolvedWidgetsArchive `
    -Destination (Join-Path $widgetsInputStage $widgetsArchiveName)
$archiveDirectory = $candidateInputStage
$widgetsArchiveDirectory = $widgetsInputStage
$runnerPath = Join-Path $resolvedEvidence "sandbox-runner.ps1"
$cleanRoomRunnerPath = Join-Path $resolvedEvidence "clean-room-runner.ps1"
$configurationPath = Join-Path $resolvedEvidence "frontend-v2-offline.wsb"
$exitCodePath = Join-Path $resolvedEvidence "sandbox-exit-code.txt"
$reportPath = Join-Path $resolvedEvidence "clean-room-report.json"
$sandboxErrorPath = Join-Path $resolvedEvidence "sandbox-error.txt"
Copy-Item `
    -LiteralPath $resolvedCleanRoomScript `
    -Destination $cleanRoomRunnerPath

$runner = @'
$ErrorActionPreference = "Continue"
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$exitCode = 1
try {
    & powershell.exe `
        -NoLogo `
        -NoProfile `
        -ExecutionPolicy Bypass `
        -File "C:\ReleaseEvidence\clean-room-runner.ps1" `
        -PackageArchive "C:\ReleaseInputQml\__ARCHIVE_NAME__" `
        -ExpectedArchiveSha256 "__ARCHIVE_SHA256__" `
        -WidgetsPackageArchive "C:\ReleaseInputWidgets\__WIDGETS_ARCHIVE_NAME__" `
        -ExpectedWidgetsArchiveSha256 "__WIDGETS_ARCHIVE_SHA256__" `
        -SourceCommit "__SOURCE_COMMIT__" `
        -EvidenceDir "C:\ReleaseEvidence"
    $exitCode = $LASTEXITCODE
}
catch {
    [IO.File]::WriteAllText(
        "C:\ReleaseEvidence\sandbox-error.txt",
        "Windows Sandbox certification failed at a redacted boundary.",
        [Text.UTF8Encoding]::new($false)
    )
}
[IO.File]::WriteAllText(
    "C:\ReleaseEvidence\sandbox-exit-code.txt",
    [string]$exitCode,
    [Text.UTF8Encoding]::new($false)
)
& shutdown.exe /s /t 0
'@
$runner = $runner.Replace(
    "__ARCHIVE_NAME__",
    $archiveName.Replace('"', '""')
)
$runner = $runner.Replace(
    "__ARCHIVE_SHA256__",
    $ExpectedArchiveSha256.Replace('"', '""')
)
$runner = $runner.Replace(
    "__WIDGETS_ARCHIVE_NAME__",
    $widgetsArchiveName.Replace('"', '""')
)
$runner = $runner.Replace(
    "__WIDGETS_ARCHIVE_SHA256__",
    $ExpectedWidgetsArchiveSha256.Replace('"', '""')
)
$runner = $runner.Replace(
    "__SOURCE_COMMIT__",
    $SourceCommit.Replace('"', '""')
)
[IO.File]::WriteAllText(
    $runnerPath,
    $runner,
    [Text.UTF8Encoding]::new($false)
)

$archiveDirectoryXml = [Security.SecurityElement]::Escape(
    $archiveDirectory
)
$widgetsArchiveDirectoryXml = [Security.SecurityElement]::Escape(
    $widgetsArchiveDirectory
)
$evidenceDirectoryXml = [Security.SecurityElement]::Escape(
    $resolvedEvidence
)
$configuration = @"
<Configuration>
  <VGpu>Enable</VGpu>
  <Networking>Disable</Networking>
  <AudioInput>Disable</AudioInput>
  <AudioOutput>Disable</AudioOutput>
  <VideoInput>Disable</VideoInput>
  <PrinterRedirection>Disable</PrinterRedirection>
  <ClipboardRedirection>Disable</ClipboardRedirection>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>$archiveDirectoryXml</HostFolder>
      <SandboxFolder>C:\ReleaseInputQml</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
    <MappedFolder>
      <HostFolder>$widgetsArchiveDirectoryXml</HostFolder>
      <SandboxFolder>C:\ReleaseInputWidgets</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
    <MappedFolder>
      <HostFolder>$evidenceDirectoryXml</HostFolder>
      <SandboxFolder>C:\ReleaseEvidence</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File C:\ReleaseEvidence\sandbox-runner.ps1</Command>
  </LogonCommand>
</Configuration>
"@
[IO.File]::WriteAllText(
    $configurationPath,
    $configuration,
    [Text.UTF8Encoding]::new($false)
)

function Stop-OwnedWindowsSandboxLauncher {
    param(
        [Parameter(Mandatory = $true)]
        [PSCustomObject]$LauncherIdentity
    )

    $launcher = Get-Process `
        -Id $LauncherIdentity.ProcessId `
        -ErrorAction SilentlyContinue
    if ($null -eq $launcher) {
        return
    }
    try {
        $actualStartTimeUtc = $launcher.StartTime.ToUniversalTime()
    }
    catch {
        return
    }
    if ($actualStartTimeUtc -ne $LauncherIdentity.StartTimeUtc) {
        return
    }
    Stop-Process `
        -InputObject $launcher `
        -Force `
        -ErrorAction SilentlyContinue
}

function Get-OwnedWindowsSandboxRemoteSession {
    param(
        [Parameter(Mandatory = $true)]
        [PSCustomObject]$LauncherIdentity
    )

    $earliestChildStartUtc = $LauncherIdentity.StartTimeUtc.AddSeconds(-2)
    $candidates = Get-CimInstance `
        -ClassName Win32_Process `
        -Filter "Name = 'WindowsSandboxRemoteSession.exe'" `
        -ErrorAction SilentlyContinue
    foreach ($candidate in @($candidates)) {
        try {
            $startTimeUtc = (
                [DateTime]$candidate.CreationDate
            ).ToUniversalTime()
        }
        catch {
            continue
        }
        if (
            [int]$candidate.ParentProcessId -eq $LauncherIdentity.ProcessId -and
            $startTimeUtc -ge $earliestChildStartUtc
        ) {
            return [PSCustomObject]@{
                ProcessId = [int]$candidate.ProcessId
                ParentProcessId = [int]$candidate.ParentProcessId
                StartTimeUtc = $startTimeUtc
            }
        }
    }
    return $null
}

function Test-OwnedWindowsSandboxRemoteSessionAlive {
    param(
        [AllowNull()]
        [PSCustomObject]$RemoteSessionIdentity
    )

    if ($null -eq $RemoteSessionIdentity) {
        return $false
    }
    $candidate = Get-CimInstance `
        -ClassName Win32_Process `
        -Filter "ProcessId = $($RemoteSessionIdentity.ProcessId)" `
        -ErrorAction SilentlyContinue
    if (
        $null -eq $candidate -or
        [string]$candidate.Name -cne "WindowsSandboxRemoteSession.exe" -or
        [int]$candidate.ParentProcessId -ne
            $RemoteSessionIdentity.ParentProcessId
    ) {
        return $false
    }
    try {
        $actualStartTimeUtc = (
            [DateTime]$candidate.CreationDate
        ).ToUniversalTime()
    }
    catch {
        return $false
    }
    return $actualStartTimeUtc -eq $RemoteSessionIdentity.StartTimeUtc
}

$sandboxCommand = Get-Command WindowsSandbox.exe -ErrorAction Stop
$sandboxProcess = Start-Process `
    -FilePath $sandboxCommand.Source `
    -ArgumentList "`"$configurationPath`"" `
    -PassThru
$sandboxLauncherIdentity = [PSCustomObject]@{
    ProcessId = $sandboxProcess.Id
    StartTimeUtc = $sandboxProcess.StartTime.ToUniversalTime()
}
$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
$sandboxLaunchGraceDeadline = [DateTime]::UtcNow.AddSeconds(5)
$sandboxExitedBeforeResult = $false
$sandboxRemoteSessionIdentity = $null
while (
    -not (Test-Path -LiteralPath $exitCodePath -PathType Leaf) -and
    [DateTime]::UtcNow -lt $deadline
) {
    if ($null -eq $sandboxRemoteSessionIdentity) {
        $sandboxRemoteSessionIdentity = (
            Get-OwnedWindowsSandboxRemoteSession `
                -LauncherIdentity $sandboxLauncherIdentity
        )
    }
    if ([DateTime]::UtcNow -ge $sandboxLaunchGraceDeadline) {
        $sandboxProcess.Refresh()
        if (
            $sandboxProcess.HasExited -and
            -not (Test-OwnedWindowsSandboxRemoteSessionAlive `
                -RemoteSessionIdentity $sandboxRemoteSessionIdentity)
        ) {
            $sandboxExitedBeforeResult = $true
            break
        }
        if (
            $null -ne $sandboxRemoteSessionIdentity -and
            -not (Test-OwnedWindowsSandboxRemoteSessionAlive `
                -RemoteSessionIdentity $sandboxRemoteSessionIdentity)
        ) {
            $sandboxExitedBeforeResult = $true
            break
        }
    }
    Start-Sleep -Milliseconds 500
}
if ($sandboxExitedBeforeResult) {
    Stop-OwnedWindowsSandboxLauncher `
        -LauncherIdentity $sandboxLauncherIdentity
    throw "Windows Sandbox exited before producing certification result."
}
if (-not (Test-Path -LiteralPath $exitCodePath -PathType Leaf)) {
    Stop-OwnedWindowsSandboxLauncher `
        -LauncherIdentity $sandboxLauncherIdentity
    throw "Windows Sandbox validation exceeded $TimeoutSeconds seconds."
}
$sandboxExitCode = (
    Get-Content -LiteralPath $exitCodePath -Raw -Encoding UTF8
).Trim()
$sandboxShutdownDeadline = [DateTime]::UtcNow.AddSeconds(10)
do {
    $sandboxProcess.Refresh()
    $launcherAlive = -not $sandboxProcess.HasExited
    $remoteSessionAlive = Test-OwnedWindowsSandboxRemoteSessionAlive `
        -RemoteSessionIdentity $sandboxRemoteSessionIdentity
    if (-not $launcherAlive -and -not $remoteSessionAlive) {
        break
    }
    Start-Sleep -Milliseconds 500
}
while ([DateTime]::UtcNow -lt $sandboxShutdownDeadline)
Stop-OwnedWindowsSandboxLauncher `
    -LauncherIdentity $sandboxLauncherIdentity

if ($sandboxExitCode -ne "0") {
    $details = if (Test-Path -LiteralPath $sandboxErrorPath) {
        Get-Content -LiteralPath $sandboxErrorPath -Raw -Encoding UTF8
    }
    else {
        "See clean-room-report.json for the failed release gate."
    }
    throw "Windows Sandbox validation failed with code $sandboxExitCode. $details"
}
if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
    throw "Windows Sandbox did not produce clean-room-report.json."
}
if (
    Test-OwnedWindowsSandboxRemoteSessionAlive `
        -RemoteSessionIdentity $sandboxRemoteSessionIdentity
) {
    throw "Windows Sandbox RemoteSession remained active after successful certification."
}

Get-Item -LiteralPath $reportPath
