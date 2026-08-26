"""Validate an HCT-408 backup without modifying the database or files."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any

REQUIRED_VERSION_KEYS = {
    "backup_id",
    "timestamp_utc",
    "git_commit",
    "git_commit_short",
    "migration_head",
    "compose_profile",
    "note",
}
REQUIRED_FILE_KEYS = {"relative_path", "size", "sha256", "modified_utc"}
FORBIDDEN_KEY_NAMES = {
    "password",
    "secret",
    "api_key",
    "access_token",
    "session_token",
    "private_key",
}
FORBIDDEN_VALUES = {
    "change-me-root",
    "change-me",
}
FILES_ARCHIVE_NAME = "files.tar.gz"
FILES_ARCHIVE_META_NAME = "files_archive.json"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("relative_path must be a non-empty string")
    normalized = value.replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"unsafe relative_path: {value}")
    return "/".join(candidate.parts)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_backup(
    backup_path: Path,
    *,
    file_root: Path | None = None,
    expected_migration_head: str | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    version_path = backup_path / "version_manifest.json"
    file_manifest_path = backup_path / "file_manifest.json"
    dump_path = backup_path / "mysqldump.sql.gz"

    if not backup_path.is_dir():
        findings.append({"code": "BACKUP_NOT_FOUND", "message": str(backup_path)})
        return {
            "schema_version": "hct408-backup-validation/v1",
            "passed": False,
            "findings": findings,
        }

    version: dict[str, Any] | None = None
    if not version_path.is_file():
        findings.append({"code": "VERSION_MANIFEST_MISSING", "message": str(version_path)})
    else:
        try:
            loaded = _load_json(version_path)
            if not isinstance(loaded, dict):
                raise ValueError("version manifest root must be an object")
            version = loaded
            missing = sorted(REQUIRED_VERSION_KEYS - set(loaded))
            if missing:
                findings.append({"code": "VERSION_KEYS_MISSING", "message": ",".join(missing)})
            text = json.dumps(loaded, ensure_ascii=False).lower()
            leaked_keys = sorted(
                key for key in FORBIDDEN_KEY_NAMES
                if f'"{key}"' in text
            )
            leaked_values = sorted(value for value in FORBIDDEN_VALUES if value in text)
            if leaked_keys or leaked_values:
                leaked = leaked_keys + leaked_values
                findings.append(
                    {
                        "code": "SECRET_TEXT_IN_VERSION_MANIFEST",
                        "message": ",".join(leaked),
                    }
                )
            if expected_migration_head and loaded.get("migration_head") != expected_migration_head:
                findings.append(
                    {
                        "code": "MIGRATION_HEAD_MISMATCH",
                        "message": (
                            f"expected {expected_migration_head}, "
                            f"got {loaded.get('migration_head')!r}"
                        ),
                    }
                )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            findings.append({"code": "VERSION_MANIFEST_INVALID", "message": str(exc)})

    if not dump_path.is_file() or dump_path.stat().st_size == 0:
        findings.append({"code": "MYSQL_DUMP_MISSING", "message": str(dump_path)})

    file_manifest: dict[str, Any] | None = None
    if not file_manifest_path.is_file():
        findings.append({"code": "FILE_MANIFEST_MISSING", "message": str(file_manifest_path)})
    else:
        try:
            loaded = _load_json(file_manifest_path)
            if not isinstance(loaded, dict):
                raise ValueError("file manifest root must be an object")
            file_manifest = loaded
            required_top_level = {
                "source_root",
                "total_files",
                "total_bytes",
                "collected_utc",
                "files",
            }
            if not required_top_level.issubset(loaded):
                findings.append(
                    {
                        "code": "FILE_MANIFEST_KEYS_MISSING",
                        "message": (
                            "source_root,total_files,total_bytes,collected_utc,files required"
                        ),
                    }
                )
            entries = loaded.get("files", [])
            if not isinstance(entries, list):
                raise ValueError("files must be a list")
            calculated_bytes = 0
            for entry in entries:
                if not isinstance(entry, dict):
                    findings.append(
                        {
                            "code": "FILE_ENTRY_INVALID",
                            "message": "file entry must be an object",
                        }
                    )
                    continue
                missing = sorted(REQUIRED_FILE_KEYS - set(entry))
                if missing:
                    findings.append(
                        {
                            "code": "FILE_ENTRY_KEYS_MISSING",
                            "message": ",".join(missing),
                        }
                    )
                    continue
                try:
                    rel = _safe_relative_path(entry["relative_path"])
                except ValueError as exc:
                    findings.append({"code": "UNSAFE_FILE_PATH", "message": str(exc)})
                    continue
                if not isinstance(entry["size"], int) or entry["size"] < 0:
                    findings.append({"code": "FILE_SIZE_INVALID", "message": rel})
                if not isinstance(entry["sha256"], str) or len(entry["sha256"]) != 64:
                    findings.append({"code": "FILE_HASH_INVALID", "message": rel})
                calculated_bytes += int(entry["size"] or 0) if isinstance(entry["size"], int) else 0
                if file_root is not None:
                    actual = file_root / Path(*rel.split("/"))
                    if not actual.is_file():
                        findings.append({"code": "FILE_REFERENCE_MISSING", "message": rel})
                    elif (
                        actual.stat().st_size != entry["size"]
                        or _sha256(actual) != entry["sha256"]
                    ):
                        findings.append({"code": "FILE_REFERENCE_MISMATCH", "message": rel})
            if (
                isinstance(loaded.get("total_files"), int)
                and loaded["total_files"] != len(entries)
            ):
                findings.append(
                    {
                        "code": "FILE_COUNT_MISMATCH",
                        "message": f"manifest={loaded['total_files']} entries={len(entries)}",
                    }
                )
            if (
                isinstance(loaded.get("total_bytes"), int)
                and loaded["total_bytes"] != calculated_bytes
            ):
                findings.append(
                    {
                        "code": "FILE_BYTES_MISMATCH",
                        "message": f"manifest={loaded['total_bytes']} entries={calculated_bytes}",
                    }
                )
            # When the inventory lists files, a restorable archive is mandatory.
            # Older inventory-only backups cannot recover destroyed FILE_ROOT.
            entry_count = len(entries) if isinstance(entries, list) else 0
            if entry_count > 0:
                archive_path = backup_path / FILES_ARCHIVE_NAME
                if not archive_path.is_file() or archive_path.stat().st_size == 0:
                    findings.append(
                        {
                            "code": "FILES_ARCHIVE_MISSING",
                            "message": str(archive_path),
                        }
                    )
                else:
                    meta_path = backup_path / FILES_ARCHIVE_META_NAME
                    if meta_path.is_file():
                        try:
                            archive_meta = _load_json(meta_path)
                            if not isinstance(archive_meta, dict):
                                raise ValueError("files_archive.json root must be an object")
                            archived = archive_meta.get("files", [])
                            if not isinstance(archived, list):
                                raise ValueError("files_archive.files must be a list")
                            if len(archived) != entry_count:
                                findings.append(
                                    {
                                        "code": "FILES_ARCHIVE_COUNT_MISMATCH",
                                        "message": (
                                            f"manifest={entry_count} archive={len(archived)}"
                                        ),
                                    }
                                )
                            expected_hash = archive_meta.get("sha256")
                            if (
                                isinstance(expected_hash, str)
                                and len(expected_hash) == 64
                                and _sha256(archive_path) != expected_hash
                            ):
                                findings.append(
                                    {
                                        "code": "FILES_ARCHIVE_HASH_MISMATCH",
                                        "message": str(archive_path),
                                    }
                                )
                        except (OSError, ValueError, json.JSONDecodeError) as exc:
                            findings.append(
                                {
                                    "code": "FILES_ARCHIVE_META_INVALID",
                                    "message": str(exc),
                                }
                            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            findings.append({"code": "FILE_MANIFEST_INVALID", "message": str(exc)})

    return {
        "schema_version": "hct408-backup-validation/v1",
        "passed": not findings,
        "decision": "BACKUP_READY_FOR_RESTORE" if not findings else "BLOCK_RESTORE",
        "backup_id": (version or {}).get("backup_id"),
        "migration_head": (version or {}).get("migration_head"),
        "file_count": len((file_manifest or {}).get("files", [])),
        "findings": findings,
        "limitations": [
            "Validation does not modify the database by itself.",
            "MySQL restore still requires a running Compose db service.",
            "A successful manifest check does not replace an independent R3 review.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--file-root", type=Path)
    parser.add_argument("--expected-migration-head")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = validate_backup(
        args.backup,
        file_root=args.file_root,
        expected_migration_head=args.expected_migration_head,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
