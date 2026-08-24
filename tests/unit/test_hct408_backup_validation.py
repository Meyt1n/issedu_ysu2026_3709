"""Tests for non-destructive HCT-408 backup validation."""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.hct408_file_inventory import create_manifest  # noqa: E402
from scripts.hct408_validate_backup import validate_backup  # noqa: E402


def _write_valid_backup(tmp_path: Path) -> tuple[Path, Path]:
    backup = tmp_path / "hct-backup-20260824-120000"
    backup.mkdir()
    file_root = tmp_path / "files"
    file_root.mkdir()
    payload = b"demo attachment"
    stored = file_root / "uploads" / "demo.txt"
    stored.parent.mkdir()
    stored.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    (backup / "mysqldump.sql.gz").write_bytes(b"compressed-dump-placeholder")
    (backup / "version_manifest.json").write_text(
        json.dumps(
            {
                "backup_id": backup.name,
                "timestamp_utc": "2026-08-24T04:00:00+00:00",
                "git_commit": "a" * 40,
                "git_commit_short": "a" * 7,
                "migration_head": "0001_initial",
                "compose_profile": "basic",
                "note": "Credentials are excluded from this manifest.",
            }
        ),
        encoding="utf-8",
    )
    (backup / "file_manifest.json").write_text(
        json.dumps(
            {
                "source_root": str(file_root),
                "total_files": 1,
                "total_bytes": len(payload),
                "collected_utc": "2026-08-24T04:00:00+00:00",
                "files": [
                    {
                        "relative_path": "uploads/demo.txt",
                        "size": len(payload),
                        "sha256": digest,
                        "modified_utc": "2026-08-24T04:00:00+00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return backup, file_root


def test_valid_backup_is_ready_for_restore(tmp_path: Path) -> None:
    backup, file_root = _write_valid_backup(tmp_path)

    report = validate_backup(
        backup,
        file_root=file_root,
        expected_migration_head="0001_initial",
    )

    assert report["passed"] is True
    assert report["decision"] == "BACKUP_READY_FOR_RESTORE"
    assert report["findings"] == []


def test_backup_rejects_path_traversal(tmp_path: Path) -> None:
    backup, _ = _write_valid_backup(tmp_path)
    manifest_path = backup / "file_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["relative_path"] = "../outside.txt"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = validate_backup(backup)

    assert report["passed"] is False
    assert any(item["code"] == "UNSAFE_FILE_PATH" for item in report["findings"])


def test_backup_rejects_changed_file_reference(tmp_path: Path) -> None:
    backup, file_root = _write_valid_backup(tmp_path)
    (file_root / "uploads" / "demo.txt").write_text("changed", encoding="utf-8")

    report = validate_backup(backup, file_root=file_root)

    assert report["passed"] is False
    assert any(item["code"] == "FILE_REFERENCE_MISMATCH" for item in report["findings"])


def test_file_inventory_is_hashable_and_relative(tmp_path: Path) -> None:
    root = tmp_path / "files"
    root.mkdir()
    (root / "nested").mkdir()
    (root / "nested" / "demo.txt").write_text("hello", encoding="utf-8")

    manifest = create_manifest(root)

    assert manifest["total_files"] == 1
    assert manifest["total_bytes"] == 5
    assert manifest["files"][0]["relative_path"] == "nested/demo.txt"
    assert len(manifest["files"][0]["sha256"]) == 64
