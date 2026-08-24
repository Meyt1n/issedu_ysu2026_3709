"""Verify an HCT-203 model-binding rollback drill from API snapshots.

The drill is intentionally separate from the application API. The operator
activates a candidate through the existing model-version-binding endpoints,
captures a before snapshot, calls the rollback endpoint, captures an after
snapshot, and then runs this command. It produces path-free evidence and never
changes a binding itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: JSON root must be an object")
    return value


def _active_model_version(snapshot: dict[str, Any]) -> str | None:
    active = snapshot.get("active_model_version")
    if isinstance(active, str) and active.strip():
        return active.strip()
    bindings = snapshot.get("bindings")
    if not isinstance(bindings, list):
        return None
    active_bindings = [
        item
        for item in bindings
        if isinstance(item, dict) and item.get("release_status") == "active"
    ]
    if len(active_bindings) != 1:
        return None
    model_id = active_bindings[0].get("model_id")
    return model_id.strip() if isinstance(model_id, str) and model_id.strip() else None


def evaluate_rollback_drill(
    *,
    before: dict[str, Any],
    after: dict[str, Any],
    current_version: str,
    previous_version: str,
    reason: str,
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    before_active = _active_model_version(before)
    after_active = _active_model_version(after)
    if before_active != current_version:
        findings.append(
            {
                "code": "BEFORE_SNAPSHOT_MISMATCH",
                "message": "before snapshot does not show the candidate as active",
            }
        )
    if after_active != previous_version:
        findings.append(
            {
                "code": "PREVIOUS_VERSION_NOT_RESTORED",
                "message": "after snapshot does not show the previous version as active",
            }
        )

    revoked_current = False
    restored_previous = False
    for item in after.get("bindings", []):
        if not isinstance(item, dict):
            continue
        model_id = item.get("model_id")
        status = item.get("release_status")
        if model_id == current_version and status == "revoked":
            revoked_current = True
        if model_id == previous_version and status == "active":
            restored_previous = True
    if "bindings" in after and not revoked_current:
        findings.append(
            {
                "code": "CURRENT_VERSION_NOT_REVOKED",
                "message": "after snapshot does not show the candidate as revoked",
            }
        )
    if "bindings" in after and not restored_previous:
        findings.append(
            {
                "code": "RESTORED_BINDING_MISSING",
                "message": "after snapshot does not show the previous binding restored",
            }
        )
    if not reason.strip():
        findings.append({"code": "ROLLBACK_REASON_MISSING", "message": "reason is required"})

    passed = not findings
    return {
        "schema_version": "hct203-rollback-drill/v1",
        "current_version": current_version,
        "previous_version": previous_version,
        "rollback_endpoint": "/api/v1/model-version-bindings/{binding_id}/rollback",
        "reason": reason,
        "rollback_tested": True,
        "restore_verified": passed,
        "decision": "ROLLBACK_VERIFIED" if passed else "ROLLBACK_BLOCKED",
        "findings": findings,
        "limitations": [
            "Snapshots must be captured from the same isolated environment and release database.",
            "This evidence verifies binding restoration; it does not copy or inspect "
            "model weights.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--current-version", required=True)
    parser.add_argument("--previous-version", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = evaluate_rollback_drill(
            before=_load(args.before),
            after=_load(args.after),
            current_version=args.current_version,
            previous_version=args.previous_version,
            reason=args.reason,
        )
        report["input_sha256"] = {
            "before": hashlib.sha256(args.before.read_bytes()).hexdigest(),
            "after": hashlib.sha256(args.after.read_bytes()).hexdigest(),
        }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema_version": "hct203-rollback-drill/v1",
            "rollback_tested": False,
            "restore_verified": False,
            "decision": "ROLLBACK_BLOCKED",
            "findings": [{"code": "INPUT_ERROR", "message": str(exc)}],
        }
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report.get("restore_verified") is True else 1


if __name__ == "__main__":
    sys.exit(main())
