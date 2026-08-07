from __future__ import annotations

import hashlib
import json
from pathlib import Path
from time import perf_counter, process_time
from typing import Any

import cv2
import numpy as np
import psutil

MIB = 1024 * 1024


def _rss_mib() -> float:
    return psutil.Process().memory_info().rss / MIB


def _cuda_device_count() -> int:
    try:
        return int(cv2.cuda.getCudaEnabledDeviceCount())
    except cv2.error:
        return 0


def _load_synthetic_grayscale(path: Path) -> np.ndarray:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("format") != "grayscale_u8":
        raise ValueError("Visual probe sample must use grayscale_u8 format")
    image = np.asarray(payload.get("pixels"), dtype=np.uint8)
    expected_shape = (int(payload.get("height", 0)), int(payload.get("width", 0)))
    if image.ndim != 2 or image.shape != expected_shape or not all(expected_shape):
        raise ValueError("Visual probe sample dimensions do not match its pixel matrix")
    return image


def probe_visual_sample(image_path: Path) -> dict[str, Any]:
    """Measure a synthetic image quality baseline without identifying its contents."""
    path = image_path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Visual probe sample does not exist: {path}")

    rss_before = _rss_mib()
    started = perf_counter()
    cpu_started = process_time()
    image = _load_synthetic_grayscale(path)

    brightness = float(np.mean(image))
    contrast = float(np.std(image))
    sharpness = float(cv2.Laplacian(image, cv2.CV_64F).var())
    elapsed_ms = (perf_counter() - started) * 1000
    cpu_elapsed_ms = (process_time() - cpu_started) * 1000
    rss_after = _rss_mib()

    checks = {
        "brightness_in_range": 20.0 <= brightness <= 235.0,
        "contrast_sufficient": contrast >= 10.0,
        "sharpness_sufficient": sharpness >= 10.0,
    }
    height, width = image.shape
    cuda_devices = _cuda_device_count()

    return {
        "probe": "opencv_visual_quality",
        "status": "ok" if all(checks.values()) else "review",
        "scope": "quality_gate_only",
        "sample": {
            "name": path.name,
            "synthetic": True,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
        "image": {"width": int(width), "height": int(height), "channels": 1},
        "checks": checks,
        "metrics": {
            "mean_brightness": round(brightness, 3),
            "contrast_stddev": round(contrast, 3),
            "sharpness_laplacian_variance": round(sharpness, 3),
        },
        "resources": {
            "elapsed_ms": round(elapsed_ms, 3),
            "cpu_elapsed_ms": round(cpu_elapsed_ms, 3),
            "rss_before_mib": round(rss_before, 3),
            "rss_after_mib": round(rss_after, 3),
            "rss_delta_mib": round(rss_after - rss_before, 3),
            "opencv_cuda_devices": cuda_devices,
            "execution_backend": "opencv_cuda" if cuda_devices else "cpu",
        },
        "versions": {"opencv": cv2.__version__, "numpy": np.__version__},
        "limitations": [
            "This probe measures image decoding and quality metrics only.",
            "It does not run YOLO, OCR, barcode matching, or medicine identification.",
        ],
    }
