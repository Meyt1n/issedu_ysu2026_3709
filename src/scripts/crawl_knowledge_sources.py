#!/usr/bin/env python3
"""Crawl allowlisted knowledge sources into staging (never auto-ingests)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "src" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

from app.knowledge_crawl import list_staging, run_crawl  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Allow HTTPS fetches for enabled remote allowlist entries",
    )
    parser.add_argument(
        "--source-id",
        action="append",
        dest="source_ids",
        help="Limit to one or more source ids (repeatable)",
    )
    parser.add_argument(
        "--list-staging",
        action="store_true",
        help="Print current staging metadata and exit",
    )
    parser.add_argument(
        "--due-only",
        action="store_true",
        help="Only crawl sources past refresh_hours since last fetch",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print crawl ops status (due sources, staging) and exit",
    )
    args = parser.parse_args(argv)
    if args.list_staging:
        print(json.dumps(list_staging(), ensure_ascii=False, indent=2))
        return 0
    if args.status:
        from app.knowledge_crawl import crawl_ops_status

        print(json.dumps(crawl_ops_status(), ensure_ascii=False, indent=2))
        return 0
    report = run_crawl(
        live=args.live,
        source_ids=args.source_ids,
        due_only=args.due_only,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
