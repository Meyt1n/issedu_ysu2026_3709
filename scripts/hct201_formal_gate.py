"""Validate the HCT-201 manifest before any formal CV training.

This gate intentionally reads metadata only.  It exits non-zero unless the
manifest proves authorization, real capture grouping, frozen fixed evaluation
and unknown sets, and no split leakage.  Experimental/quarantined data must
remain usable only through an explicitly separate experiment path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SPLITS = {"train", "validation", "test", "unknown"}
CONSENT_STATUSES = {"public-license", "explicit-training-consent", "synthetic"}
REQUIRED_FIELDS = {
    "sample_id",
    "source_id",
    "source_url",
    "license",
    "consent_status",
    "authorization_evidence_ref",
    "deidentified",
    "delete_ref",
    "retention_until",
    "sha256",
    "group_key",
    "entity_key",
    "session_key",
    "grouping_evidence_ref",
    "split",
    "fixed_eval",
    "unknown_set",
}


@dataclass(frozen=True)
class Finding:
    code: str
    message: str


def _is_nonempty(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _is_placeholder(value: Any) -> bool:
    text = str(value).strip().lower()
    return not text or text in {"unknown", "tbd", "todo", "n/a", "none"}


def _is_untrusted_group_key(value: Any) -> bool:
    text = str(value).strip().lower()
    return _is_placeholder(text) or text.startswith("proxy-") or "unknown" in text


def load_manifest(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_number}: invalid JSON: {exc.msg}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"line {line_number}: record must be an object")
            records.append(record)
    if not records:
        raise ValueError("manifest is empty")
    return records


def evaluate(records: list[dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    groups: dict[str, set[str]] = defaultdict(set)
    split_counts = defaultdict(int)

    for index, record in enumerate(records, start=1):
        prefix = f"record {index}"
        missing = sorted(field for field in REQUIRED_FIELDS if field not in record)
        if missing:
            findings.append(Finding("MISSING_METADATA", f"{prefix}: missing {', '.join(missing)}"))

        sample_id = str(record.get("sample_id", "")).strip()
        if not sample_id:
            findings.append(Finding("EMPTY_SAMPLE_ID", f"{prefix}: sample_id is empty"))
        elif sample_id in seen_ids:
            findings.append(
                Finding("DUPLICATE_SAMPLE_ID", f"{prefix}: duplicate sample_id {sample_id}")
            )
        seen_ids.add(sample_id)

        digest = str(record.get("sha256", "")).strip().lower()
        if not digest:
            findings.append(Finding("EMPTY_SHA256", f"{prefix}: sha256 is empty"))
        elif digest in seen_hashes:
            findings.append(Finding("DUPLICATE_SHA256", f"{prefix}: duplicate sha256 {digest}"))
        seen_hashes.add(digest)

        if record.get("status") != "APPROVED":
            findings.append(Finding("DATA_NOT_APPROVED", f"{prefix}: status must be APPROVED"))

        consent = str(record.get("consent_status", "")).strip()
        if consent not in CONSENT_STATUSES:
            findings.append(
                Finding("INVALID_CONSENT", f"{prefix}: unsupported consent_status {consent!r}")
            )
        if not _is_nonempty(record.get("license")):
            findings.append(Finding("MISSING_LICENSE", f"{prefix}: license is required"))
        if not _is_nonempty(record.get("authorization_evidence_ref")):
            findings.append(
                Finding(
                    "MISSING_AUTHORIZATION_EVIDENCE",
                    f"{prefix}: authorization evidence is required",
                )
            )
        if record.get("deidentified") is not True:
            findings.append(Finding("NOT_DEIDENTIFIED", f"{prefix}: deidentified must be true"))
        for field in ("source_url", "delete_ref", "retention_until"):
            if not _is_nonempty(record.get(field)):
                findings.append(
                    Finding("MISSING_LIFECYCLE_EVIDENCE", f"{prefix}: {field} is required")
                )

        group_key = str(record.get("group_key", "")).strip()
        entity_key = str(record.get("entity_key", "")).strip()
        session_key = str(record.get("session_key", "")).strip()
        grouping_ref = record.get("grouping_evidence_ref")
        if _is_untrusted_group_key(group_key):
            findings.append(
                Finding("NOT_REAL_GROUP", f"{prefix}: group_key is missing or proxy-derived")
            )
        if _is_untrusted_group_key(entity_key) or _is_untrusted_group_key(session_key):
            findings.append(
                Finding(
                    "MISSING_CAPTURE_GROUP", f"{prefix}: entity_key and session_key are required"
                )
            )
        if not _is_nonempty(grouping_ref):
            findings.append(
                Finding("MISSING_GROUPING_EVIDENCE", f"{prefix}: grouping evidence is required")
            )

        split = str(record.get("split", "")).strip()
        if split not in SPLITS:
            findings.append(
                Finding("INVALID_SPLIT", f"{prefix}: split must be one of {sorted(SPLITS)}")
            )
        else:
            split_counts[split] += 1
            if split in {"test", "unknown"} and record.get("fixed_eval") is not True:
                findings.append(
                    Finding("EVAL_NOT_FROZEN", f"{prefix}: {split} must set fixed_eval=true")
                )
            if split in {"train", "validation"} and record.get("fixed_eval") is not False:
                findings.append(
                    Finding(
                        "TRAIN_LEAKS_FIXED_EVAL", f"{prefix}: {split} must set fixed_eval=false"
                    )
                )
            if record.get("unknown_set") is not (split == "unknown"):
                findings.append(
                    Finding(
                        "UNKNOWN_FLAG_MISMATCH", f"{prefix}: unknown_set must match split=unknown"
                    )
                )

        if split in SPLITS and group_key:
            groups[group_key].add(split)

        if split == "unknown" and not _is_nonempty(record.get("unknown_reason")):
            findings.append(
                Finding("MISSING_UNKNOWN_REASON", f"{prefix}: unknown_reason is required")
            )

    for group_key, splits in groups.items():
        if len(splits) > 1:
            findings.append(
                Finding("GROUP_SPLIT_LEAK", f"group {group_key} occurs in {sorted(splits)}")
            )

    for split in sorted(SPLITS):
        if split_counts[split] == 0:
            findings.append(Finding("EMPTY_REQUIRED_SPLIT", f"split {split} has no records"))

    return findings


def build_report(
    path: Path, records: list[dict[str, Any]], findings: list[Finding]
) -> dict[str, Any]:
    split_counts = defaultdict(int)
    statuses = defaultdict(int)
    for record in records:
        split_counts[str(record.get("split", ""))] += 1
        statuses[str(record.get("status", ""))] += 1
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "gate": "HCT-201-formal-training-v1",
        "manifest": str(path.name),
        "manifest_sha256": digest,
        "record_count": len(records),
        "status_counts": dict(sorted(statuses.items())),
        "split_counts": dict(sorted(split_counts.items())),
        "passed": not findings,
        "findings": [{"code": item.code, "message": item.message} for item in findings],
        "decision": "ALLOW_FORMAL_TRAINING" if not findings else "BLOCK_FORMAL_TRAINING",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        records = load_manifest(args.manifest)
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {"passed": False, "decision": "BLOCK_FORMAL_TRAINING", "error": str(exc)},
                ensure_ascii=False,
            )
        )
        return 2

    findings = evaluate(records)
    report = build_report(args.manifest, records, findings)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
