#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
backup_dir="backups"
compose_project=""
skip_mysql=0
skip_files=0
skip_version=0
skip_validation=0
while (($#)); do
  case "$1" in
    --backup-dir) backup_dir="$2"; shift 2 ;;
    --project) compose_project="$2"; shift 2 ;;
    --skip-mysql) skip_mysql=1; shift ;;
    --skip-files) skip_files=1; shift ;;
    --skip-version) skip_version=1; shift ;;
    --skip-validation) skip_validation=1; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

timestamp="$(date -u +%Y%m%d-%H%M%S)"
backup_name="hct-backup-${timestamp}"
mkdir -p "$backup_dir"
backup_path="$(cd "$backup_dir" && pwd)/${backup_name}"
mkdir -p "$backup_path"
echo "[HCT-408 backup] backup_id=${backup_name} backup_path=${backup_path}"

compose=(docker compose)
if [[ -n "$compose_project" ]]; then compose+=(--project-name "$compose_project"); fi
mysql_password="${MYSQL_ROOT_PASSWORD:-change-me-root}"
mysql_database="${MYSQL_DATABASE:-homecare}"

if ((skip_mysql == 0)); then
  MYSQL_PWD="$mysql_password" "${compose[@]}" exec -T db mysqldump \
    -u root --single-transaction --routines --triggers --events \
    --set-gtid-purged=OFF "$mysql_database" 2>"$backup_path/mysqldump.stderr.log" \
    | gzip -c >"$backup_path/mysqldump.sql.gz"
  [[ -s "$backup_path/mysqldump.sql.gz" ]] || { echo "Empty MySQL dump" >&2; exit 1; }
  [[ -s "$backup_path/mysqldump.stderr.log" ]] || rm -f "$backup_path/mysqldump.stderr.log"
fi

file_root="${FILE_ROOT:-./data/files}"
if ((skip_files == 0)); then
  [[ -d "$file_root" ]] || { echo "FILE_ROOT not found: $file_root" >&2; exit 1; }
  uv run python scripts/hct408_file_inventory.py --root "$file_root" \
    --output "$backup_path/file_manifest.json"
fi

if ((skip_version == 0)); then
  migration_head="unknown"
  migration_head_value="$(MYSQL_PWD="$mysql_password" "${compose[@]}" exec -T db mysql -u root -N \
    -e 'SELECT version_num FROM alembic_version' 2>/dev/null | tail -n 1 || true)"
  [[ -z "$migration_head_value" ]] || migration_head="$migration_head_value"
  git_sha="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
  git_short="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  BACKUP_ID="$backup_name" GIT_SHA="$git_sha" GIT_SHORT="$git_short" \
    MIGRATION_HEAD="$migration_head" COMPOSE_PROFILE="${COMPOSE_PROFILE:-unknown}" \
    OLLAMA_MODEL="${OLLAMA_MODEL:-unavailable}" RULESET_VERSION="${RULESET_VERSION:-unknown}" \
    KNOWLEDGE_VERSION="${KNOWLEDGE_VERSION:-unknown}" \
    uv run python -c 'import json,os,sys; from datetime import UTC,datetime; from pathlib import Path; Path(sys.argv[1]).write_text(json.dumps({"backup_id":os.environ["BACKUP_ID"],"timestamp_utc":datetime.now(UTC).isoformat(),"git_commit":os.environ["GIT_SHA"],"git_commit_short":os.environ["GIT_SHORT"],"migration_head":os.environ["MIGRATION_HEAD"],"compose_profile":os.environ["COMPOSE_PROFILE"],"mysql_image":"mysql:8.4","ollama_model":os.environ["OLLAMA_MODEL"],"ruleset_version":os.environ["RULESET_VERSION"],"knowledge_version":os.environ["KNOWLEDGE_VERSION"],"note":"Credential material is intentionally excluded from this manifest."},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")' "$backup_path/version_manifest.json"
fi

if ((skip_validation == 0 && skip_mysql == 0 && skip_files == 0 && skip_version == 0)); then
  uv run python scripts/hct408_validate_backup.py --backup "$backup_path"
fi
echo "[HCT-408 backup] complete: ${backup_path}"
