"""Validate the approved HCT-205 master-data snapshot used by formal reports.

The repository deliberately does not contain a real drug master snapshot.  This
gate checks an externally supplied, controlled snapshot without printing its
drug names or other clinical fields.  A snapshot that is structurally valid is
not by itself proof that the data is real; the approval reference and review
record must remain auditable outside Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from hct201_formal_gate import load_manifest

SNAPSHOT_SCHEMA = "hct-master-data/v1"
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
DEFAULT_MIN_RECORDS = 12
DEFAULT_MAX_RECORDS = 20


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _nonempty(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _safe_record_ids(records: list[Any]) -> tuple[list[str], list[dict[str, str]]]:
    ids: list[str] = []
    findings: list[dict[str, str]] = []
    seen: set[str] = set()
    barcodes: set[str] = set()
    required_fields = ("record_id", "name_aliases", "specification", "manufacturer")
    for index, raw in enumerate(records, start=1):
        prefix = f"record {index}"
        if not isinstance(raw, dict):
            findings.append(
                {"code": "INVALID_RECORD", "message": f"{prefix}: record must be object"}
            )
            continue
        record_id = str(raw.get("record_id", "")).strip()
        if not record_id:
            findings.append(
                {"code": "MISSING_RECORD_ID", "message": f"{prefix}: record_id is required"}
            )
        elif record_id in seen:
            findings.append(
                {"code": "DUPLICATE_RECORD_ID", "message": f"{prefix}: duplicate record_id"}
            )
        else:
            seen.add(record_id)
            ids.append(record_id)
        aliases = raw.get("name_aliases")
        if (
            not isinstance(aliases, list)
            or not aliases
            or not all(_nonempty(item) for item in aliases)
        ):
            findings.append(
                {
                    "code": "INVALID_NAME_ALIASES",
                    "message": f"{prefix}: name_aliases must be non-empty",
                }
            )
        for field in required_fields[2:]:
            if not _nonempty(raw.get(field)):
                findings.append(
                    {"code": "MISSING_RECORD_FIELD", "message": f"{prefix}: {field} is required"}
                )
        barcode = str(raw.get("product_barcode", "")).strip()
        if barcode:
            if barcode in barcodes:
                findings.append(
                    {
                        "code": "DUPLICATE_PRODUCT_BARCODE",
                        "message": f"{prefix}: duplicate product_barcode",
                    }
                )
            barcodes.add(barcode)
    return sorted(ids), findings


def evaluate_snapshot(
    document: dict[str, Any],
    *,
    min_records: int = DEFAULT_MIN_RECORDS,
    max_records: int = DEFAULT_MAX_RECORDS,
    fixed_set_records: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    findings: list[dict[str, str]] = []
    if document.get("schema_version") != SNAPSHOT_SCHEMA:
        findings.append(
            {"code": "INVALID_SCHEMA", "message": "schema_version must be hct-master-data/v1"}
        )
    version = str(document.get("version", "")).strip()
    if not VERSION_PATTERN.fullmatch(version) or version == "unavailable":
        findings.append(
            {"code": "INVALID_VERSION", "message": "version is not a safe snapshot version"}
        )
    if document.get("approval_status") != "APPROVED":
        findings.append(
            {"code": "DATA_NOT_APPROVED", "message": "approval_status must be APPROVED"}
        )
    if not _nonempty(document.get("approval_ref")):
        findings.append({"code": "MISSING_APPROVAL_REF", "message": "approval_ref is required"})
    if document.get("revocation_status") != "ACTIVE":
        findings.append({"code": "SNAPSHOT_REVOKED", "message": "revocation_status must be ACTIVE"})

    declared_hash = document.get("sha256")
    payload = dict(document)
    payload.pop("sha256", None)
    computed_hash = hashlib.sha256(_canonical_payload(payload)).hexdigest()
    if not isinstance(declared_hash, str) or declared_hash.lower() != computed_hash:
        findings.append(
            {"code": "SNAPSHOT_HASH_MISMATCH", "message": "sha256 does not match canonical payload"}
        )

    raw_records = document.get("records")
    if not isinstance(raw_records, list):
        findings.append({"code": "INVALID_RECORDS", "message": "records must be a list"})
        raw_records = []
    record_ids, record_findings = _safe_record_ids(raw_records)
    findings.extend(record_findings)
    if not min_records <= len(record_ids) <= max_records:
        findings.append(
            {
                "code": "RECORD_COUNT_OUT_OF_RANGE",
                "message": f"record count={len(record_ids)}; expected {min_records}..{max_records}",
            }
        )

    interactions = document.get("interactions", [])
    if not isinstance(interactions, list):
        findings.append(
            {"code": "INVALID_INTERACTIONS", "message": "interactions must be a list when present"}
        )

    if fixed_set_records is not None:
        fixed_ids = {
            str(row.get("master_data_record_id") or row.get("drug_id", "")).strip()
            for row in fixed_set_records
            if row.get("case_type") == "known"
            and _nonempty(row.get("master_data_record_id") or row.get("drug_id"))
        }
        missing_ids = sorted(fixed_ids - set(record_ids))
        if missing_ids:
            findings.append(
                {
                    "code": "FIXED_DRUG_NOT_IN_MASTER",
                    "message": f"{len(missing_ids)} fixed-set drug IDs are absent from master data",
                }
            )

    metadata = {
        "version": version or None,
        "master_data_sha256": declared_hash if isinstance(declared_hash, str) else None,
        "record_count": len(record_ids),
        "record_ids": record_ids,
        "approval_ref": str(document.get("approval_ref", "")).strip() or None,
    }
    return findings, metadata


def gate_snapshot(
    path: Path,
    *,
    min_records: int = DEFAULT_MIN_RECORDS,
    max_records: int = DEFAULT_MAX_RECORDS,
    fixed_set_manifest: Path | None = None,
) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("snapshot must be a JSON object")
        fixed_records = load_manifest(fixed_set_manifest) if fixed_set_manifest else None
        findings, metadata = evaluate_snapshot(
            document,
            min_records=min_records,
            max_records=max_records,
            fixed_set_records=fixed_records,
        )
        if fixed_records is not None:
            from hct201_fixed_set_gate import evaluate_fixed_set

            fixed_findings = evaluate_fixed_set(fixed_records)
            if fixed_findings:
                findings.append(
                    {
                        "code": "FIXED_SET_GATE_BLOCKED",
                        "message": "linked fixed-set manifest is not approved",
                    }
                )
        passed = not findings
        report = {
            "schema_version": "hct205-approved-master-data-gate/v1",
            "snapshot": path.name,
            "snapshot_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            **metadata,
            "fixed_set_manifest_sha256": (
                hashlib.sha256(fixed_set_manifest.read_bytes()).hexdigest()
                if fixed_set_manifest
                else None
            ),
            "passed": passed,
            "decision": "ALLOW_APPROVED_MASTER_DATA" if passed else "BLOCK_APPROVED_MASTER_DATA",
            "findings": findings,
            "limitations": [
                "This gate checks declared approval and structural integrity; it does not "
                "independently verify the external review record.",
                "No raw names, barcodes, indications or other clinical fields are emitted in "
                "this report.",
            ],
        }
        return report
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {
            "schema_version": "hct205-approved-master-data-gate/v1",
            "snapshot": path.name,
            "passed": False,
            "decision": "BLOCK_APPROVED_MASTER_DATA",
            "findings": [{"code": "SNAPSHOT_INPUT_ERROR", "message": str(exc)}],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--fixed-set-manifest", type=Path)
    parser.add_argument("--min-records", type=int, default=DEFAULT_MIN_RECORDS)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = gate_snapshot(
        args.snapshot,
        min_records=args.min_records,
        max_records=args.max_records,
        fixed_set_manifest=args.fixed_set_manifest,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
