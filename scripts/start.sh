#!/usr/bin/env bash
set -euo pipefail

target="${1:-api}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "已从 .env.example 创建 .env；请在真实环境中替换开发密码。"
fi

compose_profile="${COMPOSE_PROFILE:-${COMPOSE_PROFILES:-basic}}"
compose_profile="${compose_profile%%,*}"
compose_profile="${compose_profile// /}"

case "$target" in
  setup)
    uv sync --frozen
    npm ci
    ;;
  api)
    uv run alembic upgrade head
    PYTHONPATH="$repo_root/src/api:$repo_root/src${PYTHONPATH:+:$PYTHONPATH}" \
      uv run uvicorn app.main:app --app-dir src/api --reload --host 0.0.0.0 --port 8000
    ;;
  web)
    # HCT-456：裸 auto 单入口仅供调试；产品「成员前台」必须用 web-member。
    echo "提示：当前是调试单入口（auto，按账号角色进门户）。产品成员前台请用: $0 web-member → http://127.0.0.1:5173" >&2
    npm run dev:web
    ;;
  web-member)
    # HCT-453 成员前台入口（默认 http://127.0.0.1:5173，可用 HCT_WEB_PORT 覆盖）
    echo "成员前台入口：启动后打开 http://127.0.0.1:${HCT_WEB_PORT:-5173} ，用家庭成员账号（人脸/PIN）登录；管理员请另开 web-admin。" >&2
    npm run dev:web:member
    ;;
  web-admin)
    # HCT-453 管理后台入口（默认 http://127.0.0.1:5174，可用 HCT_ADMIN_WEB_PORT 覆盖）
    echo "管理后台入口：启动后打开 http://127.0.0.1:${HCT_ADMIN_WEB_PORT:-5174} ，用管理员账号密码登录。" >&2
    npm run dev:web:admin
    ;;
  migrate)
    uv run alembic upgrade head
    ;;
  check)
    uv run ruff check src/api src/ai scripts migrations
    npm run check:web
    npm run build:web
    docker compose --profile "$compose_profile" config --quiet
    ;;
  up)
    docker compose --profile "$compose_profile" up -d --build --wait --wait-timeout 60
    echo "Compose profile=${compose_profile} 已启动。"
    "$0" health
    ;;
  health)
    docker compose --profile "$compose_profile" ps --all
    while read -r service state health; do
      if [[ "$state" != "running" || "$health" != "healthy" ]]; then
        echo "Compose 服务 $service 未健康：state=$state, health=$health" >&2
        exit 1
      fi
    done < <(docker compose --profile "$compose_profile" ps --all --format '{{.Service}} {{.State}} {{.Health}}')
    if [[ -z "$(docker compose --profile "$compose_profile" ps --all --format '{{.Service}}')" ]]; then
      echo "没有找到 Compose 服务，请先执行 ./scripts/start.sh up（默认 profile=basic）。" >&2
      exit 1
    fi
    running_services="$(docker compose --profile "$compose_profile" ps --all --format '{{.Service}}')"
    for required in db api web outbox-worker care-plan-worker; do
      if ! grep -qx "$required" <<<"$running_services"; then
        echo "Compose 服务 $required 不存在，请重新执行 ./scripts/start.sh up。" >&2
        exit 1
      fi
    done
    api_url="$(docker compose --profile "$compose_profile" port api 8000)"
    web_url="$(docker compose --profile "$compose_profile" port web 80)"
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
    docker compose --profile "$compose_profile" down
    echo "Compose 服务已停止（profile=${compose_profile}）；默认保留 mysql_data 卷。"
    ;;
  *)
    echo "用法: ./scripts/start.sh [setup|api|web|web-member|web-admin|migrate|check|up|health|down]" >&2
    exit 2
    ;;
esac
