param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("widgets", "qml", "web")]
    [string]$Technology,
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

$prototypeRoot = $PSScriptRoot
$repositoryRoot = [IO.Path]::GetFullPath((Join-Path $prototypeRoot "..\.."))
$python = @(
    $PythonExecutable,
    $env:UTI_STOCKSIM_PYTHON,
    (Join-Path $repositoryRoot ".venv\Scripts\python.exe")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $python) {
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $python) {
    throw "No Python executable found. Activate the project venv or pass -PythonExecutable."
}
$entry = Join-Path $prototypeRoot "entry_$Technology.py"
$deploymentRoot = Join-Path $prototypeRoot "deployment"
$outputDir = Join-Path $deploymentRoot $Technology
$logDir = Join-Path $deploymentRoot "logs"
$reportPath = Join-Path $logDir "$Technology-report.xml"
$exitPath = Join-Path $logDir "$Technology-exit-code.txt"

$resolvedPrototype = [IO.Path]::GetFullPath($prototypeRoot)
$resolvedOutput = [IO.Path]::GetFullPath($outputDir)
if (-not $resolvedOutput.StartsWith($resolvedPrototype, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to package outside prototype workspace: $resolvedOutput"
}

New-Item -ItemType Directory -Force -Path $outputDir, $logDir | Out-Null

$arguments = @(
    "-m", "nuitka",
    $entry,
    "--standalone",
    "--enable-plugin=pyside6",
    "--jobs=1",
    "--include-module=numpy._core._exceptions",
    "--assume-yes-for-downloads",
    "--noinclude-qt-translations",
    "--nofollow-import-to=app",
    "--nofollow-import-to=infra",
    "--nofollow-import-to=observability",
    "--output-dir=$outputDir",
    "--output-filename=UTI-Tech-$Technology.exe",
    "--report=$reportPath"
)

if ($Technology -eq "qml") {
    $arguments += "--include-data-file=$(Join-Path $prototypeRoot 'qml\Main.qml')=qml/Main.qml"
}
if ($Technology -eq "web") {
    $arguments += "--include-data-dir=$(Join-Path $prototypeRoot 'web')=web"
}

& $python @arguments
$exitCode = $LASTEXITCODE
if ($exitCode -eq 0 -and $Technology -eq "qml") {
    # Nuitka's umbrella `qml` family scans every installed QML module and exceeded
    # the prototype's 10-minute packaging budget. Copy only the modules imported by
    # Main.qml and the runtime DLLs reported by those plugin binaries.
    $pysideRoot = (& $python -c "import pathlib, PySide6; print(pathlib.Path(PySide6.__file__).resolve().parent)") |
        Select-Object -Last 1
    if ($LASTEXITCODE -ne 0 -or -not $pysideRoot) {
        throw "Unable to locate the PySide6 runtime for the minimum QML manifest."
    }
    $qmlSource = Join-Path $pysideRoot "qml"
    $qmlTarget = Join-Path $outputDir "entry_qml.dist\PySide6\qml"
    $distTarget = Join-Path $outputDir "entry_qml.dist"
    New-Item -ItemType Directory -Force -Path $qmlTarget | Out-Null
    foreach ($module in @("Qt", "QtCore", "QtQml")) {
        Copy-Item -LiteralPath (Join-Path $qmlSource $module) -Destination $qmlTarget -Recurse -Force
    }

    $qtQuickSource = Join-Path $qmlSource "QtQuick"
    $qtQuickTarget = Join-Path $qmlTarget "QtQuick"
    New-Item -ItemType Directory -Force -Path $qtQuickTarget | Out-Null
    Get-ChildItem -LiteralPath $qtQuickSource -File |
        Copy-Item -Destination $qtQuickTarget -Force
    foreach ($module in @("Layouts", "Templates", "Window")) {
        Copy-Item -LiteralPath (Join-Path $qtQuickSource $module) -Destination $qtQuickTarget -Recurse -Force
    }

    $controlsSource = Join-Path $qtQuickSource "Controls"
    $controlsTarget = Join-Path $qtQuickTarget "Controls"
    New-Item -ItemType Directory -Force -Path $controlsTarget | Out-Null
    Get-ChildItem -LiteralPath $controlsSource -File |
        Copy-Item -Destination $controlsTarget -Force
    foreach ($module in @("Basic", "impl")) {
        Copy-Item -LiteralPath (Join-Path $controlsSource $module) -Destination $controlsTarget -Recurse -Force
    }

    $qtRuntime = $pysideRoot
    foreach ($library in @(
        "Qt6QmlMeta.dll",
        "Qt6QmlWorkerScript.dll",
        "Qt6QuickControls2.dll",
        "Qt6QuickControls2Basic.dll",
        "Qt6QuickControls2BasicStyleImpl.dll",
        "Qt6QuickControls2Impl.dll",
        "Qt6QuickLayouts.dll",
        "Qt6QuickTemplates2.dll"
    )) {
        Copy-Item -LiteralPath (Join-Path $qtRuntime $library) -Destination $distTarget -Force
    }
}
Set-Content -LiteralPath $exitPath -Value $exitCode -Encoding utf8
exit $exitCode
