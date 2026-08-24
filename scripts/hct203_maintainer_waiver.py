"""Validate an explicit maintainer waiver for HCT-203 auxiliary publication.

The waiver is a controlled exception to the formal fixed-set, external-weight
verification and separate R3-record prerequisites. It does not erase the
candidate's limitations or enable the household runtime. The current model
registry remains an immutable experimental record; a separate publication
manifest records the exception.
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
WAIVED_REQUIREMENTS = {
    "approved_real_fixed_set",
    "external_weights_verification",
    "independent_r3_record",
}


def evaluate_maintainer_waiver(
    waiver: dict[str, Any],
    *,
    registry: dict[str, Any],
    rollback: dict[str, Any],
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    if waiver.get("schema_version") != "hct203-maintainer-waiver/v1":
        findings.append(
            {"code": "WAIVER_SCHEMA_INVALID", "message": "expected hct203-maintainer-waiver/v1"}
        )
    if waiver.get("approved") is not True:
        findings.append({"code": "WAIVER_NOT_APPROVED", "message": "approved=true is required"})
    approved_by = waiver.get("approved_by")
    if not isinstance(approved_by, str) or not approved_by.strip():
        findings.append({"code": "WAIVER_APPROVER_MISSING", "message": "approved_by is required"})
    approved_at = waiver.get("approved_at")
    if not isinstance(approved_at, str) or not approved_at.strip():
        findings.append({"code": "WAIVER_DATE_MISSING", "message": "approved_at is required"})
    model_id = registry.get("model_id")
    if waiver.get("model_id") != model_id:
        findings.append(
            {"code": "WAIVER_MODEL_MISMATCH", "message": "waiver model_id differs from registry"}
        )
    waived = waiver.get("waived_requirements")
    if not isinstance(waived, list) or set(waived) != WAIVED_REQUIREMENTS:
        findings.append(
            {
                "code": "WAIVER_SCOPE_INVALID",
                "message": "waiver must cover exactly the three approved prerequisites",
            }
        )
    if waiver.get("risk_acknowledged") is not True:
        findings.append(
            {
                "code": "WAIVER_RISK_NOT_ACKNOWLEDGED",
                "message": "risk_acknowledged=true is required",
            }
        )
    if waiver.get("runtime_scope") != "AUXILIARY_ONLY":
        findings.append(
            {
                "code": "WAIVER_RUNTIME_SCOPE_INVALID",
                "message": "runtime_scope must be AUXILIARY_ONLY",
            }
        )
    if waiver.get("hard_negative_disclosure") != "VISIBLE":
        findings.append(
            {
                "code": "WAIVER_HARD_NEGATIVE_DISCLOSURE_MISSING",
                "message": "hard-negative disclosure must remain visible",
            }
        )
    if waiver.get("rollback_required") is not True:
        findings.append(
            {"code": "WAIVER_ROLLBACK_REQUIRED", "message": "rollback remains mandatory"}
        )
    if rollback.get("rollback_tested") is not True or rollback.get("restore_verified") is not True:
        findings.append(
            {
                "code": "ROLLBACK_NOT_VERIFIED",
                "message": "rollback evidence must pass even under waiver",
            }
        )
    if registry.get("release_status") not in {"EXPERIMENTAL_UNRELEASED", "CANDIDATE_REVIEW"}:
        findings.append(
            {
                "code": "REGISTRY_STATUS_INVALID",
                "message": "source registry must remain an unreleased candidate",
            }
        )
    weights_sha256 = registry.get("artifacts", {}).get("weights_sha256")
    if not isinstance(weights_sha256, str) or SHA256_RE.fullmatch(weights_sha256) is None:
        findings.append(
            {
                "code": "WEIGHTS_HASH_MISSING",
                "message": "registered candidate weight hash is required",
            }
        )

    passed = not findings
    return {
        "schema_version": "hct203-maintainer-waiver-gate/v1",
        "model_id": model_id,
        "approved_by": approved_by,
        "approved_at": approved_at,
        "waived_requirements": sorted(WAIVED_REQUIREMENTS),
        "passed": passed,
        "decision": "MAINTAINER_WAIVER_APPROVED" if passed else "MAINTAINER_WAIVER_BLOCKED",
        "findings": findings,
        "limitations": [
            "This is an explicit maintainer exception, not a formal fixed-set or R3 validation.",
            "The candidate weight is identified by its registered hash but is not verified "
            "from a local artifact here.",
            "The two registered hard-negative false positives remain visible and block "
            "medicine identity decisions.",
            "Publication remains auxiliary-only, requires manual confirmation and keeps "
            "the unavailable fallback.",
        ],
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: JSON root must be an object")
    return value


def _report_hash(report: dict[str, Any]) -> str:
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--waiver", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--rollback", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = evaluate_maintainer_waiver(
            _load(args.waiver),
            registry=_load(args.registry),
            rollback=_load(args.rollback),
        )
        report["input_sha256"] = {
            "waiver": hashlib.sha256(args.waiver.read_bytes()).hexdigest(),
            "registry": hashlib.sha256(args.registry.read_bytes()).hexdigest(),
            "rollback": hashlib.sha256(args.rollback.read_bytes()).hexdigest(),
        }
        report["report_sha256"] = _report_hash(report)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema_version": "hct203-maintainer-waiver-gate/v1",
            "passed": False,
            "decision": "MAINTAINER_WAIVER_BLOCKED",
            "findings": [{"code": "INPUT_ERROR", "message": str(exc)}],
        }
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report.get("passed") is True else 1


if __name__ == "__main__":
    sys.exit(main())
