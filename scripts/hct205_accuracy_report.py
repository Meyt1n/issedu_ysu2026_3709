"""Compute a reproducible HCT-205 OCR/barcode/master-data report.

The input result JSONL and the approved fixed-set/master-data evidence stay
outside Git. A formal report is fail-closed: it cannot accept synthetic data,
an unapproved fixed set, or an unapproved master-data snapshot. Failure
samples contain only review-safe references and mismatch field names; raw OCR,
barcodes and clinical values are never copied into the report.
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

from hct201_fixed_set_gate import evaluate_fixed_set

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
FORMAL_SCOPE = "approved_real_fixed_set"


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


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: JSON object is required")
    return value


def _normalise(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    return " ".join(text.split())


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _finding(findings: list[dict[str, str]], code: str, message: str) -> None:
    findings.append({"code": code, "message": message})


def _manifest_context(
    records: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], set[str], set[str]]:
    by_sample: dict[str, dict[str, Any]] = {}
    versions: set[str] = set()
    drug_ids: set[str] = set()
    for row in records:
        sample_id = str(row.get("sample_id", "")).strip()
        if sample_id:
            by_sample[sample_id] = row
        dataset_version = str(row.get("dataset_version", "")).strip()
        if dataset_version:
            versions.add(dataset_version)
        drug_id = str(row.get("drug_id", "")).strip()
        if row.get("case_type") == "known" and drug_id:
            drug_ids.add(drug_id)
    return by_sample, versions, drug_ids


def _manifest_expected_status(row: dict[str, Any]) -> str:
    case_type = str(row.get("case_type", "")).strip().lower()
    return {"known": "MATCHED", "unknown": "UNKNOWN", "conflict": "CONFLICT"}.get(case_type, "")


def _safe_failure_sample(
    row: dict[str, Any],
    *,
    failure_codes: list[str],
    field_mismatches: list[str],
    expected_status: str,
    predicted_status: str,
    confidence: float | None,
) -> dict[str, Any]:
    """Return metadata only; never include expected/predicted payload values."""

    result: dict[str, Any] = {
        "sample_id": str(row.get("sample_id", "")).strip() or None,
        "channel": str(row.get("channel", "")).strip().lower() or None,
        "failure_codes": sorted(set(failure_codes)),
        "field_mismatches": sorted(set(field_mismatches)),
        "expected_status": expected_status or None,
        "predicted_status": predicted_status or None,
        "confidence": confidence,
        "threshold_version": str(row.get("threshold_version", "")).strip() or None,
        "source_ref": str(row.get("source_ref", "")).strip() or None,
        "master_data_version": str(row.get("master_data_version", "")).strip() or None,
        "master_data_record_id": str(row.get("master_data_record_id", "")).strip() or None,
    }
    for field in ("hard_sample_ref", "hard_sample_category"):
        if str(row.get(field, "")).strip():
            result[field] = str(row[field]).strip()
    return result


def evaluate_records(
    records: list[dict[str, Any]],
    *,
    threshold_version: str,
    min_field_accuracy: float = 0.95,
    min_barcode_accuracy: float = 0.98,
    min_status_accuracy: float = 0.95,
    allow_synthetic: bool = False,
    fixed_set_records: list[dict[str, Any]] | None = None,
    fixed_set_manifest_sha256: str | None = None,
    master_data_gate: dict[str, Any] | None = None,
    require_formal_evidence: bool = True,
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str]] = set()
    field_totals: defaultdict[str, int] = defaultdict(int)
    field_passes: defaultdict[str, int] = defaultdict(int)
    channel_totals: defaultdict[str, int] = defaultdict(int)
    channel_passes: defaultdict[str, int] = defaultdict(int)
    failure_reasons: defaultdict[str, int] = defaultdict(int)
    failure_samples: list[dict[str, Any]] = []
    status_total = status_pass = exact_pass = 0
    scopes: set[str] = set()
    dataset_statuses: set[str] = set()

    manifest_by_sample: dict[str, dict[str, Any]] = {}
    manifest_versions: set[str] = set()
    manifest_drug_ids: set[str] = set()
    fixed_gate_findings: list[Any] = []
    if fixed_set_records is not None:
        manifest_by_sample, manifest_versions, manifest_drug_ids = _manifest_context(
            fixed_set_records
        )
        fixed_gate_findings = evaluate_fixed_set(fixed_set_records)
        if fixed_gate_findings:
            _finding(
                findings,
                "FIXED_SET_GATE_BLOCKED",
                "linked fixed-set manifest did not pass HCT-201 approved fixed-set gate",
            )
        if not fixed_set_manifest_sha256:
            _finding(
                findings,
                "FIXED_SET_HASH_REQUIRED",
                "formal report requires the frozen manifest SHA-256",
            )
        if require_formal_evidence and len(manifest_versions) != 1:
            _finding(
                findings,
                "FIXED_SET_VERSION_INVALID",
                "approved fixed-set manifest must contain exactly one dataset_version",
            )
    elif require_formal_evidence:
        _finding(
            findings,
            "FIXED_SET_MANIFEST_REQUIRED",
            "formal report requires an approved fixed-set manifest",
        )

    master_gate_passed = False
    master_version = ""
    master_hash = ""
    master_snapshot_hash = ""
    master_record_ids: set[str] = set()
    if master_data_gate is None:
        if require_formal_evidence:
            _finding(
                findings,
                "MASTER_DATA_GATE_REQUIRED",
                "formal report requires an approved master-data gate report",
            )
    else:
        if master_data_gate.get("schema_version") != "hct205-approved-master-data-gate/v1":
            _finding(
                findings,
                "MASTER_DATA_GATE_SCHEMA_MISMATCH",
                "master-data gate schema_version is not supported",
            )
        master_gate_passed = (
            bool(master_data_gate.get("passed"))
            and master_data_gate.get("decision") == "ALLOW_APPROVED_MASTER_DATA"
        )
        master_version = str(master_data_gate.get("version", "")).strip()
        master_hash = str(master_data_gate.get("master_data_sha256", "")).strip().lower()
        master_snapshot_hash = str(master_data_gate.get("snapshot_file_sha256", "")).strip().lower()
        master_record_ids = {
            str(item).strip()
            for item in master_data_gate.get("record_ids", [])
            if str(item).strip()
        }
        if not master_gate_passed:
            _finding(
                findings,
                "MASTER_DATA_GATE_BLOCKED",
                "linked master-data snapshot did not pass the approved-data gate",
            )
        if not master_version or not master_hash or not master_snapshot_hash:
            _finding(
                findings,
                "MASTER_DATA_METADATA_MISSING",
                "master-data gate must expose version and canonical SHA-256",
            )
        if require_formal_evidence:
            gate_fixed_hash = (
                str(master_data_gate.get("fixed_set_manifest_sha256", "")).strip().lower()
            )
            if not gate_fixed_hash:
                _finding(
                    findings,
                    "MASTER_DATA_FIXED_SET_LINK_REQUIRED",
                    "master-data gate must be linked to the same fixed-set manifest",
                )
            elif fixed_set_manifest_sha256 and gate_fixed_hash != fixed_set_manifest_sha256.lower():
                _finding(
                    findings,
                    "MASTER_DATA_FIXED_SET_LINK_MISMATCH",
                    "master-data gate fixed-set hash does not match the report manifest",
                )

    result_sample_ids: set[str] = set()
    for index, row in enumerate(records, start=1):
        prefix = f"record {index}"
        row_failures: list[str] = []
        field_mismatches: list[str] = []
        sample_id = str(row.get("sample_id", "")).strip()
        channel = str(row.get("channel", "")).strip().lower()
        if sample_id:
            result_sample_ids.add(sample_id)
        if not sample_id:
            row_failures.append("MISSING_SAMPLE_ID")
            _finding(findings, "MISSING_SAMPLE_ID", f"{prefix}: sample_id is required")
        else:
            key = (sample_id, channel)
            if key in seen_keys:
                row_failures.append("DUPLICATE_SAMPLE_CHANNEL")
                _finding(
                    findings,
                    "DUPLICATE_SAMPLE_CHANNEL",
                    f"{prefix}: duplicate sample_id/channel",
                )
            seen_keys.add(key)

        if channel not in CHANNELS:
            row_failures.append("INVALID_CHANNEL")
            _finding(findings, "INVALID_CHANNEL", f"{prefix}: unsupported channel")
        else:
            channel_totals[channel] += 1

        expected = row.get("expected")
        predicted = row.get("predicted")
        expected_status = str(row.get("expected_status", "")).strip().upper()
        predicted_status = str(row.get("predicted_status", "")).strip().upper()
        confidence = _number(row.get("confidence"))
        if not isinstance(expected, dict) or not isinstance(predicted, dict):
            row_failures.append("INVALID_FIELDS")
            _finding(findings, "INVALID_FIELDS", f"{prefix}: expected/predicted must be objects")
            failure_samples.append(
                _safe_failure_sample(
                    row,
                    failure_codes=row_failures,
                    field_mismatches=field_mismatches,
                    expected_status=expected_status,
                    predicted_status=predicted_status,
                    confidence=confidence,
                )
            )
            continue

        dataset_status = str(row.get("dataset_status", "")).strip().upper()
        dataset_scope = str(row.get("dataset_scope", "")).strip()
        dataset_statuses.add(dataset_status)
        scopes.add(dataset_scope)
        if dataset_status != "APPROVED":
            row_failures.append("DATASET_NOT_APPROVED")
            _finding(findings, "DATASET_NOT_APPROVED", f"{prefix}: dataset_status must be APPROVED")
        if dataset_scope not in {FORMAL_SCOPE, "synthetic_fixture_only"}:
            row_failures.append("INVALID_DATASET_SCOPE")
            _finding(findings, "INVALID_DATASET_SCOPE", f"{prefix}: invalid dataset_scope")
        if dataset_scope == "synthetic_fixture_only" and not allow_synthetic:
            row_failures.append("SYNTHETIC_NOT_ALLOWED")
            _finding(
                findings,
                "SYNTHETIC_NOT_ALLOWED",
                f"{prefix}: synthetic fixture requires --allow-synthetic",
            )

        if expected_status not in STATUSES or predicted_status not in STATUSES:
            row_failures.append("INVALID_STATUS")
            _finding(
                findings, "INVALID_STATUS", f"{prefix}: expected_status/predicted_status invalid"
            )
        else:
            status_total += 1
            if expected_status == predicted_status:
                status_pass += 1
            else:
                row_failures.append("STATUS_MISMATCH")
                failure_reasons["status_mismatch"] += 1

        if confidence is None or not 0 <= confidence <= 1:
            row_failures.append("INVALID_CONFIDENCE")
            _finding(findings, "INVALID_CONFIDENCE", f"{prefix}: confidence must be 0..1")
        if str(row.get("threshold_version", "")).strip() != threshold_version:
            row_failures.append("THRESHOLD_VERSION_MISMATCH")
            _finding(
                findings, "THRESHOLD_VERSION_MISMATCH", f"{prefix}: threshold_version mismatch"
            )
        if not str(row.get("source_ref", "")).strip():
            row_failures.append("MISSING_SOURCE_REF")
            _finding(findings, "MISSING_SOURCE_REF", f"{prefix}: source_ref is required")

        if require_formal_evidence:
            manifest_row = manifest_by_sample.get(sample_id)
            if manifest_row is None:
                row_failures.append("FIXED_SAMPLE_NOT_IN_MANIFEST")
                _finding(
                    findings,
                    "FIXED_SAMPLE_NOT_IN_MANIFEST",
                    f"{prefix}: sample_id is not in the approved fixed set",
                )
            else:
                manifest_status = _manifest_expected_status(manifest_row)
                if manifest_status and expected_status != manifest_status:
                    row_failures.append("EXPECTED_STATUS_MISMATCH")
                    _finding(
                        findings,
                        "EXPECTED_STATUS_MISMATCH",
                        f"{prefix}: expected_status differs from fixed-set case type",
                    )
                dataset_version = str(row.get("dataset_version", "")).strip()
                if not dataset_version or dataset_version not in manifest_versions:
                    row_failures.append("DATASET_VERSION_MISMATCH")
                    _finding(
                        findings,
                        "DATASET_VERSION_MISMATCH",
                        f"{prefix}: dataset_version must match the frozen manifest",
                    )
                if expected_status == "MATCHED":
                    record_id = str(row.get("master_data_record_id", "")).strip()
                    expected_drug_id = str(
                        manifest_row.get("master_data_record_id") or manifest_row.get("drug_id", "")
                    ).strip()
                    if not record_id:
                        row_failures.append("MASTER_DATA_RECORD_REQUIRED")
                        _finding(
                            findings,
                            "MASTER_DATA_RECORD_REQUIRED",
                            f"{prefix}: known case requires master_data_record_id",
                        )
                    elif record_id != expected_drug_id or record_id not in master_record_ids:
                        row_failures.append("MASTER_DATA_RECORD_NOT_APPROVED")
                        _finding(
                            findings,
                            "MASTER_DATA_RECORD_NOT_APPROVED",
                            f"{prefix}: master_data_record_id is not the approved fixed-set record",
                        )

            row_master_version = str(row.get("master_data_version", "")).strip()
            row_master_hash = str(row.get("master_data_sha256", "")).strip().lower()
            if not row_master_version or row_master_version != master_version:
                row_failures.append("MASTER_DATA_VERSION_MISMATCH")
                _finding(
                    findings,
                    "MASTER_DATA_VERSION_MISMATCH",
                    f"{prefix}: master_data_version mismatch",
                )
            if not row_master_hash or row_master_hash != master_hash:
                row_failures.append("MASTER_DATA_HASH_MISMATCH")
                _finding(
                    findings, "MASTER_DATA_HASH_MISMATCH", f"{prefix}: master_data_sha256 mismatch"
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
                field_mismatches.append(field)
                row_failures.append(f"FIELD_MISMATCH:{field}")
                failure_reasons[f"field_mismatch:{field}"] += 1
        if compared and row_exact:
            exact_pass += 1
        if compared == 0:
            failure_reasons["no_comparable_fields"] += 1
            row_exact = False
            row_failures.append("NO_COMPARABLE_FIELDS")
        if channel in CHANNELS and channel_totals[channel] > 0 and row_exact:
            channel_passes[channel] += 1
        if row_failures:
            failure_samples.append(
                _safe_failure_sample(
                    row,
                    failure_codes=row_failures,
                    field_mismatches=field_mismatches,
                    expected_status=expected_status,
                    predicted_status=predicted_status,
                    confidence=confidence,
                )
            )

    if require_formal_evidence and fixed_set_records is not None:
        missing_samples = sorted(set(manifest_by_sample) - result_sample_ids)
        extra_samples = sorted(result_sample_ids - set(manifest_by_sample))
        if missing_samples:
            _finding(
                findings,
                "FIXED_SAMPLE_MISSING",
                f"{len(missing_samples)} approved fixed-set samples have no result",
            )
            for sample_id in missing_samples:
                manifest_row = manifest_by_sample[sample_id]
                failure_samples.append(
                    _safe_failure_sample(
                        {
                            "sample_id": sample_id,
                            "channel": "unreported",
                            "source_ref": manifest_row.get("review_record_ref"),
                        },
                        failure_codes=["FIXED_SAMPLE_MISSING"],
                        field_mismatches=[],
                        expected_status=_manifest_expected_status(manifest_row),
                        predicted_status="",
                        confidence=None,
                    )
                )
        if extra_samples:
            _finding(
                findings,
                "FIXED_SAMPLE_EXTRA",
                f"{len(extra_samples)} result samples are not in the approved fixed set",
            )

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
    real_scope = scopes == {FORMAL_SCOPE} and dataset_statuses == {"APPROVED"}
    metric_pass = (
        overall_field_accuracy >= min_field_accuracy
        and (barcode_accuracy is None or barcode_accuracy >= min_barcode_accuracy)
        and status_accuracy >= min_status_accuracy
    )
    if not metric_pass:
        _finding(findings, "THRESHOLD_NOT_MET", "one or more configured accuracy thresholds failed")
    if not real_scope:
        _finding(
            findings,
            "REAL_SCOPE_REQUIRED",
            "formal acceptance requires approved_real_fixed_set only",
        )
    formal_gate_ok = (
        (not fixed_gate_findings and master_gate_passed) if require_formal_evidence else True
    )
    passed = not findings and metric_pass and real_scope and formal_gate_ok

    return {
        "schema_version": "hct205-accuracy-report/v1",
        "evaluation_scope": FORMAL_SCOPE if real_scope else "synthetic_or_mixed",
        "input_record_count": len(records),
        "input_sha256": None,
        "fixed_set": {
            "manifest_sha256": fixed_set_manifest_sha256,
            "manifest_record_count": len(fixed_set_records)
            if fixed_set_records is not None
            else None,
            "approved_drug_count": len(manifest_drug_ids)
            if fixed_set_records is not None
            else None,
            "gate_passed": not fixed_gate_findings if fixed_set_records is not None else False,
        },
        "master_data": {
            "version": master_version or None,
            "master_data_sha256": master_hash or None,
            "snapshot_file_sha256": master_snapshot_hash or None,
            "record_count": len(master_record_ids) if master_data_gate is not None else None,
            "gate_passed": master_gate_passed,
        },
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
            "failure_count": len(failure_samples),
        },
        "failure_samples": failure_samples,
        "passed": passed,
        "decision": "ACCEPT_OCR_BARCODE_MASTER_DATA" if passed else "BLOCK_OCR_BARCODE_MASTER_DATA",
        "findings": findings,
        "limitations": [
            "Accuracy is only valid for the supplied frozen sample result file.",
            "Formal acceptance requires external approval evidence for both the fixed set and "
            "master-data snapshot.",
            "Failure samples intentionally omit raw OCR, barcode and clinical values.",
        ],
    }


def _write_failure_samples(path: Path, samples: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in samples
    )
    path.write_text(payload, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--threshold-version", required=True)
    parser.add_argument("--fixed-set-manifest", type=Path)
    parser.add_argument("--master-data-gate", type=Path)
    parser.add_argument("--failure-samples", type=Path)
    parser.add_argument("--min-field-accuracy", type=float, default=0.95)
    parser.add_argument("--min-barcode-accuracy", type=float, default=0.98)
    parser.add_argument("--min-status-accuracy", type=float, default=0.95)
    parser.add_argument("--allow-synthetic", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        records = load_jsonl(args.results)
        fixed_records = load_jsonl(args.fixed_set_manifest) if args.fixed_set_manifest else None
        master_gate = load_json_object(args.master_data_gate) if args.master_data_gate else None
        fixed_hash = (
            hashlib.sha256(args.fixed_set_manifest.read_bytes()).hexdigest()
            if args.fixed_set_manifest
            else None
        )
        report = evaluate_records(
            records,
            threshold_version=args.threshold_version,
            min_field_accuracy=args.min_field_accuracy,
            min_barcode_accuracy=args.min_barcode_accuracy,
            min_status_accuracy=args.min_status_accuracy,
            allow_synthetic=args.allow_synthetic,
            fixed_set_records=fixed_records,
            fixed_set_manifest_sha256=fixed_hash,
            master_data_gate=master_gate,
            require_formal_evidence=True,
        )
        report["input_sha256"] = hashlib.sha256(args.results.read_bytes()).hexdigest()
        if args.failure_samples:
            _write_failure_samples(args.failure_samples, report["failure_samples"])
            report["failure_samples_path"] = str(args.failure_samples)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
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
