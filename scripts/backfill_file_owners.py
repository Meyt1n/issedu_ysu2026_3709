#!/usr/bin/env python3
"""Backfill ownership sidecars for legacy uploaded files linked to vision tasks.

After the file-ownership hardening, objects without ``meta/<storage_key>`` are
fail-closed for key-only access. This script attributes each orphan file to the
``created_by`` of the oldest vision task that references it.

Usage (from repo root):

    uv run python scripts/backfill_file_owners.py --dry-run
    uv run python scripts/backfill_file_owners.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
for source_path in (REPO_ROOT / "src/api", REPO_ROOT / "src"):
    source = str(source_path)
    if source not in sys.path:
        sys.path.insert(0, source)

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.file_upload import file_owner, record_file_owner  # noqa: E402
from app.models import VisionTask  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned ownership writes without creating sidecars",
    )
    args = parser.parse_args()

    settings = get_settings()
    root = Path(settings.file_root).resolve()
    if not root.is_dir():
        print(f"file root missing: {root}", file=sys.stderr)
        return 1

    written = 0
    skipped = 0
    with SessionLocal() as session:
        tasks = session.scalars(
            select(VisionTask).order_by(VisionTask.created_at.asc())
        ).all()
        seen: set[str] = set()
        for task in tasks:
            key = task.file_id
            if not key or key in seen:
                continue
            seen.add(key)
            path = root / key
            if not path.is_file():
                skipped += 1
                continue
            if file_owner(key) is not None:
                skipped += 1
                continue
            owner = task.created_by
            print(f"{'DRY ' if args.dry_run else ''}owner={owner} key={key}")
            if not args.dry_run:
                record_file_owner(key, owner)
            written += 1

    print(f"done written={written} skipped={skipped} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
