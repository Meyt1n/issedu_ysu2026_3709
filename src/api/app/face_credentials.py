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
FACE_LIVENESS_VERSION = "motion-sequence-v3"
FACE_FEATURE_VERSION_MULTI = "face-embedding-sface-v3-multi"

_FEATURE_SIZE = 64
_LEGACY_FEATURE_SIZE = 32
_SFACE_EMBEDDING_SIZE = 128
_SFACE_INPUT_SIZE = 112
_BUNDLE_MAGIC = b"HCTFB01\0"

# Grayscale crop cosine threshold (legacy v1/v2).
FACE_MATCH_THRESHOLD_GRAYSCALE = 0.82
FAMILY_FACE_MATCH_MARGIN_GRAYSCALE = 0.06
# SFace defaults (override via FACE_MATCH_THRESHOLD_SFACE settings). OpenCV zoo
# cosine default is 0.363; 0.40 is a safer household false-accept gate until
# scripts/calibrate_face_thresholds.py is run on local camera captures.
FACE_MATCH_THRESHOLD_SFACE = 0.40
FAMILY_FACE_MATCH_MARGIN_SFACE = 0.05
# Back-compat exports used by older imports/tests; prefer match_threshold_for().
FACE_MATCH_THRESHOLD = FACE_MATCH_THRESHOLD_SFACE
FAMILY_FACE_MATCH_MARGIN = FAMILY_FACE_MATCH_MARGIN_SFACE

# motion-sequence-v3: every consecutive pair must change, stay the same subject,
# and the yaw span across the sequence must show a deliberate head turn.
FACE_LIVENESS_MAX_PAIR_SIMILARITY = 0.9995
FACE_SEQUENCE_CONSISTENCY_FLOOR_GRAYSCALE = 0.55
FACE_SEQUENCE_CONSISTENCY_FLOOR_SFACE = 0.30
FACE_YAW_SPAN_MIN = 0.12
FACE_YAW_ABS_MAX = 0.62
FACE_AREA_RATIO_MIN = 0.06
FACE_AREA_RATIO_MAX = 0.55
FACE_CROP_BLUR_MIN = 35.0

# Face frames come from the guided webcam capture (FaceVideoCapture.vue), not
# from medicine-carton photos, so they get their own pre-gate instead of the
# OCR quality gate in ai.vision.quality_gate.  That gate expects text-dense
# cartons and falsely rejected valid selfies: a person in front of a plain
# wall fails its edge-density/subject-contour checks, and common 16:9 low-res
# webcams (640x360) fail its 480px height floor.  Face sharpness, size, pose
# and single-subject rules remain enforced by YuNet detection plus
# assess_face_frame_geometry, so this gate only rejects frames that are
# clearly unusable: too small for a stable 112x112 SFace crop, or almost
# entirely black/white (covered lens, hard backlight).
FACE_FRAME_MIN_SIDE = 360
FACE_FRAME_MIN_LONG_SIDE = 480
FACE_FRAME_MIN_MEAN_LUMINANCE = 20.0
FACE_FRAME_MAX_MEAN_LUMINANCE = 245.0

# Desensitized auth failure buckets for audit aggregation (no scores/templates).
FACE_FAILURE_REASON_BUCKETS = frozenset(
    {
        "FRAME_QUALITY_INVALID",
        "LIVENESS_FAILED",
        "NO_MATCH",
        "AMBIGUOUS_MATCH",
        "FACE_SERVICE_UNAVAILABLE",
        "RATE_LIMITED",
        "CREDENTIAL_UNAVAILABLE",
        "CHALLENGE_INVALID",
        "FRAME_COUNT_INVALID",
        "FRAME_TYPE_INVALID",
        "FRAME_SIZE_INVALID",
        "FRAME_MAGIC_INVALID",
        "FACE_MATCH_FAILED",
        "FACE_AUTH_FAILED",
    }
)

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
        return float(get_settings().face_match_threshold_sface)
    return FACE_MATCH_THRESHOLD_GRAYSCALE


def family_match_margin_for(algorithm_version: str) -> float:
    if algorithm_version in {FACE_ALGORITHM_VERSION}:
        return float(get_settings().face_match_margin_sface)
    return FAMILY_FACE_MATCH_MARGIN_GRAYSCALE


def ranking_margin(score: float, algorithm_version: str) -> float:
    """Comparable 1:N rank key across mixed template versions."""
    return float(score) - match_threshold_for(algorithm_version)


def face_models_ready() -> bool:
    """True when YuNet + SFace ONNX files are present locally (no download)."""
    model_dir = _face_model_dir()
    return (model_dir / _YUNET_FILENAME).is_file() and (model_dir / _SFACE_FILENAME).is_file()


def is_legacy_face_algorithm(algorithm_version: str) -> bool:
    return algorithm_version in {
        LEGACY_FACE_ALGORITHM_VERSION,
        V2_FACE_ALGORITHM_VERSION,
    }


def normalize_face_failure_reason(reason: str) -> str:
    """Map raw failure codes onto a fixed desensitized bucket set."""
    token = (reason or "FACE_AUTH_FAILED").split(":", 1)[0].strip().upper()
    if token in FACE_FAILURE_REASON_BUCKETS:
        return token
    if token.startswith("FACE_") and "QUALITY" in token:
        return "FRAME_QUALITY_INVALID"
    quality_tokens = {
        "FACE_NOT_FOUND",
        "FACE_MULTIPLE_SUBJECTS",
        "FACE_POSE_EXTREME",
        "FACE_TOO_SMALL",
        "FACE_TOO_LARGE",
        "FACE_BLURRY",
        "FACE_FRAME_LOW_QUALITY",
    }
    if token in quality_tokens:
        return "FRAME_QUALITY_INVALID"
    if token == "FACE_LIVENESS_FAILED":
        return "LIVENESS_FAILED"
    service_tokens = {
        "FACE_DETECTOR_UNAVAILABLE",
        "FACE_CREDENTIAL_UNAVAILABLE",
        "FACE_CREDENTIALS_UNAVAILABLE",
    }
    if token in service_tokens:
        return "FACE_SERVICE_UNAVAILABLE"
    return "FACE_AUTH_FAILED"


def pack_face_templates(templates: list[bytes]) -> bytes:
    """Pack 1–3 embeddings into one ciphertext payload (multi-angle gallery)."""
    if not templates or len(templates) > 3:
        raise ValueError("FACE_TEMPLATE_INVALID")
    if len(templates) == 1:
        return templates[0]
    parts = [bytearray(_BUNDLE_MAGIC), bytes([len(templates)])]
    payload = bytearray()
    for template in templates:
        if len(template) != _SFACE_EMBEDDING_SIZE * 4:
            raise ValueError("FACE_TEMPLATE_INVALID")
        payload.extend(len(template).to_bytes(2, "big"))
        payload.extend(template)
    parts.append(payload)
    return b"".join(parts)


def unpack_face_templates(blob: bytes) -> list[bytes]:
    """Unpack a gallery blob; legacy single templates remain a one-item list."""
    if not blob:
        raise ValueError("FACE_TEMPLATE_INVALID")
    if not blob.startswith(_BUNDLE_MAGIC):
        return [blob]
    count = blob[len(_BUNDLE_MAGIC)]
    offset = len(_BUNDLE_MAGIC) + 1
    templates: list[bytes] = []
    for _ in range(count):
        if offset + 2 > len(blob):
            raise ValueError("FACE_TEMPLATE_INVALID")
        size = int.from_bytes(blob[offset : offset + 2], "big")
        offset += 2
        if size <= 0 or offset + size > len(blob):
            raise ValueError("FACE_TEMPLATE_INVALID")
        templates.append(blob[offset : offset + size])
        offset += size
    if not templates:
        raise ValueError("FACE_TEMPLATE_INVALID")
    return templates


def score_probe_against_gallery(probe: bytes, gallery: list[bytes]) -> float:
    """Best cosine against any enrolled angle; used before per-frame min aggregate."""
    if not gallery:
        raise ValueError("FACE_TEMPLATE_INVALID")
    return max(face_template_similarity(probe, item) for item in gallery)


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


def ensure_face_frame_quality(image_bytes: bytes) -> dict[str, float]:
    """Reject only clearly unusable webcam frames before face detection.

    Raises ``ValueError("FACE_FRAME_LOW_QUALITY")`` when the frame is too
    small for a stable SFace crop or almost entirely dark/clipped.  Everything
    face-specific (face present, exactly one subject, size, pose, crop blur)
    is enforced downstream by YuNet + ``assess_face_frame_geometry``.
    """
    image = _decode_face_image(image_bytes)
    height, width = image.shape[:2]
    if (
        min(width, height) < FACE_FRAME_MIN_SIDE
        or max(width, height) < FACE_FRAME_MIN_LONG_SIDE
    ):
        raise ValueError("FACE_FRAME_LOW_QUALITY")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    mean_luminance = float(gray.mean())
    if not FACE_FRAME_MIN_MEAN_LUMINANCE <= mean_luminance <= FACE_FRAME_MAX_MEAN_LUMINANCE:
        raise ValueError("FACE_FRAME_LOW_QUALITY")
    return {
        "width": float(width),
        "height": float(height),
        "mean_luminance": mean_luminance,
    }


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


def _estimate_yaw_from_yunet(face: np.ndarray) -> float:
    """Rough yaw in [-1, 1] from nose offset inside the YuNet box (mirrored-safe)."""
    x, _y, width, _height = float(face[0]), float(face[1]), float(face[2]), float(face[3])
    if width <= 1:
        return 0.0
    nose_x = float(face[8])
    center_x = x + width / 2.0
    return float(np.clip((nose_x - center_x) / (width / 2.0), -1.0, 1.0))


def _face_area_ratio(face: np.ndarray, image: np.ndarray) -> float:
    height, width = image.shape[:2]
    area = max(1.0, float(width) * float(height))
    return float(face[2]) * float(face[3]) / area


def _face_crop_blur_variance(image: np.ndarray, face: np.ndarray) -> float:
    x, y, width, height = (int(face[0]), int(face[1]), int(face[2]), int(face[3]))
    x2 = min(image.shape[1], x + width)
    y2 = min(image.shape[0], y + height)
    x = max(0, x)
    y = max(0, y)
    crop = image[y:y2, x:x2]
    if crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def assess_face_frame_geometry(
    image: np.ndarray,
    face: np.ndarray,
    *,
    enforce: bool = True,
) -> dict[str, float]:
    """Reject frames that are unlikely to yield a stable identity embedding."""
    yaw = _estimate_yaw_from_yunet(face)
    area_ratio = _face_area_ratio(face, image)
    blur = _face_crop_blur_variance(image, face)
    if enforce:
        if area_ratio < FACE_AREA_RATIO_MIN:
            raise ValueError("FACE_TOO_SMALL")
        if area_ratio > FACE_AREA_RATIO_MAX:
            raise ValueError("FACE_TOO_LARGE")
        if abs(yaw) > FACE_YAW_ABS_MAX:
            raise ValueError("FACE_POSE_EXTREME")
        if blur < FACE_CROP_BLUR_MIN:
            raise ValueError("FACE_BLURRY")
    return {"yaw": yaw, "face_area_ratio": area_ratio, "face_blur_variance": blur}


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


def extract_face_template(
    image_bytes: bytes,
    *,
    enforce_geometry: bool = True,
) -> tuple[bytes, dict[str, Any]]:
    """Detect one face and derive a local SFace embedding (v3)."""
    image = _decode_face_image(image_bytes)
    recognizer = _sface_recognizer()
    geometry: dict[str, float] = {"yaw": 0.0, "face_area_ratio": 0.0, "face_blur_variance": 0.0}
    try:
        face = _detect_single_face_yunet(image)
        geometry = assess_face_frame_geometry(image, face, enforce=enforce_geometry)
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
        crop = image[top:bottom, left:right]
        if enforce_geometry:
            area_ratio = float(crop.shape[0] * crop.shape[1]) / float(
                image.shape[0] * image.shape[1]
            )
            if area_ratio < FACE_AREA_RATIO_MIN:
                raise ValueError("FACE_TOO_SMALL") from None
            if area_ratio > FACE_AREA_RATIO_MAX:
                raise ValueError("FACE_TOO_LARGE") from None
            blur = float(
                cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
            )
            if blur < FACE_CROP_BLUR_MIN:
                raise ValueError("FACE_BLURRY") from None
            geometry = {
                "yaw": 0.0,
                "face_area_ratio": area_ratio,
                "face_blur_variance": blur,
            }
        aligned = cv2.resize(
            crop,
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
        "yaw": geometry["yaw"],
        "face_area_ratio": geometry["face_area_ratio"],
        "face_blur_variance": geometry["face_blur_variance"],
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


def check_face_liveness(
    templates: list[bytes],
    yaws: list[float] | None = None,
) -> None:
    """Require a short one-subject motion + head-turn sequence (motion-sequence-v3).

    Still a deterministic local OpenCV heuristic, not production-grade anti-spoofing.
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
    if yaws is not None:
        if len(yaws) != len(templates):
            raise ValueError("FACE_LIVENESS_FAILED")
        if max(yaws) - min(yaws) < FACE_YAW_SPAN_MIN:
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
