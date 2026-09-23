$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot

function Invoke-Check {
    param(
        [string]$Label,
        [string]$Command,
        [string[]]$Arguments
    )

    Write-Host "[$Label] $Command $($Arguments -join ' ')"
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "[$Label] failed with exit code $LASTEXITCODE"
    }
}

Push-Location $root
try {
    Invoke-Check "1/10 Core tests" "python" @("-m", "pytest", "tests", "-q", "-p", "no:cacheprovider")
    Invoke-Check "2/10 Runner tests" "python" @("-m", "pytest", "runner/tests", "-q", "-p", "no:cacheprovider")
    Invoke-Check "3/10 Workflow tests" "python" @("-m", "pytest", "workflow/tests", "-q", "-p", "no:cacheprovider")
    Invoke-Check "4/10 Shared GUI tests" "python" @("-m", "pytest", "gui/tests", "-q", "-p", "no:cacheprovider")

    Invoke-Check "5/10 Python lint" "ruff" @("check", "src", "runner", "workflow", "tests", "gui", "scripts")

    Push-Location "gui-tauri"
    try {
        Invoke-Check "6/10 GUI tests" "npm" @("test")
        Invoke-Check "7/10 GUI lint" "npm" @("run", "lint")
        Invoke-Check "8/10 Frontend build" "npm" @("run", "build")

        Invoke-Check "9/10 Tauri Rust tests" "cargo" @("test", "--manifest-path", "src-tauri/Cargo.toml")
        Invoke-Check "10/10 Tauri Rust lint" "cargo" @("clippy", "--manifest-path", "src-tauri/Cargo.toml", "--", "-D", "warnings")
    } finally {
        Pop-Location
    }
} finally {
    Pop-Location
}

Write-Host "Local verification completed."
