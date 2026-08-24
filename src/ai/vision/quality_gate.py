"""Local OpenCV quality gate used before OCR and detection.

The module never identifies a medicine and never mutates or stores the source
image.  Its thresholds are a demo baseline until HCT-201 provides an approved
fixed quality set for calibration.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

SCHEMA_VERSION = "vision-quality-result-v1"
DEFAULT_CONFIG_VERSION = "opencv-quality-demo-v2-lenient-exposure"


@dataclass(frozen=True)
class QualityThresholds:
    min_width: int = 640
    min_height: int = 480
    min_blur_variance: float = 80.0
    min_mean_luminance: float = 45.0
    # White cartons and white studio backgrounds are common.  Exposure is
    # therefore only a hard failure when the whole image is very bright or a
    # large share of pixels is clipped; ordinary bright packaging remains
    # eligible for OCR.
    max_mean_luminance: float = 220.0
    max_dark_ratio: float = 0.45
    max_bright_ratio: float = 0.60
    max_glare_ratio: float = 0.35
    min_edge_density: float = 0.005
    min_subject_area_ratio: float = 0.08
    max_border_touch_ratio: float = 0.50
    config_version: str = DEFAULT_CONFIG_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FrameInput:
    index: int
    timestamp_ms: int
    image: np.ndarray


_RETAKE_PROMPTS = {
    "IMAGE_TOO_SMALL": "请靠近药盒重新拍摄，并保持完整包装在画面内。",
    "BLURRY": "画面较模糊，请稳定设备并重新对焦。",
    "TOO_DARK": "光线不足，请增加均匀照明后重拍。",
    "TOO_BRIGHT": "画面过亮，请降低曝光或避开强光。",
    "TOO_MANY_DARK_PIXELS": "暗部过多，请调整角度和补光。",
    "TOO_MANY_BRIGHT_PIXELS": "亮部过多，请降低曝光后重拍。",
    "GLARE": "检测到明显反光，请倾斜药盒或移动光源。",
    "NO_TARGET": "未找到足够清晰的主体，请将单个药盒放在画面中央。",
    "TARGET_TOO_SMALL": "药盒在画面中占比过小，请靠近后重拍。",
    "SUBJECT_CROPPED": "主体可能贴边或被裁切，请保留完整包装边缘。",
}


def decode_image(content: bytes) -> np.ndarray:
    """Decode image bytes locally and reject unsupported/corrupt content."""
    if not content:
        raise ValueError("IMAGE_DECODE_FAILED")
    encoded = np.frombuffer(content, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ValueError("IMAGE_DECODE_FAILED")
    return image


def _metric(
    value: float,
    *,
    passed: bool,
    unit: str,
    threshold: dict[str, float | int],
) -> dict[str, Any]:
    return {
        "value": round(float(value), 6),
        "unit": unit,
        "threshold": threshold,
        "passed": bool(passed),
    }


def _find_subject(gray: np.ndarray) -> tuple[tuple[int, int, int, int] | None, np.ndarray | None]:
    edges = cv2.Canny(gray, 50, 150)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    joined = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, None

    image_area = gray.shape[0] * gray.shape[1]
    candidates: list[tuple[float, np.ndarray]] = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        box_area = width * height
        if box_area >= image_area * 0.005:
            candidates.append((float(box_area), contour))
    if not candidates:
        return None, None

    contour = max(candidates, key=lambda item: item[0])[1]
    return cv2.boundingRect(contour), contour


def _ordered_quad(points: np.ndarray) -> np.ndarray:
    points = points.astype(np.float32)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).reshape(-1)
    return np.array(
        [
            points[np.argmin(sums)],
            points[np.argmin(differences)],
            points[np.argmax(sums)],
            points[np.argmax(differences)],
        ],
        dtype=np.float32,
    )


def _perspective_quad(contour: np.ndarray | None) -> list[list[float]] | None:
    if contour is None:
        return None
    perimeter = cv2.arcLength(contour, True)
    approximation = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
    if len(approximation) != 4:
        return None
    ordered = _ordered_quad(approximation.reshape(4, 2))
    return [[round(float(x), 2), round(float(y), 2)] for x, y in ordered]


def four_point_transform(image: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Return a perspective-corrected copy without mutating *image*."""
    if image is None or image.size == 0:
        raise ValueError("IMAGE_EMPTY")
    if np.asarray(quad).shape != (4, 2):
        raise ValueError("PERSPECTIVE_QUAD_INVALID")

    top_left, top_right, bottom_right, bottom_left = _ordered_quad(np.asarray(quad))
    width = max(
        int(round(np.linalg.norm(bottom_right - bottom_left))),
        int(round(np.linalg.norm(top_right - top_left))),
    )
    height = max(
        int(round(np.linalg.norm(top_right - bottom_right))),
        int(round(np.linalg.norm(top_left - bottom_left))),
    )
    if width < 2 or height < 2:
        raise ValueError("PERSPECTIVE_QUAD_TOO_SMALL")
    destination = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(
        np.array([top_left, top_right, bottom_right, bottom_left], dtype=np.float32),
        destination,
    )
    return cv2.warpPerspective(image.copy(), matrix, (width, height))


def assess_image(
    image: np.ndarray,
    *,
    source_id: str,
    thresholds: QualityThresholds | None = None,
) -> dict[str, Any]:
    """Calculate deterministic quality evidence for one BGR image."""
    thresholds = thresholds or QualityThresholds()
    if image is None or image.size == 0 or image.ndim not in (2, 3):
        raise ValueError("IMAGE_EMPTY")

    source = image.copy()
    gray = source if source.ndim == 2 else cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    blur_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    mean_luminance = float(gray.mean())
    dark_ratio = float(np.mean(gray <= 30))
    bright_ratio = float(np.mean(gray >= 245))
    hsv = cv2.cvtColor(source, cv2.COLOR_BGR2HSV) if source.ndim == 3 else None
    glare_ratio = (
        float(np.mean((hsv[:, :, 2] >= 250) & (hsv[:, :, 1] <= 45)))
        if hsv is not None
        else bright_ratio
    )
    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(np.count_nonzero(edges) / edges.size)
    subject_box, contour = _find_subject(gray)

    subject_area_ratio = 0.0
    border_touch_ratio = 0.0
    orientation_degrees = 0.0
    if subject_box is not None and contour is not None:
        x, y, box_width, box_height = subject_box
        subject_area_ratio = float((box_width * box_height) / (width * height))
        margin = max(2, round(min(width, height) * 0.01))
        border_touches = sum(
            (
                x <= margin,
                y <= margin,
                x + box_width >= width - margin,
                y + box_height >= height - margin,
            )
        )
        border_touch_ratio = border_touches / 4.0
        angle = float(cv2.minAreaRect(contour)[2])
        orientation_degrees = angle + 90.0 if angle < -45.0 else angle

    size_passed = width >= thresholds.min_width and height >= thresholds.min_height
    blur_passed = blur_variance >= thresholds.min_blur_variance
    # A white carton can legitimately make the global mean bright.  Use a
    # small, deterministic detail proxy before rejecting exposure: visible
    # dark print/edges inside a sufficiently large subject means OCR still
    # has usable structure.  A flat bright frame remains a RETAKE.
    readable_detail = (
        edge_density >= max(thresholds.min_edge_density * 2.0, 0.01)
        and subject_area_ratio >= thresholds.min_subject_area_ratio * 2.0
        and dark_ratio >= 0.005
    )
    luminance_passed = (
        thresholds.min_mean_luminance <= mean_luminance <= thresholds.max_mean_luminance
        or readable_detail
    )
    dark_passed = dark_ratio <= thresholds.max_dark_ratio
    bright_passed = bright_ratio <= thresholds.max_bright_ratio or readable_detail
    glare_passed = glare_ratio <= thresholds.max_glare_ratio or readable_detail
    edge_passed = edge_density >= thresholds.min_edge_density
    subject_passed = subject_area_ratio >= thresholds.min_subject_area_ratio
    border_passed = border_touch_ratio <= thresholds.max_border_touch_ratio

    metrics = {
        "width": _metric(
            width,
            passed=width >= thresholds.min_width,
            unit="px",
            threshold={"min": thresholds.min_width},
        ),
        "height": _metric(
            height,
            passed=height >= thresholds.min_height,
            unit="px",
            threshold={"min": thresholds.min_height},
        ),
        "blur_variance": _metric(
            blur_variance,
            passed=blur_passed,
            unit="laplacian_variance",
            threshold={"min": thresholds.min_blur_variance},
        ),
        "mean_luminance": _metric(
            mean_luminance,
            passed=luminance_passed,
            unit="gray_0_255",
            threshold={
                "min": thresholds.min_mean_luminance,
                "max": thresholds.max_mean_luminance,
            },
        ),
        "dark_ratio": _metric(
            dark_ratio,
            passed=dark_passed,
            unit="ratio",
            threshold={"max": thresholds.max_dark_ratio},
        ),
        "bright_ratio": _metric(
            bright_ratio,
            passed=bright_passed,
            unit="ratio",
            threshold={"max": thresholds.max_bright_ratio},
        ),
        "glare_ratio": _metric(
            glare_ratio,
            passed=glare_passed,
            unit="ratio_proxy",
            threshold={"max": thresholds.max_glare_ratio},
        ),
        "readable_detail": _metric(
            1.0 if readable_detail else 0.0,
            passed=readable_detail,
            unit="boolean_proxy",
            threshold={"min": 1},
        ),
        "edge_density": _metric(
            edge_density,
            passed=edge_passed,
            unit="ratio",
            threshold={"min": thresholds.min_edge_density},
        ),
        "subject_area_ratio": _metric(
            subject_area_ratio,
            passed=subject_passed,
            unit="ratio_proxy",
            threshold={"min": thresholds.min_subject_area_ratio},
        ),
        "border_touch_ratio": _metric(
            border_touch_ratio,
            passed=border_passed,
            unit="ratio_proxy",
            threshold={"max": thresholds.max_border_touch_ratio},
        ),
    }

    reasons: list[str] = []
    if not size_passed:
        reasons.append("IMAGE_TOO_SMALL")
    if not blur_passed:
        reasons.append("BLURRY")
    if mean_luminance < thresholds.min_mean_luminance:
        reasons.append("TOO_DARK")
    elif mean_luminance > thresholds.max_mean_luminance and not readable_detail:
        reasons.append("TOO_BRIGHT")
    if not dark_passed:
        reasons.append("TOO_MANY_DARK_PIXELS")
    # Bright packaging with readable print is allowed through.  Only a
    # heavily clipped frame without that detail proxy is blocked.
    if not bright_passed and not readable_detail:
        reasons.append("TOO_MANY_BRIGHT_PIXELS")
    if not glare_passed and not readable_detail:
        reasons.append("GLARE")
    if not edge_passed or subject_box is None:
        reasons.append("NO_TARGET")
    elif not subject_passed:
        reasons.append("TARGET_TOO_SMALL")
    if subject_box is not None and not border_passed:
        reasons.append("SUBJECT_CROPPED")
    reasons = list(dict.fromkeys(reasons))

    quad = _perspective_quad(contour)
    return {
        "schema_version": SCHEMA_VERSION,
        "config_version": thresholds.config_version,
        "media_type": "image",
        "decision": "PASS" if not reasons else "RETAKE",
        "allow_downstream": not reasons,
        "source": {
            "source_id": source_id,
            "sha256": hashlib.sha256(source.tobytes()).hexdigest(),
            "unchanged": True,
        },
        "metrics": metrics,
        "thresholds": thresholds.as_dict(),
        "reasons": reasons,
        "retake_prompts": [_RETAKE_PROMPTS[reason] for reason in reasons],
        "correction": {
            "orientation_degrees": round(orientation_degrees, 3),
            "perspective_quad": quad,
            "available": quad is not None,
            "applied": False,
        },
        "limitations": [
            "subject_area_ratio and border_touch_ratio are geometric proxies",
            "thresholds require calibration on an approved fixed quality set",
        ],
    }


def _difference_hash(image: np.ndarray, hash_size: int = 8) -> int:
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)
    differences = resized[:, 1:] > resized[:, :-1]
    value = 0
    for bit in differences.flatten():
        value = (value << 1) | int(bit)
    return value


def _hamming_distance(first: int, second: int) -> int:
    return (first ^ second).bit_count()


def select_video_frames(
    frames: Iterable[FrameInput],
    *,
    sample_interval_ms: int = 1000,
    duplicate_hamming_threshold: int = 4,
    thresholds: QualityThresholds | None = None,
    max_selected_frames: int = 60,
) -> list[dict[str, Any]]:
    """Select timestamped frames in input order and remove near duplicates."""
    if sample_interval_ms < 0 or max_selected_frames < 1:
        raise ValueError("VIDEO_SAMPLING_CONFIG_INVALID")
    thresholds = thresholds or QualityThresholds()
    selected: list[dict[str, Any]] = []
    selected_hashes: list[int] = []
    next_timestamp = 0

    for frame in frames:
        if frame.timestamp_ms < next_timestamp:
            continue
        next_timestamp = frame.timestamp_ms + sample_interval_ms
        frame_hash = _difference_hash(frame.image)
        if any(
            _hamming_distance(frame_hash, prior) <= duplicate_hamming_threshold
            for prior in selected_hashes
        ):
            continue
        assessment = assess_image(
            frame.image,
            source_id=f"frame:{frame.index}",
            thresholds=thresholds,
        )
        selected_hashes.append(frame_hash)
        selected.append(
            {
                "frame_index": frame.index,
                "timestamp_ms": frame.timestamp_ms,
                "dhash": f"{frame_hash:016x}",
                "decision": assessment["decision"],
                "allow_downstream": assessment["allow_downstream"],
                "reasons": assessment["reasons"],
                "metrics": assessment["metrics"],
            }
        )
        if len(selected) >= max_selected_frames:
            break
    return selected


def assess_video_file(
    path: Path,
    *,
    source_id: str,
    sample_interval_ms: int = 1000,
    max_selected_frames: int = 60,
    thresholds: QualityThresholds | None = None,
    max_duration_ms: int | None = None,
) -> dict[str, Any]:
    """Decode a local video, sample frames, and return metadata without pixels."""
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise ValueError("VIDEO_DECODE_FAILED")
    if max_duration_ms is not None:
        frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        frame_rate = capture.get(cv2.CAP_PROP_FPS)
        if frame_count > 0 and frame_rate > 0 and frame_count / frame_rate * 1000 > max_duration_ms:
            capture.release()
            raise ValueError("VIDEO_DURATION_EXCEEDED")
    decoded_frames = 0
    sampled_count = 0
    max_sampled_frames = max_selected_frames * 4
    next_timestamp = 0
    last_timestamp_ms = 0

    def sampled_frames() -> Iterable[FrameInput]:
        nonlocal decoded_frames, sampled_count, next_timestamp, last_timestamp_ms
        try:
            while sampled_count < max_sampled_frames:
                ok, image = capture.read()
                if not ok:
                    break
                frame_index = decoded_frames
                decoded_frames += 1
                timestamp_ms = int(round(capture.get(cv2.CAP_PROP_POS_MSEC)))
                if timestamp_ms < next_timestamp:
                    continue
                sampled_count += 1
                last_timestamp_ms = max(last_timestamp_ms, timestamp_ms)
                next_timestamp = timestamp_ms + sample_interval_ms
                yield FrameInput(
                    index=frame_index,
                    timestamp_ms=timestamp_ms,
                    image=image,
                )
        finally:
            capture.release()

    frame_stream = sampled_frames()
    try:
        selected = select_video_frames(
            frame_stream,
            sample_interval_ms=0,
            thresholds=thresholds,
            max_selected_frames=max_selected_frames,
        )
    finally:
        frame_stream.close()
    if decoded_frames == 0:
        raise ValueError("VIDEO_DECODE_FAILED")
    if max_duration_ms is not None and last_timestamp_ms > max_duration_ms:
        # Streams without trustworthy metadata still get a hard duration bound.
        raise ValueError("VIDEO_DURATION_EXCEEDED")
    usable = [frame for frame in selected if frame["allow_downstream"]]
    reasons = [] if usable else ["NO_USABLE_FRAME"]
    return {
        "schema_version": SCHEMA_VERSION,
        "config_version": (thresholds or QualityThresholds()).config_version,
        "media_type": "video",
        "decision": "PASS" if usable else "RETAKE",
        "allow_downstream": bool(usable),
        "source": {
            "source_id": source_id,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "unchanged": True,
        },
        "metrics": {
            "decoded_frames": decoded_frames,
            "sampled_frames": sampled_count,
            "selected_frames": len(selected),
            "usable_frames": len(usable),
            "sample_interval_ms": sample_interval_ms,
            "sample_limit": max_sampled_frames,
        },
        "thresholds": (thresholds or QualityThresholds()).as_dict(),
        "reasons": reasons,
        "retake_prompts": (
            [] if usable else ["没有可用证据帧，请保持药盒稳定、居中并在均匀光线下重拍。"]
        ),
        "frames": selected,
        "limitations": [
            "video codec availability depends on the local OpenCV runtime",
            "thresholds require calibration on an approved fixed quality set",
        ],
    }
