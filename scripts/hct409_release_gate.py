"""Gate the remaining HCT-409 backend publication evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def evaluate(record: dict[str, Any], *, max_vision_p95_ms: float = 8000.0) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    performance = record.get("api_perf")
    if not isinstance(performance, dict):
        findings.append({"code": "API_PERF_MISSING", "message": "api_perf is required"})
    else:
        for name in (
            "health_p95_ms",
            "db_p95_ms",
            "household_list_p95_ms",
            "vision_full_pipeline_p95_ms",
        ):
            value = performance.get(name)
            if not isinstance(value, (int, float)):
                findings.append({"code": "PERF_METRIC_MISSING", "message": f"missing {name}"})
        error_rate = performance.get("error_rate")
        if error_rate != 0:
            findings.append(
                {"code": "API_ERROR_RATE_NONZERO", "message": "api error_rate must be zero"}
            )
        vision_p95 = performance.get("vision_full_pipeline_p95_ms")
        if isinstance(vision_p95, (int, float)) and vision_p95 > max_vision_p95_ms:
            findings.append(
                {
                    "code": "VISION_P95_TOO_HIGH",
                    "message": "vision full-pipeline P95 exceeds threshold",
                }
            )

    required_flags = {
        "security_regression_passed": "security regression",
        "privacy_delete_propagation_passed": "privacy/delete propagation",
        "red_team_passed": "red-team regression",
        "dependency_audit_passed": "dependency audit",
        "manual_screen_reader_passed": "manual screen-reader review",
        "project_lead_signoff": "project-lead sign-off",
        "independent_r3_review": "independent R3 review",
    }
    for field, label in required_flags.items():
        if record.get(field) is not True:
            findings.append(
                {"code": "REVIEW_OR_REGRESSION_MISSING", "message": f"{label} is not passed"}
            )
    passed = not findings
    return {
        "schema_version": "hct409-release-gate/v1",
        "passed": passed,
        "decision": "READY_FOR_R3_REVIEW" if passed else "BLOCK_HCT409_RELEASE",
        "findings": findings,
        "limitations": [
            "Metrics must come from the frozen release environment with command/output hashes.",
            "A passing machine gate does not replace the project-owner publication decision.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--max-vision-p95-ms", type=float, default=8000.0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        value = json.loads(args.evidence.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("evidence root must be an object")
        report = evaluate(value, max_vision_p95_ms=args.max_vision_p95_ms)
        report["input_sha256"] = hashlib.sha256(args.evidence.read_bytes()).hexdigest()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema_version": "hct409-release-gate/v1",
            "passed": False,
            "decision": "BLOCK_HCT409_RELEASE",
            "findings": [{"code": "INPUT_ERROR", "message": str(exc)}],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
