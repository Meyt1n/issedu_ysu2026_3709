[CmdletBinding()]
param(
    [string]$Model = "hct402-qlora-v5",
    [int]$MysqlPort = 3307,
    [int]$ApiPort = 8000,
    [int]$WebPort = 5173,
    [string]$ActorId = "demo-parent,parent-1",
    [string]$VisionWorkerPython = "",
    [switch]$IncludeVisionWorker,
    [switch]$Visible
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$LogRoot = Join-Path $RepoRoot "tmp\demo-artifacts\demo-logs"
$PidFile = Join-Path $LogRoot "demo-pids.json"
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null

function Require-Command {
    param([string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "Command not found: $Name. Install it and add it to PATH."
    }
    return $command.Source
}

function Invoke-External {
    param([string]$FilePath, [string[]]$Arguments)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $FilePath $($Arguments -join ' ')"
    }
}

function Test-Http {
    param([string]$Url)
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Wait-Http {
    param([string]$Url, [int]$TimeoutSeconds = 60)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Http $Url) {
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "Timed out waiting for service: $Url"
}

function Wait-ComposeServiceHealthy {
    param(
        [string]$DockerPath,
        [string]$Service,
        [int]$TimeoutSeconds = 120
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $containerId = (& $DockerPath compose ps -q $Service 2>$null | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($containerId)) {
            $status = (& $DockerPath inspect `
                --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" `
                $containerId 2>$null | Out-String).Trim()
            if ($LASTEXITCODE -eq 0 -and $status -eq "healthy") {
                return
            }
            if ($status -eq "exited" -or $status -eq "dead") {
                throw "Compose service '$Service' stopped before becoming healthy. Run: docker compose logs $Service"
            }
        }
        Start-Sleep -Seconds 2
    }
    throw "Timed out waiting for Compose service '$Service' to become healthy. Run: docker compose logs $Service"
}

function Invoke-ExternalWithRetry {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [int]$Attempts = 3,
        [int]$DelaySeconds = 3
    )
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        & $FilePath @Arguments
        if ($LASTEXITCODE -eq 0) {
            return
        }
        if ($attempt -lt $Attempts) {
            Write-Warning "Command failed on attempt $attempt/$Attempts; retrying in $DelaySeconds seconds..."
            Start-Sleep -Seconds $DelaySeconds
        }
    }
    throw "Command failed after $Attempts attempts: $FilePath $($Arguments -join ' ')"
}

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments
    )
    $stdout = Join-Path $LogRoot "$Name.out.log"
    $stderr = Join-Path $LogRoot "$Name.err.log"
    $params = @{
        FilePath = $FilePath
        ArgumentList = $Arguments
        WorkingDirectory = $RepoRoot
        PassThru = $true
    }
    if ($Visible) {
        $params["WindowStyle"] = "Normal"
    } else {
        $params["WindowStyle"] = "Hidden"
        $params["RedirectStandardOutput"] = $stdout
        $params["RedirectStandardError"] = $stderr
    }
    $process = Start-Process @params
    Write-Host "$Name started. PID=$($process.Id)"
    return [pscustomobject]@{
        Name = $Name
        PID = $process.Id
        Output = $stdout
        Error = $stderr
    }
}

$uv = Require-Command "uv"
$npm = Require-Command "npm.cmd"
$docker = Require-Command "docker"
$ollama = Require-Command "ollama"

$env:MYSQL_USER = "homecare"
$env:MYSQL_PASSWORD = "change-me"
$env:MYSQL_DATABASE = "homecare"
$env:DATABASE_URL = "mysql+pymysql://" + $env:MYSQL_USER + ":" + $env:MYSQL_PASSWORD + "@127.0.0.1:$MysqlPort/" + $env:MYSQL_DATABASE + "?charset=utf8mb4"
$env:MYSQL_PORT = "$MysqlPort"
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = $Model
$env:OLLAMA_TIMEOUT_SECONDS = "120"
$env:MASTER_DATA_APPROVED_VERSIONS = "demo-cn-en-v1"
$env:VISION_ADAPTER_SIGNING_KEY = "dev-only-change-me"
$env:HCT_ADAPTER_SIGNING_KEY = "dev-only-change-me"
$env:HCT_MASTER_DATA_VERSION = "demo-cn-en-v1"
$env:HCT_OCR_LANG = "ch"
$env:NO_PROXY = "127.0.0.1,localhost"
$env:HCT_API_PROXY = "http://127.0.0.1:$ApiPort"
$env:HCT_WEB_PORT = "$WebPort"
$env:PYTHONPATH = "$RepoRoot\src\api;$RepoRoot\src"

if ($IncludeVisionWorker) {
    if ([string]::IsNullOrWhiteSpace($VisionWorkerPython)) {
        $VisionWorkerPython = $env:HCT_VISION_WORKER_PYTHON
    }
    if ([string]::IsNullOrWhiteSpace($VisionWorkerPython) -or -not (Test-Path $VisionWorkerPython)) {
        throw "PaddleOCR Python was not found. Use -VisionWorkerPython to specify a real python.exe path."
    }
    $VisionWorkerPython = (Resolve-Path $VisionWorkerPython).Path
    $env:HCT_VISION_WORKER_PYTHON = $VisionWorkerPython
}

$portChecks = @(
    @{ Name = "API"; Port = $ApiPort },
    @{ Name = "Web"; Port = $WebPort }
)
foreach ($portCheck in $portChecks) {
    $occupied = Get-NetTCPConnection -State Listen -LocalPort $portCheck.Port -ErrorAction SilentlyContinue
    if ($occupied) {
        throw "$($portCheck.Name) port $($portCheck.Port) is already in use. Stop the existing Demo before starting again."
    }
}

Write-Host "Checking Ollama..."
$ollamaHealthy = Test-Http "http://127.0.0.1:11434/api/tags"
$managed = @()
if (-not $ollamaHealthy) {
    $env:OLLAMA_HOST = "127.0.0.1:11434"
    $managed += Start-ManagedProcess "ollama" $ollama @("serve")
    Wait-Http "http://127.0.0.1:11434/api/tags" 60
}

$tags = Invoke-RestMethod "http://127.0.0.1:11434/api/tags"
$modelNames = @($tags.models | ForEach-Object { $_.name })
$modelWithTag = "{0}:latest" -f $Model
if (($modelNames -notcontains $Model) -and ($modelNames -notcontains $modelWithTag)) {
    throw "Ollama model not found: $Model. Installed models: $($modelNames -join ', ')"
}
Write-Host "Ollama model: $Model"

Write-Host "Starting MySQL..."
Invoke-External $docker @("compose", "--profile", "basic", "up", "-d", "db")
Write-Host "Waiting for MySQL to become healthy..."
Wait-ComposeServiceHealthy $docker "db" 120

Write-Host "Running database migrations..."
Invoke-ExternalWithRetry $uv @("run", "alembic", "upgrade", "head") 3 3

Write-Host "Starting API..."
$managed += Start-ManagedProcess "api" $uv @(
    "run", "uvicorn", "app.main:app", "--app-dir", "src/api",
    "--host", "0.0.0.0", "--port", "$ApiPort"
)
Wait-Http "http://127.0.0.1:$ApiPort/health" 90

Write-Host "Starting outbox worker..."
$managed += Start-ManagedProcess "outbox-worker" $uv @(
    "run", "python", "-m", "app.outbox_worker", "--loop"
)

Write-Host "Starting care plan automation worker..."
$managed += Start-ManagedProcess "care-plan-worker" $uv @(
    "run", "python", "-m", "app.care_plan_worker", "--loop"
)

Write-Host "Starting web..."
$managed += Start-ManagedProcess "web" $npm @("run", "dev:web")
Wait-Http "http://127.0.0.1:$WebPort/health" 90

if ($IncludeVisionWorker) {
    Write-Host "Starting vision OCR worker..."
    $managed += Start-ManagedProcess "vision-worker" $VisionWorkerPython @(
        "scripts/vision_worker.py",
        "--api", "http://127.0.0.1:$ApiPort/api/v1",
        "--actors", $ActorId,
        "--interval", "5"
    )
}

$managed | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $PidFile -Encoding UTF8
Write-Host ""
Write-Host "HomeCare Twin Demo is running."
Write-Host "Web: http://127.0.0.1:$WebPort"
Write-Host "API: http://127.0.0.1:$ApiPort/docs"
Write-Host "Ollama: http://127.0.0.1:11434"
Write-Host "Logs: $LogRoot"
Write-Host "Stop: .\\scripts\\stop-demo.ps1"
