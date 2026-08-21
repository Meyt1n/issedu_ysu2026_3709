from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.face_credentials import (
    check_face_liveness,
    decrypt_template,
    encrypt_template,
    extract_face_template,
    face_template_similarity,
)


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


def test_face_template_similarity_is_bounded_for_valid_templates() -> None:
    first = (b"\x00\x00\x80\x3f" * (32 * 32))
    second = (b"\x00\x00\x80\x3f" * (32 * 32))

    assert face_template_similarity(first, second) == pytest.approx(1.0)


@pytest.mark.parametrize("image_bytes", [b"", b"not-an-image"])
def test_registration_rejects_undecodable_frames(image_bytes: bytes) -> None:
    with pytest.raises(ValueError, match="FACE_FRAME_DECODE_FAILED"):
        extract_face_template(image_bytes)
