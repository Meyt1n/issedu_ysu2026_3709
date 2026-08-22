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

FACE_ALGORITHM_VERSION = "opencv-haar-grayscale-v2"
FACE_FEATURE_VERSION = "face-template-v2"
LEGACY_FACE_ALGORITHM_VERSION = "opencv-haar-grayscale-v1"
LEGACY_FACE_FEATURE_VERSION = "face-template-v1"
FACE_CONSENT_VERSION = "face-registration-consent-v1"
FACE_LIVENESS_VERSION = "motion-sequence-v1"
_FEATURE_SIZE = 64
_LEGACY_FEATURE_SIZE = 32
FACE_MATCH_THRESHOLD = 0.82
FAMILY_FACE_MATCH_MARGIN = 0.06
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


def _decode_face_image(image_bytes: bytes) -> np.ndarray:
    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    try:
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    except cv2.error as exc:
        raise ValueError("FACE_FRAME_DECODE_FAILED") from exc
    if image is None:
        raise ValueError("FACE_FRAME_DECODE_FAILED")
    return image


def _detect_single_face(gray: np.ndarray) -> tuple[int, int, int, int]:
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
    return tuple(int(value) for value in faces[0])


def _normalize_crop(crop: np.ndarray, feature_size: int, *, robust: bool) -> bytes:
    if crop.size == 0:
        raise ValueError("FACE_CROP_INVALID")
    if robust:
        # A padded crop is less sensitive to a Haar box moving by a few pixels
        # between registration and login. CLAHE keeps indoor lighting changes
        # from dominating the local template without sending pixels anywhere.
        normalized = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(crop)
    else:
        normalized = cv2.equalizeHist(crop)
    normalized = cv2.resize(
        normalized,
        (feature_size, feature_size),
        interpolation=cv2.INTER_AREA,
    ).astype(np.float32)
    normalized = (normalized - float(normalized.mean())) / (float(normalized.std()) + 1e-6)
    return normalized.astype("<f4").tobytes()


def extract_face_template(image_bytes: bytes) -> tuple[bytes, dict[str, Any]]:
    """Detect one face and derive a lighting/box-tolerant v2 template."""
    image = _decode_face_image(image_bytes)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    x, y, width, height = _detect_single_face(gray)

    pad_x = int(width * 0.24)
    pad_top = int(height * 0.26)
    pad_bottom = int(height * 0.34)
    left = max(0, x - pad_x)
    top = max(0, y - pad_top)
    right = min(gray.shape[1], x + width + pad_x)
    bottom = min(gray.shape[0], y + height + pad_bottom)
    template = _normalize_crop(gray[top:bottom, left:right], _FEATURE_SIZE, robust=True)
    return template, {
        "face_count": 1,
        "feature_dimensions": [_FEATURE_SIZE, _FEATURE_SIZE],
        "algorithm_version": FACE_ALGORITHM_VERSION,
        "feature_version": FACE_FEATURE_VERSION,
    }


def extract_legacy_face_template(image_bytes: bytes) -> tuple[bytes, dict[str, Any]]:
    """Keep already registered v1 credentials usable until the user rebinds."""
    image = _decode_face_image(image_bytes)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    x, y, width, height = _detect_single_face(gray)
    template = _normalize_crop(
        gray[y : y + height, x : x + width],
        _LEGACY_FEATURE_SIZE,
        robust=False,
    )
    return template, {
        "face_count": 1,
        "feature_dimensions": [_LEGACY_FEATURE_SIZE, _LEGACY_FEATURE_SIZE],
        "algorithm_version": LEGACY_FACE_ALGORITHM_VERSION,
        "feature_version": LEGACY_FACE_FEATURE_VERSION,
    }


def face_template_similarity(left: bytes, right: bytes) -> float:
    """Return cosine similarity for two local, versioned face templates."""
    valid_sizes = {
        _FEATURE_SIZE * _FEATURE_SIZE * 4,
        _LEGACY_FEATURE_SIZE * _LEGACY_FEATURE_SIZE * 4,
    }
    if len(left) not in valid_sizes or len(right) not in valid_sizes or len(left) != len(right):
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
