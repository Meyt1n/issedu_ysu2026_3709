from __future__ import annotations

import hashlib
import json

from ai.vision.master_data import SNAPSHOT_SCHEMA, load_master_data_snapshot


def _write_snapshot(root, *, version: str = "demo-master-v1", tamper: bool = False) -> None:
    payload = {
        "schema_version": SNAPSHOT_SCHEMA,
        "version": version,
        "approval_status": "APPROVED",
        "approval_ref": "test-approval",
        "revocation_status": "ACTIVE",
        "records": [
            {
                "record_id": "demo-record-1",
                "product_barcode": "4006381333931",
                "name_aliases": ["Demo Medicine"],
                "active_ingredients": ["demo-ingredient"],
                "indications": ["demo indication"],
                "cautions": ["demo caution"],
                "contraindications": ["demo contraindication"],
            }
        ],
        "interactions": [
            {
                "record_ids": ["demo-record-1", "demo-record-2"],
                "level": "WARNING",
                "message": "demo interaction",
            }
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["sha256"] = hashlib.sha256(canonical).hexdigest()
    if tamper:
        payload["records"][0]["name_aliases"] = ["Tampered"]
    (root / f"{version}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_loads_versioned_snapshot_with_integrity_check(tmp_path) -> None:
    _write_snapshot(tmp_path)

    snapshot = load_master_data_snapshot(
        "demo-master-v1",
        root=tmp_path,
        approved_versions={"demo-master-v1"},
    )

    assert snapshot.available is True
    assert snapshot.version == "demo-master-v1"
    assert snapshot.records[0].record_id == "demo-record-1"
    assert snapshot.records[0].active_ingredients == ["demo-ingredient"]
    assert snapshot.interactions[0].message == "demo interaction"


def test_rejects_tampered_snapshot_and_path_like_version(tmp_path) -> None:
    _write_snapshot(tmp_path, tamper=True)

    tampered = load_master_data_snapshot(
        "demo-master-v1",
        root=tmp_path,
        approved_versions={"demo-master-v1"},
    )
    traversal = load_master_data_snapshot("../demo-master-v1", root=tmp_path)

    assert tampered.available is False
    assert traversal.available is False


def test_rejects_complete_snapshot_without_server_allowlist(tmp_path) -> None:
    _write_snapshot(tmp_path)

    snapshot = load_master_data_snapshot("demo-master-v1", root=tmp_path)

    assert snapshot.available is False
