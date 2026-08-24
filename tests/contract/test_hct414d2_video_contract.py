"""HCT-414-D2: server-side video task contract (quality cap, capability, merge).

Synthetic videos only — never real medicine footage.  Digest semantics are
full-file sha256 on both the quality receipt and task creation, so fixture
size is unconstrained (HCT-414-D2 fixed the former first-8-KiB mismatch).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import cv2
import numpy as np
from ai.vision.evidence_pipeline import (
    BarcodeCandidate,
    EvidencePipelineRequest,
    FieldProposal,
    OCRToken,
    issue_adapter_receipt,
)
from ai.vision.video_frames import merge_frame_requests

from app.config import get_settings
from app.review import get_review_task_by_vision_task


def _demo_frame(index: int) -> np.ndarray:
    image = np.full((480, 640, 3), 110, dtype=np.uint8)
    cv2.rectangle(image, (140, 90), (500, 390), (225, 225, 225), -1)
    cv2.rectangle(image, (140, 90), (500, 390), (20, 20, 20), 6)
    cv2.putText(
        image,
        f"DEMO{index:02d}",
        (220, 245),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.5,
        (20, 20, 20),
        4,
    )
    return image


def _encode_demo_video(frame_count: int, *, fps: int = 1) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
        video_path = Path(handle.name)
    writer = cv2.VideoWriter(
        str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (640, 480)
    )
    assert writer.isOpened(), "mp4 codec unavailable in this OpenCV runtime"
    for index in range(frame_count):
        writer.write(_demo_frame(index))
    writer.release()
    content = video_path.read_bytes()
    video_path.unlink(missing_ok=True)
    # Digest semantics are full-file sha256 on both the quality receipt and
    # the task-creation side, so fixture size is unconstrained.
    return content


def _check_video_quality(client, content: bytes, actor_id: str = "video-owner"):
    return client.post(
        "/api/v1/vision-quality/check",
        files={"file": ("demo.mp4", content, "video/mp4")},
        data={"media_type": "video"},
        headers={"X-Actor-ID": actor_id},
    )


def test_capabilities_declares_video_task_ability(client) -> None:
    body = client.get("/api/v1/meta/capabilities").json()
    assert "vision-task-video" in body["available"]
    assert "vision-task-video" not in body["unavailable"]


def test_video_capability_can_be_disabled_for_fail_closed_clients(
    client, monkeypatch
) -> None:
    monkeypatch.setattr("app.routes.settings.vision_video_tasks_enabled", False)
    body = client.get("/api/v1/meta/capabilities").json()
    assert "vision-task-video" in body["unavailable"]
    assert "vision-task-video" not in body["available"]


def test_video_quality_check_passes_short_synthetic_video(client) -> None:
    response = _check_video_quality(client, _encode_demo_video(3))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["media_type"] == "video"
    assert body["decision"] == "PASS"
    assert body["frames"], "frame-level summary missing"
    assert body["quality_receipt"]


def test_video_quality_check_rejects_duration_over_limit(client) -> None:
    # 31 frames at 1 fps = 31 s, one second past the default 30 s cap.
    response = _check_video_quality(client, _encode_demo_video(31))
    assert response.status_code == 422
    assert response.json() == {"detail": "VIDEO_DURATION_EXCEEDED"}


def _create_video_task(client, tmp_path, monkeypatch) -> tuple[str, str]:
    actor_id = "video-owner"
    household = client.post(
        "/api/v1/households",
        json={"name": "Video household"},
        headers={"X-Actor-ID": actor_id},
    )
    assert household.status_code == 201
    member = client.post(
        f"/api/v1/households/{household.json()['id']}/members",
        json={"display_name": "Video member"},
        headers={"X-Actor-ID": actor_id},
    )
    assert member.status_code == 201

    content = _encode_demo_video(3)
    quality = _check_video_quality(client, content, actor_id)
    assert quality.status_code == 200, quality.text
    assert quality.json()["quality_receipt"]

    file_id = "video-demo.mp4"
    (tmp_path / file_id).write_bytes(content)
    monkeypatch.setattr("app.routes.settings.file_root", str(tmp_path))
    response = client.post(
        "/api/v1/vision-tasks",
        json={
            "file_id": file_id,
            "media_type": "video",
            "member_id": member.json()["id"],
            "quality_receipt": quality.json()["quality_receipt"],
            "idempotency_key": "hct414d2-video-once",
        },
        headers={"X-Actor-ID": actor_id},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["id"], body["input_digest"]


def test_video_task_worker_merge_succeeds_and_bridges_review(
    client, tmp_path, monkeypatch, db_session
) -> None:
    """The merged multi-frame evidence must behave exactly like image evidence."""
    task_id, input_digest = _create_video_task(client, tmp_path, monkeypatch)

    def frame_request(position: int) -> EvidencePipelineRequest:
        return EvidencePipelineRequest(
            ocr_tokens=[
                OCRToken(
                    id="ocr-1",
                    raw_value=f"Demo Medicine {position}",
                    confidence=0.9,
                    engine_version="ocr-local-v1",
                )
            ],
            barcodes=[
                BarcodeCandidate(
                    id="code-1",
                    raw_value="6900000000001",
                    confidence=0.5 + 0.1 * position,
                    format="EAN-13",
                    decoder_version="cv2-v1",
                    decode_valid=True,
                )
            ],
            field_proposals=[
                FieldProposal(
                    field_name="drug_name",
                    raw_value=f"Demo Medicine {position}",
                    evidence_ids=["ocr-1"],
                    confidence=0.8,
                    parser_version="rule-v1",
                    source="rule",
                )
            ],
            ocr_engine_version="ocr-local-v1",
            barcode_decoder_version="cv2-v1",
            adapter_version="worker-video-test",
        )

    merged = merge_frame_requests(
        [frame_request(1), frame_request(2)],
        run_id="worker-test-video",
    )
    assert [token.id for token in merged.ocr_tokens] == ["f1-ocr-1", "f2-ocr-1"]
    assert len(merged.barcodes) == 1, "duplicate EAN across frames must deduplicate"
    assert merged.barcodes[0].confidence == 0.7
    assert merged.field_proposals[0].evidence_ids == ["f1-ocr-1"]

    receipt = issue_adapter_receipt(
        task_id,
        input_digest,
        merged,
        get_settings().vision_adapter_signing_key,
    )
    payload = json.loads(merged.model_dump_json())
    payload["adapter_receipt"] = receipt

    evidence = client.post(
        f"/api/v1/vision-tasks/{task_id}/evidence",
        json=payload,
        headers={"X-Actor-ID": "video-owner"},
    )
    assert evidence.status_code == 200, evidence.text

    task = client.get(
        f"/api/v1/vision-tasks/{task_id}",
        headers={"X-Actor-ID": "video-owner"},
    ).json()
    assert task["status"] == "succeeded"
    assert task["result"]

    review = get_review_task_by_vision_task(db_session, task_id)
    assert review is not None, "video evidence must bridge to human review"
