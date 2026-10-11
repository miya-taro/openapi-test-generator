$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot

Push-Location $root
try {
    Write-Host "[verify] Running the full local verification suite. Docker is required for API + DB E2E."
    & python scripts/verify_all.py @args
    if ($LASTEXITCODE -ne 0) {
        throw "Full local verification failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
