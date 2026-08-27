from __future__ import annotations

import cv2
import numpy as np
import pytest
from fastapi import HTTPException

from app.face_credentials import (
    aggregate_match_scores,
    check_face_liveness,
    decrypt_template,
    encrypt_template,
    ensure_face_frame_quality,
    extract_face_template,
    face_template_similarity,
)


def _pattern_template(flip_count: int = 0, *, invert: bool = False) -> bytes:
    """Deterministic 64x64 template made of ±1 values for similarity control."""
    values = np.ones(64 * 64, dtype="<f4")
    values[:flip_count] = -1.0
    if invert:
        values = -values
    return values.tobytes()


def _webcam_selfie_jpeg(width: int = 960, height: int = 540, *, seed: int = 7) -> bytes:
    """Guided-capture style frame: one person in front of a plain wall.

    Deliberately low edge density (plain background, no text) — exactly the
    kind of valid frame the medicine-carton OCR gate used to reject as
    FACE_FRAME_LOW_QUALITY before HCT-424 got its own face frame gate.
    """
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


def test_face_template_is_encrypted_and_round_trips() -> None:
    template = b"normalized-face-template"

    ciphertext = encrypt_template(template)

    assert ciphertext != template
    assert template not in ciphertext
    assert decrypt_template(ciphertext) == template


def test_invalid_ciphertext_is_not_returned() -> None:
    with pytest.raises(HTTPException) as error:
        decrypt_template(b"not-a-fernet-token")

    assert error.value.status_code == 500
    assert error.value.detail == "FACE_CREDENTIAL_UNAVAILABLE"


def test_face_liveness_rejects_replayed_still_frames() -> None:
    template = b"\x00" * (32 * 32 * 4)

    with pytest.raises(ValueError, match="FACE_LIVENESS_FAILED"):
        check_face_liveness([template, template])


def test_face_liveness_rejects_partial_replay_sequences() -> None:
    """motion-sequence-v2: one replayed pair inside [A, A, B] must fail too."""
    still = _pattern_template()
    moved = _pattern_template(flip_count=205)

    with pytest.raises(ValueError, match="FACE_LIVENESS_FAILED"):
        check_face_liveness([still, still, moved])


def test_face_liveness_rejects_spliced_subject_sequences() -> None:
    """Frames that stop resembling each other look spliced, not live motion."""
    subject = _pattern_template()
    unrelated = _pattern_template(invert=True)

    with pytest.raises(ValueError, match="FACE_LIVENESS_FAILED"):
        check_face_liveness([subject, unrelated])


def test_face_liveness_accepts_moderate_consistent_motion() -> None:
    frames = [
        _pattern_template(),
        _pattern_template(flip_count=205),
        _pattern_template(flip_count=410),
    ]

    check_face_liveness(frames)


def test_aggregate_match_scores_requires_every_frame_to_match() -> None:
    """A single injected matching photo must not dominate the match score."""
    assert aggregate_match_scores([0.99, 0.5, 0.9]) == pytest.approx(0.5)
    assert aggregate_match_scores([0.9]) == pytest.approx(0.9)
    with pytest.raises(ValueError, match="FACE_TEMPLATE_INVALID"):
        aggregate_match_scores([])


def test_pack_and_unpack_multi_angle_gallery() -> None:
    from app.face_credentials import (
        pack_face_templates,
        score_probe_against_gallery,
        unpack_face_templates,
    )

    # Force SFace-sized payloads for the multi-template packer.
    a128 = b"\x00\x00\x80\x3f" * 128
    b128 = b"\x00\x00\x80\xbf" * 128
    packed = pack_face_templates([a128, b128])
    gallery = unpack_face_templates(packed)
    assert len(gallery) == 2
    assert unpack_face_templates(a128) == [a128]
    assert score_probe_against_gallery(a128, gallery) == pytest.approx(1.0)


def test_normalize_face_failure_reason_buckets() -> None:
    from app.face_credentials import normalize_face_failure_reason

    assert normalize_face_failure_reason("FACE_TOO_SMALL") == "FRAME_QUALITY_INVALID"
    assert normalize_face_failure_reason("FACE_LIVENESS_FAILED") == "LIVENESS_FAILED"
    assert normalize_face_failure_reason("NO_MATCH") == "NO_MATCH"
    assert normalize_face_failure_reason("LOCKED:30") == "FACE_AUTH_FAILED"


def test_pose_liveness_requires_yaw_span() -> None:
    frames = [
        _pattern_template(),
        _pattern_template(flip_count=205),
        _pattern_template(flip_count=410),
    ]
    check_face_liveness(frames, yaws=[-0.2, 0.0, 0.25], purpose="registration")
    with pytest.raises(ValueError, match="FACE_LIVENESS_FAILED"):
        check_face_liveness(frames, yaws=[0.0, 0.01, -0.01], purpose="registration")


def test_login_liveness_accepts_two_frame_motion_without_yaw() -> None:
    """Login short path: neighbor motion only; yaw is optional for purpose=login."""
    frames = [
        _pattern_template(),
        _pattern_template(flip_count=205),
    ]
    check_face_liveness(frames, purpose="login")
    check_face_liveness(frames, yaws=None, purpose="login")
    with pytest.raises(ValueError, match="FACE_LIVENESS_FAILED"):
        check_face_liveness([frames[0]], purpose="login")


def test_match_threshold_for_uses_sface_gate_on_v3() -> None:
    from app.face_credentials import (
        FACE_ALGORITHM_VERSION,
        FACE_MATCH_THRESHOLD_SFACE,
        V2_FACE_ALGORITHM_VERSION,
        match_threshold_for,
    )

    assert match_threshold_for(FACE_ALGORITHM_VERSION) == FACE_MATCH_THRESHOLD_SFACE
    assert match_threshold_for(V2_FACE_ALGORITHM_VERSION) == pytest.approx(0.82)


def test_sface_embeddings_separate_different_people(tmp_path, monkeypatch) -> None:
    """v3 must accept same-person pairs and reject a different person."""
    import shutil
    from pathlib import Path

    from app.face_credentials import (
        FACE_MATCH_THRESHOLD_SFACE,
        _sface_recognizer,
        ensure_face_models,
        extract_face_template,
        face_template_similarity,
    )

    sample_dir = Path("/tmp/face-samples")
    obama = sample_dir / "obama.jpg"
    obama2 = sample_dir / "obama2.jpg"
    biden = sample_dir / "biden.jpg"
    if not (obama.is_file() and obama2.is_file() and biden.is_file()):
        pytest.skip("sample face images unavailable")

    model_dir = tmp_path / "face-models"
    model_dir.mkdir()
    source = Path("models/face")
    if not (source / "face_recognition_sface_2021dec.onnx").is_file():
        pytest.skip("local SFace models unavailable")
    for name in (
        "face_detection_yunet_2023mar.onnx",
        "face_recognition_sface_2021dec.onnx",
    ):
        shutil.copy(source / name, model_dir / name)

    monkeypatch.setenv("FACE_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("FACE_MODEL_AUTO_DOWNLOAD", "false")
    from app.config import get_settings

    get_settings.cache_clear()
    _sface_recognizer.cache_clear()
    ensure_face_models()

    left = extract_face_template(obama.read_bytes(), enforce_geometry=False)[0]
    same = extract_face_template(obama2.read_bytes(), enforce_geometry=False)[0]
    other = extract_face_template(biden.read_bytes(), enforce_geometry=False)[0]

    assert len(left) == 128 * 4
    assert face_template_similarity(left, same) >= FACE_MATCH_THRESHOLD_SFACE
    assert face_template_similarity(left, other) < FACE_MATCH_THRESHOLD_SFACE
    get_settings.cache_clear()
    _sface_recognizer.cache_clear()


def test_face_template_similarity_is_bounded_for_valid_templates() -> None:
    first = (b"\x00\x00\x80\x3f" * (32 * 32))
    second = (b"\x00\x00\x80\x3f" * (32 * 32))

    assert face_template_similarity(first, second) == pytest.approx(1.0)


@pytest.mark.parametrize("image_bytes", [b"", b"not-an-image"])
def test_registration_rejects_undecodable_frames(image_bytes: bytes) -> None:
    with pytest.raises(ValueError, match="FACE_FRAME_DECODE_FAILED"):
        extract_face_template(image_bytes)


@pytest.mark.parametrize(
    ("width", "height"),
    [
        (960, 540),  # 1280x720 webcam capped to 960 wide by FaceVideoCapture
        (640, 480),  # classic 4:3 webcam
        (640, 360),  # common 16:9 low-res fallback when 720p is unavailable
        (360, 640),  # mobile portrait
    ],
)
def test_face_frame_gate_accepts_guided_webcam_captures(width: int, height: int) -> None:
    """Regression HCT-424: valid guided captures must not be rejected.

    These plain-background selfie frames fail the medicine-carton OCR gate
    (edge density / subject contour / 480px height floor), which used to be
    misapplied to face frames and surfaced as FACE_FRAME_LOW_QUALITY.
    """
    metrics = ensure_face_frame_quality(_webcam_selfie_jpeg(width, height))

    assert metrics["width"] == float(width)
    assert metrics["height"] == float(height)


@pytest.mark.parametrize(("width", "height"), [(320, 240), (160, 120), (479, 200)])
def test_face_frame_gate_rejects_tiny_frames(width: int, height: int) -> None:
    with pytest.raises(ValueError, match="FACE_FRAME_LOW_QUALITY"):
        ensure_face_frame_quality(_webcam_selfie_jpeg(width, height))


@pytest.mark.parametrize("level", [0, 255])
def test_face_frame_gate_rejects_black_or_blown_out_frames(level: int) -> None:
    """A covered lens (black) or hard backlight (white) is still unusable."""
    flat = np.full((540, 960, 3), level, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", flat)
    assert ok

    with pytest.raises(ValueError, match="FACE_FRAME_LOW_QUALITY"):
        ensure_face_frame_quality(encoded.tobytes())


def test_face_frame_gate_rejects_undecodable_bytes() -> None:
    with pytest.raises(ValueError, match="FACE_FRAME_DECODE_FAILED"):
        ensure_face_frame_quality(b"not-an-image")
