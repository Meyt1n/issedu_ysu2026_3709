[CmdletBinding()]
param(
    [ValidateSet("setup", "api", "web", "web-member", "web-admin", "migrate", "check", "up", "health", "down")]
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

function Get-ComposeProfile {
    if ($env:COMPOSE_PROFILE) {
        return $env:COMPOSE_PROFILE
    }
    if ($env:COMPOSE_PROFILES) {
        return ($env:COMPOSE_PROFILES.Split(",")[0]).Trim()
    }
    return "basic"
}

function Get-ComposeServiceStatus {
    $profile = Get-ComposeProfile
    $rows = @(Invoke-CheckedCommand { docker compose --profile $profile ps --all --format json } | ConvertFrom-Json)
    if ($rows.Count -eq 0) {
        throw "没有找到 Compose 服务，请先执行 scripts/start.ps1 up（默认 profile=basic）。"
    }
    foreach ($service in @("db", "api", "web", "outbox-worker", "care-plan-worker")) {
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

function Get-ComposeHostPort {
    param([Parameter(Mandatory = $true)][string]$Service, [Parameter(Mandatory = $true)][int]$ContainerPort)

    $profile = Get-ComposeProfile
    $published = @(Invoke-CheckedCommand { docker compose --profile $profile port $Service $ContainerPort })[0]
    if (-not $published) {
        throw "无法定位 ${Service}:$ContainerPort 的宿主端口。"
    }
    return ($published.Trim() -split ":")[-1]
}

function Invoke-HealthCheck {
    Get-ComposeServiceStatus
    $apiPort = Get-ComposeHostPort -Service "api" -ContainerPort 8000
    $webPort = Get-ComposeHostPort -Service "web" -ContainerPort 80
    $endpoints = @(
        "--endpoint", "API=http://127.0.0.1:$apiPort/health",
        "--endpoint", "MySQL=http://127.0.0.1:$apiPort/api/v1/health/db",
        "--endpoint", "Web=http://127.0.0.1:$webPort/health"
    )
    Invoke-CheckedCommand { uv run python scripts/check_http_health.py @endpoints }
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
        $env:PYTHONPATH = "$RepoRoot\src\api$([IO.Path]::PathSeparator)$RepoRoot\src"
        Invoke-CheckedCommand { uv run uvicorn app.main:app --app-dir src/api --reload --host 0.0.0.0 --port 8000 }
    }
    "web" {
        # HCT-456：裸 auto 单入口仅供调试；产品「成员前台」必须用 web-member。
        Write-Host "提示：当前是调试单入口（auto，按账号角色进门户）。产品成员前台请用: .\scripts\start.ps1 web-member → http://127.0.0.1:5173" -ForegroundColor Yellow
        Invoke-CheckedCommand { npm run dev:web }
    }
    "web-member" {
        # HCT-453 成员前台入口（默认 http://127.0.0.1:5173，可用 HCT_WEB_PORT 覆盖）
        $memberPort = if ($env:HCT_WEB_PORT) { $env:HCT_WEB_PORT } else { "5173" }
        Write-Host "成员前台入口：启动后打开 http://127.0.0.1:$memberPort ，用家庭管理员账号进入后选择家人并输入 PIN；也可刷脸。管理员请另开 web-admin。" -ForegroundColor Cyan
        Invoke-CheckedCommand { npm run dev:web:member }
    }
    "web-admin" {
        # HCT-453 管理后台入口（默认 http://127.0.0.1:5174，可用 HCT_ADMIN_WEB_PORT 覆盖）
        $adminPort = if ($env:HCT_ADMIN_WEB_PORT) { $env:HCT_ADMIN_WEB_PORT } else { "5174" }
        Write-Host "管理后台入口：启动后打开 http://127.0.0.1:$adminPort ，用管理员账号密码登录。" -ForegroundColor Cyan
        Invoke-CheckedCommand { npm run dev:web:admin }
    }
    "migrate" {
        Invoke-CheckedCommand { uv run alembic upgrade head }
    }
    "check" {
        Invoke-CheckedCommand { uv run ruff check src/api src/ai scripts migrations }
        Invoke-CheckedCommand { npm run check:web }
        Invoke-CheckedCommand { npm run build:web }
        Invoke-CheckedCommand { docker compose --profile (Get-ComposeProfile) config --quiet }
    }
    "up" {
        $profile = Get-ComposeProfile
        Invoke-CheckedCommand { docker compose --profile $profile up -d --build --wait --wait-timeout 60 }
        Write-Host "Compose profile=$profile 已启动。"
        Invoke-HealthCheck
    }
    "health" {
        Invoke-HealthCheck
    }
    "down" {
        $profile = Get-ComposeProfile
        Invoke-CheckedCommand { docker compose --profile $profile down }
        Write-Host "Compose 服务已停止（profile=$profile）；默认保留 mysql_data 卷。"
    }
}
