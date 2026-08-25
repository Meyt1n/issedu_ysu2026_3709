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


def test_face_template_similarity_is_bounded_for_valid_templates() -> None:
    first = (b"\x00\x00\x80\x3f" * (32 * 32))
    second = (b"\x00\x00\x80\x3f" * (32 * 32))

    assert face_template_similarity(first, second) == pytest.approx(1.0)


@pytest.mark.parametrize("image_bytes", [b"", b"not-an-image"])
def test_registration_rejects_undecodable_frames(image_bytes: bytes) -> None:
    with pytest.raises(ValueError, match="FACE_FRAME_DECODE_FAILED"):
        extract_face_template(image_bytes)
