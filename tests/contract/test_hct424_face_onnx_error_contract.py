"""HCT-424/HCT-425 contract: OpenCV ONNX failures never leak as raw HTTP 500.

Before this fix a ``cv2.error`` raised while loading the YuNet/SFace ONNX
weights (typical on Windows when the repository path contains Chinese
characters, e.g. ``C:\\...\\多模态医疗\\...``) escaped the face routes'
RuntimeError/ValueError handlers, hit the generic exception handler and
returned HTTP 500 whose detail contained the full C++ message *including the
local Windows path* — which the web client rendered verbatim in the toast.

Contract: face registration answers 503 ``FACE_DETECTOR_UNAVAILABLE`` and both
face logins answer 503 ``FACE_AUTH_UNAVAILABLE``; no response body ever
carries the OpenCV C++ text or a local filesystem path, and no data changes.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import routes

_WINDOWS_STYLE_CV2_ERROR = (
    "OpenCV(4.14.0) D:\\a\\opencv-python\\opencv-python\\opencv\\modules\\dnn"
    "\\src\\onnx\\onnx_importer.cpp:277: error: (-5:Bad argument) Can't read "
    "ONNX file: C:\\Users\\demo\\多模态医疗\\issedu_ysu2026_3709\\models\\face"
    "\\face_recognition_sface_2021dec.onnx in function "
    "'cv::dnn::dnn4_v20260709::ONNXImporter::ONNXImporter'"
)

_TEMPLATE = b"\x00\x00\x80\x3f" * 128
_TEMPLATE_METADATA = {
    "algorithm_version": "opencv-yunet-sface-v3",
    "feature_version": "face-embedding-sface-v3",
}


def _webcam_selfie_jpeg(width: int = 960, height: int = 540, *, seed: int = 7) -> bytes:
    """Guided-capture style frame that passes the real face frame gate."""
    rng = np.random.default_rng(seed)
    frame = np.full((height, width, 3), 160.0, dtype=np.float32)
    frame += rng.normal(0.0, 2.0, frame.shape).astype(np.float32)
    center_x, center_y = width // 2, int(height * 0.45)
    short = min(width, height)
    cv2.ellipse(
        frame,
        (center_x, height),
        (int(width * 0.30), int(height * 0.45)),
        0, 180, 360, (70, 60, 55), -1,
    )
    axes = (int(short * 0.20), int(short * 0.28))
    cv2.ellipse(frame, (center_x, center_y), axes, 0, 0, 360, (150, 170, 205), -1)
    eye_y = center_y - axes[1] // 5
    for dx in (-axes[0] // 2, axes[0] // 2):
        cv2.circle(frame, (center_x + dx, eye_y), 6, (30, 30, 30), -1)
    cv2.ellipse(frame, (center_x, center_y + axes[1] // 2), (20, 8), 0, 0, 180, (80, 80, 140), 2)
    ok, encoded = cv2.imencode(
        ".jpg",
        np.clip(frame, 0, 255).astype(np.uint8),
        [cv2.IMWRITE_JPEG_QUALITY, 90],
    )
    assert ok
    return encoded.tobytes()


def _webcam_frames(prefix: str, count: int = 3) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [
        (
            "frames",
            (f"{prefix}-{index}.jpg", _webcam_selfie_jpeg(seed=index), "image/jpeg"),
        )
        for index in range(1, count + 1)
    ]


def _owner_with_household(
    client: TestClient,
    owner: str,
    password: str,
    household_name: str,
) -> tuple[str, str]:
    client.post("/api/v1/auth/register", json={"actor_id": owner, "password": password})
    owner_token = client.post(
        "/api/v1/auth/login",
        json={"actor_id": owner, "password": password},
    ).json()["session_token"]
    household = client.post(
        "/api/v1/households",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": household_name},
    ).json()["id"]
    return owner_token, household


def _raise_windows_style_cv2_error(_data: bytes, **_kwargs) -> tuple[bytes, dict]:
    raise cv2.error(_WINDOWS_STYLE_CV2_ERROR)


def _assert_no_local_path_leak(response) -> None:
    assert "多模态医疗" not in response.text
    assert "ONNX" not in response.text
    assert "C:\\\\" not in response.text and "C:\\" not in response.text
    assert "onnx_importer" not in response.text


def test_face_registration_maps_onnx_load_failure_to_503_without_path_leak(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = "hct424-onnx-owner"
    password = "hct424-onnx-owner-pass"
    owner_token, household = _owner_with_household(client, owner, password, "中文路径注册")

    monkeypatch.setattr(routes, "extract_face_template", _raise_windows_style_cv2_error)

    response = client.post(
        f"/api/v1/households/{household}/face-credentials",
        headers={"Authorization": f"Bearer {owner_token}"},
        data={
            "consent": "true",
            "confirmation_method": "password",
            "confirmation_code": password,
        },
        files=_webcam_frames("onnx-error-frame"),
    )

    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "FACE_DETECTOR_UNAVAILABLE"
    _assert_no_local_path_leak(response)

    # 「本次没有改变任何数据」 must be true: no credential was stored.
    listed = client.get(
        f"/api/v1/households/{household}/face-credentials",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert listed.status_code == 200
    assert listed.json() == []


def test_face_login_maps_onnx_failure_to_503_without_path_leak(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = "hct425-onnx-owner"
    password = "hct425-onnx-owner-pass"
    owner_token, household = _owner_with_household(client, owner, password, "中文路径登录")
    member = client.post(
        f"/api/v1/households/{household}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"display_name": "奶奶", "actor_id": "hct425-onnx-grandma"},
    ).json()

    # Register with a healthy (mocked) pipeline first.
    monkeypatch.setattr(
        routes,
        "extract_face_template",
        lambda _data, **_kwargs: (_TEMPLATE, dict(_TEMPLATE_METADATA)),
    )
    monkeypatch.setattr(routes, "check_face_liveness", lambda *_args, **_kwargs: None)
    files = _webcam_frames("onnx-login-frame")
    registered = client.post(
        f"/api/v1/households/{household}/face-credentials",
        headers={"Authorization": f"Bearer {owner_token}"},
        data={
            "consent": "true",
            "target_actor_id": member["actor_id"],
            "confirmation_method": "password",
            "confirmation_code": password,
        },
        files=files,
    )
    assert registered.status_code == 201, registered.text

    # Then the ONNX model fails to load at login time (Windows Unicode path).
    monkeypatch.setattr(routes, "extract_face_template", _raise_windows_style_cv2_error)

    challenge = client.post(
        "/api/v1/auth/face-challenge",
        json={"household_id": household, "actor_id": member["actor_id"]},
    )
    response = client.post(
        "/api/v1/auth/face-login",
        data={
            "household_id": household,
            "actor_id": member["actor_id"],
            "challenge_id": challenge.json()["challenge_id"],
        },
        files=files,
    )

    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "FACE_AUTH_UNAVAILABLE"
    _assert_no_local_path_leak(response)


def test_family_face_login_maps_onnx_failure_to_503_without_path_leak(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = "hct425-onnx-family-owner"
    password = "hct425-onnx-family-owner-pass"
    owner_token, household = _owner_with_household(client, owner, password, "中文路径家庭登录")
    member = client.post(
        f"/api/v1/households/{household}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"display_name": "爷爷", "actor_id": "hct425-onnx-grandpa"},
    ).json()

    monkeypatch.setattr(
        routes,
        "extract_face_template",
        lambda _data, **_kwargs: (_TEMPLATE, dict(_TEMPLATE_METADATA)),
    )
    monkeypatch.setattr(routes, "check_face_liveness", lambda *_args, **_kwargs: None)
    files = _webcam_frames("onnx-family-frame")
    registered = client.post(
        f"/api/v1/households/{household}/face-credentials",
        headers={"Authorization": f"Bearer {owner_token}"},
        data={
            "consent": "true",
            "target_actor_id": member["actor_id"],
            "confirmation_method": "password",
            "confirmation_code": password,
        },
        files=files,
    )
    assert registered.status_code == 201, registered.text

    monkeypatch.setattr(routes, "extract_face_template", _raise_windows_style_cv2_error)

    challenge = client.post(
        "/api/v1/auth/family-face-challenge",
        json={"household_id": household},
    )
    response = client.post(
        "/api/v1/auth/family-face-login",
        data={
            "household_id": household,
            "challenge_id": challenge.json()["challenge_id"],
        },
        files=files,
    )

    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "FACE_AUTH_UNAVAILABLE"
    _assert_no_local_path_leak(response)
