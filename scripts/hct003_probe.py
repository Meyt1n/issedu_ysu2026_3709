from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "src" / "api"))

from ai.vision.resource_probe import probe_visual_sample  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.resource_probes import probe_mysql, probe_ollama  # noqa: E402

DEFAULT_SAMPLE = REPO_ROOT / "tests" / "fixtures" / "hct003" / "visual_probe_sample.json"


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run reproducible HCT-003 resource probes.")
    parser.add_argument("resource", choices=("mysql", "vision", "ollama", "all"))
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--image", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--base-url", default=settings.ollama_base_url)
    parser.add_argument("--model", default=settings.ollama_model)
    parser.add_argument("--timeout", type=float, default=settings.ollama_timeout_seconds)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return a non-zero exit code when any selected probe is not ok.",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    if args.resource in {"mysql", "all"}:
        reports["mysql"] = probe_mysql(args.database_url)
    if args.resource in {"vision", "all"}:
        reports["vision"] = probe_visual_sample(args.image)
    if args.resource in {"ollama", "all"}:
        reports["ollama"] = probe_ollama(
            args.base_url,
            args.model,
            timeout=args.timeout,
        )
    return reports


def main() -> int:
    args = parse_args()
    reports = run(args)
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    if args.strict and any(report["status"] != "ok" for report in reports.values()):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
