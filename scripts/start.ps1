[CmdletBinding()]
param(
    [ValidateSet("setup", "api", "web", "migrate", "check", "up", "health", "down")]
    [string]$Target = "api"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Warning "已从 .env.example 创建 .env；请在真实环境中替换开发密码。"
}

function Invoke-CheckedCommand {
    param([Parameter(Mandatory = $true)][scriptblock]$Command)

    $output = & $Command
    if ($LASTEXITCODE -ne 0) {
        $output | Write-Output
        throw "命令执行失败（exit=$LASTEXITCODE）：$Command"
    }
    return $output
}

function Get-ComposeServiceStatus {
    $rows = @(Invoke-CheckedCommand { docker compose ps --all --format json } | ConvertFrom-Json)
    if ($rows.Count -eq 0) {
        throw "没有找到 Compose 服务，请先执行 scripts/start.ps1 up。"
    }
    foreach ($service in @("db", "api", "web")) {
        if ($service -notin $rows.Service) {
            throw "Compose 服务 $service 不存在，请重新执行 scripts/start.ps1 up。"
        }
    }
    foreach ($row in $rows) {
        if ($row.State -ne "running" -or $row.Health -ne "healthy") {
            throw "Compose 服务 $($row.Service) 未健康：state=$($row.State), health=$($row.Health)"
        }
    }
}

function Test-HttpHealth {
    param(
        [Parameter(Mandatory = $true)][string]$Service,
        [Parameter(Mandatory = $true)][int]$ContainerPort,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $published = @(Invoke-CheckedCommand { docker compose port $Service $ContainerPort })[0]
    if (-not $published) {
        throw "无法定位 ${Service}:$ContainerPort 的宿主端口。"
    }
    $hostPort = ($published.Trim() -split ":")[-1]
    $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$hostPort$Path" -TimeoutSec 10
    if ($response.StatusCode -ne 200) {
        throw "$Service 健康检查返回 HTTP $($response.StatusCode)。"
    }
}

function Invoke-HealthCheck {
    Get-ComposeServiceStatus
    Test-HttpHealth -Service "api" -ContainerPort 8000 -Path "/health"
    Test-HttpHealth -Service "web" -ContainerPort 80 -Path "/health"
    Write-Host "API、Web、MySQL Compose 健康检查通过。"
}

switch ($Target) {
    "setup" {
        Invoke-CheckedCommand { uv sync --frozen }
        Invoke-CheckedCommand { npm ci }
        Write-Host "依赖已安装。"
    }
    "api" {
        Invoke-CheckedCommand { uv run alembic upgrade head }
        Invoke-CheckedCommand { uv run uvicorn app.main:app --app-dir src/api --reload --host 0.0.0.0 --port 8000 }
    }
    "web" {
        Invoke-CheckedCommand { npm run dev:web }
    }
    "migrate" {
        Invoke-CheckedCommand { uv run alembic upgrade head }
    }
    "check" {
        Invoke-CheckedCommand { uv run ruff check src/api src/ai scripts tests migrations }
        Invoke-CheckedCommand { uv run pytest }
        Invoke-CheckedCommand { npm run check:web }
        Invoke-CheckedCommand { npm run build:web }
        Invoke-CheckedCommand { docker compose config --quiet }
    }
    "up" {
        Invoke-CheckedCommand { docker compose up -d --build --wait --wait-timeout 60 }
        Invoke-HealthCheck
    }
    "health" {
        Invoke-HealthCheck
    }
    "down" {
        Invoke-CheckedCommand { docker compose down }
        Write-Host "Compose 服务已停止；默认保留 mysql_data 卷。"
    }
}
