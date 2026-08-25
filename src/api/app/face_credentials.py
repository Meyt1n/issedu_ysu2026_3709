"""HCT-424/425 face registration and matching primitives.

Registration keeps pixels in memory only.  Stored values are small encrypted
templates produced by a versioned local algorithm:

- v1/v2: OpenCV Haar grayscale crops (legacy; weak identity separation)
- v3: OpenCV YuNet detection + SFace embedding (local ONNX; suitable for
  household 1:N member separation)

Matching and liveness remain HCT-425 capabilities.  Model weights are never
committed to the repository; they are loaded from a local cache directory and
may be downloaded once when explicitly allowed.
"""

from __future__ import annotations

import base64
import hashlib
import os
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status

from app.config import get_settings

# Current registration target: local SFace embeddings.
FACE_ALGORITHM_VERSION = "opencv-yunet-sface-v3"
FACE_FEATURE_VERSION = "face-embedding-sface-v3"
# Prior grayscale templates remain matchable until the member rebinds.
V2_FACE_ALGORITHM_VERSION = "opencv-haar-grayscale-v2"
V2_FACE_FEATURE_VERSION = "face-template-v2"
LEGACY_FACE_ALGORITHM_VERSION = "opencv-haar-grayscale-v1"
LEGACY_FACE_FEATURE_VERSION = "face-template-v1"
FACE_CONSENT_VERSION = "face-registration-consent-v1"
FACE_LIVENESS_VERSION = "motion-sequence-v2"

_FEATURE_SIZE = 64
_LEGACY_FEATURE_SIZE = 32
_SFACE_EMBEDDING_SIZE = 128
_SFACE_INPUT_SIZE = 112

# Grayscale crop cosine threshold (legacy v1/v2).
FACE_MATCH_THRESHOLD_GRAYSCALE = 0.82
FAMILY_FACE_MATCH_MARGIN_GRAYSCALE = 0.06
# SFace cosine threshold (OpenCV zoo default is 0.363).  A slightly higher
# gate reduces false accepts between household members in 1:N matching.
FACE_MATCH_THRESHOLD_SFACE = 0.40
FAMILY_FACE_MATCH_MARGIN_SFACE = 0.05
# Back-compat exports used by older imports/tests; prefer match_threshold_for().
FACE_MATCH_THRESHOLD = FACE_MATCH_THRESHOLD_SFACE
FAMILY_FACE_MATCH_MARGIN = FAMILY_FACE_MATCH_MARGIN_SFACE

# motion-sequence-v2: a consecutive pair at or above this similarity is an
# identical (replayed) frame; every pair of a live capture must show change.
FACE_LIVENESS_MAX_PAIR_SIMILARITY = 0.9995
# Frames captured within one short live sequence must stay recognisably the
# same subject.  Grayscale crops need a higher floor; SFace embeddings of the
# same person under mild motion commonly sit around 0.5–0.9.
FACE_SEQUENCE_CONSISTENCY_FLOOR_GRAYSCALE = 0.55
FACE_SEQUENCE_CONSISTENCY_FLOOR_SFACE = 0.30

_FACE_CASCADE_FILENAME = "haarcascade_frontalface_default.xml"
_YUNET_FILENAME = "face_detection_yunet_2023mar.onnx"
_SFACE_FILENAME = "face_recognition_sface_2021dec.onnx"
_MODEL_URLS = {
    _YUNET_FILENAME: (
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx"
    ),
    _SFACE_FILENAME: (
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_recognition_sface/face_recognition_sface_2021dec.onnx"
    ),
}


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


def match_threshold_for(algorithm_version: str) -> float:
    if algorithm_version in {FACE_ALGORITHM_VERSION}:
        return FACE_MATCH_THRESHOLD_SFACE
    return FACE_MATCH_THRESHOLD_GRAYSCALE


def family_match_margin_for(algorithm_version: str) -> float:
    if algorithm_version in {FACE_ALGORITHM_VERSION}:
        return FAMILY_FACE_MATCH_MARGIN_SFACE
    return FAMILY_FACE_MATCH_MARGIN_GRAYSCALE


def ranking_margin(score: float, algorithm_version: str) -> float:
    """Comparable 1:N rank key across mixed template versions."""
    return float(score) - match_threshold_for(algorithm_version)


def face_extractor_for(algorithm_version: str) -> Callable[[bytes], tuple[bytes, dict[str, Any]]]:
    if algorithm_version == LEGACY_FACE_ALGORITHM_VERSION:
        return extract_legacy_face_template
    if algorithm_version == V2_FACE_ALGORITHM_VERSION:
        return extract_v2_face_template
    return extract_face_template


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


def _face_model_dir() -> Path:
    return Path(get_settings().face_model_dir).expanduser().resolve()


def _download_face_model(filename: str, destination: Path) -> None:
    url = _MODEL_URLS[filename]
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    try:
        with urllib.request.urlopen(url, timeout=60) as response, open(partial, "wb") as handle:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                handle.write(chunk)
        partial.replace(destination)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError("FACE_DETECTOR_UNAVAILABLE") from exc


def ensure_face_models() -> tuple[Path, Path]:
    """Return local YuNet/SFace paths, downloading once when allowed."""
    model_dir = _face_model_dir()
    yunet = model_dir / _YUNET_FILENAME
    sface = model_dir / _SFACE_FILENAME
    missing = [path for path in (yunet, sface) if not path.is_file()]
    if missing and not get_settings().face_model_auto_download:
        raise RuntimeError("FACE_DETECTOR_UNAVAILABLE")
    for path in missing:
        _download_face_model(path.name, path)
    if not yunet.is_file() or not sface.is_file():
        raise RuntimeError("FACE_DETECTOR_UNAVAILABLE")
    return yunet, sface


@lru_cache(maxsize=1)
def _sface_recognizer() -> cv2.FaceRecognizerSF:
    _, sface = ensure_face_models()
    recognizer = cv2.FaceRecognizerSF_create(str(sface), "")
    if recognizer is None:
        raise RuntimeError("FACE_DETECTOR_UNAVAILABLE")
    return recognizer


def _yunet_detector(image_width: int, image_height: int) -> cv2.FaceDetectorYN:
    yunet, _ = ensure_face_models()
    detector = cv2.FaceDetectorYN_create(
        str(yunet),
        "",
        (image_width, image_height),
        0.6,
        0.3,
        5000,
    )
    if detector is None:
        raise RuntimeError("FACE_DETECTOR_UNAVAILABLE")
    return detector


def _decode_face_image(image_bytes: bytes) -> np.ndarray:
    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    try:
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    except cv2.error as exc:
        raise ValueError("FACE_FRAME_DECODE_FAILED") from exc
    if image is None:
        raise ValueError("FACE_FRAME_DECODE_FAILED")
    return image


def _detect_single_face_haar(gray: np.ndarray) -> tuple[int, int, int, int]:
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


def _detect_single_face_yunet(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    detector = _yunet_detector(width, height)
    detector.setInputSize((width, height))
    _, faces = detector.detect(image)
    if faces is None or len(faces) == 0:
        raise ValueError("FACE_NOT_FOUND")
    if len(faces) > 1:
        raise ValueError("FACE_MULTIPLE_SUBJECTS")
    # YuNet rows are [x, y, w, h, landmarks..., score]; alignCrop wants the
    # detection row without the trailing score.
    return faces[0][:-1]


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
    """Detect one face and derive a local SFace embedding (v3)."""
    image = _decode_face_image(image_bytes)
    recognizer = _sface_recognizer()
    try:
        face = _detect_single_face_yunet(image)
        aligned = recognizer.alignCrop(image, face)
    except ValueError as exc:
        if str(exc) != "FACE_NOT_FOUND":
            raise
        # Fall back to Haar box + square resize when YuNet misses a usable
        # landmark row but a single frontal face is still present.
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        x, y, width, height = _detect_single_face_haar(gray)
        pad_x = int(width * 0.20)
        pad_top = int(height * 0.25)
        pad_bottom = int(height * 0.30)
        left = max(0, x - pad_x)
        top = max(0, y - pad_top)
        right = min(image.shape[1], x + width + pad_x)
        bottom = min(image.shape[0], y + height + pad_bottom)
        aligned = cv2.resize(
            image[top:bottom, left:right],
            (_SFACE_INPUT_SIZE, _SFACE_INPUT_SIZE),
            interpolation=cv2.INTER_AREA,
        )
    feature = recognizer.feature(aligned)
    if feature is None or feature.size != _SFACE_EMBEDDING_SIZE:
        raise ValueError("FACE_TEMPLATE_INVALID")
    template = np.asarray(feature, dtype=np.float32).reshape(-1).astype("<f4").tobytes()
    return template, {
        "face_count": 1,
        "feature_dimensions": [_SFACE_EMBEDDING_SIZE],
        "algorithm_version": FACE_ALGORITHM_VERSION,
        "feature_version": FACE_FEATURE_VERSION,
    }


def extract_v2_face_template(image_bytes: bytes) -> tuple[bytes, dict[str, Any]]:
    """Keep already registered v2 grayscale credentials usable until rebind."""
    image = _decode_face_image(image_bytes)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    x, y, width, height = _detect_single_face_haar(gray)

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
        "algorithm_version": V2_FACE_ALGORITHM_VERSION,
        "feature_version": V2_FACE_FEATURE_VERSION,
    }


def extract_legacy_face_template(image_bytes: bytes) -> tuple[bytes, dict[str, Any]]:
    """Keep already registered v1 credentials usable until the user rebinds."""
    image = _decode_face_image(image_bytes)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    x, y, width, height = _detect_single_face_haar(gray)
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
        _SFACE_EMBEDDING_SIZE * 4,
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


def _consistency_floor_for_templates(templates: list[bytes]) -> float:
    if templates and len(templates[0]) == _SFACE_EMBEDDING_SIZE * 4:
        return FACE_SEQUENCE_CONSISTENCY_FLOOR_SFACE
    return FACE_SEQUENCE_CONSISTENCY_FLOOR_GRAYSCALE


def check_face_liveness(templates: list[bytes]) -> None:
    """Require a short one-subject motion sequence (motion-sequence-v2).

    v1 only rejected a sequence in which *no* pair of consecutive frames
    changed, so ``[still, still, other]`` passed.  v2 requires every
    consecutive pair to show measurable change (no replayed frame anywhere in
    the sequence) and to stay recognisably the same subject, which rejects
    sequences spliced together from different sources.  This remains a
    deterministic, versioned local OpenCV heuristic, not production-grade
    anti-spoofing.
    """
    if len(templates) < 2 or len(templates) > 3:
        raise ValueError("FACE_LIVENESS_FAILED")
    try:
        similarities = [
            face_template_similarity(templates[index], templates[index + 1])
            for index in range(len(templates) - 1)
        ]
    except ValueError as exc:
        raise ValueError("FACE_LIVENESS_FAILED") from exc
    consistency_floor = _consistency_floor_for_templates(templates)
    for similarity in similarities:
        if similarity >= FACE_LIVENESS_MAX_PAIR_SIMILARITY:
            raise ValueError("FACE_LIVENESS_FAILED")
        if similarity < consistency_floor:
            raise ValueError("FACE_LIVENESS_FAILED")


def aggregate_match_scores(scores: list[float]) -> float:
    """Reduce per-frame similarities to the score used against the threshold.

    Every submitted frame must independently match the stored template, so the
    aggregate is the *minimum*.  Taking the best frame (``max``) would let an
    attacker pass by injecting a single photo of the victim among otherwise
    unrelated motion frames.
    """
    if not scores:
        raise ValueError("FACE_TEMPLATE_INVALID")
    return min(scores)
