"""HCT-405 portal continuous demo: member capture scope → owner review → member read.

Exercises the dual-portal permission model (HCT-439) against the existing
vision/review bridge (HCT-206/207) without claiming real OCR accuracy.
Maps to acceptance-gate scenario ``vision_scan_to_manual_confirm``.
"""

from __future__ import annotations

import hashlib
import json

import cv2
import numpy as np
import pytest
from ai.vision.evidence_pipeline import EvidencePipelineRequest, issue_adapter_receipt
from fastapi.testclient import TestClient

from app.config import get_settings

OWNER = "portal-owner"
MEMBER = "portal-grandma"


def _encode_demo_image() -> bytes:
    image = np.full((480, 640, 3), 110, dtype=np.uint8)
    cv2.rectangle(image, (140, 90), (500, 390), (225, 225, 225), -1)
    cv2.rectangle(image, (140, 90), (500, 390), (20, 20, 20), 6)
    cv2.putText(image, "PORTAL", (190, 245), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (20, 20, 20), 4)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def _setup(client: TestClient) -> tuple[str, str, str]:
    household = client.post(
        "/api/v1/households",
        headers={"X-Actor-Id": OWNER},
        json={"name": "门户连续演示家庭"},
    )
    assert household.status_code == 201, household.text
    household_id = household.json()["id"]
    member = client.post(
        f"/api/v1/households/{household_id}/members",
        headers={"X-Actor-Id": OWNER},
        json={"display_name": "奶奶", "role": "DEPENDENT", "actor_id": MEMBER},
    )
    assert member.status_code == 201, member.text
    return household_id, member.json()["id"], member.json()["actor_id"]


def _install_master_snapshot(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routes.settings.master_data_approved_versions",
        "portal-master-v1",
    )
    snapshot = {
        "schema_version": "hct-master-data/v1",
        "version": "portal-master-v1",
        "approval_status": "APPROVED",
        "entries": [
            {
                "candidate_id": "portal-drug-1",
                "drug_name": "合成布洛芬缓释胶囊",
                "specification": "0.3g×20粒",
                "manufacturer": "合成制药",
            }
        ],
    }
    path = tmp_path / "portal-master-v1.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    monkeypatch.setattr("app.routes.settings.master_data_root", str(tmp_path))


def _create_member_task(
    client: TestClient,
    tmp_path,
    monkeypatch,
    member_id: str,
) -> tuple[str, str]:
    content = _encode_demo_image()
    quality = client.post(
        "/api/v1/vision-quality/check",
        files={"file": ("portal.png", content, "image/png")},
        data={"media_type": "image"},
        headers={"X-Actor-Id": MEMBER, "X-Access-Purpose": "family-care"},
    )
    assert quality.status_code == 200, quality.text
    file_id = "portal-demo.png"
    (tmp_path / file_id).write_bytes(content)
    monkeypatch.setattr("app.routes.settings.file_root", str(tmp_path))
    response = client.post(
        "/api/v1/vision-tasks",
        json={
            "file_id": file_id,
            "member_id": member_id,
            "quality_receipt": quality.json()["quality_receipt"],
        },
        headers={"X-Actor-Id": MEMBER, "X-Access-Purpose": "family-care"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], response.json()["input_digest"]


def _signed_payload(task_id: str, input_digest: str, body: dict) -> dict:
    settings = get_settings()
    receipt = issue_adapter_receipt(
        EvidencePipelineRequest(
            task_id=task_id,
            input_digest=input_digest,
            adapter_version="portal-adapter-v1",
            payload=body,
        ),
        secret=settings.adapter_signing_secret,
    )
    return {"receipt": receipt, "payload": body}


def test_member_capture_to_owner_confirm_then_member_timeline(
    client: TestClient,
    tmp_path,
    monkeypatch,
) -> None:
    """奶奶提交照片 → 管理员复核确认 → 奶奶时间线出现已确认事实。"""
    household_id, member_id, _member_actor = _setup(client)
    task_id, input_digest = _create_member_task(client, tmp_path, monkeypatch, member_id)
    _install_master_snapshot(tmp_path, monkeypatch)

    # 成员不能读取复核队列（含 OCR 原始候选）。
    member_review = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/review-tasks",
        headers={"X-Actor-Id": MEMBER, "X-Access-Purpose": "family-care"},
    )
    assert member_review.status_code == 404

    payload = _signed_payload(
        task_id,
        input_digest,
        {
            "ocr_tokens": [
                {
                    "id": "ocr-1",
                    "raw_value": "合成布洛芬缓释胶囊",
                    "confidence": 0.96,
                    "engine_version": "ocr-local-v1",
                }
            ],
            "field_proposals": [
                {
                    "field_name": "drug_name",
                    "raw_value": "合成布洛芬缓释胶囊",
                    "evidence_ids": ["ocr-1"],
                    "confidence": 0.95,
                    "parser_version": "rules-v1",
                }
            ],
            "master_data_version": "portal-master-v1",
        },
    )
    evidence = client.post(
        f"/api/v1/vision-tasks/{task_id}/evidence",
        json=payload,
        headers={"X-Actor-Id": OWNER},
    )
    assert evidence.status_code == 200, evidence.text

    reviews = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/review-tasks",
        headers={"X-Actor-Id": OWNER, "X-Access-Purpose": "family-care"},
    )
    assert reviews.status_code == 200, reviews.text
    review = reviews.json()[0]
    assert review["status"] == "PENDING_REVIEW"

    # 确认前：成员时间线不含未确认事实。
    before = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/timeline",
        headers={"X-Actor-Id": MEMBER, "X-Access-Purpose": "family-care"},
    )
    assert before.status_code == 200
    assert before.json() == []

    confirm = client.post(
        f"/api/v1/households/{household_id}/review-tasks/{review['id']}/confirm",
        headers={
            "X-Actor-Id": OWNER,
            "X-Access-Purpose": "family-care",
            "Idempotency-Key": f"portal-confirm-{task_id}",
        },
        json={
            "expected_version": review["version"],
            "selected_index": 0,
            "confirmation_note": "与药盒核对一致",
        },
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "CONFIRMED"

    after = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/timeline",
        headers={"X-Actor-Id": MEMBER, "X-Access-Purpose": "family-care"},
    )
    assert after.status_code == 200
    events = after.json()
    assert len(events) == 1
    assert events[0]["confirmation_status"] == "CONFIRMED"
    assert events[0]["evidence"].get("vision_task_id") == task_id

    # 成员可以读取自己的任务进度列表，但不能为他人查询。
    own_tasks = client.get(
        f"/api/v1/households/{household_id}/vision-tasks",
        params={"member_id": member_id},
        headers={"X-Actor-Id": MEMBER, "X-Access-Purpose": "family-care"},
    )
    assert own_tasks.status_code == 200
    assert any(item["id"] == task_id for item in own_tasks.json())

    denied_event = client.post(
        f"/api/v1/households/{household_id}/events",
        headers={"X-Actor-Id": MEMBER, "X-Access-Purpose": "family-care"},
        json={
            "member_id": member_id,
            "event_type": "medication_added",
            "source": "MANUAL",
            "confirmation_status": "CONFIRMED",
            "payload": {"drug": "不应写入"},
            "evidence": {},
        },
    )
    assert denied_event.status_code == 404


def test_member_cannot_confirm_review_task(client: TestClient, tmp_path, monkeypatch) -> None:
    household_id, member_id, _ = _setup(client)
    task_id, input_digest = _create_member_task(client, tmp_path, monkeypatch, member_id)
    _install_master_snapshot(tmp_path, monkeypatch)
    payload = _signed_payload(
        task_id,
        input_digest,
        {
            "ocr_tokens": [],
            "field_proposals": [],
            "master_data_version": "portal-master-v1",
        },
    )
    client.post(
        f"/api/v1/vision-tasks/{task_id}/evidence",
        json=payload,
        headers={"X-Actor-Id": OWNER},
    )
    reviews = client.get(
        f"/api/v1/households/{household_id}/members/{member_id}/review-tasks",
        headers={"X-Actor-Id": OWNER},
    ).json()
    review_id = reviews[0]["id"]
    denied = client.post(
        f"/api/v1/households/{household_id}/review-tasks/{review_id}/confirm",
        headers={
            "X-Actor-Id": MEMBER,
            "X-Access-Purpose": "family-care",
            "Idempotency-Key": f"member-confirm-{review_id}",
        },
        json={
            "expected_version": reviews[0]["version"],
            "selected_index": 0,
        },
    )
    assert denied.status_code == 404
