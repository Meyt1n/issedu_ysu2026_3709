# HCT-408 恢复脚本（PowerShell）
# 用途：从备份目录恢复 MySQL dump 并验证健康检查

param(
    [Parameter(Mandatory=$true)]
    [string]$BackupId,
    [string]$BackupDir = "backups",
    [string]$ComposeProjectName = "",
    [switch]$SkipHealth = $false,
    [switch]$Force = $false
)

$ErrorActionPreference = "Stop"
$backupPath = Join-Path $BackupDir $BackupId

if (-not (Test-Path $backupPath)) {
    Write-Error "Backup not found: $backupPath"
    exit 1
}

if (-not $Force) {
    Write-Warning "This will DESTROY the current database and replace it with backup '$BackupId'."
    Write-Warning "Current data will be LOST. Use -Force to suppress this warning."
    $confirm = Read-Host "Type YES to proceed"
    if ($confirm -ne "YES") {
        Write-Host "Aborted."
        exit 0
    }
}

Write-Host "[HCT-408 restore] starting from backup_id=$BackupId"

# --- Version manifest check ---
$versionFile = Join-Path $backupPath "version_manifest.json"
if (Test-Path $versionFile) {
    $manifest = Get-Content $versionFile -Raw | ConvertFrom-Json
    Write-Host "[HCT-408 restore] backup metadata: commit=$($manifest.git_commit_short), migration_head=$($manifest.migration_head)"
} else {
    Write-Warning "[HCT-408 restore] no version_manifest.json found, proceeding without metadata"
}

# --- MySQL restore ---
$dumpFile = Join-Path $backupPath "mysqldump.sql.gz"
if (-not (Test-Path $dumpFile)) {
    Write-Error "mysqldump not found in backup: $dumpFile"
    exit 1
}

Write-Host "[HCT-408 restore] restoring MySQL from $dumpFile ..."
$composeArgs = @("-T")
if ($ComposeProjectName) {
    $composeArgs = @("-T", "-p", $ComposeProjectName)
}
$MYSQL_PASSWORD = if ($env:MYSQL_ROOT_PASSWORD) { $env:MYSQL_ROOT_PASSWORD } else { "change-me-root" }
$MYSQL_DATABASE = if ($env:MYSQL_DATABASE) { $env:MYSQL_DATABASE } else { "homecare" }
$env:MYSQL_PWD = $MYSQL_PASSWORD

try {
    # Drop and recreate to ensure clean state
    docker compose exec $composeArgs db mysql -u root -e "DROP DATABASE IF EXISTS ``$MYSQL_DATABASE``; CREATE DATABASE ``$MYSQL_DATABASE`` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

    # Restore dump
    $mysqlArgs = @("-T")
    if ($ComposeProjectName) { $mysqlArgs = @("-T", "-p", $ComposeProjectName) }
    Get-Content $dumpFile -Raw -AsByteStream | & {
        $inputBytes = $input
        if ($dumpFile.EndsWith('.gz')) {
            $memStream = New-Object System.IO.MemoryStream(, $inputBytes)
            $gzipStream = New-Object System.IO.Compression.GzipStream($memStream, [System.IO.Compression.CompressionMode]::Decompress)
            $reader = New-Object System.IO.StreamReader($gzipStream)
            $sql = $reader.ReadToEnd()
            $reader.Close()
        } else {
            $sql = [System.Text.Encoding]::UTF8.GetString($inputBytes)
        }
        $sql | docker compose exec $mysqlArgs db mysql -u root "$MYSQL_DATABASE"
    }

    Write-Host "[HCT-408 restore] MySQL restore complete"
} finally {
    $env:MYSQL_PWD = $null
}

# --- Run migrations ---
Write-Host "[HCT-408 restore] running Alembic migrations ..."
$apiArgs = @("exec", "-T", "api")
if ($ComposeProjectName) {
    $apiArgs = @("-p", $ComposeProjectName) + $apiArgs
}
docker compose $apiArgs uv run alembic upgrade head 2>&1 | ForEach-Object { Write-Host "  $_" }

# --- Restore file references ---
$fileManifest = Join-Path $backupPath "file_manifest.json"
if (Test-Path $fileManifest) {
    Write-Host "[HCT-408 restore] file manifest found ($fileManifest), verify file references manually if needed."
}

# --- Health check ---
if (-not $SkipHealth) {
    Write-Host "[HCT-408 restore] running health checks ..."
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $healthScript = Join-Path $scriptDir "check_http_health.py"
    if (Test-Path $healthScript) {
        uv run python $healthScript 2>&1 | ForEach-Object { Write-Host "  $_" }
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "[HCT-408 restore] health check returned non-zero exit code: $LASTEXITCODE"
        } else {
            Write-Host "[HCT-408 restore] all health checks passed"
        }
    } else {
        Write-Warning "[HCT-408 restore] health check script not found at $healthScript"
    }
}

Write-Host "[HCT-408 restore] complete. backup_id=$BackupId restored successfully."
Write-Host "[HCT-408 restore] verify with: uv run python scripts/check_http_health.py"
