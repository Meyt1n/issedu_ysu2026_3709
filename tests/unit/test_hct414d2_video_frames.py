"""HCT-414-D2 unit tests: video frame sampling and evidence merging."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from ai.vision.evidence_pipeline import EvidencePipelineRequest, OCRToken
from ai.vision.video_frames import decode_video_frames, merge_frame_requests


def _write_video(path: Path, frame_count: int, *, fps: int = 10) -> None:
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (640, 480)
    )
    assert writer.isOpened(), "mp4 codec unavailable in this OpenCV runtime"
    for index in range(frame_count):
        image = np.full((480, 640, 3), 110, dtype=np.uint8)
        cv2.putText(
            image,
            f"F{index:02d}",
            (240, 245),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.5,
            (20, 20, 20),
            4,
        )
        writer.write(image)
    writer.release()


def test_decode_video_frames_samples_by_interval_and_cap(tmp_path) -> None:
    video = tmp_path / "demo.mp4"
    _write_video(video, 30)  # 3 s at 10 fps

    frames = list(decode_video_frames(video, sample_interval_ms=500, max_frames=8))
    assert 1 < len(frames) <= 8
    timestamps = [frame.timestamp_ms for frame in frames]
    assert timestamps == sorted(timestamps)
    assert timestamps[0] == 0

    capped = list(decode_video_frames(video, sample_interval_ms=10, max_frames=3))
    assert len(capped) == 3

    single = list(decode_video_frames(video, sample_interval_ms=60_000, max_frames=8))
    assert len(single) == 1


def test_decode_video_frames_rejects_garbage_and_bad_config(tmp_path) -> None:
    garbage = tmp_path / "garbage.mp4"
    garbage.write_bytes(b"not a video at all")
    with pytest.raises(ValueError, match="VIDEO_DECODE_FAILED"):
        list(decode_video_frames(garbage))

    video = tmp_path / "demo.mp4"
    _write_video(video, 2)
    with pytest.raises(ValueError, match="VIDEO_SAMPLING_CONFIG_INVALID"):
        list(decode_video_frames(video, max_frames=0))


def test_merge_frame_requests_requires_frames() -> None:
    with pytest.raises(ValueError, match="VIDEO_FRAMES_REQUIRED"):
        merge_frame_requests([], run_id="worker-x")


def test_merge_frame_requests_prefixes_ids_and_sets_run_id() -> None:
    def frame_request(position: int) -> EvidencePipelineRequest:
        return EvidencePipelineRequest(
            ocr_tokens=[
                OCRToken(
                    id="ocr-1",
                    raw_value=f"text {position}",
                    confidence=0.9,
                    engine_version="e-v1",
                )
            ],
            ocr_engine_version="e-v1",
        )

    merged = merge_frame_requests(
        [frame_request(1), frame_request(2)],
        run_id="worker-video-run",
    )
    assert [token.id for token in merged.ocr_tokens] == ["f1-ocr-1", "f2-ocr-1"]
    assert merged.adapter_run_id == "worker-video-run"
