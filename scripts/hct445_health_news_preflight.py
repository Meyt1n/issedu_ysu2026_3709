#!/usr/bin/env python3
"""Offline preflight for HCT-445 health-news allowlist configuration.

Does not perform live fetches unless --live is passed.  Offline mode only
checks HTTPS URLs, allowlist membership, and built-in source activation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "api"))

from app.config import get_settings  # noqa: E402
from app.egress_guard import is_health_news_egress_allowed  # noqa: E402
from app.health_news_adapter import builtin_source_catalog, resolve_active_sources  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually GET active source list URLs (requires network + allowlist).",
    )
    args = parser.parse_args()
    settings = get_settings()
    mode = (settings.health_news_adapter or "local").strip().casefold()
    print(f"adapter={mode}")
    print(f"allowlist={sorted(settings.health_news_allowed_domain_set)}")
    print(f"built_in_sources={len(builtin_source_catalog())}")

    if mode != "enabled":
        print("OK: local/disabled mode — no egress expected.")
        return 0

    if not settings.health_news_allowed_domain_set:
        print("FAIL: HEALTH_NEWS_ALLOWED_DOMAINS is empty while adapter=enabled")
        return 2

    active = resolve_active_sources(settings)
    if not active:
        print("FAIL: no built-in/extra sources match the allowlist")
        return 2

    for source in active:
        allowed = is_health_news_egress_allowed(source.list_url)
        print(f"source={source.id} url={source.list_url} egress_allowed={allowed}")
        if not allowed:
            print("FAIL: active source blocked by egress guard")
            return 2
        if not source.list_url.lower().startswith("https://"):
            print("FAIL: source URL must be HTTPS")
            return 2

    if not args.live:
        print("OK: offline preflight passed (no live fetch).")
        return 0

    import asyncio

    import httpx

    async def _live() -> int:
        for source in active:
            async with httpx.AsyncClient(timeout=settings.health_news_timeout_seconds) as client:
                response = await client.get(source.list_url)
            print(
                f"live source={source.id} "
                f"status={response.status_code} "
                f"bytes={len(response.content)}"
            )
            if response.status_code >= 400:
                return 3
        print("OK: live preflight passed.")
        return 0

    return asyncio.run(_live())


if __name__ == "__main__":
    raise SystemExit(main())
