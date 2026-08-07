[CmdletBinding()]
param(
    [ValidateSet("setup", "api", "web", "migrate", "check")]
    [string]$Target = "api"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Warning "已从 .env.example 创建 .env；请在真实环境中替换开发密码。"
}

switch ($Target) {
    "setup" {
        uv sync
        npm ci
        Write-Host "依赖已安装。"
    }
    "api" {
        uv run alembic upgrade head
        uv run uvicorn app.main:app --app-dir src/api --reload --host 0.0.0.0 --port 8000
    }
    "web" {
        npm run dev:web
    }
    "migrate" {
        uv run alembic upgrade head
    }
    "check" {
        uv run ruff check src/api src/ai scripts tests migrations
        uv run pytest
        npm run check:web
        npm run build:web
    }
}
