"""Gate the final HCT-405 continuous demo and offline deployment evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_SCENARIOS = {
    "family_login_to_member_context",
    "vision_scan_to_manual_confirm",
    "confirmed_event_to_rule_alert",
    "assistant_evidence_explanation",
    "offline_restart_degradation",
}


def evaluate(trace: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    scenarios = trace.get("scenarios")
    by_id = {
        str(item.get("scenario_id")): item
        for item in scenarios or []
        if isinstance(item, dict) and item.get("scenario_id")
    }
    for scenario_id in sorted(REQUIRED_SCENARIOS):
        item = by_id.get(scenario_id)
        if not item or item.get("result") != "PASS":
            findings.append(
                {"code": "SCENARIO_NOT_PASSED", "message": f"missing or failed {scenario_id}"}
            )
        elif not str(item.get("evidence_ref", "")).strip():
            findings.append(
                {
                    "code": "SCENARIO_EVIDENCE_MISSING",
                    "message": f"{scenario_id} evidence_ref is required",
                }
            )

    deployment = trace.get("deployment_drill")
    if (
        not isinstance(deployment, dict)
        or deployment.get("restart_verified") is not True
        or deployment.get("offline_degradation_verified") is not True
    ):
        findings.append(
            {
                "code": "DEPLOYMENT_DRILL_MISSING",
                "message": "restart and offline degradation must be verified",
            }
        )
    if trace.get("released_model_fixed_set_verified") is not True:
        findings.append(
            {
                "code": "RELEASED_MODEL_EVIDENCE_MISSING",
                "message": "released model on approved fixed set is required",
            }
        )
    if trace.get("cross_team_r3_review") is not True:
        findings.append(
            {"code": "R3_REVIEW_MISSING", "message": "cross-team R3 review is required"}
        )
    passed = not findings
    return {
        "schema_version": "hct405-core-acceptance/v1",
        "passed": passed,
        "decision": "ACCEPT_CORE_E2E" if passed else "BLOCK_CORE_E2E",
        "findings": findings,
        "limitations": [
            "Run the continuous line against deployed local API and web; unit tests "
            "do not satisfy this gate.",
            "No real health payload or model weight belongs in the committed trace.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        value = json.loads(args.trace.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("trace root must be an object")
        report = evaluate(value)
        report["input_sha256"] = hashlib.sha256(args.trace.read_bytes()).hexdigest()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema_version": "hct405-core-acceptance/v1",
            "passed": False,
            "decision": "BLOCK_CORE_E2E",
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
