"""Collect local evidence for HCT-405 without claiming final acceptance.

The report separates automated synthetic checks from the real-camera, released
model, restart and independent-R3 evidence that the final gate still requires.
It is safe to run during a demo because it only performs health reads and
pytest checks; it never creates health events or face credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "hct405-local-evidence.json"
AUTOMATED_TESTS = (
    "tests/e2e/test_hct405_core_flows.py",
    "tests/e2e/test_hct405_vision_review_release.py",
    "tests/e2e/test_hct405_portal_continuous.py",
    "tests/e2e/test_hct405_member_risk_loop.py",
    "tests/e2e/test_hct405_family_login.py",
    "tests/integration/test_hct413_risk_ack.py",
)


def probe(url: str, path: str) -> dict[str, object]:
    target = f"{url.rstrip('/')}{path}"
    request = Request(target, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=5) as response:
            body = response.read(4096)
            return {
                "result": "PASS" if 200 <= response.status < 300 else "BLOCK",
                "status_code": response.status,
                "evidence_ref": target,
                "body_sha256": hashlib.sha256(body).hexdigest(),
            }
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return {
            "result": "BLOCK",
            "evidence_ref": target,
            "error_type": type(exc).__name__,
        }


def run_automated_tests() -> dict[str, object]:
    uv = shutil.which("uv")
    command = ([uv, "run", "pytest", "-q", *AUTOMATED_TESTS] if uv else [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        *AUTOMATED_TESTS,
    ])
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    combined = (completed.stdout + "\n" + completed.stderr).strip()
    return {
        "result": "PASS" if completed.returncode == 0 else "BLOCK",
        "returncode": completed.returncode,
        "command": command,
        "output_tail": combined[-4000:],
        "synthetic_only": True,
    }


def collect_evidence(
    *,
    api_url: str,
    web_url: str,
    run_tests: bool = True,
) -> dict[str, object]:
    health = {
        "api": probe(api_url, "/health"),
        "api_database": probe(api_url, "/api/v1/health/db"),
        "api_capabilities": probe(api_url, "/api/v1/meta/capabilities"),
        "web": probe(web_url, "/health"),
    }
    automated = run_automated_tests() if run_tests else {"result": "SKIPPED"}
    return {
        "schema_version": "hct405-local-evidence/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "local-automated-and-health-only",
        "health": health,
        "automated_tests": automated,
        "manual_or_external_evidence_required": [
            "real dynamic camera registration and family 1:N recognition",
            "released model on an approved fixed set",
            "restart and offline degradation drill against the deployed stack",
            "cross-team R3 review and project-owner sign-off",
        ],
        "decision": "LOCAL_EVIDENCE_COLLECTED_NOT_ACCEPTANCE",
        "limitations": [
            "This report intentionally cannot satisfy scripts/hct405_acceptance_gate.py.",
            "No face image, video, health payload, model weight or secret is recorded.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--web-url", default="http://127.0.0.1:5173")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    report = collect_evidence(
        api_url=args.api_url,
        web_url=args.web_url,
        run_tests=not args.skip_tests,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["automated_tests"].get("result") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
