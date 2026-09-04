"""Local OCR and barcode engines for the family trusted domain.

These engines close the OCR-first loop of the HCT-201 field-extraction
contract without any cloud call: PaddleOCR (PP-OCRv4, cached locally) reads
the full image as the primary text-evidence channel, and OpenCV decodes
barcodes / QR codes as the independent code channel.

Governance boundaries (HCT-201 contract / AI-RAG spec):

* OCR of the full image is always the primary pass.  YOLO package proposals
  are only used to run an *additional* OCR pass on crops; crop tokens can add
  evidence but never replace or filter full-image tokens.
* Barcode decoding is a separate channel; OCR text is not promoted to a code
  value here (that fallback belongs to the server-side rules).
* Both engines degrade gracefully: a missing dependency or an inference
  failure yields an empty list and the adapter documents the degraded mode.
* Versions are self-reported from package metadata, never from model output.
* Confidences for barcode decodes are assigned by deterministic system rules
  (decode + checksum status), not by any model self-report.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai.vision.evidence_pipeline import (
    BarcodeCandidate,
    BarcodeFormat,
    EvidenceRegion,
    OCRToken,
    PackageRegionProposal,
)

logger = logging.getLogger(__name__)

MAX_OCR_TOKENS = 512
MAX_BARCODES = 64

DEFAULT_OCR_MODEL_DIR = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "models"
    / "vision"
    / "ocr"
    / "paddleocr"
    / "ppocrv4-ch"
)


def _default_ocr_model_dir() -> str | None:
    """Use the bundled PP-OCRv4 cache when no operator override is set."""
    configured = os.environ.get("HCT_OCR_MODEL_DIR")
    if configured:
        return configured
    return str(DEFAULT_OCR_MODEL_DIR) if DEFAULT_OCR_MODEL_DIR.is_dir() else None

# opencv-contrib decoded_type values -> evidence contract formats
BARCODE_FORMAT_MAP: dict[str, BarcodeFormat] = {
    "EAN_13": "EAN-13",
    "EAN_8": "EAN-8",
    "UPC_A": "UPC-A",
    "UPC_E": "UNKNOWN",
    "ITF": "ITF-14",
    "QR": "QR",
}


def gtin_checksum_valid(code: str) -> bool | None:
    """Validate the GS1 check digit for EAN-8/EAN-13/UPC-A/ITF-14 codes.

    Returns ``None`` when the value is not a plausible GTIN (letters, wrong
    length), so QR payloads and trace codes are not judged by a rule that
    does not apply to them.
    """
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return None
    digits = [int(ch) for ch in code]
    check = digits.pop()
    total = 0
    # GS1: weight 3 applies to positions counted from the right, starting at 1
    for position, digit in enumerate(reversed(digits)):
        total += digit * (3 if position % 2 == 0 else 1)
    return (10 - total % 10) % 10 == check


def quad_to_region(points: Any) -> EvidenceRegion | None:
    """Convert a 4-point polygon (paddle/opencv style) to a bounding region."""
    try:
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
    except (TypeError, ValueError, IndexError):
        return None
    x, y = max(min(xs), 0.0), max(min(ys), 0.0)
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    if width <= 0 or height <= 0:
        return None
    return EvidenceRegion(x=x, y=y, width=width, height=height, coordinate_space="pixel")


def worker_python() -> str:
    """Interpreter for engine worker subprocesses.

    Defaults to the current interpreter; ``HCT_VISION_WORKER_PYTHON`` lets a
    host process (e.g. the API env without paddle/torch) point workers at the
    adapter environment that has the heavy runtimes installed.
    """
    return os.environ.get("HCT_VISION_WORKER_PYTHON") or sys.executable


def _read_image_bgr(image_path: str | Path) -> Any | None:
    """Read an image as a BGR ndarray; safe for non-ASCII Windows paths.

    ``cv2.imread`` cannot open paths with Chinese characters on Windows, so
    the bytes are read with numpy first and decoded in memory.
    """
    try:
        import cv2
        import numpy as np

        data = np.fromfile(str(image_path), dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        logger.exception("LOCAL_VISION_IMAGE_READ_FAILED")
        return None


def _normalize_text(value: str) -> str:
    return "".join(value.split()).casefold()


def _is_duplicate(token: OCRToken, existing: list[OCRToken]) -> bool:
    """A crop token duplicates a full-image token when the normalized text
    matches and the region centers are close (or either has no region)."""
    text = _normalize_text(token.raw_value)
    for other in existing:
        if _normalize_text(other.raw_value) != text:
            continue
        if token.region is None or other.region is None:
            return True
        cx1 = token.region.x + token.region.width / 2
        cy1 = token.region.y + token.region.height / 2
        cx2 = other.region.x + other.region.width / 2
        cy2 = other.region.y + other.region.height / 2
        tolerance = max(20.0, other.region.height)
        if abs(cx1 - cx2) <= tolerance and abs(cy1 - cy2) <= tolerance:
            return True
    return False


# ── PaddleOCR (primary text channel) ────────────────────────────────────


@dataclass
class LocalPaddleOCR:
    """Full-image-first OCR built on the locally cached PP-OCRv4 models.

    PaddlePaddle and PyTorch cannot share one Windows process (their native
    DLLs conflict in either import order), so production OCR runs in the
    isolated ``_paddle_worker`` subprocess: one call OCRs the full image and
    all crops, and this class only parses the returned JSON.

    ``run_batch_fn(image_path, crop_rects) -> {"full": [...], "crops":
    [[...], ...]}`` may be injected for tests.
    """

    lang: str = field(default_factory=lambda: os.environ.get("HCT_OCR_LANG", "ch"))
    model_dir: str | None = field(default_factory=_default_ocr_model_dir)
    timeout_seconds: int = 300
    run_batch_fn: Callable[[str, list[dict]], dict] | None = None
    _version: str | None = field(default=None, repr=False)

    @property
    def available(self) -> bool:
        if self.run_batch_fn is not None:
            return True
        # a configured worker interpreter carries its own paddle install,
        # so the host process does not need the package importable
        if os.environ.get("HCT_VISION_WORKER_PYTHON"):
            return True
        return (
            importlib.util.find_spec("paddleocr") is not None
            and self.model_dir is not None
            and Path(self.model_dir).is_dir()
        )

    @property
    def engine_version(self) -> str:
        if self.run_batch_fn is not None:
            return "injected-test-ocr"
        if self._version is None:
            try:
                release = importlib.metadata.version("paddleocr")
            except importlib.metadata.PackageNotFoundError:
                release = "worker-env"
            self._version = f"paddleocr-{release}-ppocrv4-{self.lang}"
        return self._version

    def _run_batch(self, image_path: str, crop_rects: list[dict]) -> dict:
        if self.run_batch_fn is not None:
            return self.run_batch_fn(image_path, crop_rects)
        worker = Path(__file__).with_name("_paddle_worker.py")
        request = json.dumps(
            {
                "image_path": image_path,
                "lang": self.lang,
                "model_dir": self.model_dir,
                "crops": crop_rects,
            }
        )
        completed = subprocess.run(  # noqa: S603 (fixed worker script, no shell)
            [worker_python(), "-X", "utf8", str(worker)],
            input=request,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout_seconds,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"paddle worker exited {completed.returncode}: "
                f"{(completed.stderr or '')[-500:]}"
            )
        return json.loads(completed.stdout)

    @staticmethod
    def _lines_to_tokens(
        lines: list[Any],
        *,
        id_prefix: str,
        engine_version: str,
        offset: tuple[float, float] = (0.0, 0.0),
    ) -> list[OCRToken]:
        tokens: list[OCRToken] = []
        for line in lines or []:
            try:
                points, (text, confidence) = line[0], line[1]
            except (TypeError, ValueError, IndexError):
                continue
            if not isinstance(text, str) or not text.strip():
                continue
            region = quad_to_region(points)
            if region is not None and offset != (0.0, 0.0):
                region = EvidenceRegion(
                    x=region.x + offset[0],
                    y=region.y + offset[1],
                    width=region.width,
                    height=region.height,
                    coordinate_space="pixel",
                )
            tokens.append(
                OCRToken(
                    id=f"{id_prefix}{len(tokens) + 1}",
                    raw_value=text.strip(),
                    region=region,
                    confidence=min(max(float(confidence), 0.0), 1.0),
                    engine_version=engine_version,
                    language="zh-Hans" if "ch" in engine_version else "und",
                )
            )
        return tokens

    def recognize(
        self,
        image_path: str | Path,
        crop_regions: list[PackageRegionProposal] | None = None,
    ) -> list[OCRToken]:
        """OCR the full image first, then add non-duplicate tokens from the
        YOLO-proposed crops. Empty on failure (documented degraded mode)."""
        if not self.available:
            logger.info("LOCAL_OCR_UNAVAILABLE paddleocr not importable")
            return []
        proposals = crop_regions or []
        crop_rects = [
            {
                "x": proposal.region.x,
                "y": proposal.region.y,
                "width": proposal.region.width,
                "height": proposal.region.height,
            }
            for proposal in proposals
        ]
        try:
            batch = self._run_batch(str(image_path), crop_rects)
        except Exception:
            logger.exception("LOCAL_OCR_WORKER_FAILED")
            return []
        if not isinstance(batch, dict) or batch.get("error"):
            logger.warning("LOCAL_OCR_DEGRADED reason=%s", (batch or {}).get("error"))
            return []

        version = self.engine_version
        tokens = self._lines_to_tokens(
            batch.get("full") or [], id_prefix="ocr-", engine_version=version
        )
        crops_lines = batch.get("crops") or []
        # index-based pairing: zip(strict=) is unavailable on the 3.9 adapter env
        for crop_index, proposal in enumerate(proposals, 1):
            if crop_index > len(crops_lines):
                break
            crop_tokens = self._lines_to_tokens(
                crops_lines[crop_index - 1],
                id_prefix=f"ocr-c{crop_index}-",
                engine_version=version,
                offset=(proposal.region.x, proposal.region.y),
            )
            for token in crop_tokens:
                if not _is_duplicate(token, tokens):
                    tokens.append(token)
        return tokens[:MAX_OCR_TOKENS]


# ── OpenCV barcode / QR decoding (independent code channel) ─────────────


@dataclass
class LocalBarcodeDecoder:
    """Barcode/QR decoding via opencv-contrib; deterministic confidences.

    ``detect_fn(image_path) -> list[(text, type_name, points)]`` may be
    injected for tests.
    """

    detect_fn: Callable[[str], list[tuple[str, str, Any]]] | None = None
    _version: str | None = None

    @property
    def available(self) -> bool:
        if self.detect_fn is not None:
            return True
        try:
            import cv2

            return hasattr(cv2, "QRCodeDetector")
        except Exception:
            return False

    @property
    def decoder_version(self) -> str:
        if self.detect_fn is not None:
            return "injected-test-decoder"
        if self._version is None:
            try:
                import cv2

                self._version = f"opencv-contrib-{cv2.__version__}"
            except Exception:
                self._version = "opencv-unavailable"
        return self._version

    def _detect(self, image_path: str) -> list[tuple[str, str, Any]]:
        if self.detect_fn is not None:
            return self.detect_fn(image_path)
        import cv2

        image = _read_image_bgr(image_path)
        if image is None:
            return []
        results: list[tuple[str, str, Any]] = []
        barcode_detector_cls = getattr(getattr(cv2, "barcode", None), "BarcodeDetector", None)
        if barcode_detector_cls is not None:
            try:
                ok, infos, types, points = barcode_detector_cls().detectAndDecodeWithType(image)
                if ok:
                    for index, text in enumerate(infos):
                        if text:
                            point = points[index] if points is not None else None
                            results.append((text, str(types[index]), point))
            except Exception:
                logger.exception("LOCAL_BARCODE_1D_FAILED")
        try:
            ok, texts, points, _ = cv2.QRCodeDetector().detectAndDecodeMulti(image)
            if ok:
                for index, text in enumerate(texts):
                    if text:
                        point = points[index] if points is not None else None
                        results.append((text, "QR", point))
        except Exception:
            logger.exception("LOCAL_BARCODE_QR_FAILED")
        return results

    def decode(self, image_path: str | Path) -> list[BarcodeCandidate]:
        if not self.available:
            logger.info("LOCAL_BARCODE_UNAVAILABLE opencv not importable")
            return []
        try:
            detections = self._detect(str(image_path))
        except Exception:
            logger.exception("LOCAL_BARCODE_DETECT_FAILED")
            return []
        candidates: list[BarcodeCandidate] = []
        for text, type_name, points in detections[:MAX_BARCODES]:
            checksum = gtin_checksum_valid(text)
            candidates.append(
                BarcodeCandidate(
                    id=f"code-{len(candidates) + 1}",
                    raw_value=text,
                    region=quad_to_region(points) if points is not None else None,
                    # deterministic system rule, not a model self-report:
                    # checksum-verified decode 0.95, plain decode 0.8
                    confidence=0.95 if checksum else 0.8,
                    format=BARCODE_FORMAT_MAP.get(type_name, "UNKNOWN"),
                    decoder_version=self.decoder_version,
                    checksum_valid=checksum,
                    decode_valid=True,
                )
            )
        return candidates
