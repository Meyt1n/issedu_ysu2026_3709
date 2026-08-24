"""Run the approved severe/duplicate/interaction rule acceptance cases.

Cases are JSONL and contain only the facts needed by the deterministic rule
engine.  The report requires rule and master-data provenance; it does not let
an LLM decide a medication interaction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from app.rules import run_rules

ALLOWED_LEVELS = {"SEVERE", "WARNING", "INFO", "TIP"}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"line {line_number}: case must be an object")
        records.append(value)
    if not records:
        raise ValueError("rule case file is empty")
    return records


def evaluate_cases(
    records: list[dict[str, Any]], *, allow_synthetic: bool = False
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    passed_cases = 0
    case_results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, case in enumerate(records, start=1):
        case_id = str(case.get("case_id", "")).strip()
        prefix = f"case {index}"
        case_findings: list[str] = []
        if not case_id or case_id in seen_ids:
            case_findings.append("CASE_ID_MISSING_OR_DUPLICATE")
        seen_ids.add(case_id)
        if case.get("case_status") != "APPROVED":
            case_findings.append("CASE_NOT_APPROVED")
        scope = case.get("data_scope")
        if scope not in {"approved_rule_cases", "synthetic_fixture_only"}:
            case_findings.append("INVALID_DATA_SCOPE")
        if scope == "synthetic_fixture_only" and not allow_synthetic:
            case_findings.append("SYNTHETIC_NOT_ALLOWED")
        for field in ("rule_version", "master_data_version", "source_ref"):
            if not str(case.get(field, "")).strip():
                case_findings.append(f"MISSING_{field.upper()}")
        rule_id = str(case.get("rule_id", "")).strip()
        expected_level = str(case.get("expected_level", "")).strip().upper()
        if expected_level not in ALLOWED_LEVELS:
            case_findings.append("INVALID_EXPECTED_LEVEL")
        facts = case.get("facts")
        if not isinstance(facts, dict) or not rule_id:
            case_findings.append("FACTS_OR_RULE_MISSING")
            alerts = []
        else:
            alerts = run_rules(facts, rule_ids=[rule_id])
            expected_sources = {str(item) for item in case.get("expected_source_event_ids", [])}
            if not alerts:
                case_findings.append("EXPECTED_ALERT_NOT_EMITTED")
            elif not any(
                alert.level == expected_level and expected_sources <= set(alert.source_event_ids)
                for alert in alerts
            ):
                case_findings.append("ALERT_LEVEL_OR_SOURCE_MISMATCH")
        result = {
            "case_id": case_id,
            "rule_id": rule_id,
            "alert_count": len(alerts),
            "passed": not case_findings,
            "findings": case_findings,
        }
        case_results.append(result)
        if case_findings:
            findings.append(
                {
                    "code": "CASE_FAILED",
                    "message": f"{prefix} {case_id}: {', '.join(case_findings)}",
                }
            )
        else:
            passed_cases += 1
    passed = not findings and passed_cases == len(records)
    return {
        "schema_version": "hct302-rule-acceptance/v1",
        "case_count": len(records),
        "passed_case_count": passed_cases,
        "passed": passed,
        "decision": "ACCEPT_RULES" if passed else "BLOCK_RULE_ACCEPTANCE",
        "case_results": case_results,
        "findings": findings,
        "limitations": [
            "Interaction cases must cite the approved local master-data version and source record.",
            "This report proves only the supplied rule cases; it is not clinical advice.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--allow-synthetic", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        records = load_jsonl(args.cases)
        report = evaluate_cases(records, allow_synthetic=args.allow_synthetic)
        report["input_sha256"] = hashlib.sha256(args.cases.read_bytes()).hexdigest()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema_version": "hct302-rule-acceptance/v1",
            "passed": False,
            "decision": "BLOCK_RULE_ACCEPTANCE",
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
