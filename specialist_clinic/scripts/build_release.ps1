[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pyinstaller = Join-Path $projectRoot ".venv\Scripts\pyinstaller.exe"
$dist = Join-Path $projectRoot "dist"
$build = Join-Path $projectRoot "build"
$release = Join-Path $projectRoot "release"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Virtual environment Python was not found: $python"
}

Push-Location $projectRoot
try {
    if (-not $SkipInstall) {
        & $python -m pip install -r requirements-build.lock
        if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    }

    & $python start.py self-test
    if ($LASTEXITCODE -ne 0) { throw "Source self-test failed." }

    if (-not $SkipTests) {
        & $python -m pytest tests -q --tb=short
        if ($LASTEXITCODE -ne 0) { throw "Regression suite failed." }
    }

    foreach ($candidate in @($dist, $build, $release)) {
        $resolvedParent = (Resolve-Path (Split-Path $candidate -Parent)).Path
        if ($resolvedParent -ne $projectRoot) {
            throw "Unsafe build cleanup target: $candidate"
        }
        if (Test-Path -LiteralPath $candidate) {
            Remove-Item -LiteralPath $candidate -Recurse -Force
        }
    }

    & $pyinstaller --noconfirm --clean SpecialistClinic.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

    $exe = Join-Path $dist "SpecialistClinic.exe"
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
        throw "Frozen executable was not produced."
    }
    & $exe self-test
    if ($LASTEXITCODE -ne 0) { throw "Frozen executable self-test failed." }

    New-Item -ItemType Directory -Path $release | Out-Null
    $zip = Join-Path $release "SpecialistClinic-win-x64.zip"
    Compress-Archive -LiteralPath $exe -DestinationPath $zip
    $hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    $hashFile = Join-Path $release "SpecialistClinic-win-x64.zip.sha256"
    Set-Content -LiteralPath $hashFile -Encoding ascii -NoNewline `
        -Value "$hash  SpecialistClinic-win-x64.zip"
    Write-Host "Release artifact: $zip"
    Write-Host "SHA-256: $hash"
}
finally {
    Pop-Location
}
