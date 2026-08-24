"""Gate the approved fixed drug set used by the formal vision evaluation.

This is deliberately stricter than the metadata-only HCT-201 training gate.  It
requires a production fixed set with 12--20 distinct approved drug identities,
plus explicit unknown and conflict samples.  The repository contains no real
drug images; a missing or synthetic manifest must therefore remain blocked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from hct201_formal_gate import Finding, load_manifest

MIN_DRUGS = 12
MAX_DRUGS = 20
REQUIRED_CASE_TYPES = {"unknown", "conflict"}


def _nonempty(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def evaluate_fixed_set(records: list[dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    drug_ids: set[str] = set()
    case_types: Counter[str] = Counter()
    seen_ids: set[str] = set()

    for index, record in enumerate(records, start=1):
        prefix = f"record {index}"
        sample_id = str(record.get("sample_id", "")).strip()
        if not sample_id:
            findings.append(Finding("EMPTY_SAMPLE_ID", f"{prefix}: sample_id is required"))
        elif sample_id in seen_ids:
            findings.append(Finding("DUPLICATE_SAMPLE_ID", f"{prefix}: duplicate sample_id"))
        seen_ids.add(sample_id)

        if record.get("status") != "APPROVED":
            findings.append(Finding("DATA_NOT_APPROVED", f"{prefix}: status must be APPROVED"))
        if record.get("dataset_scope") != "approved_real_fixed_set":
            findings.append(
                Finding(
                    "NOT_APPROVED_REAL_SCOPE",
                    f"{prefix}: dataset_scope must be approved_real_fixed_set",
                )
            )
        for field in ("dataset_version", "dataset_approval_ref", "review_record_ref"):
            if not _nonempty(record.get(field)):
                findings.append(
                    Finding("MISSING_APPROVAL_REFERENCE", f"{prefix}: {field} is required")
                )

        case_type = str(record.get("case_type", "")).strip().lower()
        if case_type not in {"known", "unknown", "conflict"}:
            findings.append(
                Finding("INVALID_CASE_TYPE", f"{prefix}: case_type must be known/unknown/conflict")
            )
            continue
        case_types[case_type] += 1

        if case_type == "known":
            drug_id = str(record.get("drug_id", "")).strip()
            if not drug_id:
                findings.append(Finding("MISSING_DRUG_ID", f"{prefix}: known case needs drug_id"))
            else:
                drug_ids.add(drug_id)
            if record.get("fixed_eval") is not True or record.get("split") != "test":
                findings.append(
                    Finding(
                        "KNOWN_CASE_NOT_FROZEN",
                        f"{prefix}: known fixed cases must be split=test and fixed_eval=true",
                    )
                )
        elif case_type == "unknown":
            if record.get("split") != "unknown" or record.get("unknown_set") is not True:
                findings.append(
                    Finding("UNKNOWN_CASE_NOT_FROZEN", f"{prefix}: unknown case must be frozen")
                )
            if not _nonempty(record.get("unknown_reason")):
                findings.append(
                    Finding("MISSING_UNKNOWN_REASON", f"{prefix}: unknown_reason is required")
                )
        elif case_type == "conflict":
            if record.get("fixed_eval") is not True:
                findings.append(
                    Finding("CONFLICT_CASE_NOT_FROZEN", f"{prefix}: conflict must be fixed_eval")
                )
            if record.get("expected_status") != "CONFLICT":
                findings.append(
                    Finding(
                        "CONFLICT_EXPECTATION_MISSING",
                        f"{prefix}: expected_status must be CONFLICT",
                    )
                )
            if not _nonempty(record.get("conflict_reason")):
                findings.append(
                    Finding("MISSING_CONFLICT_REASON", f"{prefix}: conflict_reason is required")
                )

    if len(drug_ids) < MIN_DRUGS or len(drug_ids) > MAX_DRUGS:
        findings.append(
            Finding(
                "FIXED_DRUG_COUNT_OUT_OF_RANGE",
                f"approved known drug count={len(drug_ids)}; expected {MIN_DRUGS}..{MAX_DRUGS}",
            )
        )
    for case_type in REQUIRED_CASE_TYPES:
        if case_types[case_type] == 0:
            findings.append(Finding("REQUIRED_CASE_SET_MISSING", f"no {case_type} samples"))

    return findings


def build_report(
    path: Path, records: list[dict[str, Any]], findings: list[Finding]
) -> dict[str, Any]:
    known_drugs = sorted(
        {
            str(record.get("drug_id")).strip()
            for record in records
            if record.get("case_type") == "known" and _nonempty(record.get("drug_id"))
        }
    )
    case_counts = dict(sorted(Counter(str(item.get("case_type", "")) for item in records).items()))
    passed = not findings
    return {
        "schema_version": "hct201-approved-fixed-set-gate/v1",
        "manifest": path.name,
        "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "dataset_scope": "approved_real_fixed_set",
        "record_count": len(records),
        "approved_drug_count": len(known_drugs),
        "case_counts": case_counts,
        "passed": passed,
        "decision": "ALLOW_APPROVED_FIXED_SET" if passed else "BLOCK_APPROVED_FIXED_SET",
        "findings": [{"code": item.code, "message": item.message} for item in findings],
        "limitations": [
            "This gate checks metadata and approval evidence, not image quality or model accuracy.",
            "Unknown and conflict cases must be independently reviewed before release.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        records = load_manifest(args.manifest)
        findings = evaluate_fixed_set(records)
        report = build_report(args.manifest, records, findings)
    except (OSError, ValueError) as exc:
        report = {
            "schema_version": "hct201-approved-fixed-set-gate/v1",
            "passed": False,
            "decision": "BLOCK_APPROVED_FIXED_SET",
            "findings": [{"code": "MANIFEST_ERROR", "message": str(exc)}],
        }
        payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        print(payload, end="")
        return 2

    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
