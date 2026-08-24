"""Gate HCT-206 candidate-fusion evidence before production review.

The deterministic fusion rule and synthetic calibration fixture are useful for
technical regression, but they cannot establish production medicine accuracy.
This gate therefore requires three external, auditable reports:

* the HCT-201 approved real fixed-set gate;
* the HCT-205 approved-real OCR/barcode/master-data accuracy report; and
* an HCT-206 calibration report explicitly marked for the approved real set.

The command only produces an evidence decision.  It never changes runtime
thresholds, publishes a model, confirms a candidate, or writes a health event.
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
SCHEMA_VERSION = "hct206-release-gate/v1"
CALIBRATION_SCHEMA_VERSION = "fusion-calibration-report-v1"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: JSON root must be an object")
    return value


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _require_sha256(findings: list[dict[str, str]], report: dict[str, Any], field: str) -> None:
    if not _is_sha256(report.get(field)):
        findings.append({"code": "REPORT_HASH_MISSING", "message": f"{field} must be a SHA-256"})


def _check_hct201(findings: list[dict[str, str]], report: dict[str, Any]) -> None:
    if report.get("schema_version") != "hct201-approved-fixed-set-gate/v1":
        findings.append(
            {
                "code": "HCT201_REPORT_INVALID",
                "message": "HCT-201 fixed-set report schema is invalid",
            }
        )
    if report.get("passed") is not True or report.get("decision") != "ALLOW_APPROVED_FIXED_SET":
        findings.append(
            {
                "code": "HCT201_GATE_BLOCKED",
                "message": "HCT-201 approved fixed-set gate did not pass",
            }
        )
    if report.get("dataset_scope") != "approved_real_fixed_set":
        findings.append(
            {
                "code": "HCT201_REAL_SCOPE_REQUIRED",
                "message": "HCT-201 report must use approved_real_fixed_set",
            }
        )
    drug_count = report.get("approved_drug_count")
    if (
        not isinstance(drug_count, int)
        or isinstance(drug_count, bool)
        or not 12 <= drug_count <= 20
    ):
        findings.append(
            {
                "code": "HCT201_DRUG_RANGE_INVALID",
                "message": "HCT-201 report must contain 12..20 approved drugs",
            }
        )
    case_counts = report.get("case_counts")
    if not isinstance(case_counts, dict) or not all(
        isinstance(case_counts.get(case_type), int) and case_counts[case_type] > 0
        for case_type in ("unknown", "conflict")
    ):
        findings.append(
            {
                "code": "HCT201_CASE_SETS_REQUIRED",
                "message": "HCT-201 report must contain unknown and conflict cases",
            }
        )
    _require_sha256(findings, report, "manifest_sha256")


def _check_hct205(findings: list[dict[str, str]], report: dict[str, Any]) -> None:
    if report.get("schema_version") != "hct205-accuracy-report/v1":
        findings.append(
            {
                "code": "HCT205_REPORT_INVALID",
                "message": "HCT-205 accuracy report schema is invalid",
            }
        )
    if (
        report.get("passed") is not True
        or report.get("decision") != "ACCEPT_OCR_BARCODE_MASTER_DATA"
    ):
        findings.append(
            {"code": "HCT205_GATE_BLOCKED", "message": "HCT-205 accuracy gate did not pass"}
        )
    if report.get("evaluation_scope") != "approved_real_fixed_set":
        findings.append(
            {
                "code": "HCT205_REAL_SCOPE_REQUIRED",
                "message": "HCT-205 report must use approved_real_fixed_set",
            }
        )
    metrics = report.get("metrics")
    thresholds = report.get("thresholds")
    if not isinstance(metrics, dict) or not isinstance(thresholds, dict):
        findings.append(
            {
                "code": "HCT205_METRICS_MISSING",
                "message": "HCT-205 metrics and thresholds are required",
            }
        )
    else:
        for metric, threshold in (
            ("overall_field_accuracy", "min_field_accuracy"),
            ("status_accuracy", "min_status_accuracy"),
        ):
            actual = metrics.get(metric)
            minimum = thresholds.get(threshold)
            if not isinstance(actual, (int, float)) or isinstance(actual, bool):
                findings.append(
                    {"code": "HCT205_METRIC_INVALID", "message": f"{metric} must be numeric"}
                )
            elif (
                not isinstance(minimum, (int, float))
                or isinstance(minimum, bool)
                or actual < minimum
            ):
                findings.append(
                    {
                        "code": "HCT205_METRIC_BELOW_THRESHOLD",
                        "message": f"{metric} is below its configured threshold",
                    }
                )
        field_accuracy = metrics.get("field_accuracy")
        barcode_accuracy = (
            field_accuracy.get("barcode") if isinstance(field_accuracy, dict) else None
        )
        barcode_minimum = thresholds.get("min_barcode_accuracy")
        if barcode_accuracy is None:
            findings.append(
                {
                    "code": "HCT205_BARCODE_METRIC_REQUIRED",
                    "message": "HCT-205 report must include barcode accuracy for HCT-206",
                }
            )
        elif (
            not isinstance(barcode_accuracy, (int, float))
            or isinstance(barcode_accuracy, bool)
            or not isinstance(barcode_minimum, (int, float))
            or isinstance(barcode_minimum, bool)
            or barcode_accuracy < barcode_minimum
        ):
            findings.append(
                {
                    "code": "HCT205_BARCODE_BELOW_THRESHOLD",
                    "message": "barcode accuracy is below its configured threshold",
                }
            )
    _require_sha256(findings, report, "input_sha256")


def _calibration_payload(report: dict[str, Any]) -> dict[str, Any]:
    """Return the nested or direct calibration report for compatibility."""

    nested = report.get("report")
    if isinstance(nested, dict):
        return nested
    return report


def _check_hct206(
    findings: list[dict[str, str]],
    envelope: dict[str, Any],
    *,
    max_false_match_rate: float,
    hct201_manifest_sha256: Any,
    hct205_input_sha256: Any,
) -> None:
    if envelope.get("schema_version") not in {
        SCHEMA_VERSION,
        "hct206-production-calibration-evidence/v1",
    }:
        findings.append(
            {
                "code": "HCT206_REPORT_INVALID",
                "message": "HCT-206 production calibration envelope schema is invalid",
            }
        )
    if envelope.get("dataset_scope") != "approved_real_fixed_set":
        findings.append(
            {
                "code": "HCT206_REAL_SCOPE_REQUIRED",
                "message": "HCT-206 calibration must use approved_real_fixed_set",
            }
        )
    if envelope.get("production_eligible") is not True:
        findings.append(
            {
                "code": "HCT206_PRODUCTION_MARKER_REQUIRED",
                "message": "HCT-206 calibration must be explicitly production_eligible",
            }
        )
    if envelope.get("approval_status") != "APPROVED_FOR_PRODUCTION_CALIBRATION":
        findings.append(
            {
                "code": "HCT206_APPROVAL_REQUIRED",
                "message": "HCT-206 production calibration approval is required",
            }
        )
    source = envelope.get("source")
    if not isinstance(source, dict) or source.get("type") != "approved_real_fixed_set":
        findings.append(
            {
                "code": "HCT206_SOURCE_INVALID",
                "message": "HCT-206 source must be an approved real fixed set",
            }
        )
    for field in ("dataset_gate_ref", "accuracy_report_ref", "review_record_ref"):
        if not str(envelope.get(field, "")).strip():
            findings.append(
                {"code": "HCT206_PROVENANCE_MISSING", "message": f"{field} is required"}
            )
    human_review = envelope.get("human_review")
    if (
        not isinstance(human_review, dict)
        or human_review.get("review_status") != "PRODUCTION_CALIBRATION_REVIEWED"
        or not str(human_review.get("reviewer", "")).strip()
        or not str(human_review.get("review_date", "")).strip()
    ):
        findings.append(
            {
                "code": "HCT206_HUMAN_REVIEW_REQUIRED",
                "message": "production calibration reviewer and review date are required",
            }
        )
    bindings = envelope.get("evidence_bindings")
    if not isinstance(bindings, dict):
        findings.append(
            {
                "code": "HCT206_EVIDENCE_BINDING_MISSING",
                "message": "HCT-201 and HCT-205 evidence hashes must be bound",
            }
        )
    else:
        if bindings.get("hct201_manifest_sha256") != hct201_manifest_sha256:
            findings.append(
                {
                    "code": "HCT206_HCT201_BINDING_MISMATCH",
                    "message": "HCT-206 is not bound to the supplied HCT-201 manifest",
                }
            )
        if bindings.get("hct205_input_sha256") != hct205_input_sha256:
            findings.append(
                {
                    "code": "HCT206_HCT205_BINDING_MISMATCH",
                    "message": "HCT-206 is not bound to the supplied HCT-205 result input",
                }
            )

    report = _calibration_payload(envelope)
    if report.get("schema_version") != CALIBRATION_SCHEMA_VERSION:
        findings.append(
            {
                "code": "HCT206_CALIBRATION_SCHEMA_INVALID",
                "message": "fusion-calibration-report-v1 is required",
            }
        )
    _require_sha256(findings, report, "sample_sha256")
    thresholds = report.get("thresholds")
    if not isinstance(thresholds, dict) or not str(thresholds.get("config_version", "")).strip():
        findings.append(
            {
                "code": "HCT206_THRESHOLD_VERSION_REQUIRED",
                "message": "versioned calibrated thresholds are required",
            }
        )
    for split_name in ("validation", "independent_test"):
        split = report.get(split_name)
        if (
            not isinstance(split, dict)
            or not isinstance(split.get("sample_count"), int)
            or split.get("sample_count", 0) <= 0
        ):
            findings.append(
                {
                    "code": "HCT206_SPLIT_REQUIRED",
                    "message": f"non-empty {split_name} split is required",
                }
            )
            continue
        false_match_rate = split.get("false_match_rate")
        if (
            not isinstance(false_match_rate, (int, float))
            or isinstance(false_match_rate, bool)
            or false_match_rate > max_false_match_rate
        ):
            findings.append(
                {
                    "code": "HCT206_FALSE_MATCH_RATE_TOO_HIGH",
                    "message": f"{split_name} false_match_rate exceeds the configured maximum",
                }
            )


def evaluate_release_readiness(
    *,
    dataset_gate: dict[str, Any],
    accuracy_report: dict[str, Any],
    calibration_report: dict[str, Any],
    max_false_match_rate: float = 0.0,
) -> dict[str, Any]:
    """Evaluate external HCT-201/HCT-205/HCT-206 evidence fail-closed."""

    findings: list[dict[str, str]] = []
    if not 0 <= max_false_match_rate <= 1:
        findings.append(
            {
                "code": "INVALID_FALSE_MATCH_THRESHOLD",
                "message": "max_false_match_rate must be between 0 and 1",
            }
        )
    _check_hct201(findings, dataset_gate)
    _check_hct205(findings, accuracy_report)
    _check_hct206(
        findings,
        calibration_report,
        max_false_match_rate=max_false_match_rate,
        hct201_manifest_sha256=dataset_gate.get("manifest_sha256"),
        hct205_input_sha256=accuracy_report.get("input_sha256"),
    )
    passed = not findings
    return {
        "schema_version": SCHEMA_VERSION,
        "passed": passed,
        "decision": "READY_FOR_R3_REVIEW" if passed else "BLOCK_CANDIDATE_FUSION",
        "inputs": {
            "hct201_decision": dataset_gate.get("decision"),
            "hct205_decision": accuracy_report.get("decision"),
            "hct206_dataset_scope": calibration_report.get("dataset_scope"),
        },
        "thresholds": {"max_false_match_rate": max_false_match_rate},
        "findings": findings,
        "limitations": [
            "This gate is evidence-only and never changes runtime fusion thresholds "
            "or publishes a model.",
            "Every MATCHED result still requires human confirmation and "
            "health_event_allowed remains false.",
            "R3 review and maintainer sign-off remain required after this machine gate passes.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-gate", required=True, type=Path)
    parser.add_argument("--accuracy-report", required=True, type=Path)
    parser.add_argument("--calibration-report", required=True, type=Path)
    parser.add_argument("--max-false-match-rate", type=float, default=0.0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = evaluate_release_readiness(
            dataset_gate=_load(args.dataset_gate),
            accuracy_report=_load(args.accuracy_report),
            calibration_report=_load(args.calibration_report),
            max_false_match_rate=args.max_false_match_rate,
        )
        report["input_sha256"] = {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in (
                ("hct201_dataset_gate", args.dataset_gate),
                ("hct205_accuracy_report", args.accuracy_report),
                ("hct206_calibration_report", args.calibration_report),
            )
        }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schema_version": SCHEMA_VERSION,
            "passed": False,
            "decision": "BLOCK_CANDIDATE_FUSION",
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
