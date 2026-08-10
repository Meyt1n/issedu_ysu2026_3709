# HCT-408 备份恢复脚本（PowerShell）
# 用途：从运行中的 Docker Compose 环境导出数据库、文件清单和版本组合清单

param(
    [string]$BackupDir = "backups",
    [string]$ComposeProjectName = "",
    [switch]$SkipMysql = $false,
    [switch]$SkipFiles = $false,
    [switch]$SkipVersion = $false
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}
$backupName = "hct-backup-$timestamp"
$backupPath = Join-Path $BackupDir $backupName
New-Item -ItemType Directory -Path $backupPath -Force | Out-Null

Write-Host "[HCT-408 backup] backup_id=$backupName backup_path=$backupPath"

# --- MySQL dump ---
if (-not $SkipMysql) {
    Write-Host "[HCT-408 backup] dumping MySQL ..."
    $composeArgs = @("exec", "-T", "db")
    if ($ComposeProjectName) {
        $composeArgs = @("-p", $ComposeProjectName) + $composeArgs
    }

    $dumpFile = Join-Path $backupPath "mysqldump.sql.gz"
    $MYSQL_PASSWORD = if ($env:MYSQL_ROOT_PASSWORD) { $env:MYSQL_ROOT_PASSWORD } else { "change-me-root" }
    $MYSQL_DATABASE = if ($env:MYSQL_DATABASE) { $env:MYSQL_DATABASE } else { "homecare" }

    $env:MYSQL_PWD = $MYSQL_PASSWORD
    try {
        docker compose $composeArgs mysqldump `
            -u root `
            --single-transaction `
            --routines `
            --triggers `
            --events `
            --set-gtid-purged=OFF `
            "$MYSQL_DATABASE" 2>&1 | `
            & { gzip -c 2>$null } > $dumpFile
        Write-Host "[HCT-408 backup] mysqldump written: $dumpFile ($((Get-Item $dumpFile).Length) bytes)"
    } finally {
        $env:MYSQL_PWD = $null
    }
}

# --- File inventory ---
if (-not $SkipFiles) {
    Write-Host "[HCT-408 backup] collecting file inventory ..."
    $fileRoot = if ($env:FILE_ROOT) { $env:FILE_ROOT } else { "./data/files" }
    $fileManifest = Join-Path $backupPath "file_manifest.json"

    if (Test-Path $fileRoot) {
        $files = Get-ChildItem -Path $fileRoot -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
            $sha = (Get-FileHash -Path $_.FullName -Algorithm SHA256).Hash
            @{
                relative_path = $_.FullName.Replace((Resolve-Path $fileRoot).Path + "\", "").Replace("\", "/")
                size          = $_.Length
                sha256        = $sha
                modified_utc  = $_.LastWriteTimeUtc.ToString("o")
            }
        }
        $manifest = @{
            source_root    = (Resolve-Path $fileRoot).Path
            total_files    = @($files).Count
            total_bytes    = ($files | Measure-Object -Property size -Sum).Sum
            collected_utc  = (Get-Date).ToUniversalTime().ToString("o")
            files          = @($files)
        }
        $manifest | ConvertTo-Json -Depth 4 | Out-File -FilePath $fileManifest -Encoding utf8
        Write-Host "[HCT-408 backup] file manifest written: $fileManifest ($($manifest.total_files) files, $($manifest.total_bytes) bytes)"
    } else {
        Write-Host "[HCT-408 backup] FILE_ROOT not found, skipping file inventory"
    }
}

# --- Version manifest ---
if (-not $SkipVersion) {
    Write-Host "[HCT-408 backup] collecting version manifest ..."
    $versionFile = Join-Path $backupPath "version_manifest.json"

    $gitSha = try { (git rev-parse HEAD) } catch { "unknown" }
    $gitShort = try { (git rev-parse --short HEAD) } catch { "unknown" }

    $composeArgs = @("exec", "-T", "db")
    if ($ComposeProjectName) {
        $composeArgs = @("-p", $ComposeProjectName) + $composeArgs
    }
    $MYSQL_PASSWORD = if ($env:MYSQL_ROOT_PASSWORD) { $env:MYSQL_ROOT_PASSWORD } else { "change-me-root" }
    $env:MYSQL_PWD = $MYSQL_PASSWORD
    try {
        $migrationHead = docker compose $composeArgs mysql `
            -u root -N -e "SELECT version_num FROM alembic_version" 2>&1 | ForEach-Object { $_.Trim() }
    } finally {
        $env:MYSQL_PWD = $null
    }

    $versionManifest = @{
        backup_id       = $backupName
        timestamp_utc   = (Get-Date).ToUniversalTime().ToString("o")
        git_commit      = $gitSha
        git_commit_short = $gitShort
        migration_head  = $migrationHead
        compose_profile = $env:COMPOSE_PROFILE
        mysql_image     = "mysql:8.4"
        ollama_model    = if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { "unavailable" }
        ruleset_version = if ($env:RULESET_VERSION) { $env:RULESET_VERSION } else { "unknown" }
        knowledge_version = if ($env:KNOWLEDGE_VERSION) { $env:KNOWLEDGE_VERSION } else { "unknown" }
        note            = "Secrets and passwords are NEVER included in this manifest."
    }
    $versionManifest | ConvertTo-Json -Depth 2 | Out-File -FilePath $versionFile -Encoding utf8
    Write-Host "[HCT-408 backup] version manifest written: $versionFile"
}

Write-Host "[HCT-408 backup] complete. backup_id=$backupName"
Write-Host "[HCT-408 backup] backup contents:"
Get-ChildItem -Path $backupPath -Recurse | ForEach-Object {
    $size = if ($_.PSIsContainer) { "-" } else { "$($_.Length) bytes" }
    Write-Host "  $($_.Name)`t$size"
}
