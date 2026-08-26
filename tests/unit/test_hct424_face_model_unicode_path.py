"""HCT-424/HCT-425 regression: ONNX face models must load from Unicode paths.

Root cause of the HTTP 500 「Can't read ONNX file: C:\\...\\多模态医疗\\...」:
OpenCV's C++ file loader uses the ANSI narrow-character ``fopen`` on Windows,
so ``cv2.FaceRecognizerSF_create(str(path), "")`` and
``cv2.FaceDetectorYN_create(str(path), ...)`` fail whenever the repository
lives under a path containing non-ASCII characters (e.g. Chinese folder
names).  The raw ``cv2.error`` then escaped the route's RuntimeError/ValueError
handlers and surfaced as an HTTP 500 whose body leaked the full local Windows
path into the user's toast.

The fix reads the model bytes with Python I/O (Unicode-safe on every OS) and
hands OpenCV an in-memory buffer via the ``create(framework, bufferModel,
bufferConfig, ...)`` overloads, so no model path ever reaches an OpenCV file
API.  Any residual OpenCV load failure is mapped to the stable
``FACE_DETECTOR_UNAVAILABLE`` service code.
"""

from __future__ import annotations

import shutil
from functools import partial
from pathlib import Path

import cv2
import numpy as np
import pytest

from app import face_credentials
from app.config import get_settings
from app.face_credentials import (
    _read_onnx_model_bytes,
    _sface_recognizer,
    _yunet_detector,
    _yunet_model_buffer,
    ensure_face_models,
    face_models_ready,
)

_YUNET = "face_detection_yunet_2023mar.onnx"
_SFACE = "face_recognition_sface_2021dec.onnx"
_LOCAL_MODEL_DIR = Path("models/face")
# Mirrors the user-visible failure: a repository checkout under a Chinese path.
_UNICODE_DIR_NAME = "多模态医疗模型缓存"

_WINDOWS_STYLE_CV2_ERROR = (
    "OpenCV(4.14.0) D:\\a\\opencv-python\\opencv-python\\opencv\\modules\\dnn"
    "\\src\\onnx\\onnx_importer.cpp:277: error: (-5:Bad argument) Can't read "
    "ONNX file: C:\\Users\\demo\\多模态医疗\\issedu_ysu2026_3709\\models\\face"
    "\\face_recognition_sface_2021dec.onnx in function "
    "'cv::dnn::dnn4_v20260709::ONNXImporter::ONNXImporter'"
)


def _clear_model_caches() -> None:
    get_settings.cache_clear()
    _sface_recognizer.cache_clear()
    _yunet_model_buffer.cache_clear()


@pytest.fixture()
def unicode_model_dir(tmp_path, monkeypatch) -> Path:
    """A FACE_MODEL_DIR whose path contains Chinese characters."""
    model_dir = tmp_path / _UNICODE_DIR_NAME
    model_dir.mkdir()
    monkeypatch.setenv("FACE_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("FACE_MODEL_AUTO_DOWNLOAD", "false")
    _clear_model_caches()
    yield model_dir
    _clear_model_caches()


def _copy_real_models_or_skip(destination: Path) -> None:
    if not (_LOCAL_MODEL_DIR / _SFACE).is_file() or not (_LOCAL_MODEL_DIR / _YUNET).is_file():
        pytest.skip("local YuNet/SFace models unavailable; run scripts/ensure_face_models.py")
    for name in (_YUNET, _SFACE):
        shutil.copy(_LOCAL_MODEL_DIR / name, destination / name)


def test_face_models_load_and_infer_from_unicode_path_directory(unicode_model_dir) -> None:
    """Real YuNet + SFace weights must load from a Chinese-character directory."""
    _copy_real_models_or_skip(unicode_model_dir)

    assert face_models_ready()
    yunet, sface = ensure_face_models()
    assert _UNICODE_DIR_NAME in str(yunet) and _UNICODE_DIR_NAME in str(sface)

    recognizer = _sface_recognizer()
    detector = _yunet_detector(640, 480)
    assert recognizer is not None
    assert detector is not None

    # End-to-end embedding from an aligned 112x112 crop proves the DNN graph
    # actually loaded (not just that construction did not throw).
    rng = np.random.default_rng(11)
    aligned = rng.integers(0, 255, (112, 112, 3), dtype=np.uint8)
    feature = recognizer.feature(aligned)
    assert feature is not None and feature.size == 128


def test_opencv_receives_model_bytes_never_a_filesystem_path(
    unicode_model_dir,
    monkeypatch,
) -> None:
    """The loaders must use the buffer overloads: no path string reaches OpenCV."""
    for name in (_YUNET, _SFACE):
        (unicode_model_dir / name).write_bytes(b"fake-onnx-bytes-for-signature-check")

    recorded: list[tuple] = []

    def _recording_sface_create(*args):
        recorded.append(("sface", args))
        return object()

    def _recording_yunet_create(*args):
        recorded.append(("yunet", args))
        return object()

    monkeypatch.setattr(cv2, "FaceRecognizerSF_create", _recording_sface_create)
    monkeypatch.setattr(cv2, "FaceDetectorYN_create", _recording_yunet_create)

    _sface_recognizer()
    _yunet_detector(640, 480)

    assert {name for name, _ in recorded} == {"sface", "yunet"}
    for _, args in recorded:
        framework, buffer, config = args[0], args[1], args[2]
        assert framework == "onnx"
        assert isinstance(buffer, np.ndarray) and buffer.dtype == np.uint8
        assert not isinstance(config, str)
        # The critical property: no argument carries a filesystem path.
        for argument in args:
            assert not (isinstance(argument, str) and _UNICODE_DIR_NAME in argument)


@pytest.mark.parametrize("loader", ["sface", "yunet"])
def test_onnx_load_failure_maps_to_stable_service_code(
    unicode_model_dir,
    monkeypatch,
    loader: str,
) -> None:
    """A cv2.error during model creation becomes FACE_DETECTOR_UNAVAILABLE.

    The RuntimeError message is the stable code only — the raw C++ text with
    the full Windows path must never be the user-facing detail.
    """
    for name in (_YUNET, _SFACE):
        (unicode_model_dir / name).write_bytes(b"corrupt-model-bytes")

    def _windows_style_failure(*_args):
        raise cv2.error(_WINDOWS_STYLE_CV2_ERROR)

    if loader == "sface":
        monkeypatch.setattr(cv2, "FaceRecognizerSF_create", _windows_style_failure)
        target = _sface_recognizer
    else:
        monkeypatch.setattr(cv2, "FaceDetectorYN_create", _windows_style_failure)
        target = partial(_yunet_detector, 640, 480)

    with pytest.raises(RuntimeError) as error:
        target()

    assert str(error.value) == "FACE_DETECTOR_UNAVAILABLE"
    assert "多模态医疗" not in str(error.value)
    assert "onnx" not in str(error.value).lower()


def test_missing_or_empty_model_file_maps_to_service_code(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="FACE_DETECTOR_UNAVAILABLE"):
        _read_onnx_model_bytes(tmp_path / "missing.onnx")

    empty = tmp_path / "empty.onnx"
    empty.write_bytes(b"")
    with pytest.raises(RuntimeError, match="FACE_DETECTOR_UNAVAILABLE"):
        _read_onnx_model_bytes(empty)


def test_extract_face_template_pipeline_works_from_unicode_model_dir(
    unicode_model_dir,
) -> None:
    """The full registration extraction path works with a Chinese FACE_MODEL_DIR.

    Uses a synthetic single-face frame; only asserts that model loading and
    inference succeed (identity quality is covered by the SFace sample test).
    """
    _copy_real_models_or_skip(unicode_model_dir)

    frame = _synthetic_face_jpeg()
    try:
        template, metadata = face_credentials.extract_face_template(
            frame,
            enforce_geometry=False,
        )
    except ValueError as exc:
        # The synthetic drawing may fall below detector confidence on some
        # OpenCV builds; a *detection* miss is acceptable here, a model-load
        # failure (RuntimeError/cv2.error) is not.
        assert str(exc) in {"FACE_NOT_FOUND", "FACE_MULTIPLE_SUBJECTS"}
        return
    assert len(template) == 128 * 4
    assert metadata["algorithm_version"] == "opencv-yunet-sface-v3"


def _synthetic_face_jpeg(width: int = 960, height: int = 540) -> bytes:
    rng = np.random.default_rng(7)
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
