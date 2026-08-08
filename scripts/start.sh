#!/usr/bin/env bash
set -euo pipefail

target="${1:-api}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "已从 .env.example 创建 .env；请在真实环境中替换开发密码。"
fi

case "$target" in
  setup)
    uv sync --frozen
    npm ci
    ;;
  api)
    uv run alembic upgrade head
    uv run uvicorn app.main:app --app-dir src/api --reload --host 0.0.0.0 --port 8000
    ;;
  web)
    npm run dev:web
    ;;
  migrate)
    uv run alembic upgrade head
    ;;
  check)
    uv run ruff check src/api src/ai scripts tests migrations
    uv run pytest
    npm run check:web
    npm run build:web
    docker compose config --quiet
    ;;
  up)
    docker compose up -d --build --wait --wait-timeout 60
    "$0" health
    ;;
  health)
    docker compose ps --all
    while read -r service state health; do
      if [[ "$state" != "running" || "$health" != "healthy" ]]; then
        echo "Compose 服务 $service 未健康：state=$state, health=$health" >&2
        exit 1
      fi
    done < <(docker compose ps --all --format '{{.Service}} {{.State}} {{.Health}}')
    if [[ -z "$(docker compose ps --all --format '{{.Service}}')" ]]; then
      echo "没有找到 Compose 服务，请先执行 ./scripts/start.sh up。" >&2
      exit 1
    fi
    api_url="$(docker compose port api 8000)"
    web_url="$(docker compose port web 80)"
    [[ -n "$api_url" && -n "$web_url" ]] || { echo "无法定位 API/Web 宿主端口。" >&2; exit 1; }
    api_port="${api_url##*:}"
    web_port="${web_url##*:}"
    uv run python scripts/check_http_health.py \
      --endpoint "API=http://127.0.0.1:${api_port}/health" \
      --endpoint "MySQL=http://127.0.0.1:${api_port}/api/v1/health/db" \
      --endpoint "Web=http://127.0.0.1:${web_port}/health"
    echo "API、Web、MySQL Compose 健康检查通过。"
    ;;
  down)
    docker compose down
    echo "Compose 服务已停止；默认保留 mysql_data 卷。"
    ;;
  *)
    echo "用法: ./scripts/start.sh [setup|api|web|migrate|check|up|health|down]" >&2
    exit 2
    ;;
esac
