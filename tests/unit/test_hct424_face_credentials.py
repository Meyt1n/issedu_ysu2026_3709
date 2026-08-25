from __future__ import annotations

import numpy as np
import pytest
from fastapi import HTTPException

from app.face_credentials import (
    aggregate_match_scores,
    check_face_liveness,
    decrypt_template,
    encrypt_template,
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

    left = extract_face_template(obama.read_bytes())[0]
    same = extract_face_template(obama2.read_bytes())[0]
    other = extract_face_template(biden.read_bytes())[0]

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
