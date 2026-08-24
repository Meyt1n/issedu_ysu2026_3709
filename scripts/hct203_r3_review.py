"""Validate the human R3 review record for an HCT-203 release candidate.

The machine gate only says that evidence is ready for review. This command
checks a separately authored, human-readable R3 decision and still does not
activate a runtime model. A real reviewer must provide the record; synthetic
fixtures are useful for testing the contract but cannot close HCT-203.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_CONFIRMATIONS = (
    "dataset_approval_confirmed",
    "independent_evaluation_confirmed",
    "hard_negative_confirmed",
    "rollback_confirmed",
    "runtime_scope_confirmed",
    "limitations_acknowledged",
)


def evaluate_r3_review(machine_gate: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    if (
        machine_gate.get("passed") is not True
        or machine_gate.get("decision") != "READY_FOR_R3_REVIEW"
    ):
        findings.append(
            {
                "code": "MACHINE_GATE_NOT_READY",
                "message": "the HCT-203 machine gate must pass before R3 review",
            }
        )
    if review.get("schema_version") != "hct203-r3-review/v1":
        findings.append(
            {"code": "REVIEW_SCHEMA_INVALID", "message": "expected hct203-r3-review/v1"}
        )
    for field in ("reviewer_id", "reviewed_at"):
        value = review.get(field)
        if not isinstance(value, str) or not value.strip():
            findings.append({"code": "REVIEW_FIELD_MISSING", "message": f"{field} is required"})
    if review.get("scope_confirmed") is not True:
        findings.append(
            {"code": "REVIEW_FIELD_MISSING", "message": "scope_confirmed is required"}
        )
    if review.get("decision") != "APPROVE_RELEASE":
        findings.append(
            {
                "code": "R3_NOT_APPROVED",
                "message": "R3 decision must be APPROVE_RELEASE",
            }
        )
    for field in REQUIRED_CONFIRMATIONS:
        if review.get(field) is not True:
            findings.append({"code": "R3_CONFIRMATION_MISSING", "message": f"{field} must be true"})
    gate_hash = review.get("machine_gate_report_sha256")
    if not isinstance(gate_hash, str) or not SHA256_RE.fullmatch(gate_hash):
        findings.append(
            {
                "code": "MACHINE_GATE_HASH_INVALID",
                "message": "machine_gate_report_sha256 must be a lowercase SHA-256",
            }
        )
    if review.get("reviewer_id") in {"", "TBD", "TODO", "unknown", "unknown-reviewer"}:
        findings.append(
            {"code": "REVIEWER_PLACEHOLDER", "message": "a real reviewer identity is required"}
        )

    passed = not findings
    return {
        "schema_version": "hct203-r3-review-gate/v1",
        "reviewer_id": review.get("reviewer_id"),
        "reviewed_at": review.get("reviewed_at"),
        "passed": passed,
        "decision": "R3_APPROVED" if passed else "R3_REVIEW_REQUIRED",
        "findings": findings,
        "limitations": [
            "This validator checks the signed/recorded checklist fields; it cannot "
            "establish reviewer identity.",
            "R3 approval remains a human action and is not a substitute for the "
            "independent test data.",
        ],
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: JSON root must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--machine-gate", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = evaluate_r3_review(_load(args.machine_gate), _load(args.review))
        report["input_sha256"] = {
            "machine_gate": hashlib.sha256(args.machine_gate.read_bytes()).hexdigest(),
            "review": hashlib.sha256(args.review.read_bytes()).hexdigest(),
        }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema_version": "hct203-r3-review-gate/v1",
            "passed": False,
            "decision": "R3_REVIEW_REQUIRED",
            "findings": [{"code": "INPUT_ERROR", "message": str(exc)}],
        }
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report.get("passed") is True else 1


if __name__ == "__main__":
    sys.exit(main())
