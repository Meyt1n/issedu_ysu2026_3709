"""Create a deterministic HCT-408 file inventory without copying file contents."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_manifest(root: Path) -> dict[str, object]:
    resolved = root.resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"FILE_ROOT_NOT_FOUND:{resolved}")
    entries: list[dict[str, object]] = []
    for path in sorted(item for item in resolved.rglob("*") if item.is_file()):
        entries.append(
            {
                "relative_path": path.relative_to(resolved).as_posix(),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
                "modified_utc": datetime.fromtimestamp(
                    path.stat().st_mtime, tz=UTC
                ).isoformat(),
            }
        )
    return {
        "source_root": str(resolved),
        "total_files": len(entries),
        "total_bytes": sum(int(item["size"]) for item in entries),
        "collected_utc": datetime.now(UTC).isoformat(),
        "files": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = create_manifest(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
