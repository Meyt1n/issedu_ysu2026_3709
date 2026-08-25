#!/usr/bin/env python3
"""Seed interconnected synthetic health events for formal demo accounts.

Prefer the in-API endpoint so Web「演示造数」与 CLI 共用同一套幂等逻辑。

Usage:
  uv run python scripts/seed_formal_demo_health.py --base http://127.0.0.1:8000
  uv run python scripts/seed_formal_demo_health.py --base http://127.0.0.1:8000 --dev-header
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Any

from formal_demo_health_plan import (
    FORMAL_OWNER_ACTOR_ID,
    FORMAL_OWNER_PASSWORD_DEFAULT,
)


class ApiError(RuntimeError):
    def __init__(self, status: int, body: str, path: str) -> None:
        super().__init__(f"HTTP {status} {path}: {body[:400]}")
        self.status = status


def _request(
    base: str,
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{base.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise ApiError(exc.code, raw, path) from exc


def _auth_headers(base: str, *, password: str, use_dev_header: bool) -> dict[str, str]:
    if use_dev_header:
        return {
            "X-Actor-Id": FORMAL_OWNER_ACTOR_ID,
            "X-Access-Purpose": "family-care",
        }
    try:
        _request(
            base,
            "/api/v1/auth/register",
            method="POST",
            body={"actor_id": FORMAL_OWNER_ACTOR_ID, "password": password},
        )
    except ApiError as exc:
        if exc.status != 409:
            raise
    login = _request(
        base,
        "/api/v1/auth/login",
        method="POST",
        body={"actor_id": FORMAL_OWNER_ACTOR_ID, "password": password},
    )
    return {
        "Authorization": f"Bearer {login['session_token']}",
        "X-Access-Purpose": "family-care",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--password", default=FORMAL_OWNER_PASSWORD_DEFAULT)
    parser.add_argument("--dev-header", action="store_true")
    args = parser.parse_args(argv)
    health = _request(args.base, "/health")
    if not health or health.get("status") != "ok":
        raise SystemExit(f"API health check failed: {health}")
    headers = _auth_headers(
        args.base, password=args.password, use_dev_header=args.dev_header
    )
    report = _request(
        args.base,
        "/api/v1/demo/formal-health-seed",
        method="POST",
        headers=headers,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
