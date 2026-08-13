"""Compare runtime pip-audit findings against the HCT-409 allowlist.

Unexpected vulnerability IDs fail the gate. Allowlisted IDs must stay
documented with an owner and rollback; descriptions are never committed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = REPO_ROOT / "docs" / "reviews" / "hct409-pip-audit-allowlist.json"


def _uv() -> list[str]:
    """Resolve the uv binary, not `python -m uv` inside the project venv.

    `uv run python` prepends `.venv/Scripts` and leaves the venv interpreter
    without the uv module. Prefer a real `uv`/`uv.exe` on PATH or a user install.
    """
    found = shutil.which("uv") or shutil.which("uv.exe")
    if found:
        return [found]
    home = Path.home()
    user_bins = [
        *sorted(
            (home / "AppData" / "Roaming" / "Python").glob("Python*/Scripts/uv.exe"),
            reverse=True,
        ),
        home / ".local" / "bin" / "uv",
        home / ".local" / "bin" / "uv.exe",
        home / ".cargo" / "bin" / "uv",
        home / ".cargo" / "bin" / "uv.exe",
    ]
    for candidate in user_bins:
        if candidate.is_file():
            return [str(candidate)]
    raise RuntimeError("UV_NOT_FOUND")


def load_allowlist(path: Path = ALLOWLIST_PATH) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    allowed: dict[str, dict] = {}
    for item in payload["items"]:
        vuln_id = item["id"]
        if vuln_id in allowed:
            raise ValueError(f"DUPLICATE_ALLOWLIST_ID:{vuln_id}")
        allowed[vuln_id] = item
    return allowed


def collect_finding_ids(audit: dict) -> set[str]:
    found: set[str] = set()
    for dependency in audit.get("dependencies", []):
        for vuln in dependency.get("vulns", []):
            vuln_id = vuln.get("id")
            if vuln_id:
                found.add(str(vuln_id))
    return found


def run_pip_audit(requirements: Path) -> dict:
    result = subprocess.run(
        _uv()
        + [
            "tool",
            "run",
            "pip-audit",
            "-r",
            str(requirements),
            "--format",
            "json",
            "--progress-spinner",
            "off",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    raw = result.stdout.strip() or result.stderr.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"PIP_AUDIT_JSON_INVALID:{raw[:200]}") from exc


def evaluate(audit: dict, allowlist: dict[str, dict]) -> tuple[list[str], list[str]]:
    found = collect_finding_ids(audit)
    unexpected = sorted(found - set(allowlist))
    stale = sorted(set(allowlist) - found)
    return unexpected, stale


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allowlist", type=Path, default=ALLOWLIST_PATH)
    parser.add_argument("--requirements", type=Path, default=None)
    args = parser.parse_args()
    allowlist = load_allowlist(args.allowlist)

    if args.requirements is None:
        with tempfile.TemporaryDirectory() as tmp:
            reqs = Path(tmp) / "runtime-reqs.txt"
            subprocess.run(
                _uv()
                + [
                    "export",
                    "--frozen",
                    "--no-dev",
                    "--no-hashes",
                    "-o",
                    str(reqs),
                ],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            audit = run_pip_audit(reqs)
    else:
        audit = run_pip_audit(args.requirements)

    unexpected, stale = evaluate(audit, allowlist)
    if unexpected:
        print("UNEXPECTED_VULNS " + ",".join(unexpected), file=sys.stderr)
        return 1
    if stale:
        print("STALE_ALLOWLIST " + ",".join(stale), file=sys.stderr)
        return 1
    print(f"pip-audit allowlist matched {len(allowlist)} ids")
    return 0


if __name__ == "__main__":
    sys.exit(main())
