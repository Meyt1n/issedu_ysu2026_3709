from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.face_credentials import decrypt_template, encrypt_template, extract_face_template


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


@pytest.mark.parametrize("image_bytes", [b"", b"not-an-image"])
def test_registration_rejects_undecodable_frames(image_bytes: bytes) -> None:
    with pytest.raises(ValueError, match="FACE_FRAME_DECODE_FAILED"):
        extract_face_template(image_bytes)
