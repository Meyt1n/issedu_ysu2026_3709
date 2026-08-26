#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
backup_id=""
backup_dir="backups"
compose_project=""
file_root="${FILE_ROOT:-./data/files}"
skip_health=0
force=0
while (($#)); do
  case "$1" in
    --backup-id) backup_id="$2"; shift 2 ;;
    --backup-dir) backup_dir="$2"; shift 2 ;;
    --project) compose_project="$2"; shift 2 ;;
    --file-root) file_root="$2"; shift 2 ;;
    --skip-health) skip_health=1; shift ;;
    --force) force=1; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$backup_id" ]] || { echo "--backup-id is required" >&2; exit 2; }
backup_path="$(cd "$backup_dir" && pwd)/$backup_id"
[[ -d "$backup_path" ]] || { echo "Backup not found: $backup_path" >&2; exit 1; }

# This must pass before the database can be dropped.
uv run python scripts/hct408_validate_backup.py --backup "$backup_path" \
  --output "$backup_path/validation-before-restore.json"

if ((force == 0)); then
  echo "This will replace the current database. Type YES to continue:"
  read -r confirmation
  [[ "$confirmation" == "YES" ]] || { echo "Aborted."; exit 0; }
fi

compose=(docker compose)
if [[ -n "$compose_project" ]]; then compose+=(--project-name "$compose_project"); fi
mysql_password="${MYSQL_ROOT_PASSWORD:-change-me-root}"
mysql_database="${MYSQL_DATABASE:-homecare}"
database_sql="DROP DATABASE IF EXISTS \`$mysql_database\`; CREATE DATABASE \`$mysql_database\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
MYSQL_PWD="$mysql_password" "${compose[@]}" exec -T db mysql -u root -e "$database_sql"
gzip -dc "$backup_path/mysqldump.sql.gz" \
  | MYSQL_PWD="$mysql_password" "${compose[@]}" exec -T db mysql -u root "$mysql_database"
"${compose[@]}" exec -T api uv run alembic upgrade head

entry_count="$(uv run python -c 'import json,sys; from pathlib import Path; p=Path(sys.argv[1]); print(len(json.loads(p.read_text(encoding="utf-8")).get("files",[])) if p.exists() else 0)' "$backup_path/file_manifest.json")"
if ((entry_count > 0)); then
  # Recover FILE_ROOT from the archived contents before hash verification.
  uv run python scripts/hct408_file_archive.py restore \
    --backup "$backup_path" --file-root "$file_root" --wipe-existing
  uv run python scripts/hct408_validate_backup.py --backup "$backup_path" --file-root "$file_root"
fi

if ((skip_health == 0)); then uv run python scripts/check_http_health.py; fi
echo "[HCT-408 restore] complete: ${backup_id}"
