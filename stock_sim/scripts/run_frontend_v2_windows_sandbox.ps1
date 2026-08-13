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
$resultAckPath = Join-Path $resolvedEvidence "sandbox-result-ack.txt"
$resultAckReceivedPath = Join-Path `
    $resolvedEvidence `
    "sandbox-result-ack-received.txt"
$resultAckToken = [Guid]::NewGuid().ToString("N")
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
$expectedResultAck = "__RESULT_ACK_TOKEN__"
$resultAckDeadline = [DateTime]::UtcNow.AddSeconds(60)
$resultAckReceived = $false
do {
    $resultAckPath = "C:\ReleaseEvidence\sandbox-result-ack.txt"
    if (Test-Path -LiteralPath $resultAckPath -PathType Leaf) {
        $observedResultAck = (
            Get-Content -LiteralPath $resultAckPath -Raw -Encoding UTF8
        ).Trim()
        if ($observedResultAck -ceq $expectedResultAck) {
            [IO.File]::WriteAllText(
                "C:\ReleaseEvidence\sandbox-result-ack-received.txt",
                $observedResultAck,
                [Text.UTF8Encoding]::new($false)
            )
            $resultAckReceived = $true
            break
        }
    }
    Start-Sleep -Milliseconds 200
}
while ([DateTime]::UtcNow -lt $resultAckDeadline)
if (
    -not $resultAckReceived -and
    $exitCode -eq 0 -and
    -not (Test-Path -LiteralPath "C:\ReleaseEvidence\sandbox-error.txt")
) {
    [IO.File]::WriteAllText(
        "C:\ReleaseEvidence\sandbox-error.txt",
        "Windows Sandbox result acknowledgment was not received.",
        [Text.UTF8Encoding]::new($false)
    )
}
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
$runner = $runner.Replace(
    "__RESULT_ACK_TOKEN__",
    $resultAckToken
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

function Get-OwnedWindowsSandboxTerminalProcess {
    param(
        [Parameter(Mandatory = $true)]
        [PSCustomObject]$LauncherIdentity
    )

    $earliestChildStartUtc = $LauncherIdentity.StartTimeUtc.AddSeconds(-2)
    $ownedCandidates = @()
    foreach ($terminalName in @(
        "WindowsSandboxClient.exe",
        "WindowsSandboxRemoteSession.exe"
    )) {
        $candidates = Get-CimInstance `
            -ClassName Win32_Process `
            -Filter "Name = '$terminalName'" `
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
                [int]$candidate.ParentProcessId -eq
                    $LauncherIdentity.ProcessId -and
                $startTimeUtc -ge $earliestChildStartUtc
            ) {
                $ownedCandidates += [PSCustomObject]@{
                    Name = $terminalName
                    ProcessId = [int]$candidate.ProcessId
                    ParentProcessId = [int]$candidate.ParentProcessId
                    StartTimeUtc = $startTimeUtc
                }
            }
        }
    }
    if ($ownedCandidates.Count -gt 1) {
        throw "Windows Sandbox terminal process ownership was ambiguous."
    }
    return $ownedCandidates | Select-Object -First 1
}

function Test-OwnedWindowsProcessIdentityAlive {
    param(
        [AllowNull()]
        [PSCustomObject]$ProcessIdentity
    )

    if ($null -eq $ProcessIdentity) {
        return $false
    }
    $candidate = Get-CimInstance `
        -ClassName Win32_Process `
        -Filter "ProcessId = $($ProcessIdentity.ProcessId)" `
        -ErrorAction SilentlyContinue
    if (
        $null -eq $candidate -or
        [string]$candidate.Name -cne [string]$ProcessIdentity.Name
    ) {
        return $false
    }
    if (
        $null -ne $ProcessIdentity.ParentProcessId -and
        [int]$candidate.ParentProcessId -ne
            [int]$ProcessIdentity.ParentProcessId
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
    return $actualStartTimeUtc -eq $ProcessIdentity.StartTimeUtc
}

function Test-OwnedWindowsSandboxGuestProcessesStopped {
    param(
        [AllowNull()]
        [PSCustomObject]$ServerIdentity,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [PSCustomObject[]]$VmWorkerIdentities
    )

    if (
        Test-OwnedWindowsProcessIdentityAlive `
            -ProcessIdentity $ServerIdentity
    ) {
        return $false
    }
    foreach ($workerIdentity in @($VmWorkerIdentities)) {
        if (
            Test-OwnedWindowsProcessIdentityAlive `
                -ProcessIdentity $workerIdentity
        ) {
            return $false
        }
    }
    return $true
}

function Test-OwnedWindowsSandboxServerOwnership {
    param(
        [AllowNull()]
        [PSCustomObject]$TerminalProcessIdentity,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [PSCustomObject[]]$ServerIdentities
    )

    if ($null -eq $TerminalProcessIdentity) {
        return $false
    }
    if (
        [string]$TerminalProcessIdentity.Name -ceq
            "WindowsSandboxClient.exe"
    ) {
        return $ServerIdentities.Count -eq 0
    }
    if (
        [string]$TerminalProcessIdentity.Name -cne
            "WindowsSandboxRemoteSession.exe"
    ) {
        return $false
    }
    return (
        $ServerIdentities.Count -eq 1 -and
        [int]$ServerIdentities[0].ParentProcessId -eq
            [int]$TerminalProcessIdentity.ProcessId
    )
}

function Get-NewWindowsSandboxGuestProcessIdentities {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [int[]]$BaselineProcessIds,
        [Parameter(Mandatory = $true)]
        [DateTime]$LauncherStartTimeUtc
    )

    $identities = @()
    foreach ($processName in @("WindowsSandboxServer.exe", "vmwp.exe")) {
        $candidates = Get-CimInstance `
            -ClassName Win32_Process `
            -Filter "Name = '$processName'" `
            -ErrorAction SilentlyContinue
        foreach ($candidate in @($candidates)) {
            if ($BaselineProcessIds -contains [int]$candidate.ProcessId) {
                continue
            }
            try {
                $startTimeUtc = (
                    [DateTime]$candidate.CreationDate
                ).ToUniversalTime()
            }
            catch {
                continue
            }
            if ($startTimeUtc -lt $LauncherStartTimeUtc.AddSeconds(-2)) {
                continue
            }
            $identities += [PSCustomObject]@{
                Name = $processName
                ProcessId = [int]$candidate.ProcessId
                ParentProcessId = [int]$candidate.ParentProcessId
                StartTimeUtc = $startTimeUtc
            }
        }
    }
    if (@($identities | Where-Object { $_.Name -ceq "vmwp.exe" }).Count -gt 1) {
        throw "Windows Sandbox VM worker ownership was ambiguous."
    }
    if (
        @(
            $identities |
                Where-Object { $_.Name -ceq "WindowsSandboxServer.exe" }
        ).Count -gt 1
    ) {
        throw "Windows Sandbox server ownership was ambiguous."
    }
    return $identities
}

function Get-WindowsSandboxComputeSystemSnapshot {
    $hcsdiag = Get-Command hcsdiag.exe -ErrorAction Stop
    $rawSnapshot = & $hcsdiag.Source list -raw
    if ($LASTEXITCODE -ne 0) {
        throw "Windows Sandbox compute-system inventory was unavailable."
    }
    try {
        $snapshot = @($rawSnapshot | ConvertFrom-Json -ErrorAction Stop)
    }
    catch {
        throw "Windows Sandbox compute-system inventory was unreadable."
    }
    return @(
        $snapshot |
            ForEach-Object {
                [PSCustomObject]@{
                    Id = [string]$_.Id
                    SystemType = [string]$_.SystemType
                    Owner = [string]$_.Owner
                    RuntimeId = [string]$_.RuntimeId
                    RuntimeTemplateId = [string]$_.RuntimeTemplateId
                }
            }
    )
}

function Get-NewWindowsSandboxComputeSystemIdentity {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$BaselineComputeSystemIds
    )

    $newComputeSystems = @(
        Get-WindowsSandboxComputeSystemSnapshot |
            Where-Object {
                $_.Id -and
                -not ($BaselineComputeSystemIds -contains $_.Id)
            }
    )
    if ($newComputeSystems.Count -gt 1) {
        throw "Windows Sandbox compute-system ownership was ambiguous."
    }
    if ($newComputeSystems.Count -eq 0) {
        return $null
    }
    $candidate = $newComputeSystems[0]
    if (
        ($candidate.SystemType -and
            $candidate.SystemType -cne "VirtualMachine") -or
        ($candidate.Owner -and $candidate.Owner -cne "Madrid") -or
        ($candidate.RuntimeId -and
            $candidate.RuntimeId -cne $candidate.Id)
    ) {
        throw "Windows Sandbox compute-system ownership was ambiguous."
    }
    if (-not $candidate.RuntimeTemplateId) {
        return $candidate
    }
    if (
        -not ($BaselineComputeSystemIds -contains $candidate.RuntimeTemplateId)
    ) {
        throw "Windows Sandbox compute-system ownership was ambiguous."
    }
    return $candidate
}

function Merge-WindowsSandboxComputeSystemIdentity {
    param(
        [AllowNull()]
        [PSCustomObject]$CurrentIdentity,
        [AllowNull()]
        [PSCustomObject]$ObservedIdentity
    )

    if ($null -eq $ObservedIdentity) {
        return $CurrentIdentity
    }
    if ($null -eq $CurrentIdentity) {
        return $ObservedIdentity
    }
    if ($ObservedIdentity.Id -cne $CurrentIdentity.Id) {
        throw "Windows Sandbox compute-system ownership was ambiguous."
    }
    $mergedFields = @{}
    foreach (
        $fieldName in @(
            "SystemType",
            "Owner",
            "RuntimeId",
            "RuntimeTemplateId"
        )
    ) {
        $currentValue = [string]$CurrentIdentity.$fieldName
        $observedValue = [string]$ObservedIdentity.$fieldName
        if (
            $currentValue -and
            $observedValue -and
            $observedValue -cne $currentValue
        ) {
            throw "Windows Sandbox compute-system ownership was ambiguous."
        }
        $mergedFields[$fieldName] = if ($currentValue) {
            $currentValue
        }
        else {
            $observedValue
        }
    }
    return [PSCustomObject]@{
        Id = [string]$CurrentIdentity.Id
        SystemType = [string]$mergedFields["SystemType"]
        Owner = [string]$mergedFields["Owner"]
        RuntimeId = [string]$mergedFields["RuntimeId"]
        RuntimeTemplateId = [string]$mergedFields["RuntimeTemplateId"]
    }
}

function Test-WindowsSandboxComputeSystemIdentityComplete {
    param(
        [AllowNull()]
        [PSCustomObject]$ComputeSystemIdentity,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$BaselineComputeSystemIds
    )

    return (
        $null -ne $ComputeSystemIdentity -and
        $ComputeSystemIdentity.Id -and
        $ComputeSystemIdentity.SystemType -ceq "VirtualMachine" -and
        $ComputeSystemIdentity.Owner -ceq "Madrid" -and
        $ComputeSystemIdentity.RuntimeId -ceq $ComputeSystemIdentity.Id -and
        $ComputeSystemIdentity.RuntimeTemplateId -and
        $BaselineComputeSystemIds -contains
            $ComputeSystemIdentity.RuntimeTemplateId
    )
}

function Request-OwnedWindowsSandboxRemoteSessionClose {
    param(
        [Parameter(Mandatory = $true)]
        [PSCustomObject]$TerminalProcessIdentity
    )

    if (
        [string]$TerminalProcessIdentity.Name -cne
            "WindowsSandboxRemoteSession.exe"
    ) {
        return $false
    }
    try {
        $script:sandboxTerminalCloseJob = Start-Job `
            -ScriptBlock {
                param(
                    [int]$ProcessId,
                    [int]$ParentProcessId,
                    [string]$StartTimeUtcText
                )
                $ErrorActionPreference = "Stop"
                $expectedStartTimeUtc = [DateTime]::Parse(
                    $StartTimeUtcText,
                    [Globalization.CultureInfo]::InvariantCulture,
                    [Globalization.DateTimeStyles]::RoundtripKind
                ).ToUniversalTime()
                $ownedProcess = Get-CimInstance `
                    -ClassName Win32_Process `
                    -Filter "ProcessId = $ProcessId" `
                    -ErrorAction Stop
                if (
                    [string]$ownedProcess.Name -cne
                        "WindowsSandboxRemoteSession.exe" -or
                    [int]$ownedProcess.ParentProcessId -ne $ParentProcessId -or
                    ([DateTime]$ownedProcess.CreationDate).ToUniversalTime() -ne
                        $expectedStartTimeUtc
                ) {
                    throw "Owned Sandbox terminal identity changed."
                }
                $ownedTerminal = Get-Process -Id $ProcessId -ErrorAction Stop
                if (
                    [string]$ownedTerminal.ProcessName -cne
                        "WindowsSandboxRemoteSession" -or
                    [Math]::Abs((
                        $ownedTerminal.StartTime.ToUniversalTime() -
                            $expectedStartTimeUtc
                    ).TotalMilliseconds) -gt 1.0 -or
                    $ownedTerminal.MainWindowHandle -eq [IntPtr]::Zero
                ) {
                    throw "Owned Sandbox terminal window identity changed."
                }
                Add-Type -AssemblyName UIAutomationClient
                Add-Type -AssemblyName UIAutomationTypes
                $ownedWindow = (
                    [System.Windows.Automation.AutomationElement]::FromHandle(
                        $ownedTerminal.MainWindowHandle
                    )
                )
                if ($null -eq $ownedWindow) {
                    throw "Owned Sandbox terminal window was unavailable."
                }
                $ownedCloseActions = @(
                    $ownedWindow.FindAll(
                        [System.Windows.Automation.TreeScope]::Descendants,
                        [System.Windows.Automation.Condition]::TrueCondition
                        ) |
                        Where-Object {
                            [string]$_.Current.ControlType.ProgrammaticName -ceq
                                "ControlType.Button" -and
                            [string]$_.Current.AutomationId -ceq "" -and
                            [string]$_.Current.ClassName -ceq "Button" -and
                            [string]$_.Current.FrameworkId -ceq "XAML" -and
                            [bool]$_.Current.IsEnabled -and
                            -not [bool]$_.Current.IsOffscreen
                        }
                )
                if ($ownedCloseActions.Count -ne 1) {
                    throw "Owned Sandbox terminal Close action was ambiguous."
                }
                $ownedInvokePattern = $null
                if (
                    -not $ownedCloseActions[0].TryGetCurrentPattern(
                        [System.Windows.Automation.InvokePattern]::Pattern,
                        [ref]$ownedInvokePattern
                    )
                ) {
                    throw "Owned Sandbox terminal Close action was unavailable."
                }
                "sandbox-terminal-close-dispatch-started"
                $ownedInvokePattern.Invoke()
            } `
            -ArgumentList @(
                [int]$TerminalProcessIdentity.ProcessId,
                [int]$TerminalProcessIdentity.ParentProcessId,
                $TerminalProcessIdentity.StartTimeUtc.ToString("o")
            )
        return $null -ne $script:sandboxTerminalCloseJob
    }
    catch {
        return $false
    }
}

function Request-OwnedWindowsSandboxTerminalClose {
    param(
        [AllowNull()]
        [PSCustomObject]$TerminalProcessIdentity
    )

    if ($null -eq $TerminalProcessIdentity) {
        return $false
    }
    $allowedTerminalProcessNames = @{
        "WindowsSandboxClient.exe" = "WindowsSandboxClient"
        "WindowsSandboxRemoteSession.exe" = "WindowsSandboxRemoteSession"
    }
    $terminalName = [string]$TerminalProcessIdentity.Name
    if (-not $allowedTerminalProcessNames.ContainsKey($terminalName)) {
        return $false
    }
    $candidate = Get-CimInstance `
        -ClassName Win32_Process `
        -Filter "ProcessId = $($TerminalProcessIdentity.ProcessId)" `
        -ErrorAction SilentlyContinue
    if (
        $null -eq $candidate -or
        [string]$candidate.Name -cne $terminalName -or
        [int]$candidate.ParentProcessId -ne
            $TerminalProcessIdentity.ParentProcessId
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
    if ($actualStartTimeUtc -ne $TerminalProcessIdentity.StartTimeUtc) {
        return $false
    }
    $terminalProcess = Get-Process `
        -Id $TerminalProcessIdentity.ProcessId `
        -ErrorAction SilentlyContinue
    if (
        $null -eq $terminalProcess -or
        [string]$terminalProcess.ProcessName -cne
            $allowedTerminalProcessNames[$terminalName]
    ) {
        return $false
    }
    try {
        if (
            [Math]::Abs((
                $terminalProcess.StartTime.ToUniversalTime() -
                    $TerminalProcessIdentity.StartTimeUtc
            ).TotalMilliseconds) -gt 1.0 -or
            $terminalProcess.MainWindowHandle -eq [IntPtr]::Zero
        ) {
            return $false
        }
        if ($terminalName -ceq "WindowsSandboxRemoteSession.exe") {
            return Request-OwnedWindowsSandboxRemoteSessionClose `
                -TerminalProcessIdentity $TerminalProcessIdentity
        }
        return [bool]$terminalProcess.CloseMainWindow()
    }
    catch {
        return $false
    }
}

function Complete-OwnedWindowsSandboxTerminalCloseJob {
    param(
        [AllowNull()]
        [System.Management.Automation.Job]$CloseJob
    )

    if ($null -eq $CloseJob) {
        return $false
    }
    $invokeConfirmed = $false
    try {
        $invokeResult = @(
            Receive-Job -Job $CloseJob -ErrorAction SilentlyContinue
        )
        $invokeConfirmed = @(
            $invokeResult |
                Where-Object {
                    [string]$_ -ceq
                        "sandbox-terminal-close-dispatch-started"
                }
        ).Count -eq 1
    }
    catch {
        $invokeConfirmed = $false
    }
    Stop-Job -Job $CloseJob -ErrorAction SilentlyContinue
    Remove-Job -Job $CloseJob -Force -ErrorAction SilentlyContinue
    return $invokeConfirmed
}

function Request-OwnedWindowsSandboxFailureClose {
    param(
        [AllowNull()]
        [PSCustomObject]$TerminalProcessIdentity
    )

    if ($null -eq $TerminalProcessIdentity) {
        return
    }
    $allowedProcessNames = @{
        "WindowsSandboxClient.exe" = "WindowsSandboxClient"
        "WindowsSandboxRemoteSession.exe" = "WindowsSandboxRemoteSession"
    }
    $terminalName = [string]$TerminalProcessIdentity.Name
    if (-not $allowedProcessNames.ContainsKey($terminalName)) {
        return
    }
    $candidate = Get-CimInstance `
        -ClassName Win32_Process `
        -Filter "ProcessId = $($TerminalProcessIdentity.ProcessId)" `
        -ErrorAction SilentlyContinue
    if (
        $null -eq $candidate -or
        [string]$candidate.Name -cne $terminalName -or
        [int]$candidate.ParentProcessId -ne
            [int]$TerminalProcessIdentity.ParentProcessId
    ) {
        return
    }
    try {
        if (
            ([DateTime]$candidate.CreationDate).ToUniversalTime() -ne
                $TerminalProcessIdentity.StartTimeUtc
        ) {
            return
        }
        $terminalProcess = Get-Process `
            -Id $TerminalProcessIdentity.ProcessId `
            -ErrorAction SilentlyContinue
        if (
            $null -eq $terminalProcess -or
            [string]$terminalProcess.ProcessName -cne
                $allowedProcessNames[$terminalName] -or
            [Math]::Abs((
                $terminalProcess.StartTime.ToUniversalTime() -
                    $TerminalProcessIdentity.StartTimeUtc
            ).TotalMilliseconds) -gt 1.0 -or
            $terminalProcess.MainWindowHandle -eq [IntPtr]::Zero
        ) {
            return
        }
        $null = $terminalProcess.CloseMainWindow()
    }
    catch {
        # Failure cleanup must preserve the original redacted gate failure.
    }
}

$existingWindowsSandboxProcesses = @(
    Get-CimInstance `
        -ClassName Win32_Process `
        -ErrorAction SilentlyContinue |
        Where-Object { [string]$_.Name -like "WindowsSandbox*" }
)
if ($existingWindowsSandboxProcesses.Count -ne 0) {
    throw "A Windows Sandbox process already exists."
}
$existingVmWorkerProcesses = @(
    Get-CimInstance `
        -ClassName Win32_Process `
        -ErrorAction SilentlyContinue |
        Where-Object { [string]$_.Name -ceq "vmwp.exe" }
)
if ($existingVmWorkerProcesses.Count -ne 0) {
    throw "A Hyper-V VM worker already exists."
}
$baselineComputeSystemIds = @(
    Get-WindowsSandboxComputeSystemSnapshot |
        ForEach-Object { $_.Id }
)
$baselineSandboxGuestProcessIds = @()
$sandboxCommand = Get-Command WindowsSandbox.exe -ErrorAction Stop
$sandboxProcess = $null
$sandboxLauncherIdentity = $null
$sandboxTerminalProcessIdentity = $null
$sandboxComputeSystemIdentity = $null
$sandboxGuestProcessIdentities = @()
$script:sandboxTerminalCloseJob = $null
$runnerCompleted = $false
try {
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
while (
    -not (Test-Path -LiteralPath $exitCodePath -PathType Leaf) -and
    [DateTime]::UtcNow -lt $deadline
) {
    if ($null -eq $sandboxTerminalProcessIdentity) {
        $sandboxTerminalProcessIdentity = (
            Get-OwnedWindowsSandboxTerminalProcess `
                -LauncherIdentity $sandboxLauncherIdentity
        )
    }
    $observedComputeSystemIdentity = (
        Get-NewWindowsSandboxComputeSystemIdentity `
            -BaselineComputeSystemIds $baselineComputeSystemIds
    )
    $sandboxComputeSystemIdentity = (
        Merge-WindowsSandboxComputeSystemIdentity `
            -CurrentIdentity $sandboxComputeSystemIdentity `
            -ObservedIdentity $observedComputeSystemIdentity
    )
    $observedGuestProcesses = @(
        Get-NewWindowsSandboxGuestProcessIdentities `
            -BaselineProcessIds $baselineSandboxGuestProcessIds `
            -LauncherStartTimeUtc $sandboxLauncherIdentity.StartTimeUtc
    )
    foreach ($observedGuestProcess in $observedGuestProcesses) {
        if (
            -not ($sandboxGuestProcessIdentities | Where-Object {
                $_.Name -ceq $observedGuestProcess.Name -and
                $_.ProcessId -eq $observedGuestProcess.ProcessId -and
                $_.StartTimeUtc -eq $observedGuestProcess.StartTimeUtc
            })
        ) {
            $sandboxGuestProcessIdentities += $observedGuestProcess
        }
    }
    if (
        @(
            $sandboxGuestProcessIdentities |
                Where-Object { $_.Name -ceq "vmwp.exe" }
        ).Count -gt 1
    ) {
        throw "Windows Sandbox VM worker ownership was ambiguous."
    }
    if (
        @(
            $sandboxGuestProcessIdentities |
                Where-Object { $_.Name -ceq "WindowsSandboxServer.exe" }
        ).Count -gt 1
    ) {
        throw "Windows Sandbox server ownership was ambiguous."
    }
    if ([DateTime]::UtcNow -ge $sandboxLaunchGraceDeadline) {
        $sandboxProcess.Refresh()
        if (
            $sandboxProcess.HasExited -and
            -not (Test-OwnedWindowsProcessIdentityAlive `
                -ProcessIdentity $sandboxTerminalProcessIdentity)
        ) {
            $sandboxExitedBeforeResult = $true
            break
        }
        if (
            $null -ne $sandboxTerminalProcessIdentity -and
            -not (Test-OwnedWindowsProcessIdentityAlive `
                -ProcessIdentity $sandboxTerminalProcessIdentity)
        ) {
            $sandboxExitedBeforeResult = $true
            break
        }
    }
    Start-Sleep -Milliseconds 500
}
if ($sandboxExitedBeforeResult) {
    throw "Windows Sandbox exited before producing certification result."
}
if (-not (Test-Path -LiteralPath $exitCodePath -PathType Leaf)) {
    throw "Windows Sandbox validation exceeded $TimeoutSeconds seconds."
}
$sandboxExitCode = (
    Get-Content -LiteralPath $exitCodePath -Raw -Encoding UTF8
).Trim()
$reportVisibilityDeadline = [DateTime]::UtcNow.AddSeconds(30)
while (
    -not (Test-Path -LiteralPath $reportPath -PathType Leaf) -and
    [DateTime]::UtcNow -lt $reportVisibilityDeadline
) {
    Start-Sleep -Milliseconds 200
}
$reportVisible = Test-Path -LiteralPath $reportPath -PathType Leaf
$resultAckWriteFailure = $null
$resultAckPersisted = $false
if ($reportVisible) {
    try {
        [IO.File]::WriteAllText(
            $resultAckPath,
            $resultAckToken,
            [Text.UTF8Encoding]::new($false)
        )
        $observedResultAck = (
            Get-Content -LiteralPath $resultAckPath -Raw -Encoding UTF8
        ).Trim()
        $expectedResultAck = $resultAckToken
        if ($observedResultAck -cne $expectedResultAck) {
            $resultAckWriteFailure = (
                "Windows Sandbox result acknowledgment was not persisted."
            )
        }
        else {
            $resultAckPersisted = $true
        }
    }
    catch {
        $resultAckWriteFailure = (
            "Windows Sandbox result acknowledgment was not persisted."
        )
    }
}
$resultAckConfirmed = $false
if ($resultAckPersisted) {
    $resultAckReceivedDeadline = [DateTime]::UtcNow.AddSeconds(65)
    while ([DateTime]::UtcNow -lt $resultAckReceivedDeadline) {
        if (
            Test-Path `
                -LiteralPath $resultAckReceivedPath `
                -PathType Leaf
        ) {
            try {
                $observedResultAckReceived = (
                    Get-Content `
                        -LiteralPath $resultAckReceivedPath `
                        -Raw `
                        -Encoding UTF8
                ).Trim()
                $expectedResultAck = $resultAckToken
                if ($observedResultAckReceived -ceq $expectedResultAck) {
                    $resultAckConfirmed = $true
                    break
                }
            }
            catch {
                # Keep the failure at the redacted acknowledgment boundary.
            }
        }
        Start-Sleep -Milliseconds 200
    }
}
$sandboxGuestShutdownDeadline = [DateTime]::UtcNow.AddSeconds(70)
do {
    $serverIdentities = @(
        $sandboxGuestProcessIdentities |
            Where-Object { $_.Name -ceq "WindowsSandboxServer.exe" }
    )
    $serverIdentity = $serverIdentities | Select-Object -First 1
    $vmWorkerIdentities = @(
        $sandboxGuestProcessIdentities |
            Where-Object { $_.Name -ceq "vmwp.exe" }
    )
    $guestProcessesStopped = Test-OwnedWindowsSandboxGuestProcessesStopped `
        -ServerIdentity $serverIdentity `
        -VmWorkerIdentities $vmWorkerIdentities
    if ($guestProcessesStopped) {
        break
    }
    Start-Sleep -Milliseconds 500
}
while ([DateTime]::UtcNow -lt $sandboxGuestShutdownDeadline)
$vmWorkerIdentity = $vmWorkerIdentities | Select-Object -First 1
$terminalName = [string]$sandboxTerminalProcessIdentity.Name
$serverOwnershipValid = Test-OwnedWindowsSandboxServerOwnership `
    -TerminalProcessIdentity $sandboxTerminalProcessIdentity `
    -ServerIdentities $serverIdentities
$terminalCloseRequested = $false
$terminalCloseInvokeConfirmed = $false
if (
    $guestProcessesStopped -and
    $(Test-OwnedWindowsProcessIdentityAlive `
        -ProcessIdentity $sandboxTerminalProcessIdentity)
) {
    $terminalCloseRequested = Request-OwnedWindowsSandboxTerminalClose `
        -TerminalProcessIdentity $sandboxTerminalProcessIdentity
}
$sandboxTerminalCloseDeadline = [DateTime]::UtcNow.AddSeconds(30)
do {
    $sandboxProcess.Refresh()
    $launcherAlive = -not $sandboxProcess.HasExited
    $terminalProcessAlive = Test-OwnedWindowsProcessIdentityAlive `
        -ProcessIdentity $sandboxTerminalProcessIdentity
    if (
        -not $launcherAlive -and
        -not $terminalProcessAlive -and
        $guestProcessesStopped
    ) {
        break
    }
    Start-Sleep -Milliseconds 500
}
while ([DateTime]::UtcNow -lt $sandboxTerminalCloseDeadline)
if ($null -ne $script:sandboxTerminalCloseJob) {
    $terminalCloseInvokeConfirmed = (
        Complete-OwnedWindowsSandboxTerminalCloseJob `
            -CloseJob $script:sandboxTerminalCloseJob
    )
    $script:sandboxTerminalCloseJob = $null
}
$terminalProcessIdentityObserved = $null -ne $sandboxTerminalProcessIdentity
$computeSystemIdentityObserved = (
    Test-WindowsSandboxComputeSystemIdentityComplete `
        -ComputeSystemIdentity $sandboxComputeSystemIdentity `
        -BaselineComputeSystemIds $baselineComputeSystemIds
)
$vmWorkerIdentityObserved = $null -ne $vmWorkerIdentity
$remainingWindowsSandboxProcesses = @(
    Get-CimInstance `
        -ClassName Win32_Process `
        -ErrorAction SilentlyContinue |
        Where-Object { [string]$_.Name -like "WindowsSandbox*" }
)
$remainingVmWorkerProcesses = @(
    Get-CimInstance `
        -ClassName Win32_Process `
        -Filter "Name = 'vmwp.exe'" `
        -ErrorAction SilentlyContinue
)
$remainingNewComputeSystems = @(
    Get-WindowsSandboxComputeSystemSnapshot |
        Where-Object {
            $_.Id -and
            -not ($baselineComputeSystemIds -contains $_.Id)
        }
)

if ($sandboxExitCode -ne "0") {
    $details = if (Test-Path -LiteralPath $sandboxErrorPath) {
        Get-Content -LiteralPath $sandboxErrorPath -Raw -Encoding UTF8
    }
    else {
        "See clean-room-report.json for the failed release gate."
    }
    throw "Windows Sandbox validation failed with code $sandboxExitCode. $details"
}
if ($null -ne $resultAckWriteFailure) {
    throw $resultAckWriteFailure
}
if ($resultAckPersisted -and -not $resultAckConfirmed) {
    throw "Windows Sandbox did not confirm the result acknowledgment."
}
if (-not $reportVisible) {
    throw "Windows Sandbox did not produce clean-room-report.json."
}
if (Test-Path -LiteralPath $sandboxErrorPath -PathType Leaf) {
    throw "Windows Sandbox reported a redacted failure after exit code 0."
}
if (-not $terminalProcessIdentityObserved) {
    throw "Windows Sandbox terminal process ownership was not observed."
}
if (-not $computeSystemIdentityObserved) {
    throw "Windows Sandbox compute-system ownership was not observed."
}
if (-not $vmWorkerIdentityObserved) {
    throw "Windows Sandbox VM worker ownership was not observed."
}
if (-not $serverOwnershipValid) {
    throw "Windows Sandbox server ownership was ambiguous."
}
if (-not $guestProcessesStopped) {
    throw "Windows Sandbox guest processes remained active after guest shutdown."
}
if ($terminalProcessAlive -and -not $terminalCloseRequested) {
    throw "Windows Sandbox terminal window did not accept a normal close request."
}
if (
    $terminalName -ceq "WindowsSandboxRemoteSession.exe" -and
    -not $terminalCloseInvokeConfirmed
) {
    throw "Windows Sandbox terminal Close action was not confirmed."
}
if ($remainingVmWorkerProcesses.Count -ne 0) {
    throw "Windows Sandbox VM worker remained active after normal close."
}
if ($remainingNewComputeSystems.Count -ne 0) {
    throw "Windows Sandbox compute system remained active after normal close."
}
if (
    $terminalProcessAlive -or
    $launcherAlive -or
    $remainingWindowsSandboxProcesses.Count -ne 0
) {
    throw "Windows Sandbox terminal process remained active after normal close."
}

$runnerCompleted = $true
Get-Item -LiteralPath $reportPath
}
finally {
    if ($null -ne $script:sandboxTerminalCloseJob) {
        $null = Complete-OwnedWindowsSandboxTerminalCloseJob `
            -CloseJob $script:sandboxTerminalCloseJob
        $script:sandboxTerminalCloseJob = $null
    }
    if (-not $runnerCompleted) {
        Request-OwnedWindowsSandboxFailureClose `
            -TerminalProcessIdentity $sandboxTerminalProcessIdentity
    }
    if (
        -not $runnerCompleted -and
        $null -ne $sandboxLauncherIdentity
    ) {
        Stop-OwnedWindowsSandboxLauncher `
            -LauncherIdentity $sandboxLauncherIdentity
    }
}
