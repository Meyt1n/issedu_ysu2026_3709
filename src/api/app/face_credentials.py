"""HCT-424 face registration primitives.

Registration deliberately keeps pixels in memory only.  The stored value is a
small encrypted template produced by a versioned local algorithm; matching and
liveness are separate capabilities owned by HCT-425.
"""

from __future__ import annotations

import base64
import hashlib
import os
import tempfile
from typing import Any

import cv2
import numpy as np
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status

from app.config import get_settings

FACE_ALGORITHM_VERSION = "opencv-haar-grayscale-v1"
FACE_FEATURE_VERSION = "face-template-v1"
FACE_CONSENT_VERSION = "face-registration-consent-v1"
FACE_LIVENESS_VERSION = "motion-sequence-v1"
_FEATURE_SIZE = 32
FACE_MATCH_THRESHOLD = 0.82
_FACE_CASCADE_FILENAME = "haarcascade_frontalface_default.xml"


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


def _load_face_cascade() -> cv2.CascadeClassifier:
    """Load the bundled detector, including Windows Unicode-path fallback."""
    source = os.path.join(cv2.data.haarcascades, _FACE_CASCADE_FILENAME)
    if os.name != "nt" or source.isascii():
        cascade = cv2.CascadeClassifier(source)
        if not cascade.empty():
            return cascade

    # OpenCV's Windows loader can fail when the repository path contains non-ASCII
    # characters.  A short-lived ASCII temp path keeps the detector local and
    # avoids changing the configured project or model paths.
    try:
        with open(source, "rb") as source_file, tempfile.NamedTemporaryFile(
            mode="wb", suffix=".xml", delete=False
        ) as fallback_file:
            fallback_file.write(source_file.read())
            fallback_path = fallback_file.name
        cascade = cv2.CascadeClassifier(fallback_path)
    finally:
        if "fallback_path" in locals():
            try:
                os.unlink(fallback_path)
            except OSError:
                pass
    return cascade


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
    cascade = _load_face_cascade()
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


def face_template_similarity(left: bytes, right: bytes) -> float:
    """Return cosine similarity for two local, versioned face templates."""
    expected = _FEATURE_SIZE * _FEATURE_SIZE * 4
    if len(left) != expected or len(right) != expected:
        raise ValueError("FACE_TEMPLATE_INVALID")
    left_values = np.frombuffer(left, dtype="<f4").astype(np.float32)
    right_values = np.frombuffer(right, dtype="<f4").astype(np.float32)
    left_norm = float(np.linalg.norm(left_values))
    right_norm = float(np.linalg.norm(right_values))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("FACE_TEMPLATE_INVALID")
    return float(np.dot(left_values, right_values) / (left_norm * right_norm))


def check_face_liveness(templates: list[bytes]) -> None:
    """Require a short motion sequence; identical replayed frames are rejected."""
    if len(templates) < 2 or len(templates) > 3:
        raise ValueError("FACE_LIVENESS_FAILED")
    try:
        similarities = [
            face_template_similarity(templates[index], templates[index + 1])
            for index in range(len(templates) - 1)
        ]
    except ValueError as exc:
        raise ValueError("FACE_LIVENESS_FAILED") from exc
    # A live sequence must contain measurable pose/illumination change.  This
    # intentionally rejects a repeated still image while keeping the heuristic
    # deterministic and versioned for this local OpenCV implementation.
    if all(similarity >= 0.9995 for similarity in similarities):
        raise ValueError("FACE_LIVENESS_FAILED")
