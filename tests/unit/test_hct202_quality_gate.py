from __future__ import annotations

import cv2
import numpy as np
import pytest
from ai.vision.quality_gate import (
    FrameInput,
    QualityThresholds,
    assess_image,
    assess_video_file,
    decode_image,
    four_point_transform,
    select_video_frames,
)


def _clear_subject() -> np.ndarray:
    image = np.full((480, 640, 3), 110, dtype=np.uint8)
    cv2.rectangle(image, (140, 90), (500, 390), (225, 225, 225), -1)
    cv2.rectangle(image, (140, 90), (500, 390), (20, 20, 20), 6)
    cv2.putText(image, "DEMO BOX", (185, 245), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (20, 20, 20), 4)
    return image


def _demo_thresholds() -> QualityThresholds:
    return QualityThresholds(
        min_width=320,
        min_height=240,
        min_blur_variance=20.0,
        min_mean_luminance=30.0,
        max_mean_luminance=235.0,
        max_dark_ratio=0.60,
        max_bright_ratio=0.60,
        max_glare_ratio=0.40,
        min_edge_density=0.002,
        min_subject_area_ratio=0.05,
        max_border_touch_ratio=0.75,
    )


def test_clear_synthetic_subject_passes_with_versioned_evidence() -> None:
    result = assess_image(
        _clear_subject(),
        source_id="synthetic-clear",
        thresholds=_demo_thresholds(),
    )

    assert result["decision"] == "PASS"
    assert result["allow_downstream"] is True
    assert result["schema_version"] == "vision-quality-result-v1"
    assert result["config_version"] == "opencv-quality-demo-v2-lenient-exposure"
    assert result["source"]["source_id"] == "synthetic-clear"
    assert result["source"]["unchanged"] is True
    assert "path" not in str(result).lower()
    assert result["metrics"]["blur_variance"]["passed"] is True


@pytest.mark.parametrize(
    ("image", "reason"),
    [
        (np.full((480, 640, 3), 5, dtype=np.uint8), "TOO_DARK"),
        (np.full((480, 640, 3), 255, dtype=np.uint8), "TOO_BRIGHT"),
        (np.full((100, 100, 3), 100, dtype=np.uint8), "IMAGE_TOO_SMALL"),
    ],
)
def test_bad_inputs_require_retake(image: np.ndarray, reason: str) -> None:
    result = assess_image(image, source_id="synthetic-bad", thresholds=_demo_thresholds())

    assert result["decision"] == "RETAKE"
    assert result["allow_downstream"] is False
    assert reason in result["reasons"]
    assert result["retake_prompts"]


def test_blur_is_rejected() -> None:
    blurred = cv2.GaussianBlur(_clear_subject(), (51, 51), 0)
    thresholds = _demo_thresholds()
    thresholds = QualityThresholds(**{**thresholds.as_dict(), "min_blur_variance": 100.0})

    result = assess_image(blurred, source_id="synthetic-blur", thresholds=thresholds)

    assert result["decision"] == "RETAKE"
    assert "BLURRY" in result["reasons"]


def test_bright_packaging_with_text_detail_is_not_rejected_as_overexposed() -> None:
    image = np.full((480, 640, 3), 238, dtype=np.uint8)
    cv2.rectangle(image, (110, 70), (530, 410), (250, 250, 250), -1)
    cv2.rectangle(image, (110, 70), (530, 410), (25, 25, 25), 6)
    cv2.putText(image, "MEDICINE", (170, 235), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (30, 30, 30), 4)

    result = assess_image(image, source_id="bright-white-packaging")

    assert result["decision"] == "PASS"
    assert "TOO_BRIGHT" not in result["reasons"]
    assert "TOO_MANY_BRIGHT_PIXELS" not in result["reasons"]
    assert "GLARE" not in result["reasons"]
    assert result["metrics"]["readable_detail"]["passed"] is True


def test_uniform_clipped_image_still_requires_retake() -> None:
    result = assess_image(
        np.full((480, 640, 3), 255, dtype=np.uint8),
        source_id="uniform-clipped",
    )

    assert result["decision"] == "RETAKE"
    assert "TOO_BRIGHT" in result["reasons"]


def test_decode_image_rejects_invalid_bytes() -> None:
    with pytest.raises(ValueError, match="IMAGE_DECODE_FAILED"):
        decode_image(b"not-an-image")


def test_four_point_transform_does_not_mutate_source() -> None:
    source = _clear_subject()
    before = source.copy()
    quad = np.array([[140, 90], [500, 90], [500, 390], [140, 390]], dtype=np.float32)

    corrected = four_point_transform(source, quad)

    assert corrected.shape[0] >= 299
    assert corrected.shape[1] >= 359
    assert np.array_equal(source, before)
    assert not np.shares_memory(source, corrected)


def test_video_sampling_and_dhash_dedup_are_deterministic() -> None:
    first = _clear_subject()
    duplicate = first.copy()
    gradient = np.tile(np.linspace(0, 255, 640, dtype=np.uint8), (480, 1))
    changed = cv2.cvtColor(gradient, cv2.COLOR_GRAY2BGR)
    frames = [
        FrameInput(index=0, timestamp_ms=0, image=first),
        FrameInput(index=1, timestamp_ms=400, image=duplicate),
        FrameInput(index=2, timestamp_ms=1100, image=duplicate),
        FrameInput(index=3, timestamp_ms=2200, image=changed),
    ]

    selected = select_video_frames(
        frames,
        sample_interval_ms=1000,
        duplicate_hamming_threshold=2,
        thresholds=_demo_thresholds(),
    )

    assert [frame["frame_index"] for frame in selected] == [0, 3]
    assert [frame["timestamp_ms"] for frame in selected] == [0, 2200]
    assert all("image" not in frame for frame in selected)


def test_video_decode_is_streamed_bounded_and_released(tmp_path, monkeypatch) -> None:
    class FakeCapture:
        def __init__(self) -> None:
            self.read_count = 0
            self.released = False

        def isOpened(self) -> bool:  # noqa: N802
            return True

        def read(self):
            self.read_count += 1
            if self.read_count > 100:
                return False, None
            image = _clear_subject()
            image[20:40, self.read_count : self.read_count + 20] = 255
            return True, image

        def get(self, _property: int) -> float:
            return float(self.read_count * 1000)

        def release(self) -> None:
            self.released = True

    capture = FakeCapture()
    monkeypatch.setattr(cv2, "VideoCapture", lambda _path: capture)
    video_path = tmp_path / "synthetic.mp4"
    video_path.write_bytes(b"synthetic-video-placeholder")

    result = assess_video_file(
        video_path,
        source_id="synthetic-video",
        sample_interval_ms=1000,
        max_selected_frames=2,
        thresholds=_demo_thresholds(),
    )

    assert capture.released is True
    assert result["metrics"]["sample_limit"] == 8
    assert result["metrics"]["sampled_frames"] <= 8
    assert len(result["frames"]) <= 2
    assert "path" not in str(result).lower()
