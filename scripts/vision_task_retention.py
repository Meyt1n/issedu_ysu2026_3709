"""Run the HCT-439 temporary-video retention pass.

The command is dry-run by default so it can be attached to a scheduler for a
preview first.  Use ``--execute`` only in the approved local deployment.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
for source_path in (REPO_ROOT / "src/api", REPO_ROOT / "src"):
    source = str(source_path)
    if source not in sys.path:
        sys.path.insert(0, source)

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Household  # noqa: E402
from app.vision_tasks import cleanup_expired_video_files  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview or execute video task retention cleanup")
    parser.add_argument("--execute", action="store_true", help="delete eligible file trees")
    parser.add_argument("--household-id", help="limit the pass to one household")
    parser.add_argument("--limit", type=int, help="maximum tasks per household")
    args = parser.parse_args()

    settings = get_settings()
    limit = args.limit or settings.vision_video_cleanup_batch_size
    if limit < 1 or limit > settings.vision_video_cleanup_batch_size:
        parser.error(f"--limit must be between 1 and {settings.vision_video_cleanup_batch_size}")

    with SessionLocal() as session:
        statement = select(Household.id).where(Household.deleted_at.is_(None))
        if args.household_id:
            statement = statement.where(Household.id == args.household_id)
        household_ids = list(session.scalars(statement).all())
        reports = []
        for household_id in household_ids:
            report = cleanup_expired_video_files(
                session,
                household_id,
                retention_seconds=settings.vision_video_retention_seconds,
                limit=limit,
                dry_run=not args.execute,
            )
            item = asdict(report)
            item["household_id"] = household_id
            item["cutoff_at"] = report.cutoff_at.isoformat()
            reports.append(item)

    print(
        json.dumps(
            {"dry_run": not args.execute, "reports": reports},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
