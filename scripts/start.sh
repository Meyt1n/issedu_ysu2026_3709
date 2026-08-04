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
    uv sync
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
    uv run ruff check src/api tests migrations
    uv run pytest
    npm run check:web
    npm run build:web
    ;;
  *)
    echo "用法: ./scripts/start.sh [setup|api|web|migrate|check]" >&2
    exit 2
    ;;
esac
