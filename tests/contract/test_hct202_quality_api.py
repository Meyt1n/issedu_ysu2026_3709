from __future__ import annotations

import hashlib

import cv2
import numpy as np
from ai.vision.quality_receipt import issue_quality_receipt

from app.config import get_settings


def _encode_demo_image(*, dark: bool = False) -> bytes:
    if dark:
        image = np.full((480, 640, 3), 5, dtype=np.uint8)
    else:
        image = np.full((480, 640, 3), 110, dtype=np.uint8)
        cv2.rectangle(image, (140, 90), (500, 390), (225, 225, 225), -1)
        cv2.rectangle(image, (140, 90), (500, 390), (20, 20, 20), 6)
        cv2.putText(
            image,
            "DEMO",
            (220, 245),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.5,
            (20, 20, 20),
            4,
        )
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def _check_quality(client, content: bytes, actor_id: str = "demo-owner"):
    return client.post(
        "/api/v1/vision-quality/check",
        files={"file": ("demo.png", content, "image/png")},
        data={"media_type": "image"},
        headers={"X-Actor-ID": actor_id},
    )


def _create_member(client, actor_id: str) -> str:
    household = client.post(
        "/api/v1/households",
        json={"name": f"{actor_id} household"},
        headers={"X-Actor-ID": actor_id},
    )
    assert household.status_code == 201
    member = client.post(
        f"/api/v1/households/{household.json()['id']}/members",
        json={"display_name": f"{actor_id} member"},
        headers={"X-Actor-ID": actor_id},
    )
    assert member.status_code == 201
    return member.json()["id"]


def _tamper_receipt(receipt: str) -> str:
    encoded, signature = receipt.split(".", maxsplit=1)
    replacement = "A" if signature[0] != "A" else "B"
    return f"{encoded}.{replacement}{signature[1:]}"


def test_quality_api_returns_versioned_local_result_and_receipt(client) -> None:
    response = _check_quality(client, _encode_demo_image())

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "vision-quality-result-v1"
    assert body["decision"] == "PASS"
    assert body["allow_downstream"] is True
    assert body["source"]["source_id"].startswith("upload:")
    assert body["source"]["digest_scope"] == "uploaded_file_bytes"
    assert body["source"]["unchanged"] is True
    assert body["quality_receipt"]
    assert "path" not in str(body).lower()
    assert "demo.png" not in str(body)


def test_quality_api_retake_has_no_receipt(client) -> None:
    response = _check_quality(client, _encode_demo_image(dark=True))

    assert response.status_code == 200
    assert response.json()["decision"] == "RETAKE"
    assert response.json()["allow_downstream"] is False
    assert response.json()["quality_receipt"] is None


def test_quality_api_persists_creator_scoped_provenance(client) -> None:
    response = _check_quality(client, _encode_demo_image(), actor_id="record-owner")

    assert response.status_code == 200
    body = response.json()
    record_id = body["quality_record_id"]
    assert record_id

    record = client.get(
        f"/api/v1/vision-quality/records/{record_id}",
        headers={"X-Actor-ID": "record-owner"},
    )

    assert record.status_code == 200
    record_body = record.json()
    assert record_body["id"] == record_id
    assert record_body["actor_id"] == "record-owner"
    assert record_body["input_digest"] == body["source"]["sha256"]
    assert record_body["media_type"] == "image"
    assert record_body["decision"] == "PASS"
    assert record_body["allow_downstream"] is True
    assert "quality_receipt" not in record_body
    assert "source" not in record_body
    assert "path" not in str(record_body).lower()


def test_quality_api_persists_retake_without_receipt(client) -> None:
    response = _check_quality(client, _encode_demo_image(dark=True), actor_id="retake-owner")

    assert response.status_code == 200
    body = response.json()
    record = client.get(
        f"/api/v1/vision-quality/records/{body['quality_record_id']}",
        headers={"X-Actor-ID": "retake-owner"},
    )

    assert record.status_code == 200
    record_body = record.json()
    assert record_body["decision"] == "RETAKE"
    assert record_body["allow_downstream"] is False
    assert "quality_receipt" not in record_body


def test_quality_api_record_cannot_be_read_by_another_actor(client) -> None:
    response = _check_quality(client, _encode_demo_image(), actor_id="record-owner")
    record_id = response.json()["quality_record_id"]

    forbidden = client.get(
        f"/api/v1/vision-quality/records/{record_id}",
        headers={"X-Actor-ID": "different-owner"},
    )

    assert forbidden.status_code == 404
    assert forbidden.json() == {"detail": "VISION_QUALITY_RECORD_NOT_FOUND"}


def test_quality_api_advisory_demo_mode_allows_diagnostic_retake(client, monkeypatch) -> None:
    monkeypatch.setattr("app.routes.settings.vision_quality_enforce_retake", False)

    response = _check_quality(client, _encode_demo_image(dark=True))

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "PASS"
    assert body["allow_downstream"] is True
    assert body["quality_receipt"]
    assert "TOO_DARK" in body["reasons"]
    assert "quality enforcement disabled" in body["limitations"][-1]


def test_quality_api_rejects_corrupt_image_without_leaking_path(client) -> None:
    response = client.post(
        "/api/v1/vision-quality/check",
        files={"file": ("corrupt.png", b"\x89PNG\r\n\x1a\ncorrupt", "image/png")},
        data={"media_type": "image"},
        headers={"X-Actor-ID": "demo-owner"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "IMAGE_DECODE_FAILED"}
    assert "temp" not in response.text.lower()


def test_quality_api_rejects_media_extension_mismatch(client) -> None:
    response = client.post(
        "/api/v1/vision-quality/check",
        files={"file": ("demo.png", _encode_demo_image(), "image/png")},
        data={"media_type": "video"},
        headers={"X-Actor-ID": "demo-owner"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "MEDIA_EXTENSION_MISMATCH"}


def test_quality_api_rejects_multipart_content_type_mismatch(client) -> None:
    response = client.post(
        "/api/v1/vision-quality/check",
        files={"file": ("demo.png", _encode_demo_image(), "video/mp4")},
        data={"media_type": "image"},
        headers={"X-Actor-ID": "demo-owner"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "MEDIA_CONTENT_TYPE_MISMATCH"}


def test_vision_task_requires_matching_actor_and_file_receipt(
    client, tmp_path, monkeypatch
) -> None:
    household = client.post(
        "/api/v1/households",
        json={"name": "Quality household"},
        headers={"X-Actor-ID": "owner-a"},
    )
    assert household.status_code == 201
    member = client.post(
        f"/api/v1/households/{household.json()['id']}/members",
        json={"display_name": "Quality member"},
        headers={"X-Actor-ID": "owner-a"},
    )
    assert member.status_code == 201
    other_member_id = _create_member(client, "owner-b")
    content = _encode_demo_image()
    quality = _check_quality(client, content, actor_id="owner-a")
    assert quality.status_code == 200
    receipt = quality.json()["quality_receipt"]
    file_id = "stored.png"
    (tmp_path / file_id).write_bytes(content)
    monkeypatch.setattr("app.routes.settings.file_root", str(tmp_path))

    missing_receipt = client.post(
        "/api/v1/vision-tasks",
        json={"file_id": file_id, "member_id": member.json()["id"]},
        headers={"X-Actor-ID": "owner-a"},
    )
    wrong_actor = client.post(
        "/api/v1/vision-tasks",
        json={
            "file_id": file_id,
            "member_id": other_member_id,
            "quality_receipt": receipt,
        },
        headers={"X-Actor-ID": "owner-b"},
    )
    accepted = client.post(
        "/api/v1/vision-tasks",
        json={
            "file_id": file_id,
            "member_id": member.json()["id"],
            "quality_receipt": receipt,
        },
        headers={"X-Actor-ID": "owner-a"},
    )

    assert missing_receipt.status_code == 409
    assert missing_receipt.json() == {"detail": "QUALITY_GATE_REQUIRED"}
    assert wrong_actor.status_code == 409
    assert wrong_actor.json() == {"detail": "QUALITY_RECEIPT_MISMATCH"}
    assert accepted.status_code == 201
    assert accepted.json()["input_digest"] == quality.json()["source"]["sha256"]
    assert accepted.json()["preprocess_version"] == "opencv-quality-demo-v2-lenient-exposure"


def test_vision_task_rejects_cross_household_member(
    client, tmp_path, monkeypatch
) -> None:
    household = client.post(
        "/api/v1/households",
        json={"name": "Private household"},
        headers={"X-Actor-ID": "member-owner"},
    )
    member = client.post(
        f"/api/v1/households/{household.json()['id']}/members",
        json={"display_name": "Private member"},
        headers={"X-Actor-ID": "member-owner"},
    )
    assert member.status_code == 201

    content = _encode_demo_image()
    quality = _check_quality(client, content, actor_id="other-actor")
    assert quality.status_code == 200
    file_id = "cross-household.png"
    (tmp_path / file_id).write_bytes(content)
    monkeypatch.setattr("app.routes.settings.file_root", str(tmp_path))

    response = client.post(
        "/api/v1/vision-tasks",
        json={
            "file_id": file_id,
            "member_id": member.json()["id"],
            "quality_receipt": quality.json()["quality_receipt"],
        },
        headers={"X-Actor-ID": "other-actor"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "RESOURCE_NOT_FOUND"}


def test_vision_task_rejects_tampered_or_different_file_receipt(
    client, tmp_path, monkeypatch
) -> None:
    member_id = _create_member(client, "demo-owner")
    content = _encode_demo_image()
    quality = _check_quality(client, content)
    receipt = quality.json()["quality_receipt"]
    file_id = "different.png"
    (tmp_path / file_id).write_bytes(_encode_demo_image(dark=True))
    monkeypatch.setattr("app.routes.settings.file_root", str(tmp_path))

    different_file = client.post(
        "/api/v1/vision-tasks",
        json={
            "file_id": file_id,
            "member_id": member_id,
            "quality_receipt": receipt,
        },
        headers={"X-Actor-ID": "demo-owner"},
    )
    tampered = client.post(
        "/api/v1/vision-tasks",
        json={
            "file_id": file_id,
            "member_id": member_id,
            "quality_receipt": _tamper_receipt(receipt),
        },
        headers={"X-Actor-ID": "demo-owner"},
    )

    assert different_file.status_code == 409
    assert different_file.json() == {"detail": "QUALITY_RECEIPT_MISMATCH"}
    assert tampered.status_code == 409
    assert tampered.json() == {"detail": "QUALITY_RECEIPT_INVALID"}


def test_vision_task_rejects_malformed_receipt_as_controlled_conflict(
    client, tmp_path, monkeypatch
) -> None:
    member_id = _create_member(client, "demo-owner")
    file_id = "stored.png"
    (tmp_path / file_id).write_bytes(_encode_demo_image())
    monkeypatch.setattr("app.routes.settings.file_root", str(tmp_path))

    response = client.post(
        "/api/v1/vision-tasks",
        json={
            "file_id": file_id,
            "member_id": member_id,
            "quality_receipt": "x" * 32,
        },
        headers={"X-Actor-ID": "demo-owner"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "QUALITY_RECEIPT_INVALID"}


def test_vision_task_binds_media_type_to_file_and_receipt(
    client, tmp_path, monkeypatch
) -> None:
    member_id = _create_member(client, "video-owner")
    content = b"synthetic video container bytes"
    file_id = "stored.mp4"
    (tmp_path / file_id).write_bytes(content)
    monkeypatch.setattr("app.routes.settings.file_root", str(tmp_path))
    digest = hashlib.sha256(content).hexdigest()
    receipt = issue_quality_receipt(
        actor_id="video-owner",
        input_digest=digest,
        config_version=get_settings().vision_quality_config_version,
        media_type="video",
    )

    accepted = client.post(
        "/api/v1/vision-tasks",
        json={
            "file_id": file_id,
            "media_type": "video",
            "member_id": member_id,
            "quality_receipt": receipt,
        },
        headers={"X-Actor-ID": "video-owner"},
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["media_type"] == "video"

    mismatch = client.post(
        "/api/v1/vision-tasks",
        json={
            "file_id": file_id,
            "media_type": "image",
            "member_id": member_id,
            "quality_receipt": receipt,
        },
        headers={"X-Actor-ID": "video-owner"},
    )
    assert mismatch.status_code == 409
    assert mismatch.json() == {"detail": "MEDIA_TYPE_MISMATCH"}
