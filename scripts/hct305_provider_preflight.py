"""Preflight the explicitly allowlisted weather provider integration.

The default command is offline and only checks configuration.  ``--live``
performs one HTTPS request containing only a city/district code and validates
the provider response.  It never sends household, member or health fields.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

CODE_RE = re.compile(r"^\d{6}$")


def _host(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    return f"{host.lower()}:{parsed.port}" if parsed.port else host.lower()


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload


def _validate_payload(provider: str, payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["PROVIDER_RESPONSE_NOT_OBJECT"]
    body = _unwrap(payload)
    if not isinstance(body, dict):
        return ["PROVIDER_RESPONSE_DATA_NOT_OBJECT"]
    observations = {
        "temperature",
        "humidity",
        "weather",
        "condition",
        "wind",
        "wind_direction",
        "wind_power",
        "aqi",
    }
    if not observations.intersection(body):
        return ["NO_ENVIRONMENT_OBSERVATION"]
    findings: list[str] = []
    if provider == "uapis":
        if "weather" not in body:
            findings.append("UAPIS_WEATHER_FIELD_MISSING")
        if "report_time" not in body and "observed_at" not in body:
            findings.append("UAPIS_REPORT_TIME_MISSING")
    return findings


def preflight(
    *,
    provider: str,
    url: str,
    city_code: str,
    district_code: str,
    allowed_hosts: set[str],
    live: bool = False,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        findings.append({"code": "HTTPS_REQUIRED", "message": "weather provider must use HTTPS"})
    target_host = _host(url)
    if not target_host or target_host not in {item.lower() for item in allowed_hosts}:
        findings.append(
            {
                "code": "HOST_NOT_ALLOWLISTED",
                "message": "provider host is not in deployment allowlist",
            }
        )
    if provider not in {"uapis", "generic"}:
        findings.append(
            {"code": "INVALID_PROVIDER", "message": "provider must be uapis or generic"}
        )
    for name, value in (("city_code", city_code), ("district_code", district_code)):
        if value and not CODE_RE.fullmatch(value):
            findings.append(
                {"code": "INVALID_LOCATION_CODE", "message": f"{name} must be a six digit code"}
            )
    if not city_code and not district_code:
        findings.append(
            {"code": "LOCATION_REQUIRED", "message": "city_code or district_code is required"}
        )
    if findings or not live:
        passed = not findings
        return {
            "schema_version": "hct305-provider-preflight/v1",
            "provider": provider,
            "endpoint_host": target_host,
            "live_check": live,
            "request_fields": ["adcode"] if provider == "uapis" else ["city_code", "district_code"],
            "passed": passed,
            "decision": "READY_FOR_LIVE_PROVIDER" if passed else "BLOCK_WEATHER_PROVIDER",
            "findings": findings,
            "limitations": ["Offline preflight is not a real provider integration test."],
        }

    params = (
        {"adcode": district_code or city_code}
        if provider == "uapis"
        else {
            "city_code": city_code,
            "district_code": district_code,
        }
    )
    try:
        response = httpx.get(url, params=params, timeout=timeout_seconds, follow_redirects=False)
        if response.is_redirect or response.is_client_error or response.is_server_error:
            findings.append(
                {
                    "code": "HTTP_STATUS_REJECTED",
                    "message": f"provider returned HTTP {response.status_code}",
                }
            )
        else:
            findings.extend(
                {"code": code, "message": code}
                for code in _validate_payload(provider, response.json())
            )
    except (httpx.HTTPError, ValueError) as exc:
        findings.append({"code": "LIVE_REQUEST_FAILED", "message": str(exc)})
    passed = not findings
    return {
        "schema_version": "hct305-provider-preflight/v1",
        "provider": provider,
        "endpoint_host": target_host,
        "live_check": True,
        "request_fields": sorted(params),
        "passed": passed,
        "decision": "LIVE_PROVIDER_VERIFIED" if passed else "BLOCK_WEATHER_PROVIDER",
        "findings": findings,
        "limitations": [
            "One provider response is not enough; cache, retry, outage and monitoring "
            "still need HCT-305 tests."
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=("uapis", "generic"))
    parser.add_argument("--url", required=True)
    parser.add_argument("--city-code", default="")
    parser.add_argument("--district-code", default="")
    parser.add_argument("--allowed-host", action="append", default=[])
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = preflight(
        provider=args.provider,
        url=args.url,
        city_code=args.city_code,
        district_code=args.district_code,
        allowed_hosts=set(args.allowed_host),
        live=args.live,
        timeout_seconds=args.timeout_seconds,
    )
    report["config_sha256"] = hashlib.sha256(
        json.dumps(
            {
                "provider": args.provider,
                "url": args.url,
                "city_code": args.city_code,
                "district_code": args.district_code,
                "allowed_hosts": args.allowed_host,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return (
        0
        if report["passed"] and (args.live or report["decision"] == "READY_FOR_LIVE_PROVIDER")
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
