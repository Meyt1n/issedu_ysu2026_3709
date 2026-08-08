"""Audit HCT-201 dataset metadata manifests without reading image or video content."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = {
    "sample_id",
    "source_id",
    "license",
    "consent_status",
    "deidentified",
    "entity_key",
    "session_key",
    "capture_date",
    "device_key",
    "group_key",
    "split",
    "status",
    "sha256",
    "annotation_version",
    "dataset_version",
    "delete_ref",
    "retention_until",
}
ALLOWED_STATUS = {"APPROVED", "QUARANTINED", "REVOKED"}
ALLOWED_SPLITS = {"train", "validation", "test", "unknown", "quarantine"}
PII_KEYS = {
    "name",
    "full_name",
    "phone",
    "mobile",
    "email",
    "address",
    "id_card",
    "身份证",
    "处方号",
    "病历号",
    "prescription_no",
    "medical_record_no",
}
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _violation(code: str, message: str, sample_id: str | None = None) -> dict[str, str]:
    item = {"code": code, "message": message}
    if sample_id:
        item["sample_id"] = sample_id
    return item


def _key_names(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys = {str(key).casefold() for key in value}
        for child in value.values():
            keys.update(_key_names(child))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for child in value:
            keys.update(_key_names(child))
        return keys
    return set()


def _hamming_distance(left: str, right: str) -> int | None:
    if not left or not right or len(left) != len(right):
        return None
    try:
        return sum((int(a, 16) ^ int(b, 16)).bit_count() for a, b in zip(left, right, strict=True))
    except ValueError:
        return None


def load_manifest(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    violations: list[dict[str, str]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            violations.append(_violation("INVALID_JSON", f"line {line_number}: {exc.msg}"))
            continue
        if not isinstance(record, dict):
            violations.append(
                _violation("RECORD_NOT_OBJECT", f"line {line_number} must be a JSON object")
            )
            continue
        records.append(record)
    if not records:
        violations.append(
            _violation("EMPTY_MANIFEST", "manifest must contain at least one JSON object")
        )
    return records, violations


def audit_manifest(path: Path) -> dict[str, Any]:
    records, violations = load_manifest(path)
    manifest_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    sample_ids: set[str] = set()
    approved_records: list[dict[str, Any]] = []
    groups: dict[str, set[str]] = defaultdict(set)
    hashes: dict[str, str] = {}
    perceptual_hashes: list[tuple[str, str, str]] = []
    dataset_versions: set[str] = set()
    counts: Counter[str] = Counter()

    for record in records:
        sample_id = str(record.get("sample_id", ""))
        if sample_id in sample_ids:
            violations.append(_violation("DUPLICATE_SAMPLE_ID", "sample_id is repeated", sample_id))
        sample_ids.add(sample_id)
        missing = sorted(REQUIRED_FIELDS - record.keys())
        if missing:
            violations.append(
                _violation("MISSING_FIELDS", f"missing: {', '.join(missing)}", sample_id or None)
            )
            continue

        status = record["status"]
        split = record["split"]
        counts[f"status:{status}"] += 1
        counts[f"split:{split}"] += 1
        dataset_versions.add(str(record["dataset_version"]))
        if status not in ALLOWED_STATUS:
            violations.append(
                _violation("INVALID_STATUS", f"unsupported status: {status}", sample_id)
            )
        if split not in ALLOWED_SPLITS:
            violations.append(_violation("INVALID_SPLIT", f"unsupported split: {split}", sample_id))
        if not HEX_SHA256.fullmatch(str(record["sha256"]).lower()):
            violations.append(
                _violation(
                    "INVALID_SHA256", "sha256 must be 64 lowercase hex characters", sample_id
                )
            )
        if record["license"] in {"", "unknown", "UNSPECIFIED", None}:
            violations.append(_violation("MISSING_LICENSE", "license is not specified", sample_id))
        if record["consent_status"] in {"", "unknown", "UNSPECIFIED", None}:
            violations.append(
                _violation("MISSING_CONSENT", "consent_status is not specified", sample_id)
            )
        if record["deidentified"] is not True:
            violations.append(
                _violation("NOT_DEIDENTIFIED", "deidentified must be true", sample_id)
            )
        if not str(record["delete_ref"]).strip() or not str(record["retention_until"]).strip():
            violations.append(
                _violation(
                    "MISSING_RETENTION", "delete_ref and retention_until are required", sample_id
                )
            )
        if PII_KEYS.intersection(_key_names(record)) or record.get("contains_pii") is True:
            violations.append(
                _violation("PII_FIELD", "manifest contains a prohibited PII field", sample_id)
            )

        if status == "APPROVED":
            approved_records.append(record)
            groups[str(record["group_key"])].add(str(split))
            digest = str(record["sha256"]).lower()
            if digest in hashes:
                violations.append(
                    _violation("DUPLICATE_SHA256", f"same sha256 as {hashes[digest]}", sample_id)
                )
            hashes[digest] = sample_id
            if record.get("consent_status") != "granted":
                violations.append(
                    _violation("UNAPPROVED_CONSENT", "APPROVED requires granted consent", sample_id)
                )
            if record.get("fixed_eval") and split not in {"test", "unknown"}:
                violations.append(
                    _violation("FIXED_EVAL_SPLIT", "fixed_eval must be test or unknown", sample_id)
                )
            if record.get("unknown_set") and split != "unknown":
                violations.append(
                    _violation("UNKNOWN_SPLIT", "unknown_set must use the unknown split", sample_id)
                )
            perceptual_hash = str(record.get("perceptual_hash", "")).lower()
            if perceptual_hash:
                perceptual_hashes.append((sample_id, str(split), perceptual_hash))
        elif split not in {"quarantine", "unknown"}:
            violations.append(
                _violation(
                    "NON_APPROVED_SPLIT",
                    "QUARANTINED/REVOKED records cannot be train/validation/test",
                    sample_id,
                )
            )

    for group_key, split_set in groups.items():
        if len(split_set) > 1:
            violations.append(_violation("GROUP_LEAKAGE", f"group_key spans splits: {group_key}"))

    for index, (sample_id, split, perceptual_hash) in enumerate(perceptual_hashes):
        for other_id, other_split, other_hash in perceptual_hashes[index + 1 :]:
            distance = _hamming_distance(perceptual_hash, other_hash)
            if distance is not None and distance <= 2:
                violations.append(
                    _violation(
                        "NEAR_DUPLICATE",
                        (
                            "perceptual hashes are within distance "
                            f"{distance}: {sample_id}/{other_id} ({split}/{other_split})"
                        ),
                    )
                )

    if len(dataset_versions) > 1:
        violations.append(
            _violation("MIXED_DATASET_VERSIONS", f"versions: {sorted(dataset_versions)}")
        )
    if records and not any(
        record.get("fixed_eval") is True and record.get("split") == "test"
        for record in approved_records
    ):
        violations.append(
            _violation("MISSING_FIXED_EVAL", "approved test records must include fixed_eval=true")
        )
    if records and not any(
        record.get("unknown_set") is True and record.get("split") == "unknown"
        for record in approved_records
    ):
        violations.append(
            _violation(
                "MISSING_UNKNOWN_SET", "approved unknown records must include unknown_set=true"
            )
        )

    return {
        "status": "ok" if not violations else "failed",
        "valid": not violations,
        "manifest": str(path),
        "manifest_sha256": manifest_sha256,
        "record_count": len(records),
        "approved_count": len(approved_records),
        "counts": dict(sorted(counts.items())),
        "dataset_versions": sorted(dataset_versions),
        "violations": violations,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit HCT-201 metadata manifests without reading media files."
    )
    parser.add_argument(
        "--manifest", type=Path, required=True, help="UTF-8 JSONL metadata manifest"
    )
    parser.add_argument(
        "--strict", action="store_true", help="return non-zero when the manifest has violations"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = audit_manifest(args.manifest)
    except OSError as exc:
        print(
            json.dumps({"status": "failed", "valid": False, "error": str(exc)}, ensure_ascii=False)
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if args.strict and not report["valid"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
