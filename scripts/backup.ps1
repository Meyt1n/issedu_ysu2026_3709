# HCT-408 full backup: MySQL dump, file inventory, and version metadata.

param(
    [string]$BackupDir = "backups",
    [string]$ComposeProjectName = "",
    [switch]$SkipMysql = $false,
    [switch]$SkipFiles = $false,
    [switch]$SkipVersion = $false,
    [switch]$SkipValidation = $false
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupRoot = [System.IO.Path]::GetFullPath((Join-Path (Get-Location) $BackupDir))
$backupName = "hct-backup-$timestamp"
$backupPath = Join-Path $backupRoot $backupName

New-Item -ItemType Directory -Path $backupPath -Force | Out-Null
Write-Host "[HCT-408 backup] backup_id=$backupName backup_path=$backupPath"

$composeArgs = @("exec", "-T", "db")
if ($ComposeProjectName) { $composeArgs = @("-p", $ComposeProjectName) + $composeArgs }
$mysqlPassword = if ($env:MYSQL_ROOT_PASSWORD) { $env:MYSQL_ROOT_PASSWORD } else { "change-me-root" }
$mysqlDatabase = if ($env:MYSQL_DATABASE) { $env:MYSQL_DATABASE } else { "homecare" }

if (-not $SkipMysql) {
    Write-Host "[HCT-408 backup] dumping MySQL ..."
    $dumpFile = Join-Path $backupPath "mysqldump.sql.gz"
    $dumpError = Join-Path $backupPath "mysqldump.stderr.log"
    $previousMysqlPwd = $env:MYSQL_PWD
    $env:MYSQL_PWD = $mysqlPassword
    try {
        docker compose $composeArgs mysqldump `
            -u root `
            --single-transaction `
            --routines `
            --triggers `
            --events `
            --set-gtid-purged=OFF `
            "$mysqlDatabase" 2> $dumpError | gzip -c > $dumpFile
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $dumpFile) -or (Get-Item -LiteralPath $dumpFile).Length -eq 0) {
            throw "mysqldump failed or produced an empty archive"
        }
        Write-Host "[HCT-408 backup] mysqldump written: $dumpFile ($((Get-Item -LiteralPath $dumpFile).Length) bytes)"
    } finally {
        $env:MYSQL_PWD = $previousMysqlPwd
    }
    if (Test-Path -LiteralPath $dumpError -and (Get-Item -LiteralPath $dumpError).Length -eq 0) {
        Remove-Item -LiteralPath $dumpError -Force
    }
}

$fileRoot = if ($env:FILE_ROOT) { $env:FILE_ROOT } else { "./data/files" }
if (-not $SkipFiles) {
    Write-Host "[HCT-408 backup] collecting file inventory ..."
    if (-not (Test-Path -LiteralPath $fileRoot)) {
        throw "FILE_ROOT not found: $fileRoot. Use -SkipFiles only for a database-only backup."
    }
    $resolvedFileRoot = (Resolve-Path -LiteralPath $fileRoot).Path
    $files = @(Get-ChildItem -LiteralPath $resolvedFileRoot -Recurse -File -ErrorAction Stop | ForEach-Object {
        $relative = $_.FullName.Substring($resolvedFileRoot.Length).TrimStart("\", "/").Replace("\", "/")
        [ordered]@{
            relative_path = $relative
            size = [int64]$_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            modified_utc = $_.LastWriteTimeUtc.ToString("o")
        }
    })
    $totalBytes = if ($files.Count -eq 0) { [int64]0 } else { [int64](($files | Measure-Object -Property size -Sum).Sum) }
    $fileManifest = [ordered]@{
        source_root = $resolvedFileRoot
        total_files = $files.Count
        total_bytes = $totalBytes
        collected_utc = (Get-Date).ToUniversalTime().ToString("o")
        files = $files
    }
    $fileManifest | ConvertTo-Json -Depth 6 | Out-File -LiteralPath (Join-Path $backupPath "file_manifest.json") -Encoding utf8
    Write-Host "[HCT-408 backup] file manifest written ($($files.Count) files, $totalBytes bytes)"
}

$skipRoot = Join-Path $fileRoot "backup-skip"
if (Test-Path -LiteralPath $skipRoot) {
    Copy-Item -LiteralPath $skipRoot -Destination (Join-Path $backupPath "backup-skip") -Recurse -Force
    Write-Host "[HCT-408 backup] copied deletion skip markers"
}

if (-not $SkipVersion) {
    Write-Host "[HCT-408 backup] collecting version manifest ..."
    $gitSha = try { (git rev-parse HEAD).Trim() } catch { "unknown" }
    $gitShort = try { (git rev-parse --short HEAD).Trim() } catch { "unknown" }

    $previousMysqlPwd = $env:MYSQL_PWD
    $env:MYSQL_PWD = $mysqlPassword
    try {
        $migrationHead = @(docker compose $composeArgs mysql -u root -N -e "SELECT version_num FROM alembic_version" 2>&1 | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ }) | Select-Object -Last 1
    } finally {
        $env:MYSQL_PWD = $previousMysqlPwd
    }
    if (-not $migrationHead) { $migrationHead = "unknown" }

    $configHashes = [ordered]@{}
    foreach ($configPath in @("docker-compose.yml", ".env.example")) {
        $fullConfigPath = Join-Path (Get-Location) $configPath
        if (Test-Path -LiteralPath $fullConfigPath) {
            $configHashes[$configPath] = (Get-FileHash -LiteralPath $fullConfigPath -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }

    $versionManifest = [ordered]@{
        backup_id = $backupName
        timestamp_utc = (Get-Date).ToUniversalTime().ToString("o")
        git_commit = $gitSha
        git_commit_short = $gitShort
        migration_head = $migrationHead
        compose_profile = if ($env:COMPOSE_PROFILE) { $env:COMPOSE_PROFILE } else { "unknown" }
        mysql_image = "mysql:8.4"
        ollama_model = if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { "unavailable" }
        ruleset_version = if ($env:RULESET_VERSION) { $env:RULESET_VERSION } else { "unknown" }
        knowledge_version = if ($env:KNOWLEDGE_VERSION) { $env:KNOWLEDGE_VERSION } else { "unknown" }
        config_hashes = $configHashes
        note = "Credential material is intentionally excluded from this manifest."
    }
    $versionManifest | ConvertTo-Json -Depth 6 | Out-File -LiteralPath (Join-Path $backupPath "version_manifest.json") -Encoding utf8
}

if (-not $SkipValidation -and -not $SkipMysql -and -not $SkipFiles -and -not $SkipVersion) {
    $validator = Join-Path $scriptDir "hct408_validate_backup.py"
    if (-not (Test-Path -LiteralPath $validator)) { throw "HCT-408 validator not found: $validator" }
    Write-Host "[HCT-408 backup] validating backup manifest ..."
    & uv run python $validator --backup $backupPath
    if ($LASTEXITCODE -ne 0) { throw "Backup validation failed; the backup is not safe to restore." }
}

Write-Host "[HCT-408 backup] complete. backup_id=$backupName"
Get-ChildItem -LiteralPath $backupPath -Recurse | ForEach-Object {
    $size = if ($_.PSIsContainer) { "-" } else { "$($_.Length) bytes" }
    Write-Host "  $($_.Name)`t$size"
}
