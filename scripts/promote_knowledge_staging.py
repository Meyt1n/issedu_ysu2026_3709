#!/usr/bin/env python3
"""Review / promote staged knowledge drafts into approved/incoming."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "src" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

from app.knowledge_crawl import (  # noqa: E402
    list_staging,
    mark_staging_reviewed,
    promote_approved_staging,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List staging documents")

    review = sub.add_parser("review", help="Mark a staging doc reviewed/approved")
    review.add_argument("--source-id", required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--notes", default="")
    review.add_argument("--approve", action="store_true")
    review.add_argument("--reject", action="store_true")

    promote = sub.add_parser("promote", help="Promote approved staging into approved/incoming")
    promote.add_argument("--actor-id", default="knowledge-steward")

    args = parser.parse_args(argv)
    if args.command == "list":
        print(json.dumps(list_staging(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "review":
        meta = mark_staging_reviewed(
            args.source_id,
            reviewer=args.reviewer,
            notes=args.notes,
            approve=args.approve,
            reject=args.reject,
        )
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return 0
    report = promote_approved_staging(actor_id=args.actor_id)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
