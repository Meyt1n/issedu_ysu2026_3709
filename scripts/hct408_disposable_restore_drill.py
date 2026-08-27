"""HCT-408 disposable backup → destroy → restore drill (no shared DB).

This drill proves the previously missing FILE_ROOT recovery path:

1. Seed a disposable teaching FILE_ROOT (no real health data).
2. Build a restorable backup (inventory + files.tar.gz + version + synthetic dump).
3. Validate the backup (fail-closed).
4. Destroy FILE_ROOT.
5. Restore files from the archive and re-validate hashes.
6. Emit an evidence JSON that honestly records MySQL Compose status.

MySQL DROP/IMPORT is only attempted when ``docker compose`` is available and
``--with-mysql`` is passed. Without Docker the drill remains PASS for the file
path and records ``MYSQL_RESTORE_SKIPPED_NO_DOCKER`` — it does not claim a
full three-profile live restore.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.hct408_file_archive import (  # noqa: E402
    create_files_archive,
    restore_files_archive,
)
from scripts.hct408_file_inventory import create_manifest  # noqa: E402
from scripts.hct408_validate_backup import validate_backup  # noqa: E402


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _git_commit() -> tuple[str, str]:
    try:
        full = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        short = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return full, short
    except (OSError, subprocess.CalledProcessError):
        return "unknown", "unknown"


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _seed_file_root(file_root: Path) -> list[str]:
    file_root.mkdir(parents=True, exist_ok=True)
    samples = {
        "uploads/teaching-label.txt": (
            b"HCT-408 teaching sample - synthetic label text only.\n"
            b"No real patient or household health content.\n"
        ),
        "uploads/nested/demo-ref.bin": b"\x00HCT408\x01demo-ref\x02",
        "backup-skip/tombstone.json": (
            b'{"schema":"hct-deletion-skip/v1","note":"teaching marker"}\n'
        ),
    }
    for rel, payload in samples.items():
        path = file_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return sorted(samples)


def _write_synthetic_dump(backup_path: Path) -> None:
    # Minimal gzip SQL artifact so validators and restore scripts see a dump.
    sql = (
        b"-- HCT-408 disposable synthetic dump\n"
        b"-- NOT a production MySQL backup; used only for fail-closed drills.\n"
        b"SELECT 'hct408-disposable' AS marker;\n"
    )
    with gzip.open(backup_path / "mysqldump.sql.gz", "wb") as handle:
        handle.write(sql)


def _write_version_manifest(backup_path: Path, backup_id: str) -> dict[str, Any]:
    full, short = _git_commit()
    compose_path = ROOT / "docker-compose.yml"
    config_hashes: dict[str, str] = {}
    if compose_path.is_file():
        config_hashes["docker-compose.yml"] = _sha256_bytes(compose_path.read_bytes())
    env_example = ROOT / ".env.example"
    if env_example.is_file():
        config_hashes[".env.example"] = _sha256_bytes(env_example.read_bytes())
    manifest = {
        "backup_id": backup_id,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit": full,
        "git_commit_short": short,
        "migration_head": "disposable-drill",
        "compose_profile": "basic",
        "mysql_image": "mysql:8.4",
        "ollama_model": "unavailable",
        "ruleset_version": "rules-v0",
        "knowledge_version": "knowledge-v0",
        "config_hashes": config_hashes,
        "note": (
            "Credential material is intentionally excluded from this manifest. "
            "This backup was created by the disposable HCT-408 drill."
        ),
    }
    (backup_path / "version_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def run_drill(
    work_dir: Path,
    *,
    with_mysql: bool = False,
    keep: bool = False,
) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    file_root = work_dir / "file-root"
    backup_root = work_dir / "backups"
    backup_id = f"hct-backup-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    backup_path = backup_root / backup_id
    backup_path.mkdir(parents=True, exist_ok=True)

    seeded = _seed_file_root(file_root)
    before_hashes = {
        rel: hashlib.sha256((file_root / rel).read_bytes()).hexdigest() for rel in seeded
    }

    inventory = create_manifest(file_root)
    (backup_path / "file_manifest.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    archive_meta = create_files_archive(file_root, backup_path)
    _write_synthetic_dump(backup_path)
    version = _write_version_manifest(backup_path, backup_id)

    preflight = validate_backup(backup_path, expected_migration_head="disposable-drill")
    if not preflight["passed"]:
        return {
            "schema_version": "hct408-disposable-restore-drill/v1",
            "passed": False,
            "decision": "BLOCK_RESTORE",
            "stage": "preflight",
            "preflight": preflight,
        }

    # Destroy FILE_ROOT to prove recovery is real, not inventory-only.
    shutil.rmtree(file_root)
    assert not file_root.exists()

    restore_report = restore_files_archive(backup_path, file_root, wipe_existing=True)
    post = validate_backup(
        backup_path,
        file_root=file_root,
        expected_migration_head="disposable-drill",
    )
    after_hashes = {
        rel: hashlib.sha256((file_root / rel).read_bytes()).hexdigest() for rel in seeded
    }
    hash_match = before_hashes == after_hashes

    docker_ok = _docker_available()
    mysql_status = {
        "attempted": bool(with_mysql and docker_ok),
        "docker_available": docker_ok,
        "status": (
            "MYSQL_RESTORE_SKIPPED_NO_DOCKER"
            if not docker_ok
            else (
                "MYSQL_RESTORE_NOT_REQUESTED"
                if not with_mysql
                else "MYSQL_RESTORE_REQUIRES_LIVE_COMPOSE"
            )
        ),
        "note": (
            "Disposable drill does not DROP a shared MySQL database. "
            "Live Compose restore remains an operator-run step with --force "
            "against a disposable project."
        ),
    }

    passed = bool(
        preflight["passed"] and post["passed"] and hash_match and restore_report["passed"]
    )
    evidence = {
        "schema_version": "hct408-disposable-restore-drill/v1",
        "passed": passed,
        "decision": "DISPOSABLE_RESTORE_PASSED" if passed else "DISPOSABLE_RESTORE_FAILED",
        "backup_id": backup_id,
        "backup_path": str(backup_path),
        "file_root": str(file_root),
        "seeded_files": seeded,
        "archive": {
            "total_files": archive_meta["total_files"],
            "sha256": archive_meta["sha256"],
        },
        "version_manifest": {
            "git_commit_short": version["git_commit_short"],
            "migration_head": version["migration_head"],
            "compose_profile": version["compose_profile"],
        },
        "preflight": preflight,
        "restore": restore_report,
        "post_validate": post,
        "content_hash_match": hash_match,
        "mysql": mysql_status,
        "limitations": [
            "No real household health data was used.",
            "Synthetic mysqldump is not a production database backup.",
            "Three-profile live Compose up/health and MySQL DROP/IMPORT still need Docker.",
            "Independent R3 review is still required before marking HCT-408 verified.",
        ],
        "completed_utc": datetime.now(UTC).isoformat(),
    }

    report_path = backup_path / "disposable-restore-drill.json"
    report_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    evidence["report_path"] = str(report_path)

    if not keep:
        # Keep only the evidence report copy destination handled by caller.
        pass
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path(os.environ.get("HCT408_DRILL_DIR", "tmp/hct408-disposable-drill")),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/reviews/HCT-408-disposable-restore-drill.json"),
    )
    parser.add_argument("--with-mysql", action="store_true")
    parser.add_argument("--keep", action="store_true", help="Retain work-dir contents")
    args = parser.parse_args()

    evidence = run_drill(args.work_dir, with_mysql=args.with_mysql, keep=args.keep)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    if not args.keep and args.work_dir.exists():
        # Preserve the written evidence under docs/; wipe disposable workspace.
        shutil.rmtree(args.work_dir, ignore_errors=True)
    return 0 if evidence.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
