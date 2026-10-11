param([switch]$SmokeTest)
$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonEnvironment = Join-Path $repo "runner\.venv"
$pythonExecutable = Join-Path $pythonEnvironment "Scripts\python.exe"
$requirementsFile = Join-Path $repo "requirements-runtime.txt"
$requirementsStamp = Join-Path $pythonEnvironment ".runtime-requirements.sha256"
$frontend = Join-Path $repo "gui-tauri"
$frontendDependencies = Join-Path $frontend "node_modules"
$frontendLockfile = Join-Path $frontend "package-lock.json"
$frontendStamp = Join-Path $frontendDependencies ".package-lock.sha256"

function Require-Command {
    param([string]$Name, [string]$InstallHint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found. $InstallHint"
    }
}

function Invoke-Checked {
    param([string]$Command, [string[]]$Arguments)
    Write-Host "[setup] $Command $($Arguments -join ' ')"
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE."
    }
}

Require-Command "py.exe" "Install Python 3.10 or newer and enable the Python launcher."
Require-Command "node.exe" "Install Node.js 22.12 or newer."
Require-Command "npm.cmd" "Install Node.js 22.12 or newer (npm is included)."

$pythonVersion = & py.exe -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0) { throw "Python 3 could not be started with 'py -3'." }
if ([version]$pythonVersion.Trim() -lt [version]"3.10") {
    throw "Python 3.10 or newer is required; found $($pythonVersion.Trim())."
}

$nodeVersionText = (& node.exe --version).Trim().TrimStart("v")
if ($LASTEXITCODE -ne 0) { throw "Node.js could not be started." }
if ([version]$nodeVersionText -lt [version]"22.12") {
    throw "Node.js 22.12 or newer is required; found $nodeVersionText."
}

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    Invoke-Checked "py.exe" @("-3", "-m", "venv", $pythonEnvironment)
}

$env:PATH = (Join-Path $pythonEnvironment "Scripts") + [System.IO.Path]::PathSeparator + $env:PATH
$runtimeHash = (Get-FileHash -LiteralPath $requirementsFile -Algorithm SHA256).Hash
$installedRuntimeHash = if (Test-Path -LiteralPath $requirementsStamp) {
    (Get-Content -LiteralPath $requirementsStamp -Raw).Trim()
} else { "" }
if ($runtimeHash -ne $installedRuntimeHash) {
    Invoke-Checked $pythonExecutable @("-m", "pip", "install", "--disable-pip-version-check", "-r", $requirementsFile)
    [System.IO.File]::WriteAllText($requirementsStamp, $runtimeHash)
}

$lockHash = (Get-FileHash -LiteralPath $frontendLockfile -Algorithm SHA256).Hash
$installedLockHash = if (Test-Path -LiteralPath $frontendStamp) {
    (Get-Content -LiteralPath $frontendStamp -Raw).Trim()
} else { "" }
if (-not (Test-Path -LiteralPath $frontendDependencies) -or $lockHash -ne $installedLockHash) {
    Push-Location $frontend
    try {
        Invoke-Checked "npm.cmd" @("ci")
        [System.IO.File]::WriteAllText($frontendStamp, $lockHash)
    } finally {
        Pop-Location
    }
}

Push-Location $frontend
try {
    Invoke-Checked "npm.cmd" @("run", "build")
} finally {
    Pop-Location
}

Write-Host "[run] Starting the local browser app. Rust and Visual Studio Build Tools are not used."
Write-Host "[run] Keep this window open while using the app. Press Ctrl+C to stop."
$serverArguments = @(
    (Join-Path $repo "gui\web_server.py"),
    "--root", $repo,
    "--static-root", (Join-Path $frontend "dist"),
    "--port", "0"
)
if ($SmokeTest) { $serverArguments += "--smoke-test" }
Invoke-Checked $pythonExecutable $serverArguments
