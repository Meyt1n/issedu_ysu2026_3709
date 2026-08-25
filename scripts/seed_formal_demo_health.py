#!/usr/bin/env python3
"""Seed interconnected synthetic health events for formal demo accounts.

Targets the classroom household created by scripts/prepare-family-demo.ps1
(demo-parent / grandpa-demo / grandma-demo). All facts are fiction labelled
「演示」; no real patient data.

Usage:
  # After API is up and prepare-family-demo has created the household:
  uv run python scripts/seed_formal_demo_health.py \\
    --base http://127.0.0.1:8000 \\
    --password 'DemoOnly-ChangeMe!'

  # Dev-header mode (ALLOW_DEV_ACTOR_HEADER=true):
  uv run python scripts/seed_formal_demo_health.py --base http://127.0.0.1:8000 --dev-header
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from formal_demo_health_plan import (  # noqa: E402
    FORMAL_DEMO_HEALTH_EVENTS,
    FORMAL_GRANDMA_ACTOR_ID,
    FORMAL_GRANDPA_ACTOR_ID,
    FORMAL_HOUSEHOLD_NAME,
    FORMAL_OWNER_ACTOR_ID,
    FORMAL_OWNER_PASSWORD_DEFAULT,
    expected_graph_labels,
)


class ApiError(RuntimeError):
    def __init__(self, status: int, body: str, path: str) -> None:
        super().__init__(f"HTTP {status} {path}: {body[:400]}")
        self.status = status
        self.body = body


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
        with urllib.request.urlopen(req, timeout=30) as response:
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
    token = login["session_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Access-Purpose": "family-care",
    }


def _resolve_household(base: str, headers: dict[str, str]) -> dict[str, Any]:
    households = _request(base, "/api/v1/households", headers=headers) or []
    owned = [
        item
        for item in households
        if item.get("name") == FORMAL_HOUSEHOLD_NAME
        and item.get("created_by") == FORMAL_OWNER_ACTOR_ID
    ]
    if owned:
        return owned[0]
    named = [item for item in households if item.get("name") == FORMAL_HOUSEHOLD_NAME]
    if named:
        return named[0]
    return _request(
        base,
        "/api/v1/households",
        method="POST",
        headers=headers,
        body={"name": FORMAL_HOUSEHOLD_NAME, "time_zone": "Asia/Shanghai"},
    )


def _resolve_members(
    base: str, headers: dict[str, str], household_id: str
) -> dict[str, dict[str, Any]]:
    members = (
        _request(base, f"/api/v1/households/{household_id}/members", headers=headers)
        or []
    )
    by_key: dict[str, dict[str, Any]] = {}
    for member in members:
        actor = member.get("actor_id")
        name = member.get("display_name")
        if actor == FORMAL_GRANDMA_ACTOR_ID or name == "奶奶":
            by_key["grandma"] = member
        elif actor == FORMAL_GRANDPA_ACTOR_ID or name == "爷爷":
            by_key["grandpa"] = member
    desired = {
        "grandma": {
            "display_name": "奶奶",
            "role": "DEPENDENT",
            "actor_id": FORMAL_GRANDMA_ACTOR_ID,
        },
        "grandpa": {
            "display_name": "爷爷",
            "role": "DEPENDENT",
            "actor_id": FORMAL_GRANDPA_ACTOR_ID,
        },
    }
    for key, body in desired.items():
        if key in by_key:
            continue
        by_key[key] = _request(
            base,
            f"/api/v1/households/{household_id}/members",
            method="POST",
            headers=headers,
            body=body,
        )
    return by_key


def seed_formal_demo_health(
    *,
    base: str,
    password: str = FORMAL_OWNER_PASSWORD_DEFAULT,
    use_dev_header: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    health = _request(base, "/health")
    if not health or health.get("status") != "ok":
        raise RuntimeError(f"API health check failed: {health}")

    headers = _auth_headers(base, password=password, use_dev_header=use_dev_header)
    household = _resolve_household(base, headers)
    members = _resolve_members(base, headers, household["id"])

    created: list[str] = []
    skipped: list[str] = []
    for spec in FORMAL_DEMO_HEALTH_EVENTS:
        member = members[spec["member_key"]]
        body = {
            "member_id": member["id"],
            "event_type": spec["event_type"],
            "source": "MANUAL",
            "confirmation_status": "CONFIRMED",
            "payload": spec["payload"],
            "idempotency_key": spec["idempotency_key"],
        }
        if dry_run:
            skipped.append(spec["idempotency_key"])
            continue
        try:
            event = _request(
                base,
                f"/api/v1/households/{household['id']}/events",
                method="POST",
                headers=headers,
                body=body,
            )
            created.append(event["id"])
        except ApiError as exc:
            # Idempotent replay often returns 200/201 with same key; some
            # builds may reject duplicates — treat conflict as skip.
            if exc.status in {409, 422} and "idempotency" in exc.body.lower():
                skipped.append(spec["idempotency_key"])
                continue
            # If key already stored, API may return the original event as 201
            # again; any other error still fails loudly.
            raise

    report = {
        "ok": True,
        "household_id": household["id"],
        "household_name": household["name"],
        "members": {
            key: {
                "id": value["id"],
                "display_name": value.get("display_name"),
                "actor_id": value.get("actor_id"),
            }
            for key, value in members.items()
        },
        "events_planned": len(FORMAL_DEMO_HEALTH_EVENTS),
        "events_created_or_returned": len(created),
        "dry_run_skipped": skipped if dry_run else [],
        "expected_graph": {
            key: {kind: sorted(labels) for kind, labels in kinds.items()}
            for key, kinds in expected_graph_labels().items()
        },
        "disclaimer": "全部为虚构教学演示数据，禁止用于诊疗，不含真实健康信息。",
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--password", default=FORMAL_OWNER_PASSWORD_DEFAULT)
    parser.add_argument(
        "--dev-header",
        action="store_true",
        help="Use X-Actor-Id instead of password login",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    report = seed_formal_demo_health(
        base=args.base,
        password=args.password,
        use_dev_header=args.dev_header,
        dry_run=args.dry_run,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
