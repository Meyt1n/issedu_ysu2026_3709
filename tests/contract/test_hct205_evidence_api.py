from __future__ import annotations

import hashlib
import json

import cv2
import numpy as np
from ai.vision.evidence_pipeline import EvidencePipelineRequest, issue_adapter_receipt

from app.config import get_settings


def _encode_demo_image() -> bytes:
    image = np.full((480, 640, 3), 110, dtype=np.uint8)
    cv2.rectangle(image, (140, 90), (500, 390), (225, 225, 225), -1)
    cv2.rectangle(image, (140, 90), (500, 390), (20, 20, 20), 6)
    cv2.putText(image, "DEMO", (220, 245), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (20, 20, 20), 4)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def _create_task(
    client, tmp_path, monkeypatch, *, actor_id: str = "evidence-owner"
) -> tuple[str, str]:
    household = client.post(
        "/api/v1/households",
        json={"name": "Evidence household"},
        headers={"X-Actor-ID": actor_id},
    )
    assert household.status_code == 201
    member = client.post(
        f"/api/v1/households/{household.json()['id']}/members",
        json={"display_name": "Evidence member"},
        headers={"X-Actor-ID": actor_id},
    )
    assert member.status_code == 201
    content = _encode_demo_image()
    quality = client.post(
        "/api/v1/vision-quality/check",
        files={"file": ("demo.png", content, "image/png")},
        data={"media_type": "image"},
        headers={"X-Actor-ID": actor_id},
    )
    assert quality.status_code == 200
    assert quality.json()["quality_receipt"]
    file_id = "evidence-demo.png"
    (tmp_path / file_id).write_bytes(content)
    monkeypatch.setattr("app.routes.settings.file_root", str(tmp_path))
    response = client.post(
        "/api/v1/vision-tasks",
        json={
            "file_id": file_id,
            "member_id": member.json()["id"],
            "quality_receipt": quality.json()["quality_receipt"],
        },
        headers={"X-Actor-ID": actor_id},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["id"], body["input_digest"]


def _signed_payload(task_id: str, input_digest: str, payload: dict) -> dict:
    request = EvidencePipelineRequest.model_validate(payload)
    receipt = issue_adapter_receipt(
        task_id,
        input_digest,
        request,
        get_settings().vision_adapter_signing_key,
    )
    return {**payload, "adapter_receipt": receipt}


def test_evidence_api_stores_versioned_safe_result(client, tmp_path, monkeypatch) -> None:
    task_id, input_digest = _create_task(client, tmp_path, monkeypatch)
    payload = _signed_payload(
        task_id,
        input_digest,
        {
            "ocr_tokens": [
                {
                    "id": "ocr-1",
                    "raw_value": "Demo Medicine",
                    "confidence": 0.9,
                    "engine_version": "ocr-local-v1",
                }
            ],
            "field_proposals": [
                {
                    "field_name": "drug_name",
                    "raw_value": "Demo Medicine",
                    "evidence_ids": ["ocr-1"],
                    "confidence": 0.85,
                    "parser_version": "rules-v1",
                }
            ],
            "vision_model_version": "yolo11n-experimental-v1.3",
        },
    )
    response = client.post(
        f"/api/v1/vision-tasks/{task_id}/evidence",
        json=payload,
        headers={"X-Actor-ID": "evidence-owner"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "ocr-first-evidence-v1"
    assert body["fusion_readiness"] == "UNKNOWN"
    assert body["requires_human_confirmation"] is True
    assert body["fields"][0]["confirmation_status"] == "UNCONFIRMED"
    assert "MATCHED" not in response.text

    stored = client.get(
        f"/api/v1/vision-tasks/{task_id}",
        headers={"X-Actor-ID": "evidence-owner"},
    )
    assert stored.status_code == 200
    assert stored.json()["status"] == "succeeded"
    assert stored.json()["result"]["schema_version"] == "ocr-first-evidence-v1"


def test_evidence_api_requires_task_owner(client, tmp_path, monkeypatch) -> None:
    task_id, _ = _create_task(client, tmp_path, monkeypatch, actor_id="owner-a")

    response = client.post(
        f"/api/v1/vision-tasks/{task_id}/evidence",
        json={"barcodes": []},
        headers={"X-Actor-ID": "owner-b"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "VISION_TASK_NOT_FOUND"}


def test_evidence_api_rejects_missing_adapter_receipt(client, tmp_path, monkeypatch) -> None:
    task_id, _ = _create_task(client, tmp_path, monkeypatch)

    response = client.post(
        f"/api/v1/vision-tasks/{task_id}/evidence",
        json={"ocr_tokens": []},
        headers={"X-Actor-ID": "evidence-owner"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "ADAPTER_RECEIPT_REQUIRED"}


def test_evidence_api_rejects_tampered_adapter_receipt(client, tmp_path, monkeypatch) -> None:
    task_id, input_digest = _create_task(client, tmp_path, monkeypatch)
    payload = _signed_payload(task_id, input_digest, {"ocr_tokens": []})
    payload["adapter_run_id"] = "tampered-after-signing"

    response = client.post(
        f"/api/v1/vision-tasks/{task_id}/evidence",
        json=payload,
        headers={"X-Actor-ID": "evidence-owner"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "ADAPTER_RECEIPT_INVALID"}


def test_evidence_api_keeps_invalid_barcode_as_review_finding(
    client, tmp_path, monkeypatch
) -> None:
    task_id, input_digest = _create_task(client, tmp_path, monkeypatch)
    payload = _signed_payload(
        task_id,
        input_digest,
        {
            "barcodes": [
                {
                    "id": "barcode-bad",
                    "raw_value": "4006381333932",
                    "format": "EAN-13",
                    "confidence": 0.95,
                    "decoder_version": "decoder-v1",
                }
            ]
        },
    )

    response = client.post(
        f"/api/v1/vision-tasks/{task_id}/evidence",
        json=payload,
        headers={"X-Actor-ID": "evidence-owner"},
    )

    assert response.status_code == 200
    assert response.json()["barcodes"][0]["validation_status"] == "INVALID_CHECKSUM"
    assert any(
        finding["code"] == "BARCODE_INVALID_CHECKSUM" for finding in response.json()["findings"]
    )


def test_evidence_api_loads_requested_local_master_snapshot(client, tmp_path, monkeypatch) -> None:
    task_id, input_digest = _create_task(client, tmp_path, monkeypatch)
    monkeypatch.setattr("app.routes.settings.master_data_approved_versions", "demo-master-v1")
    snapshot = {
        "schema_version": "hct-master-data/v1",
        "version": "demo-master-v1",
        "approval_status": "APPROVED",
        "approval_ref": "test-approval",
        "revocation_status": "ACTIVE",
        "records": [
            {
                "record_id": "demo-record-1",
                "product_barcode": "4006381333931",
                "name_aliases": ["Demo Medicine"],
            }
        ],
    }
    canonical = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    snapshot["sha256"] = hashlib.sha256(canonical).hexdigest()
    (tmp_path / "demo-master-v1.json").write_text(
        json.dumps(snapshot, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.routes.settings.master_data_root", str(tmp_path))

    payload = _signed_payload(
        task_id,
        input_digest,
        {
            "ocr_tokens": [
                {
                    "id": "ocr-1",
                    "raw_value": "Demo Medicine",
                    "confidence": 0.9,
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
                    "raw_value": "Demo Medicine",
                    "evidence_ids": ["ocr-1"],
                    "confidence": 0.85,
                    "parser_version": "rules-v1",
                }
            ],
            "master_data_version": "demo-master-v1",
        },
    )
    response = client.post(
        f"/api/v1/vision-tasks/{task_id}/evidence",
        json=payload,
        headers={"X-Actor-ID": "evidence-owner"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["master_candidates"] == [
        {"record_id": "demo-record-1", "reasons": ["BARCODE_EXACT", "NAME_EXACT"]}
    ]
    assert body["versions"]["master_data_version"] == "demo-master-v1"
    assert "MASTER_DATA_UNAVAILABLE" not in {finding["code"] for finding in body["findings"]}


def test_fusion_api_returns_versioned_safe_four_state_result(client, tmp_path, monkeypatch) -> None:
    task_id, input_digest = _create_task(client, tmp_path, monkeypatch)
    payload = _signed_payload(
        task_id,
        input_digest,
        {
            "ocr_tokens": [
                {
                    "id": "ocr-1",
                    "raw_value": "Demo Medicine",
                    "confidence": 0.9,
                    "engine_version": "ocr-local-v1",
                }
            ],
            "field_proposals": [
                {
                    "field_name": "drug_name",
                    "raw_value": "Demo Medicine",
                    "evidence_ids": ["ocr-1"],
                    "confidence": 0.85,
                    "parser_version": "rules-v1",
                }
            ],
        },
    )
    evidence = client.post(
        f"/api/v1/vision-tasks/{task_id}/evidence",
        json=payload,
        headers={"X-Actor-ID": "evidence-owner"},
    )
    assert evidence.status_code == 200

    response = client.post(
        f"/api/v1/vision-tasks/{task_id}/fusion",
        json={},
        headers={"X-Actor-ID": "evidence-owner"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "candidate-fusion-v1"
    assert body["status"] in {"UNKNOWN", "REVIEW", "CONFLICT", "MATCHED"}
    assert body["requires_human_confirmation"] is True
    assert body["health_event_allowed"] is False
    assert "fusion_rule_version" in body["versions"]
    assert body["review_task_id"]
    assert body["review_task_version"] == 1
