"""HCT-424 face registration primitives.

Registration deliberately keeps pixels in memory only.  The stored value is a
small encrypted template produced by a versioned local algorithm; matching and
liveness are separate capabilities owned by HCT-425.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

import cv2
import numpy as np
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status

from app.config import get_settings

FACE_ALGORITHM_VERSION = "opencv-haar-grayscale-v1"
FACE_FEATURE_VERSION = "face-template-v1"
FACE_CONSENT_VERSION = "face-registration-consent-v1"
_FEATURE_SIZE = 32


def _cipher() -> Fernet:
    configured = get_settings().biometric_encryption_key.encode("utf-8")
    # Accept a Fernet key in deployment, while keeping a deterministic local
    # development fallback that never stores the raw config value.
    try:
        return Fernet(configured)
    except (ValueError, TypeError):
        derived = base64.urlsafe_b64encode(hashlib.sha256(configured).digest())
        return Fernet(derived)


def encrypt_template(template: bytes) -> bytes:
    return _cipher().encrypt(template)


def decrypt_template(ciphertext: bytes) -> bytes:
    try:
        return _cipher().decrypt(ciphertext)
    except InvalidToken as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FACE_CREDENTIAL_UNAVAILABLE",
        ) from exc


def extract_face_template(image_bytes: bytes) -> tuple[bytes, dict[str, Any]]:
    """Detect exactly one face and derive a normalized, versioned template."""
    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    try:
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    except cv2.error as exc:
        raise ValueError("FACE_FRAME_DECODE_FAILED") from exc
    if image is None:
        raise ValueError("FACE_FRAME_DECODE_FAILED")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    if cascade.empty():
        raise RuntimeError("FACE_DETECTOR_UNAVAILABLE")
    faces = cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(80, 80),
    )
    if len(faces) == 0:
        raise ValueError("FACE_NOT_FOUND")
    if len(faces) > 1:
        raise ValueError("FACE_MULTIPLE_SUBJECTS")

    x, y, width, height = [int(value) for value in faces[0]]
    crop = gray[y : y + height, x : x + width]
    if crop.size == 0:
        raise ValueError("FACE_CROP_INVALID")
    normalized = cv2.equalizeHist(crop)
    normalized = cv2.resize(
        normalized,
        (_FEATURE_SIZE, _FEATURE_SIZE),
        interpolation=cv2.INTER_AREA,
    ).astype(np.float32)
    normalized = (normalized - float(normalized.mean())) / (float(normalized.std()) + 1e-6)
    template = normalized.astype("<f4").tobytes()
    return template, {
        "face_count": 1,
        "feature_dimensions": [_FEATURE_SIZE, _FEATURE_SIZE],
        "algorithm_version": FACE_ALGORITHM_VERSION,
        "feature_version": FACE_FEATURE_VERSION,
    }
