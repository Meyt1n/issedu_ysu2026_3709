from __future__ import annotations

import json
from pathlib import Path

from hct201_dataset_audit import audit_manifest


def _record(
    sample_id: str, split: str, group_key: str, digest: str, **extra: object
) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "source_id": f"synthetic-{sample_id}",
        "license": "synthetic",
        "consent_status": "granted",
        "deidentified": True,
        "entity_key": f"entity-{group_key}",
        "session_key": f"session-{group_key}",
        "capture_date": "2026-08-08",
        "device_key": "synthetic-device",
        "group_key": group_key,
        "split": split,
        "status": "APPROVED",
        "sha256": digest,
        "annotation_version": "annotation-spec-v1",
        "dataset_version": "HCT-201-dataset-v1",
        "delete_ref": f"delete-{sample_id}",
        "retention_until": "2026-12-31",
        "fixed_eval": split == "test",
        "unknown_set": split == "unknown",
        "perceptual_hash": sample_id * 16,
        **extra,
    }


def _write_manifest(path: Path, records: list[dict[str, object]]) -> None:
    payload = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
    path.write_text(payload, encoding="utf-8")


def test_valid_synthetic_manifest_passes(tmp_path: Path) -> None:
    records = [
        _record("a", "train", "train-group", "a" * 64),
        _record("b", "validation", "validation-group", "b" * 64),
        _record("c", "test", "test-group", "c" * 64),
        _record("d", "unknown", "unknown-group", "d" * 64),
    ]
    path = tmp_path / "valid.jsonl"
    _write_manifest(path, records)

    report = audit_manifest(path)

    assert report["valid"] is True
    assert report["approved_count"] == 4
    assert report["violations"] == []


def test_unlicensed_or_non_deidentified_record_fails(tmp_path: Path) -> None:
    record = _record(
        "a",
        "test",
        "test-group",
        "a" * 64,
        license="unknown",
        deidentified=False,
    )
    record["consent_status"] = "pending"
    path = tmp_path / "invalid.jsonl"
    _write_manifest(path, [record, _record("u", "unknown", "unknown-group", "b" * 64)])

    report = audit_manifest(path)

    codes = {violation["code"] for violation in report["violations"]}
    assert report["valid"] is False
    assert {"MISSING_LICENSE", "UNAPPROVED_CONSENT", "NOT_DEIDENTIFIED"} <= codes


def test_group_leakage_duplicate_and_pii_are_reported(tmp_path: Path) -> None:
    records = [
        _record("a", "train", "same-group", "a" * 64),
        _record("b", "validation", "same-group", "b" * 64),
        _record(
            "c",
            "test",
            "test-group",
            "b" * 64,
            contact_email="redacted@example.invalid",
            perceptual_hash="b" * 16,
        ),
        _record("d", "unknown", "unknown-group", "d" * 64),
    ]
    records[2]["name"] = "should-not-be-present"
    path = tmp_path / "manifest.jsonl"
    _write_manifest(path, records)

    report = audit_manifest(path)

    codes = {violation["code"] for violation in report["violations"]}
    assert {"GROUP_LEAKAGE", "DUPLICATE_SHA256", "PII_FIELD", "NEAR_DUPLICATE"} <= codes


def test_quarantined_record_cannot_enter_training_split(tmp_path: Path) -> None:
    quarantined = _record("q", "train", "quarantine-group", "e" * 64)
    quarantined.update(
        {
            "status": "QUARANTINED",
            "consent_status": "public-license-pending-human-verification",
            "fixed_eval": False,
            "unknown_set": False,
        }
    )
    path = tmp_path / "quarantined.jsonl"
    _write_manifest(
        path,
        [
            quarantined,
            _record("t", "test", "test-group", "f" * 64),
            _record("u", "unknown", "unknown-group", "1" * 64),
        ],
    )

    report = audit_manifest(path)

    violations = [
        item
        for item in report["violations"]
        if item["code"] == "NON_APPROVED_SPLIT" and item.get("sample_id") == "q"
    ]
    assert len(violations) == 1
