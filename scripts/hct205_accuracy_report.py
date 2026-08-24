"""Compute a reproducible OCR/barcode/master-data accuracy report.

Input is JSONL so the image files and raw OCR payloads can stay outside Git.
Every row must point to an approved fixed-set sample.  ``--allow-synthetic`` is
only for unit/contract fixtures and can never produce an acceptance decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

CHANNELS = {"ocr", "barcode", "master_data", "fusion"}
STATUSES = {"MATCHED", "CONFLICT", "UNKNOWN", "REVIEW"}
DEFAULT_FIELDS = (
    "drug_name",
    "specification",
    "manufacturer",
    "usage",
    "contraindications",
    "barcode",
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_number}: invalid JSON: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"line {line_number}: record must be an object")
        records.append(value)
    if not records:
        raise ValueError("result JSONL is empty")
    return records


def _normalise(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    return " ".join(text.split())


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def evaluate_records(
    records: list[dict[str, Any]],
    *,
    threshold_version: str,
    min_field_accuracy: float = 0.95,
    min_barcode_accuracy: float = 0.98,
    min_status_accuracy: float = 0.95,
    allow_synthetic: bool = False,
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    field_totals: defaultdict[str, int] = defaultdict(int)
    field_passes: defaultdict[str, int] = defaultdict(int)
    channel_totals: defaultdict[str, int] = defaultdict(int)
    channel_passes: defaultdict[str, int] = defaultdict(int)
    failure_reasons: defaultdict[str, int] = defaultdict(int)
    status_total = status_pass = exact_pass = 0
    scopes: set[str] = set()
    dataset_statuses: set[str] = set()

    for index, row in enumerate(records, start=1):
        prefix = f"record {index}"
        sample_id = str(row.get("sample_id", "")).strip()
        if not sample_id:
            findings.append(
                {"code": "MISSING_SAMPLE_ID", "message": f"{prefix}: sample_id is required"}
            )
        elif sample_id in seen_ids:
            findings.append(
                {"code": "DUPLICATE_SAMPLE_ID", "message": f"{prefix}: duplicate sample_id"}
            )
        seen_ids.add(sample_id)

        channel = str(row.get("channel", "")).strip().lower()
        if channel not in CHANNELS:
            findings.append(
                {"code": "INVALID_CHANNEL", "message": f"{prefix}: unsupported channel"}
            )
        else:
            channel_totals[channel] += 1

        expected = row.get("expected")
        predicted = row.get("predicted")
        if not isinstance(expected, dict) or not isinstance(predicted, dict):
            findings.append(
                {
                    "code": "INVALID_FIELDS",
                    "message": f"{prefix}: expected/predicted must be objects",
                }
            )
            continue

        dataset_status = str(row.get("dataset_status", "")).strip().upper()
        dataset_scope = str(row.get("dataset_scope", "")).strip()
        dataset_statuses.add(dataset_status)
        scopes.add(dataset_scope)
        if dataset_status != "APPROVED":
            findings.append(
                {
                    "code": "DATASET_NOT_APPROVED",
                    "message": f"{prefix}: dataset_status must be APPROVED",
                }
            )
        if dataset_scope not in {"approved_real_fixed_set", "synthetic_fixture_only"}:
            findings.append(
                {"code": "INVALID_DATASET_SCOPE", "message": f"{prefix}: invalid dataset_scope"}
            )
        if dataset_scope == "synthetic_fixture_only" and not allow_synthetic:
            findings.append(
                {
                    "code": "SYNTHETIC_NOT_ALLOWED",
                    "message": f"{prefix}: synthetic fixture requires --allow-synthetic",
                }
            )

        expected_status = str(row.get("expected_status", "")).strip().upper()
        predicted_status = str(row.get("predicted_status", "")).strip().upper()
        if expected_status not in STATUSES or predicted_status not in STATUSES:
            findings.append(
                {
                    "code": "INVALID_STATUS",
                    "message": f"{prefix}: expected_status/predicted_status invalid",
                }
            )
        else:
            status_total += 1
            if expected_status == predicted_status:
                status_pass += 1

        confidence = _number(row.get("confidence"))
        if confidence is None or not 0 <= confidence <= 1:
            findings.append(
                {"code": "INVALID_CONFIDENCE", "message": f"{prefix}: confidence must be 0..1"}
            )
        if str(row.get("threshold_version", "")).strip() != threshold_version:
            findings.append(
                {
                    "code": "THRESHOLD_VERSION_MISMATCH",
                    "message": f"{prefix}: threshold_version mismatch",
                }
            )
        if not str(row.get("source_ref", "")).strip():
            findings.append(
                {"code": "MISSING_SOURCE_REF", "message": f"{prefix}: source_ref is required"}
            )

        compared = 0
        row_exact = True
        for field in DEFAULT_FIELDS:
            expected_value = _normalise(expected.get(field))
            if not expected_value:
                continue
            compared += 1
            field_totals[field] += 1
            passed = expected_value == _normalise(predicted.get(field))
            if passed:
                field_passes[field] += 1
            else:
                row_exact = False
                failure_reasons[f"field_mismatch:{field}"] += 1
        if compared and row_exact:
            exact_pass += 1
        if compared == 0:
            failure_reasons["no_comparable_fields"] += 1
            row_exact = False
        if channel in CHANNELS and channel_totals[channel] > 0 and row_exact:
            channel_passes[channel] += 1

    field_accuracy = {
        field: round(field_passes[field] / field_totals[field], 4) if field_totals[field] else None
        for field in sorted(field_totals)
    }
    channel_accuracy = {
        channel: round(channel_passes[channel] / channel_totals[channel], 4)
        if channel_totals[channel]
        else None
        for channel in sorted(channel_totals)
    }
    all_fields_total = sum(field_totals.values())
    overall_field_accuracy = (
        round(sum(field_passes.values()) / all_fields_total, 4) if all_fields_total else 0.0
    )
    barcode_accuracy = field_accuracy.get("barcode")
    status_accuracy = round(status_pass / status_total, 4) if status_total else 0.0
    real_scope = scopes == {"approved_real_fixed_set"} and dataset_statuses == {"APPROVED"}
    metric_pass = (
        overall_field_accuracy >= min_field_accuracy
        and (barcode_accuracy is None or barcode_accuracy >= min_barcode_accuracy)
        and status_accuracy >= min_status_accuracy
    )
    passed = not findings and metric_pass and real_scope
    if not metric_pass:
        findings.append(
            {
                "code": "THRESHOLD_NOT_MET",
                "message": "one or more configured accuracy thresholds failed",
            }
        )
    if not real_scope:
        findings.append(
            {
                "code": "REAL_SCOPE_REQUIRED",
                "message": "formal acceptance requires approved_real_fixed_set only",
            }
        )

    return {
        "schema_version": "hct205-accuracy-report/v1",
        "evaluation_scope": "approved_real_fixed_set" if real_scope else "synthetic_or_mixed",
        "input_record_count": len(records),
        "input_sha256": None,
        "thresholds": {
            "version": threshold_version,
            "min_field_accuracy": min_field_accuracy,
            "min_barcode_accuracy": min_barcode_accuracy,
            "min_status_accuracy": min_status_accuracy,
        },
        "metrics": {
            "overall_field_accuracy": overall_field_accuracy,
            "field_accuracy": field_accuracy,
            "status_accuracy": status_accuracy,
            "exact_sample_accuracy": round(exact_pass / len(records), 4) if records else 0.0,
            "channel_accuracy": channel_accuracy,
            "failure_reasons": dict(sorted(failure_reasons.items())),
        },
        "passed": passed,
        "decision": "ACCEPT_OCR_BARCODE_MASTER_DATA" if passed else "BLOCK_OCR_BARCODE_MASTER_DATA",
        "findings": findings,
        "limitations": [
            "Accuracy is only valid for the supplied frozen sample result file.",
            "A real report must retain engine, master-data and threshold versions "
            "plus reviewer sign-off.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--threshold-version", required=True)
    parser.add_argument("--min-field-accuracy", type=float, default=0.95)
    parser.add_argument("--min-barcode-accuracy", type=float, default=0.98)
    parser.add_argument("--min-status-accuracy", type=float, default=0.95)
    parser.add_argument("--allow-synthetic", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        records = load_jsonl(args.results)
        report = evaluate_records(
            records,
            threshold_version=args.threshold_version,
            min_field_accuracy=args.min_field_accuracy,
            min_barcode_accuracy=args.min_barcode_accuracy,
            min_status_accuracy=args.min_status_accuracy,
            allow_synthetic=args.allow_synthetic,
        )
        report["input_sha256"] = hashlib.sha256(args.results.read_bytes()).hexdigest()
    except (OSError, ValueError) as exc:
        report = {
            "schema_version": "hct205-accuracy-report/v1",
            "passed": False,
            "decision": "BLOCK_OCR_BARCODE_MASTER_DATA",
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
