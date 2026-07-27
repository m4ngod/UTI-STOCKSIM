param(
    [Parameter(Mandatory = $true)]
    [string]$PackageArchive,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedArchiveSha256,
    [Parameter(Mandatory = $true)]
    [string]$SourceCommit,
    [Parameter(Mandatory = $true)]
    [string]$EvidenceDir,
    [ValidateRange(60, 1800)]
    [int]$TimeoutSeconds = 600
)

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

$resolvedArchive = (Resolve-Path -LiteralPath $PackageArchive).Path
$archiveItem = Get-Item -LiteralPath $resolvedArchive
if (-not $archiveItem.Exists) {
    throw "Release archive is unavailable."
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

$archiveDirectory = Split-Path -Parent $resolvedArchive
$archiveName = Split-Path -Leaf $resolvedArchive
$scriptDirectory = Split-Path -Parent $resolvedCleanRoomScript
$runnerPath = Join-Path $resolvedEvidence "sandbox-runner.ps1"
$configurationPath = Join-Path $resolvedEvidence "frontend-v2-offline.wsb"
$exitCodePath = Join-Path $resolvedEvidence "sandbox-exit-code.txt"
$reportPath = Join-Path $resolvedEvidence "clean-room-report.json"
$sandboxErrorPath = Join-Path $resolvedEvidence "sandbox-error.txt"

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
        -File "C:\ReleaseScripts\run_frontend_v2_clean_room.ps1" `
        -PackageArchive "C:\ReleaseInput\__ARCHIVE_NAME__" `
        -ExpectedArchiveSha256 "__ARCHIVE_SHA256__" `
        -SourceCommit "__SOURCE_COMMIT__" `
        -EvidenceDir "C:\ReleaseEvidence"
    $exitCode = $LASTEXITCODE
}
catch {
    [IO.File]::WriteAllText(
        "C:\ReleaseEvidence\sandbox-error.txt",
        $_.Exception.ToString(),
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
$scriptDirectoryXml = [Security.SecurityElement]::Escape(
    $scriptDirectory
)
$evidenceDirectoryXml = [Security.SecurityElement]::Escape(
    $resolvedEvidence
)
$configuration = @"
<Configuration>
  <VGpu>Enable</VGpu>
  <Networking>Disable</Networking>
  <AudioInput>Disable</AudioInput>
  <VideoInput>Disable</VideoInput>
  <PrinterRedirection>Disable</PrinterRedirection>
  <ClipboardRedirection>Disable</ClipboardRedirection>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>$archiveDirectoryXml</HostFolder>
      <SandboxFolder>C:\ReleaseInput</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
    <MappedFolder>
      <HostFolder>$scriptDirectoryXml</HostFolder>
      <SandboxFolder>C:\ReleaseScripts</SandboxFolder>
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

$sandboxCommand = Get-Command WindowsSandbox.exe -ErrorAction Stop
$existingSandboxProcessIds = @(
    Get-Process `
        -Name WindowsSandboxRemoteSession, WindowsSandboxServer `
        -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Id
)
$sandboxProcess = Start-Process `
    -FilePath $sandboxCommand.Source `
    -ArgumentList "`"$configurationPath`"" `
    -WindowStyle Hidden `
    -PassThru
$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
while (
    -not (Test-Path -LiteralPath $exitCodePath -PathType Leaf) -and
    [DateTime]::UtcNow -lt $deadline
) {
    Start-Sleep -Milliseconds 500
}
if (-not (Test-Path -LiteralPath $exitCodePath -PathType Leaf)) {
    if (-not $sandboxProcess.HasExited) {
        Stop-Process `
            -Id $sandboxProcess.Id `
            -Force `
            -ErrorAction SilentlyContinue
    }
    Get-Process `
        -Name WindowsSandboxRemoteSession, WindowsSandboxServer `
        -ErrorAction SilentlyContinue |
        Where-Object { $_.Id -notin $existingSandboxProcessIds } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    throw "Windows Sandbox validation exceeded $TimeoutSeconds seconds."
}
$sandboxExitCode = (
    Get-Content -LiteralPath $exitCodePath -Raw -Encoding UTF8
).Trim()
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

Get-Item -LiteralPath $reportPath
