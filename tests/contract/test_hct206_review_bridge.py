"""HCT-206 → HCT-207 bridge: fusion output must land in the review center.

Closes the vision loop: evidence submission for a member-bound vision task
creates exactly one review task carrying fused candidates; confirming that
task writes a CONFIRMED health event. MATCHED never bypasses human review.
"""
from __future__ import annotations

import hashlib
import json

import cv2
import numpy as np
from ai.vision.evidence_pipeline import EvidencePipelineRequest, issue_adapter_receipt

from app.config import get_settings

ACTOR = "bridge-owner"


def _encode_demo_image() -> bytes:
    image = np.full((480, 640, 3), 110, dtype=np.uint8)
    cv2.rectangle(image, (140, 90), (500, 390), (225, 225, 225), -1)
    cv2.rectangle(image, (140, 90), (500, 390), (20, 20, 20), 6)
    cv2.putText(image, "BRIDGE", (200, 245), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (20, 20, 20), 4)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def _setup_household_member(client) -> tuple[str, str]:
    household = client.post(
        "/api/v1/households",
        json={"name": "桥接演示家庭"},
        headers={"X-Actor-ID": ACTOR},
    )
    assert household.status_code == 201, household.text
    household_id = household.json()["id"]
    member = client.post(
        f"/api/v1/households/{household_id}/members",
        json={"display_name": "桥接演示成员", "role": "DEPENDENT"},
        headers={"X-Actor-ID": ACTOR},
    )
    assert member.status_code == 201, member.text
    return household_id, member.json()["id"]


def _create_member_task(client, tmp_path, monkeypatch, member_id: str) -> tuple[str, str]:
    content = _encode_demo_image()
    quality = client.post(
        "/api/v1/vision-quality/check",
        files={"file": ("bridge.png", content, "image/png")},
        data={"media_type": "image"},
        headers={"X-Actor-ID": ACTOR},
    )
    assert quality.status_code == 200
    file_id = "bridge-demo.png"
    (tmp_path / file_id).write_bytes(content)
    monkeypatch.setattr("app.routes.settings.file_root", str(tmp_path))
    response = client.post(
        "/api/v1/vision-tasks",
        json={
            "file_id": file_id,
            "member_id": member_id,
            "quality_receipt": quality.json()["quality_receipt"],
        },
        headers={"X-Actor-ID": ACTOR},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], response.json()["input_digest"]


def _install_master_snapshot(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routes.settings.master_data_approved_versions", "bridge-master-v1"
    )
    snapshot = {
        "schema_version": "hct-master-data/v1",
        "version": "bridge-master-v1",
        "approval_status": "APPROVED",
        "approval_ref": "test-approval",
        "revocation_status": "ACTIVE",
        "records": [
            {
                "record_id": "rec-amoxicillin",
                "product_barcode": "4006381333931",
                "name_aliases": ["阿莫西林胶囊", "Amoxicillin Capsules"],
                "specification": "0.25g×24粒",
            }
        ],
    }
    canonical = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    snapshot["sha256"] = hashlib.sha256(canonical).hexdigest()
    (tmp_path / "bridge-master-v1.json").write_text(
        json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr("app.routes.settings.master_data_root", str(tmp_path))


def _signed_payload(task_id: str, input_digest: str, payload: dict) -> dict:
    request = EvidencePipelineRequest.model_validate(payload)
    receipt = issue_adapter_receipt(
        task_id, input_digest, request, get_settings().vision_adapter_signing_key
    )
    return {**payload, "adapter_receipt": receipt}


def _evidence_payload(task_id: str, input_digest: str) -> dict:
    return _signed_payload(
        task_id,
        input_digest,
        {
            "ocr_tokens": [
                {
                    "id": "ocr-1",
                    "raw_value": "阿莫西林胶囊",
                    "region": {
                        "x": 150,
                        "y": 120,
                        "width": 300,
                        "height": 60,
                        "coordinate_space": "pixel",
                    },
                    "confidence": 0.92,
                    "engine_version": "ocr-local-v1",
                }
            ],
            "barcodes": [
                {
                    "id": "barcode-1",
                    "raw_value": "4006381333931",
                    "format": "EAN-13",
                    "confidence": 0.99,
                    "decoder_version": "decoder-v1",
                }
            ],
            "field_proposals": [
                {
                    "field_name": "drug_name",
                    "raw_value": "阿莫西林胶囊",
                    "evidence_ids": ["ocr-1"],
                    "confidence": 0.9,
                    "parser_version": "rules-v1",
                }
            ],
            "master_data_version": "bridge-master-v1",
        },
    )


def test_evidence_submission_bridges_into_review_center(
    client, tmp_path, monkeypatch
) -> None:
    household_id, member_id = _setup_household_member(client)
    task_id, input_digest = _create_member_task(client, tmp_path, monkeypatch, member_id)
    _install_master_snapshot(tmp_path, monkeypatch)

    evidence = client.post(
        f"/api/v1/vision-tasks/{task_id}/evidence",
        json=_evidence_payload(task_id, input_digest),
        headers={"X-Actor-ID": ACTOR},
    )
    assert evidence.status_code == 200, evidence.text

    reviews = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/review-tasks",
        headers={"X-Actor-ID": ACTOR},
    )
    assert reviews.status_code == 200, reviews.text
    body = reviews.json()
    assert len(body) == 1, "evidence submission must create exactly one review task"
    review = body[0]
    assert review["vision_task_id"] == task_id
    assert review["status"] == "PENDING_REVIEW"
    assert review["fusion_status"] in {"MATCHED", "CONFLICT", "UNKNOWN", "LOW_QUALITY"}
    assert review["candidates"], "fused master candidates must reach the reviewer"
    assert review["candidates"][0]["drug_name"] == "阿莫西林胶囊"
    assert 0 <= review["candidates"][0]["confidence"] <= 1

    confirm = client.post(
        f"/api/v1/households/{household_id}/review-tasks/{review['id']}/confirm",
        json={"selected_index": 0, "confirmation_note": "与实物核对一致"},
        headers={"X-Actor-ID": ACTOR, "Idempotency-Key": "bridge-confirm-1"},
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "CONFIRMED"

    timeline = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/timeline",
        headers={"X-Actor-ID": ACTOR},
    )
    assert timeline.status_code == 200
    events = timeline.json()
    assert any(
        event["event_type"] == "medication_confirmed"
        and event["confirmation_status"] == "CONFIRMED"
        and event["payload"].get("drug_name") == "阿莫西林胶囊"
        for event in events
    ), "confirming the review must append a CONFIRMED health event"


def test_no_master_match_bridges_ocr_fields_as_candidates(
    client, tmp_path, monkeypatch
) -> None:
    """Unmatched packages still reach review with the raw OCR extraction."""
    household_id, member_id = _setup_household_member(client)
    task_id, input_digest = _create_member_task(client, tmp_path, monkeypatch, member_id)
    _install_master_snapshot(tmp_path, monkeypatch)

    payload = _signed_payload(
        task_id,
        input_digest,
        {
            "ocr_tokens": [
                {
                    "id": "ocr-1",
                    "raw_value": "演示降压灵片",
                    "confidence": 0.93,
                    "engine_version": "ocr-local-v1",
                },
                {
                    "id": "ocr-2",
                    "raw_value": "5mg×28片",
                    "confidence": 0.95,
                    "engine_version": "ocr-local-v1",
                },
            ],
            "field_proposals": [
                {
                    "field_name": "drug_name",
                    "raw_value": "演示降压灵片",
                    "evidence_ids": ["ocr-1"],
                    "confidence": 0.6,
                    "parser_version": "rules-v1",
                },
                {
                    "field_name": "specification",
                    "raw_value": "5mg×28片",
                    "evidence_ids": ["ocr-2"],
                    "confidence": 0.9,
                    "parser_version": "rules-v1",
                },
            ],
            "master_data_version": "bridge-master-v1",
        },
    )
    evidence = client.post(
        f"/api/v1/vision-tasks/{task_id}/evidence",
        json=payload,
        headers={"X-Actor-ID": ACTOR},
    )
    assert evidence.status_code == 200, evidence.text

    reviews = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/review-tasks",
        headers={"X-Actor-ID": ACTOR},
    )
    assert reviews.status_code == 200
    review = reviews.json()[0]
    assert review["candidates"], "OCR extraction must reach the reviewer even without master match"
    names = [candidate["drug_name"] for candidate in review["candidates"]]
    assert "演示降压灵片" in names
    matched = next(c for c in review["candidates"] if c["drug_name"] == "演示降压灵片")
    assert matched["dosage"] == "5mg×28片"
    assert matched["candidate_id"] is None


def test_worker_poll_lists_own_queued_tasks_only(
    client, tmp_path, monkeypatch
) -> None:
    """Adapter workers poll GET /vision-tasks for their own queued jobs."""
    _, member_id = _setup_household_member(client)
    task_id, _ = _create_member_task(client, tmp_path, monkeypatch, member_id)

    mine = client.get(
        "/api/v1/vision-tasks",
        params={"task_status": "queued"},
        headers={"X-Actor-ID": ACTOR},
    )
    assert mine.status_code == 200, mine.text
    ids = [item["id"] for item in mine.json()]
    assert task_id in ids
    assert all(item["status"] == "queued" for item in mine.json())
    assert all(item["created_by"] == ACTOR for item in mine.json())

    others = client.get(
        "/api/v1/vision-tasks",
        params={"task_status": "queued"},
        headers={"X-Actor-ID": "someone-else"},
    )
    assert others.status_code == 200
    assert others.json() == []

    invalid = client.get(
        "/api/v1/vision-tasks",
        params={"task_status": "bogus"},
        headers={"X-Actor-ID": ACTOR},
    )
    assert invalid.status_code == 422


def test_taskless_member_evidence_still_succeeds_without_review(
    client, tmp_path, monkeypatch
) -> None:
    """Tasks without a member keep the old contract: evidence stored, no review."""
    content = _encode_demo_image()
    quality = client.post(
        "/api/v1/vision-quality/check",
        files={"file": ("nomember.png", content, "image/png")},
        data={"media_type": "image"},
        headers={"X-Actor-ID": ACTOR},
    )
    file_id = "nomember-demo.png"
    (tmp_path / file_id).write_bytes(content)
    monkeypatch.setattr("app.routes.settings.file_root", str(tmp_path))
    task = client.post(
        "/api/v1/vision-tasks",
        json={"file_id": file_id, "quality_receipt": quality.json()["quality_receipt"]},
        headers={"X-Actor-ID": ACTOR},
    )
    assert task.status_code == 201
    task_id, input_digest = task.json()["id"], task.json()["input_digest"]

    payload = _signed_payload(
        task_id,
        input_digest,
        {
            "ocr_tokens": [
                {
                    "id": "ocr-1",
                    "raw_value": "Loose Evidence",
                    "confidence": 0.8,
                    "engine_version": "ocr-local-v1",
                }
            ]
        },
    )
    response = client.post(
        f"/api/v1/vision-tasks/{task_id}/evidence",
        json=payload,
        headers={"X-Actor-ID": ACTOR},
    )
    assert response.status_code == 200, response.text
