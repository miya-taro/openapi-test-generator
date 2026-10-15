$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$buildRoot = Join-Path $repo ".build"
$runtimeResources = Join-Path $buildRoot "python-runtime"
$runtimeStaging = Join-Path $buildRoot "portable-runtime-staging"
$portable = Join-Path $repo "dist\openapi-test-tool-portable"
$installerOutput = Join-Path $repo "dist\openapi-test-tool-installers"
$signingThumbprint = ($env:WINDOWS_SIGNING_CERTIFICATE_THUMBPRINT -replace '\s', '').ToUpperInvariant()
$signingRequired = $env:WINDOWS_REQUIRE_SIGNING -eq "true"

function Get-CheckedChildPath {
    param([string]$Path, [string]$Parent)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullParent = [System.IO.Path]::GetFullPath($Parent).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    if (-not $fullPath.StartsWith($fullParent + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside its permitted directory: $fullPath"
    }
    return $fullPath
}

function Invoke-Check {
    param([string]$Command, [string[]]$Arguments)

    Write-Host "[package] $Command $($Arguments -join ' ')"
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "[package] $Command failed with exit code $LASTEXITCODE"
    }
}

function Get-SignToolPath {
    $command = Get-Command "signtool.exe" -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    $sdkRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    if (Test-Path -LiteralPath $sdkRoot) {
        $candidates = Get-ChildItem -LiteralPath $sdkRoot -Directory |
            Sort-Object -Property Name -Descending
        foreach ($candidate in $candidates) {
            $path = Join-Path $candidate.FullName "x64\signtool.exe"
            if (Test-Path -LiteralPath $path) { return $path }
        }
    }
    throw "signtool.exe was not found in PATH or the Windows SDK."
}

function Sign-And-VerifyFile {
    param([string]$Path)

    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        & $script:SignToolPath sign /fd SHA256 /sha1 $script:SigningThumbprint /tr https://timestamp.digicert.com /td SHA256 /v $Path
        if ($LASTEXITCODE -ne 0) { throw "Code signing failed for $Path (exit code $LASTEXITCODE)." }
    }

    & $script:SignToolPath verify /pa /all /v $Path
    if ($LASTEXITCODE -ne 0) { throw "Authenticode verification failed for $Path (exit code $LASTEXITCODE)." }
}

function Sign-GeneratedBinaries {
    param([string]$Path)

    if (-not $script:SigningThumbprint) { return }
    $extensions = @(".exe", ".dll", ".pyd", ".msi")
    foreach ($file in Get-ChildItem -LiteralPath $Path -File -Recurse) {
        if ($extensions -contains $file.Extension.ToLowerInvariant()) {
            Sign-And-VerifyFile $file.FullName
        }
    }
}

function Remove-GeneratedDirectory {
    param([string]$Path, [string]$Parent, [string]$MarkerName)

    if (-not (Test-Path -LiteralPath $Path)) { return }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if ($resolved -ne (Get-CheckedChildPath $resolved $Parent)) {
        throw "Refusing to remove an unexpected directory: $resolved"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $resolved $MarkerName))) {
        throw "Refusing to replace an unrecognized directory: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

function Copy-CodeTree {
    param([string]$Name)

    $sourceRoot = (Resolve-Path -LiteralPath (Join-Path $repo $Name)).Path
    $sourcePrefix = $sourceRoot.TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar
    $targetRoot = Join-Path $portable $Name
    New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null
    $excluded = @("tests", "__pycache__", ".pytest_cache")
    foreach ($file in Get-ChildItem -LiteralPath $sourceRoot -File -Recurse -Force) {
        $fullFilePath = [System.IO.Path]::GetFullPath($file.FullName)
        if (-not $fullFilePath.StartsWith($sourcePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Source file is outside its expected code tree: $fullFilePath"
        }
        $relative = $fullFilePath.Substring($sourcePrefix.Length)
        $segments = $relative.Split([System.IO.Path]::DirectorySeparatorChar, [System.StringSplitOptions]::RemoveEmptyEntries)
        if ($segments | Where-Object { $excluded -contains $_ }) { continue }
        $destination = Join-Path $targetRoot $relative
        $null = Get-CheckedChildPath $destination $targetRoot
        $destinationDirectory = Split-Path -Parent $destination
        New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
    }
}

New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
New-Item -ItemType Directory -Path $runtimeResources -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $repo "dist") -Force | Out-Null

if ($signingRequired -and -not $signingThumbprint) {
    throw "This Windows package requires a code-signing certificate. Configure the GitHub Actions signing secrets before building."
}
if ($signingThumbprint) {
    $signingCertificate = Get-ChildItem Cert:\CurrentUser\My |
        Where-Object { $_.Thumbprint -eq $signingThumbprint -and $_.HasPrivateKey } |
        Select-Object -First 1
    if (-not $signingCertificate) {
        throw "The configured code-signing certificate is not installed in the current user's certificate store."
    }
    $script:SigningThumbprint = $signingThumbprint
    $script:SignToolPath = Get-SignToolPath
} else {
    Write-Warning "Building unsigned Windows files. Device Guard or another application-control policy may block them."
}

Remove-GeneratedDirectory $runtimeStaging $buildRoot "runtime-manifest.json"

$env:CARGO_NET_OFFLINE = "true"
$env:npm_config_offline = "true"
Invoke-Check "python" @(
    (Join-Path $repo "scripts\package_runtime.py"),
    "--output", $runtimeStaging,
    "--requirements", (Join-Path $repo "requirements-runtime.txt"),
    "--requirements", (Join-Path $repo "docs\requirements-schemathesis.txt")
)

$stagedPython = Join-Path $runtimeStaging "python.exe"
& $stagedPython --version
if ($LASTEXITCODE -ne 0) { throw "Bundled Python failed to start (exit code $LASTEXITCODE)" }
& $stagedPython -c "import requests, openpyxl, jsonschema, yaml, psycopg2, influxdb, rstr, schemathesis; print('Portable runtime imports passed')"
if ($LASTEXITCODE -ne 0) { throw "A bundled runtime dependency failed to import (exit code $LASTEXITCODE)" }

# Replace only generated contents inside the exact runtime resource directory.
$runtimeRoot = (Resolve-Path -LiteralPath $runtimeResources).Path
foreach ($entry in Get-ChildItem -LiteralPath $runtimeRoot -Force) {
    if ($entry.Name -eq ".gitkeep") { continue }
    $resolvedEntry = (Resolve-Path -LiteralPath $entry.FullName).Path
    $null = Get-CheckedChildPath $resolvedEntry $runtimeRoot
    Remove-Item -LiteralPath $resolvedEntry -Recurse -Force
}
foreach ($entry in Get-ChildItem -LiteralPath $runtimeStaging -Force) {
    Copy-Item -LiteralPath $entry.FullName -Destination $runtimeResources -Recurse -Force
}
Sign-GeneratedBinaries $runtimeResources

Push-Location (Join-Path $repo "gui-tauri")
$tauriSigningConfig = $null
try {
    $tauriBuildArguments = @("run", "tauri", "--", "build")
    if ($signingThumbprint) {
        $tauriSigningConfig = Join-Path $env:TEMP "openapi-test-tool-tauri-signing-$PID.json"
        $tauriConfig = [ordered]@{
            bundle = [ordered]@{
                windows = [ordered]@{
                    certificateThumbprint = $signingThumbprint
                    digestAlgorithm = "sha256"
                    timestampUrl = "https://timestamp.digicert.com"
                }
            }
        }
        $utf8WithoutBom = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllText($tauriSigningConfig, ($tauriConfig | ConvertTo-Json -Depth 8), $utf8WithoutBom)
        $tauriBuildArguments += @("--config", $tauriSigningConfig)
    }
    Invoke-Check "npm" $tauriBuildArguments
} finally {
    Pop-Location
    if ($tauriSigningConfig -and (Test-Path -LiteralPath $tauriSigningConfig)) {
        Remove-Item -LiteralPath $tauriSigningConfig -Force
    }
}

$portableMarker = Join-Path $portable "portable-manifest.json"
Remove-GeneratedDirectory $portable $repo "portable-manifest.json"
New-Item -ItemType Directory -Path $portable -Force | Out-Null
$buildingManifest = [ordered]@{
    generatedBy = "api-tester/scripts/package-portable.ps1"
    state = "building"
}
$buildingManifest | ConvertTo-Json | Set-Content -LiteralPath $portableMarker -Encoding utf8
$releaseExe = Join-Path $repo "gui-tauri\src-tauri\target\release\gui-tauri.exe"
if (-not (Test-Path -LiteralPath $releaseExe)) { throw "Tauri executable was not produced: $releaseExe" }
Copy-Item -LiteralPath $releaseExe -Destination (Join-Path $portable "openapi-test-tool.exe") -Force

foreach ($name in @("src", "runner", "workflow")) { Copy-CodeTree $name }
$guiTarget = Join-Path $portable "gui"
New-Item -ItemType Directory -Path $guiTarget -Force | Out-Null
foreach ($file in @("tauri_bridge.py", "validators.py")) {
    Copy-Item -LiteralPath (Join-Path $repo "gui\$file") -Destination (Join-Path $guiTarget $file) -Force
}
$portableRuntimeDirectory = Join-Path $portable "runtime\python"
New-Item -ItemType Directory -Path $portableRuntimeDirectory -Force | Out-Null
foreach ($entry in Get-ChildItem -LiteralPath $runtimeResources -Force) {
    Copy-Item -LiteralPath $entry.FullName -Destination $portableRuntimeDirectory -Recurse -Force
}

$tauriConfig = Get-Content -LiteralPath (Join-Path $repo "gui-tauri\src-tauri\tauri.conf.json") -Raw | ConvertFrom-Json
$runtimeManifest = Get-Content -LiteralPath (Join-Path $runtimeResources "runtime-manifest.json") -Raw | ConvertFrom-Json
$manifest = [ordered]@{
    generatedBy = "api-tester/scripts/package-portable.ps1"
    state = "complete"
    productName = $tauriConfig.productName
    version = $tauriConfig.version
    pythonVersion = $runtimeManifest.pythonVersion
    packages = $runtimeManifest.packages
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $portableMarker -Encoding utf8

New-Item -ItemType Directory -Path $installerOutput -Force | Out-Null
$bundleRoot = Join-Path $repo "gui-tauri\src-tauri\target\release\bundle"
$installers = @(
    Get-ChildItem -LiteralPath (Join-Path $bundleRoot "msi") -Filter "openapi-test-tool_*.msi" -File -ErrorAction Stop
    Get-ChildItem -LiteralPath (Join-Path $bundleRoot "nsis") -Filter "openapi-test-tool_*-setup.exe" -File -ErrorAction Stop
)
if ($installers.Count -ne 2) { throw "Expected one MSI and one NSIS installer; found $($installers.Count)" }
foreach ($installer in $installers) {
    Copy-Item -LiteralPath $installer.FullName -Destination (Join-Path $installerOutput $installer.Name) -Force
}
Sign-GeneratedBinaries $portable
Sign-GeneratedBinaries $installerOutput

if ($signingRequired) {
    foreach ($file in Get-ChildItem -LiteralPath $installerOutput -File) {
        if ((Get-AuthenticodeSignature -LiteralPath $file.FullName).Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
            throw "Windows installer is not Authenticode-signed: $($file.FullName)"
        }
    }
    $mainExecutable = Join-Path $portable "openapi-test-tool.exe"
    if ((Get-AuthenticodeSignature -LiteralPath $mainExecutable).Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw "Portable application executable is not Authenticode-signed: $mainExecutable"
    }
}

$resolvedStaging = (Resolve-Path -LiteralPath $runtimeStaging).Path
$null = Get-CheckedChildPath $resolvedStaging $buildRoot
if (-not (Test-Path -LiteralPath (Join-Path $resolvedStaging "runtime-manifest.json"))) {
    throw "Refusing to remove unrecognized runtime staging directory: $resolvedStaging"
}
Remove-Item -LiteralPath $resolvedStaging -Recurse -Force
Write-Host "Portable application: $portable"
Write-Host "Windows installers: $installerOutput"
