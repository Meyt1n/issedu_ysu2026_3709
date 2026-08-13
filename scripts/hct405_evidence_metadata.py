"""Write reproducible, non-sensitive metadata for HCT-405 CI evidence."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "hct405-environment.json"
API_COMMAND = (
    "uv run pytest tests/e2e/test_hct405_core_flows.py "
    "tests/e2e/test_hct405_failure_degradation.py "
    "tests/e2e/test_hct405_scenario_manifest.py "
    "tests/e2e/test_hct405_vision_review_release.py "
    "--junitxml=artifacts/hct405-api-junit.xml"
)
BROWSER_COMMAND = "npm run test:e2e:web"


def _git_sha() -> str:
    ci_sha = os.environ.get("GITHUB_SHA", "").strip()
    if ci_sha:
        return ci_sha
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _command_version(*command: str) -> str:
    try:
        result = subprocess.run(
            list(command),
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return "unavailable"
    output = result.stdout.strip() or result.stderr.strip()
    return output.splitlines()[0] if output else "unavailable"


def build_metadata() -> dict[str, object]:
    npm_command = "npm.cmd" if os.name == "nt" else "npm"
    return {
        "schema_version": "hct405-evidence-metadata-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "commit_sha": _git_sha(),
        "environment": {
            "ci": os.environ.get("CI", "").casefold() == "true",
            "runner_os": os.environ.get("RUNNER_OS") or platform.system(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "node": _command_version("node", "--version"),
            "npm": _command_version(npm_command, "--version"),
        },
        "data_policy": {
            "classification": "synthetic-only",
            "real_health_data": False,
            "secrets_recorded": False,
        },
        "scenario_manifest": "tests/e2e/hct405_scenarios.json",
        "reproduce": {
            "api": API_COMMAND,
            "browser": BROWSER_COMMAND,
            "full_backend": "uv run pytest",
            "frontend": [
                "npm run test:web",
                "npm run check:web",
                "npm run build:web",
            ],
        },
        "artifacts": {
            "api_junit": "artifacts/hct405-api-junit.xml",
            "browser_junit": "artifacts/hct405-browser-junit.xml",
            "browser_failures": ["test-results/", "playwright-report/"],
            "retention_days": 14,
        },
        "failure_reproduction": (
            "Use the matching reproduce command at this commit SHA; API cases use "
            "temporary SQLite/files, and browser failures retain trace, screenshot, "
            "and video when available."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="JSON output path (default: artifacts/hct405-environment.json)",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_metadata(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output.relative_to(REPO_ROOT) if output.is_relative_to(REPO_ROOT) else output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
