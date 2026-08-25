"""HCT-424/HCT-425 regression: heavy face work must run off the event loop.

Root cause of the false 「本地 API 不可用」 during guided face registration:
``register_face_credential`` (and both face-login routes) executed OpenCV
decode, YuNet/SFace inference and the one-time ~37MB SFace download
synchronously inside the asyncio event loop.  The whole API — /health
included — froze until the pipeline finished, the web client aborted at its
default 15s timeout and mapped the abort to DEPENDENCY_UNAVAILABLE even
though the server was up and still processing (and would later commit the
credential).  These tests pin the heavy work to the dedicated face worker
thread so the event loop stays responsive.
"""

from __future__ import annotations

import asyncio
import threading
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import routes
from app.face_credentials import (
    FACE_PIPELINE_THREAD_PREFIX,
    run_face_pipeline,
    warm_face_models_if_present,
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


def test_face_registration_pipeline_runs_off_the_event_loop(
    client: TestClient,
    monkeypatch,
) -> None:
    owner = "hct424-offload-owner"
    password = "hct424-offload-owner-pass"
    owner_token, household = _owner_with_household(client, owner, password, "离线管线注册")

    pipeline_threads: list[str] = []

    def _recording_extract(_data: bytes, **_kwargs) -> tuple[bytes, dict]:
        pipeline_threads.append(threading.current_thread().name)
        return _TEMPLATE, dict(_TEMPLATE_METADATA)

    monkeypatch.setattr(routes, "extract_face_template", _recording_extract)
    monkeypatch.setattr(routes, "check_face_liveness", lambda *_args, **_kwargs: None)

    registered = client.post(
        f"/api/v1/households/{household}/face-credentials",
        headers={"Authorization": f"Bearer {owner_token}"},
        data={
            "consent": "true",
            "confirmation_method": "password",
            "confirmation_code": password,
        },
        files=_webcam_frames("offload-frame"),
    )

    assert registered.status_code == 201, registered.text
    assert pipeline_threads, "extraction never ran"
    assert all(
        name.startswith(FACE_PIPELINE_THREAD_PREFIX) for name in pipeline_threads
    ), f"face extraction ran on the event loop, not the face worker: {pipeline_threads}"


def test_face_login_pipeline_runs_off_the_event_loop(
    client: TestClient,
    monkeypatch,
) -> None:
    owner = "hct425-offload-owner"
    password = "hct425-offload-owner-pass"
    owner_token, household = _owner_with_household(client, owner, password, "离线管线登录")
    member = client.post(
        f"/api/v1/households/{household}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"display_name": "奶奶", "actor_id": "hct425-offload-grandma"},
    ).json()

    pipeline_threads: list[str] = []

    def _recording_extract(_data: bytes, **_kwargs) -> tuple[bytes, dict]:
        pipeline_threads.append(threading.current_thread().name)
        return _TEMPLATE, dict(_TEMPLATE_METADATA)

    monkeypatch.setattr(routes, "extract_face_template", _recording_extract)
    monkeypatch.setattr(routes, "check_face_liveness", lambda *_args, **_kwargs: None)

    files = _webcam_frames("offload-login-frame")
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

    pipeline_threads.clear()
    challenge = client.post(
        "/api/v1/auth/face-challenge",
        json={"household_id": household, "actor_id": member["actor_id"]},
    )
    logged_in = client.post(
        "/api/v1/auth/face-login",
        data={
            "household_id": household,
            "actor_id": member["actor_id"],
            "challenge_id": challenge.json()["challenge_id"],
        },
        files=files,
    )

    assert logged_in.status_code == 200, logged_in.text
    assert pipeline_threads, "login extraction never ran"
    assert all(
        name.startswith(FACE_PIPELINE_THREAD_PREFIX) for name in pipeline_threads
    ), f"face matching ran on the event loop, not the face worker: {pipeline_threads}"


def test_health_stays_responsive_while_face_registration_is_processing(
    client: TestClient,
    monkeypatch,
) -> None:
    """/health must answer while a slow face pipeline is in flight.

    Before the fix the event loop executed the pipeline itself, so this
    health probe hung until registration finished and the web client's
    15s abort surfaced as a false 「本地 API 不可用」.
    """
    owner = "hct424-health-owner"
    password = "hct424-health-owner-pass"
    owner_token, household = _owner_with_household(client, owner, password, "健康探针家庭")

    extraction_started = threading.Event()

    def _slow_extract(_data: bytes, **_kwargs) -> tuple[bytes, dict]:
        extraction_started.set()
        time.sleep(1.5)
        return _TEMPLATE, dict(_TEMPLATE_METADATA)

    monkeypatch.setattr(routes, "extract_face_template", _slow_extract)
    monkeypatch.setattr(routes, "check_face_liveness", lambda *_args, **_kwargs: None)

    register_result: dict = {}

    def _register() -> None:
        register_result["response"] = client.post(
            f"/api/v1/households/{household}/face-credentials",
            headers={"Authorization": f"Bearer {owner_token}"},
            data={
                "consent": "true",
                "confirmation_method": "password",
                "confirmation_code": password,
            },
            files=_webcam_frames("health-frame"),
        )

    register_thread = threading.Thread(target=_register, daemon=True)
    register_thread.start()
    try:
        assert extraction_started.wait(timeout=10), "registration never reached extraction"
        probe_started = time.perf_counter()
        health = client.get("/health")
        probe_elapsed = time.perf_counter() - probe_started
        assert health.status_code == 200
        # The first frame alone sleeps 1.5s in the worker; a blocked event
        # loop would keep this probe pending for several seconds.
        assert probe_elapsed < 1.4, (
            f"/health took {probe_elapsed:.2f}s while the face pipeline was running; "
            "the event loop appears blocked by face processing again"
        )
    finally:
        register_thread.join(timeout=30)

    assert not register_thread.is_alive(), "registration request never finished"
    assert register_result["response"].status_code == 201, register_result["response"].text


def test_run_face_pipeline_returns_values_and_propagates_errors() -> None:
    def _boom() -> None:
        raise ValueError("FACE_FRAME_LOW_QUALITY")

    async def _scenario() -> None:
        worker_names: list[str] = []

        def _observe(value: int) -> int:
            worker_names.append(threading.current_thread().name)
            return value + 1

        assert await run_face_pipeline(_observe, 41) == 42
        assert worker_names and worker_names[0].startswith(FACE_PIPELINE_THREAD_PREFIX)
        with pytest.raises(ValueError, match="FACE_FRAME_LOW_QUALITY"):
            await run_face_pipeline(_boom)

    asyncio.run(_scenario())


def test_warm_face_models_reports_missing_weights(tmp_path) -> None:
    """Startup warm never downloads: missing weights simply return False."""
    from app.config import get_settings

    settings = get_settings()
    previous = settings.face_model_dir
    settings.face_model_dir = str(tmp_path / "empty-face-models")
    try:
        assert warm_face_models_if_present() is False
    finally:
        settings.face_model_dir = previous
