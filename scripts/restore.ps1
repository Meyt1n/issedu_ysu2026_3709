# HCT-408 restore: validate first, then restore database and verify references.

param(
    [Parameter(Mandatory=$true)]
    [string]$BackupId,
    [string]$BackupDir = "backups",
    [string]$ComposeProjectName = "",
    [string]$FileRoot = "",
    [switch]$SkipHealth = $false,
    [switch]$Force = $false
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$backupPath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) (Join-Path $BackupDir $BackupId)))

if (-not (Test-Path -LiteralPath $backupPath)) { throw "Backup not found: $backupPath" }

$validator = Join-Path $scriptDir "hct408_validate_backup.py"
$validationReport = Join-Path $backupPath "validation-before-restore.json"
if (-not (Test-Path -LiteralPath $validator)) { throw "HCT-408 validator not found: $validator" }
Write-Host "[HCT-408 restore] validating backup before any destructive operation ..."
& uv run python $validator --backup $backupPath --output $validationReport
if ($LASTEXITCODE -ne 0) { throw "Backup validation failed. Database was not modified. See $validationReport" }

$versionFile = Join-Path $backupPath "version_manifest.json"
$manifest = Get-Content -LiteralPath $versionFile -Raw | ConvertFrom-Json
Write-Host "[HCT-408 restore] backup metadata: commit=$($manifest.git_commit_short), migration_head=$($manifest.migration_head)"

if (-not $Force) {
    Write-Warning "This will DESTROY the current database and replace it with backup '$BackupId'."
    Write-Warning "Current data will be LOST. Use -Force to suppress this warning."
    $confirm = Read-Host "Type YES to proceed"
    if ($confirm -ne "YES") { Write-Host "Aborted."; exit 0 }
}

$composeArgs = @("-T")
if ($ComposeProjectName) { $composeArgs = @("-p", $ComposeProjectName) + $composeArgs }
$mysqlPassword = if ($env:MYSQL_ROOT_PASSWORD) { $env:MYSQL_ROOT_PASSWORD } else { "change-me-root" }
$mysqlDatabase = if ($env:MYSQL_DATABASE) { $env:MYSQL_DATABASE } else { "homecare" }
$dumpFile = Join-Path $backupPath "mysqldump.sql.gz"

Write-Host "[HCT-408 restore] restoring MySQL from $dumpFile ..."
$previousMysqlPwd = $env:MYSQL_PWD
$env:MYSQL_PWD = $mysqlPassword
try {
    docker compose exec $composeArgs db mysql -u root -e "DROP DATABASE IF EXISTS ``$mysqlDatabase``; CREATE DATABASE ``$mysqlDatabase`` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    if ($LASTEXITCODE -ne 0) { throw "Failed to recreate database." }

    $dumpBytes = Get-Content -LiteralPath $dumpFile -Raw -AsByteStream
    $memStream = New-Object System.IO.MemoryStream(, $dumpBytes)
    $gzipStream = New-Object System.IO.Compression.GzipStream($memStream, [System.IO.Compression.CompressionMode]::Decompress)
    $reader = New-Object System.IO.StreamReader($gzipStream)
    try {
        $sql = $reader.ReadToEnd()
    } finally {
        $reader.Close()
        $gzipStream.Close()
        $memStream.Close()
    }
    $sql | docker compose exec $composeArgs db mysql -u root $mysqlDatabase
    if ($LASTEXITCODE -ne 0) { throw "MySQL dump import failed." }
    Write-Host "[HCT-408 restore] MySQL restore complete"
} finally {
    $env:MYSQL_PWD = $previousMysqlPwd
}

$apiArgs = @("exec", "-T", "api")
if ($ComposeProjectName) { $apiArgs = @("-p", $ComposeProjectName) + $apiArgs }
Write-Host "[HCT-408 restore] running Alembic migrations ..."
docker compose $apiArgs uv run alembic upgrade head 2>&1 | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -ne 0) { throw "Alembic migration failed after restore." }

$fileManifest = Join-Path $backupPath "file_manifest.json"
if (Test-Path -LiteralPath $fileManifest) {
    $manifestFiles = @((Get-Content -LiteralPath $fileManifest -Raw | ConvertFrom-Json).files)
    $fileRootValue = if ($FileRoot) { $FileRoot } elseif ($env:FILE_ROOT) { $env:FILE_ROOT } else { "./src/runtime/data/files" }
    if ($manifestFiles.Count -gt 0) {
        Write-Host "[HCT-408 restore] restoring FILE_ROOT from files.tar.gz into $fileRootValue ..."
        & uv run python (Join-Path $scriptDir "hct408_file_archive.py") restore --backup $backupPath --file-root $fileRootValue --wipe-existing
        if ($LASTEXITCODE -ne 0) { throw "FILE_ROOT archive restore failed." }
        Write-Host "[HCT-408 restore] validating file references under $fileRootValue ..."
        & uv run python $validator --backup $backupPath --file-root $fileRootValue
        if ($LASTEXITCODE -ne 0) { throw "File reference validation failed after restore." }
    } else {
        Write-Host "[HCT-408 restore] file manifest contains no file references."
    }
}

if (-not $SkipHealth) {
    $healthScript = Join-Path $scriptDir "check_http_health.py"
    if (-not (Test-Path -LiteralPath $healthScript)) { throw "Health check script not found: $healthScript" }
    Write-Host "[HCT-408 restore] running health checks ..."
    uv run python $healthScript 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) { throw "Health check returned non-zero exit code: $LASTEXITCODE" }
    Write-Host "[HCT-408 restore] all health checks passed"
}

Write-Host "[HCT-408 restore] complete. backup_id=$BackupId restored successfully."
