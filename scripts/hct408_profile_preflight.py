"""Static three-profile Compose preflight for HCT-408 (no Docker daemon).

Parses ``docker-compose.yml`` with PyYAML and checks that basic / enhanced / dev
service sets match the Story contract. This does **not** replace
``docker compose --profile <name> config`` or a live ``up --wait`` health run.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ROOT / "docker-compose.yml"

EXPECTED = {
    "basic": {
        "required": {"db", "api", "web", "outbox-worker", "care-plan-worker"},
        "forbidden": {"ollama"},
    },
    "enhanced": {
        "required": {"db", "api", "web", "outbox-worker", "care-plan-worker", "ollama"},
        "forbidden": set(),
    },
    "dev": {
        "required": {"db", "api", "web", "outbox-worker", "care-plan-worker", "ollama"},
        "forbidden": set(),
    },
}


def _services_for_profile(compose: dict[str, Any], profile: str) -> set[str]:
    selected: set[str] = set()
    for name, service in (compose.get("services") or {}).items():
        profiles = set(service.get("profiles") or [])
        # Compose includes services with no profiles in every invocation, and
        # services that list the requested profile.
        if not profiles or profile in profiles:
            selected.add(name)
    return selected


def run_preflight(compose_path: Path = COMPOSE_PATH) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    if not compose_path.is_file():
        return {
            "schema_version": "hct408-profile-preflight/v1",
            "passed": False,
            "decision": "BLOCK_PROFILES",
            "findings": [{"code": "COMPOSE_MISSING", "message": str(compose_path)}],
        }

    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    if not isinstance(compose, dict):
        return {
            "schema_version": "hct408-profile-preflight/v1",
            "passed": False,
            "decision": "BLOCK_PROFILES",
            "findings": [{"code": "COMPOSE_INVALID", "message": "root must be mapping"}],
        }

    profiles: dict[str, Any] = {}
    for profile, expectation in EXPECTED.items():
        services = sorted(_services_for_profile(compose, profile))
        missing = sorted(expectation["required"] - set(services))
        forbidden_hit = sorted(expectation["forbidden"] & set(services))
        profiles[profile] = {
            "services": services,
            "missing": missing,
            "forbidden_present": forbidden_hit,
        }
        for name in missing:
            findings.append({"code": f"{profile.upper()}_MISSING_{name.upper()}", "message": name})
        for name in forbidden_hit:
            findings.append(
                {"code": f"{profile.upper()}_FORBIDDEN_{name.upper()}", "message": name}
            )

    return {
        "schema_version": "hct408-profile-preflight/v1",
        "passed": not findings,
        "decision": "PROFILES_STATIC_OK" if not findings else "BLOCK_PROFILES",
        "compose_path": str(compose_path),
        "profiles": profiles,
        "findings": findings,
        "limitations": [
            "Static YAML parse only; does not execute docker compose config/up.",
            "Live health probes still require Docker and an operator-run drill.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose", type=Path, default=COMPOSE_PATH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_preflight(args.compose)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
