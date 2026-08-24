"""Video frame decoding and evidence merging for the resident vision worker.

HCT-414-D2.  The module keeps the video branch of ``scripts/vision_worker.py``
testable without the heavy local engines: frame sampling returns pixels for
the OCR/barcode/box adapters, and per-frame adapter outputs are merged into a
single ``EvidencePipelineRequest`` before signing.  It never identifies a
medicine, never mutates the source video and never persists frames — the
worker writes frames to a temp directory that is removed right after the
engines finish.  DEMO_ONLY until the HCT-201 fixed quality set is signed off.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import cv2

from ai.vision.evidence_pipeline import EvidencePipelineRequest
from ai.vision.quality_gate import FrameInput

# Mirror the Field(max_length=...) limits of EvidencePipelineRequest; the merge
# truncates to these so a signed request can never exceed the schema.
MAX_OCR_TOKENS = 512
MAX_BARCODES = 64
MAX_PACKAGE_REGIONS = 64
MAX_FIELD_PROPOSALS = 64


def decode_video_frames(
    path: Path,
    *,
    sample_interval_ms: int = 1000,
    max_frames: int = 8,
) -> Iterator[FrameInput]:
    """Yield at most ``max_frames`` sampled frames, keeping pixels for engines."""
    if sample_interval_ms < 0 or max_frames < 1:
        raise ValueError("VIDEO_SAMPLING_CONFIG_INVALID")
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise ValueError("VIDEO_DECODE_FAILED")
    decoded_frames = 0
    yielded = 0
    next_timestamp = 0
    try:
        while yielded < max_frames:
            ok, image = capture.read()
            if not ok:
                break
            frame_index = decoded_frames
            decoded_frames += 1
            timestamp_ms = int(round(capture.get(cv2.CAP_PROP_POS_MSEC)))
            if timestamp_ms < next_timestamp:
                continue
            next_timestamp = timestamp_ms + sample_interval_ms
            yielded += 1
            yield FrameInput(index=frame_index, timestamp_ms=timestamp_ms, image=image)
    finally:
        capture.release()
    if decoded_frames == 0:
        raise ValueError("VIDEO_DECODE_FAILED")


def merge_frame_requests(
    requests: list[EvidencePipelineRequest],
    *,
    run_id: str,
) -> EvidencePipelineRequest:
    """Merge per-frame adapter outputs into one request payload.

    Evidence ids get a ``f<N>-`` frame prefix so every token, barcode and
    region stays traceable to its source frame; ``FieldProposal
    .evidence_ids`` references are remapped with the same prefix.  Barcodes
    that repeat across frames keep only the highest-confidence copy.  Lists
    are truncated to the schema limits (later frames are dropped first).
    """
    if not requests:
        raise ValueError("VIDEO_FRAMES_REQUIRED")

    ocr_tokens: list[Any] = []
    package_regions: list[Any] = []
    field_proposals: list[Any] = []
    best_barcodes: dict[tuple[str, str], Any] = {}

    for position, request in enumerate(requests):
        prefix = f"f{position + 1}-"
        for token in request.ocr_tokens:
            token.id = f"{prefix}{token.id}"
            ocr_tokens.append(token)
        for region in request.package_regions:
            region.id = f"{prefix}{region.id}"
            package_regions.append(region)
        for proposal in request.field_proposals:
            proposal.evidence_ids = [f"{prefix}{ref}" for ref in proposal.evidence_ids]
            field_proposals.append(proposal)
        for barcode in request.barcodes:
            key = (barcode.raw_value, barcode.format)
            current = best_barcodes.get(key)
            if current is None or barcode.confidence > current.confidence:
                barcode.id = f"{prefix}{barcode.id}"
                best_barcodes[key] = barcode

    merged = requests[0].model_copy(deep=True)
    merged.ocr_tokens = ocr_tokens[:MAX_OCR_TOKENS]
    merged.barcodes = list(best_barcodes.values())[:MAX_BARCODES]
    merged.package_regions = package_regions[:MAX_PACKAGE_REGIONS]
    merged.field_proposals = field_proposals[:MAX_FIELD_PROPOSALS]
    merged.adapter_run_id = run_id
    return merged
