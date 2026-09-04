"""Archive and restore HCT-408 FILE_ROOT contents with path-safe tar.gz.

The earlier HCT-408 backup only wrote a hash inventory. Restore therefore could
only *verify* existing files, not recover them after destruction. This module
closes that gap for the teaching / disposable drill path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

ARCHIVE_NAME = "files.tar.gz"
ARCHIVE_META_NAME = "files_archive.json"


def _safe_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if not normalized or candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"unsafe relative_path: {value}")
    return "/".join(candidate.parts)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_files_archive(file_root: Path, backup_path: Path) -> dict[str, Any]:
    """Write ``files.tar.gz`` plus a small archive metadata sidecar."""
    resolved = file_root.resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"FILE_ROOT_NOT_FOUND:{resolved}")

    backup_path.mkdir(parents=True, exist_ok=True)
    archive_path = backup_path / ARCHIVE_NAME
    members: list[dict[str, Any]] = []

    with tarfile.open(archive_path, "w:gz") as tar:
        for path in sorted(item for item in resolved.rglob("*") if item.is_file()):
            rel = path.relative_to(resolved).as_posix()
            _safe_relative_path(rel)
            tar.add(path, arcname=rel)
            members.append(
                {
                    "relative_path": rel,
                    "size": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )

    meta = {
        "schema_version": "hct408-files-archive/v1",
        "archive": ARCHIVE_NAME,
        "source_root": str(resolved),
        "total_files": len(members),
        "total_bytes": sum(int(item["size"]) for item in members),
        "sha256": _sha256(archive_path),
        "created_utc": datetime.now(UTC).isoformat(),
        "files": members,
    }
    (backup_path / ARCHIVE_META_NAME).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return meta


def restore_files_archive(
    backup_path: Path,
    file_root: Path,
    *,
    wipe_existing: bool = False,
) -> dict[str, Any]:
    """Extract ``files.tar.gz`` into ``file_root`` and verify hashes."""
    archive_path = backup_path / ARCHIVE_NAME
    if not archive_path.is_file() or archive_path.stat().st_size == 0:
        raise FileNotFoundError(f"FILES_ARCHIVE_MISSING:{archive_path}")

    resolved = file_root.resolve()
    if wipe_existing and resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)

    restored: list[str] = []
    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            rel = _safe_relative_path(member.name)
            target = resolved / Path(*rel.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = tar.extractfile(member)
            if extracted is None:
                raise RuntimeError(f"ARCHIVE_MEMBER_UNREADABLE:{rel}")
            with extracted, target.open("wb") as out:
                shutil.copyfileobj(extracted, out)
            restored.append(rel)

    meta_path = backup_path / ARCHIVE_META_NAME
    expected: dict[str, dict[str, Any]] = {}
    if meta_path.is_file():
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        for entry in payload.get("files", []):
            expected[entry["relative_path"]] = entry

    mismatches: list[str] = []
    for rel in restored:
        actual = resolved / Path(*rel.split("/"))
        digest = _sha256(actual)
        size = actual.stat().st_size
        wanted = expected.get(rel)
        if wanted and (wanted.get("sha256") != digest or wanted.get("size") != size):
            mismatches.append(rel)

    if mismatches:
        raise RuntimeError("FILE_RESTORE_HASH_MISMATCH:" + ",".join(mismatches))

    return {
        "schema_version": "hct408-files-restore/v1",
        "file_root": str(resolved),
        "restored_files": len(restored),
        "mismatches": mismatches,
        "passed": True,
        "restored_utc": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Create files.tar.gz from FILE_ROOT")
    create.add_argument("--root", required=True, type=Path)
    create.add_argument("--backup", required=True, type=Path)

    restore = sub.add_parser("restore", help="Restore FILE_ROOT from files.tar.gz")
    restore.add_argument("--backup", required=True, type=Path)
    restore.add_argument("--file-root", required=True, type=Path)
    restore.add_argument("--wipe-existing", action="store_true")

    args = parser.parse_args()
    if args.command == "create":
        meta = create_files_archive(args.root, args.backup)
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return 0

    report = restore_files_archive(
        args.backup,
        args.file_root,
        wipe_existing=args.wipe_existing,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
