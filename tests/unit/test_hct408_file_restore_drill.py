"""Tests for HCT-408 file archive restore and disposable drill."""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.hct408_disposable_restore_drill import run_drill  # noqa: E402
from scripts.hct408_file_archive import (  # noqa: E402
    create_files_archive,
    restore_files_archive,
)
from scripts.hct408_file_inventory import create_manifest  # noqa: E402
from scripts.hct408_profile_preflight import run_preflight  # noqa: E402
from scripts.hct408_validate_backup import validate_backup  # noqa: E402


def _seed(root: Path) -> None:
    (root / "a").mkdir(parents=True)
    (root / "a" / "one.txt").write_bytes(b"one")
    (root / "b").mkdir(parents=True)
    (root / "b" / "two.bin").write_bytes(b"\x00\x01two")


def test_create_and_restore_files_archive_recovers_destroyed_root(tmp_path: Path) -> None:
    file_root = tmp_path / "files"
    backup = tmp_path / "backup"
    _seed(file_root)
    before = {
        path.relative_to(file_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in file_root.rglob("*")
        if path.is_file()
    }

    meta = create_files_archive(file_root, backup)
    assert meta["total_files"] == 2
    assert (backup / "files.tar.gz").is_file()

    # Destroy and restore.
    for path in list(file_root.rglob("*")):
        if path.is_file():
            path.unlink()
    file_root.joinpath("a").rmdir()
    file_root.joinpath("b").rmdir()

    report = restore_files_archive(backup, file_root, wipe_existing=True)
    assert report["passed"] is True
    assert report["restored_files"] == 2
    after = {
        path.relative_to(file_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in file_root.rglob("*")
        if path.is_file()
    }
    assert before == after


def test_validate_backup_requires_files_archive_when_inventory_nonempty(tmp_path: Path) -> None:
    backup = tmp_path / "hct-backup-20260826-000001"
    backup.mkdir()
    file_root = tmp_path / "files"
    _seed(file_root)
    (backup / "mysqldump.sql.gz").write_bytes(gzip.compress(b"SELECT 1;\n"))
    (backup / "version_manifest.json").write_text(
        json.dumps(
            {
                "backup_id": backup.name,
                "timestamp_utc": "2026-08-26T00:00:00+00:00",
                "git_commit": "b" * 40,
                "git_commit_short": "b" * 7,
                "migration_head": "0001_initial",
                "compose_profile": "basic",
                "note": "Credentials are excluded from this manifest.",
            }
        ),
        encoding="utf-8",
    )
    (backup / "file_manifest.json").write_text(
        json.dumps(create_manifest(file_root)),
        encoding="utf-8",
    )

    blocked = validate_backup(backup)
    assert blocked["passed"] is False
    assert any(item["code"] == "FILES_ARCHIVE_MISSING" for item in blocked["findings"])

    create_files_archive(file_root, backup)
    ready = validate_backup(backup, expected_migration_head="0001_initial")
    assert ready["passed"] is True
    assert ready["decision"] == "BACKUP_READY_FOR_RESTORE"


def test_disposable_restore_drill_passes_without_docker(tmp_path: Path) -> None:
    evidence = run_drill(tmp_path / "work", with_mysql=False, keep=True)
    assert evidence["passed"] is True
    assert evidence["decision"] == "DISPOSABLE_RESTORE_PASSED"
    assert evidence["content_hash_match"] is True
    assert evidence["mysql"]["status"] in {
        "MYSQL_RESTORE_SKIPPED_NO_DOCKER",
        "MYSQL_RESTORE_NOT_REQUESTED",
    }
    assert Path(evidence["backup_path"]).joinpath("files.tar.gz").is_file()


def test_profile_preflight_accepts_repo_compose() -> None:
    report = run_preflight()
    assert report["passed"] is True
    assert "ollama" not in report["profiles"]["basic"]["services"]
    assert "ollama" in report["profiles"]["enhanced"]["services"]
    assert "care-plan-worker" in report["profiles"]["basic"]["services"]
