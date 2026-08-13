"""Unit tests for the local OCR / barcode engines.

No paddle/opencv model runs here: engine logic is exercised through injected
functions, keeping CI free of heavy dependencies while covering the OCR-first
merge rules, region math, checksum rules and degraded modes.
"""

from __future__ import annotations

from ai.vision.evidence_pipeline import EvidenceRegion, PackageRegionProposal
from ai.vision.local_ocr import (
    LocalBarcodeDecoder,
    LocalPaddleOCR,
    gtin_checksum_valid,
    quad_to_region,
)


def _quad(x: float, y: float, width: float, height: float) -> list[list[float]]:
    return [[x, y], [x + width, y], [x + width, y + height], [x, y + height]]


def _paddle_line(text: str, confidence: float, quad: list[list[float]]) -> list:
    return [quad, (text, confidence)]


def test_quad_to_region_bounding_box() -> None:
    region = quad_to_region([[10, 20], [110, 25], [108, 60], [12, 58]])
    assert region is not None
    assert region.x == 10 and region.y == 20
    assert region.width == 100 and region.height == 40
    assert quad_to_region("not-points") is None
    assert quad_to_region([[5, 5], [5, 5], [5, 5], [5, 5]]) is None


def test_gtin_checksum_rules() -> None:
    assert gtin_checksum_valid("4006381333931") is True  # valid EAN-13
    assert gtin_checksum_valid("4006381333932") is False  # wrong check digit
    assert gtin_checksum_valid("96385074") is True  # valid EAN-8
    assert gtin_checksum_valid("https://trace.example/qr") is None  # not a GTIN
    assert gtin_checksum_valid("12345") is None  # implausible length


def test_ocr_full_image_tokens_have_regions_and_stable_ids() -> None:
    lines = [
        _paddle_line("演示药甲片", 0.98, _quad(40, 30, 200, 42)),
        _paddle_line("0.25g×24片", 0.91, _quad(40, 90, 160, 30)),
        _paddle_line("  ", 0.5, _quad(0, 0, 10, 10)),  # blank text dropped
    ]
    engine = LocalPaddleOCR(
        run_batch_fn=lambda path, rects: {"full": lines, "crops": []}
    )
    tokens = engine.recognize("demo.png")
    assert [token.id for token in tokens] == ["ocr-1", "ocr-2"]
    assert tokens[0].raw_value == "演示药甲片"
    assert tokens[0].region is not None and tokens[0].region.x == 40
    assert tokens[0].engine_version == "injected-test-ocr"
    assert 0 <= tokens[0].confidence <= 1


def test_ocr_crop_tokens_offset_and_deduplicated() -> None:
    full_lines = [_paddle_line("演示药甲片", 0.98, _quad(40, 30, 200, 42))]
    crop_lines = [
        _paddle_line("演示药甲片", 0.95, _quad(20, 10, 200, 42)),  # duplicate
        _paddle_line("批号A1B2C3", 0.88, _quad(20, 80, 150, 28)),  # new evidence
    ]
    seen_rects: list[list[dict]] = []

    def run_batch(path: str, rects: list[dict]) -> dict:
        seen_rects.append(rects)
        return {"full": full_lines, "crops": [crop_lines]}

    engine = LocalPaddleOCR(run_batch_fn=run_batch)
    proposal = PackageRegionProposal(
        id="yolo-1",
        label="medicine_box",
        region=EvidenceRegion(x=20, y=20, width=400, height=300),
        confidence=0.9,
        model_version="yolo-test",
    )
    tokens = engine.recognize("demo.png", [proposal])

    assert seen_rects == [[{"x": 20, "y": 20, "width": 400, "height": 300}]]
    values = [token.raw_value for token in tokens]
    assert values == ["演示药甲片", "批号A1B2C3"]
    assert tokens[0].id == "ocr-1"  # full-image token wins over the duplicate
    batch = tokens[1]
    assert batch.id == "ocr-c1-2"
    # crop-local (20, 80) offset by the proposal origin (20, 20)
    assert batch.region is not None
    assert batch.region.x == 40 and batch.region.y == 100


def test_ocr_worker_failure_degrades_to_empty() -> None:
    def boom(path: str, rects: list[dict]) -> dict:
        raise RuntimeError("worker exited 3221225477")

    assert LocalPaddleOCR(run_batch_fn=boom).recognize("demo.png") == []


def test_ocr_unreadable_image_degrades_to_empty() -> None:
    engine = LocalPaddleOCR(
        run_batch_fn=lambda path, rects: {
            "error": "IMAGE_UNREADABLE",
            "full": [],
            "crops": [],
        }
    )
    assert engine.recognize("不存在的图.png") == []


def test_worker_clamp_rect_bounds() -> None:
    from ai.vision._paddle_worker import clamp_rect

    assert clamp_rect({"x": -5, "y": 10, "width": 100, "height": 50}, 80, 40) == (
        0,
        10,
        80,
        40,
    )
    assert clamp_rect({"x": 70, "y": 30, "width": 5, "height": 5}, 80, 40) is None


def test_barcode_candidates_formats_and_checksum_confidence() -> None:
    detections = [
        ("4006381333931", "EAN_13", _quad(10, 10, 120, 40)),
        ("https://trace.example/qr", "QR", _quad(200, 10, 80, 80)),
        ("4006381333932", "EAN_13", None),  # wrong checksum, no region
    ]
    decoder = LocalBarcodeDecoder(detect_fn=lambda path: detections)
    candidates = decoder.decode("demo.png")
    assert [candidate.id for candidate in candidates] == ["code-1", "code-2", "code-3"]
    ean = candidates[0]
    assert ean.format == "EAN-13" and ean.checksum_valid is True
    assert ean.confidence == 0.95 and ean.decode_valid is True
    qr = candidates[1]
    assert qr.format == "QR" and qr.checksum_valid is None and qr.confidence == 0.8
    bad = candidates[2]
    assert bad.checksum_valid is False and bad.region is None


def test_barcode_detect_failure_degrades_to_empty() -> None:
    def boom(path):
        raise RuntimeError("decoder crashed")

    assert LocalBarcodeDecoder(detect_fn=boom).decode("demo.png") == []
