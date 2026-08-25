"""HCT-201 teaching-demo master-data path (INTERNAL_TEACHING_DEMO scope).

These tests pin the compliant teaching-demo enablement path:

- the synthetic snapshot from ``scripts/setup_vision_demo.py`` loads through
  the checked ``hct-master-data/v1`` loader once (and only once) the version
  is explicitly approved via ``MASTER_DATA_APPROVED_VERSIONS``;
- fusion/matching works against the teaching snapshot;
- the snapshot honestly declares that it is NOT the formal released drug set
  (``formal_release_eligible: false``) and the formal fixed-set gate keeps
  blocking teaching-scope records — the teaching exemption cannot leak into a
  formal release;
- ``/meta/capabilities`` distinguishes teaching-demo master data from the
  formal HCT-201 drug set, which stays UNRELEASED.
"""

from __future__ import annotations

import json

from ai.vision.evidence_pipeline import EvidencePipelineRequest, process_evidence
from ai.vision.master_data import load_master_data_snapshot
from fastapi.testclient import TestClient

import setup_vision_demo
from hct201_fixed_set_gate import evaluate_fixed_set

TEACHING_VERSION = setup_vision_demo.VERSION


def test_generated_snapshot_loads_when_version_is_approved(tmp_path) -> None:
    setup_vision_demo.write_snapshot(tmp_path)

    snapshot = load_master_data_snapshot(
        TEACHING_VERSION,
        root=tmp_path,
        approved_versions={TEACHING_VERSION},
    )

    assert snapshot.available is True
    assert snapshot.version == TEACHING_VERSION
    record_ids = {record.record_id for record in snapshot.records}
    assert record_ids == {"rec-amoxicillin-cn", "rec-ibuprofen-en"}


def test_generated_snapshot_stays_fail_closed_without_approval(tmp_path) -> None:
    """A snapshot file on disk is not enough: the version must be approved."""
    setup_vision_demo.write_snapshot(tmp_path)

    snapshot = load_master_data_snapshot(TEACHING_VERSION, root=tmp_path)

    assert snapshot.available is False


def test_snapshot_declares_teaching_scope_not_formal_release(tmp_path) -> None:
    target = setup_vision_demo.write_snapshot(tmp_path)
    document = json.loads(target.read_text(encoding="utf-8"))

    assert document["approval_scope"] == "INTERNAL_TEACHING_DEMO"
    assert document["formal_release_eligible"] is False
    assert document["production_eligible"] is False
    assert document["approval_ref"] == "docs/data/HCT-201-教学演示批准范围-V1.md"


def test_fusion_matches_against_teaching_snapshot(tmp_path) -> None:
    """Name + barcode evidence resolves to the teaching record (no auto-confirm)."""
    setup_vision_demo.write_snapshot(tmp_path)
    master = load_master_data_snapshot(
        TEACHING_VERSION,
        root=tmp_path,
        approved_versions={TEACHING_VERSION},
    )
    request = EvidencePipelineRequest(
        ocr_tokens=[
            {
                "id": "ocr-1",
                "raw_value": "阿莫西林胶囊",
                "confidence": 0.93,
                "engine_version": "paddleocr-demo",
                "language": "zh",
            }
        ],
        barcodes=[
            {
                "id": "bar-1",
                "raw_value": "6901234567892",
                "confidence": 0.99,
                "format": "EAN-13",
                "decoder_version": "zbar-demo",
            }
        ],
        field_proposals=[
            {
                "field_name": "drug_name",
                "raw_value": "阿莫西林胶囊",
                "evidence_ids": ["ocr-1"],
                "confidence": 0.93,
                "parser_version": "rule-demo",
            }
        ],
        master_data_version=TEACHING_VERSION,
    )

    result = process_evidence(request, master_data=master)

    assert result.master_candidates, "teaching snapshot must produce a master candidate"
    candidate = result.master_candidates[0]
    assert candidate.record_id == "rec-amoxicillin-cn"
    assert set(candidate.reasons) == {"BARCODE_EXACT", "NAME_EXACT"}
    # 产品契约：任何候选都必须人工确认，教学路径也不例外。
    assert result.requires_human_confirmation is True


def test_formal_fixed_set_gate_blocks_teaching_scope_records() -> None:
    """INTERNAL_TEACHING_DEMO records can never satisfy the formal gate."""
    records = [
        {
            "sample_id": f"teach-{index}",
            "status": "APPROVED",
            "dataset_scope": "INTERNAL_TEACHING_DEMO",
            "dataset_version": "demo-cn-en-v1",
            "dataset_approval_ref": "docs/data/HCT-201-教学演示批准范围-V1.md",
            "review_record_ref": "",
            "case_type": "known",
            "drug_id": f"demo-drug-{index}",
            "fixed_eval": True,
            "split": "test",
        }
        for index in range(12)
    ]

    findings = evaluate_fixed_set(records)

    codes = {finding.code for finding in findings}
    assert "NOT_APPROVED_REAL_SCOPE" in codes
    assert "MISSING_APPROVAL_REFERENCE" in codes
    assert "REQUIRED_CASE_SET_MISSING" in codes


def test_capabilities_declare_formal_set_unreleased_and_teaching_unconfigured(
    client: TestClient,
) -> None:
    """Default deployment: no approved versions → both capabilities unavailable."""
    body = client.get("/api/v1/meta/capabilities").json()

    assert "hct201-formal-drug-set" in body["unavailable"]
    assert "master-data-teaching-demo" in body["unavailable"]
    assert "master-data-teaching-demo" not in body["available"]


def test_capabilities_expose_teaching_demo_once_configured(
    client: TestClient, tmp_path, monkeypatch
) -> None:
    """Approved + loadable teaching snapshot → teaching available, formal still not."""
    setup_vision_demo.write_snapshot(tmp_path)
    monkeypatch.setattr("app.routes.settings.master_data_root", str(tmp_path))
    monkeypatch.setattr(
        "app.routes.settings.master_data_approved_versions", TEACHING_VERSION
    )

    body = client.get("/api/v1/meta/capabilities").json()

    assert "master-data-teaching-demo" in body["available"]
    assert "hct201-formal-drug-set" in body["unavailable"]
