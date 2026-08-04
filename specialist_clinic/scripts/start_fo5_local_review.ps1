param(
    [string]$Database = "specialist.db",
    [switch]$SkipPrepare
)

$ErrorActionPreference = "Stop"
$SpecialistRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $SpecialistRoot ".venv\Scripts\python.exe"

Push-Location $SpecialistRoot
try {
    if (-not (Test-Path -LiteralPath $Python)) {
        throw "Python environment not found: $Python. Create .venv and install requirements first."
    }

    $DatabasePath = [System.IO.Path]::GetFullPath((Join-Path $SpecialistRoot $Database))
    if (-not (Test-Path -LiteralPath $DatabasePath)) {
        throw "Review database not found: $DatabasePath"
    }

    Write-Host "FOUX-V1 FO-5 local owner UX review" -ForegroundColor Cyan
    Write-Host "TEST_ONLY / SYNTHETIC_OR_RESETTABLE data is required." -ForegroundColor Yellow
    Write-Host "Acceptance Issue: #107"
    Write-Host "Reviewed merge: 94aa2c3eaf335a46e8911a5ac9984e1ff6f4b852"

    $BackupDir = Join-Path $SpecialistRoot "backups"
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    $Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $BackupPath = Join-Path $BackupDir "fo5-local-review-$Stamp.db"
    Copy-Item -LiteralPath $DatabasePath -Destination $BackupPath -Force
    Write-Host "Backup created: $BackupPath" -ForegroundColor Green

    $FlagNames = @(
        "FOLLOWUP_EPISODES_ENABLED",
        "FOLLOWUP_PROJECTION_SHADOW",
        "FOLLOWUP_UNIFIED_WORKLIST_READONLY",
        "FOLLOWUP_UNIFIED_WORKLIST_ACTIONS",
        "FOLLOWUP_AUTO_ROUTING",
        "FOLLOWUP_STRUCTURED_CONTACT"
    )
    $BlockedFlagNames = @(
        "FOLLOWUP_SMS_AUTO_GUARDED",
        "FOLLOWUP_APPOINTMENT_SYNC",
        "FOLLOWUP_EVIDENCE_ASSIST",
        "FOLLOWUP_AUTOMATION_HEALTH"
    )

    $PreviousValues = @{}
    foreach ($Name in ($FlagNames + $BlockedFlagNames)) {
        $PreviousValues[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
    }

    try {
        foreach ($Name in $FlagNames) {
            [Environment]::SetEnvironmentVariable($Name, "1", "Process")
        }
        foreach ($Name in $BlockedFlagNames) {
            [Environment]::SetEnvironmentVariable($Name, "0", "Process")
        }

        [Environment]::SetEnvironmentVariable(
            "SPECIALIST_DATABASE_PATH",
            $DatabasePath,
            "Process"
        )

        if (-not $SkipPrepare) {
            Write-Host "Preparing Episodes and Unified projection explicitly..." -ForegroundColor Cyan
            & $Python "scripts\prepare_seeded_followup_view.py" --database $DatabasePath
            if ($LASTEXITCODE -ne 0) {
                throw "FO-5 review preparation failed with exit code $LASTEXITCODE"
            }
        }

        Write-Host "Starting Specialist Clinic with FO-1..FO-5 review flags." -ForegroundColor Green
        Write-Host "FO-6+ flags remain OFF. Close the server to restore prior environment values."
        & $Python "start.py"
        if ($LASTEXITCODE -ne 0) {
            throw "Specialist Clinic exited with code $LASTEXITCODE"
        }
    }
    finally {
        foreach ($Name in ($FlagNames + $BlockedFlagNames)) {
            [Environment]::SetEnvironmentVariable(
                $Name,
                $PreviousValues[$Name],
                "Process"
            )
        }
        [Environment]::SetEnvironmentVariable(
            "SPECIALIST_DATABASE_PATH",
            $null,
            "Process"
        )
        Write-Host "Previous process-level feature flag values restored." -ForegroundColor DarkGray
    }
}
finally {
    Pop-Location
}
